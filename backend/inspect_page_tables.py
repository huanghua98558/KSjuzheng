from sqlalchemy import text
from app.core.db import get_session_factory
for t in ['spark_org_members','wait_collect_videos','drama_collections','collect_pool_auth_codes']:
    print('--',t)
    with get_session_factory()() as db:
        cols=db.execute(text(f'SHOW COLUMNS FROM `{t}`')).mappings().all()
        print([c['Field'] for c in cols])
        rows=db.execute(text(f'SELECT * FROM `{t}` LIMIT 3')).mappings().all()
        for r in rows: print(dict(r))
