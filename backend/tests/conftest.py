"""pytest 共享 fixture."""
from __future__ import annotations

import os
import sys
from pathlib import Path

# 把 bendi 加到 sys.path
BENDI = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BENDI))

# 测试用 sqlite 文件 (不污染开发库)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{BENDI / 'data' / 'test.db'}")
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DEBUG", "true")

import pytest
from fastapi.testclient import TestClient

from app.core.db import get_session_factory, init_engine
from scripts.init_db import (
    create_all,
    drop_all,
    seed_admin,
    seed_default_role_perms,
    seed_demo_announcements,
    seed_demo_content,
    seed_demo_income,
    seed_demo_licenses,
    seed_demo_org_and_users,
    seed_demo_phase3,
    seed_permissions,
    seed_roles,
)


@pytest.fixture(scope="session")
def _db_setup():
    init_engine()
    drop_all()
    create_all()
    Session = get_session_factory()
    with Session() as db:
        seed_permissions(db)
        seed_roles(db)
        seed_default_role_perms(db)
        seed_admin(db)
        seed_demo_licenses(db)
        seed_demo_org_and_users(db)
        seed_demo_content(db)
        seed_demo_income(db)
        seed_demo_announcements(db)
        seed_demo_phase3(db)
        db.commit()
    yield


@pytest.fixture()
def client(_db_setup):
    from app.main import app
    with TestClient(app) as c:
        yield c
