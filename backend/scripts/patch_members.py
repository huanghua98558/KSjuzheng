"""Patch members.py to support `source` query param (双表合并显示)."""
import os, sys

PATH = "/opt/ksjuzheng/app/api/v1/members.py"
text_content = open(PATH, encoding="utf-8").read()

# ── Patch 1: 改 _source_members 函数 ──
OLD_FUNC = '''def _source_members(db, user, *, table: str, program: str, page: int, size: int, keyword: str | None):
    where = []
    params = {}
    if not user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = user.organization_id
    if keyword:
        where.append("(CAST(member_id AS CHAR) LIKE :kw OR member_name LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    sql_where = " AND ".join(where) if where else "1=1"
    total = int(db.execute(text(f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"), params).scalar_one())
    order_col = "id" if table == "spark_members" else "member_id"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY total_amount DESC, {order_col} DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": size, "offset": max(page - 1, 0) * size},
    ).mappings().all()
    return [_member_dict(row, program=program) for row in rows], total
'''

NEW_FUNC = '''def _source_members(db, user, *, table: str, program: str, page: int, size: int,
                     keyword: str | None, source: str = "all"):
    """双表查询 (老表 + mcn_xxx 镜像). source: all=合并 / self=老表 / mcn=镜像."""
    where = []
    params = {}
    if not user.is_superadmin:
        where.append("org_id = :org_id")
        params["org_id"] = user.organization_id
    if keyword:
        where.append("(CAST(member_id AS CHAR) LIKE :kw OR member_name LIKE :kw)")
        params["kw"] = f"%{keyword}%"
    sql_where = " AND ".join(where) if where else "1=1"
    order_col = "id" if table == "spark_members" else "member_id"
    mcn_table = f"mcn_{table}"

    if source == "self":
        count_sql = f"SELECT COUNT(*) FROM {table} WHERE {sql_where}"
        list_sql = (f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
                    f"ORDER BY total_amount DESC, {order_col} DESC "
                    f"LIMIT :limit OFFSET :offset")
    elif source == "mcn":
        count_sql = f"SELECT COUNT(*) FROM {mcn_table} WHERE {sql_where}"
        list_sql = (f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
                    f"ORDER BY total_amount DESC, {order_col} DESC "
                    f"LIMIT :limit OFFSET :offset")
    else:  # all = 合并
        count_sql = (f"SELECT (SELECT COUNT(*) FROM {table} WHERE {sql_where}) + "
                     f"(SELECT COUNT(*) FROM {mcn_table} WHERE {sql_where})")
        list_sql = (f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
                    f"UNION ALL "
                    f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
                    f"ORDER BY total_amount DESC, {order_col} DESC "
                    f"LIMIT :limit OFFSET :offset")

    total = int(db.execute(text(count_sql), params).scalar_one())
    rows = db.execute(
        text(list_sql),
        {**params, "limit": size, "offset": max(page - 1, 0) * size},
    ).mappings().all()
    return [_member_dict(row, program=program) for row in rows], total
'''

if OLD_FUNC not in text_content:
    print("ERR: 老 _source_members 函数没找到")
    sys.exit(1)
text_content = text_content.replace(OLD_FUNC, NEW_FUNC)
print("  ✓ Patch 1: _source_members 加 source 参数")

# ── Patch 2: _member_dict 加 _src 字段 ──
OLD_DICT_END = '''        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }'''
NEW_DICT_END = '''        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "_src": row["_src"] if "_src" in row.keys() else None,
    }'''
text_content = text_content.replace(OLD_DICT_END, NEW_DICT_END)
print("  ✓ Patch 2: _member_dict 加 _src 字段")

# ── Patch 3: 3 个路由签名加 source 参数 ──
sig_patches = [
    ('user: User = Depends(require_perm("firefly:view-monthly")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n):',
     'user: User = Depends(require_perm("firefly:view-monthly")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n    source: str = "all",\n):'),
    ('user: User = Depends(require_perm("spark:view")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n):',
     'user: User = Depends(require_perm("spark:view")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n    source: str = "all",\n):'),
    ('user: User = Depends(require_perm("fluorescent:view")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n):',
     'user: User = Depends(require_perm("fluorescent:view")),\n    page: int = 1, size: int = 50, keyword: str | None = None,\n    source: str = "all",\n):'),
]
n_sig = 0
for old, new in sig_patches:
    if old in text_content:
        text_content = text_content.replace(old, new)
        n_sig += 1
print(f"  ✓ Patch 3: 路由签名加 source — {n_sig}/3")

# ── Patch 4: 调用处加 source=source ──
call_patches = [
    ('_source_members(db, user, table="spark_members", program="spark", page=page, size=size, keyword=keyword)',
     '_source_members(db, user, table="spark_members", program="spark", page=page, size=size, keyword=keyword, source=source)'),
    ('_source_members(db, user, table="fluorescent_members", program="firefly", page=page, size=size, keyword=keyword)',
     '_source_members(db, user, table="fluorescent_members", program="firefly", page=page, size=size, keyword=keyword, source=source)'),
    ('_source_members(db, user, table="fluorescent_members", program="fluorescent", page=page, size=size, keyword=keyword)',
     '_source_members(db, user, table="fluorescent_members", program="fluorescent", page=page, size=size, keyword=keyword, source=source)'),
]
n_call = 0
for old, new in call_patches:
    if old in text_content:
        text_content = text_content.replace(old, new)
        n_call += 1
print(f"  ✓ Patch 4: 路由调用加 source — {n_call}/3")

open(PATH, "w", encoding="utf-8").write(text_content)
print("\n✓ 写回完成")
print("\n[语法检查]")
os.system(f"python3 -c 'import ast; ast.parse(open(\"{PATH}\").read()); print(\"  AST OK\")'")
