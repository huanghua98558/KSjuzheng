"""软件账号 API.

15+ 端点, 全部装权限校验 + 审计.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.schemas.account import (
    AccountBatchAssign,
    AccountBatchAuthorize,
    AccountBatchCommission,
    AccountBatchSetGroup,
    AccountBatchStatus,
    AccountCreate,
    AccountListQuery,
    AccountPublic,
    AccountUpdate,
)
from app.schemas.common import IdListRequest, make_pagination
from app.services import account_service


router = APIRouter()


def _trace(request: Request) -> str:
    return getattr(request.state, "trace_id", "-")


# ============================================================
# List + CRUD
# ============================================================

@router.get("")
async def list_accounts(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:view")),
    page: int = 1,
    size: int = 20,
    keyword: str | None = None,
    org_id: int | None = None,
    group_id: int | None = None,
    assigned_user_id: int | None = None,
    status: str | None = None,
    sign_status: str | None = None,
    mcn_status: str | None = None,
    commission_min: float | None = None,
    commission_max: float | None = None,
    sort: str = "created_at.desc",
):
    q = AccountListQuery(
        page=page, size=size, keyword=keyword, org_id=org_id, group_id=group_id,
        assigned_user_id=assigned_user_id, status=status,
        sign_status=sign_status, mcn_status=mcn_status,
        commission_min=commission_min, commission_max=commission_max, sort=sort,
    )
    items, total = account_service.list_accounts(db, user, q)
    return ok(
        {
            "items": [AccountPublic.model_validate(a).model_dump(mode="json") for a in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/{account_id}")
async def get_account(
    account_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:view")),
):
    a = account_service.get_account(db, user, account_id)
    return ok(AccountPublic.model_validate(a).model_dump(mode="json"), trace_id=_trace(request))


@router.post("")
async def create_account(
    data: AccountCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:create")),
):
    a = account_service.create_account(db, user, data)
    audit_request(
        request, db, user=user, action="create", module="account",
        target_type="account", target_id=a.id,
        detail={"kuaishou_id": a.kuaishou_id, "organization_id": a.organization_id},
    )
    db.commit()
    db.refresh(a)
    return ok(AccountPublic.model_validate(a).model_dump(mode="json"), trace_id=_trace(request))


@router.put("/{account_id}")
async def update_account(
    account_id: int,
    data: AccountUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:edit")),
):
    a = account_service.update_account(db, user, account_id, data)
    audit_request(
        request, db, user=user, action="update", module="account",
        target_type="account", target_id=account_id,
        detail=data.model_dump(exclude_unset=True),
    )
    db.commit()
    db.refresh(a)
    return ok(AccountPublic.model_validate(a).model_dump(mode="json"), trace_id=_trace(request))


@router.delete("/{account_id}")
async def delete_account(
    account_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:delete")),
):
    account_service.delete_account(db, user, account_id)
    audit_request(
        request, db, user=user, action="delete", module="account",
        target_type="account", target_id=account_id,
    )
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))


# ============================================================
# Batch operations
# ============================================================

@router.post("/batch-authorize")
async def post_batch_authorize(
    data: AccountBatchAuthorize,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:batch-authorize")),
):
    result = account_service.batch_authorize(db, user, data.ids)
    audit_request(
        request, db, user=user, action="batch_authorize", module="account",
        target_type="account", target_id=",".join(str(i) for i in data.ids[:20]),
        detail={"count": len(data.ids), **result},
    )
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-revoke")
async def post_batch_revoke(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:batch-revoke")),
):
    result = account_service.batch_revoke(db, user, data.ids)
    audit_request(
        request, db, user=user, action="batch_revoke", module="account",
        target_type="account", target_id=",".join(str(i) for i in data.ids[:20]),
        detail={"count": len(data.ids), **result},
    )
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-assign")
async def post_batch_assign(
    data: AccountBatchAssign,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:assign-user")),
):
    result = account_service.batch_assign_user(db, user, data.ids, data.assigned_user_id)
    audit_request(
        request, db, user=user, action="batch_assign", module="account",
        detail={"count": len(data.ids), "assigned_user_id": data.assigned_user_id},
    )
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-set-group")
async def post_batch_set_group(
    data: AccountBatchSetGroup,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:set-group")),
):
    result = account_service.batch_set_group(db, user, data.ids, data.group_id)
    audit_request(request, db, user=user, action="batch_set_group", module="account",
                  detail={"count": len(data.ids), "group_id": data.group_id})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-set-status")
async def post_batch_status(
    data: AccountBatchStatus,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:batch-update-status")),
):
    result = account_service.batch_set_status(db, user, data.ids, data.status)
    audit_request(request, db, user=user, action="batch_set_status", module="account",
                  detail={"count": len(data.ids), "status": data.status})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-set-commission")
async def post_batch_set_commission(
    data: AccountBatchCommission,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:change-commission")),
):
    result = account_service.batch_set_commission(db, user, data.ids, data.commission_rate)
    audit_request(request, db, user=user, action="batch_set_commission", module="account",
                  detail={"count": len(data.ids), "rate": data.commission_rate})
    db.commit()
    return ok(result, trace_id=_trace(request))


@router.post("/batch-delete")
async def post_batch_delete(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:batch-delete")),
):
    result = account_service.batch_delete(db, user, data.ids)
    audit_request(request, db, user=user, action="batch_delete", module="account",
                  detail={"count": len(data.ids)})
    db.commit()
    return ok(result, trace_id=_trace(request))


# ============================================================
# 任务记录子页
# ============================================================

@router.get("/{account_id}/tasks")
async def get_account_tasks(
    account_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("account:view-task-records")),
    page: int = 1,
    size: int = 50,
):
    items, total = account_service.list_account_tasks(db, user, account_id, page, size)
    return ok(
        {
            "items": [
                {
                    "id": r.id, "task_type": r.task_type,
                    "drama_id": r.drama_id, "drama_name": r.drama_name,
                    "success": r.success, "duration_ms": r.duration_ms,
                    "error_message": r.error_message,
                    "created_at": r.created_at.isoformat() if r.created_at else None,
                }
                for r in items
            ],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )
