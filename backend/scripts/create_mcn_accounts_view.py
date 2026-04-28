"""创建 huoshijie.mcn_accounts 物化视图 (从 mcn_kuaishou_accounts 映射 ksjuzheng accounts schema).

按用户期望: "MCN 镜像应该有 accounts 表" — 我们用 SQL VIEW 实现"看起来像有镜像".
数据自动跟随 mcn_kuaishou_accounts (sync_daemon 维护它), VIEW 实时.

字段映射 (mcn_kuaishou_accounts → ksjuzheng accounts):
  id              → id
  organization_id → organization_id
  owner_id        → assigned_user_id
  group_id        → group_id
  uid             → kuaishou_id
  uid_real        → real_uid
  nickname        → nickname
  account_status  → status
  contract_status → mcn_status / sign_status
  device_serial   → device_serial
  org_note        → remark (优先) | status_note (fallback)
  blacklisted_by  → imported_by_user_id
  invite_time     → imported_at
  created_at      → created_at
  updated_at      → updated_at
  commission_rate → commission_rate
"""
import pymysql

conn = pymysql.connect(
    host="hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com",
    port=27666, user="xhy_app", password="Hh19875210.",
    database="huoshijie", charset="utf8mb4",
)
cur = conn.cursor()

# 1. 删除可能存在的旧 view (但要小心: 如果是 BASE TABLE 则保护)
cur.execute("""
SELECT TABLE_TYPE FROM information_schema.tables
WHERE TABLE_SCHEMA='huoshijie' AND TABLE_NAME='mcn_accounts'
""")
row = cur.fetchone()
if row:
    if row[0] == "BASE TABLE":
        print(f"⚠ mcn_accounts 已是 BASE TABLE, 拒绝删除 (避免数据丢失)")
        print("  请手动确认是否要丢弃, 改用 VIEW.")
        exit(1)
    elif row[0] == "VIEW":
        print(f"  发现旧 VIEW, 删除重建")
        cur.execute("DROP VIEW IF EXISTS mcn_accounts")
else:
    print("  无旧表/视图")

# 2. 创建 VIEW
ddl = """
CREATE VIEW mcn_accounts AS
SELECT
  id,
  COALESCE(organization_id, 0) AS organization_id,
  owner_id AS assigned_user_id,
  group_id,
  uid AS kuaishou_id,
  uid_real AS real_uid,
  nickname,
  COALESCE(account_status, 'normal') AS status,
  contract_status AS mcn_status,
  contract_status AS sign_status,
  NULL AS cookie_status,
  NULL AS cookie_last_success_at,
  COALESCE(commission_rate, 80.0) AS commission_rate,
  device_serial,
  COALESCE(org_note, status_note) AS remark,
  blacklisted_by AS imported_by_user_id,
  invite_time AS imported_at,
  created_at,
  updated_at,
  blacklisted_at AS deleted_at
FROM mcn_kuaishou_accounts
WHERE is_blacklisted = 0
"""
cur.execute(ddl)
print("✓ CREATE VIEW mcn_accounts 完成")

# 3. 验证
cur.execute("SELECT COUNT(*) FROM mcn_accounts")
total = cur.fetchone()[0]
print(f"✓ mcn_accounts VIEW 行数 = {total}")

cur.execute("SELECT id, kuaishou_id, nickname, status, mcn_status, organization_id, group_id, assigned_user_id FROM mcn_accounts ORDER BY id DESC LIMIT 3")
print("✓ Sample rows (top 3):")
for r in cur.fetchall():
    print(f"    {r}")

cur.execute("DESCRIBE mcn_accounts")
print(f"✓ 字段数: {len(cur.fetchall())}")

conn.close()
print("\n完成. ksjuzheng /accounts source=mcn 现可直接查 mcn_accounts (无需跨表).")
