"""Multi-agent orchestration graph.

START -> input_guard -> supervisor(router) -+-> research (self-corrective RAG) -----------------+
                  |                          +-> scanner (local/MCP tool) -> [research if assess] +-> risk
                  +-> END (blocked)          +-> ops (dynamic MCP tool routing) -----------------+
risk -> synthesize -> output_guard -> approval_gate -> END   (every node writes the audit chain)
"""
from __future__ import annotations

import hashlib
import re
import uuid
from typing import Optional, TypedDict

from .approvals import ApprovalStore
from .audit import AuditLog
from .config import Settings
from .graph_runtime import END, START, StateGraph
from .guardrails import Guardrails
from .llm import LLM, get_llm
from .rag.corrective import CorrectiveRAG
from .rag.retriever import get_retriever
from .scanner.report import to_markdown
from .scanner.engine import ScanResult, Finding
from .tools import Toolbox, build_toolbox

INTENTS = {"qa", "scan", "assess", "ops"}
ZERO_ARG_TOOLS = {"verify_audit_chain", "list_rules"}


class State(TypedDict, total=False):
    request: str
    user: str
    thread_id: str
    scan_path: Optional[str]
    clean_request: str
    intent: str
    rag: dict
    scan: dict
    ops: dict
    risk: dict
    draft: str
    answer: str
    status: str
    approval_id: Optional[str]
    violations: list
    trace: list


def heuristic_intent(text: str, has_path: bool) -> str:
    t = text.lower()
    if re.search(r"verify.*audit|audit.*(integrity|chain|log)|list.*(rules|tools)|available (tools|rules)", t):
        return "ops"
    if re.search(r"\b(assess|assessment|gap analysis|gap)\b", t):
        return "assess" if has_path else "qa"
    if re.search(r"\b(scan|violations?|audit (the )?(code|repo)|check (the )?(code|repo))\b", t):
        return "scan" if has_path else "qa"
    return "qa"


class Copilot:
    def __init__(self, settings: Settings | None = None, llm: LLM | None = None, toolbox: Toolbox | None = None):
        self.s = settings or Settings.load()
        self.llm = llm or get_llm(self.s)
        self.audit = AuditLog(self.s.audit_path)
        self.guard = Guardrails(self.s.policies_path)
        gov = self.guard.policy["governance"]
        self.gov = gov
        self.approvals = ApprovalStore(self.s.approvals_path, self.audit, gov.get("four_eyes", True))
        self.toolbox = toolbox or build_toolbox(self.s)
        self.crag = CorrectiveRAG(get_retriever(self.s), self.llm, self.s.crag_threshold, self.s.crag_max_attempts)
        self.graph = self._build()

    # ------------------------------------------------------------------ nodes
    def _t(self, s, msg):
        return (s.get("trace") or []) + [msg]

    def n_input_guard(self, s):
        r = self.guard.check_input(s["request"])
        sha = hashlib.sha256(s["request"].encode()).hexdigest()[:16]
        self.audit.append("request.received", s["user"], {
            "thread": s["thread_id"], "sha256": sha, "text": r.text[:200],
            "violations": r.violations, "redactions": r.redactions})
        if not r.allowed:
            return {"status": "blocked", "violations": r.violations, "trace": self._t(s, f"input_guard: BLOCKED {r.violations}"),
                    "answer": "Request blocked by input policy: " + ", ".join(r.violations)}
        return {"clean_request": r.text, "trace": self._t(s, f"input_guard: ok redactions={r.redactions}")}

    def n_supervisor(self, s):
        text, has_path = s["clean_request"], bool(s.get("scan_path"))
        intent = None
        if not self.llm.is_offline:
            try:
                out = self.llm.complete(
                    "Classify the request as exactly one of: qa, scan, assess, ops. qa=regulatory question; "
                    "scan=scan code for violations; assess=regulatory analysis plus code scan; ops=audit verification or listing rules/tools. "
                    "Output the single word.", text, max_tokens=5).strip().lower()
                intent = out if out in INTENTS else None
            except Exception:
                intent = None
        intent = intent or heuristic_intent(text, has_path)
        if intent in {"scan", "assess"} and not has_path:
            intent = "qa"
        self.audit.append("route", "supervisor", {"thread": s["thread_id"], "intent": intent})
        return {"intent": intent, "trace": self._t(s, f"supervisor: intent={intent}")}

    def n_research(self, s):
        question = s["clean_request"]
        scan = s.get("scan")
        if scan and scan.get("findings"):   # assess mode: ground the legal analysis in what the scan found
            titles = list(dict.fromkeys(f["title"] for f in scan["findings"]))[:6]
            question += ". Regulatory basis for: " + "; ".join(titles)
        res = self.crag.run(question)
        self.audit.append("rag.completed", "research_agent", {
            "thread": s["thread_id"], "attempts": res["attempts"], "confidence": res["confidence"],
            "abstained": res["abstained"], "sources": [r["chunk_id"] for r in res["refs"]]})
        return {"rag": res, "trace": self._t(
            s, f"research_agent: CRAG attempts={res['attempts']} confidence={res['confidence']} abstained={res['abstained']}")}

    def n_scanner(self, s):
        try:
            result = self.toolbox.call("scan_path", path=s["scan_path"])
        except Exception as e:
            self.audit.append("scan.failed", "scanner_agent", {"thread": s["thread_id"], "error": str(e)[:200]})
            return {"scan": {"error": str(e)}, "trace": self._t(s, f"scanner_agent: ERROR {e}")}
        self.audit.append("scan.completed", "scanner_agent", {
            "thread": s["thread_id"], "target": result["target"], "findings": len(result["findings"]),
            "tier": result["tier"], "score": result["score"]})
        return {"scan": result, "trace": self._t(s, f"scanner_agent: {len(result['findings'])} findings, tier={result['tier']}")}

    def n_ops(self, s):
        zero = Toolbox([t for t in self.toolbox.specs.values() if t.name in ZERO_ARG_TOOLS])
        tool = zero.route(s["clean_request"])
        if tool is None:
            return {"ops": {"error": "no matching tool"}, "trace": self._t(s, "ops_agent: no tool matched")}
        out = tool.fn()
        self.audit.append("ops.tool_call", "ops_agent", {"thread": s["thread_id"], "tool": tool.name, "server": tool.server})
        return {"ops": {"tool": tool.name, "server": tool.server, "result": out},
                "trace": self._t(s, f"ops_agent: routed to {tool.server}/{tool.name}")}

    def n_risk(self, s):
        scan, rag = s.get("scan") or {}, s.get("rag") or {}
        tier = scan.get("tier", "low") if "error" not in scan else "low"
        reasons = []
        if tier in self.gov["approval_required_tiers"]:
            reasons.append(f"scan risk tier {tier}")
        if rag.get("abstained") and self.gov.get("review_on_abstain", True):
            reasons.append("low-confidence retrieval (abstained)")
        risk = {"tier": tier, "needs_approval": bool(reasons), "reasons": reasons}
        self.audit.append("risk.assessed", "risk_agent", {"thread": s["thread_id"], **risk})
        return {"risk": risk, "trace": self._t(s, f"risk_agent: tier={tier} needs_approval={risk['needs_approval']}")}

    def n_synthesize(self, s):
        out = [f"# Compliance assessment\n**Request:** {s['clean_request']}\n"]
        rag, scan, ops = s.get("rag"), s.get("scan"), s.get("ops")
        if rag:
            out += ["## Regulatory analysis", rag["answer"], ""]
            if rag["refs"]:
                out += ["**Sources**"] + [f"- [R{r['ref']}] {r['regulation']} - {r['section']}" for r in rag["refs"]] + [""]
        if scan:
            out.append("## Technical control scan")
            if "error" in scan:
                out.append(f"Scan could not be completed: {scan['error']}")
            else:
                res = ScanResult(scan["target"], scan["files_scanned"], scan["rules_evaluated"],
                                 [Finding(**f) for f in scan["findings"]])
                out.append(to_markdown(res))
                actions, seen = [], set()
                for f in res.findings:
                    if f.rule_id not in seen and len(actions) < 5:
                        seen.add(f.rule_id)
                        actions.append(f"- **{f.rule_id}** ({f.severity}): {f.remediation}")
                if actions:
                    out += ["", "## Priority remediation"] + actions
            out.append("")
        if ops:
            out += ["## Operational result", f"Tool `{ops.get('server')}/{ops.get('tool')}`:", "```", str(ops.get("result", ops)), "```", ""]
        out.append(f"## Risk rating: {s['risk']['tier'].upper()}")
        if s["risk"]["reasons"]:
            out.append("Human approval required: " + "; ".join(s["risk"]["reasons"]))
        return {"draft": "\n".join(out), "trace": self._t(s, "synthesizer: draft composed")}

    def n_output_guard(self, s):
        rag = s.get("rag")
        valid = {r["ref"] for r in rag["refs"]} if rag else set()
        r = self.guard.check_output(s["draft"], valid, used_rag=bool(rag), abstained=bool(rag and rag["abstained"]))
        self.audit.append("guard.output", "output_guard", {"thread": s["thread_id"], "ok": r.allowed,
                                                           "violations": r.violations, "redactions": r.redactions})
        if not r.allowed:
            return {"status": "blocked", "violations": r.violations, "answer": "Response blocked by output policy: " + ", ".join(r.violations),
                    "trace": self._t(s, f"output_guard: BLOCKED {r.violations}")}
        return {"draft": r.text, "trace": self._t(s, "output_guard: ok")}

    def n_gate(self, s):
        risk = s["risk"]
        if risk["needs_approval"]:
            rag = s.get("rag") or {}
            aid = self.approvals.submit(s["user"], s["thread_id"], risk["tier"], "; ".join(risk["reasons"]), s["draft"],
                                        {"intent": s["intent"], "confidence": rag.get("confidence")})
            return {"status": "pending_approval", "approval_id": aid,
                    "answer": f"Output held for approval ({'; '.join(risk['reasons'])}). Approval id: {aid}.",
                    "trace": self._t(s, f"approval_gate: HELD id={aid}")}
        self.audit.append("response.released", s["user"], {"thread": s["thread_id"], "mode": "auto"})
        return {"status": "released", "answer": s["draft"], "trace": self._t(s, "approval_gate: auto-released")}

    # ------------------------------------------------------------------ wiring
    def _build(self):
        g = StateGraph(State)
        for name, fn in [("input_guard", self.n_input_guard), ("supervisor", self.n_supervisor),
                         ("research", self.n_research), ("scanner", self.n_scanner), ("ops", self.n_ops),
                         ("risk", self.n_risk), ("synthesize", self.n_synthesize),
                         ("output_guard", self.n_output_guard), ("gate", self.n_gate)]:
            g.add_node(name, fn)
        g.add_edge(START, "input_guard")
        g.add_conditional_edges("input_guard", lambda s: END if s.get("status") == "blocked" else "supervisor",
                                {END: END, "supervisor": "supervisor"})
        g.add_conditional_edges("supervisor", lambda s: {"qa": "research", "assess": "scanner", "scan": "scanner", "ops": "ops"}[s["intent"]],
                                {"research": "research", "scanner": "scanner", "ops": "ops"})
        g.add_conditional_edges("scanner", lambda s: "research" if s["intent"] == "assess" else "risk",
                                {"research": "research", "risk": "risk"})
        g.add_edge("research", "risk")
        g.add_edge("ops", "risk")
        g.add_edge("risk", "synthesize")
        g.add_edge("synthesize", "output_guard")
        g.add_conditional_edges("output_guard", lambda s: END if s.get("status") == "blocked" else "gate",
                                {END: END, "gate": "gate"})
        g.add_edge("gate", END)
        return g.compile()

    # ------------------------------------------------------------------ public API
    def ask(self, request: str, user: str = "anonymous", scan_path: str | None = None) -> dict:
        state = self.graph.invoke({"request": request, "user": user, "thread_id": uuid.uuid4().hex[:12],
                                   "scan_path": scan_path, "trace": []})
        return {k: state.get(k) for k in ("thread_id", "status", "answer", "intent", "risk", "rag", "scan",
                                          "approval_id", "violations", "trace")}

    def resume(self, approval_id: str, approver: str, approve: bool, comment: str = "") -> dict:
        rec = self.approvals.decide(approval_id, approver, approve, comment)
        if approve:
            self.audit.append("response.released", approver, {"thread": rec["thread_id"], "mode": "approved", "approval_id": approval_id})
            return {"status": "released", "answer": rec["draft"], "approval_id": approval_id}
        return {"status": "rejected", "answer": f"Rejected by {approver}: {comment}", "approval_id": approval_id}
