from sqlalchemy import text
from app.core.db import get_session_factory
from app.core.security import hash_password
new_hash = hash_password("admin")
with get_session_factory()() as db:
    row = db.execute(text("SELECT id, username FROM admin_users WHERE username = 'admin' LIMIT 1")).mappings().first()
    if not row:
        raise SystemExit('admin user not found')
    db.execute(text("UPDATE admin_users SET password_hash = :hash, password_salt = '' WHERE username = 'admin'"), {"hash": new_hash})
    db.commit()
    print('UPDATED', dict(row))
