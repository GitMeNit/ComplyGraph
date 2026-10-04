"""Tool layer shared by the in-process toolbox AND the MCP server (single source of truth).

`Toolbox.route()` is the dynamic tool router: it ranks every registered tool (local or MCP)
against the request, so new MCP servers become usable without code changes.
"""
from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .audit import AuditLog
from .config import Settings
from .rag.retriever import get_retriever
from .rag.text import terms
from .scanner import engine


# ----- pure tool functions ---------------------------------------------------
def allowed_scan_path(path: str, settings: Settings) -> Path:
    """Path-traversal guard: API/MCP callers may only scan inside configured roots."""
    p = Path(path).resolve()
    if not any(p == r or r in p.parents for r in settings.scan_roots):
        raise PermissionError(f"path outside allowed scan roots: {path}")
    return p


def search_regulations(query: str, k: int = 4, settings: Settings | None = None) -> list[dict]:
    """Search the approved regulatory corpus (GDPR, EU AI Act, DORA, SR 11-7, NIST AI RMF)."""
    s = settings or Settings.load()
    return [c.to_dict() for c in get_retriever(s).search(query, k)]


def scan_path(path: str, regulations: list[str] | None = None, settings: Settings | None = None) -> dict:
    """Scan a code/config directory for regulatory control gaps; returns findings with legal references."""
    s = settings or Settings.load()
    return engine.scan_path(allowed_scan_path(path, s), s.rules_path, regulations).to_dict()


def list_rules(settings: Settings | None = None) -> list[dict]:
    """List the declarative compliance rules (id, regulation, reference, severity)."""
    s = settings or Settings.load()
    return [{k: r[k] for k in ("id", "title", "regulation", "reference", "severity")}
            for r in engine.load_rules(s.rules_path)]


def verify_audit_chain(settings: Settings | None = None) -> dict:
    """Verify integrity of the tamper-evident audit log hash chain."""
    s = settings or Settings.load()
    return AuditLog(s.audit_path).verify()


# ----- toolbox + router --------------------------------------------------------
@dataclass
class ToolSpec:
    name: str
    description: str
    server: str
    fn: Callable


class Toolbox:
    def __init__(self, specs: list[ToolSpec]):
        self.specs = {t.name: t for t in specs}

    def route(self, query: str, min_overlap: int = 1) -> ToolSpec | None:
        q = set(terms(query))
        best, best_score = None, 0
        for t in self.specs.values():
            score = len(q & set(terms(f"{t.name.replace('_', ' ')} {t.description}")))
            if score > best_score:
                best, best_score = t, score
        return best if best_score >= min_overlap else None

    def call(self, name: str, **kwargs):
        return self.specs[name].fn(**kwargs)

    def describe(self) -> list[dict]:
        return [{"name": t.name, "server": t.server, "description": t.description} for t in self.specs.values()]


def local_toolbox(settings: Settings) -> Toolbox:
    fns = [search_regulations, scan_path, list_rules, verify_audit_chain]
    specs = []
    for fn in fns:
        def bound(_fn=fn, **kw):
            return _fn(settings=settings, **kw)
        specs.append(ToolSpec(fn.__name__, (fn.__doc__ or "").strip(), "local", bound))
    return Toolbox(specs)


def _coerce(result):
    """MCP adapters return str or a list of content blocks; normalise to Python objects."""
    if isinstance(result, list):
        result = "".join(b.get("text", "") if isinstance(b, dict) else str(b) for b in result)
    if isinstance(result, str):
        try:
            return json.loads(result)
        except ValueError:
            return result
    return result


def mcp_toolbox(settings: Settings) -> Toolbox:
    """Discover tools from every server in config/mcp_servers.json (langchain-mcp-adapters)."""
    from langchain_mcp_adapters.client import MultiServerMCPClient

    cfg = json.loads(settings.mcp_config_path.read_text())
    client = MultiServerMCPClient(cfg)
    tools = asyncio.run(client.get_tools())
    specs = []
    for t in tools:
        def call(_t=t, **kw):
            return _coerce(asyncio.run(_t.ainvoke(kw)))
        specs.append(ToolSpec(t.name, t.description or "", "mcp", call))
    return Toolbox(specs)


def build_toolbox(settings: Settings) -> Toolbox:
    if settings.use_mcp:
        try:
            return mcp_toolbox(settings)
        except Exception as e:  # MCP unavailable -> fail safe to in-process tools, never fail open on policy
            print(f"[complygraph] MCP unavailable ({e}); using local tools")
    return local_toolbox(settings)
