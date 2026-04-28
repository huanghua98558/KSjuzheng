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
endpoints=[
('/api/statistics/overview',{}),('/api/statistics/drama',{}),('/api/accounts',{'page':1,'page_size':20}),('/api/ks-accounts',{'page':1,'page_size':20}),('/api/org-members',{'page':1,'page_size':20}),('/api/auth/users',{'page':1,'page_size':20}),('/api/wallet-info',{}),('/api/firefly/members',{'page':1,'page_size':20}),('/api/firefly/income',{'page':1,'page_size':20}),('/api/spark/members',{'page':1,'page_size':20}),('/api/spark/archive',{'page':1,'page_size':20}),('/api/fluorescent/income',{'page':1,'page_size':20}),('/api/collections/accounts',{}),('/api/collect-pool',{'page':1,'page_size':20}),('/api/high-income-dramas',{'page':1,'page_size':20}),('/api/high-income-dramas/links',{'page':1,'page_size':20}),('/api/statistics/drama-links',{'page':1,'page_size':20}),('/api/spark/violation-photos',{'page':1,'page_size':20}),('/api/spark/violation-dramas',{'page':1,'page_size':20}),('/api/cloud-cookies',{'page':1,'page_size':20}),('/api/cxt-videos',{'page':1,'page_size':20}),('/api/bindings',{'page':1,'page_size':20}),('/api/announcements',{'page':1,'page_size':20}),('/api/config',{})]

def count_items(js):
    d=js.get('data',js)
    if isinstance(d,list): return len(d), 'list'
    if not isinstance(d,dict): return None, type(d).__name__
    for k in ['accounts','users','logs','announcements','list','items','data']:
        if isinstance(d.get(k),list): return len(d[k]), k
    if 'total' in d: return d.get('total'), 'total'
    if 'total_count' in d: return d.get('total_count'), 'total_count'
    return len(d.keys()), 'keys'
for path,params in endpoints:
    r=client.get(path,headers=headers,params=params)
    try: js=r.json(); cnt,kind=count_items(js)
    except Exception: cnt,kind=None,'badjson'
    print(path, r.status_code, kind, cnt, r.text[:180].replace('\n',' '))
