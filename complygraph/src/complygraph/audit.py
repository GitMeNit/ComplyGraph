"""Tamper-evident audit trail: append-only JSONL, SHA-256 hash chain, optional HMAC signing.

Each record commits to the previous record's hash, so any edit, deletion or reorder
breaks verification. With COMPLYGRAPH_AUDIT_HMAC_KEY set, an attacker with file access
cannot recompute a valid chain. In production also ship to WORM storage (S3 Object Lock).
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
from pathlib import Path

GENESIS = "0" * 64


def _canon(obj) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str).encode()


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._key = os.environ.get("COMPLYGRAPH_AUDIT_HMAC_KEY", "").encode() or None
        self._seq, self._prev = 0, GENESIS
        if self.path.exists():
            last = None
            with self.path.open() as f:
                for line in f:
                    if line.strip():
                        last = line
            if last:
                rec = json.loads(last)
                self._seq, self._prev = rec["seq"], rec["hash"]

    def _digest(self, body: dict) -> str:
        data = _canon(body)
        if self._key:
            return hmac.new(self._key, data, hashlib.sha256).hexdigest()
        return hashlib.sha256(data).hexdigest()

    def append(self, event: str, actor: str, payload: dict | None = None) -> dict:
        with self._lock:
            body = {
                "seq": self._seq + 1,
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                "event": event,
                "actor": actor,
                "payload": payload or {},
                "prev": self._prev,
            }
            rec = {**body, "hash": self._digest(body)}
            with self.path.open("a") as f:
                f.write(json.dumps(rec, sort_keys=True) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self._seq, self._prev = rec["seq"], rec["hash"]
            return rec

    def records(self) -> list[dict]:
        if not self.path.exists():
            return []
        with self.path.open() as f:
            return [json.loads(line) for line in f if line.strip()]

    def verify(self) -> dict:
        prev, n = GENESIS, 0
        for rec in self.records():
            n += 1
            body = {k: v for k, v in rec.items() if k != "hash"}
            if rec.get("prev") != prev:
                return {"ok": False, "records": n, "broken_at": rec.get("seq"), "reason": "chain link mismatch"}
            if rec.get("seq") != n:
                return {"ok": False, "records": n, "broken_at": rec.get("seq"), "reason": "sequence gap"}
            if not hmac.compare_digest(self._digest(body), rec.get("hash", "")):
                return {"ok": False, "records": n, "broken_at": rec.get("seq"), "reason": "hash mismatch (record altered)"}
            prev = rec["hash"]
        return {"ok": True, "records": n, "broken_at": None, "reason": None}
