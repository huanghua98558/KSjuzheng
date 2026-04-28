from sqlalchemy import text
from app.core.db import get_session_factory
keywords=['member','org','collect','pool','drama']
with get_session_factory()() as db:
    tables=db.execute(text('SHOW TABLES')).scalars().all()
    for t in tables:
        low=t.lower()
        if any(k in low for k in keywords):
            try: c=db.execute(text(f'SELECT COUNT(*) FROM `{t}`')).scalar()
            except Exception as e: c='ERR '+str(e)[:80]
            print(t,c)
