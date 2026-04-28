"""V6c — 给 /ks-accounts (ORM/service) + /auth/users (service) 加 source=mcn 分支.

策略: source=mcn 时直接 SQL 查 mcn_xxx 表, 否则仍走 service (老表).
不破坏 service 抽象, 最少侵入.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v6c"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")
text = open(PATH, encoding="utf-8").read()
n = 0


def patch(label, old, new):
    global text, n
    cnt = text.count(old)
    if cnt == 0:
        print(f"  ✗ {label}: 没找到")
        return False
    if cnt > 1:
        print(f"  ✗ {label}: {cnt} 处 跳过")
        return False
    text = text.replace(old, new)
    print(f"  ✓ {label}")
    n += 1
    return True


# ── /ks-accounts ──
patch("/ks-accounts + source=mcn 分支",
'''@router.get("/ks-accounts")
async def ks_accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    keyword: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        rows, total = source_mysql_service.list_ks_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            keyword=keyword,
        )
        return _success(
            [_ks_account_payload(row) for row in rows],
            pagination={"total": total, "page": page, "page_size": per_page},
        )''',
'''@router.get("/ks-accounts")
async def ks_accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    keyword: str | None = None,
    source: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_kuaishou_accounts 镜像
            where: list[str] = []
            params: dict[str, Any] = {}
            if keyword:
                where.append("(account_name LIKE :kw OR kuaishou_uid LIKE :kw OR device_code LIKE :kw)")
                params["kw"] = f"%{keyword}%"
            rows, total = _dual_select(db, "kuaishou_accounts", where, params, page, per_page, "mcn")
            data = [{**dict(r), "_src": r.get("_src")} for r in rows]
            return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})
        rows, total = source_mysql_service.list_ks_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            keyword=keyword,
        )
        return _success(
            [{**_ks_account_payload(row), "_src": "我的"} for row in rows],
            total=total,
            pagination={"total": total, "page": page, "page_size": per_page},
        )''')


# ── /auth/users ──
# 注意: service.list_users 返 row 对象 + total. source=mcn 时跳过.
patch("/auth/users + source=mcn 分支",
'''@router.get("/auth/users")
async def users(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    role: str | None = None,
    is_active: int | None = None,
    organization_id: int | None = None,
    parent_user_id: int | None = None,
    has_parent: str | None = None,
    cooperation_type: str | None = None,
    include_all: int | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        explicit_page_size = pageSize or page_size or size
        if explicit_page_size is None or include_all:
            per_page = 100000
        else:
            page, per_page = _page_size(page, pageSize or page_size, size)
        rows, total = source_mysql_service.list_users(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            search=search,
            role=role,
            is_active=is_active,
            organization_id=organization_id,
            parent_user_id=parent_user_id,
            has_parent=has_parent,
        )
        data = [_user_payload(row) for row in rows]
        return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})''',
'''@router.get("/auth/users")
async def users(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    role: str | None = None,
    is_active: int | None = None,
    organization_id: int | None = None,
    parent_user_id: int | None = None,
    has_parent: str | None = None,
    cooperation_type: str | None = None,
    include_all: int | None = None,
    source: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        explicit_page_size = pageSize or page_size or size
        if explicit_page_size is None or include_all:
            per_page = 100000
        else:
            page, per_page = _page_size(page, pageSize or page_size, size)
        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_admin_users 镜像
            where: list[str] = []
            params: dict[str, Any] = {}
            if search:
                where.append("(username LIKE :s OR nickname LIKE :s OR phone LIKE :s)")
                params["s"] = f"%{search}%"
            if role:
                where.append("role = :role")
                params["role"] = role
            if is_active is not None:
                where.append("is_active = :is_active")
                params["is_active"] = int(is_active)
            rows, total = _dual_select(db, "admin_users", where, params, page, per_page, "mcn")
            data = [{**dict(r), "_src": r.get("_src")} for r in rows]
            return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})
        rows, total = source_mysql_service.list_users(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            search=search,
            role=role,
            is_active=is_active,
            organization_id=organization_id,
            parent_user_id=parent_user_id,
            has_parent=has_parent,
        )
        data = [{**_user_payload(row), "_src": "我的"} for row in rows]
        return _success(data, total=total, pagination={"total": total, "page": page, "page_size": per_page})''')


open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V6c 改动: {n} 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
