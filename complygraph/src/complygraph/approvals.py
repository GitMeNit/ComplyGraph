"""Human-in-the-loop approval queue with maker-checker (four-eyes) enforcement."""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from .audit import AuditLog


class ApprovalStore:
    def __init__(self, path: Path, audit: AuditLog, four_eyes: bool = True):
        self.path, self.audit, self.four_eyes = Path(path), audit, four_eyes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        return json.loads(self.path.read_text()) if self.path.exists() else {}

    def _save(self, data: dict):
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(self.path)

    def submit(self, requester: str, thread_id: str, tier: str, reason: str, draft: str, meta: dict) -> str:
        with self._lock:
            data, aid = self._load(), uuid.uuid4().hex[:12]
            data[aid] = {"id": aid, "thread_id": thread_id, "requester": requester, "tier": tier, "reason": reason,
                         "draft": draft, "meta": meta, "status": "pending", "created": time.time(),
                         "decided_by": None, "comment": None}
            self._save(data)
        self.audit.append("approval.requested", requester, {"approval_id": aid, "tier": tier, "reason": reason})
        return aid

    def get(self, aid: str) -> dict:
        return self._load()[aid]

    def pending(self) -> list[dict]:
        return [a for a in self._load().values() if a["status"] == "pending"]

    def decide(self, aid: str, approver: str, approve: bool, comment: str = "") -> dict:
        with self._lock:
            data = self._load()
            rec = data.get(aid)
            if rec is None:
                raise KeyError(aid)
            if rec["status"] != "pending":
                raise ValueError(f"approval {aid} already {rec['status']}")
            if self.four_eyes and approver == rec["requester"]:
                self.audit.append("approval.denied_self_approval", approver, {"approval_id": aid})
                raise PermissionError("four-eyes: requester cannot approve their own output")
            rec.update(status="approved" if approve else "rejected", decided_by=approver, comment=comment,
                       decided=time.time())
            self._save(data)
        self.audit.append("approval.decided", approver,
                          {"approval_id": aid, "decision": rec["status"], "comment": comment[:200]})
        return rec
