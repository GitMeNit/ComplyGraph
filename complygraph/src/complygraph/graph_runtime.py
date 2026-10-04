"""Thin graph runtime.

Uses LangGraph when installed. Otherwise falls back to a minimal in-process
implementation of the same API subset (add_node / add_edge /
add_conditional_edges / compile / invoke) so the whole system runs and is
testable in air-gapped environments and CI without heavyweight dependencies.
"""
from __future__ import annotations

try:  # pragma: no cover - exercised only when langgraph is installed
    from langgraph.graph import END, START, StateGraph

    HAS_LANGGRAPH = True
except ImportError:
    HAS_LANGGRAPH = False
    START, END = "__start__", "__end__"

    class StateGraph:  # type: ignore[no-redef]
        def __init__(self, state_schema=None):
            self.nodes, self.edges, self.cond = {}, {}, {}

        def add_node(self, name, fn):
            self.nodes[name] = fn

        def add_edge(self, src, dst):
            self.edges[src] = dst

        def add_conditional_edges(self, src, fn, mapping=None):
            self.cond[src] = (fn, mapping)

        def compile(self, **_kw):
            return _Compiled(self)

    class _Compiled:
        MAX_STEPS = 200

        def __init__(self, g):
            self.g = g

        def invoke(self, state, config=None):
            state, cur = dict(state), self.g.edges[START]
            for _ in range(self.MAX_STEPS):
                if cur == END:
                    return state
                state.update(self.g.nodes[cur](state) or {})
                if cur in self.g.cond:
                    fn, mapping = self.g.cond[cur]
                    key = fn(state)
                    cur = mapping[key] if mapping else key
                else:
                    cur = self.g.edges[cur]
            raise RuntimeError("graph exceeded MAX_STEPS (possible cycle)")
