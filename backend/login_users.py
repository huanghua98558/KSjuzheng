from sqlalchemy import text
from app.core.db import get_session_factory
with get_session_factory()() as db:
    rows=db.execute(text("SELECT id,username,nickname,role,is_active,last_login FROM admin_users ORDER BY CASE WHEN role IN ('super_admin','superadmin','admin') THEN 0 ELSE 1 END, id ASC LIMIT 10")).mappings().all()
    for r in rows: print(dict(r))
