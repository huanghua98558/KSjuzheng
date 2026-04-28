"""ksjuzheng 健康检查脚本 — 验证双表读写规则没破.

跑这个脚本可以快速确认:
  1. 数据库结构完整 (102 张表 / 配置数据保留 / 18474358043 super_admin)
  2. mcn_xxx 镜像在持续更新 (sync 在跑)
  3. 老表没被 sync 误写 / mcn_xxx 没被 ksjuzheng 误写
  4. 后端代码没出现违规 SQL (INSERT INTO mcn_*)
  5. 服务在跑 (ksjuzheng + mcn-sync)

用法:
  python3 /opt/ksjuzheng/scripts/health_check.py
  python3 /opt/ksjuzheng/scripts/health_check.py --no-code   # 跳过代码扫描
  python3 /opt/ksjuzheng/scripts/health_check.py --json       # 输出 JSON

退出码:
  0  全部通过
  1  有警告 (⚠ 但能跑)
  2  有红线违反 (✗ 必须修)
"""
import argparse
import datetime
import json
import os
import re
import subprocess
import sys
import time

import pymysql

DB = dict(host="10.5.0.12", port=3306,
    user="xhy_app", password="Hh19875210.",
    database="huoshijie", charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor)

# 51 张老表清单
LEGACY_TABLES = [
    "account_groups","account_summary","admin_operation_logs","admin_users",
    "auto_devices","auto_device_accounts","auto_task_history",
    "card_keys","card_usage_logs","cloud_cookie_accounts",
    "collect_pool_auth_codes","cxt_author","cxt_titles","cxt_user","cxt_videos",
    "drama_collections","drama_execution_logs",
    "firefly_income","firefly_members",
    "fluorescent_income","fluorescent_income_archive","fluorescent_members",
    "iqiyi_videos","ks_account","ks_episodes",
    "kuaishou_account_bindings","kuaishou_accounts","kuaishou_urls",
    "mcm_organizations","mcn_verification_logs",
    "operator_quota","page_permissions","role_default_permissions",
    "spark_drama_info","spark_highincome_dramas","spark_income",
    "spark_income_archive","spark_members","spark_org_members","spark_photos",
    "spark_violation_dramas","spark_violation_photos",
    "system_announcements","system_config","task_statistics",
    "tv_dramas","tv_episodes","tv_publish_record",
    "user_button_permissions","user_page_permissions",
    "wait_collect_videos",
]

# 必须保留数据的配置表
CONFIG_KEEP_TABLES = ["system_config", "role_default_permissions", "collect_pool_auth_codes"]

# 高频表 (5 分钟内应该在涨)
HOT_TABLES = [
    ("mcn_kuaishou_urls", "id"),
    ("mcn_mcn_verification_logs", "id"),
    ("mcn_fluorescent_members", "member_id"),
    ("mcn_wait_collect_videos", "id"),
]

# 后端代码扫描位置
CODE_DIR = "/opt/ksjuzheng/app"


# ─── 输出 ──────────────────────────────────
RESULTS = []


def add(level, label, msg):
    RESULTS.append({"level": level, "label": label, "msg": msg})
    if level == "OK":
        prefix = "[\033[32m✓\033[0m]"
    elif level == "WARN":
        prefix = "[\033[33m⚠\033[0m]"
    elif level == "FAIL":
        prefix = "[\033[31m✗\033[0m]"
    else:
        prefix = "[i]"
    print(f"{prefix} {label}: {msg}")


# ─── 检查项 ──────────────────────────────────
def check_db_structure(db):
    """R1-R4: 数据库结构完整性"""
    print("\n[Layer 1: 数据库结构]")
    cur = db.cursor()

    # R1: 102 张表
    cur.execute("SHOW TABLES")
    all_tables = {list(r.values())[0] for r in cur.fetchall()}
    legacy_present = [t for t in LEGACY_TABLES if t in all_tables]
    mcn_present = [t for t in LEGACY_TABLES if f"mcn_{t}" in all_tables]
    if len(legacy_present) == 51 and len(mcn_present) == 51:
        add("OK", "R1 表完整", f"51 老 + 51 mcn_ 全部存在")
    else:
        add("FAIL", "R1 表完整",
            f"老表 {len(legacy_present)}/51, mcn_ {len(mcn_present)}/51")

    # R2: _sync_state 表
    if "_sync_state" in all_tables:
        cur.execute("SELECT COUNT(*) AS c FROM _sync_state")
        n = cur.fetchone()["c"]
        if n >= 50:
            add("OK", "R2 _sync_state", f"{n} 行 (sync 状态记录正常)")
        else:
            add("WARN", "R2 _sync_state", f"只 {n} 行 (sync 可能没全跑)")
    else:
        add("FAIL", "R2 _sync_state", "_sync_state 表不存在")

    # R3: 配置数据保留
    for tbl in CONFIG_KEEP_TABLES:
        cur.execute(f"SELECT COUNT(*) AS c FROM `{tbl}`")
        n = cur.fetchone()["c"]
        if n > 0:
            add("OK", f"R3 配置 {tbl}", f"保留 {n} 行")
        else:
            add("FAIL", f"R3 配置 {tbl}", "数据丢失!")

    # R4: 18474358043 super_admin
    cur.execute("""SELECT id, role, organization_access FROM admin_users
                   WHERE username='18474358043'""")
    row = cur.fetchone()
    if row and row["role"] == "super_admin":
        add("OK", "R4 super_admin",
            f"id={row['id']} role=super_admin org={row['organization_access']}")
    else:
        add("FAIL", "R4 super_admin",
            f"18474358043 不是 super_admin 或不存在 (实际: {row})")


def check_sync_active(db):
    """R5-R6: sync 实时同步活跃度"""
    print("\n[Layer 2: sync 同步活跃度]")
    cur = db.cursor()

    # R5: 高频表 max(id) 最近 5 分钟内更新
    cur.execute("""SELECT table_name, last_synced_at, last_pk_value
                   FROM _sync_state
                   WHERE table_name IN ('mcn_kuaishou_urls','mcn_mcn_verification_logs',
                                         'mcn_fluorescent_members','mcn_wait_collect_videos')""")
    states = {r["table_name"]: r for r in cur.fetchall()}
    now = datetime.datetime.now()
    for tbl, _ in HOT_TABLES:
        st = states.get(tbl)
        if not st:
            add("WARN", f"R5 {tbl}", "没有 sync_state 记录")
            continue
        sync_age = (now - st["last_synced_at"]).total_seconds()
        if sync_age < 300:
            add("OK", f"R5 {tbl}", f"{int(sync_age)} 秒前同步过")
        elif sync_age < 1800:
            add("WARN", f"R5 {tbl}", f"{int(sync_age/60)} 分钟前 (略慢)")
        else:
            add("FAIL", f"R5 {tbl}", f"{int(sync_age/60)} 分钟未更新 — sync 可能挂了")


def check_dual_track_rules(db):
    """R7-R8: 双轨规则不破"""
    print("\n[Layer 3: 双轨规则]")
    cur = db.cursor()

    # R7: 老 admin_users 数据应 ≤ 火视界用户数 (sync 不写老表)
    cur.execute("SELECT COUNT(*) AS c FROM admin_users")
    n_old = cur.fetchone()["c"]
    cur.execute("SELECT COUNT(*) AS c FROM mcn_admin_users")
    n_mcn = cur.fetchone()["c"]
    if n_old < n_mcn:
        add("OK", "R7 老表未被 sync 写", f"admin_users {n_old} < mcn_admin_users {n_mcn}")
    elif n_old == n_mcn:
        add("WARN", "R7 老表行数=mcn",
            "或 sync 误写老表, 或 ksjuzheng 写到 mcn (查代码)")
    else:
        add("FAIL", "R7 老表 > mcn", f"{n_old} > {n_mcn} (异常)")

    # R8: mcn_admin_users 没被 ksjuzheng 写
    # (检查: mcn_xxx 的 max(id) 应该等于 sync_state 记录的)
    cur.execute("SELECT MAX(id) AS m FROM mcn_admin_users")
    actual_max = cur.fetchone()["m"]
    cur.execute("""SELECT last_pk_value FROM _sync_state
                   WHERE table_name='mcn_admin_users'""")
    state_row = cur.fetchone()
    if state_row:
        state_max = int(state_row["last_pk_value"] or 0)
        if abs(actual_max - state_max) <= 100:
            add("OK", "R8 mcn_admin_users 干净",
                f"max id {actual_max} ~= state {state_max}")
        else:
            add("WARN", "R8 mcn_admin_users",
                f"actual_max={actual_max} state={state_max} (差 {actual_max-state_max})")
    else:
        add("WARN", "R8 mcn_admin_users", "无 _sync_state 记录")


def check_code_violations():
    """R9-R10: 后端代码扫描违规 SQL"""
    print("\n[Layer 4: 代码规则]")

    if not os.path.isdir(CODE_DIR):
        add("WARN", "R9-R10", f"{CODE_DIR} 不存在, 跳过")
        return

    bad_inserts = []
    bad_updates = []
    bad_deletes = []
    legacy_select_no_source = []  # 没带 source 参数的 SELECT 老表 (建议级)

    for root, dirs, files in os.walk(CODE_DIR):
        # 跳备份目录
        dirs[:] = [d for d in dirs if not d.startswith('.') and 'backup' not in d
                   and '__pycache__' not in d]
        for f in files:
            if not f.endswith('.py') or 'backup' in f:
                continue
            full = os.path.join(root, f)
            try:
                text = open(full, encoding='utf-8').read()
            except Exception:
                continue
            rel = full.replace(CODE_DIR, "")

            # R9: INSERT INTO mcn_xxx
            for m in re.finditer(r'INSERT\s+(?:IGNORE\s+)?INTO\s+`?mcn_\w+`?',
                                  text, re.I):
                line = text[:m.start()].count('\n') + 1
                bad_inserts.append(f"{rel}:{line}")

            # R10: UPDATE mcn_xxx / DELETE FROM mcn_xxx
            for m in re.finditer(r'UPDATE\s+`?mcn_\w+`?\s+SET', text, re.I):
                line = text[:m.start()].count('\n') + 1
                bad_updates.append(f"{rel}:{line}")
            for m in re.finditer(r'DELETE\s+FROM\s+`?mcn_\w+`?', text, re.I):
                line = text[:m.start()].count('\n') + 1
                bad_deletes.append(f"{rel}:{line}")

    if not bad_inserts:
        add("OK", "R9 无违规 INSERT", "代码无 'INSERT INTO mcn_*'")
    else:
        add("FAIL", "R9 违规 INSERT mcn_*", f"{len(bad_inserts)} 处: {bad_inserts[:3]}")

    if not bad_updates and not bad_deletes:
        add("OK", "R10 无违规 UPDATE/DELETE", "代码无 'UPDATE/DELETE mcn_*'")
    else:
        add("FAIL", "R10 违规 UPDATE/DELETE",
            f"UPDATE {len(bad_updates)} 处, DELETE {len(bad_deletes)} 处")


def check_services():
    """R11-R12: 服务运行状态"""
    print("\n[Layer 5: 服务状态]")
    for svc, label in [("ksjuzheng", "R11 ksjuzheng"),
                        ("mcn-sync", "R12 mcn-sync")]:
        try:
            res = subprocess.run(
                ["sudo", "systemctl", "is-active", svc],
                capture_output=True, text=True, timeout=10)
            state = res.stdout.strip()
            if state == "active":
                add("OK", label, f"{svc}.service active")
            else:
                add("FAIL", label, f"{svc} not active ({state})")
        except Exception as e:
            add("WARN", label, f"无法检查: {e}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-code", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    print("\n🔍 ksjuzheng 健康检查 (huoshijie 双轨)")
    print("═" * 60)

    try:
        db = pymysql.connect(**DB)
    except Exception as e:
        add("FAIL", "DB 连接", str(e))
        if args.json:
            print(json.dumps(RESULTS, ensure_ascii=False))
        return 2

    try:
        check_db_structure(db)
        check_sync_active(db)
        check_dual_track_rules(db)
        if not args.no_code:
            check_code_violations()
        check_services()
    finally:
        db.close()

    print()
    print("═" * 60)
    n_ok = sum(1 for r in RESULTS if r["level"] == "OK")
    n_warn = sum(1 for r in RESULTS if r["level"] == "WARN")
    n_fail = sum(1 for r in RESULTS if r["level"] == "FAIL")
    total = len(RESULTS)
    print(f"  总计: {n_ok}/{total} ✓  |  {n_warn} ⚠  |  {n_fail} ✗")

    if args.json:
        print(json.dumps(RESULTS, ensure_ascii=False, indent=2))

    if n_fail > 0:
        print("\n  🚨 有红线违反, 必须修. 看 ✗ 项详情.")
        return 2
    if n_warn > 0:
        print("\n  ⚠ 有警告, 系统能跑但建议关注.")
        return 1
    print("\n  🎉 全部通过, 系统健康.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
