from sqlalchemy import text
from app.core.db import get_session_factory
with get_session_factory()() as db:
    for t in ["admin_operation_logs","system_announcements","role_default_permissions","system_config"]:
        print("--",t)
        cols=db.execute(text(f"SHOW COLUMNS FROM `{t}`")).mappings().all()
        print([c["Field"] for c in cols])
        rows=db.execute(text(f"SELECT * FROM `{t}` LIMIT 3")).mappings().all()
        for r in rows: print(dict(r))
