"""Patch demo_compat.py — 简化版 (V2).

策略:
  只改 2 个 helper, 让它们默认 source='all' 返回合并数据.
  Router 不改 — 调 helper 时不传 source, 自动用默认值, 返回合并数据.

  前端如果想要筛选, 后续单独 patch 个别 router 加 source 参数.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v2"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")

text = open(PATH, encoding="utf-8").read()
n = 0

# ── Patch 1: _source_member_list 函数体 (在 sql_where 之后, 改 SQL 为 UNION) ──
# 找老的整段 SQL (从 sql_where 到 .all())
OLD_MEMBER = '''    sql_where = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY {sort_field} DESC, id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total'''

NEW_MEMBER = '''    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    # 双轨合并: 老表 + mcn_xxx 镜像
    total = total + _source_count(db, mcn_table, where, params)
    rows = db.execute(
        text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
             f"UNION ALL "
             f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
             f"ORDER BY {sort_field} DESC, id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total'''

if OLD_MEMBER in text:
    text = text.replace(OLD_MEMBER, NEW_MEMBER)
    print("  ✓ Patch 1: _source_member_list → 合并查询")
    n += 1
else:
    print("  ✗ Patch 1: 没找到 _source_member_list 的目标 SQL")

# ── Patch 2: _source_income_list ──
OLD_INCOME = '''    total = _source_count(db, table, where, params)
    sql_where = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_income_payload(dict(row), program=program) for row in rows], total'''

NEW_INCOME = '''    total = _source_count(db, table, where, params)
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    total = total + _source_count(db, mcn_table, where, params)
    rows = db.execute(
        text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
             f"UNION ALL "
             f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
             f"ORDER BY id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_income_payload(dict(row), program=program) for row in rows], total'''

if OLD_INCOME in text:
    text = text.replace(OLD_INCOME, NEW_INCOME)
    print("  ✓ Patch 2: _source_income_list → 合并查询")
    n += 1
else:
    print("  ✗ Patch 2: 没找到 _source_income_list 的目标 SQL")

# ── Patch 3: _source_member_payload 加 _src 透传 ──
OLD_PAYLOAD_M_END = '''    return {
        "id": row["id"] if "id" in row else row["member_id"],'''
# 找 _source_member_payload 函数 return dict 末尾的 } 加 _src
import re
m = re.search(
    r'(def _source_member_payload[^}]+?)(\n    \}\s*\n)',
    text, re.S)
if m and '"_src"' not in m.group(1):
    body = m.group(1)
    end = m.group(2)
    new_body = body.rstrip() + ',\n        "_src": row.get("_src"),'
    text = text[:m.start()] + new_body + end + text[m.end():]
    print("  ✓ Patch 3: _source_member_payload 加 _src")
    n += 1

# ── Patch 4: _source_income_payload 加 _src 透传 ──
m2 = re.search(
    r'(def _source_income_payload[^}]+?)(\n    \}\s*\n)',
    text, re.S)
if m2 and '"_src"' not in m2.group(1):
    body = m2.group(1)
    end = m2.group(2)
    new_body = body.rstrip() + ',\n        "_src": row.get("_src"),'
    text = text[:m2.start()] + new_body + end + text[m2.end():]
    print("  ✓ Patch 4: _source_income_payload 加 _src")
    n += 1

# 写回
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ 总改动: {n} 项")

# 语法检查
ret = os.system(f"python3 -c 'import ast; ast.parse(open(\"{PATH}\").read())' 2>&1")
if ret != 0:
    print("✗ AST 语法错误! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST 语法 OK")
