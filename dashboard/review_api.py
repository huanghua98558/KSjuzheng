# -*- coding: utf-8 -*-
"""人工复核中心 — manual_review_items CRUD + task 联动.

流程:
  任何 failed / dead_letter / 待人工的 task_queue 行
    → POST /api/review/escalate  {task_id, reason, severity}
    → manual_review_items 新建一行 (manual_status=open)
    → task_queue.status = 'waiting_manual'

  运营打开 /review 页看待处理列表
    → GET /api/review/items?status=open

  运营点击决策:
    → POST /api/review/{id}/resolve  {action, note}
       action ∈ retry | cancel | skip | override_success
    → task_queue 回到对应状态 + manual_review_items 关闭
"""
from __future__ import annotations

import secrets
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from core.auth import current_user, write_audit, _db

router = APIRouter()


# ---------------------------------------------------------------------------

class EscalateBody(BaseModel):
    task_id: str
    reason: str = ""
    severity: str = "normal"   # low / normal / high / critical
    suggested_action: str = "retry"


class ResolveBody(BaseModel):
    action: str                # retry / cancel / skip / override_success
    note: str = ""


# ---------------------------------------------------------------------------

@router.post("/escalate")
def escalate(body: EscalateBody, request: Request):
    """把一个 task_queue 行人工升级到 waiting_manual + 落 manual_review_items."""
    u = current_user(request)
    conn = _db()
    try:
        t = conn.execute(
            """SELECT id, status, task_type, account_id, drama_name,
                      batch_id, error_message
               FROM task_queue WHERE id=?""",
            (body.task_id,),
        ).fetchone()
        if not t:
            raise HTTPException(status_code=404, detail="task not found")

        review_id = f"mr_{secrets.token_hex(6)}"
        conn.execute(
            """INSERT INTO manual_review_items
                 (review_id, source_type, source_id, task_queue_id,
                  batch_id, account_id,
                  manual_status, manual_reason, suggested_action,
                  severity)
               VALUES (?, 'task_queue', ?, ?, ?, ?, 'open', ?, ?, ?)""",
            (review_id, t["id"], t["id"], t["batch_id"], t["account_id"],
             body.reason or (t["error_message"] or "")[:300],
             body.suggested_action, body.severity),
        )
        # 同步 task_queue.status
        conn.execute(
            """UPDATE task_queue SET
                 status='waiting_manual',
                 manual_reason=?,
                 manual_operator=?,
                 manual_updated_at=datetime('now','localtime')
               WHERE id=?""",
            (body.reason or (t["error_message"] or "")[:300],
             u["username"], t["id"]),
        )
    finally:
        conn.close()

    ip = request.client.host if request.client else ""
    write_audit(u, action="review.escalate",
                target_type="task", target_id=str(body.task_id),
                after={"reason": body.reason, "severity": body.severity},
                ip=ip)
    return {"ok": True, "review_id": review_id}


@router.get("/items")
def items(request: Request, status: str = "open",
          severity: str = "", limit: int = 100):
    """列人工复核项. status: open / resolved / all."""
    current_user(request)
    conn = _db()
    try:
        sql = """SELECT mr.id, mr.review_id, mr.source_type, mr.source_id,
                        mr.task_queue_id, mr.batch_id, mr.account_id,
                        mr.manual_status, mr.manual_reason,
                        mr.suggested_action, mr.severity,
                        mr.assigned_to, mr.decided_action, mr.decision_notes,
                        mr.created_at, mr.resolved_at,
                        tq.task_type, tq.drama_name, tq.status AS task_status,
                        tq.error_message, tq.retry_count, tq.max_retries
                 FROM manual_review_items mr
                 LEFT JOIN task_queue tq ON tq.id = mr.task_queue_id
                 WHERE 1=1"""
        params: list = []
        if status == "open":
            sql += " AND mr.manual_status='open'"
        elif status == "resolved":
            sql += " AND mr.manual_status IN ('resolved','dismissed')"
        if severity:
            sql += " AND mr.severity=?"
            params.append(severity)
        sql += " ORDER BY mr.id DESC LIMIT ?"
        params.append(limit)
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()
    return {"items": [dict(r) for r in rows]}


@router.post("/{review_id}/resolve")
def resolve(review_id: str, body: ResolveBody, request: Request):
    """决策: retry / cancel / skip / override_success."""
    u = current_user(request)
    action = body.action.lower()
    if action not in ("retry", "cancel", "skip", "override_success"):
        raise HTTPException(status_code=400,
                            detail="action ∈ retry|cancel|skip|override_success")

    conn = _db()
    try:
        mr = conn.execute(
            """SELECT id, task_queue_id, manual_status
               FROM manual_review_items WHERE review_id=?""",
            (review_id,),
        ).fetchone()
        if not mr:
            raise HTTPException(status_code=404, detail="review not found")
        if mr["manual_status"] != "open":
            raise HTTPException(status_code=400,
                                detail=f"already {mr['manual_status']}")

        tid = mr["task_queue_id"]

        # 根据 action 决定 task_queue 新状态
        if action == "retry":
            # 重置为 pending, retry_count 清零
            conn.execute(
                """UPDATE task_queue SET
                     status='pending',
                     retry_count=0,
                     next_retry_at='',
                     manual_reason='',
                     manual_operator=?,
                     manual_updated_at=datetime('now','localtime'),
                     error_message=''
                   WHERE id=?""",
                (u["username"], tid),
            )
        elif action == "cancel":
            conn.execute(
                """UPDATE task_queue SET
                     status='canceled',
                     manual_operator=?,
                     manual_updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (u["username"], tid),
            )
        elif action == "skip":
            conn.execute(
                """UPDATE task_queue SET
                     status='skipped',
                     manual_operator=?,
                     manual_updated_at=datetime('now','localtime')
                   WHERE id=?""",
                (u["username"], tid),
            )
        elif action == "override_success":
            conn.execute(
                """UPDATE task_queue SET
                     status='success',
                     manual_operator=?,
                     manual_updated_at=datetime('now','localtime'),
                     error_message='OVERRIDDEN by '||?||': '||?
                   WHERE id=?""",
                (u["username"], u["username"], body.note or "no note", tid),
            )

        # 关闭 manual_review_items
        conn.execute(
            """UPDATE manual_review_items SET
                 manual_status='resolved',
                 decided_action=?,
                 decision_notes=?,
                 assigned_to=?,
                 resolved_at=datetime('now','localtime'),
                 updated_at=datetime('now','localtime')
               WHERE id=?""",
            (action, body.note, u["username"], mr["id"]),
        )
    finally:
        conn.close()

    ip = request.client.host if request.client else ""
    write_audit(u, action=f"review.resolve.{action}",
                target_type="review", target_id=review_id,
                note=body.note, ip=ip)
    return {"ok": True, "action": action, "task_id": tid}


@router.get("/stats")
def stats(request: Request):
    """复核看板 KPI."""
    current_user(request)
    conn = _db()
    try:
        row = conn.execute(
            """SELECT
                 SUM(CASE WHEN manual_status='open' THEN 1 ELSE 0 END) AS open,
                 SUM(CASE WHEN manual_status='resolved' THEN 1 ELSE 0 END) AS resolved,
                 SUM(CASE WHEN severity='critical' AND manual_status='open' THEN 1 ELSE 0 END) AS critical_open,
                 SUM(CASE WHEN severity='high' AND manual_status='open' THEN 1 ELSE 0 END) AS high_open,
                 COUNT(*) AS total
               FROM manual_review_items"""
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else {"open": 0, "resolved": 0, "total": 0}
