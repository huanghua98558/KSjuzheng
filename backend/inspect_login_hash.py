from sqlalchemy import text
from app.core.db import get_session_factory
with get_session_factory()() as db:
    rows=db.execute(text("SELECT id,username,password_hash,password_salt FROM admin_users WHERE username IN ('admin','admin888','cpkj888') ORDER BY id")).mappings().all()
    for r in rows:
        d=dict(r);
        for k in ['password_hash','password_salt']:
            v=d.get(k); d[k]=(v[:20]+'... len='+str(len(v))) if isinstance(v,str) and len(v)>20 else v
        print(d)
