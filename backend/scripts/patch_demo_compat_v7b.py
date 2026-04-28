"""V7b — /accounts 加 source=mcn 跨表分支.

ksjuzheng accounts 表无 mcn_accounts 镜像, 但 MCN 那边业务上同一概念是
mcn_kuaishou_accounts. source=mcn 时跨表查 + 字段映射成 accounts schema.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v7b"
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


patch("/accounts + source=mcn 跨表",
'''@router.get("/accounts")
async def accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    keyword: str | None = None,
    organization_id: int | None = None,
    org_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        rows, total, mcn_count = source_mysql_service.list_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            term=search or keyword,
            organization_id=organization_id or org_id,
            group_id=group_id,
            owner_id=owner_id,
        )
        data = {
            "accounts": [_account_payload(row) for row in rows],
            "total": total,
            "mcn_count": mcn_count,
            "normal_count": max(total - mcn_count, 0),
            "user_role": "super_admin" if user.is_superadmin else user.role,
        }
        return _success(data)''',
'''@router.get("/accounts")
async def accounts(
    db: DbSession,
    user: CurrentUser,
    page: int = 1,
    pageSize: int | None = None,
    page_size: int | None = None,
    size: int | None = None,
    search: str | None = None,
    keyword: str | None = None,
    organization_id: int | None = None,
    org_id: int | None = None,
    group_id: int | None = None,
    owner_id: int | None = None,
    source: str | None = None,
):
    if source_mysql_service.is_source_mysql(db):
        page, per_page = _page_size(page, page_size or pageSize, size)
        if (source or "").lower() == "mcn":
            # source=mcn: 跨表映射 mcn_kuaishou_accounts (无 mcn_accounts 镜像)
            where: list[str] = []
            params: dict[str, Any] = {}
            term = search or keyword
            if term:
                where.append("(account_name LIKE :kw OR kuaishou_uid LIKE :kw OR device_serial LIKE :kw)")
                params["kw"] = f"%{term}%"
            sql_where = " AND ".join(where) if where else "1=1"
            total = int(db.execute(text(f"SELECT COUNT(*) FROM mcn_kuaishou_accounts WHERE {sql_where}"), params).scalar_one())
            rows = db.execute(
                text(f"SELECT id, account_id, account_name, kuaishou_uid, kuaishou_name, device_serial, login_status, created_at, updated_at FROM mcn_kuaishou_accounts WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
            data = {
                "accounts": [
                    {
                        "id": r["id"],
                        "account_id": r["account_id"],
                        "account_name": r["account_name"] or r["kuaishou_name"],
                        "kuaishou_id": r["kuaishou_uid"],
                        "real_uid": r["kuaishou_uid"],
                        "kuaishou_uid": r["kuaishou_uid"],
                        "nickname": r["kuaishou_name"],
                        "device_serial": r["device_serial"],
                        "login_status": r["login_status"],
                        "created_at": _dt(r["created_at"]),
                        "updated_at": _dt(r["updated_at"]),
                        "_src": "MCN",
                    }
                    for r in rows
                ],
                "total": total,
                "mcn_count": total,
                "normal_count": 0,
                "user_role": "super_admin" if user.is_superadmin else user.role,
            }
            return _success(data, total=total)
        rows, total, mcn_count = source_mysql_service.list_accounts(
            db,
            viewer=user,
            page=page,
            per_page=per_page,
            term=search or keyword,
            organization_id=organization_id or org_id,
            group_id=group_id,
            owner_id=owner_id,
        )
        data = {
            "accounts": [{**_account_payload(row), "_src": "我的"} for row in rows],
            "total": total,
            "mcn_count": mcn_count,
            "normal_count": max(total - mcn_count, 0),
            "user_role": "super_admin" if user.is_superadmin else user.role,
        }
        return _success(data, total=total)''')


open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V7b 改动: {n}")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
