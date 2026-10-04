"""Retrievers. LlamaIndex vector retrieval when configured; dependency-free BM25 otherwise."""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import replace

from ..config import Settings
from .corpus import Chunk, load_corpus
from .text import terms


class BM25Retriever:
    name = "bm25"

    def __init__(self, chunks: list[Chunk], k1: float = 1.4, b: float = 0.75):
        self.chunks, self.k1, self.b = chunks, k1, b
        self.docs = [Counter(terms(f"{c.regulation} {c.section} {c.text}")) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = sum(self.lens) / max(1, len(self.lens))
        df = Counter(t for d in self.docs for t in d)
        n = len(chunks)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def search(self, query: str, k: int = 6) -> list[Chunk]:
        q = terms(query)
        scored = []
        for i, d in enumerate(self.docs):
            s = 0.0
            for t in q:
                if t in d:
                    tf = d[t]
                    s += self.idf[t] * tf * (self.k1 + 1) / (tf + self.k1 * (1 - self.b + self.b * self.lens[i] / self.avg))
            if s > 0:
                scored.append(replace(self.chunks[i], score=round(s, 4)))
        return sorted(scored, key=lambda c: -c.score)[:k]


class LlamaIndexRetriever:
    """Vector retrieval through LlamaIndex (pluggable embeddings/vector stores)."""
    name = "llamaindex"

    def __init__(self, chunks: list[Chunk], embed_model: str):
        from llama_index.core import VectorStoreIndex
        from llama_index.core.schema import TextNode

        self.by_id = {c.id: c for c in chunks}
        nodes = [
            TextNode(id_=c.id, text=f"{c.regulation} - {c.section}\n{c.text}",
                     metadata={"regulation": c.regulation, "section": c.section})
            for c in chunks
        ]
        self.index = VectorStoreIndex(nodes, embed_model=embed_model)

    def search(self, query: str, k: int = 6) -> list[Chunk]:
        hits = self.index.as_retriever(similarity_top_k=k).retrieve(query)
        return [replace(self.by_id[h.node.node_id], score=float(h.score or 0.0)) for h in hits]


_CACHE: dict = {}


def get_retriever(settings: Settings | None = None):
    s = settings or Settings.load()
    key = (str(s.regulations_dir), s.embed_model)
    if key not in _CACHE:
        chunks = load_corpus(s.regulations_dir)
        r = None
        if s.embed_model:
            try:
                r = LlamaIndexRetriever(chunks, s.embed_model)
            except Exception:  # llama-index missing or embeddings unavailable -> degrade to BM25
                r = None
        _CACHE[key] = r or BM25Retriever(chunks)
    return _CACHE[key]
