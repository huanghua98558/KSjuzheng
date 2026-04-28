from sqlalchemy import text
from app.core.db import get_session_factory
phone='13337289759'
with get_session_factory()() as db:
    rows=db.execute(text("SELECT id, username, nickname, phone, role, is_active, password_hash, password_salt, last_login FROM admin_users WHERE phone=:phone OR username=:phone ORDER BY id"), {'phone': phone}).mappings().all()
    print('COUNT', len(rows))
    for r in rows:
        d=dict(r)
        for k in ['password_hash','password_salt']:
            v=d.get(k)
            if isinstance(v,str):
                d[k]=v[:16]+'... len='+str(len(v))
        print(d)
