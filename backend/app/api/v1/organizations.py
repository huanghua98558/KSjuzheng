"""机构 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.models import User
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.schemas.common import make_pagination
from app.schemas.user import OrganizationCreate, OrganizationPublic, OrganizationUpdate
from app.services import org_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


@router.get("")
async def list_orgs(
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org:view")),
    page: int = 1,
    size: int = 20,
    keyword: str | None = None,
):
    items, total = org_service.list_orgs(db, user, page=page, size=size, keyword=keyword)
    return ok(
        {
            "items": [OrganizationPublic.model_validate(o).model_dump(mode="json") for o in items],
            "pagination": make_pagination(total, page, size).model_dump(),
        },
        trace_id=_trace(request),
    )


@router.get("/accessible")
async def list_accessible_orgs(
    request: Request,
    db: DbSession,
    user: CurrentUser,
):
    """所有人都能拿自己可访问的机构 (用于下拉选)."""
    items, _ = org_service.list_orgs(db, user, page=1, size=200)
    return ok(
        [
            {"id": o.id, "name": o.name, "org_code": o.org_code}
            for o in items
        ],
        trace_id=_trace(request),
    )


@router.get("/{org_id}")
async def get_org(
    org_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org:view")),
):
    o = org_service.get_org(db, user, org_id)
    return ok(OrganizationPublic.model_validate(o).model_dump(mode="json"),
              trace_id=_trace(request))


@router.post("")
async def post_org(
    data: OrganizationCreate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org:create")),
):
    o = org_service.create_org(db, user, data)
    audit_request(request, db, user=user, action="create", module="org",
                  target_type="org", target_id=o.id, detail={"name": o.name, "code": o.org_code})
    db.commit()
    db.refresh(o)
    return ok(OrganizationPublic.model_validate(o).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/{org_id}")
async def put_org(
    org_id: int,
    data: OrganizationUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org:edit")),
):
    o = org_service.update_org(db, user, org_id, data)
    audit_request(request, db, user=user, action="update", module="org",
                  target_type="org", target_id=org_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(o)
    return ok(OrganizationPublic.model_validate(o).model_dump(mode="json"),
              trace_id=_trace(request))


@router.delete("/{org_id}")
async def delete_org(
    org_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("org:delete")),
):
    org_service.delete_org(db, user, org_id)
    audit_request(request, db, user=user, action="delete", module="org",
                  target_type="org", target_id=org_id)
    db.commit()
    return ok({"deleted": True}, trace_id=_trace(request))
