"""V7c — /accounts source=mcn 改查 mcn_accounts VIEW (替代之前硬编码 mcn_kuaishou_accounts).

VIEW 已 schema 对齐 ksjuzheng.accounts, 所以查询字段自然匹配, 不需要复杂映射.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v7c"
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


# V7b 的硬编码 mcn_kuaishou_accounts 改为 mcn_accounts VIEW (字段已对齐)
patch("/accounts source=mcn 改用 mcn_accounts VIEW",
'''        if (source or "").lower() == "mcn":
            # source=mcn: 跨表映射 mcn_kuaishou_accounts (无 mcn_accounts 镜像)
            where: list[str] = []
            params: dict[str, Any] = {}
            term = search or keyword
            if term:
                where.append("(nickname LIKE :kw OR uid LIKE :kw OR device_serial LIKE :kw OR uid_real LIKE :kw)")
                params["kw"] = f"%{term}%"
            sql_where = " AND ".join(where) if where else "1=1"
            total = int(db.execute(text(f"SELECT COUNT(*) FROM mcn_kuaishou_accounts WHERE {sql_where}"), params).scalar_one())
            rows = db.execute(
                text(f"SELECT id, uid, uid_real, nickname, device_serial, account_status, organization_id, group_id, owner_id, created_at, updated_at FROM mcn_kuaishou_accounts WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
            data = {
                "accounts": [
                    {
                        "id": r["id"],
                        "account_id": r["uid"],
                        "account_name": r["nickname"],
                        "kuaishou_id": r["uid"],
                        "real_uid": r["uid_real"] or r["uid"],
                        "kuaishou_uid": r["uid"],
                        "nickname": r["nickname"],
                        "device_serial": r["device_serial"],
                        "login_status": r["account_status"] or "normal",
                        "organization_id": r["organization_id"],
                        "group_id": r["group_id"],
                        "owner_id": r["owner_id"],
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
            return _success(data, total=total)''',
'''        if (source or "").lower() == "mcn":
            # source=mcn: 直接查 mcn_accounts VIEW (字段已对齐 ksjuzheng accounts)
            # VIEW 由 mcn_kuaishou_accounts 映射, sync_daemon 自动维护数据
            where: list[str] = []
            params: dict[str, Any] = {}
            term = search or keyword
            if term:
                where.append("(nickname LIKE :kw OR kuaishou_id LIKE :kw OR device_serial LIKE :kw OR real_uid LIKE :kw)")
                params["kw"] = f"%{term}%"
            sql_where = " AND ".join(where) if where else "1=1"
            total = int(db.execute(text(f"SELECT COUNT(*) FROM mcn_accounts WHERE {sql_where}"), params).scalar_one())
            rows = db.execute(
                text(f"SELECT * FROM mcn_accounts WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
                {**params, "limit": per_page, "offset": (page - 1) * per_page},
            ).mappings().all()
            data = {
                "accounts": [
                    {
                        "id": r["id"],
                        "account_id": r["kuaishou_id"],
                        "account_name": r["nickname"],
                        "kuaishou_id": r["kuaishou_id"],
                        "real_uid": r["real_uid"],
                        "kuaishou_uid": r["kuaishou_id"],
                        "nickname": r["nickname"],
                        "device_serial": r["device_serial"],
                        "login_status": r["status"],
                        "mcn_status": r["mcn_status"],
                        "sign_status": r["sign_status"],
                        "commission_rate": float(r["commission_rate"] or 80.0),
                        "organization_id": r["organization_id"],
                        "group_id": r["group_id"],
                        "assigned_user_id": r["assigned_user_id"],
                        "remark": r["remark"],
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
            return _success(data, total=total)''')


open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V7c 改动: {n}")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
