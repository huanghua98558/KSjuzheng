"""手动全量重导 mcn_account_groups (源 → 镜像), 修 phase1 owner_id 过滤遗留.

问题: phase1_filter_and_promote.py 的 OWNER_ID_TABLES 包含 account_groups,
      初始化时按 owner_id ∈ 火视界 users 过滤, 镜像只 266 行.
修复: 直接全量 INSERT (镜像 = 源全量), 后续 sync_daemon watermark 维护增量.
"""
import sys
sys.path.insert(0, "/opt/ksjuzheng")
import pymysql

# 源端 (MCN 通过 SSH tunnel)
SRC = pymysql.connect(host="127.0.0.1", port=13306, user="shortju",
                      password="4pz8PjGspTCxxAd4", database="shortju", charset="utf8mb4")
# 镜像端 (huoshijie)
DST = pymysql.connect(host="hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com",
                      port=27666, user="xhy_app", password="Hh19875210.",
                      database="huoshijie", charset="utf8mb4")

src_cur = SRC.cursor()
dst_cur = DST.cursor()

src_cur.execute("SELECT COUNT(*) FROM account_groups")
n_src = src_cur.fetchone()[0]
dst_cur.execute("SELECT COUNT(*) FROM mcn_account_groups")
n_dst_before = dst_cur.fetchone()[0]
print(f"  源 account_groups: {n_src}")
print(f"  镜像 mcn_account_groups (before): {n_dst_before}")

# 全量 INSERT IGNORE (避免重复 ID 冲突)
src_cur.execute("SELECT id, group_name, description, color, sort_order, created_at, updated_at, owner_id FROM account_groups")
rows = src_cur.fetchall()
print(f"  从源拉到 {len(rows)} 行")

dst_cur.executemany("""
INSERT INTO mcn_account_groups (id, group_name, description, color, sort_order, created_at, updated_at, owner_id)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
  group_name=VALUES(group_name), description=VALUES(description),
  color=VALUES(color), sort_order=VALUES(sort_order),
  updated_at=VALUES(updated_at), owner_id=VALUES(owner_id)
""", rows)
DST.commit()

dst_cur.execute("SELECT COUNT(*) FROM mcn_account_groups")
n_dst_after = dst_cur.fetchone()[0]
print(f"  镜像 mcn_account_groups (after): {n_dst_after} (期望 ≥ {n_src})")

# 更新 _sync_state.last_synced_at
dst_cur.execute("""
UPDATE _sync_state SET last_synced_at=NOW(), rows_synced_total=%s
WHERE table_name='account_groups'
""", (n_dst_after,))
DST.commit()
print(f"  ✓ _sync_state 已更新")

SRC.close()
DST.close()
