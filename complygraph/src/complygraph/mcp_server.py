"""MCP server exposing ComplyGraph's regulatory capabilities to ANY MCP client
(Claude Desktop, LangGraph agents via langchain-mcp-adapters, internal agent platforms).

Run:  python -m complygraph.mcp_server            (stdio)
"""
from __future__ import annotations

from .config import Settings
from . import tools

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as e:  # pragma: no cover
    raise SystemExit("Install the MCP SDK first: pip install 'mcp[cli]'") from e

mcp = FastMCP("complygraph-regulatory")
_S = Settings.load()


@mcp.tool()
def search_regulations(query: str, k: int = 4) -> list[dict]:
    """Search the approved regulatory corpus (GDPR, EU AI Act, DORA, SR 11-7, NIST AI RMF)."""
    return tools.search_regulations(query, k, _S)


@mcp.tool()
def scan_path(path: str, regulations: list[str] | None = None) -> dict:
    """Scan a code/config directory for regulatory control gaps; returns findings with legal references."""
    return tools.scan_path(path, regulations, _S)


@mcp.tool()
def list_rules() -> list[dict]:
    """List the declarative compliance rules (id, regulation, reference, severity)."""
    return tools.list_rules(_S)


@mcp.tool()
def verify_audit_chain() -> dict:
    """Verify integrity of the tamper-evident audit log hash chain."""
    return tools.verify_audit_chain(_S)


@mcp.resource("regulation://{name}")
def regulation(name: str) -> str:
    """Full text of a regulation summary by file stem, e.g. regulation://dora"""
    path = (_S.regulations_dir / f"{name}.md").resolve()
    if _S.regulations_dir.resolve() not in path.parents or not path.exists():
        raise ValueError(f"unknown regulation: {name}")
    return path.read_text()


@mcp.prompt()
def gap_assessment(system_description: str) -> str:
    """Prompt template for a structured regulatory gap assessment."""
    return (
        "Perform a regulatory gap assessment for the system below across GDPR, EU AI Act, DORA and SR 11-7. "
        "For each regulation: applicability, obligations, current-state gaps, remediation, owner. "
        "Cite sources from search_regulations as [R#] and never assert compliance.\n\n" + system_description
    )


if __name__ == "__main__":
    mcp.run()
