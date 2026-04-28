"""创建临时测试用户 testop / test123, role=operator (非 super_admin), 用于权限测试."""
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
sql = """
INSERT INTO admin_users (username, nickname, role, password_hash, password_salt,
                         is_active, organization_access, parent_user_id, created_at, updated_at)
VALUES ('testop', '测试operator', 'operator', %s, '', 1, 10, 1068, NOW(), NOW())
ON DUPLICATE KEY UPDATE password_hash=%s, role='operator', is_active=1
"""
cur.execute(sql, (pw_hash, pw_hash))
conn.commit()
cur.execute("SELECT id, username, role, is_active FROM admin_users WHERE username='testop'")
print(cur.fetchone())
conn.close()
