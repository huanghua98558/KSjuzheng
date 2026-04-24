# -*- coding: utf-8 -*-
"""数据分析中心 — 多维透视 (账号/剧种/时段/通道).

数据源:
  publish_results              (发布事务真相 — channel/时段/成功率)
  content_performance_daily    (作品 ROI)
  account_performance_daily    (账号进度)
  mcn_income_snapshots         (收益)
  task_queue                   (任务层面指标)
"""
from __future__ import annotations

from fastapi import APIRouter, Request

from core.auth import current_user, _db

router = APIRouter()


# ---------------------------------------------------------------------------

@router.get("/overview")
def overview(request: Request, days: int = 7):
    """顶部 KPI: 近 N 天发布数 / 成功率 / 作品总播放 / 收益."""
    current_user(request)
    conn = _db()
    try:
        pr = conn.execute(
            """SELECT COUNT(*) total,
                      SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) ok,
                      SUM(CASE WHEN verify_status='verified' THEN 1 ELSE 0 END) verified,
                      COUNT(DISTINCT account_id) accounts_active,
                      COUNT(DISTINCT drama_name) dramas_used
               FROM publish_results
               WHERE created_at >= datetime('now', ?)""",
            (f"-{int(days)} days",),
        ).fetchone()
        inc = conn.execute(
            """SELECT
                   SUM(commission_amount) commission_sum,
                   SUM(total_amount) gross_sum
               FROM mcn_income_snapshots
               WHERE snapshot_date >= date('now', ?)""",
            (f"-{int(days)} days",),
        ).fetchone()
        work = conn.execute(
            """SELECT
                   SUM(view_count) views_sum,
                   SUM(like_count) likes_sum,
                   SUM(comment_count) comments_sum,
                   COUNT(DISTINCT photo_id) photos
               FROM content_performance_daily
               WHERE snapshot_date >= date('now', ?)""",
            (f"-{int(days)} days",),
        ).fetchone()
    finally:
        conn.close()
    total = pr["total"] or 0
    ok = pr["ok"] or 0
    return {
        "days": days,
        "publish_total": total,
        "publish_success": ok,
        "publish_success_rate": round(ok / max(1, total), 4),
        "publish_verified": pr["verified"] or 0,
        "accounts_active": pr["accounts_active"] or 0,
        "dramas_used": pr["dramas_used"] or 0,
        "income_commission": round(inc["commission_sum"] or 0, 2),
        "income_gross": round(inc["gross_sum"] or 0, 2),
        "content_views": work["views_sum"] or 0,
        "content_likes": work["likes_sum"] or 0,
        "content_comments": work["comments_sum"] or 0,
        "content_photos": work["photos"] or 0,
    }


@router.get("/by-account")
def by_account(request: Request, days: int = 7):
    """每账号的发布数/成功率/最近视频表现."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT pr.account_id,
                      da.account_name,
                      da.kuaishou_uid,
                      COUNT(pr.id) publish_total,
                      SUM(CASE WHEN pr.publish_status='success' THEN 1 ELSE 0 END) publish_ok,
                      MAX(pr.created_at) last_publish_at,
                      (SELECT SUM(view_count) FROM content_performance_daily
                       WHERE account_id = pr.account_id
                         AND snapshot_date >= date('now', ?)) views_recent,
                      (SELECT SUM(commission_amount) FROM mcn_income_snapshots
                       WHERE kuaishou_uid = da.kuaishou_uid
                         AND snapshot_date >= date('now', ?)) income_recent
               FROM publish_results pr
               LEFT JOIN device_accounts da
                 ON CAST(da.id AS TEXT) = pr.account_id
               WHERE pr.created_at >= datetime('now', ?)
               GROUP BY pr.account_id
               ORDER BY publish_total DESC""",
            (f"-{int(days)} days", f"-{int(days)} days",
             f"-{int(days)} days"),
        ).fetchall()
    finally:
        conn.close()
    return {"rows": [dict(r) for r in rows]}


@router.get("/by-drama")
def by_drama(request: Request, days: int = 7, limit: int = 30):
    """每剧种的发布分布 + 平均播放."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT pr.drama_name,
                      COUNT(*) publish_total,
                      SUM(CASE WHEN pr.publish_status='success' THEN 1 ELSE 0 END) ok,
                      COUNT(DISTINCT pr.account_id) accounts,
                      COUNT(DISTINCT pr.photo_id) photos_uniq
               FROM publish_results pr
               WHERE pr.drama_name != '' AND pr.drama_name IS NOT NULL
                 AND pr.created_at >= datetime('now', ?)
               GROUP BY pr.drama_name
               ORDER BY publish_total DESC
               LIMIT ?""",
            (f"-{int(days)} days", limit),
        ).fetchall()
    finally:
        conn.close()
    return {"rows": [dict(r) for r in rows]}


@router.get("/by-hour")
def by_hour(request: Request, days: int = 14):
    """按发布小时 0-23 聚合成功率 — 找最佳发布时段."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT
                   CAST(strftime('%H', published_at) AS INTEGER) hour,
                   COUNT(*) total,
                   SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) ok
               FROM publish_results
               WHERE published_at IS NOT NULL
                 AND created_at >= datetime('now', ?)
               GROUP BY hour
               ORDER BY hour""",
            (f"-{int(days)} days",),
        ).fetchall()
    finally:
        conn.close()
    # 补齐空小时
    by_h = {r["hour"]: dict(r) for r in rows}
    out = []
    for h in range(24):
        r = by_h.get(h) or {"hour": h, "total": 0, "ok": 0}
        r["rate"] = round((r["ok"] or 0) / max(1, r["total"] or 1), 4)
        out.append(r)
    return {"rows": out}


@router.get("/by-channel")
def by_channel(request: Request, days: int = 14):
    """通道 A/B 成功率对比."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT
                   channel_type,
                   COUNT(*) total,
                   SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) ok,
                   SUM(CASE WHEN publish_status='failed' THEN 1 ELSE 0 END) fail,
                   COUNT(DISTINCT account_id) accounts
               FROM publish_results
               WHERE created_at >= datetime('now', ?)
               GROUP BY channel_type
               ORDER BY total DESC""",
            (f"-{int(days)} days",),
        ).fetchall()
    finally:
        conn.close()
    out = []
    for r in rows:
        d = dict(r)
        d["rate"] = round((d["ok"] or 0) / max(1, d["total"] or 1), 4)
        out.append(d)
    return {"rows": out}


@router.get("/top-content")
def top_content(request: Request, days: int = 7, limit: int = 20):
    """近 N 天最佳作品 (按播放量)."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT cpd.photo_id, cpd.account_id,
                      MAX(cpd.view_count) max_views,
                      MAX(cpd.like_count) max_likes,
                      MAX(cpd.comment_count) max_comments,
                      pr.drama_name, pr.caption
               FROM content_performance_daily cpd
               LEFT JOIN publish_results pr ON pr.photo_id = cpd.photo_id
               WHERE cpd.snapshot_date >= date('now', ?)
                 AND cpd.view_count > 0
               GROUP BY cpd.photo_id
               ORDER BY max_views DESC
               LIMIT ?""",
            (f"-{int(days)} days", limit),
        ).fetchall()
    finally:
        conn.close()
    return {"rows": [dict(r) for r in rows]}


@router.get("/failure-reasons")
def failure_reasons(request: Request, days: int = 7, limit: int = 20):
    """失败原因聚类 (近 N 天 publish_results failure_reason 归类)."""
    current_user(request)
    conn = _db()
    try:
        rows = conn.execute(
            """SELECT
                   SUBSTR(failure_reason, 1, 80) reason,
                   COUNT(*) n,
                   COUNT(DISTINCT account_id) accounts
               FROM publish_results
               WHERE publish_status='failed' AND failure_reason != ''
                 AND created_at >= datetime('now', ?)
               GROUP BY reason
               ORDER BY n DESC LIMIT ?""",
            (f"-{int(days)} days", limit),
        ).fetchall()
    finally:
        conn.close()
    return {"rows": [dict(r) for r in rows]}
