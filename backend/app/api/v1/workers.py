"""Worker 状态 + 手动触发 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import DbSession
from app.core.envelope import ok
from app.core.errors import RESOURCE_404, ResourceNotFound
from app.core.permissions import require_perm
from app.models import User
from app.workers.scheduler import get_worker_status, trigger_now


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("/status")
async def get_status(
    request: Request,
    user: User = Depends(require_perm("settings:view-basic")),
):
    return ok(get_worker_status(), trace_id=_trace(request))


@router.post("/{job_id}/trigger")
async def post_trigger(
    job_id: str,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("settings:edit-basic")),
):
    if not trigger_now(job_id):
        raise ResourceNotFound(f"未知 job_id: {job_id}")
    audit_request(request, db, user=user, action="trigger", module="worker",
                  target_type="job", target_id=job_id)
    db.commit()
    return ok({"job_id": job_id, "triggered": True}, trace_id=_trace(request))
