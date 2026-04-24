# -*- coding: utf-8 -*-
"""Pipeline 配置 + 执行器 + 选剧 + 通知事件 REST API.

路由:
  GET    /config                   - 所有配置 (group 分类)
  GET    /config/{key}             - 单个配置
  PUT    /config/{key}             - 更新配置值 (body: {"value": ...})
  GET    /config/meta              - meta (类型/注释/默认值)

  GET    /selector/pool            - 候选池统计
  POST   /selector/pick            - 试选 (body: {account_id, n, strategy})

  GET    /executor/queue           - queue stats (各状态计数)
  GET    /executor/tasks           - 最近 N 个 task (query: limit, status)
  POST   /executor/enqueue         - enqueue PUBLISH (body: {account_id, drama})

  GET    /events                   - 最近 N 条 system_events (query: limit, level)
  POST   /notify                   - 手动发 1 条 (测试通知)
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.app_config import cfg, get as cfg_get
from core.drama_selector import select_for_account, pool_stats, STRATEGIES
from core.executor.account_executor import (
    enqueue_publish_task, queue_stats,
)
from core.notifier import notify
from core.config import DB_PATH

router = APIRouter()


def _connect():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.row_factory = sqlite3.Row
    return c


# ─── Config ────────────────────────────────────────────────────
@router.get("/config")
def list_configs():
    with _connect() as c:
        rows = c.execute(
            "SELECT config_key, config_value, updated_at FROM app_config ORDER BY config_key"
        ).fetchall()
        meta_rows = c.execute(
            "SELECT config_key, value_type, default_value, comment FROM app_config_meta"
        ).fetchall()
    meta = {r["config_key"]: dict(r) for r in meta_rows}
    out: dict[str, list] = {}
    for r in rows:
        group = r["config_key"].split(".")[0]
        item = {
            "key": r["config_key"],
            "value": r["config_value"],
            "updated_at": r["updated_at"],
            "meta": meta.get(r["config_key"], {}),
        }
        out.setdefault(group, []).append(item)
    return {"groups": out, "total": len(rows)}


@router.get("/config/{key:path}")
def get_config(key: str):
    value = cfg_get(key)
    if value is None:
        raise HTTPException(404, f"config key not found: {key}")
    return {"key": key, "value": value}


class ConfigUpdate(BaseModel):
    value: Any


@router.put("/config/{key:path}")
def update_config(key: str, body: ConfigUpdate):
    cfg().set(key, body.value)
    return {"ok": True, "key": key, "value": body.value}


# ─── Selector ──────────────────────────────────────────────────
@router.get("/selector/pool")
def get_pool():
    return pool_stats()


class PickRequest(BaseModel):
    account_id: int | None = None
    n: int = 5
    strategy: str = "top_weighted_random"


@router.post("/selector/pick")
def pick_dramas(body: PickRequest):
    if body.strategy not in STRATEGIES:
        raise HTTPException(400, f"unknown strategy; choose from {STRATEGIES}")
    picks = select_for_account(account_id=body.account_id, n=body.n,
                                 strategy=body.strategy)
    return {"count": len(picks), "picks": picks,
            "strategy": body.strategy, "account_id": body.account_id}


# ─── Executor ──────────────────────────────────────────────────
@router.get("/executor/queue")
def get_queue():
    return {"by_status": queue_stats(),
            "worker_count": cfg_get("executor.worker_count", 2)}


@router.get("/executor/tasks")
def list_tasks(limit: int = Query(50, ge=1, le=500),
               status: str | None = None):
    sql = """SELECT id, task_type, account_id, drama_name, priority, status,
                    retry_count, created_at, started_at, finished_at,
                    error_message, photo_id, banner_task_id, worker_name,
                    process_recipe, stage_updates_json
             FROM task_queue"""
    params: list = []
    if status:
        sql += " WHERE status = ?"
        params.append(status)
    sql += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)

    with _connect() as c:
        rows = c.execute(sql, params).fetchall()
    return {"count": len(rows), "tasks": [dict(r) for r in rows]}


class EnqueueRequest(BaseModel):
    account_id: int
    drama_name: str
    banner_task_id: str | None = None
    priority: int = 50
    batch_id: str = ""


@router.post("/executor/enqueue")
def enqueue(body: EnqueueRequest):
    tid = enqueue_publish_task(
        account_id=body.account_id, drama_name=body.drama_name,
        banner_task_id=body.banner_task_id, priority=body.priority,
        batch_id=body.batch_id,
    )
    return {"ok": True, "task_id": tid}


# ─── Events / Notify ───────────────────────────────────────────
@router.get("/events")
def list_events(limit: int = Query(100, ge=1, le=500),
                level: str | None = None,
                source: str | None = None):
    sql = """SELECT id, event_type, event_level, source_module,
                    entity_type, entity_id, payload, created_at, acknowledged
             FROM system_events WHERE 1=1"""
    params: list = []
    if level:
        sql += " AND event_level = ?"
        params.append(level)
    if source:
        sql += " AND source_module = ?"
        params.append(source)
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)

    with _connect() as c:
        rows = c.execute(sql, params).fetchall()
    out = []
    for r in rows:
        d = dict(r)
        try:
            d["payload"] = json.loads(d["payload"]) if d["payload"] else None
        except Exception:
            pass
        out.append(d)
    return {"count": len(out), "events": out}


class NotifyRequest(BaseModel):
    title: str
    body: str = ""
    level: str = "info"
    source: str = "api"


@router.post("/notify")
def manual_notify(body: NotifyRequest):
    r = notify(body.title, body.body, level=body.level, source=body.source,
               bypass_rate_limit=True)
    return r
