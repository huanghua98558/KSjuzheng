"""卡密管理 CLI — 生成 / 列表 / 作废 / 重置.

用法:
    python -m scripts.license_admin generate --plan pro --days 30 --count 5
    python -m scripts.license_admin list
    python -m scripts.license_admin revoke KS-A8F2-C7D4-9B1E-3F60
    python -m scripts.license_admin reset KS-A8F2-C7D4-9B1E-3F60   (清指纹, 允许换机)
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from app.core.db import init_engine, get_session_factory
from app.core.security import generate_license_key
from app.models import License


def cmd_generate(args):
    init_engine()
    Session = get_session_factory()
    out = []
    with Session() as db:
        for _ in range(args.count):
            key = generate_license_key()
            license = License(
                license_key=key,
                plan_tier=args.plan,
                max_accounts=args.max_accounts,
                issued_at=datetime.now(timezone.utc),
                expires_at=datetime.now(timezone.utc) + timedelta(days=args.days),
                status="unused",
            )
            db.add(license)
            out.append(key)
        db.commit()
    print(f"=== 生成 {len(out)} 张卡密 plan={args.plan} 有效 {args.days} 天 ===")
    for k in out:
        print(f"  {k}")


def cmd_list(args):
    init_engine()
    Session = get_session_factory()
    with Session() as db:
        stmt = select(License).order_by(License.id.desc())
        if args.status:
            stmt = stmt.where(License.status == args.status)
        rows = db.execute(stmt.limit(args.limit)).scalars().all()

        print(f"{'ID':<5} {'KEY':<28} {'PLAN':<8} {'STATUS':<10} "
              f"{'EXPIRES':<12} {'PHONE':<14} {'FP':<10}")
        print("-" * 100)
        for L in rows:
            fp = (L.device_fingerprint or "")[:8]
            phone = L.bound_phone or "-"
            print(f"{L.id:<5} {L.license_key:<28} {L.plan_tier:<8} "
                  f"{L.status:<10} {L.expires_at.strftime('%Y-%m-%d'):<12} {phone:<14} {fp:<10}")


def cmd_revoke(args):
    init_engine()
    Session = get_session_factory()
    with Session() as db:
        L = db.execute(
            select(License).where(License.license_key == args.key)
        ).scalar_one_or_none()
        if not L:
            print(f"卡密 {args.key} 不存在")
            sys.exit(2)
        L.status = "revoked"
        L.revoke_reason = args.reason
        db.commit()
        print(f"卡密 {args.key} 已作废. 原因: {args.reason}")


def cmd_reset(args):
    """清掉 device_fingerprint 让用户重新激活 (换机)."""
    init_engine()
    Session = get_session_factory()
    with Session() as db:
        L = db.execute(
            select(License).where(License.license_key == args.key)
        ).scalar_one_or_none()
        if not L:
            print(f"卡密 {args.key} 不存在")
            sys.exit(2)
        if L.status not in ("active", "unused"):
            print(f"卡密状态 {L.status}, 不能 reset")
            sys.exit(2)
        L.device_fingerprint = None
        L.status = "unused" if L.activated_at is None else "active"
        db.commit()
        print(f"卡密 {args.key} 已 reset, 用户可在新设备激活")


def main():
    ap = argparse.ArgumentParser(description="License admin")
    sub = ap.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("generate", help="批量生成卡密")
    g.add_argument("--plan", default="basic", choices=["basic", "pro", "team", "enterprise"])
    g.add_argument("--days", type=int, default=30)
    g.add_argument("--count", type=int, default=1)
    g.add_argument("--max-accounts", type=int, default=10)
    g.set_defaults(func=cmd_generate)

    L = sub.add_parser("list", help="列卡密")
    L.add_argument("--status", default=None,
                   choices=[None, "unused", "active", "expired", "revoked", "locked"])
    L.add_argument("--limit", type=int, default=50)
    L.set_defaults(func=cmd_list)

    R = sub.add_parser("revoke", help="作废卡密")
    R.add_argument("key")
    R.add_argument("--reason", default="manual revoke")
    R.set_defaults(func=cmd_revoke)

    rs = sub.add_parser("reset", help="清指纹, 允许换机")
    rs.add_argument("key")
    rs.set_defaults(func=cmd_reset)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
