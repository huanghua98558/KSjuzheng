# -*- coding: utf-8 -*-
"""JSON API routes for SPA — full coverage 8 pages + bulk ops + Agent debug.

挂载方式: app.include_router(router, prefix='/api')
路由列表详见 ROUTE_DOCS.
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core.db_manager import DBManager
from core.data_insights import DataInsights
from core.incident_center import IncidentCenter
from core.switches import (
    get_all as switches_all,
    get_layered_tree,
    set_switch,
    bulk_set as switches_bulk_set,
    toggle_layer_master,
    cascade_off,
    recent_changes as switch_changes,
)
from core.agents import registry as agent_registry, debug as agent_debug
from core.agents.memory_consolidator import MemoryConsolidator
from core.config_center import cfg
from core.llm import LLMClient, LLM_PROVIDERS
from core.llm.prompts import PROMPTS


router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency
# ---------------------------------------------------------------------------

def _db() -> DBManager:
    return DBManager()


# ---------------------------------------------------------------------------
# Pydantic 模型 (POST 请求体用)
# ---------------------------------------------------------------------------

class BulkIdsBody(BaseModel):
    ids: list[Any] = Field(default_factory=list)
    operator: str = "dashboard"
    note: str = ""


class BulkSwitchesBody(BaseModel):
    codes: list[str] = Field(default_factory=list)
    value: bool
    operator: str = "dashboard"
    note: str = ""


class SwitchToggleBody(BaseModel):
    value: bool
    operator: str = "dashboard"


class TriggerAgentBody(BaseModel):
    payload: dict = Field(default_factory=dict)
    batch_id: str = ""
    account_id: str = ""
    respect_switch: bool = True


class ExperimentCreateBody(BaseModel):
    experiment_code: str
    experiment_name: str
    hypothesis: str = ""
    variable_name: str
    control_group: str = ""
    test_group: str = ""
    sample_target: int = 20
    success_metric: str = "total_plays"
    success_threshold: float = 1.2    # test 组比 control 高 >= 20%
    stop_condition: str = "sample>=target OR days>=7"
    created_by_agent: str = "manual"


class MemoryPinBody(BaseModel):
    pinned: bool


# ---------------------------------------------------------------------------
# 健康检查
# ---------------------------------------------------------------------------

@router.get("/health")
def health():
    return {"ok": True, "service": "ks-dashboard", "time": datetime.now().isoformat()}


# ============================================================================
#  总览 /home
# ============================================================================

@router.get("/home/overview")
def api_home_overview():
    db = _db()
    try:
        di = DataInsights(db)
        fv = di.build_feature_vector()
        ic = IncidentCenter(db)
        incident_sum = ic.summary()
        agent_sum = agent_debug.summary(db)

        # 最近 7 天每日发布数曲线
        publish_trend = db.conn.execute("""
            SELECT DATE(created_at) AS d,
                   SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) AS ok,
                   SUM(CASE WHEN publish_status='failed'  THEN 1 ELSE 0 END) AS fail
            FROM publish_results
            WHERE DATE(created_at) >= DATE('now','-7 days')
            GROUP BY DATE(created_at)
            ORDER BY d
        """).fetchall()

        # 最近 7 天账号日度播放总量
        plays_trend = db.conn.execute("""
            SELECT metric_date AS d, SUM(total_plays) AS plays, SUM(total_likes) AS likes
            FROM daily_account_metrics
            WHERE metric_date >= DATE('now','-7 days')
            GROUP BY metric_date ORDER BY d
        """).fetchall()

        # 最近 7 天 Agent 运行次数
        agent_trend = db.conn.execute("""
            SELECT DATE(created_at) AS d, COUNT(*) AS runs,
                   AVG(confidence) AS conf
            FROM agent_runs
            WHERE DATE(created_at) >= DATE('now','-7 days')
            GROUP BY DATE(created_at) ORDER BY d
        """).fetchall()

        return {
            "feature_vector": fv,
            "counts": fv.get("counts", {}),
            "matrix_summary": fv.get("matrix", {}).get("summary", {}),
            "keyword_heat": fv.get("market", {}).get("keyword_heat", [])[:10],
            "top_matrix_works": fv.get("matrix", {}).get("top_works", [])[:10],
            "income_today": fv.get("income", {}).get("today", [])[:10],
            "incident_summary": incident_sum,
            "agent_summary": agent_sum,
            "publish_trend": [
                {"date": r[0], "success": r[1] or 0, "failed": r[2] or 0}
                for r in publish_trend
            ],
            "plays_trend": [
                {"date": r[0], "plays": r[1] or 0, "likes": r[2] or 0}
                for r in plays_trend
            ],
            "agent_trend": [
                {"date": r[0], "runs": r[1] or 0,
                 "avg_confidence": round(r[2] or 0, 3)}
                for r in agent_trend
            ],
            "generated_at": datetime.now().isoformat(),
        }
    finally:
        db.close()


# ============================================================================
#  账号 /accounts
# ============================================================================

PLAN_ZH: dict[str, str] = {
    "firefly":  "萤光计划",
    "spark":    "星火计划",
    "nebula":   "极速版计划",
    "":         "未绑定",
}


@router.get("/accounts")
def api_accounts(
    only_logged_in: bool = True,
    health_max: Optional[float] = Query(None, description="只看健康度 <= X"),
    health_min: Optional[float] = Query(None, description="只看健康度 >= X"),
    bound_only: bool = False,
):
    """账号总览.

    关键修复: 账号有两种 uid (字符串 3xxxxxxx / 数字 88888888).
    MCN 数据只按数字 uid 索引, 所以字符串 uid 账号要走 account_name 匹配.
    全部用 Python 多路 merge, SQL 只拉原料.
    """
    db = _db()
    try:
        where_parts = []
        if only_logged_in:
            where_parts.append("da.login_status='logged_in'")
        where_sql = ("WHERE " + " AND ".join(where_parts)) if where_parts else ""

        # 1. 账号基础信息 + 生命周期 + 任务状态 + 等级/赛道 + 主人信息 (v30)
        # ★ 2026-04-21 bug fix: 加 numeric_uid 用于 MCN 匹配 (string↔numeric 双 ID 命名空间坑)
        rows = db.conn.execute(f"""
            SELECT
                da.id, da.account_name, da.kuaishou_uid, da.login_status,
                da.is_active, da.kuaishou_name,
                da.lifecycle_stage, da.tags_json, da.account_group,
                da.signed_status, da.signed_note, da.signed_updated_at,
                da.current_task_id, da.current_task_status,
                da.current_task_text, da.current_task_updated_at,
                da.avatar_url, da.device_serial,
                da.account_level, da.first_published_at,
                da.account_age_days, da.vertical_category, da.vertical_locked,
                da.owner_phone, da.owner_real_name,
                da.mcn_last_invite_at, da.mcn_last_invite_status,
                da.nickname_suggestions_json, da.numeric_uid,
                (SELECT health_score FROM account_health_snapshots
                    WHERE account_id = da.kuaishou_uid
                    ORDER BY snapshot_date DESC LIMIT 1) AS health,
                (SELECT risk_score FROM account_health_snapshots
                    WHERE account_id = da.kuaishou_uid
                    ORDER BY snapshot_date DESC LIMIT 1) AS risk,
                (SELECT publish_fail_count_7d FROM account_health_snapshots
                    WHERE account_id = da.kuaishou_uid
                    ORDER BY snapshot_date DESC LIMIT 1) AS fail7d,
                (SELECT total_plays FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                    ORDER BY metric_date DESC LIMIT 1) AS plays,
                (SELECT plays_delta FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                    ORDER BY metric_date DESC LIMIT 1) AS plays_delta,
                -- ★ 2026-04-20: 真实 today_delta (今日 00:xx 起增量) 从 hourly_metrics_snapshots 算
                (SELECT today_delta FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                      AND metric_date = date('now','localtime')
                    LIMIT 1) AS today_delta,
                (SELECT yesterday_delta FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                      AND metric_date = date('now','localtime')
                    LIMIT 1) AS yesterday_delta,
                (SELECT total_likes FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                    ORDER BY metric_date DESC LIMIT 1) AS likes,
                (SELECT fans FROM daily_account_metrics
                    WHERE kuaishou_uid = da.kuaishou_uid
                    ORDER BY metric_date DESC LIMIT 1) AS fans_dm
            FROM device_accounts da
            {where_sql}
        """).fetchall()
        acct_cols = ["id","account_name","kuaishou_uid","login_status","is_active",
                     "kuaishou_name","lifecycle_stage","tags_json","account_group",
                     "signed_status","signed_note","signed_updated_at",
                     "current_task_id","current_task_status",
                     "current_task_text","current_task_updated_at",
                     "avatar_url","device_serial",
                     "account_level","first_published_at",
                     "account_age_days","vertical_category","vertical_locked",
                     "owner_phone","owner_real_name",
                     "mcn_last_invite_at","mcn_last_invite_status",
                     "nickname_suggestions_json","numeric_uid",   # ★ 2026-04-21 fix
                     "health","risk","fail7d","plays","plays_delta",
                     "today_delta","yesterday_delta",
                     "likes","fans_dm"]
        accounts = [dict(zip(acct_cols, r)) for r in rows]
        for a in accounts:
            try:
                a["tags"] = json.loads(a.get("tags_json") or "[]")
            except Exception:
                a["tags"] = []
            a.pop("tags_json", None)

        # 2. MCN 最新快照 (★ 2026-04-21 fix: 用 numeric_uid + member_id 做 key,
        #    不再依赖 kuaishou_uid (string↔numeric 命名空间不一致))
        mcn_by_numeric: dict[int, dict] = {}   # numeric_uid key (主键, 100% 匹配)
        mcn_by_name: dict[str, dict] = {}       # member_name key (备用)
        try:
            mcn_rows = db.conn.execute("""
                SELECT kuaishou_uid, member_id, total_amount,
                       commission_amount, commission_rate, raw_response_json
                FROM mcn_income_snapshots
                WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM mcn_income_snapshots)
            """).fetchall()
        except Exception:
            mcn_rows = []
        for m in mcn_rows:
            uid, member_id, total, commission, rate, raw = m
            member_name = ""
            fans_mcn = 0
            org_name = ""
            try:
                j = json.loads(raw or "{}")
                member = j.get("member") or {}
                member_name = member.get("member_name") or ""
                fans_mcn = int(member.get("fans_count") or 0)
                org_name = member.get("org_name") or ""
            except Exception:
                pass
            data = {
                "mcn_uid_num": uid,
                "mcn_member_id": member_id,
                "mcn_member_name": member_name,
                "mcn_total_amount": round(float(total or 0), 2),
                "mcn_commission_amount": round(float(commission or 0), 3),
                "commission_rate": float(rate or 0),
                "mcn_fans": fans_mcn,
                "mcn_org_name": org_name,
            }
            # 这两个字段在 mcn_income_snapshots 里 "kuaishou_uid" 和 "member_id"
            # 都是 numeric_uid (同一个值, 只是列名不同). 用 int key:
            for candidate_numeric in (uid, member_id):
                try:
                    nk = int(candidate_numeric)
                    if nk > 0:
                        mcn_by_numeric[nk] = data
                except Exception:
                    pass
            if member_name:
                mcn_by_name[member_name] = data

        # 3. 基础绑定表 (给 plan_type) — 这个表的 kuaishou_uid 存 string 格式 (和 device_accounts 一致)
        bindings_rows = db.conn.execute("""
            SELECT kuaishou_uid, account_name, plan_type, last_verified_at
            FROM mcn_account_bindings
        """).fetchall()
        bind_by_uid = {str(r[0]): r for r in bindings_rows if r[0]}   # string key
        bind_by_name = {r[1]: r for r in bindings_rows if r[1]}

        # 4. Merge
        for a in accounts:
            uid = str(a["kuaishou_uid"] or "")
            name = a["account_name"] or ""
            ks_name = a["kuaishou_name"] or ""
            nuid = a.get("numeric_uid")   # ★ int, 2026-04-21 修 MCN 匹配 bug

            # ★ 2026-04-21 fix: 改用 numeric_uid 作为 MCN 匹配 key (100% 可靠)
            mcn = None
            if nuid:
                try:
                    mcn = mcn_by_numeric.get(int(nuid))
                except Exception:
                    pass
            if not mcn:
                # fallback 1: member_name 精确匹配 (MCN 的 member_name == device.account_name 有时成立)
                mcn = mcn_by_name.get(name) or mcn_by_name.get(ks_name)
            if mcn:
                a["mcn_member_id"] = mcn["mcn_member_id"]
                a["mcn_member_name"] = mcn["mcn_member_name"]
                a["mcn_uid_num"] = mcn["mcn_uid_num"]
                a["mcn_total_amount"] = mcn["mcn_total_amount"]
                a["mcn_commission_amount"] = mcn["mcn_commission_amount"]
                a["commission_rate"] = mcn["commission_rate"]
                a["fans"] = mcn["mcn_fans"] or a.get("fans_dm") or 0
                a["mcn_org_name"] = mcn["mcn_org_name"]
                a["avatar_url"] = a.get("avatar_url") or mcn.get("mcn_avatar") or ""
            else:
                a["mcn_member_id"] = None
                a["mcn_member_name"] = ""
                a["mcn_uid_num"] = ""
                a["mcn_total_amount"] = 0
                a["mcn_commission_amount"] = 0
                a["commission_rate"] = 0
                a["fans"] = a.get("fans_dm") or 0
                a["mcn_org_name"] = ""
            a.pop("fans_dm", None)

            bind = bind_by_uid.get(uid) or bind_by_name.get(name) or bind_by_name.get(ks_name)
            plan_raw = bind[2] if bind else ""
            a["plan_type"] = plan_raw or ""
            a["plan_type_zh"] = PLAN_ZH.get(plan_raw or "", plan_raw or "未绑定")
            a["mcn_verified_at"] = bind[3] if bind else None

        # 5. 筛选
        if health_max is not None:
            accounts = [a for a in accounts if (a["health"] or 0) <= health_max]
        if health_min is not None:
            accounts = [a for a in accounts if (a["health"] or 0) >= health_min]
        if bound_only:
            accounts = [a for a in accounts if a["commission_rate"] > 0]

        # 6. 排序 (健康度 > 播放)
        accounts.sort(key=lambda a: (
            -(a.get("health") or 0),
            -(a.get("plays") or 0),
        ))

        return {"accounts": accounts, "total": len(accounts)}
    finally:
        db.close()


class RefreshBody(BaseModel):
    include_mcn: bool = True
    include_metrics: bool = True
    operator: str = "dashboard"


class StageBody(BaseModel):
    stage: str  # test/startup/active/viral/dormant


class TagsBody(BaseModel):
    tags: list[str]


class GroupBody(BaseModel):
    group: str


class BulkAccountBody(BaseModel):
    ids: list[int]
    action: str  # set_stage/set_group/add_tag/remove_tag/invite/delete
    value: Any = None
    operator: str = "dashboard"


@router.api_route("/accounts/refresh", methods=["GET", "POST"])
async def api_accounts_refresh(request: Request):
    """一键刷新账号全量数据 (GET/POST 都接受, 兼容浏览器缓存旧 JS).

    执行 (可选择组合):
      1. sync_mcn_business.sync_account_bindings  -> 从云端拉 MCN 绑定
      2. sync_mcn_business.sync_members           -> 覆盖 commission_rate
      3. sync_mcn_business.snapshot_daily_income  -> 今日收入快照
      4. data_collector.snapshot_all_accounts     -> 每日指标 (可选)

    同步执行 (30-60s), 适合手动触发. 未来改异步 + SSE 推进度.
    """
    import time
    # 兼容 GET (默认参数) + POST (body)
    if request.method == "POST":
        try:
            raw = await request.json()
            body = RefreshBody(**(raw or {}))
        except Exception:
            body = RefreshBody()
    else:
        body = RefreshBody()
    t0 = time.time()
    steps = []
    db = _db()
    try:
        if body.include_mcn:
            try:
                from core.mcn_business import MCNBusiness
                biz = MCNBusiness(db)
                t1 = time.time()
                n1 = biz.sync_account_bindings()
                steps.append({
                    "name": "MCN 绑定同步", "ok": True, "count": n1,
                    "latency_ms": int((time.time() - t1) * 1000),
                })
                t2 = time.time()
                n2 = biz.sync_members()
                steps.append({
                    "name": "萤光成员同步 (含佣金率)", "ok": True, "count": n2,
                    "latency_ms": int((time.time() - t2) * 1000),
                })
                t3 = time.time()
                n3 = biz.snapshot_daily_income()
                steps.append({
                    "name": "今日收入快照", "ok": True, "count": n3,
                    "latency_ms": int((time.time() - t3) * 1000),
                })
            except Exception as e:
                steps.append({
                    "name": "MCN 同步", "ok": False, "error": str(e)[:200],
                })

        if body.include_metrics:
            try:
                from core.cookie_manager import CookieManager
                from core.data_collector import DataCollector
                cm = CookieManager(db)
                dc = DataCollector(db, cm)
                t4 = time.time()
                res = dc.snapshot_all_accounts()
                ok_n = res.get("accounts_processed", 0) if isinstance(res, dict) else 0
                failed = res.get("accounts_failed", 0) if isinstance(res, dict) else 0
                steps.append({
                    "name": "每日指标采集",
                    "ok": failed == 0,
                    "count": ok_n,
                    "failed": failed,
                    "latency_ms": int((time.time() - t4) * 1000),
                })
            except Exception as e:
                steps.append({
                    "name": "每日指标采集", "ok": False, "error": str(e)[:200],
                })

        # 审计
        try:
            db.conn.execute(
                """INSERT INTO dashboard_bulk_ops
                     (op_code, target_type, target_ids_json, params_json,
                      affected_count, operator, note)
                   VALUES ('refresh_accounts', 'account', '[]', ?, ?, ?, ?)""",
                (
                    json.dumps({"include_mcn": body.include_mcn,
                                "include_metrics": body.include_metrics},
                               ensure_ascii=False),
                    sum(s.get("count", 0) for s in steps),
                    body.operator,
                    f"refreshed {len(steps)} steps",
                ),
            )
            db.conn.commit()
        except Exception:
            pass

        total_latency = int((time.time() - t0) * 1000)
        return {
            "ok": all(s.get("ok") for s in steps),
            "steps": steps,
            "total_latency_ms": total_latency,
            "operator": body.operator,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 账号: 统计 / 分组 / 标签 / 生命周期
# ---------------------------------------------------------------------------

@router.get("/accounts/stats")
def api_accounts_stats():
    """各维度统计 - 给"统计视图"用."""
    db = _db()
    try:
        # 生命周期分布
        lifecycle_rows = db.conn.execute("""
            SELECT s.stage_code, s.stage_name, s.color, s.description,
                   COUNT(da.id) AS count
            FROM account_lifecycle_stages s
            LEFT JOIN device_accounts da
              ON da.lifecycle_stage = s.stage_code
                 AND da.login_status = 'logged_in'
            GROUP BY s.stage_code
            ORDER BY s.sort_order
        """).fetchall()
        lifecycle = [
            {"code": r[0], "name": r[1], "color": r[2], "desc": r[3], "count": r[4]}
            for r in lifecycle_rows
        ]

        # 签约分布
        signed_rows = db.conn.execute("""
            SELECT signed_status, COUNT(*)
            FROM device_accounts WHERE login_status='logged_in'
            GROUP BY signed_status
        """).fetchall()
        signed = {r[0]: r[1] for r in signed_rows}

        # 健康度分布
        health_rows = db.conn.execute("""
            SELECT CASE
              WHEN h.health_score >= 80 THEN 'good'
              WHEN h.health_score >= 70 THEN 'normal'
              WHEN h.health_score >= 50 THEN 'warn'
              ELSE 'danger'
            END AS bucket, COUNT(*) AS c
            FROM device_accounts da
            LEFT JOIN account_health_snapshots h
              ON h.account_id = da.kuaishou_uid
              AND h.snapshot_date = (SELECT MAX(snapshot_date) FROM account_health_snapshots)
            WHERE da.login_status='logged_in'
            GROUP BY bucket
        """).fetchall()
        health = {r[0] or "unknown": r[1] for r in health_rows}

        # 分组
        group_rows = db.conn.execute("""
            SELECT COALESCE(NULLIF(account_group,''), '(未分组)') AS g, COUNT(*)
            FROM device_accounts WHERE login_status='logged_in'
            GROUP BY g ORDER BY COUNT(*) DESC
        """).fetchall()
        groups = [{"name": r[0], "count": r[1]} for r in group_rows]

        # 任务状态
        task_rows = db.conn.execute("""
            SELECT COALESCE(current_task_status, 'idle'), COUNT(*)
            FROM device_accounts WHERE login_status='logged_in'
            GROUP BY current_task_status
        """).fetchall()
        tasks = {r[0]: r[1] for r in task_rows}

        return {
            "lifecycle": lifecycle,
            "signed": signed,
            "health": health,
            "groups": groups,
            "tasks": tasks,
        }
    finally:
        db.close()


@router.get("/accounts/groups")
def api_accounts_groups():
    db = _db()
    try:
        rows = db.conn.execute(
            "SELECT id, name, description, color FROM account_groups ORDER BY id"
        ).fetchall()
        return {"groups": [{"id": r[0], "name": r[1],
                            "description": r[2], "color": r[3]} for r in rows]}
    finally:
        db.close()


@router.get("/accounts/tags")
def api_accounts_tags():
    db = _db()
    try:
        rows = db.conn.execute(
            "SELECT id, name, color, scope FROM account_tags ORDER BY name"
        ).fetchall()
        return {"tags": [{"id": r[0], "name": r[1], "color": r[2], "scope": r[3]}
                         for r in rows]}
    finally:
        db.close()


@router.get("/accounts/lifecycle")
def api_accounts_lifecycle():
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT stage_code, stage_name, color, description, sort_order
               FROM account_lifecycle_stages ORDER BY sort_order"""
        ).fetchall()
        return {"stages": [{"code": r[0], "name": r[1], "color": r[2],
                            "description": r[3], "sort_order": r[4]} for r in rows]}
    finally:
        db.close()


@router.post("/accounts/{account_id}/stage")
def api_account_set_stage(account_id: int, body: StageBody):
    db = _db()
    try:
        cur = db.conn.execute(
            "UPDATE device_accounts SET lifecycle_stage=? WHERE id=?",
            (body.stage, account_id),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0, "new_stage": body.stage}
    finally:
        db.close()


@router.post("/accounts/{account_id}/tags")
def api_account_set_tags(account_id: int, body: TagsBody):
    db = _db()
    try:
        cur = db.conn.execute(
            "UPDATE device_accounts SET tags_json=? WHERE id=?",
            (json.dumps(body.tags, ensure_ascii=False), account_id),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0, "tags": body.tags}
    finally:
        db.close()


@router.post("/accounts/{account_id}/group")
def api_account_set_group(account_id: int, body: GroupBody):
    db = _db()
    try:
        cur = db.conn.execute(
            "UPDATE device_accounts SET account_group=? WHERE id=?",
            (body.group, account_id),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0, "group": body.group}
    finally:
        db.close()


@router.post("/accounts/bulk-action")
def api_accounts_bulk(body: BulkAccountBody):
    """批量操作: set_stage / set_group / add_tag / remove_tag / delete"""
    if not body.ids:
        return {"affected": 0}
    db = _db()
    try:
        affected = 0
        placeholders = ",".join("?" for _ in body.ids)

        if body.action == "set_stage":
            cur = db.conn.execute(
                f"UPDATE device_accounts SET lifecycle_stage=? WHERE id IN ({placeholders})",
                (body.value, *body.ids),
            )
            affected = cur.rowcount

        elif body.action == "set_group":
            cur = db.conn.execute(
                f"UPDATE device_accounts SET account_group=? WHERE id IN ({placeholders})",
                (body.value or "", *body.ids),
            )
            affected = cur.rowcount

        elif body.action in ("add_tag", "remove_tag"):
            rows = db.conn.execute(
                f"SELECT id, tags_json FROM device_accounts WHERE id IN ({placeholders})",
                body.ids,
            ).fetchall()
            for aid, tj in rows:
                try:
                    tags = json.loads(tj or "[]")
                except Exception:
                    tags = []
                if body.action == "add_tag":
                    if body.value and body.value not in tags:
                        tags.append(body.value)
                else:
                    tags = [t for t in tags if t != body.value]
                db.conn.execute(
                    "UPDATE device_accounts SET tags_json=? WHERE id=?",
                    (json.dumps(tags, ensure_ascii=False), aid),
                )
                affected += 1

        elif body.action == "delete":
            cur = db.conn.execute(
                f"DELETE FROM device_accounts WHERE id IN ({placeholders})",
                body.ids,
            )
            affected = cur.rowcount

        else:
            raise HTTPException(400, f"未知 action: {body.action}")

        db.conn.commit()
        # 审计
        db.conn.execute(
            """INSERT INTO dashboard_bulk_ops
                 (op_code, target_type, target_ids_json, params_json,
                  affected_count, operator, note)
               VALUES (?, 'account', ?, ?, ?, ?, ?)""",
            (
                f"account_{body.action}",
                json.dumps(body.ids),
                json.dumps({"action": body.action, "value": body.value},
                           ensure_ascii=False),
                affected, body.operator,
                f"{body.action} × {len(body.ids)} accounts",
            ),
        )
        db.conn.commit()
        return {"affected": affected, "requested": len(body.ids)}
    finally:
        db.close()


class OwnerBody(BaseModel):
    owner_phone: str
    owner_real_name: str


@router.post("/accounts/{account_id}/owner")
def api_account_set_owner(account_id: int, body: OwnerBody):
    """填主人手机 + 真实姓名 (MCN direct_invite 强制要求).

    2026-04-21 用户要求: 规范化加号+邀请流程. 这是邀请前的必填一步.
    """
    phone = (body.owner_phone or "").strip()
    name = (body.owner_real_name or "").strip()
    if not phone or len(phone) < 6:
        raise HTTPException(400, "手机号不合法")
    if not name:
        raise HTTPException(400, "真实姓名不能为空")

    db = _db()
    try:
        r = db.conn.execute(
            "SELECT id FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        db.conn.execute(
            """UPDATE device_accounts SET
                 owner_phone=?, owner_real_name=?,
                 owner_filled_at=datetime('now','localtime')
               WHERE id=?""",
            (phone, name, account_id),
        )
        db.conn.commit()
        try:
            from core.event_bus import emit_event
            emit_event("account.owner_filled",
                       entity_type="account", entity_id=str(account_id),
                       payload={"phone_mask": phone[:3] + "***", "name": name},
                       source_module="dashboard_api")
        except Exception:
            pass
        return {"ok": True, "account_id": account_id,
                "phone_mask": phone[:3] + "***" + phone[-2:],
                "owner_real_name": name}
    finally:
        db.close()


@router.post("/accounts/{account_id}/invite")
def api_account_invite(account_id: int):
    """触发 MCN 邀请 (账号未加入机构时).

    2026-04-21 重写: 走 MCNBusiness.invite_and_persist() 同步写 mcn_invitations
    账本 + 回写 device_accounts.mcn_last_invite_at/status.

    要求: 账号必须已填 owner_phone + owner_real_name (调 /accounts/{id}/owner).
    """
    db = _db()
    try:
        row = db.conn.execute(
            """SELECT kuaishou_uid, numeric_uid, account_name, kuaishou_name,
                      owner_phone, owner_real_name
               FROM device_accounts WHERE id=?""",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        ks_uid, num_uid, acc_name, ks_name, phone, real_name = row

        # MCN direct_invite 要 numeric_uid (纯数字), 不是 kuaishou_uid 的字符串格式
        invite_uid = str(num_uid) if num_uid else str(ks_uid or "")
        if not invite_uid or not invite_uid.isdigit():
            return {"ok": False,
                    "error": "numeric_uid 缺失, 邀请需要纯数字 UID (cookie 回填或 MCN 同步后获取)"}
        if not phone or not real_name:
            return {"ok": False, "error": "需先填主人手机 + 真实姓名 (POST /accounts/{id}/owner)"}

        try:
            from core.mcn_business import MCNBusiness
            biz = MCNBusiness(db)
            note = f"{real_name}-{acc_name or ks_name or invite_uid}"
            resp = biz.invite_and_persist(
                target_uid=invite_uid,
                phone=phone,
                note=note,
                contract_month=36,
                organization_id=10,
            )
            # 回写 device_accounts.mcn_last_invite_at/status
            success = bool(resp.get("success"))
            from datetime import datetime as _dt
            db.conn.execute(
                """UPDATE device_accounts SET
                     mcn_last_invite_at=?, mcn_last_invite_status=?
                   WHERE id=?""",
                (_dt.now().strftime("%Y-%m-%d %H:%M:%S"),
                 "success" if success else "failed", account_id),
            )
            db.conn.commit()
            return {"ok": success, "result": resp, "account_id": account_id,
                    "target_uid": invite_uid}
        except Exception as e:
            return {"ok": False, "error": str(e)[:400]}
    finally:
        db.close()


@router.get("/invitations")
def api_invitations_list(status: str = "all", limit: int = 100):
    """列邀请账本 (含账号名 + 签约状态).

    status ∈ {all, pending, signed, failed, need_owner}
    """
    db = _db()
    try:
        sql = """
          SELECT i.id, i.target_kuaishou_uid, i.target_phone, i.note,
                 i.invited_at, i.signed_status, i.signed_at, i.member_id,
                 i.last_polled_at,
                 da.id, da.account_name, da.kuaishou_name
          FROM mcn_invitations i
          LEFT JOIN device_accounts da
            ON CAST(i.target_kuaishou_uid AS TEXT) = CAST(da.numeric_uid AS TEXT)
               OR i.target_kuaishou_uid = da.kuaishou_uid
        """
        params: list = []
        if status == "pending":
            sql += " WHERE i.signed_status='pending' OR i.signed_status IS NULL"
        elif status == "signed":
            sql += " WHERE i.signed_status='signed'"
        elif status == "failed":
            sql += " WHERE i.signed_status NOT IN ('pending','signed') " \
                   "AND i.signed_status IS NOT NULL"
        sql += " ORDER BY i.id DESC LIMIT ?"
        params.append(int(limit))

        rows = db.conn.execute(sql, params).fetchall()
        items = []
        for r in rows:
            items.append({
                "id": r[0], "target_uid": r[1], "target_phone": r[2],
                "note": r[3], "invited_at": r[4], "signed_status": r[5],
                "signed_at": r[6], "member_id": r[7], "last_polled_at": r[8],
                "account_id": r[9], "account_name": r[10], "kuaishou_name": r[11],
            })

        # 另加 need_owner 列表 (活跃 + 无 owner_phone 的 device_accounts)
        if status in ("all", "need_owner"):
            need_owner = db.conn.execute(
                """SELECT id, account_name, kuaishou_name, numeric_uid, login_status
                   FROM device_accounts
                   WHERE (login_status='logged_in' OR login_status IS NULL)
                     AND (owner_phone IS NULL OR owner_phone='')
                     AND numeric_uid IS NOT NULL
                   ORDER BY id"""
            ).fetchall()
        else:
            need_owner = []

        return {
            "invitations": items,
            "need_owner_accounts": [
                {"account_id": r[0], "account_name": r[1], "kuaishou_name": r[2],
                 "numeric_uid": r[3], "login_status": r[4]}
                for r in need_owner
            ],
            "total": len(items),
        }
    finally:
        db.close()


@router.post("/invitations/{invitation_id}/poll")
def api_invitation_poll(invitation_id: int):
    """手动触发一次签约状态查询 (调 MCN /api/accounts/invitation-records)."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT target_kuaishou_uid FROM mcn_invitations WHERE id=?",
            (invitation_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "邀请记录不存在")
        target_uid = row[0]
        try:
            from core.mcn_business import MCNBusiness
            biz = MCNBusiness(db)
            resp = biz.poll_invitation_status(target_uid)
            # 重读最新行
            updated = db.conn.execute(
                """SELECT signed_status, signed_at, member_id, last_polled_at
                   FROM mcn_invitations WHERE id=?""",
                (invitation_id,),
            ).fetchone()
            return {
                "ok": True,
                "signed_status": updated[0] if updated else None,
                "signed_at": updated[1] if updated else None,
                "member_id": updated[2] if updated else None,
                "last_polled_at": updated[3] if updated else None,
                "raw_response_summary": {
                    "record_count": len((resp or {}).get("data") or []),
                },
            }
        except Exception as e:
            return {"ok": False, "error": str(e)[:300]}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 账号: 记录 / 链接 / 收藏库 (数据抽屉)
# ---------------------------------------------------------------------------

@router.get("/accounts/{account_id}/records")
def api_account_records(account_id: int, limit: int = 50):
    """该账号的发布/执行历史."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT kuaishou_uid FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid = row[0]
        # account_drama_execution_logs
        logs = db.conn.execute(
            """SELECT id, drama_name, drama_url, status, publish_mode,
                      photo_id, verified_at, created_at
               FROM account_drama_execution_logs
               WHERE kuaishou_uid = ?
               ORDER BY id DESC LIMIT ?""",
            (uid, limit),
        ).fetchall()
        return {
            "records": [
                {"id": r[0], "drama_name": r[1], "drama_url": r[2],
                 "status": r[3], "publish_mode": r[4], "photo_id": r[5],
                 "verified_at": r[6], "created_at": r[7]}
                for r in logs
            ],
            "account_id": account_id,
        }
    finally:
        db.close()


@router.get("/accounts/{account_id}/links")
def api_account_links(account_id: int, limit: int = 50):
    """该账号挂载的分销链接 + 已发布作品."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT kuaishou_uid FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid = row[0]
        # account_published_works
        works = []
        try:
            works = [
                {"id": r[0], "photo_id": r[1], "drama_name": r[2],
                 "share_url": r[3], "published_at": r[4]}
                for r in db.conn.execute(
                    """SELECT id, photo_id, drama_name, share_url, published_at
                       FROM account_published_works WHERE kuaishou_uid=?
                       ORDER BY id DESC LIMIT ?""",
                    (uid, limit),
                ).fetchall()
            ]
        except Exception:
            pass
        # publish_results
        publishes = []
        try:
            publishes = [
                {"id": r[0], "drama_name": r[1], "channel": r[2],
                 "publish_status": r[3], "share_url": r[4],
                 "created_at": r[5]}
                for r in db.conn.execute(
                    """SELECT id, drama_name, channel_type, publish_status,
                              share_url, created_at
                       FROM publish_results WHERE account_id=?
                       ORDER BY id DESC LIMIT ?""",
                    (uid, limit),
                ).fetchall()
            ]
        except Exception:
            pass
        return {
            "account_id": account_id,
            "works": works,
            "publishes": publishes,
        }
    finally:
        db.close()


@router.get("/accounts/{account_id}/collections")
def api_account_collections(account_id: int, limit: int = 100):
    """该账号的 drama 收藏库 (drama_links 里本账号相关的)."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT kuaishou_uid FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid = row[0]
        # collect-pool 里该账号抓过的剧 (source_file LIKE 'collect-pool:uid%')
        collections = []
        try:
            collections = [
                {"id": r[0], "drama_name": r[1], "drama_url": r[2],
                 "status": r[3], "use_count": r[4], "created_at": r[5]}
                for r in db.conn.execute(
                    """SELECT id, drama_name, drama_url, status, use_count, created_at
                       FROM drama_links
                       WHERE source_file LIKE ?
                       ORDER BY id DESC LIMIT ?""",
                    (f"collect-pool:{uid}%", limit),
                ).fetchall()
            ]
        except Exception:
            pass
        return {
            "account_id": account_id,
            "collections": collections,
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 账号: 通过 Cookie 添加新账号 (脱离 KS184)
# ---------------------------------------------------------------------------

class CookieAddBody(BaseModel):
    cookie_string: str = ""          # 字符串 "k=v; k=v"
    cookie_json: Any | None = None   # Chrome JSON 数组, 或任何 parser 能认
    cookie_raw: str = ""             # 任意格式 (parser 自动探测)
    account_name: str = ""
    kuaishou_uid: str = ""           # 可选 (不填自动提取 userId)
    lifecycle_stage: str = "startup"
    validate: bool = True            # 是否在入库前调 cp API 验证


class CookiePreviewBody(BaseModel):
    raw: Any                         # 字符串/JSON/数组, parser 自动处理


class ValidateCookieBody(BaseModel):
    cookie_string: str = ""
    cookie_json: Any | None = None
    cookie_raw: str = ""


@router.post("/accounts/cookie-preview")
def api_account_cookie_preview(body: CookiePreviewBody):
    """解析 cookie 不入库, 返回格式识别 + suite 分布 + key cookie 缺失提示."""
    from core.cookie_parser import preview
    return preview(body.raw)


@router.post("/accounts/validate-cookie")
def api_account_validate_cookie(body: ValidateCookieBody):
    """验证 cookie 是否有效 (调 cp API)."""
    from core.cookie_parser import build_account_cookies_json
    raw = body.cookie_raw or body.cookie_json or body.cookie_string
    if not raw:
        raise HTTPException(400, "请提供 cookie")
    data = build_account_cookies_json(raw, login_method="validate_only")
    if not data:
        return {"ok": False, "reason": "cookie 解析失败"}
    from core.cookie_validator import validate_cookie_string
    return validate_cookie_string(
        data.get("creator_cookie") or data.get("cookies", [{}])[0].get("value", "")
    )


@router.post("/accounts/add-by-cookie")
def api_account_add_by_cookie(body: CookieAddBody):
    """用 Cookie 添加新账号 — 支持所有主流格式 + 可选验证."""
    import json as _json
    from core.cookie_parser import build_account_cookies_json, extract_user_id
    from core.cookie_validator import validate_cookie_string

    # 合并 raw
    raw = body.cookie_raw or body.cookie_json or body.cookie_string
    if not raw:
        raise HTTPException(400, "必须提供 cookie_raw / cookie_string / cookie_json 其一")

    # 规范化成 device_accounts.cookies JSON
    cookies_data = build_account_cookies_json(raw, login_method="cookie_import")
    if not cookies_data or not cookies_data.get("cookies") and not any(
        cookies_data.get(k) for k in
        ("creator_cookie", "shop_cookie", "niu_cookie", "official_cookie")
    ):
        raise HTTPException(400, "cookie 解析为空, 请检查格式")

    # 提取 userId
    uid = body.kuaishou_uid.strip() or extract_user_id(raw)
    if not uid:
        raise HTTPException(400, "cookie 中未包含 userId, 请手工填写 kuaishou_uid")

    # 可选验证
    validation: dict = {"ok": None}
    if body.validate:
        validation = validate_cookie_string(
            cookies_data.get("creator_cookie", "")
        )
        if validation.get("ok"):
            cookies_data["user_info"] = {
                "userId": validation.get("user_id") or uid,
                "userName": validation.get("user_name") or "",
                "userHead": validation.get("user_avatar") or "",
            }

    name = (body.account_name.strip()
            or validation.get("user_name")
            or f"acct_{uid}")
    avatar = validation.get("user_avatar", "")

    db = _db()
    try:
        cookies_blob = _json.dumps(cookies_data, ensure_ascii=False)
        existing = db.conn.execute(
            "SELECT id FROM device_accounts WHERE kuaishou_uid=?", (uid,)
        ).fetchone()
        if existing:
            db.conn.execute(
                """UPDATE device_accounts SET
                     cookies=?,
                     login_status='logged_in',
                     cookie_last_success_at=datetime('now','localtime'),
                     lifecycle_stage=?,
                     avatar_url=COALESCE(NULLIF(avatar_url,''), ?)
                   WHERE kuaishou_uid=?""",
                (cookies_blob, body.lifecycle_stage, avatar, uid),
            )
            db.conn.commit()
            return {
                "ok": True, "action": "updated",
                "id": existing[0], "uid": uid,
                "validation": validation,
            }
        # ★ 2026-04-23 Bug 5 修复: device_serial + account_id NOT NULL 漏了.
        # 与 browser_qrlogin 同步修法: no_device + acc_{sha1[:8]}
        import hashlib
        account_id_legacy = f"acc_{hashlib.sha1(str(uid).encode()).hexdigest()[:8]}"
        try:
            numeric_uid = int(uid) if str(uid).isdigit() else 0
        except (TypeError, ValueError):
            numeric_uid = 0
        cur = db.conn.execute(
            """INSERT INTO device_accounts
                 (device_serial, account_id,
                  account_name, kuaishou_uid, kuaishou_name, numeric_uid,
                  login_status, is_active, cookies,
                  cookie_last_success_at, lifecycle_stage,
                  signed_status, avatar_url)
               VALUES ('no_device', ?,
                       ?, ?, ?, ?, 'logged_in', 1, ?,
                       datetime('now','localtime'), ?, 'unknown', ?)""",
            (account_id_legacy,
             name, uid, name, numeric_uid, cookies_blob,
             body.lifecycle_stage, avatar),
        )
        db.conn.commit()
        return {
            "ok": True, "action": "created",
            "id": cur.lastrowid, "uid": uid, "name": name,
            "account_id": account_id_legacy,
            "validation": validation,
        }
    finally:
        db.close()


@router.get("/accounts/{account_id}/export-cookies")
def api_account_export_cookies(account_id: int,
                                format: str = Query("json",
                                                    description="json/string/chrome")):
    """导出账号 cookie (JSON 规范格式 / 字符串 / Chrome 扩展格式)."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT cookies, account_name FROM device_accounts WHERE id=?",
            (account_id,),
        ).fetchone()
        if not row or not row[0]:
            raise HTTPException(404, "账号或 cookies 不存在")
        try:
            data = json.loads(row[0])
        except Exception:
            data = None
        if format == "json":
            return {"format": "device_accounts.cookies",
                    "account_name": row[1], "data": data}
        if format == "string":
            if isinstance(data, dict):
                return {"cookie_string": data.get("creator_cookie", ""),
                        "account_name": row[1]}
            return {"cookie_string": row[0] if isinstance(row[0], str) else "",
                    "account_name": row[1]}
        if format == "chrome":
            # Chrome 扩展可直接导入的格式
            if isinstance(data, dict):
                return {"format": "chrome_extension",
                        "cookies": data.get("cookies", [])}
            return {"format": "chrome_extension", "cookies": []}
        raise HTTPException(400, "format 只接受 json/string/chrome")
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 浏览器会话管理 + 浏览器登录
# ---------------------------------------------------------------------------

class BrowserLoginBody(BaseModel):
    login_url_code: str = "cp"   # cp / www / pass
    headless: bool = False


@router.get("/accounts/browser-sessions")
def api_accounts_browser_sessions():
    """列当前打开的 Chrome 窗口 (browser_sessions 表)."""
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT bs.id, bs.account_id, bs.pid, bs.port,
                      bs.target_url, bs.status, bs.started_at,
                      da.account_name, da.kuaishou_uid
               FROM browser_sessions bs
               LEFT JOIN device_accounts da ON da.id = bs.account_id
               WHERE bs.status='running'
               ORDER BY bs.id DESC LIMIT 50"""
        ).fetchall()
        cols = ["id","account_id","pid","port","target_url","status",
                "started_at","account_name","kuaishou_uid"]
        return {"sessions": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.post("/accounts/browser-sessions/{session_id}/close")
def api_accounts_browser_close(session_id: int):
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT pid FROM browser_sessions WHERE id=? AND status='running'",
            (session_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "未找到运行中的 session")
        from core.browser_launcher import BrowserLauncher
        r = BrowserLauncher().stop(row[0])
        db.conn.execute(
            """UPDATE browser_sessions SET
                 status='closed',
                 closed_at=datetime('now','localtime')
               WHERE id=?""",
            (session_id,),
        )
        db.conn.commit()
        return {"ok": r.get("ok", False)}
    finally:
        db.close()


@router.post("/accounts/browser-login/start")
def api_accounts_browser_login_start(body: BrowserLoginBody):
    """启 Chrome 打开快手登录页, 后台轮询 cookie, 成功自动入库."""
    from core.browser_qrlogin import start_login, cleanup_old
    cleanup_old()
    db = _db()
    try:
        r = start_login(db, login_url_code=body.login_url_code,
                        headless=body.headless)
        return r
    finally:
        # 不 close db, 因为 qrlogin 的后台线程还在用
        pass


@router.get("/accounts/browser-login/{session_id}/status")
def api_accounts_browser_login_status(session_id: str):
    from core.browser_qrlogin import get_status
    return get_status(session_id)


@router.post("/accounts/browser-login/{session_id}/cancel")
def api_accounts_browser_login_cancel(session_id: str):
    from core.browser_qrlogin import cancel
    return cancel(session_id)


# ---------------------------------------------------------------------------
# 账号: 启动 / 停止 任务 (对接 task_queue)
# ---------------------------------------------------------------------------

class StartTaskBody(BaseModel):
    task_type: str = "COLLECT"    # COLLECT/DOWNLOAD/PROCESS/PUBLISH_A/MCN_SYNC/VERIFY/HEALTH_CHECK
    drama_name: str = ""
    drama_url: str = ""
    priority: int = 30


@router.post("/accounts/{account_id}/start-task")
def api_account_start_task(account_id: int, body: StartTaskBody):
    """启动一个 task_queue 任务, 脱离 KS184."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT kuaishou_uid, account_name FROM device_accounts WHERE id=?",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid, name = row
        # 写入 task_queue (Task dataclass 会自动生成 id + idempotency_key)
        from core.task_queue import Task, TASK_TYPES
        if body.task_type not in TASK_TYPES:
            raise HTTPException(400, f"未知 task_type, 可选: {TASK_TYPES}")
        task = Task(
            task_type=body.task_type,
            account_id=uid,
            drama_name=body.drama_name,
            priority=body.priority,
            params={"drama_url": body.drama_url} if body.drama_url else {},
            created_by="dashboard",
        )
        d = task.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        db.conn.execute(
            f"INSERT INTO task_queue ({cols}) VALUES ({placeholders})",
            list(d.values()),
        )
        # 更新 device_accounts.current_task_*
        db.conn.execute(
            """UPDATE device_accounts SET
                 current_task_id=?, current_task_status='queued',
                 current_task_text=?,
                 current_task_updated_at=datetime('now','localtime')
               WHERE id=?""",
            (task.id, f"{body.task_type} {body.drama_name or ''}".strip(), account_id),
        )
        db.conn.commit()
        return {"ok": True, "task_id": task.id, "task_type": body.task_type}
    finally:
        db.close()


@router.post("/accounts/{account_id}/stop-task")
def api_account_stop_task(account_id: int):
    """停止该账号所有活跃任务 — 设置 canceled."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT kuaishou_uid FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid = row[0]
        cur = db.conn.execute(
            """UPDATE task_queue SET
                 status='canceled',
                 finished_at=datetime('now','localtime'),
                 error_message='stopped by dashboard'
               WHERE account_id=?
                 AND status IN ('pending','queued','running','waiting_retry')""",
            (uid,),
        )
        db.conn.execute(
            """UPDATE device_accounts SET
                 current_task_status='idle',
                 current_task_text='',
                 current_task_updated_at=datetime('now','localtime')
               WHERE id=?""",
            (account_id,),
        )
        db.conn.commit()
        return {"ok": True, "canceled": cur.rowcount}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 账号: 打开浏览器 (Chrome + cookie 注入)
# ---------------------------------------------------------------------------

class OpenBrowserBody(BaseModel):
    target_url: str = "https://cp.kuaishou.com/"
    inject_cookies: bool = True
    headless: bool = False


@router.post("/accounts/{account_id}/open-browser")
def api_account_open_browser(account_id: int, body: OpenBrowserBody):
    """启独立 Chrome + 注入该账号 cookie → 打开目标页."""
    db = _db()
    try:
        from core.browser_launcher import BrowserLauncher, find_chrome
        if not find_chrome():
            return {"ok": False, "error": "未找到 Chrome / Edge, 请安装"}
        launcher = BrowserLauncher(db_manager=db)
        result = launcher.launch_for_account(
            account_id,
            target_url=body.target_url,
            inject_cookies=body.inject_cookies,
            headless=body.headless,
        )
        if result.get("ok"):
            try:
                db.conn.execute(
                    """INSERT INTO browser_sessions
                         (account_id, pid, port, profile_dir, chrome_path,
                          target_url, status)
                       VALUES (?, ?, ?, ?, ?, ?, 'running')""",
                    (account_id, result["pid"], result["port"],
                     result.get("profile_dir"), result.get("chrome_path"),
                     body.target_url),
                )
                db.conn.commit()
            except Exception:
                pass
        return result
    finally:
        db.close()


@router.post("/accounts/{account_id}/close-browser")
def api_account_close_browser(account_id: int):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, pid FROM browser_sessions
               WHERE account_id=? AND status='running'""",
            (account_id,),
        ).fetchall()
        closed = 0
        from core.browser_launcher import BrowserLauncher
        launcher = BrowserLauncher()
        for sid, pid in rows:
            r = launcher.stop(pid)
            db.conn.execute(
                """UPDATE browser_sessions SET
                     status='closed',
                     closed_at=datetime('now','localtime'),
                     error_message=?
                   WHERE id=?""",
                ("" if r.get("ok") else str(r.get("error", "")), sid),
            )
            if r.get("ok"):
                closed += 1
        db.conn.commit()
        return {"ok": True, "closed": closed}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 账号: 扫码登录
# ---------------------------------------------------------------------------

@router.post("/accounts/login/qr-generate")
def api_account_qr_generate():
    from core.kuaishou_qrlogin import generate_qr, cleanup_expired
    cleanup_expired()
    return generate_qr()


@router.get("/accounts/login/qr-poll/{qr_id}")
def api_account_qr_poll(qr_id: str):
    from core.kuaishou_qrlogin import poll_qr
    return poll_qr(qr_id)


# ---------------------------------------------------------------------------
# 开关: 账号组级覆盖
# ---------------------------------------------------------------------------

class GroupOverrideBody(BaseModel):
    group: str
    switch_code: str
    value: bool
    operator: str = "dashboard"


@router.get("/switches/group-overrides")
def api_switches_group_overrides(group: Optional[str] = None):
    from core.switches import get_group_overrides
    return {"overrides": get_group_overrides(group)}


@router.post("/switches/group-overrides/set")
def api_switch_group_override_set(body: GroupOverrideBody):
    from core.switches import set_group_override
    return set_group_override(body.group, body.switch_code, body.value,
                              updated_by=body.operator)


@router.post("/switches/group-overrides/clear")
def api_switch_group_override_clear(body: GroupOverrideBody):
    from core.switches import clear_group_override
    return clear_group_override(body.group, body.switch_code)


# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 账号等级 / 赛道 / 配额 (Phase 3.2)
# ---------------------------------------------------------------------------

class LevelBody(BaseModel):
    level: str           # V1_new / V1 / V2 / V3 / V4 / V5plus / VIRAL / DORMANT
    note: str = ""


class CategoryBody(BaseModel):
    category: str        # female_tianchong / male_xuanhuan / ...
    lock: bool = False   # 是否锁定赛道 (跨赛道发拒绝)


@router.get("/accounts/categories")
def api_accounts_categories():
    """所有赛道 (男频/女频) 元数据."""
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT code, name, channel, description
               FROM account_vertical_categories
               ORDER BY channel, code"""
        ).fetchall()
        return {"categories": [
            {"code": r[0], "name": r[1], "channel": r[2], "description": r[3]}
            for r in rows
        ]}
    finally:
        db.close()


@router.get("/accounts/{account_id}/quota")
def api_account_quota(account_id: int):
    """该账号今日配额 + 已用 + 剩余 (按 account_level 差异化)."""
    db = _db()
    try:
        from core.agents.rule_engine import RuleEngine
        row = db.conn.execute(
            """SELECT kuaishou_uid, account_level, lifecycle_stage,
                      account_age_days, vertical_category, vertical_locked
               FROM device_accounts WHERE id=?""",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid, level, stage, age, vertical, vlocked = row
        re = RuleEngine(db)
        quota = re._resolve_daily_limit(uid)   # noqa: SLF001
        used = re._today_published(uid)
        return {
            "account_id": account_id,
            "kuaishou_uid": uid,
            "account_level": level,
            "lifecycle_stage": stage,
            "account_age_days": age,
            "vertical_category": vertical,
            "vertical_locked": bool(vlocked),
            "daily_limit": quota,
            "today_used": used,
            "today_remaining": max(0, quota - used),
        }
    finally:
        db.close()


@router.post("/accounts/{account_id}/level")
def api_account_set_level(account_id: int, body: LevelBody):
    """手工改账号等级 (V1_new/V1/V2/V3/V4/V5plus)."""
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT account_level FROM device_accounts WHERE id=?", (account_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        old_level = row[0]
        db.conn.execute(
            "UPDATE device_accounts SET account_level=? WHERE id=?",
            (body.level, account_id),
        )
        db.conn.execute(
            """INSERT INTO account_level_history
                 (account_id, old_level, new_level, changed_by, note)
               VALUES (?, ?, ?, 'dashboard', ?)""",
            (account_id, old_level, body.level, body.note),
        )
        db.conn.commit()
        return {"ok": True, "old_level": old_level, "new_level": body.level}
    finally:
        db.close()


@router.post("/accounts/{account_id}/category")
def api_account_set_category(account_id: int, body: CategoryBody):
    """设账号赛道."""
    db = _db()
    try:
        cur = db.conn.execute(
            """UPDATE device_accounts SET
                 vertical_category=?, vertical_locked=?
               WHERE id=?""",
            (body.category, 1 if body.lock else 0, account_id),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0,
                "category": body.category, "locked": body.lock}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 一键 pipeline: DOWNLOAD → PROCESS → PUBLISH_A → VERIFY
# ---------------------------------------------------------------------------

class RunPipelineBody(BaseModel):
    drama_id: Optional[int] = None         # drama_links.id (优先)
    drama_url: str = ""                     # 或直接传 m3u8 URL
    drama_name: str = ""
    drama_category: str = ""
    process_mode: str = "mode6"             # mode1/mode6
    priority: int = 30
    caption: str = ""


@router.post("/accounts/{account_id}/run-pipeline")
def api_account_run_pipeline(account_id: int, body: RunPipelineBody):
    """把 DOWNLOAD → PROCESS → PUBLISH_A → VERIFY 串成依赖链入队.

    返回入队的 4 个 task_id.
    """
    import json as _json
    from core.task_queue import Task

    db = _db()
    try:
        # 解析 drama
        drama_url = body.drama_url
        drama_name = body.drama_name
        drama_id = body.drama_id
        if drama_id and not drama_url:
            row = db.conn.execute(
                "SELECT drama_name, drama_url FROM drama_links WHERE id=?",
                (drama_id,),
            ).fetchone()
            if not row:
                raise HTTPException(404, f"drama_id={drama_id} 不存在")
            drama_name, drama_url = drama_name or row[0], drama_url or row[1]
        if not drama_url:
            raise HTTPException(400, "必须提供 drama_id 或 drama_url")

        # 取账号 uid
        acct_row = db.conn.execute(
            """SELECT kuaishou_uid, account_level, lifecycle_stage,
                      vertical_category
               FROM device_accounts WHERE id=?""",
            (account_id,),
        ).fetchone()
        if not acct_row:
            raise HTTPException(404, f"account_id={account_id} 不存在")
        uid, level, stage, vertical = acct_row

        # 规则预检 (发布前)
        from core.agents.rule_engine import RuleEngine
        check = RuleEngine(db).can_publish_now(
            uid, drama_category=body.drama_category or None,
        )
        if not check["allowed"]:
            raise HTTPException(400, f"规则拒绝: {check.get('reason')}")

        # 创建依赖链: DOWNLOAD → PROCESS → PUBLISH_A → VERIFY
        tasks = []
        import secrets
        batch_id = f"pipeline_{secrets.token_hex(4)}"

        download_task = Task(
            task_type="DOWNLOAD",
            account_id=uid, drama_name=drama_name,
            priority=body.priority,
            params={"drama_url": drama_url, "drama_id": drama_id},
            batch_id=batch_id, created_by="dashboard",
        )
        process_task = Task(
            task_type="PROCESS",
            account_id=uid, drama_name=drama_name,
            priority=body.priority,
            params={"mode": body.process_mode,
                    "input_asset_id": download_task.id},   # PROCESS 读 DOWNLOAD 的 output
            depends_on=download_task.id,
            batch_id=batch_id, created_by="dashboard",
        )
        publish_task = Task(
            task_type="PUBLISH_A",
            account_id=uid, drama_name=drama_name,
            priority=body.priority,
            params={"caption": body.caption,
                    "input_asset_id": process_task.id,
                    "drama_category": body.drama_category},
            depends_on=process_task.id,
            batch_id=batch_id, created_by="dashboard",
        )
        verify_task = Task(
            task_type="VERIFY",
            account_id=uid, drama_name=drama_name,
            priority=body.priority + 5,
            params={"upstream_task": publish_task.id},
            depends_on=publish_task.id,
            batch_id=batch_id, created_by="dashboard",
        )

        # 用独立 connection 批量插入 (避开 DBManager 连接池锁争用)
        import time as _time
        from core.config import DB_PATH
        write_conn = sqlite3.connect(DB_PATH, timeout=60)
        write_conn.execute("PRAGMA busy_timeout=60000;")
        try:
            for t in [download_task, process_task, publish_task, verify_task]:
                d = t.to_dict()
                cols = ", ".join(d.keys())
                placeholders = ", ".join("?" for _ in d)
                for attempt in range(8):
                    try:
                        write_conn.execute(
                            f"INSERT INTO task_queue ({cols}) VALUES ({placeholders})",
                            list(d.values()),
                        )
                        write_conn.commit()
                        break
                    except sqlite3.OperationalError as ex:
                        if "locked" in str(ex).lower() and attempt < 7:
                            _time.sleep(1.0 + attempt * 0.5)
                            continue
                        raise
                tasks.append({"id": t.id, "task_type": t.task_type,
                              "depends_on": t.depends_on})
        finally:
            write_conn.close()

        return {"ok": True, "batch_id": batch_id, "tasks": tasks,
                "pre_check": check}
    finally:
        db.close()


@router.post("/accounts/{account_id}/delete")
def api_account_delete(account_id: int):
    db = _db()
    try:
        cur = db.conn.execute(
            "DELETE FROM device_accounts WHERE id=?", (account_id,))
        db.conn.commit()
        return {"affected": cur.rowcount}
    finally:
        db.close()


# ★ 2026-04-20: 3 层账号画像 API (Layer 1/2/3 + 完整画像)
# 用户发现缺失: /api/accounts/{id}/{memory|decisions|diary}

@router.get("/accounts/{account_id}/memory")
def api_account_memory(account_id: int):
    """Layer 2 聚合记忆: preferred_recipes, avoid_drama_ids, ai_trust_score 等."""
    db = _db()
    try:
        cols = [x[1] for x in db.conn.execute("PRAGMA table_info(account_strategy_memory)").fetchall()]
        r = db.conn.execute("SELECT * FROM account_strategy_memory WHERE account_id=?",
                             (account_id,)).fetchone()
        if not r:
            return {"account_id": account_id, "exists": False, "note": "该账号还没记忆数据 (Analyzer 跑过才会有)"}
        d = dict(zip(cols, r))
        # JSON 字段解
        for k in ("preferred_recipes","preferred_image_modes","preferred_genres",
                  "avoid_drama_ids","avoid_genres","avoid_post_hours",
                  "best_post_hours","notes_json"):
            if d.get(k) and isinstance(d[k], str):
                try: d[k] = json.loads(d[k])
                except Exception: pass
        return {"account_id": account_id, "exists": True, "memory": d}
    finally:
        db.close()


@router.get("/accounts/{account_id}/decisions")
def api_account_decisions(account_id: int, limit: int = 30):
    """Layer 1 决策历史: 每次 planner 选剧/recipe/image_mode 的事件流."""
    db = _db()
    try:
        cols = [x[1] for x in db.conn.execute(
            "PRAGMA table_info(account_decision_history)"
        ).fetchall()]
        rs = db.conn.execute(
            f"SELECT {','.join(cols)} FROM account_decision_history "
            "WHERE account_id=? ORDER BY created_at DESC LIMIT ?",
            (account_id, limit)
        ).fetchall()
        items = []
        for r in rs:
            d = dict(zip(cols, r))
            for k in ("score_breakdown","alternatives_json","expected_outcome",
                      "actual_outcome"):
                if d.get(k):
                    try: d[k] = json.loads(d[k])
                    except Exception: pass
            items.append(d)
        # verdict 分布统计
        vdist = {}
        for it in items:
            vdist[it.get("verdict") or "pending"] = vdist.get(it.get("verdict") or "pending", 0) + 1
        return {"account_id": account_id, "count": len(items),
                "verdict_distribution": vdist, "decisions": items}
    finally:
        db.close()


@router.get("/accounts/{account_id}/diary")
def api_account_diary(account_id: int, limit: int = 10):
    """Layer 3 AI 周记: Qwen 3.6 Plus 每周写的账号运营总结."""
    db = _db()
    try:
        cols = [x[1] for x in db.conn.execute(
            "PRAGMA table_info(account_diary_entries)"
        ).fetchall()]
        if not cols:
            return {"account_id": account_id, "entries": [],
                    "note": "account_diary_entries 表不存在"}
        # 兼容字段名 diary_date / entry_date
        order_col = "diary_date" if "diary_date" in cols else (
            "entry_date" if "entry_date" in cols else "created_at"
        )
        rs = db.conn.execute(
            f"SELECT {','.join(cols)} FROM account_diary_entries "
            f"WHERE account_id=? ORDER BY {order_col} DESC LIMIT ?",
            (account_id, limit)
        ).fetchall()
        entries = [dict(zip(cols, r)) for r in rs]
        return {"account_id": account_id, "count": len(entries), "entries": entries}
    finally:
        db.close()


@router.get("/accounts/{account_id}/profile")
def api_account_profile(account_id: int):
    """账号完整画像 = static + Layer 1 计数 + Layer 2 聚合 + Layer 3 最新周记."""
    db = _db()
    try:
        # static
        cols = [x[1] for x in db.conn.execute("PRAGMA table_info(device_accounts)").fetchall()]
        r = db.conn.execute(
            f"SELECT {','.join(cols)} FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        static = dict(zip(cols, r))
        if static.get("tags_json"):
            try: static["tags_json"] = json.loads(static["tags_json"])
            except Exception: pass

        # MCN 真实绑定 (★ 2026-04-21 fix: 多源验证, 避免误报 "未绑")
        # 3 种证据任一成立即认为已绑:
        #   a) mcn_account_bindings 表有 kuaishou_uid 或 account_name 记录
        #   b) mcn_member_snapshots 近 7 天有 member_id 快照
        #   c) mcn_income_snapshots 近 30 天有 kuaishou_uid / member_id 记录
        mcn_status = "未绑"
        mcn_detail = {}
        ks_uid_str = static.get("kuaishou_uid") or ""
        nuid = static.get("numeric_uid")
        acct_name = static.get("account_name") or ""
        ks_name = static.get("kuaishou_name") or ""

        is_bound = False
        # a) bindings 表 (最权威)
        try:
            bind_row = db.conn.execute(
                """SELECT plan_type, last_verified_at FROM mcn_account_bindings
                   WHERE kuaishou_uid=? OR account_name=? OR account_name=?
                   LIMIT 1""",
                (ks_uid_str, acct_name, ks_name),
            ).fetchone()
            if bind_row:
                is_bound = True
                mcn_detail["plan_type"] = bind_row[0]
                mcn_detail["last_verified_at"] = bind_row[1]
        except Exception:
            pass

        # b) member_snapshot 近 7 天
        if nuid:
            snap = db.conn.execute(
                """SELECT total_amount, org_task_num, snapshot_date
                   FROM mcn_member_snapshots
                   WHERE member_id=? AND snapshot_date >= date('now','-7 days')
                   ORDER BY snapshot_date DESC LIMIT 1""",
                (nuid,)
            ).fetchone()
            if snap:
                is_bound = True
                mcn_detail["total_amount"] = snap[0]
                mcn_detail["tasks"] = snap[1]
                mcn_detail["last_snapshot"] = snap[2]

        # c) income_snapshot 近 30 天
        if not is_bound and nuid:
            inc = db.conn.execute(
                """SELECT snapshot_date FROM mcn_income_snapshots
                   WHERE (kuaishou_uid=? OR member_id=?)
                     AND snapshot_date >= date('now','-30 days')
                   ORDER BY snapshot_date DESC LIMIT 1""",
                (nuid, nuid)
            ).fetchone()
            if inc:
                is_bound = True
                mcn_detail["last_income_snapshot"] = inc[0]

        if is_bound:
            # 有收益的叫 "活跃", 无收益但在册的叫 "已绑"
            total_amount = mcn_detail.get("total_amount") or 0
            if total_amount > 0:
                mcn_status = "活跃"
            else:
                mcn_status = "已绑"

        # Layer 1 计数
        l1 = db.conn.execute(
            "SELECT COUNT(*), SUM(CASE WHEN verdict='correct' THEN 1 ELSE 0 END),"
            " SUM(CASE WHEN verdict='wrong' THEN 1 ELSE 0 END)"
            " FROM account_decision_history WHERE account_id=?",
            (account_id,)
        ).fetchone()

        # Layer 2
        l2 = None
        try:
            r2 = db.conn.execute("SELECT * FROM account_strategy_memory WHERE account_id=?",
                                  (account_id,)).fetchone()
            if r2:
                l2_cols = [x[1] for x in db.conn.execute("PRAGMA table_info(account_strategy_memory)").fetchall()]
                l2 = dict(zip(l2_cols, r2))
        except Exception: pass

        # Layer 3 最新 1 条
        l3 = None
        try:
            diary_cols = [x[1] for x in db.conn.execute("PRAGMA table_info(account_diary_entries)").fetchall()]
            order_col = "diary_date" if "diary_date" in diary_cols else "created_at"
            r3 = db.conn.execute(
                f"SELECT * FROM account_diary_entries WHERE account_id=? "
                f"ORDER BY {order_col} DESC LIMIT 1", (account_id,)
            ).fetchone()
            if r3:
                l3_cols = [x[1] for x in db.conn.execute("PRAGMA table_info(account_diary_entries)").fetchall()]
                l3 = dict(zip(l3_cols, r3))
        except Exception: pass

        return {
            "account_id": account_id,
            "static_profile": static,
            "mcn_status": mcn_status,
            "mcn_detail": mcn_detail,
            "decision_stats": {"total": l1[0], "correct": l1[1], "wrong": l1[2]},
            "memory": l2,
            "latest_diary": l3,
        }
    finally:
        db.close()


# ★ 2026-04-20: 账号清洗 (改名 + 删历史作品)
class CleanupBody(BaseModel):
    dry_run: bool = True
    max_deletes: int = 50
    delete_interval_sec: float = 8.0


@router.post("/accounts/{account_id}/cleanup_works")
def api_account_cleanup_works(account_id: int, body: CleanupBody):
    """批量删非短剧作品 (激进清洗: 保留我们自己发的 + 含短剧 tag).

    keep_drama_names 自动从 publish_results 拉, 不用前端传.
    """
    db = _db()
    try:
        # 查该账号所有我们发过的剧名 + photo_id
        rs = db.conn.execute(
            """SELECT DISTINCT drama_name, photo_id FROM publish_results
               WHERE account_id=? AND publish_status='success'""",
            (str(account_id),)
        ).fetchall()
        keep_drama_names = list({r[0] for r in rs if r[0]})
        keep_photo_ids = [r[1] for r in rs if r[1]]

        from core.publisher import KuaishouPublisher
        from core.db_manager import DBManager
        from core.cookie_manager import CookieManager
        from core.sig_service import SigService
        from core.mcn_client import MCNClient
        inner_db = DBManager()
        pub = KuaishouPublisher(
            CookieManager(inner_db), SigService(), MCNClient(), inner_db
        )
        r = pub.batch_cleanup_non_drama(
            account_id,
            keep_drama_names=keep_drama_names,
            keep_photo_ids=keep_photo_ids,
            delete_interval_sec=body.delete_interval_sec,
            max_deletes=body.max_deletes,
            dry_run=body.dry_run,
        )
        return r
    finally:
        db.close()


class RenameBody(BaseModel):
    new_name: str | None = None   # None = 用 AI 建议的
    use_ai_suggestion: bool = True


# ★ 2026-04-20: CDP 网络监听 — 第 1 次改名时抓 API, 下次全自动
@router.post("/accounts/{account_id}/rename_with_sniff")
def api_account_rename_with_sniff(account_id: int, body: RenameBody):
    """方案 B: 打开 Chrome + 跳资料页 + 后台监听 Network → 用户改名 1 次 → 抓到 API.

    用户流程:
      1. Dashboard 点 🎨 AI改名 → 这个 API 触发
      2. 我们开 Chrome, cookie 注入, 跳 cp.kuaishou.com/creator-center/profile
      3. 后台监听 5 分钟, pattern 匹配 [user/modify, nickname, profile/update]
      4. 用户在 Chrome 里自己点"修改"改名 → 保存
      5. 监听器抓到 POST → 存到 tools/trace_publish/sniff_acc{id}_*.json
      6. 我们从 sniff 文件里读出真实端点 + body 格式 → 写 publisher.change_nickname()
      7. 下次改名不用开浏览器, API 直接 fire-and-forget
    """
    db = _db()
    try:
        r = db.conn.execute(
            "SELECT kuaishou_uid, account_name, nickname_suggestions_json FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not r:
            raise HTTPException(404, "账号不存在")
        ksuid, aname, sug_json = r

        # 1. 确定 new_name
        new_name = (body.new_name or "").strip()
        if not new_name and body.use_ai_suggestion and sug_json:
            try:
                new_name = json.loads(sug_json).get("suggested", "").strip()
            except Exception: pass
        if not new_name:
            raise HTTPException(400, "无 new_name 和 AI 推荐")

        # 2. 开浏览器 + 注入 cookie
        from core.browser_launcher import BrowserLauncher, find_chrome
        if not find_chrome():
            raise HTTPException(500, "Chrome 未安装")
        launcher = BrowserLauncher(db_manager=db)
        launch = launcher.launch_for_account(
            account_id,
            target_url="https://cp.kuaishou.com/profile/info",  # 创作者平台资料页
            inject_cookies=True,
            headless=False,
        )
        if not launch.get("ok"):
            raise HTTPException(500, f"浏览器启动失败: {launch.get('error')}")
        port = launch["port"]

        # 3. 启动 CDP 监听 (异步, 5 分钟窗口)
        from core.browser_api_sniffer import BrowserAPISniffer
        sniffer = BrowserAPISniffer(
            account_id=account_id, port=port,
            patterns=[
                "user.*update", "user.*modify", "modifyUserInfo",
                "nickname", "profile.*update", "user.*info",
                "creator.*user", "setting.*user",
            ],
        )
        started = sniffer.start_sniffing(duration=300)

        # 4. 本地先改 account_name (planner 用)
        db.conn.execute(
            "UPDATE device_accounts SET account_name=?, updated_at=datetime('now','localtime') WHERE id=?",
            (new_name, account_id)
        )
        db.conn.commit()

        return {
            "ok": True,
            "account_id": account_id,
            "new_name": new_name,
            "browser_port": port,
            "sniffing_started": started,
            "sniffing_duration_sec": 300,
            "note": (
                f"✅ 浏览器已打开快手资料页. 新名 '{new_name}' 已复制.\n"
                f"📌 请你在浏览器里手动改名 (粘贴 '{new_name}' 到昵称框 → 保存).\n"
                f"🔬 后台监听中, 5 分钟内完成改名, 抓到的 API 会存到 tools/trace_publish/sniff_*.json"
            ),
        }
    finally:
        db.close()


@router.post("/accounts/{account_id}/rename")
def api_account_rename(account_id: int, body: RenameBody):
    """改账号昵称. 当前 Phase 1:
    (1) 写 device_accounts.account_name (本地 + planner 立即用新名)
    (2) 触发浏览器自动打开账号 cp.kuaishou.com/profile-setting (用户手动点改)
    (3) API 自动改 TODO: 待 Frida 抓 1 次真实改名流程, 写 publisher.change_nickname()
    """
    db = _db()
    try:
        # 1. 拿目标名字
        new_name = (body.new_name or "").strip()
        if not new_name and body.use_ai_suggestion:
            r = db.conn.execute(
                "SELECT nickname_suggestions_json FROM device_accounts WHERE id=?",
                (account_id,)
            ).fetchone()
            if r and r[0]:
                try:
                    sug = json.loads(r[0])
                    new_name = sug.get("suggested", "").strip()
                except Exception:
                    pass
        if not new_name:
            raise HTTPException(400, "无 new_name 且无 AI 推荐, 请先跑 suggest_nicknames_ai")

        # 2. 查当前 account_name 做 before/after
        cur = db.conn.execute(
            "SELECT account_name, kuaishou_uid, kuaishou_name FROM device_accounts WHERE id=?",
            (account_id,)
        ).fetchone()
        if not cur:
            raise HTTPException(404, "账号不存在")
        old_name, ksuid, ks_nick = cur

        # 3. 更新本地 (立即生效, planner 用新名)
        db.conn.execute(
            """UPDATE device_accounts SET
                 account_name=?,
                 updated_at=datetime('now','localtime')
               WHERE id=?""",
            (new_name, account_id)
        )
        db.conn.commit()

        # 4. 打开浏览器 (已修好 cookie 注入) → 跳 cp.kuaishou.com 个人资料
        #    用户手动点改名, 或下一版用 CDP 自动点
        browser_url = None
        try:
            from core.browser_launcher import BrowserLauncher, find_chrome
            if find_chrome():
                r = BrowserLauncher(db).launch_for_account(
                    account_id,
                    # KS 个人资料页, 有改名按钮
                    target_url=f"https://www.kuaishou.com/profile/{ksuid}",
                    inject_cookies=True,
                    headless=False,
                )
                if r.get("ok"):
                    browser_url = f"http://127.0.0.1:{r['port']}"
        except Exception as e:
            pass

        return {
            "ok": True,
            "account_id": account_id,
            "old_name": old_name,
            "new_name": new_name,
            "ks_nickname_old": ks_nick,
            "browser_opened": bool(browser_url),
            "browser_devtools_url": browser_url,
            "note": (
                "本地 account_name 已改. 浏览器已打开快手个人页, "
                "请在快手手动点'修改资料'改成新名 (API 端点待逆向). "
                "改完后 planner/MCN 会用新名. 你也可以在此弹窗取消浏览器."
            ),
        }
    finally:
        db.close()


@router.get("/accounts/{account_id}/trend")
def api_account_trend(account_id: int, days: int = 7):
    db = _db()
    try:
        # 先找 kuaishou_uid
        row = db.conn.execute(
            "SELECT kuaishou_uid FROM device_accounts WHERE id=?",
            (account_id,),
        ).fetchone()
        if not row:
            raise HTTPException(404, "账号不存在")
        uid = row[0]
        rows = db.conn.execute(
            """SELECT metric_date, total_plays, total_likes, fans, plays_delta
               FROM daily_account_metrics
               WHERE kuaishou_uid = ? AND metric_date >= DATE('now', ?)
               ORDER BY metric_date""",
            (uid, f"-{days} days"),
        ).fetchall()
        health_rows = db.conn.execute(
            """SELECT snapshot_date, health_score, risk_score
               FROM account_health_snapshots
               WHERE account_id = ? AND snapshot_date >= DATE('now', ?)
               ORDER BY snapshot_date""",
            (uid, f"-{days} days"),
        ).fetchall()
        return {
            "account_id": account_id, "kuaishou_uid": uid,
            "metrics": [
                {"date": r[0], "plays": r[1], "likes": r[2],
                 "fans": r[3], "plays_delta": r[4]}
                for r in rows
            ],
            "health": [
                {"date": r[0], "health": r[1], "risk": r[2]}
                for r in health_rows
            ],
        }
    finally:
        db.close()


# ============================================================================
#  任务队列 /queue
# ============================================================================

@router.get("/queue")
def api_queue(
    status: Optional[str] = Query(None, description="逗号分隔多状态, 如 failed,waiting_retry"),
    task_type: Optional[str] = None,
    account_id: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
):
    db = _db()
    try:
        where = []
        params: list[Any] = []
        if status:
            status_list = [s.strip() for s in status.split(",") if s.strip()]
            placeholders = ",".join("?" for _ in status_list)
            where.append(f"status IN ({placeholders})")
            params.extend(status_list)
        if task_type:
            where.append("task_type = ?")
            params.append(task_type)
        if account_id:
            where.append("account_id = ?")
            params.append(account_id)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        total = db.conn.execute(
            f"SELECT COUNT(*) FROM task_queue {where_sql}", params
        ).fetchone()[0]

        offset = (page - 1) * page_size
        rows = db.conn.execute(
            f"""SELECT id, task_type, account_id, drama_name, priority, status,
                       retry_count, max_retries, created_at, started_at, finished_at,
                       error_message, idempotency_key, batch_id, channel_type,
                       strategy_name, next_retry_at, manual_reason
                FROM task_queue {where_sql}
                ORDER BY CASE WHEN status IN ('running','pending','queued','waiting_retry','waiting_manual') THEN 0 ELSE 1 END,
                         priority ASC, id DESC
                LIMIT ? OFFSET ?""",
            (*params, page_size, offset),
        ).fetchall()
        cols = ["id","task_type","account_id","drama_name","priority","status",
                "retry_count","max_retries","created_at","started_at","finished_at",
                "error_message","idempotency_key","batch_id","channel_type",
                "strategy_name","next_retry_at","manual_reason"]

        # 状态统计
        status_counts_rows = db.conn.execute(
            "SELECT status, COUNT(*) FROM task_queue GROUP BY status"
        ).fetchall()
        status_counts = {r[0]: r[1] for r in status_counts_rows}

        return {
            "tasks": [dict(zip(cols, r)) for r in rows],
            "total": total, "page": page, "page_size": page_size,
            "status_counts": status_counts,
        }
    finally:
        db.close()


@router.get("/queue/{task_id}")
def api_queue_detail(task_id: str):
    db = _db()
    try:
        row = db.conn.execute(
            "SELECT * FROM task_queue WHERE id=?", (task_id,)
        ).fetchone()
        if not row:
            raise HTTPException(404, "任务不存在")
        cols = [d[0] for d in db.conn.execute("PRAGMA table_info(task_queue)").fetchall()]
        # 实际上 fetchall 返回的是 (cid, name, type, ...) — 用 Row 工厂更好
        col_rows = db.conn.execute("PRAGMA table_info(task_queue)").fetchall()
        cols = [c[1] for c in col_rows]
        task = dict(zip(cols, row))
        for f in ("params", "result"):
            if task.get(f):
                try:
                    task[f] = json.loads(task[f])
                except Exception:
                    pass
        return task
    finally:
        db.close()


@router.post("/queue/bulk-retry")
def api_queue_bulk_retry(body: BulkIdsBody):
    db = _db()
    try:
        ids = [str(x) for x in body.ids]
        if not ids:
            return {"affected": 0}
        placeholders = ",".join("?" for _ in ids)
        cur = db.conn.execute(
            f"""UPDATE task_queue
                SET status='pending', retry_count=0, error_message='',
                    finished_at='', started_at=''
                WHERE id IN ({placeholders})
                  AND status IN ('failed','waiting_manual','waiting_retry','dead_letter')""",
            ids,
        )
        db.conn.commit()
        affected = cur.rowcount
        db.conn.execute(
            """INSERT INTO dashboard_bulk_ops
                 (op_code, target_type, target_ids_json, affected_count, operator, note)
               VALUES ('retry_tasks','task',?,?,?,?)""",
            (json.dumps(ids, ensure_ascii=False), affected, body.operator, body.note),
        )
        db.conn.commit()
        return {"affected": affected, "requested": len(ids)}
    finally:
        db.close()


@router.post("/queue/bulk-cancel")
def api_queue_bulk_cancel(body: BulkIdsBody):
    db = _db()
    try:
        ids = [str(x) for x in body.ids]
        if not ids:
            return {"affected": 0}
        placeholders = ",".join("?" for _ in ids)
        cur = db.conn.execute(
            f"""UPDATE task_queue
                SET status='canceled', finished_at=datetime('now','localtime'),
                    error_message='canceled by dashboard'
                WHERE id IN ({placeholders})
                  AND status IN ('pending','queued','waiting_retry','waiting_manual')""",
            ids,
        )
        db.conn.commit()
        affected = cur.rowcount
        db.conn.execute(
            """INSERT INTO dashboard_bulk_ops
                 (op_code, target_type, target_ids_json, affected_count, operator, note)
               VALUES ('cancel_tasks','task',?,?,?,?)""",
            (json.dumps(ids, ensure_ascii=False), affected, body.operator, body.note),
        )
        db.conn.commit()
        return {"affected": affected, "requested": len(ids)}
    finally:
        db.close()


# ============================================================================
#  剧源 /dramas
# ============================================================================

@router.get("/dramas")
def api_dramas(
    status: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 50,
):
    db = _db()
    try:
        where = []
        params: list[Any] = []
        if status:
            where.append("status = ?")
            params.append(status)
        if source:
            where.append("source_file LIKE ?")
            params.append(f"{source}%")
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""

        rows = db.conn.execute(
            f"""SELECT id, drama_name, drama_url, status, use_count,
                       source_file, created_at
                FROM drama_links {where_sql}
                ORDER BY id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        cols = ["id","drama_name","drama_url","status","use_count",
                "source_file","created_at"]
        dramas = [dict(zip(cols, r)) for r in rows]

        # 状态 / 来源分组统计
        by_status = {r[0]: r[1] for r in db.conn.execute(
            "SELECT status, COUNT(*) FROM drama_links GROUP BY status"
        ).fetchall()}
        by_source = {r[0]: r[1] for r in db.conn.execute(
            """SELECT CASE
                   WHEN source_file LIKE 'profile_feed:%' THEN 'profile_feed'
                   WHEN source_file LIKE 'collect-pool:%' THEN 'collect_pool'
                   WHEN source_file = 'download_cache' THEN 'download_cache'
                   ELSE COALESCE(source_file, 'other')
               END AS src, COUNT(*)
               FROM drama_links GROUP BY src"""
        ).fetchall()}

        authors_total = db.conn.execute(
            "SELECT COUNT(*) FROM drama_authors WHERE is_active=1"
        ).fetchone()[0]
        authors_by_src = {r[0] or "other": r[1] for r in db.conn.execute(
            "SELECT source, COUNT(*) FROM drama_authors GROUP BY source"
        ).fetchall()}

        banner_cache = [
            dict(zip(["drama_name","banner_task_id","hit_count","last_seen_at"], r))
            for r in db.conn.execute(
                """SELECT drama_name, banner_task_id, hit_count, last_seen_at
                   FROM drama_banner_tasks
                   ORDER BY hit_count DESC, id DESC LIMIT 50"""
            ).fetchall()
        ]

        # ★ 2026-04-20: 全剧池四层 pool 统计 (用户反馈 "为什么只 62")
        # drama_links (URL 池) vs drama_banner_tasks (我们聚合) vs high_income (MCN 榜)
        # vs mcn_drama_library (134k MCN 全量). 让 UI 看到真实可选剧规模.
        def _count(q, default=0):
            try:
                r = db.conn.execute(q).fetchone()
                return r[0] if r else default
            except Exception:
                return default

        pool_sizes = {
            "drama_links_rows":        _count("SELECT COUNT(*) FROM drama_links"),
            "drama_links_pending":     _count("SELECT COUNT(*) FROM drama_links WHERE status='pending'"),
            "drama_links_verified":    _count("SELECT COUNT(*) FROM drama_links WHERE status='pending' AND verified_at IS NOT NULL"),
            "drama_links_unique":      _count("SELECT COUNT(DISTINCT drama_name) FROM drama_links"),
            "drama_links_downloadable": _count(
                "SELECT COUNT(DISTINCT drama_name) FROM drama_links WHERE status='pending' AND verified_at IS NOT NULL"
            ),
            "drama_banner_tasks":      _count("SELECT COUNT(*) FROM drama_banner_tasks"),
            "high_income_dramas":      _count("SELECT COUNT(*) FROM high_income_dramas"),
            "mcn_drama_library":       _count("SELECT COUNT(*) FROM mcn_drama_library"),
            "mcn_library_active":      _count(
                "SELECT COUNT(*) FROM mcn_drama_library WHERE commission_rate >= 30 "
                "AND (end_time IS NULL OR end_time >= strftime('%s','now'))"
            ),
        }
        # 剧源"真实可选池" = planner 实际 cartesian 大小
        pool_sizes["ai_planner_pool_total"] = (
            50 + 50 + 100  # drama_banner_tasks top50 + high_income top50 + mcn_library top100
        )

        return {
            "dramas": dramas,
            "by_status": by_status, "by_source": by_source,
            "authors_total": authors_total, "authors_by_src": authors_by_src,
            "banner_cache": banner_cache,
            "pool_sizes": pool_sizes,   # ★ 新: 4 层剧池全景
        }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 剧源 / 榜单 / MCN 手动一键刷新 (POST)
# ---------------------------------------------------------------------------

class RefreshAllBody(BaseModel):
    skip_mcn: bool = False
    only: Optional[str] = None          # drama | hot | mcn | authors


_REFRESH_STATE: dict = {"running": False, "started_at": None, "job_id": None,
                         "last_result": None}


@router.post("/admin/refresh_all")
def api_admin_refresh_all(body: RefreshAllBody):
    """手动一键刷新 剧源+榜单+MCN (异步).

    调用 scripts.refresh_all 的 subprocess, 不阻塞 API.
    Dashboard 前端调后再调 /admin/refresh_status 查进度.
    """
    import subprocess
    import threading
    import uuid
    from datetime import datetime

    if _REFRESH_STATE.get("running"):
        return {"ok": False, "error": "another_refresh_already_running",
                "started_at": _REFRESH_STATE.get("started_at"),
                "job_id": _REFRESH_STATE.get("job_id")}

    job_id = f"refresh_{uuid.uuid4().hex[:8]}"
    args = [sys.executable, "-m", "scripts.refresh_all"]
    if body.skip_mcn:
        args.append("--skip-mcn")
    if body.only:
        args.extend(["--only", body.only])

    logdir = Path(__file__).resolve().parent.parent / "logs"
    logdir.mkdir(parents=True, exist_ok=True)
    logfile = logdir / f"{job_id}.log"

    def _run():
        started = datetime.now().isoformat(timespec="seconds")
        _REFRESH_STATE["running"] = True
        _REFRESH_STATE["started_at"] = started
        _REFRESH_STATE["job_id"] = job_id
        _REFRESH_STATE["logfile"] = str(logfile)
        try:
            with open(logfile, "w", encoding="utf-8") as f:
                f.write(f"[refresh] started_at={started}\n")
                f.write(f"[refresh] args={args}\n\n")
                f.flush()
                r = subprocess.run(
                    args, stdout=f, stderr=subprocess.STDOUT,
                    cwd=str(Path(__file__).resolve().parent.parent),
                    timeout=1500, env={**os.environ, "PYTHONIOENCODING": "utf-8"},
                )
                _REFRESH_STATE["last_result"] = {
                    "returncode": r.returncode,
                    "finished_at": datetime.now().isoformat(timespec="seconds"),
                    "log": str(logfile),
                    "job_id": job_id,
                }
        except Exception as e:
            _REFRESH_STATE["last_result"] = {"error": str(e), "job_id": job_id}
        finally:
            _REFRESH_STATE["running"] = False

    t = threading.Thread(target=_run, daemon=True, name=f"refresh-{job_id}")
    t.start()
    return {"ok": True, "job_id": job_id, "log": str(logfile),
            "message": "已后台启动 refresh_all, 轮询 /admin/refresh_status 查进度"}


@router.get("/admin/refresh_status")
def api_admin_refresh_status():
    """查当前 / 上次 refresh_all 的状态 + 最后 30 行 log."""
    tail = []
    lf = _REFRESH_STATE.get("logfile")
    if lf and os.path.isfile(lf):
        try:
            with open(lf, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()
            tail = [l.rstrip() for l in lines[-30:]]
        except Exception:
            pass
    return {
        "running": _REFRESH_STATE.get("running", False),
        "started_at": _REFRESH_STATE.get("started_at"),
        "job_id": _REFRESH_STATE.get("job_id"),
        "last_result": _REFRESH_STATE.get("last_result"),
        "log_tail": tail,
    }


@router.get("/dramas/authors")
def api_dramas_authors(
    source: Optional[str] = None,
    keyword: Optional[str] = None,
    limit: int = 100,
):
    db = _db()
    try:
        where = ["is_active = 1"]
        params: list[Any] = []
        if source:
            where.append("source = ?")
            params.append(source)
        if keyword:
            where.append("(nickname LIKE ? OR drama_tags LIKE ?)")
            params.extend([f"%{keyword}%", f"%{keyword}%"])
        where_sql = "WHERE " + " AND ".join(where)
        rows = db.conn.execute(
            f"""SELECT id, nickname, kuaishou_uid, drama_tags,
                       source, fans_count, photos_count, is_active,
                       last_scraped_at, created_at
                FROM drama_authors {where_sql}
                ORDER BY id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        cols = ["id","author_name","kuaishou_uid","drama_tags",
                "source","fans","works","is_active",
                "last_scraped_at","created_at"]
        return {"authors": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


# ============================================================================
#  榜单 /rankings
# ============================================================================

@router.get("/rankings/external")
def api_rankings_external():
    db = _db()
    try:
        di = DataInsights(db)
        return {
            "keyword_heat": di.keyword_heat_index(),
            "top_per_keyword": di.market_top_by_keyword(limit_per_kw=5),
        }
    finally:
        db.close()


@router.get("/rankings/internal")
def api_rankings_internal(limit: int = 30):
    db = _db()
    try:
        di = DataInsights(db)
        return {"matrix_top": di.matrix_top_works(limit=limit)}
    finally:
        db.close()


@router.get("/rankings/heatmap")
def api_rankings_heatmap():
    """热力矩阵: 关键词 × 排名 → view_count."""
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT keyword, rank, AVG(view_count) AS v
               FROM drama_hot_rankings
               WHERE platform='kuaishou_search'
                 AND snapshot_date = (SELECT MAX(snapshot_date) FROM drama_hot_rankings)
               GROUP BY keyword, rank
               ORDER BY keyword, rank"""
        ).fetchall()
        keywords = sorted({r[0] for r in rows})
        max_rank = max((r[1] for r in rows), default=15)
        cells = [
            {"keyword": r[0], "rank": r[1], "view": int(r[2] or 0)}
            for r in rows
        ]
        return {
            "keywords": keywords,
            "max_rank": max_rank,
            "cells": cells,
        }
    finally:
        db.close()


# ============================================================================
#  发布结果 /publishes
# ============================================================================

@router.get("/publishes")
def api_publishes(
    status: Optional[str] = None,
    account_id: Optional[str] = None,
    limit: int = 50,
):
    """★ 2026-04-22 §27: 返回账号中文名 (JOIN device_accounts)."""
    db = _db()
    try:
        where = []
        params: list[Any] = []
        if status:
            where.append("pr.publish_status = ?")
            params.append(status)
        if account_id:
            where.append("pr.account_id = ?")
            params.append(account_id)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = db.conn.execute(
            f"""SELECT pr.id, pr.account_id,
                       COALESCE(da.kuaishou_name, da.account_name,
                                '账号#' || CAST(pr.account_id AS TEXT)) AS account_display,
                       pr.channel_type, pr.drama_name,
                       pr.publish_status, pr.verify_status, pr.failure_reason,
                       pr.photo_id, pr.share_url, pr.banner_task_id,
                       pr.mcn_binding_status, pr.created_at, pr.published_at
                FROM publish_results pr
                LEFT JOIN device_accounts da
                  ON CAST(pr.account_id AS INTEGER) = da.id
                {where_sql}
                ORDER BY pr.id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        cols = ["id","account_id","account_display","channel_type","drama_name",
                "publish_status","verify_status","failure_reason",
                "photo_id","share_url","banner_task_id",
                "mcn_binding_status","created_at","published_at"]
        return {"publishes": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.get("/publishes/summary")
def api_publishes_summary():
    db = _db()
    try:
        total = db.conn.execute("SELECT COUNT(*) FROM publish_results").fetchone()[0]
        by_status = {r[0]: r[1] for r in db.conn.execute(
            "SELECT publish_status, COUNT(*) FROM publish_results GROUP BY publish_status"
        ).fetchall()}
        by_channel = {r[0]: r[1] for r in db.conn.execute(
            "SELECT channel_type, COUNT(*) FROM publish_results GROUP BY channel_type"
        ).fetchall()}
        by_reason = [
            {"reason": r[0] or "(未知)", "count": r[1]}
            for r in db.conn.execute(
                """SELECT COALESCE(failure_reason,''), COUNT(*) AS c
                   FROM publish_results
                   WHERE publish_status='failed'
                   GROUP BY failure_reason
                   ORDER BY c DESC LIMIT 10"""
            ).fetchall()
        ]
        trend = [
            {"date": r[0], "success": r[1] or 0, "failed": r[2] or 0}
            for r in db.conn.execute(
                """SELECT DATE(created_at),
                          SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END),
                          SUM(CASE WHEN publish_status='failed'  THEN 1 ELSE 0 END)
                   FROM publish_results
                   WHERE DATE(created_at) >= DATE('now','-14 days')
                   GROUP BY DATE(created_at) ORDER BY DATE(created_at)"""
            ).fetchall()
        ]
        return {
            "total": total, "by_status": by_status,
            "by_channel": by_channel, "top_failure_reasons": by_reason,
            "trend": trend,
        }
    finally:
        db.close()


# ============================================================================
#  异常中心 /incidents
# ============================================================================

@router.get("/incidents")
def api_incidents(
    severity: str = "low",
    hours: int = 48,
    limit: int = 200,
    type_filter: Optional[str] = Query(None, alias="type"),
):
    db = _db()
    try:
        ic = IncidentCenter(db)
        items = ic.list_all(severity=severity, hours=hours, limit=limit)
        if type_filter:
            items = [x for x in items if x["type"] == type_filter]
        return {"items": items, "total": len(items)}
    finally:
        db.close()


@router.get("/incidents/summary")
def api_incidents_summary():
    db = _db()
    try:
        return IncidentCenter(db).summary()
    finally:
        db.close()


@router.post("/incidents/acknowledge")
def api_incidents_ack(body: BulkIdsBody):
    db = _db()
    try:
        ic = IncidentCenter(db)
        return ic.acknowledge([str(x) for x in body.ids], operator=body.operator)
    finally:
        db.close()


@router.post("/incidents/{incident_id}/retry")
def api_incident_retry(incident_id: str):
    db = _db()
    try:
        return IncidentCenter(db).retry(incident_id)
    finally:
        db.close()


# ============================================================================
#  系统开关 /switches
# ============================================================================

@router.get("/switches")
def api_switches():
    return {
        "tree": get_layered_tree(),
        "flat": switches_all(),
    }


@router.get("/switches/changes")
def api_switches_changes(limit: int = 50):
    return {"changes": switch_changes(limit)}


@router.post("/switches/{code}/toggle")
def api_switch_toggle(code: str, body: SwitchToggleBody):
    set_switch(code, body.value, updated_by=body.operator)
    return {"code": code, "value": body.value}


@router.post("/switches/bulk")
def api_switches_bulk(body: BulkSwitchesBody):
    return switches_bulk_set(
        body.codes, body.value,
        updated_by=body.operator, note=body.note,
    )


@router.post("/switches/layer/{layer}/master")
def api_switches_layer_master(layer: int, body: SwitchToggleBody):
    return toggle_layer_master(layer, body.value, updated_by=body.operator)


@router.post("/switches/layer/{layer}/cascade-off")
def api_switches_layer_off(layer: int, body: SwitchToggleBody):
    return cascade_off(layer, updated_by=body.operator)


# ============================================================================
#  策略实验 /experiments
# ============================================================================

@router.get("/experiments")
def api_experiments(status: Optional[str] = None):
    db = _db()
    try:
        where = ""
        params: list[Any] = []
        if status:
            where = "WHERE status=?"
            params = [status]
        rows = db.conn.execute(
            f"""SELECT id, experiment_code, experiment_name, hypothesis,
                       variable_name, control_group, test_group,
                       sample_target, sample_current, success_metric,
                       success_threshold, status, created_by_agent,
                       started_at, ended_at, result_summary, created_at
                FROM strategy_experiments {where} ORDER BY id DESC""",
            params,
        ).fetchall()
        cols = ["id","experiment_code","experiment_name","hypothesis",
                "variable_name","control_group","test_group",
                "sample_target","sample_current","success_metric",
                "success_threshold","status","created_by_agent",
                "started_at","ended_at","result_summary","created_at"]
        return {"experiments": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.post("/experiments")
def api_experiment_create(body: ExperimentCreateBody):
    db = _db()
    try:
        db.conn.execute(
            """INSERT INTO strategy_experiments
                 (experiment_code, experiment_name, hypothesis, variable_name,
                  control_group, test_group, sample_target, success_metric,
                  success_threshold, stop_condition, status, created_by_agent,
                  created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?,
                       datetime('now','localtime'))""",
            (body.experiment_code, body.experiment_name, body.hypothesis,
             body.variable_name, body.control_group, body.test_group,
             body.sample_target, body.success_metric, body.success_threshold,
             body.stop_condition, body.created_by_agent),
        )
        db.conn.commit()
        return {"ok": True, "code": body.experiment_code}
    except Exception as e:
        raise HTTPException(400, f"创建失败: {e}")
    finally:
        db.close()


@router.post("/experiments/{code}/start")
def api_experiment_start(code: str):
    db = _db()
    try:
        cur = db.conn.execute(
            """UPDATE strategy_experiments
               SET status='running', started_at=datetime('now','localtime')
               WHERE experiment_code=? AND status IN ('draft','paused')""",
            (code,),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0, "affected": cur.rowcount}
    finally:
        db.close()


@router.post("/experiments/{code}/stop")
def api_experiment_stop(code: str):
    db = _db()
    try:
        cur = db.conn.execute(
            """UPDATE strategy_experiments
               SET status='completed', ended_at=datetime('now','localtime')
               WHERE experiment_code=?""",
            (code,),
        )
        db.conn.commit()
        return {"ok": cur.rowcount > 0, "affected": cur.rowcount}
    finally:
        db.close()


@router.get("/experiments/{code}/assignments")
def api_experiment_assignments(code: str):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, experiment_code, account_id, drama_name, strategy_name,
                      group_name, status, outcome_json, created_at
               FROM experiment_assignments
               WHERE experiment_code=? ORDER BY id DESC""",
            (code,),
        ).fetchall()
        cols = ["id","experiment_code","account_id","drama_name","strategy_name",
                "group_name","status","outcome_json","created_at"]
        return {"assignments": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


# ============================================================================
#  Agents 中枢 /agents
# ============================================================================

@router.get("/agents/list")
def api_agents_list():
    return {"agents": agent_registry.list_agents()}


@router.get("/agents/summary")
def api_agents_summary():
    db = _db()
    try:
        s = agent_debug.summary(db)
        # 最近一批次
        batches = agent_debug.list_batches(db, limit=3)
        # 记忆 + 实验数
        mem_count = db.conn.execute(
            """SELECT COUNT(*) FROM strategy_memories
               WHERE valid_to IS NULL OR valid_to > datetime('now')"""
        ).fetchone()[0]
        exp_count = db.conn.execute(
            "SELECT COUNT(*) FROM strategy_experiments WHERE status='running'"
        ).fetchone()[0]
        return {
            **s,
            "active_memories": mem_count,
            "running_experiments": exp_count,
            "recent_batches": batches,
        }
    finally:
        db.close()


@router.get("/agents/runs")
def api_agents_runs(
    agent_name: Optional[str] = None,
    status: Optional[str] = None,
    batch_id: Optional[str] = None,
    limit: int = 50, offset: int = 0,
):
    db = _db()
    try:
        return {
            "runs": agent_debug.list_runs(
                db, agent_name=agent_name or "", status=status or "",
                batch_id=batch_id or "", limit=limit, offset=offset,
            ),
        }
    finally:
        db.close()


@router.get("/agents/runs/{run_id}")
def api_agents_run_detail(run_id: str):
    db = _db()
    try:
        d = agent_debug.get_run_detail(run_id, db)
        if not d:
            raise HTTPException(404, f"run_id={run_id} 不存在")
        return d
    finally:
        db.close()


@router.get("/agents/batches")
def api_agents_batches(limit: int = 30):
    db = _db()
    try:
        return {"batches": agent_debug.list_batches(db, limit=limit)}
    finally:
        db.close()


@router.get("/agents/batches/{batch_id}")
def api_agents_batch_detail(batch_id: str):
    db = _db()
    try:
        d = agent_debug.batch_detail(batch_id, db)
        if not d:
            raise HTTPException(404, f"batch_id={batch_id} 不存在")
        return d
    finally:
        db.close()


@router.post("/agents/{name}/trigger")
def api_agent_trigger(name: str, body: TriggerAgentBody):
    db = _db()
    try:
        return agent_debug.trigger(
            name, body.payload, db,
            batch_id=body.batch_id, account_id=body.account_id,
            respect_switch=body.respect_switch,
        )
    finally:
        db.close()


@router.post("/agents/replay/{run_id}")
def api_agent_replay(run_id: str):
    db = _db()
    try:
        return agent_debug.replay(run_id, db)
    finally:
        db.close()


@router.get("/agents/memories")
def api_agents_memories(
    active_only: bool = True,
    pinned_only: bool = False,
    memory_type: Optional[str] = None,
    limit: int = 100,
):
    db = _db()
    try:
        where = []
        params: list[Any] = []
        if active_only:
            where.append("(valid_to IS NULL OR valid_to > datetime('now'))")
        if pinned_only:
            where.append("COALESCE(pinned,0) = 1")
        if memory_type:
            where.append("memory_type = ?")
            params.append(memory_type)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = db.conn.execute(
            f"""SELECT id, memory_type, drama_genre, strategy_name, title,
                       description, recommendation, confidence_score,
                       impact_score, hit_count, valid_from, valid_to,
                       COALESCE(pinned, 0) AS pinned, source_agent, created_at
                FROM strategy_memories {where_sql}
                ORDER BY COALESCE(pinned,0) DESC, confidence_score DESC,
                         impact_score DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        cols = ["id","memory_type","drama_genre","strategy_name","title",
                "description","recommendation","confidence_score",
                "impact_score","hit_count","valid_from","valid_to",
                "pinned","source_agent","created_at"]
        return {"memories": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.post("/agents/memories/{memory_id}/pin")
def api_agents_memory_pin(memory_id: int, body: MemoryPinBody):
    db = _db()
    try:
        cur = db.conn.execute(
            """UPDATE strategy_memories SET pinned=?,
                 updated_at=datetime('now','localtime')
               WHERE id=?""",
            (1 if body.pinned else 0, memory_id),
        )
        db.conn.commit()
        return {"affected": cur.rowcount, "pinned": body.pinned}
    finally:
        db.close()


@router.post("/agents/memories/{memory_id}/invalidate")
def api_agents_memory_invalidate(memory_id: int):
    db = _db()
    try:
        cur = db.conn.execute(
            """UPDATE strategy_memories SET
                 valid_to=datetime('now','localtime'),
                 invalidation_reason='manually invalidated'
               WHERE id=?""",
            (memory_id,),
        )
        db.conn.commit()
        return {"affected": cur.rowcount}
    finally:
        db.close()


@router.post("/agents/consolidate-memory")
def api_agents_consolidate():
    db = _db()
    try:
        res = MemoryConsolidator(db).daily()
        return res
    finally:
        db.close()


@router.get("/agents/decisions")
def api_agents_decisions(limit: int = 20):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, batch_id, decision_reasoning, publish_count,
                      llm_provider, prompt_version, rule_ids_applied, created_at
               FROM decision_history ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        cols = ["id","batch_id","reasoning","publish_count","llm_provider",
                "prompt_version","rule_ids_applied","created_at"]
        return {"decisions": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


# ============================================================================
#  批量操作审计
# ============================================================================

# ============================================================================
#  配置中心 /config
# ============================================================================

class ConfigSetBody(BaseModel):
    value: Any
    operator: str = "dashboard"


class ConfigBulkSetBody(BaseModel):
    items: list[dict]  # [{category, key, value}]
    operator: str = "dashboard"


class ProviderTestBody(BaseModel):
    provider: str                    # codex | codex-spark | deepseek | ...
    prompt: str = "用一句中文说你好, 不超过 10 字."


@router.get("/config")
def api_config_all():
    """全部分类 → 列表."""
    return {"categories": cfg.list_all()}


# --- 专门路由必须放在 /config/{category} 通配之前 ---

@router.get("/config/changes/recent")
def api_config_changes(limit: int = 50):
    return {"changes": cfg.recent_changes(limit)}


@router.post("/config/bulk")
def api_config_bulk(body: ConfigBulkSetBody):
    return cfg.bulk_set(body.items, updated_by=body.operator)


# ---------------------------------------------------------------------------
# LLM Provider 详情 (给"配置中心 > LLM Tab")
# ---------------------------------------------------------------------------

@router.get("/config/llm/providers")
def api_config_llm_providers(check_online: bool = False):
    """列出所有 provider + 元数据. check_online=true 时才做实时健康检查 (较慢).

    普通展示用 check_online=false (默认), 打开"测试"按钮时用 true.
    """
    import urllib.request
    import os
    out = []
    priority = cfg.get("llm", "provider_priority",
                       list(LLM_PROVIDERS.keys()))
    # 只检测一次 Hermes (大多数 provider 共用同一个 Hermes 端点)
    # 用 /health (无需 auth) 而非 /v1/models (需 Bearer → urllib 不带 header → 401 → 误判离线)
    hermes_online: bool | None = None
    if check_online:
        try:
            urllib.request.urlopen("http://127.0.0.1:8642/health", timeout=2.0)
            hermes_online = True
        except Exception:
            hermes_online = False
    for name, p in LLM_PROVIDERS.items():
        has_key = False
        if p.get("api_key"):
            has_key = True
        elif p.get("api_key_file"):
            has_key = os.path.isfile(p["api_key_file"])
        elif p.get("api_key_env"):
            has_key = bool(os.getenv(p["api_key_env"]))
        online = None
        if check_online and p.get("is_local"):
            online = hermes_online   # 本地 provider 都指向 Hermes
        out.append({
            "name": name,
            "model": p.get("model"),
            "base_url": p.get("base_url"),
            "description": p.get("description"),
            "is_local": bool(p.get("is_local")),
            "has_key": has_key,
            "online": online,   # None = 未检测(非本地), True/False
            "cost_in":  p.get("cost_per_mtoken_in", 0),
            "cost_out": p.get("cost_per_mtoken_out", 0),
            "priority_index": priority.index(name) if name in priority else 999,
        })
    out.sort(key=lambda x: x["priority_index"])
    # active 只在 check_online=true 时才实例化 (会触发真实探测)
    if check_online:
        active = LLMClient()
        active_info = active.info() if active.available else {"available": False}
    else:
        # 从配置读当前优先级第一个作为"理论上的 active"
        first = priority[0] if priority else None
        if first and first in LLM_PROVIDERS:
            active_info = {
                "available": None,   # 未检测
                "provider": first,
                "model": LLM_PROVIDERS[first].get("model"),
                "description": LLM_PROVIDERS[first].get("description"),
                "is_local": bool(LLM_PROVIDERS[first].get("is_local")),
            }
        else:
            active_info = {"available": False}
    return {"providers": out, "active": active_info, "priority": priority}


@router.post("/config/llm/test")
def api_config_llm_test(body: ProviderTestBody):
    """测某个 provider 的连通性 (发真实 chat 请求)."""
    import time
    llm = LLMClient(provider=body.provider)
    if not llm.available:
        return {"ok": False, "error": "provider not available",
                "provider": body.provider}
    t0 = time.time()
    resp = llm.chat(
        system_prompt="你是一个回声测试助手, 只重复用户的问候.",
        user_prompt=body.prompt,
        max_tokens=64, temperature=0.1,
    )
    latency = int((time.time() - t0) * 1000)
    return {
        "ok": bool(resp),
        "provider": body.provider,
        "model": llm.model,
        "reply": (resp or "")[:200],
        "latency_ms": latency,
    }


# ---------------------------------------------------------------------------
# Prompt 模板 (给"配置中心 > Prompt Tab")
# ---------------------------------------------------------------------------

@router.get("/config/prompts")
def api_config_prompts():
    """4 个 Agent 的 prompt 模板 (system + user_template)."""
    out = []
    for agent_name, tmpl in PROMPTS.items():
        # 如果 system_config 里有覆盖 就用覆盖, 否则用默认
        override_system = cfg.get("prompt", f"{agent_name}_system_override", "")
        override_user = cfg.get("prompt", f"{agent_name}_user_override", "")
        out.append({
            "agent": agent_name,
            "version": cfg.get("prompt", f"{agent_name}_version", tmpl.get("version", "")),
            "system": override_system or tmpl.get("system", ""),
            "user_template": override_user or tmpl.get("user_template", ""),
            "system_default": tmpl.get("system", ""),
            "user_default": tmpl.get("user_template", ""),
            "has_override": bool(override_system or override_user),
        })
    return {"prompts": out}


# ---------------------------------------------------------------------------
# 关键词 watchlist
# ---------------------------------------------------------------------------

class KeywordBody(BaseModel):
    keyword: str
    priority: int = 50
    note: str = ""


@router.get("/config/keywords")
def api_config_keywords():
    db = _db()
    try:
        try:
            rows = db.conn.execute(
                """SELECT id, keyword, priority, is_active, last_scraped_at,
                          notes, created_at
                   FROM keyword_watch_list ORDER BY priority DESC, id"""
            ).fetchall()
        except Exception:
            rows = []
        cols = ["id","keyword","priority","is_active","last_scraped_at",
                "notes","created_at"]
        return {"keywords": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.post("/config/keywords")
def api_config_keyword_add(body: KeywordBody):
    db = _db()
    try:
        db.conn.execute(
            """INSERT OR IGNORE INTO keyword_watch_list
                 (keyword, priority, notes, is_active, created_at)
               VALUES (?, ?, ?, 1, datetime('now','localtime'))""",
            (body.keyword, body.priority, body.note),
        )
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/config/keywords/{kw_id}/toggle")
def api_config_keyword_toggle(kw_id: int):
    db = _db()
    try:
        db.conn.execute(
            """UPDATE keyword_watch_list
               SET is_active = 1 - COALESCE(is_active, 0)
               WHERE id=?""",
            (kw_id,),
        )
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/config/keywords/{kw_id}/delete")
def api_config_keyword_delete(kw_id: int):
    db = _db()
    try:
        db.conn.execute("DELETE FROM keyword_watch_list WHERE id=?", (kw_id,))
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


# ---------------------------------------------------------------------------
# 环境信息 (只读, 专门路由必须放在 /config/{category} 通配之前)
# ---------------------------------------------------------------------------

@router.get("/config/environment")
def api_config_env():
    import sys as _sys
    import platform
    try:
        import importlib.metadata as md
    except Exception:
        md = None

    pkgs: dict[str, str] = {}
    if md is not None:
        for p in ["fastapi", "uvicorn", "openai", "langgraph",
                  "langgraph-checkpoint-sqlite", "httpx"]:
            try:
                pkgs[p] = md.version(p)
            except Exception:
                pkgs[p] = "(未安装)"

    # Hermes 状态
    hermes_online = False
    try:
        import urllib.request
        req = urllib.request.Request("http://127.0.0.1:8642/v1/models")
        urllib.request.urlopen(req, timeout=1)
        hermes_online = True
    except Exception:
        pass

    import os
    db_path = cfg.get("integration", "db_path", "")
    return {
        "python": _sys.version,
        "platform": platform.platform(),
        "executable": _sys.executable,
        "project_root": str(Path(__file__).resolve().parent.parent),
        "packages": pkgs,
        "hermes_online": hermes_online,
        "db_path": db_path,
        "db_size_mb": round(os.path.getsize(db_path) / 1024 / 1024, 2) if db_path and os.path.isfile(db_path) else 0,
        "started_at": datetime.now().isoformat(),
    }


# --- 通配路由放在所有专门路由之后 ---

@router.get("/config/{category}")
def api_config_category(category: str):
    return {"category": category, "items": cfg.get_category(category)}


@router.post("/config/{category}/{key}")
def api_config_set(category: str, key: str, body: ConfigSetBody):
    r = cfg.set(category, key, body.value, updated_by=body.operator)
    if not r.get("ok"):
        raise HTTPException(400, r.get("message") or r.get("error"))
    return r


@router.post("/config/{category}/{key}/reset")
def api_config_reset(category: str, key: str):
    return cfg.reset_to_default(category, key)


# ============================================================================
#  执行中心 /execution
# ============================================================================

@router.get("/execution/status")
def api_execution_status():
    """Worker 运行状态 + 各 task_type 并发 + 熔断器.

    ★ 2026-04-24 v6 Day 5-C: 改读 account_executor 顶层 API (WorkerManager 已废).
    Worker 进程由 run_autopilot.py 单独跑, dashboard 只读状态不控制.
    """
    from core.executor.account_executor import (
        executor_status, executor_concurrency, executor_running_tasks,
    )
    from core.operation_mode import mcn_mode, mcn_status_detail
    return {
        **executor_status(),
        **executor_concurrency(),
        "running_tasks": executor_running_tasks(limit=50),
        "mcn_mode": mcn_mode(),
        "mcn_detail": mcn_status_detail(),
    }


@router.get("/execution/logs")
def api_execution_logs(limit: int = 200, level: Optional[str] = None):
    from core.executor.account_executor import executor_logs
    return {"logs": executor_logs(limit=limit, level=level)}


@router.post("/execution/start-worker")
def api_execution_start_worker():
    """Worker 由 run_autopilot.py 单独启动, 不再由 dashboard 控制.

    返回提示信息 + 当前 executor 状态, 保持前端 API 兼容.
    """
    from core.executor.account_executor import executor_status
    return {
        "ok": False,
        "message": (
            "Worker 进程由 `python -m scripts.run_autopilot` 单独启动. "
            "Dashboard 不再管理 worker 生命周期 (避免 split-brain). "
            "若未启动请在终端运行 scripts.run_autopilot."
        ),
        "current_status": executor_status(),
    }


@router.post("/execution/stop-worker")
def api_execution_stop_worker():
    """同上 — 停 worker 请 kill run_autopilot.py 进程."""
    from core.executor.account_executor import executor_status
    return {
        "ok": False,
        "message": (
            "Worker 进程由 run_autopilot.py 管理. 要停: kill 该进程."
        ),
        "current_status": executor_status(),
    }


@router.post("/execution/submit-task")
def api_execution_submit_task(body: dict):
    """快速向 task_queue 提交一个 task — 调试用."""
    import json as _json
    from core.db_manager import DBManager
    from core.task_queue import Task, TASK_TYPES
    task_type = body.get("task_type")
    if task_type not in TASK_TYPES:
        raise HTTPException(400, f"未知 task_type, 可选: {TASK_TYPES}")
    db = DBManager()
    try:
        task = Task(
            task_type=task_type,
            account_id=str(body.get("account_id", "")),
            drama_name=body.get("drama_name", ""),
            priority=int(body.get("priority", 30)),
            params=body.get("params", {}),
            created_by="dashboard_debug",
        )
        d = task.to_dict()
        cols = ", ".join(d.keys())
        placeholders = ", ".join("?" for _ in d)
        db.conn.execute(f"INSERT INTO task_queue ({cols}) VALUES ({placeholders})",
                        list(d.values()))
        db.conn.commit()
        return {"ok": True, "task_id": task.id}
    finally:
        db.close()


# ============================================================================
#  规则演化 /rules (Seed + Proposals + History)
# ============================================================================

class ProposalDecideBody(BaseModel):
    operator: str = "dashboard"
    note: str = ""


class SeedResetBody(BaseModel):
    operator: str = "dashboard"


@router.get("/rules/seed-vs-current")
def api_rules_seed_vs_current():
    """列所有种子规则 + 当前值 + 是否漂移."""
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, category, config_key, config_value, seed_value,
                      seed_version, last_evolved_at, evolution_count,
                      description, value_type
               FROM system_config WHERE is_seed=1
               ORDER BY category, config_key"""
        ).fetchall()
        out = []
        for r in rows:
            drifted = (r[3] != r[4])
            out.append({
                "id": r[0], "category": r[1], "key": r[2],
                "current_value": r[3], "seed_value": r[4],
                "seed_version": r[5],
                "last_evolved_at": r[6],
                "evolution_count": r[7] or 0,
                "description": r[8],
                "value_type": r[9],
                "drifted": drifted,
            })
        return {
            "total": len(out),
            "drifted_count": sum(1 for x in out if x["drifted"]),
            "rules": out,
        }
    finally:
        db.close()


@router.get("/rules/evolution")
def api_rules_evolution(limit: int = 100,
                         category: Optional[str] = None,
                         config_key: Optional[str] = None):
    """规则演化历史."""
    db = _db()
    try:
        where, params = [], []
        if category:
            where.append("category=?"); params.append(category)
        if config_key:
            where.append("config_key=?"); params.append(config_key)
        where_sql = ("WHERE " + " AND ".join(where)) if where else ""
        rows = db.conn.execute(
            f"""SELECT id, category, config_key, old_value, new_value,
                       changed_by, source, reason, confidence,
                       proposal_id, created_at
                FROM rule_evolution_history {where_sql}
                ORDER BY id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        cols = ["id","category","config_key","old_value","new_value",
                "changed_by","source","reason","confidence",
                "proposal_id","created_at"]
        return {"history": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.get("/rules/proposals")
def api_rules_proposals(status: Optional[str] = "pending", limit: int = 50):
    db = _db()
    try:
        where = ""
        params: list = []
        if status:
            where = "WHERE status=?"
            params.append(status)
        rows = db.conn.execute(
            f"""SELECT id, category, config_key, current_value, proposed_value,
                       proposer, reason, evidence_json, confidence, status,
                       decided_by, decided_at, decision_note, created_at
                FROM rule_proposals {where}
                ORDER BY id DESC LIMIT ?""",
            (*params, limit),
        ).fetchall()
        out = []
        for r in rows:
            try:
                evidence = json.loads(r[7] or "{}")
            except Exception:
                evidence = {}
            out.append({
                "id": r[0], "category": r[1], "key": r[2],
                "current_value": r[3], "proposed_value": r[4],
                "proposer": r[5], "reason": r[6],
                "evidence": evidence,
                "confidence": r[8], "status": r[9],
                "decided_by": r[10], "decided_at": r[11],
                "decision_note": r[12], "created_at": r[13],
            })
        return {"proposals": out}
    finally:
        db.close()


@router.post("/rules/proposals/{pid}/approve")
def api_rules_approve(pid: int, body: ProposalDecideBody):
    from core.agents.threshold_agent import apply_proposal
    db = _db()
    try:
        r = apply_proposal(db, pid, approver=body.operator, note=body.note)
        if not r.get("ok"):
            raise HTTPException(400, r.get("error", "apply failed"))
        return r
    finally:
        db.close()


@router.post("/rules/proposals/{pid}/reject")
def api_rules_reject(pid: int, body: ProposalDecideBody):
    from core.agents.threshold_agent import reject_proposal
    db = _db()
    try:
        return reject_proposal(db, pid, rejector=body.operator, note=body.note)
    finally:
        db.close()


@router.post("/rules/{category}/{config_key}/reset-to-seed")
def api_rules_reset_seed(category: str, config_key: str, body: SeedResetBody):
    from core.agents.threshold_agent import reset_to_seed
    db = _db()
    try:
        return reset_to_seed(db, category, config_key, operator=body.operator)
    finally:
        db.close()


@router.post("/rules/analyze")
def api_rules_analyze(min_samples: int = 30, weeks: int = 4):
    """手动触发 ThresholdAgent."""
    db = _db()
    try:
        from core.agents.threshold_agent import ThresholdAgent
        agent = ThresholdAgent(db)
        return agent.run({"min_samples": min_samples, "weeks": weeks})
    finally:
        db.close()


# ============================================================================
#  自动驾驶 /autopilot
# ============================================================================

@router.get("/autopilot/status")
def api_autopilot_status():
    """★ 2026-04-24 v6 Day 5-C: autopilot / worker 运行状态改读 DB 推断.

    autopilot_running: 过去 5 min 有 autopilot_cycles 新增 → True
    worker_running:    有 account_locks 或 running task → True
    """
    import sqlite3
    from core.config import DB_PATH
    with sqlite3.connect(DB_PATH, timeout=5) as c:
        autopilot_alive = (c.execute(
            """SELECT 1 FROM autopilot_cycles
               WHERE started_at > datetime('now','-5 minutes','localtime')
               LIMIT 1"""
        ).fetchone() is not None)
        worker_alive = (c.execute(
            """SELECT 1 FROM task_queue
               WHERE status='running' LIMIT 1"""
        ).fetchone() is not None)
        latest = c.execute(
            """SELECT started_at, status FROM autopilot_cycles
               ORDER BY id DESC LIMIT 1"""
        ).fetchone()
    return {
        "autopilot_running": autopilot_alive,
        "worker_running": worker_alive,
        "last_cycle_at": latest[0] if latest else None,
        "last_cycle_status": latest[1] if latest else None,
        "hint": ("使用 `python -m scripts.run_autopilot` 单独启动 autopilot. "
                 "此 endpoint 只观察状态."),
    }


@router.get("/autopilot/cycles")
def api_autopilot_cycles(limit: int = 20):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, cycle_id, started_at, ended_at, duration_ms,
                      checks_run, failures_found, heals_proposed,
                      heals_applied, agents_triggered, summary, status
               FROM autopilot_cycles
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        cols = ["id","cycle_id","started_at","ended_at","duration_ms",
                "checks_run","failures_found","heals_proposed",
                "heals_applied","agents_triggered","summary","status"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["agents_triggered"] = json.loads(d["agents_triggered"] or "[]")
            except Exception:
                d["agents_triggered"] = []
            out.append(d)
        return {"cycles": out}
    finally:
        db.close()


@router.get("/autopilot/diagnoses")
def api_autopilot_diagnoses(limit: int = 50):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, cycle_id, playbook_code, task_type, diagnosis,
                      confidence, affected_entities, created_at
               FROM healing_diagnoses
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        cols = ["id","cycle_id","playbook_code","task_type","diagnosis",
                "confidence","affected_entities","created_at"]
        return {"diagnoses": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.get("/autopilot/actions")
def api_autopilot_actions(limit: int = 50):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, cycle_id, playbook_code, action, status,
                      target_ids, result_json, error_message,
                      created_at, completed_at
               FROM healing_actions
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        cols = ["id","cycle_id","playbook_code","action","status",
                "target_ids","result_json","error_message",
                "created_at","completed_at"]
        out = []
        for r in rows:
            d = dict(zip(cols, r))
            try:
                d["result"] = json.loads(d.pop("result_json") or "{}")
            except Exception:
                d["result"] = {}
            out.append(d)
        return {"actions": out}
    finally:
        db.close()


@router.get("/autopilot/playbook")
def api_autopilot_playbook():
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, code, symptom_pattern, task_type, min_occurrences,
                      diagnosis, remedy_action, confidence,
                      is_active, success_count, fail_count
               FROM healing_playbook ORDER BY id"""
        ).fetchall()
        cols = ["id","code","symptom_pattern","task_type","min_occurrences",
                "diagnosis","remedy_action","confidence",
                "is_active","success_count","fail_count"]
        return {"playbook": [dict(zip(cols, r)) for r in rows]}
    finally:
        db.close()


@router.get("/snapshot/status")
def api_snapshot_status():
    """每日快照调度状态 — 改读 agent_run_state / autopilot_cycles."""
    import sqlite3
    from core.config import DB_PATH
    with sqlite3.connect(DB_PATH, timeout=5) as c:
        row = c.execute(
            """SELECT last_run_at, last_result FROM agent_run_state
               WHERE agent_name='mcn_member_snapshot'"""
        ).fetchone()
    return {
        "last_run_at": row[0] if row else None,
        "last_result": row[1] if row else None,
        "hint": "由 ControllerAgent 按 cron 调 (每日 23:50). 若需手工触发见 /snapshot/trigger",
    }


@router.post("/snapshot/trigger")
def api_snapshot_trigger():
    """立即跑一次每日快照 — 直接调 scripts.snapshot_mcn_members."""
    try:
        import subprocess, sys
        # 后台启动 (不阻塞 http 返回)
        subprocess.Popen([sys.executable, "-m", "scripts.snapshot_mcn_members"],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {"ok": True, "message": "快照已在后台启动, 约 30s-2min 完成"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


@router.get("/sig/health")
def api_sig_health():
    """SigService (__NS_sig3 远程端点) 健康 + 缓存状态."""
    from core.sig_service import SigService, _load_endpoints
    return {
        "configured_endpoints": _load_endpoints(),
        "endpoint_health": SigService.health_report(),
        "cache_size": SigService.cache_size(),
    }


@router.post("/autopilot/trigger")
def api_autopilot_trigger():
    """手动触发一次 Controller cycle (测试用)."""
    db = _db()
    try:
        from core.agents.controller_agent import ControllerAgent
        return ControllerAgent(db).run_cycle()
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Report (24h 修复日报) + Upgrade (AI 升级提议)
# ---------------------------------------------------------------------------

@router.post("/autopilot/report/generate")
def api_autopilot_report_generate(hours: int = 24):
    """手动生成一份 AI 修复日报."""
    db = _db()
    try:
        from core.agents.report_agent import ReportAgent
        resp = ReportAgent(db).run({"hours": hours})
        return {
            "ok": True,
            "report_id": resp.get("meta", {}).get("report_id"),
            "summary": resp.get("meta", {}).get("summary_text", ""),
            "findings": resp.get("findings", []),
            "recommendations": resp.get("recommendations", []),
        }
    finally:
        db.close()


@router.get("/autopilot/reports")
def api_autopilot_reports(limit: int = 20):
    """近 N 份 AI 修复日报."""
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, window_hours, summary_text, findings_json, created_at
               FROM healing_reports ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    except Exception:
        return {"reports": []}
    finally:
        db.close()
    out = []
    for r in rows:
        try:
            findings = json.loads(r[3] or "[]")
        except Exception:
            findings = []
        out.append({
            "id": r[0],
            "window_hours": r[1],
            "summary_text": r[2],
            "findings": findings,
            "created_at": r[4],
        })
    return {"reports": out}


@router.post("/autopilot/upgrade/scan")
def api_autopilot_upgrade_scan(days: int = 7, min_occurrences: int = 3):
    """手动触发 UpgradeAgent 扫描."""
    db = _db()
    try:
        from core.agents.upgrade_agent import UpgradeAgent
        resp = UpgradeAgent(db).run({
            "days": days, "min_occurrences": min_occurrences,
        })
        return {
            "ok": True,
            "meta": resp.get("meta", {}),
            "findings": resp.get("findings", []),
            "recommendations": resp.get("recommendations", []),
        }
    finally:
        db.close()


@router.get("/autopilot/upgrades")
def api_autopilot_upgrades(status: str = "pending", limit: int = 50):
    """列出升级提议. status ∈ pending / approved / rejected / applied / all."""
    db = _db()
    try:
        if status == "all":
            rows = db.conn.execute(
                """SELECT id, upgrade_type, target_file, reason,
                          current_state, proposed_state, evidence_json,
                          confidence, status, created_at, decided_at,
                          decision_note, proposer
                   FROM upgrade_proposals ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        else:
            rows = db.conn.execute(
                """SELECT id, upgrade_type, target_file, reason,
                          current_state, proposed_state, evidence_json,
                          confidence, status, created_at, decided_at,
                          decision_note, proposer
                   FROM upgrade_proposals WHERE status=? ORDER BY id DESC LIMIT ?""",
                (status, limit),
            ).fetchall()
    except Exception:
        return {"upgrades": []}
    finally:
        db.close()
    out = []
    for r in rows:
        def _jl(s):
            try: return json.loads(s or "{}")
            except Exception: return {}
        out.append({
            "id": r[0], "type": r[1], "target_code": r[2],
            "reason": r[3],
            "current": _jl(r[4]),
            "patch": _jl(r[5]),
            "evidence": _jl(r[6]),
            "confidence": r[7], "status": r[8],
            "created_at": r[9], "reviewed_at": r[10],
            "decision_note": r[11], "proposer": r[12],
        })
    return {"upgrades": out}


@router.post("/autopilot/upgrades/{pid}/approve")
def api_autopilot_upgrade_approve(pid: int):
    db = _db()
    try:
        db.conn.execute(
            """UPDATE upgrade_proposals SET status='approved',
                 decided_at=datetime('now','localtime'),
                 decision_note='approved via dashboard'
               WHERE id=?""",
            (pid,),
        )
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


@router.post("/autopilot/upgrades/{pid}/reject")
def api_autopilot_upgrade_reject(pid: int):
    db = _db()
    try:
        db.conn.execute(
            """UPDATE upgrade_proposals SET status='rejected',
                 decided_at=datetime('now','localtime'),
                 decision_note='rejected via dashboard'
               WHERE id=?""",
            (pid,),
        )
        db.conn.commit()
        return {"ok": True}
    finally:
        db.close()


@router.get("/bulk-ops")
def api_bulk_ops(limit: int = 50):
    db = _db()
    try:
        rows = db.conn.execute(
            """SELECT id, op_code, target_type, target_ids_json, params_json,
                      affected_count, operator, note, created_at
               FROM dashboard_bulk_ops ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            out.append({
                "id": r[0], "op_code": r[1], "target_type": r[2],
                "target_ids": json.loads(r[3] or "[]"),
                "params": json.loads(r[4] or "{}") if r[4] else {},
                "affected": r[5], "operator": r[6], "note": r[7], "created_at": r[8],
            })
        return {"ops": out}
    finally:
        db.close()
