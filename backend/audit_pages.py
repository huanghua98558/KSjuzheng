
from fastapi.testclient import TestClient
from sqlalchemy import text
from app.main import app
from app.core.db import get_session_factory
from app.core.security import encode_token

client = TestClient(app)
with get_session_factory()() as db:
    user_row = db.execute(text("SELECT id, organization_access FROM admin_users WHERE is_active = 1 ORDER BY CASE WHEN role IN ('super_admin','superadmin','admin') THEN 0 ELSE 1 END, id ASC LIMIT 1")).mappings().first()
    if not user_row:
        raise SystemExit('NO_ACTIVE_USER')
    token, _, _ = encode_token(user_id=int(user_row['id']), organization_id=user_row['organization_access'], token_type='access')
headers = {'Authorization': f'Bearer {token}'}
print('TOKEN_USER', int(user_row['id']), user_row['organization_access'])

with get_session_factory()() as db:
    for table in ['fluorescent_members','spark_violation_photos','drama_collections','fluorescent_income_archive','spark_income_archive','task_statistics','spark_highincome_dramas','kuaishou_urls','cloud_cookie_accounts','cxt_videos','kuaishou_account_bindings']:
        try:
            c = db.execute(text(f'SELECT COUNT(*) FROM {table}')).scalar()
            print('SRC', table, c)
        except Exception as e:
            print('SRC_ERR', table, type(e).__name__, str(e)[:120])
    try:
        rows = db.execute(text('SELECT status, COUNT(*) c FROM task_statistics GROUP BY status ORDER BY c DESC LIMIT 10')).all()
        print('STATUS', [(r[0], int(r[1])) for r in rows])
    except Exception as e:
        print('STATUS_ERR', e)

endpoints = [
('/api/statistics/overview', {}),
('/api/auth/users', {'page':1,'page_size':20}),
('/api/ks-accounts', {'page':1,'page_size':20}),
('/api/org-members', {'page':1,'page_size':20}),
('/api/firefly/members', {'page':1,'page_size':20}),
('/api/firefly/members/stats', {}),
('/api/firefly/income', {'page':1,'page_size':20}),
('/api/firefly/income/stats', {}),
('/api/firefly/income/wallet-stats', {}),
('/api/spark/members', {'page':1,'page_size':20}),
('/api/spark/members/stats', {}),
('/api/spark/stats', {}),
('/api/spark/archive', {'page':1,'page_size':20}),
('/api/spark/archive/stats', {}),
('/api/spark/archive/wallet-stats', {}),
('/api/fluorescent/income', {'page':1,'page_size':20}),
('/api/fluorescent/income/stats', {}),
('/api/high-income-dramas', {'page':1,'page_size':20}),
('/api/high-income-dramas/links', {'page':1,'page_size':20}),
('/api/statistics/drama-links', {'page':1,'page_size':20}),
('/api/collections/accounts', {}),
('/api/collections/stats/overview', {}),
('/api/spark/violation-photos', {'page':1,'page_size':20}),
('/api/spark/violation-dramas', {'page':1,'page_size':20}),
('/api/spark/photos', {'page':1,'page_size':20}),
('/api/cloud-cookies', {'page':1,'page_size':20}),
('/api/cxt-videos', {'page':1,'page_size':20}),
('/api/bindings', {'page':1,'page_size':20}),
('/api/bindings/stats', {}),
('/api/statistics/external-urls', {'page':1,'page_size':20}),
]

def shape(x):
    if isinstance(x, list): return len(x)
    if not isinstance(x, dict): return type(x).__name__
    d = x.get('data', x)
    out = {}
    if isinstance(d, list): return {'items': len(d)}
    if isinstance(d, dict):
        for k in ['total','total_count','total_members','total_amount','total_income','period_income','wallet_count']:
            if k in d: out[k]=d[k]
        for k in ['list','items','users','accounts','data']:
            if isinstance(d.get(k), list): out[k]=len(d[k])
        if 'pagination' in x: out['pagination_total']=x['pagination'].get('total')
        if 'summary' in d: out['summary']=d['summary']
    return out

for path, params in endpoints:
    try:
        r = client.get(path, params=params, headers=headers)
        txt = r.text[:240].replace('\n',' ')
        if r.status_code >= 400:
            print('API_ERR', path, r.status_code, txt)
        else:
            print('API_OK', path, shape(r.json()))
    except Exception as e:
        print('API_EXC', path, type(e).__name__, str(e)[:240])
