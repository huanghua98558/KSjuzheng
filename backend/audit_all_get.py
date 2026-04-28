
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.db import get_session_factory
from app.core.security import encode_token

client = TestClient(app)
with get_session_factory()() as db:
    user_row = db.execute(text("SELECT id, organization_access FROM admin_users WHERE is_active = 1 ORDER BY CASE WHEN role IN ('super_admin','superadmin','admin') THEN 0 ELSE 1 END, id ASC LIMIT 1")).mappings().first()
    token, _, _ = encode_token(user_id=int(user_row['id']), organization_id=user_row['organization_access'], token_type='access')
headers = {'Authorization': f'Bearer {token}'}
skip_prefix = {'/docs','/redoc','/openapi.json','/api/debug','/api/ws'}
rows=[]
for route in app.routes:
    methods = getattr(route,'methods',set()) or set()
    path = getattr(route,'path','')
    if 'GET' not in methods or not path.startswith('/api/'):
        continue
    if any(path.startswith(p) for p in skip_prefix):
        continue
    if '{' in path:
        continue
    try:
        r = client.get(path, headers=headers, params={'page':1,'page_size':5})
        ok = r.status_code < 400
        body = r.text[:160].replace('\n',' ')
        rows.append((ok, r.status_code, path, body))
    except Exception as e:
        rows.append((False, 'EXC', path, f'{type(e).__name__}: {str(e)[:140]}'))

bad=[x for x in rows if not x[0]]
print('GET_TOTAL', len(rows), 'BAD', len(bad))
for ok,code,path,body in bad:
    print('BAD', code, path, body)
print('SAMPLE_OK')
for ok,code,path,body in rows[:30]:
    if ok:
        print('OK', code, path)
