
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.db import get_session_factory
from app.core.security import encode_token

client=TestClient(app)
with get_session_factory()() as db:
    u=db.execute(text("SELECT id, organization_access FROM admin_users WHERE is_active=1 ORDER BY CASE WHEN role IN ('super_admin','superadmin','admin') THEN 0 ELSE 1 END, id ASC LIMIT 1")).mappings().first()
    token,_,_=encode_token(user_id=int(u['id']), organization_id=u['organization_access'], token_type='access')
    print('USER', dict(u))
    tables=db.execute(text('SHOW TABLES')).scalars().all()
    for t in tables:
        low=t.lower()
        if any(k in low for k in ['config','setting','announce','audit','log','permission','organization','cookie']):
            try: c=db.execute(text(f'SELECT COUNT(*) FROM `{t}`')).scalar()
            except Exception as e: c='ERR '+str(e)[:80]
            print('TABLE',t,c)
headers={'Authorization':f'Bearer {token}'}
endpoints=[
('/api/auth/profile',{}),('/api/auth/logs',{'page':1,'page_size':5}),('/api/auth/logs/stats',{}),
('/api/organizations',{}),('/api/organizations/accessible',{}),('/api/accounts/organization-stats',{}),
('/api/announcements',{'page':1,'page_size':5}),('/api/auth/users',{'page':1,'page_size':5}),
('/api/auth/role-default-permissions/super_admin',{}),('/api/auth/role-default-permissions/operator',{}),('/api/auth/role-default-permissions/normal_user',{}),
('/api/config',{}),('/api/cloud-cookies',{'page':1,'page_size':5}),('/api/cloud-cookies/owner-codes',{}),('/api/auth/auth-codes-status',{}),('/api/auth/my-auth-code',{})]
for path,params in endpoints:
    r=client.get(path,headers=headers,params=params)
    body=r.text[:350].replace('\n',' ')
    print('EP',r.status_code,path,body)
