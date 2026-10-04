# Architecture notes

* **Single source of truth for tools** - `tools.py` functions back both the in-process toolbox and the MCP server, so behaviour is identical locally and over MCP.
* **Router pattern** - the supervisor picks a *workflow* (qa / scan / assess / ops); `Toolbox.route()` picks a *tool* by ranking registered tool descriptions. Adding an MCP server adds routable tools with no code change.
* **Self-corrective RAG** - `rag/corrective.py` is itself a graph: retrieve -> grade -> (generate | rewrite -> retrieve). It keeps the best attempt, caps retries, and abstains below threshold. Offline grading is lexical coverage; online grading is an LLM scoring call with lexical fallback.
* **LangGraph + LlamaIndex** - LangGraph owns control flow and state; LlamaIndex is used strictly as a retriever behind `search(query, k)`, so vector stores/embeddings can change without touching agents.
* **Deterministic enforcement** - input/output guardrails, approval policy, and scanner never call an LLM. LLMs only classify intent, grade/rewrite queries, and draft prose; all have deterministic fallbacks.
* **Approvals are not LangGraph interrupts** by design: the graph terminates with `pending_approval` and `resume()` completes later. This survives process restarts and works identically with or without LangGraph. Swap to `interrupt()` + a checkpointer if you prefer in-graph pause semantics.
