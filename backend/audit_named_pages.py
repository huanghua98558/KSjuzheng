from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.db import get_session_factory
from app.core.security import encode_token
client=TestClient(app)
with get_session_factory()() as db:
    u=db.execute(text("SELECT id, organization_access FROM admin_users WHERE username='admin' LIMIT 1")).mappings().first()
    token,_,_=encode_token(user_id=int(u['id']), organization_id=u['organization_access'], token_type='access')
headers={'Authorization':f'Bearer {token}'}
for path,params in [('/api/org-members',{'page':1,'page_size':3}),('/api/org-members/stats',{}),('/api/org-members/brokers',{}),('/api/collect-pool',{'page':1,'page_size':3}),('/api/collect-pool/stats',{}),('/api/collect-pool/auth-code',{})]:
    r=client.get(path,headers=headers,params=params)
    print(path,r.status_code,r.text[:700].replace('\n',' '))
