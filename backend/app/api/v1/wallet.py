"""钱包 API."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.core.audit import audit_request
from app.core.deps import CurrentUser, DbSession
from app.core.envelope import ok
from app.core.permissions import require_perm
from app.models import User
from app.schemas.income import WalletPublic, WalletUpdate
from app.services import wallet_service


router = APIRouter()


def _trace(r: Request) -> str:
    return getattr(r.state, "trace_id", "-")


# ============================================================
# 自己的钱包
# ============================================================

@router.get("")
async def get_my_wallet(
    request: Request, db: DbSession, user: CurrentUser,
):
    w = wallet_service.get_my_wallet(db, user)
    db.commit()
    return ok(WalletPublic.model_validate(w).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("")
async def put_my_wallet(
    data: WalletUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("wallet:edit")),
):
    w = wallet_service.update_my_wallet(db, user, data)
    audit_request(request, db, user=user, action="update", module="wallet",
                  target_type="wallet", target_id=user.id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(w)
    return ok(WalletPublic.model_validate(w).model_dump(mode="json"),
              trace_id=_trace(request))


# ============================================================
# super_admin 看 / 改别人钱包
# ============================================================

@router.get("/users/{user_id}")
async def get_user_wallet(
    user_id: int,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:view-wallet-others")),
):
    w = wallet_service.get_user_wallet(db, user, user_id)
    audit_request(request, db, user=user, action="view", module="wallet",
                  target_type="wallet", target_id=user_id)
    db.commit()
    return ok(WalletPublic.model_validate(w).model_dump(mode="json"),
              trace_id=_trace(request))


@router.put("/users/{user_id}")
async def put_user_wallet(
    user_id: int,
    data: WalletUpdate,
    request: Request,
    db: DbSession,
    user: User = Depends(require_perm("user:view-wallet-others")),
):
    w = wallet_service.update_user_wallet(db, user, user_id, data)
    audit_request(request, db, user=user, action="update", module="wallet",
                  target_type="wallet", target_id=user_id,
                  detail=data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(w)
    return ok(WalletPublic.model_validate(w).model_dump(mode="json"),
              trace_id=_trace(request))
