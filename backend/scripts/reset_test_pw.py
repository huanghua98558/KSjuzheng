"""重置 hsj888 (operator) 密码 + 确保 users 表 sync, 用于权限测试."""
import sys
sys.path.insert(0, "/opt/ksjuzheng")
from app.core.security import hash_password
import pymysql

conn = pymysql.connect(
    host="hk-cynosdbmysql-grp-ag6t3waf.sql.tencentcdb.com",
    port=27666, user="xhy_app", password="Hh19875210.",
    database="huoshijie", charset="utf8mb4",
)
cur = conn.cursor()
pw_hash = hash_password("test123")

# 重置 admin_users 密码
cur.execute("UPDATE admin_users SET password_hash=%s, is_active=1 WHERE username='hsj888'", (pw_hash,))
print(f"admin_users updated: {cur.rowcount}")

# 看 users 表对应行
cur.execute("SELECT id, username FROM users WHERE username='hsj888'")
row = cur.fetchone()
if row:
    print(f"users 已存在: id={row[0]}")
    cur.execute("UPDATE users SET hashed_password=%s, is_active=1 WHERE username='hsj888'", (pw_hash,))
    print(f"users updated: {cur.rowcount}")
else:
    # 看 admin_users 的 id (它必须等于 users.id 因为外键)
    cur.execute("SELECT id, username, role, organization_access FROM admin_users WHERE username='hsj888'")
    a = cur.fetchone()
    print(f"admin_users: {a}")
    # users 表 INSERT
    cur.execute("DESCRIBE users")
    cols = [r[0] for r in cur.fetchall()]
    print(f"users 表字段: {cols[:10]}")
    cur.execute("""
        INSERT INTO users (id, username, hashed_password, role, organization_id, is_active, is_superadmin, created_at, updated_at)
        VALUES (%s, %s, %s, %s, %s, 1, 0, NOW(), NOW())
    """, (a[0], a[1], pw_hash, a[2], a[3]))
    print(f"users INSERT: {cur.rowcount}")

conn.commit()

# 显示结果
cur.execute("SELECT id, username, role FROM admin_users WHERE username='hsj888'")
print("admin_users:", cur.fetchone())
cur.execute("SELECT id, username, role, is_superadmin FROM users WHERE username='hsj888'")
print("users:", cur.fetchone())
conn.close()
