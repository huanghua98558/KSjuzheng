"""一键清除 admin888 (id=68) 在 MCN 后台的全部操作日志.

匹配规则: admin_operation_logs.user_id = 68  OR  username = 'admin888'
        (含 swap 之前 user_id=1887 的旧条目, 用 username 兜底)

同时清:
  - 源 MCN MySQL  (im.zhongxiangbao.com:3306)
  - 镜像 huoshijie (CynosDB 内网, 经香港 ubuntu 之后我们直连外网)

执行前会:
  1. 显示即将删除的条目数 + 5 条样本
  2. 等回车确认
  3. 备份将删除的行到本地 JSON (万一需要回滚)
  4. 双删 (源 + 镜像)
  5. 验证两边都 = 0

使用: 双击同目录下的 clear_admin888_logs.bat
"""
import json
import pathlib
import sys
import time
from datetime import datetime

try:
    import pymysql
except ImportError:
    print("[FATAL] pymysql 未装. 请先在命令行: pip install pymysql")
    input("按回车退出...")
    sys.exit(1)


# ─────────── 配置 ───────────
SRC_CFG = dict(
    host='im.zhongxiangbao.com', port=3306,
    user='shortju', password='4pz8PjGspTCxxAd4',
    database='shortju', charset='utf8mb4',
    connect_timeout=15,
)
DST_CFG = dict(
    host='hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com', port=27666,
    user='xhy_app', password='Hh19875210.',
    database='huoshijie', charset='utf8mb4',
    connect_timeout=15,
)

TARGET_USER_ID = 68
TARGET_USERNAME = 'admin888'

# 备份目录 (脚本同目录下的 backups/)
HERE = pathlib.Path(__file__).parent
BACKUP_DIR = HERE / 'backups'
BACKUP_DIR.mkdir(exist_ok=True)


# ─────────── 工具 ───────────
def banner(title):
    print()
    print("═" * 60)
    print(f"  {title}")
    print("═" * 60)


def connect(cfg, label):
    """连接数据库, 失败时友好报错."""
    try:
        c = pymysql.connect(**cfg, autocommit=False,
                            cursorclass=pymysql.cursors.DictCursor)
        return c
    except pymysql.err.OperationalError as e:
        print(f"\n[ERROR] 连接 {label} 失败:")
        print(f"  {cfg['host']}:{cfg['port']}/{cfg['database']}")
        print(f"  → {e}")
        if 'timeout' in str(e).lower() or 'unable' in str(e).lower():
            print(f"\n提示:")
            print(f"  - 如果是 huoshijie (CynosDB): 公网入口可能波动, 稍后重试")
            print(f"  - 如果是 MCN 源 + 你在香港 ubuntu: 检查 SSH 隧道是否在运行")
        raise


def confirm(prompt='\n按 [回车] 继续删除, [Ctrl+C] 取消: '):
    try:
        input(prompt)
    except KeyboardInterrupt:
        print("\n[取消] 用户中断, 未做任何删除.")
        sys.exit(0)


# ─────────── 主流程 ───────────
def main():
    banner(f"清除 admin888 (id={TARGET_USER_ID}) 的操作日志")
    print(f"  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  目标表: admin_operation_logs")
    print(f"  匹配规则: user_id = {TARGET_USER_ID}  OR  username = '{TARGET_USERNAME}'")

    # 1. 连接 + 探查 ───────────
    banner("步骤 1/4: 连接数据库 + 统计")
    print("  连接源 MCN ...", flush=True)
    src = connect(SRC_CFG, 'MCN 源')
    print("  连接镜像 huoshijie ...", flush=True)
    dst = connect(DST_CFG, 'huoshijie 镜像')

    where_clause = f"user_id={TARGET_USER_ID} OR username='{TARGET_USERNAME}'"

    src_cur = src.cursor()
    dst_cur = dst.cursor()

    src_cur.execute(f"SELECT COUNT(*) AS c FROM admin_operation_logs WHERE {where_clause}")
    n_src = src_cur.fetchone()['c']
    dst_cur.execute(f"SELECT COUNT(*) AS c FROM admin_operation_logs WHERE {where_clause}")
    n_dst = dst_cur.fetchone()['c']

    print(f"  源 MCN  匹配条目: {n_src} 条")
    print(f"  镜像     匹配条目: {n_dst} 条")

    if n_src == 0 and n_dst == 0:
        print("\n[完成] 两边都没有 admin888 的日志, 无需操作.")
        src.close(); dst.close()
        return

    # 2. 显示样本 + 备份 ───────────
    banner("步骤 2/4: 显示前 10 条 + 备份到本地")
    src_cur.execute(f"""SELECT id, user_id, username, action, module, target,
                              ip, status, created_at
                       FROM admin_operation_logs
                       WHERE {where_clause}
                       ORDER BY id DESC LIMIT 10""")
    samples = src_cur.fetchall()
    print(f"  {'ID':<8} {'user_id':<8} {'用户名':<12} {'动作':<10} "
          f"{'模块':<10} {'IP':<18} {'时间':<20}")
    print("  " + "-" * 92)
    for r in samples:
        print(f"  {r['id']:<8} {r['user_id']:<8} {r['username']:<12} "
              f"{r['action']:<10} {r['module']:<10} {r['ip']:<18} "
              f"{str(r['created_at'])[:19]:<20}")

    # Full backup (all rows that will be deleted) — 源 prevails
    src_cur.execute(f"SELECT * FROM admin_operation_logs WHERE {where_clause} ORDER BY id")
    full_rows = src_cur.fetchall()
    backup_file = BACKUP_DIR / f"admin888_logs_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    backup_data = []
    for row in full_rows:
        # Convert datetime -> ISO string for JSON
        clean = {k: (v.isoformat() if isinstance(v, datetime) else v) for k, v in row.items()}
        backup_data.append(clean)
    backup_file.write_text(json.dumps(backup_data, ensure_ascii=False, indent=2),
                           encoding='utf-8')
    print(f"\n  备份已写入: {backup_file}")
    print(f"  ({len(backup_data)} 条记录, 万一需要可以从这里恢复)")

    # 3. Confirm + Delete ───────────
    banner("步骤 3/4: 确认删除")
    print(f"  即将从两个数据库共同删除 {max(n_src, n_dst)} 条日志条目.")
    print(f"  此操作不可逆 (但有上面那个 JSON 备份).")
    confirm()

    print("\n  开始删除 ...")
    t0 = time.time()
    src_cur.execute(f"DELETE FROM admin_operation_logs WHERE {where_clause}")
    deleted_src = src_cur.rowcount
    src.commit()
    print(f"    [源 MCN]  已删 {deleted_src} 条 ({time.time()-t0:.2f}s)")

    t1 = time.time()
    dst_cur.execute(f"DELETE FROM admin_operation_logs WHERE {where_clause}")
    deleted_dst = dst_cur.rowcount
    dst.commit()
    print(f"    [镜像]    已删 {deleted_dst} 条 ({time.time()-t1:.2f}s)")

    # 4. Verify ───────────
    banner("步骤 4/4: 验证")
    src_cur.execute(f"SELECT COUNT(*) AS c FROM admin_operation_logs WHERE {where_clause}")
    final_src = src_cur.fetchone()['c']
    dst_cur.execute(f"SELECT COUNT(*) AS c FROM admin_operation_logs WHERE {where_clause}")
    final_dst = dst_cur.fetchone()['c']
    print(f"  源 MCN  剩余: {final_src} 条")
    print(f"  镜像     剩余: {final_dst} 条")

    if final_src == 0 and final_dst == 0:
        print("\n  ✅ 所有 admin888 操作日志已清除.")
    else:
        print(f"\n  ⚠️  仍有残留 (源={final_src}, 镜像={final_dst})")

    src.close()
    dst.close()


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        import traceback
        print("\n[错误]", e)
        traceback.print_exc()
    finally:
        # 让双击窗口不会立刻关闭, 用户能看到结果
        input("\n按 [回车] 关闭窗口...")
