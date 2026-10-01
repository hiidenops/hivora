"""Audit trail routes (/api/v1/audit), admin only."""

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Query
from pydantic import BaseModel

from hivora.web.deps import Admin, RuntimeDep

router = APIRouter(tags=["audit"])


class AuditOut(BaseModel):
    id: int
    ts: datetime
    user_id: int | None
    username: str | None
    ip: str | None
    action: str
    target: str | None
    payload: dict[str, Any]
    result: str


@router.get("")
async def list_audit(
    _: Admin, rt: RuntimeDep, before_id: int | None = None,
    limit: int = Query(100, ge=1, le=1000),
) -> list[AuditOut]:  # fmt: skip
    return [AuditOut(id=a.id, ts=a.ts, user_id=a.user_id, username=a.username, ip=a.ip,
                     action=a.action, target=a.target, payload=a.payload, result=a.result)
            for a in await rt.audit.entries(before_id, limit)]  # fmt: skip


class ClearedOut(BaseModel):
    deleted: int


@router.delete("")
async def clear_audit(_: Admin, rt: RuntimeDep) -> ClearedOut:
    """Empty the trail, leaving one entry that says who emptied it and when."""
    return ClearedOut(deleted=await rt.audit.clear())
