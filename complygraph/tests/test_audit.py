import tempfile
from pathlib import Path

from complygraph.audit import AuditLog


def test_chain_verifies_and_resumes():
    p = Path(tempfile.mkdtemp()) / "a.jsonl"
    a = AuditLog(p)
    for i in range(5):
        a.append("evt", "u", {"i": i})
    assert a.verify()["ok"]
    b = AuditLog(p)           # restart continues the chain
    b.append("evt", "u", {"i": 5})
    assert b.verify() == {"ok": True, "records": 6, "broken_at": None, "reason": None}


def test_tamper_detected():
    p = Path(tempfile.mkdtemp()) / "a.jsonl"
    a = AuditLog(p)
    for i in range(4):
        a.append("evt", "u", {"i": i})
    lines = p.read_text().splitlines()
    lines[1] = lines[1].replace('"i": 1', '"i": 99').replace('"i":1', '"i":99')
    p.write_text("\n".join(lines) + "\n")
    v = a.verify()
    assert not v["ok"] and v["broken_at"] == 2


def test_deletion_detected():
    p = Path(tempfile.mkdtemp()) / "a.jsonl"
    a = AuditLog(p)
    for i in range(4):
        a.append("evt", "u", {"i": i})
    lines = p.read_text().splitlines()
    del lines[1]
    p.write_text("\n".join(lines) + "\n")
    assert not a.verify()["ok"]
