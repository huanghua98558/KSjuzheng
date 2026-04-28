"""向 /api/collections/accounts payload dict 加 _src 字段."""
import os, sys, ast

PATH = "/opt/ksjuzheng/app/api/demo_compat.py"
t = open(PATH, encoding="utf-8").read()

OLD = '                    "last_collected_at": _dt(row["last_collected_at"]),\n                    "updated_at": _dt(row["updated_at"]),\n                }'
NEW = '                    "last_collected_at": _dt(row["last_collected_at"]),\n                    "updated_at": _dt(row["updated_at"]),\n                    "_src": row.get("_src"),\n                }'

cnt = t.count(OLD)
print(f"matches: {cnt}")
if cnt != 1:
    print(f"✗ 找到 {cnt} 处 (期望 1)"); sys.exit(1)
t2 = t.replace(OLD, NEW, 1)
open(PATH, "w", encoding="utf-8").write(t2)
ast.parse(open(PATH).read())
print("✓ AST OK")
