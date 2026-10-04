"""FastAPI service: authenticated, role-based access to the compliance copilot.

Roles: analyst (ask/scan), approver (decide approvals), auditor (read audit). Keys come from
COMPLYGRAPH_API_KEYS="key:user:role,..." - in production front this with your SSO/API gateway.
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from . import tools
from .config import Settings
from .copilot import Copilot
from .scanner.engine import Finding, ScanResult
from .scanner.report import to_sarif

app = FastAPI(title="ComplyGraph", version="0.1.0")
ROLE_RANK = {"analyst": 1, "auditor": 1, "approver": 2, "admin": 3}


@lru_cache
def copilot() -> Copilot:
    return Copilot(Settings.load())


@lru_cache
def _keys() -> dict:
    raw = os.environ.get("COMPLYGRAPH_API_KEYS", "dev-analyst:alice:analyst,dev-approver:bob:approver,dev-auditor:carol:auditor")
    out = {}
    for item in filter(None, raw.split(",")):
        key, user, role = item.split(":")
        out[key] = {"user": user, "role": role}
    return out


def principal(x_api_key: str = Header(...)) -> dict:
    p = _keys().get(x_api_key)
    if not p:
        raise HTTPException(401, "invalid API key")
    return p


def require(*roles: str):
    def dep(p: dict = Depends(principal)) -> dict:
        if p["role"] not in roles and p["role"] != "admin":
            raise HTTPException(403, f"role '{p['role']}' not permitted")
        return p
    return dep


class AskBody(BaseModel):
    request: str = Field(min_length=3, max_length=8000)
    scan_path: Optional[str] = None


class DecisionBody(BaseModel):
    approve: bool
    comment: str = ""


@app.get("/healthz")
def healthz():
    c = copilot()
    return {"status": "ok", "llm": c.llm.name, "retriever": c.crag.retriever.name, "tools": c.toolbox.describe()}


@app.post("/v1/assess")
def assess(body: AskBody, p: dict = Depends(require("analyst"))):
    if body.scan_path:
        try:
            tools.allowed_scan_path(body.scan_path, copilot().s)
        except PermissionError as e:
            raise HTTPException(403, str(e))
    return copilot().ask(body.request, p["user"], body.scan_path)


@app.post("/v1/scan/sarif")
def scan_sarif(body: AskBody, p: dict = Depends(require("analyst"))):
    if not body.scan_path:
        raise HTTPException(422, "scan_path required")
    try:
        res = tools.scan_path(body.scan_path, settings=copilot().s)
    except PermissionError as e:
        raise HTTPException(403, str(e))
    return to_sarif(ScanResult(res["target"], res["files_scanned"], res["rules_evaluated"],
                               [Finding(**f) for f in res["findings"]]))


@app.get("/v1/approvals")
def pending(p: dict = Depends(require("approver"))):
    return [{k: a[k] for k in ("id", "requester", "tier", "reason", "created")} for a in copilot().approvals.pending()]


@app.get("/v1/approvals/{aid}")
def approval(aid: str, p: dict = Depends(require("approver"))):
    try:
        return copilot().approvals.get(aid)
    except KeyError:
        raise HTTPException(404, "unknown approval")


@app.post("/v1/approvals/{aid}")
def decide(aid: str, body: DecisionBody, p: dict = Depends(require("approver"))):
    try:
        return copilot().resume(aid, p["user"], body.approve, body.comment)
    except KeyError:
        raise HTTPException(404, "unknown approval")
    except PermissionError as e:
        raise HTTPException(403, str(e))
    except ValueError as e:
        raise HTTPException(409, str(e))


@app.get("/v1/audit/verify")
def audit_verify(p: dict = Depends(require("auditor", "approver"))):
    return copilot().audit.verify()


@app.get("/v1/audit")
def audit_tail(limit: int = 50, p: dict = Depends(require("auditor"))):
    return copilot().audit.records()[-min(limit, 500):]
