from fastapi.testclient import TestClient
from app.main import app
client=TestClient(app)
for u,p in [("admin","admin"),("admin888","MCNAdmin@2024")]:
    r=client.post("/api/auth/login",json={"username":u,"password":p})
    print(u, r.status_code, r.text[:220])
