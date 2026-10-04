"""Declarative regulatory scanner: rules.yaml (law -> control) evaluated over a code/config tree."""
from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass, asdict, field
from pathlib import Path

import yaml

from ..guardrails import redact

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".state", "dist", "build", ".mypy_cache"}
MAX_BYTES = 1_000_000
WEIGHTS = {"critical": 25, "high": 12, "medium": 5, "low": 1}


@dataclass
class Finding:
    rule_id: str
    title: str
    regulation: str
    reference: str
    severity: str
    path: str
    line: int
    snippet: str
    remediation: str

    def to_dict(self):
        return asdict(self)


@dataclass
class ScanResult:
    target: str
    files_scanned: int
    rules_evaluated: int
    findings: list = field(default_factory=list)

    @property
    def score(self) -> int:
        return min(100, sum(WEIGHTS[f.severity] for f in self.findings))

    @property
    def tier(self) -> str:
        sev = {f.severity for f in self.findings}
        if "critical" in sev or self.score >= 60:
            return "critical"
        if self.score >= 30:
            return "high"
        if self.score >= 10:
            return "medium"
        return "low"

    def by_regulation(self) -> dict:
        out: dict = {}
        for f in self.findings:
            for reg in f.regulation.split("/"):
                out[reg] = out.get(reg, 0) + 1
        return out

    def to_dict(self) -> dict:
        return {
            "target": self.target, "files_scanned": self.files_scanned, "rules_evaluated": self.rules_evaluated,
            "score": self.score, "tier": self.tier, "by_regulation": self.by_regulation(),
            "findings": [f.to_dict() for f in self.findings],
        }


def load_rules(rules_path: Path, regulations: list[str] | None = None):
    doc = yaml.safe_load(Path(rules_path).read_text())
    defaults = doc.get("defaults", {}).get("files", ["*"])
    rules = doc["rules"]
    for r in rules:
        r.setdefault("files", defaults)
    if regulations:
        want = {x.lower() for x in regulations}
        rules = [r for r in rules if want & {p.lower() for p in re.split(r"[/]", r["regulation"])}
                 or any(w in r["regulation"].lower() for w in want)]
    return rules


def _iter_files(root: Path):
    if root.is_file():
        yield root
        return
    for dp, dns, fns in os.walk(root):
        dns[:] = [d for d in dns if d not in SKIP_DIRS]
        for fn in fns:
            p = Path(dp) / fn
            try:
                if p.stat().st_size <= MAX_BYTES:
                    yield p
            except OSError:
                continue


def _read(p: Path):
    try:
        return p.read_text(errors="strict")
    except (UnicodeDecodeError, OSError):
        return None


def _matches(p: Path, globs) -> bool:
    return any(fnmatch.fnmatch(p.name, g) for g in globs)


def scan_path(path: str | Path, rules_path: Path, regulations: list[str] | None = None) -> ScanResult:
    root = Path(path).resolve()
    if not root.exists():
        raise FileNotFoundError(f"scan target not found: {path}")
    rules = load_rules(rules_path, regulations)
    base = root if root.is_dir() else root.parent
    files = [(p, t) for p in _iter_files(root) if (t := _read(p)) is not None]
    result = ScanResult(str(root), len(files), len(rules))

    def rel(p: Path) -> str:
        return str(p.relative_to(base))

    def add(rule, p, line, text):
        snippet, _ = redact(text.strip()[:160])
        result.findings.append(Finding(rule["id"], rule["title"], rule["regulation"], rule["reference"],
                                       rule["severity"], rel(p) if p else ".", line, snippet, rule["remediation"]))

    for rule in rules:
        scoped = [(p, t) for p, t in files if _matches(p, rule["files"])]
        rx = re.compile(rule["pattern"])
        kind = rule["type"]
        if kind == "pattern":
            for p, t in scoped:
                for i, line in enumerate(t.splitlines(), 1):
                    if rx.search(line):
                        add(rule, p, i, line)
        elif kind == "cooccur_missing":
            ab = re.compile(rule["absent"])
            for p, t in scoped:
                m = rx.search(t)
                if m and not ab.search(t):
                    ln = t.count("\n", 0, m.start()) + 1
                    add(rule, p, ln, t.splitlines()[ln - 1])
        elif kind == "project_missing":
            gate = re.compile(rule["applies_if"]) if rule.get("applies_if") else None
            code = [(p, t) for p, t in files if p.suffix in {".py", ".js", ".ts", ".java", ".go", ".tf", ".yaml", ".yml", ".json", ".md"}]
            applies = gate is None or any(gate.search(t) for _, t in code)
            if applies and code and not any(rx.search(t) for _, t in code):
                add(rule, None, 0, f"control not found in project (expected pattern: {rule['pattern'][:60]})")
        else:
            raise ValueError(f"unknown rule type {kind!r} in {rule['id']}")
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    result.findings.sort(key=lambda f: (order[f.severity], f.rule_id, f.path, f.line))
    return result
