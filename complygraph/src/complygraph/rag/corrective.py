"""Self-corrective RAG (CRAG-style) as an explicit graph:

  retrieve -> grade -> (confident? generate : attempts left? rewrite -> retrieve : abstain)

Abstaining with 'insufficient evidence' is a feature in regulated settings: the system
prefers escalation to a human over a confident-sounding unsupported answer.
"""
from __future__ import annotations

import math
from typing import TypedDict

from ..graph_runtime import END, START, StateGraph
from ..llm import LLM
from .text import terms

GLOSSARY = [
    (("outage", "downtime", "went down", "disruption"), "ICT-related incident classification major incident reporting"),
    (("breach", "leak", "hacked", "data loss"), "personal data breach notification supervisory authority 72 hours"),
    (("vendor", "supplier", "cloud provider", "outsourc", "third party", "third-party", "api provider"),
     "ICT third-party risk register of information contractual exit strategy"),
    (("chatbot", "assistant", "genai", "gen ai", "llm"), "transparency obligations AI system interacting natural persons disclosure"),
    (("credit", "loan", "scoring", "hiring", "recruit"), "high-risk AI system Annex III creditworthiness"),
    (("model risk", "validation", "model governance"), "SR 11-7 model validation effective challenge model inventory"),
    (("automated decision", "auto approve", "auto-approve", "profiling"), "solely automated decision-making human intervention Article 22"),
    (("fine", "penalt", "sanction"), "administrative fines worldwide annual turnover"),
    (("logging", "logs", "traceab"), "record-keeping automatic recording of events logs"),
    (("pen test", "penetration", "resilience test"), "digital operational resilience testing threat-led penetration testing TLPT"),
    (("bias", "fairness", "discriminat"), "data governance bias examination training data"),
    (("dpia", "impact assessment"), "data protection impact assessment high risk processing"),
    (("transfer", "abroad", "us region", "outside the eu"), "international transfers adequacy standard contractual clauses"),
    (("oversight", "human in the loop", "override"), "human oversight natural persons override interrupt"),
]


class CragState(TypedDict, total=False):
    question: str
    query: str
    attempt: int
    chunks: list
    confidence: float
    best: dict
    history: list
    answer: str
    refs: list
    abstained: bool


def lexical_relevance(query: str, chunk) -> float:
    qt = set(terms(query))
    if not qt:
        return 0.0
    ct = set(terms(f"{chunk.regulation} {chunk.section} {chunk.text}"))
    need = max(2, math.ceil(len(qt) / 3))
    return min(1.0, len(qt & ct) / need)


class CorrectiveRAG:
    def __init__(self, retriever, llm: LLM, threshold: float = 0.6, max_attempts: int = 3, keep: float = 0.5):
        self.retriever, self.llm = retriever, llm
        self.threshold, self.max_attempts, self.keep = threshold, max_attempts, keep
        self.graph = self._build()

    # -- nodes -------------------------------------------------------------
    def _retrieve(self, s):
        return {"chunks": self.retriever.search(s["query"], k=6)}

    def _grade(self, s):
        chunks = s["chunks"]
        scores = self._llm_grades(s["question"], chunks) if not self.llm.is_offline else None
        if scores is None:
            scores = [lexical_relevance(s["question"] + " " + s["query"], c) for c in chunks]
        kept = sorted(((sc, c) for sc, c in zip(scores, chunks) if sc >= self.keep), key=lambda x: -x[0])
        top = [sc for sc, _ in kept[:3]]
        conf = round(sum(top) / 3, 3) if top else 0.0   # penalise thin evidence: always divide by 3
        best = s.get("best") or {"confidence": -1}
        if conf > best["confidence"]:
            top_score = max((c.score for c in chunks), default=0.0)
            # keep only evidence at least half as strong as the best hit, so weak sources never reach the answer
            strong = [c for _, c in kept[:4] if top_score <= 0 or c.score >= 0.5 * top_score]
            best = {"confidence": conf, "chunks": strong}
        hist = (s.get("history") or []) + [
            {"attempt": s["attempt"], "query": s["query"], "confidence": conf, "kept": len(kept)}
        ]
        return {"confidence": conf, "best": best, "history": hist}

    def _llm_grades(self, question, chunks):
        try:
            listing = "\n".join(f"{i}. {c.regulation} / {c.section}: {c.text[:300]}" for i, c in enumerate(chunks))
            out = self.llm.complete_json(
                "You grade retrieval relevance for regulatory questions. Score each passage 0..1.",
                f"Question: {question}\nPassages:\n{listing}\nReturn a JSON list of {len(chunks)} numbers.",
            )
            if isinstance(out, list) and len(out) == len(chunks):
                return [max(0.0, min(1.0, float(x))) for x in out]
        except Exception:
            pass
        return None

    def _rewrite(self, s):
        q = s["query"]
        if not self.llm.is_offline:
            try:
                new = self.llm.complete(
                    "Rewrite the question as a precise regulatory search query using formal legal terminology. Output only the query.",
                    f"Original: {s['question']}\nPrevious query: {q}\nTop regulations seen: "
                    + ", ".join(sorted({c.regulation for c in s['chunks']})),
                    max_tokens=100,
                ).strip()
                if new:
                    return {"query": new, "attempt": s["attempt"] + 1}
            except Exception:
                pass
        low = s["question"].lower()
        extra = [exp for trig, exp in GLOSSARY if any(t in low for t in trig) and exp not in q]
        return {"query": (q + " " + " ".join(extra)).strip(), "attempt": s["attempt"] + 1}

    def _generate(self, s):
        best = s["best"]
        chunks = best.get("chunks", [])
        abstained = best["confidence"] < self.threshold
        refs = [{"ref": i + 1, "chunk_id": c.id, "regulation": c.regulation, "section": c.section}
                for i, c in enumerate(chunks)]
        if abstained:
            answer = ("Insufficient evidence in the approved regulatory corpus to answer reliably "
                      f"(retrieval confidence {best['confidence']:.2f} < {self.threshold}). "
                      "Escalating for review by a subject-matter expert.")
            if chunks:
                answer += " Closest sources: " + "; ".join(f"{c.regulation} - {c.section} [R{i+1}]" for i, c in enumerate(chunks[:2]))
            return {"answer": answer, "refs": refs, "abstained": True}
        if not self.llm.is_offline:
            try:
                ctx = "\n\n".join(f"[R{i+1}] {c.regulation} - {c.section}\n{c.text}" for i, c in enumerate(chunks))
                answer = self.llm.complete(
                    "You are a regulatory analyst. Answer ONLY from the numbered sources. Cite as [R#] after every claim. "
                    "If sources are insufficient, say so. Never claim certainty of compliance.",
                    f"Question: {s['question']}\n\nSources:\n{ctx}",
                )
                if answer.strip():
                    return {"answer": answer.strip(), "refs": refs, "abstained": False}
            except Exception:
                pass
        parts = []
        for i, c in enumerate(chunks[:3]):
            sentence = c.text.split(". ")[0].rstrip(".")
            parts.append(f"- **{c.regulation} - {c.section}**: {sentence}. [R{i+1}]")
        return {"answer": "Based on the approved regulatory corpus:\n" + "\n".join(parts), "refs": refs, "abstained": False}

    # -- wiring ------------------------------------------------------------
    def _build(self):
        g = StateGraph(CragState)
        g.add_node("retrieve", self._retrieve)
        g.add_node("grade", self._grade)
        g.add_node("rewrite", self._rewrite)
        g.add_node("generate", self._generate)
        g.add_edge(START, "retrieve")
        g.add_edge("retrieve", "grade")
        g.add_conditional_edges("grade", self._decide, {"generate": "generate", "rewrite": "rewrite"})
        g.add_edge("rewrite", "retrieve")
        g.add_edge("generate", END)
        return g.compile()

    def _decide(self, s):
        if s["confidence"] >= self.threshold or s["attempt"] >= self.max_attempts:
            return "generate"
        return "rewrite"

    def run(self, question: str) -> dict:
        out = self.graph.invoke({"question": question, "query": question, "attempt": 1, "history": []})
        return {
            "answer": out["answer"], "refs": out["refs"], "abstained": out["abstained"],
            "confidence": out["best"]["confidence"], "attempts": out["attempt"], "history": out["history"],
        }
