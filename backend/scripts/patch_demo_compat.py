"""Patch demo_compat.py — 加 source 参数支持双轨表合并显示.

改动:
  1. _source_count: 不变 (caller 自己传 mcn_table 名)
  2. _source_member_list / _source_income_list: 加 source 参数 + UNION 逻辑
  3. _source_member_payload / _source_income_payload: 加 _src 透传
  4. 各 GET list router: 加 source 参数 + 调用时透传
"""
import os, sys, re, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_dual_source"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")

text = open(PATH, encoding="utf-8").read()
n_changes = 0


# ── Patch 1: _source_member_payload 加 _src ──
OLD_MP = '''def _source_member_payload(row: dict[str, Any], *, program: str) -> dict[str, Any]:'''
NEW_MP_PREFIX = '''def _source_member_payload(row: dict[str, Any], *, program: str) -> dict[str, Any]:'''
# 找 _source_member_payload 函数末尾的 return, 加 _src
m = re.search(r'(def _source_member_payload[^}]+?return\s*\{[^}]+?)(\}\s*\n\n)', text, re.S)
if m:
    body, end = m.group(1), m.group(2)
    if "_src" not in body:
        new_body = body.rstrip() + ',\n        "_src": row.get("_src"),\n    '
        text = text[:m.start()] + new_body + end + text[m.end():]
        print("  ✓ Patch 1a: _source_member_payload 加 _src")
        n_changes += 1


# ── Patch 2: _source_income_payload 加 _src ──
m = re.search(r'(def _source_income_payload[^}]+?return\s*\{[^}]+?)(\}\s*\n\n)', text, re.S)
if m:
    body, end = m.group(1), m.group(2)
    if "_src" not in body:
        new_body = body.rstrip() + ',\n        "_src": row.get("_src"),\n    '
        text = text[:m.start()] + new_body + end + text[m.end():]
        print("  ✓ Patch 1b: _source_income_payload 加 _src")
        n_changes += 1


# ── Patch 3: 改 _source_member_list ──
old_member_list = '''def _source_member_list(
    db: Session,
    user: CurrentUser,
    *,
    table: str,
    program: str,
    page: int,
    per_page: int,
    search: str | None = None,
    broker_name: str | None = None,
    sort_field: str = "total_amount",
'''

if old_member_list in text:
    # 加 source 参数到签名
    new_member_list = old_member_list.replace(
        'sort_field: str = "total_amount",\n',
        'sort_field: str = "total_amount",\n    source: str = "all",\n')
    text = text.replace(old_member_list, new_member_list)
    print("  ✓ Patch 2a: _source_member_list 签名加 source")
    n_changes += 1


# ── Patch 4: _source_member_list 函数体改成支持 source ──
# 找函数体最后的 SELECT 语句, 替换成双源
member_list_body = re.search(
    r'def _source_member_list\([^)]+\)\s*->[^:]+:\s*\n(.+?)\n    return \[_source_member_payload',
    text, re.S)
if member_list_body and "mcn_table" not in member_list_body.group(1):
    body = member_list_body.group(1)
    # 找原始 SELECT 部分 (db.execute(text(...)).mappings().all())
    # 替换为支持 source 的版本
    select_pat = re.search(
        r'(    total = _source_count\(db, table, where, params\)\s*\n'
        r'    sql_where = " AND "\.join\(where\) if where else "1=1"\s*\n'
        r'    rows = db\.execute\([^)]+?\.mappings\(\)\.all\(\)\s*\n)',
        body, re.S)
    if select_pat:
        old = select_pat.group(1)
        # 新版本:
        new = '''    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"

    if source == "self":
        total = _source_count(db, table, where, params)
        rows = db.execute(
            text(f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
                 f"ORDER BY {sort_field} DESC, id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    elif source == "mcn":
        total = _source_count(db, mcn_table, where, params)
        rows = db.execute(
            text(f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
                 f"ORDER BY {sort_field} DESC, id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    else:  # all
        total = (_source_count(db, table, where, params)
                 + _source_count(db, mcn_table, where, params))
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
                 f"ORDER BY {sort_field} DESC, id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
'''
        text = text.replace(old, new)
        print("  ✓ Patch 2b: _source_member_list 函数体改 UNION")
        n_changes += 1


# ── Patch 5: 改 _source_income_list ──
old_income_list_sig = '''def _source_income_list(
    db: Session,
    user: CurrentUser,
    *,
    table: str,
    program: str,
    page: int,
    per_page: int,
    task_name: str | None = None,
    org_column: str | None = "org_id",
'''
if old_income_list_sig in text:
    new_income_list_sig = old_income_list_sig.replace(
        'org_column: str | None = "org_id",\n',
        'org_column: str | None = "org_id",\n    source: str = "all",\n')
    text = text.replace(old_income_list_sig, new_income_list_sig)
    print("  ✓ Patch 3a: _source_income_list 签名加 source")
    n_changes += 1


# ── Patch 6: _source_income_list 函数体支持 source ──
income_body = re.search(
    r'def _source_income_list\([^)]+\)[^:]+:\s*\n(.+?)\n    return \[_source_income_payload',
    text, re.S)
if income_body and "mcn_table" not in income_body.group(1):
    body = income_body.group(1)
    select_pat = re.search(
        r'(    total = _source_count\(db, table, where, params\)\s*\n'
        r'    sql_where = " AND "\.join\(where\) if where else "1=1"\s*\n'
        r'    rows = db\.execute\([^)]+?\.mappings\(\)\.all\(\)\s*\n)',
        body, re.S)
    if select_pat:
        old = select_pat.group(1)
        new = '''    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"

    if source == "self":
        total = _source_count(db, table, where, params)
        rows = db.execute(
            text(f"SELECT *, '我的' AS _src FROM {table} WHERE {sql_where} "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    elif source == "mcn":
        total = _source_count(db, mcn_table, where, params)
        rows = db.execute(
            text(f"SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where} "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
    else:  # all
        total = (_source_count(db, table, where, params)
                 + _source_count(db, mcn_table, where, params))
        rows = db.execute(
            text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
                 f"UNION ALL "
                 f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
                 f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
            {**params, "limit": per_page, "offset": (page - 1) * per_page},
        ).mappings().all()
'''
        text = text.replace(old, new)
        print("  ✓ Patch 3b: _source_income_list 函数体改 UNION")
        n_changes += 1


# ── Patch 7: 各 router 加 source 参数 + 透传 ──
# 用 regex 找 router signatures 含 page_size 的, 加 source
patch_routes = [
    # 关键 list endpoints (SELECT 双轨表)
    "spark_members", "firefly_members", "fluorescent_members",
    "firefly_income", "spark_income", "fluorescent_income",
    "spark_archive", "spark_violation_photos", "spark_violation_dramas",
]

# 给每个 async def xxx(...) 函数签名末尾加 source 参数 (在最后一个参数前)
# 同时给 _source_xxx_list(...) 调用加 source=source
n_route_sig = 0
n_route_call = 0

# 找所有 _source_member_list/_source_income_list 调用, 在末尾加 source=source
for helper in ["_source_member_list", "_source_income_list"]:
    # 匹配 helper(...) 但末尾不是 source=source 的
    pat = re.compile(
        rf'({helper}\s*\(\s*\n[^)]*?(?<!source=source))\s*\n(\s*\))', re.S)
    matches = list(pat.finditer(text))
    for m in matches:
        before = m.group(1)
        end = m.group(2)
        # 在最后一个非空行后加 source=source
        if "source=" not in before:
            new_call = before.rstrip().rstrip(",") + ",\n            source=source," + "\n" + end
            text = text[:m.start()] + new_call + text[m.end():]
            n_route_call += 1

print(f"  ✓ Patch 4a: helper 调用加 source=source — {n_route_call} 处")
n_changes += n_route_call

# 给 router 的 async def 函数签名加 source: str = "all"
# 匹配模式: 含 _source_member_list 或 _source_income_list 调用的 async def
async_def_pat = re.compile(
    r'(@router\.get\([^)]+\)\s*\n'
    r'async def \w+\([^)]+?)(page_size: int \| None = None, size: int \| None = None[^)]*?)\)',
    re.S
)
for m in async_def_pat.finditer(text):
    sig_full = m.group(0)
    if "source: str" not in sig_full:
        # 在 ): 前加 source 参数
        new_sig = sig_full.replace(") ", ", source: str = \"all\")", 1)
        if new_sig == sig_full:
            new_sig = sig_full[:-1] + ', source: str = "all")'
        # 确保只改一次
        text = text.replace(sig_full, new_sig, 1)
        n_route_sig += 1

print(f"  ✓ Patch 4b: router 签名加 source — {n_route_sig} 处")
n_changes += n_route_sig

# 写回
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ 总改动: {n_changes} 项")

# 语法检查
ret = os.system(f"python3 -c 'import ast; ast.parse(open(\"{PATH}\").read())'")
if ret == 0:
    print("✓ AST 语法 OK")
else:
    print("✗ AST 语法错误! 请回滚")
    print(f"   恢复: cp {BACKUP} {PATH}")
    sys.exit(1)
