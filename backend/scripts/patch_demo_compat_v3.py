"""Patch demo_compat.py — V3 精准字符串替换 (基于 1289-1329 + 1332-1361 实际内容).

策略:
  1. _source_member_list 的 SELECT 改成 UNION ALL (合并老表 + mcn_xxx)
  2. _source_income_list  的 SELECT 改成 UNION ALL
  3. _source_member_payload 在 } 前插一行 "_src": row.get("_src"),
  4. _source_income_payload 同上

不动 router. helper 默认就返回合并数据, 调用方不传 source 参数就拿合并视图.
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v3"
shutil.copy(PATH, BACKUP)
print(f"  备份: {BACKUP}")

text = open(PATH, encoding="utf-8").read()
n = 0

# ── Patch 1: _source_member_list 改 UNION ALL ─────────────────────────
OLD_MEMBER = '''    total = _source_count(db, table, where, params)
    order_map = {
        "member_id": "member_id",
        "member_name": "member_name",
        "fans_count": "fans_count",
        "org_task_num": "org_task_num",
        "total_amount": "total_amount",
        "created_at": "created_at",
    }
    order_col = order_map.get(sort_field or "total_amount", "total_amount")
    direction = "ASC" if sort_order == "ascending" else "DESC"
    sql_where = " AND ".join(where) if where else "1=1"
    rows = db.execute(
        text(f"SELECT * FROM {table} WHERE {sql_where} ORDER BY {order_col} {direction} LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total'''

NEW_MEMBER = '''    total = _source_count(db, table, where, params)
    order_map = {
        "member_id": "member_id",
        "member_name": "member_name",
        "fans_count": "fans_count",
        "org_task_num": "org_task_num",
        "total_amount": "total_amount",
        "created_at": "created_at",
    }
    order_col = order_map.get(sort_field or "total_amount", "total_amount")
    direction = "ASC" if sort_order == "ascending" else "DESC"
    sql_where = " AND ".join(where) if where else "1=1"
    mcn_table = f"mcn_{table}"
    # 双轨合并: 老表 (我的) + mcn_xxx 镜像 (MCN)
    total = total + _source_count(db, mcn_table, where, params)
    rows = db.execute(
        text(f"(SELECT *, '我的' AS _src FROM {table} WHERE {sql_where}) "
             f"UNION ALL "
             f"(SELECT *, 'MCN' AS _src FROM {mcn_table} WHERE {sql_where}) "
             f"ORDER BY {order_col} {direction}, id DESC LIMIT :limit OFFSET :offset"),
        {**params, "limit": per_page, "offset": (page - 1) * per_page},
    ).mappings().all()
    return [_source_member_payload(dict(row), program=program) for row in rows], total'''

if OLD_MEMBER in text:
    text = text.replace(OLD_MEMBER, NEW_MEMBER)
    print("  ✓ Patch 1: _source_member_list → 合并查询")
    n += 1
else:
    print("  ✗ Patch 1: 没找到 _source_member_list 目标 SQL")

# ── Patch 2: _source_income_list 改 UNION ALL ─────────────────────────
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
    # 双轨合并: 老表 (我的) + mcn_xxx 镜像 (MCN)
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
    print("  ✗ Patch 2: 没找到 _source_income_list 目标 SQL")

# ── Patch 3: _source_member_payload 加 _src (替换 closing brace) ──────
OLD_MEMBER_PAYLOAD_END = '''        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
    }


def _source_income_payload'''

NEW_MEMBER_PAYLOAD_END = '''        "created_at": _dt(row.get("created_at")),
        "updated_at": _dt(row.get("updated_at")),
        "_src": row.get("_src"),
    }


def _source_income_payload'''

if OLD_MEMBER_PAYLOAD_END in text and '"_src"' not in text[text.find('def _source_member_payload'):text.find('def _source_income_payload')]:
    text = text.replace(OLD_MEMBER_PAYLOAD_END, NEW_MEMBER_PAYLOAD_END)
    print("  ✓ Patch 3: _source_member_payload 加 _src")
    n += 1
else:
    print("  ✗ Patch 3: 没找到 _source_member_payload 末尾, 或已加过 _src")

# ── Patch 4: _source_income_payload 加 _src (替换 closing brace) ──────
# 找 _source_income_payload 函数体到 def _source_member_list 之间 (income_payload 在前!)
# 实际顺序: _source_member_payload @ 1201, _source_income_payload @ 1239, _source_member_list @ 1289
OLD_INCOME_PAYLOAD_END = '''        "program": program,
        "created_at": _dt(row.get("created_at")),
    }


def _source_member_list'''

NEW_INCOME_PAYLOAD_END = '''        "program": program,
        "created_at": _dt(row.get("created_at")),
        "_src": row.get("_src"),
    }


def _source_member_list'''

# 检查 income_payload 是否已加过 _src
inc_start = text.find('def _source_income_payload')
inc_end = text.find('def _source_member_list')
if OLD_INCOME_PAYLOAD_END in text and '"_src"' not in text[inc_start:inc_end]:
    text = text.replace(OLD_INCOME_PAYLOAD_END, NEW_INCOME_PAYLOAD_END)
    print("  ✓ Patch 4: _source_income_payload 加 _src")
    n += 1
else:
    print("  ✗ Patch 4: 没找到 _source_income_payload 末尾, 或已加过 _src")

# ── 写回 + AST 校验 ────────────────────────────────────────────────────
open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ 总改动: {n} 项")

ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 语法错误! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST 语法 OK")
