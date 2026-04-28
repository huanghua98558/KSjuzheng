"""数据库引擎 + Session.

特性:
  - SQLite 自动开 WAL + busy_timeout (对齐 ks_automation/CLAUDE.md §21)
  - PostgreSQL 用普通连接池
  - get_db() 是 FastAPI dependency, 每请求一 session
"""
from __future__ import annotations

import sqlite3
from typing import Iterator

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings
from app.core.logging import logger


# ============================================================
# Declarative Base
# ============================================================

class Base(DeclarativeBase):
    """所有 ORM 模型的基类."""


# ============================================================
# Engine 与 Session
# ============================================================

_engine: Engine | None = None
_SessionLocal: sessionmaker | None = None




def _mask_db_url(url: str) -> str:
    """脱敏 DATABASE_URL: mysql+pymysql://user:PASSWORD@host:port/db -> mysql+pymysql://user:***@host:port/db"""
    import re as _re
    return _re.sub(r"://([^:/@]+):([^@/]+)@", r"://\1:***@", str(url))


def init_engine() -> Engine:
    """启动时调用一次. 返单例 engine."""
    global _engine, _SessionLocal

    if _engine is not None:
        return _engine

    url = settings.DATABASE_URL

    if settings.is_sqlite:
        # SQLite 特调: WAL + busy_timeout
        _engine = create_engine(
            url,
            connect_args={
                "check_same_thread": False,
                "timeout": 30,
            },
            pool_pre_ping=True,
            future=True,
        )

        @event.listens_for(_engine, "connect")
        def _set_sqlite_pragma(dbapi_conn, _conn_record):
            if isinstance(dbapi_conn, sqlite3.Connection):
                cur = dbapi_conn.cursor()
                cur.execute(f"PRAGMA busy_timeout = {settings.DB_BUSY_TIMEOUT_MS}")
                cur.execute("PRAGMA journal_mode = WAL")
                cur.execute("PRAGMA synchronous = NORMAL")
                cur.execute("PRAGMA foreign_keys = ON")
                cur.close()
    else:
        # PostgreSQL / 其他
        _engine = create_engine(
            url,
            pool_size=settings.DB_POOL_SIZE,
            max_overflow=20,
            pool_pre_ping=True,
            future=True,
        )

    _SessionLocal = sessionmaker(
        bind=_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
        future=True,
    )

    logger.info(f"DB engine initialized: {_mask_db_url(url)}")
    return _engine


def get_engine() -> Engine:
    if _engine is None:
        return init_engine()
    return _engine


def get_session_factory() -> sessionmaker:
    if _SessionLocal is None:
        init_engine()
    assert _SessionLocal is not None
    return _SessionLocal


def get_db() -> Iterator[Session]:
    """FastAPI Dependency: 每请求一个 Session, 自动 close."""
    factory = get_session_factory()
    db = factory()
    try:
        yield db
    finally:
        db.close()


# ============================================================
# 健康检查
# ============================================================

def check_db() -> tuple[bool, str]:
    """简单 SELECT 1 探测."""
    try:
        eng = get_engine()
        with eng.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True, "ok"
    except Exception as ex:
        return False, f"{type(ex).__name__}: {ex}"
