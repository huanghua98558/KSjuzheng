"""KS 账号 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from sqlalchemy import or_, select, func

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.core.tenant_scope import compute_tenant_scope
from app.models import KsAccount
from app.schemas.account import KsAccountPublic
from app.schemas.common import IdListRequest, make_pagination


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_ks_accounts(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ks-account:view")),
    page: int = 1,
    size: int = 20,
    keyword: str | None = None,
):
    scope = compute_tenant_scope(db, user)
    stmt = select(KsAccount)
    if not scope.unrestricted:
        stmt = stmt.where(KsAccount.organization_id.in_(scope.organization_ids))
    if keyword:
        like = f"%{keyword}%"
        stmt = stmt.where(
            or_(
                KsAccount.account_name.like(like),
                KsAccount.kuaishou_uid.like(like),
                KsAccount.device_code.like(like),
            )
        )
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    stmt = stmt.order_by(KsAccount.id.desc()).offset((page - 1) * size).limit(size)
    items = db.execute(stmt).scalars().all()
    return ok(
        {
            "items": [KsAccountPublic.model_validate(k).model_dump(mode="json") for k in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.delete("/{ks_id}")
async def delete_ks_account(
    ks_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ks-account:delete")),
):
    scope = compute_tenant_scope(db, user)
    k = db.get(KsAccount, ks_id)
    if not k:
        from app.core.errors import ResourceNotFound
        raise ResourceNotFound("KS 账号不存在")
    if not scope.unrestricted and (
        k.organization_id is None or k.organization_id not in scope.organization_ids
    ):
        from app.core.errors import AUTH_403, AuthError
        raise AuthError(AUTH_403, message="不在您的可见范围")
    db.delete(k)
    audit_request(request, db, user=user, action="delete", module="ks-account",
                  target_type="ks_account", target_id=ks_id)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))


@router.post("/batch-delete")
async def post_batch_delete(
    data: IdListRequest,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("ks-account:batch-delete")),
):
    scope = compute_tenant_scope(db, user)
    if not scope.unrestricted:
        stmt = select(KsAccount.id).where(
            KsAccount.organization_id.in_(scope.organization_ids)
        ).where(KsAccount.id.in_(data.ids))
        visible = set(db.execute(stmt).scalars().all())
        invalid = set(data.ids) - visible
        if invalid:
            from app.core.errors import AUTH_403, AuthError
            raise AuthError(AUTH_403, message="部分 KS 账号不在您的范围")
    affected = 0
    for kid in data.ids:
        k = db.get(KsAccount, kid)
        if k:
            db.delete(k)
            affected += 1
    audit_request(request, db, user=user, action="batch_delete", module="ks-account",
                  detail={"count": affected})
    db.commit()
    return ok({"success_count": affected, "failed_count": len(data.ids) - affected},
              trace_id=_trace(request))
