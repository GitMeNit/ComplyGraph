from __future__ import annotations

from .engine import ScanResult

LEVEL = {"critical": "error", "high": "error", "medium": "warning", "low": "note"}


def to_markdown(res: ScanResult, limit: int = 25) -> str:
    lines = [f"**Risk tier: {res.tier.upper()}** (score {res.score}/100) - {len(res.findings)} findings "
             f"across {res.files_scanned} files, {res.rules_evaluated} rules."]
    if res.by_regulation():
        lines.append("By regulation: " + ", ".join(f"{k}: {v}" for k, v in sorted(res.by_regulation().items())))
    if res.findings:
        lines += ["", "| Sev | Rule | Reference | Location | Remediation |", "|---|---|---|---|---|"]
        for f in res.findings[:limit]:
            loc = f"{f.path}:{f.line}" if f.line else "project-level"
            lines.append(f"| {f.severity} | {f.rule_id} | {f.reference} | {loc} | {f.remediation} |")
        if len(res.findings) > limit:
            lines.append(f"\n_{len(res.findings) - limit} more findings omitted; see JSON/SARIF export._")
    return "\n".join(lines)


def to_sarif(res: ScanResult) -> dict:
    rules, seen = [], set()
    for f in res.findings:
        if f.rule_id not in seen:
            seen.add(f.rule_id)
            rules.append({"id": f.rule_id, "name": f.title, "shortDescription": {"text": f.title},
                          "help": {"text": f.remediation},
                          "properties": {"regulation": f.regulation, "reference": f.reference}})
    results = [{
        "ruleId": f.rule_id, "level": LEVEL[f.severity],
        "message": {"text": f"{f.title} ({f.reference}). {f.remediation}"},
        "locations": [{"physicalLocation": {"artifactLocation": {"uri": f.path},
                                            "region": {"startLine": max(1, f.line)}}}],
    } for f in res.findings]
    return {"version": "2.1.0", "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
            "runs": [{"tool": {"driver": {"name": "ComplyGraph", "version": "0.1.0", "rules": rules}}, "results": results}]}
