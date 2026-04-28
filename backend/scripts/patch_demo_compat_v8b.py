"""V8b — 补 V8 漏的 3 处 + 收益 helper 加权限.

V8 漏的:
  1. line 1901 _dual_select admin_users (V6c /auth/users mcn 分支)
  2. line 3786 _dual_select kuaishou_accounts (V6c /ks-accounts mcn 分支)
  3. line 5291 _dual_select cloud_cookie_accounts (V6b /cloud-cookies)

V5 改的收益 helper 也漏权限:
  _source_member_list 内部 source 三档没 viewer 校验
  _source_income_list 同上
  + 6 收益 router 调用时传 viewer=user
"""
import os, sys, shutil

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
BACKUP = PATH + ".bak_v8b"
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


# ── P1: 3 个 _dual_select 漏 viewer ──
patch("admin_users 加 viewer",
'''rows, total = _dual_select(db, "admin_users", where, params, page, per_page, "mcn")''',
'''rows, total = _dual_select(db, "admin_users", where, params, page, per_page, "mcn", viewer=user)''')

patch("kuaishou_accounts 加 viewer",
'''rows, total = _dual_select(db, "kuaishou_accounts", where, params, page, per_page, "mcn")''',
'''rows, total = _dual_select(db, "kuaishou_accounts", where, params, page, per_page, "mcn", viewer=user)''')

patch("cloud_cookie_accounts 加 viewer",
'''rows, total = _dual_select(db, "cloud_cookie_accounts", [], {}, page, per_page, source)''',
'''rows, total = _dual_select(db, "cloud_cookie_accounts", [], {}, page, per_page, source, viewer=user)''')


# ── P2: _source_member_list 加 viewer 参数 ──
patch("_source_member_list 签名加 viewer",
'''    sort_field: str | None = None,
    sort_order: str | None = None,
    source: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _source_org_clause(user, "org_id")''',
'''    sort_field: str | None = None,
    sort_order: str | None = None,
    source: str | None = None,
    viewer: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    if viewer is not None and not getattr(viewer, "is_superadmin", False):
        source = "self"
    where, params = _source_org_clause(user, "org_id")''')


# ── P3: _source_income_list 加 viewer 参数 ──
patch("_source_income_list 签名加 viewer",
'''    task_name: str | None = None,
    org_column: str | None = "org_id",
    source: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:''',
'''    task_name: str | None = None,
    org_column: str | None = "org_id",
    source: str | None = None,
    viewer: Any = None,
) -> tuple[list[dict[str, Any]], int]:
    if viewer is not None and not getattr(viewer, "is_superadmin", False):
        source = "self"
    where: list[str] = []
    params: dict[str, Any] = {}
    if org_column and not user.is_superadmin:''')


# ── P4: 6 收益 router 调用 helper 加 viewer=user ──
# _source_member_list 调用 (firefly_members + spark_members)
import re
member_calls = list(re.finditer(
    r'_source_member_list\(\s*\n\s*db,\s*\n\s*user,(?:[^)]+)source=source,\s*\n\s*\)',
    text, re.DOTALL,
))
print(f"\n  _source_member_list 调用: {len(member_calls)} 处")
for m in reversed(member_calls):
    old = m.group(0)
    new = old.rstrip(")\n").rstrip("\n").rstrip() + "\n            viewer=user,\n        )"
    text = text.replace(old, new)
    n += 1
    print(f"    ✓ 加 viewer=user @ _source_member_list pos {m.start()}")

# _source_income_list 调用 (firefly_income/spark_income/fluorescent_income/spark_archive)
income_calls = list(re.finditer(
    r'_source_income_list\(\s*\n\s*db,\s*user,[^)]+source=source,\s*\n?\s*\)',
    text, re.DOTALL,
))
print(f"\n  _source_income_list 调用 (multi-line): {len(income_calls)} 处")
for m in reversed(income_calls):
    old = m.group(0)
    new = old[:-1] + " viewer=user,\n        )"
    new = new.rstrip(")") + "viewer=user, )"
    text = text.replace(old, m.group(0).replace("source=source,", "source=source, viewer=user,"))
    n += 1

# 单行 _source_income_list 调用
line_pattern = re.compile(r'(_source_income_list\([^)]+source=source)(\s*,?\s*\))')
single_calls = list(line_pattern.finditer(text))
print(f"  _source_income_list 调用 (single-line patch): {len(single_calls)} 处")
for m in reversed(single_calls):
    text = text[:m.start(2)] + ", viewer=user)" + text[m.end(2):]
    n += 1
    print(f"    ✓ 加 viewer=user @ _source_income_list single pos {m.start()}")


open(PATH, "w", encoding="utf-8").write(text)
print(f"\n✓ V8b 改动: {n} 项")
ret = os.system(f'python3 -c "import ast; ast.parse(open(\\"{PATH}\\").read())" 2>&1')
if ret != 0:
    print("✗ AST 错!! 自动回滚")
    shutil.copy(BACKUP, PATH)
    sys.exit(1)
print("✓ AST OK")
