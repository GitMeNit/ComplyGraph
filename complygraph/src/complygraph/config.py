from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    root: Path
    state_dir: Path
    regulations_dir: Path
    rules_path: Path
    policies_path: Path
    mcp_config_path: Path
    scan_roots: tuple
    llm_provider: str
    llm_model: str
    embed_model: str
    use_mcp: bool
    crag_threshold: float
    crag_max_attempts: int

    @property
    def audit_path(self) -> Path:
        return self.state_dir / "audit.jsonl"

    @property
    def approvals_path(self) -> Path:
        return self.state_dir / "approvals.json"

    @classmethod
    def load(cls, **overrides) -> "Settings":
        e = os.environ.get
        roots = e("COMPLYGRAPH_SCAN_ROOTS", str(ROOT / "examples")).split(os.pathsep)
        base = cls(
            root=ROOT,
            state_dir=Path(e("COMPLYGRAPH_STATE_DIR", str(ROOT / ".state"))),
            regulations_dir=ROOT / "data" / "regulations",
            rules_path=ROOT / "config" / "rules.yaml",
            policies_path=ROOT / "config" / "policies.yaml",
            mcp_config_path=ROOT / "config" / "mcp_servers.json",
            scan_roots=tuple(Path(r).resolve() for r in roots if r),
            llm_provider=e("COMPLYGRAPH_LLM_PROVIDER", "offline").lower(),
            llm_model=e("COMPLYGRAPH_LLM_MODEL", "claude-sonnet-5-5"),
            embed_model=e("COMPLYGRAPH_EMBED_MODEL", ""),
            use_mcp=e("COMPLYGRAPH_USE_MCP", "0") == "1",
            crag_threshold=float(e("COMPLYGRAPH_CRAG_THRESHOLD", "0.6")),
            crag_max_attempts=int(e("COMPLYGRAPH_CRAG_MAX_ATTEMPTS", "3")),
        )
        return replace(base, **overrides) if overrides else base
