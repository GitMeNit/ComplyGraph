import tempfile
from pathlib import Path

from complygraph.config import Settings
from complygraph.scanner import engine
from complygraph.scanner.report import to_sarif

S = Settings.load()


def test_sample_app_findings():
    res = engine.scan_path(S.root / "examples/credit_scoring_service", S.rules_path)
    ids = {f.rule_id for f in res.findings}
    assert {"SEC-001", "GDPR-001", "GDPR-002", "GDPR-003", "DORA-001", "AIACT-001", "SR117-001"} <= ids
    assert res.tier == "critical"
    assert "sk-FAKEDEMO" not in "".join(f.snippet for f in res.findings)   # secrets never echoed in reports


def test_clean_project_is_low_risk():
    d = Path(tempfile.mkdtemp())
    (d / "main.py").write_text("def add(a, b):\n    return a + b\n")
    res = engine.scan_path(d, S.rules_path)
    assert res.tier == "low" and not [f for f in res.findings if f.severity in {"critical", "high"}]


def test_gating_prevents_false_positives():
    d = Path(tempfile.mkdtemp())      # no AI usage -> AI Act project-level rules must not fire
    (d / "main.py").write_text("def add(a, b):\n    return a + b\n")
    ids = {f.rule_id for f in engine.scan_path(d, S.rules_path).findings}
    assert not any(i.startswith("AIACT") for i in ids)


def test_sarif_shape():
    res = engine.scan_path(S.root / "examples/credit_scoring_service", S.rules_path)
    sarif = to_sarif(res)
    assert sarif["version"] == "2.1.0" and len(sarif["runs"][0]["results"]) == len(res.findings)


def test_regulation_filter():
    res = engine.scan_path(S.root / "examples/credit_scoring_service", S.rules_path, ["DORA"])
    assert res.findings and all("DORA" in f.regulation for f in res.findings)
