# -*- coding: utf-8 -*-
"""异常中心 — 聚合全矩阵的"需要人/系统看一眼"的事件.

六路聚合 (按 severity 排序后统一输出):
  1. 失败任务        task_queue where status IN ('failed','dead_letter','waiting_manual')
  2. 降级 Agent      agent_runs where status IN ('degraded','error')
  3. 低健康账号      account_health_snapshots where health_score<70
  4. 系统事件        system_events where event_level IN ('warning','error','critical') AND acknowledged=0
  5. MCN 掉线        mcn_account_bindings where last_verified_at older than 24h
  6. 发布失败        publish_results where publish_status='failed'

输出结构 (每条):
  {
    "id":              "incident_<type>_<db_id>",
    "type":            "task_failed | agent_degraded | health_low | ...",
    "severity":        "low | medium | high | critical",
    "entity_type":     "task | agent_run | account | event | binding | publish",
    "entity_id":       "...",
    "title":           "中文一句话",
    "description":     "中文详情",
    "suggested_action":"中文建议",
    "created_at":      "...",
    "can_retry":       True/False,
    "can_acknowledge": True/False,
    "raw_ref":         {...}
  }

单点调用:
  center = IncidentCenter(db)
  data = center.list_all(severity='>=high', hours=24, limit=200)
  center.acknowledge([id1, id2], operator='dashboard')
  center.retry(incident_id)
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any


SEVERITY_RANK = {"low": 1, "medium": 2, "high": 3, "critical": 4}


def _sev_ge(a: str, threshold: str) -> bool:
    return SEVERITY_RANK.get(a, 0) >= SEVERITY_RANK.get(threshold, 0)


class IncidentCenter:
    def __init__(self, db_manager):
        self.db = db_manager

    # ==================================================================
    # 汇总入口
    # ==================================================================

    def list_all(self, *, severity: str = "low",
                 hours: int = 48, limit: int = 500) -> list[dict]:
        """按时间窗口 + 最小 severity 聚合所有异常."""
        out: list[dict] = []
        out.extend(self._failed_tasks(hours=hours))
        out.extend(self._degraded_agents(hours=hours))
        out.extend(self._low_health())
        out.extend(self._open_system_events())
        out.extend(self._mcn_stale(stale_hours=24))
        out.extend(self._publish_failures(hours=hours))

        # 过滤 severity
        if severity and severity != "low":
            out = [x for x in out if _sev_ge(x["severity"], severity)]

        # 排序: severity desc, created_at desc
        out.sort(key=lambda x: (-SEVERITY_RANK.get(x["severity"], 0),
                                x.get("created_at", "")), reverse=False)
        # 实际上我们要 created_at desc — 重排
        out.sort(key=lambda x: x.get("created_at", ""), reverse=True)
        out.sort(key=lambda x: SEVERITY_RANK.get(x["severity"], 0), reverse=True)

        return out[:limit]

    def summary(self) -> dict[str, Any]:
        """给 UI 顶部卡片用."""
        all_inc = self.list_all(hours=48, limit=10000)
        by_sev: dict[str, int] = {}
        by_type: dict[str, int] = {}
        for x in all_inc:
            by_sev[x["severity"]] = by_sev.get(x["severity"], 0) + 1
            by_type[x["type"]] = by_type.get(x["type"], 0) + 1
        return {
            "total": len(all_inc),
            "by_severity": by_sev,
            "by_type": by_type,
            "critical": by_sev.get("critical", 0),
            "high": by_sev.get("high", 0),
        }

    # ==================================================================
    # 六路子查询
    # ==================================================================

    def _failed_tasks(self, hours: int = 48) -> list[dict]:
        try:
            rows = self.db.conn.execute(
                """SELECT id, task_type, account_id, drama_name, status,
                          error_message, retry_count, max_retries,
                          created_at, finished_at
                   FROM task_queue
                   WHERE status IN ('failed','dead_letter','waiting_manual')
                     AND datetime(created_at) >= datetime('now', ?)
                   ORDER BY id DESC LIMIT 200""",
                (f"-{hours} hours",),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            status = r[4]
            sev = ("critical" if status == "dead_letter"
                   else "high" if status == "failed"
                   else "medium")
            out.append({
                "id": f"incident_task_{r[0]}",
                "type": f"task_{status}",
                "severity": sev,
                "entity_type": "task",
                "entity_id": str(r[0]),
                "title": f"任务 #{r[0]} {r[1]} {status}",
                "description": (r[5] or "")[:200],
                "suggested_action": (
                    "人工复查后决定重试或放弃" if status == "waiting_manual"
                    else "已用尽重试次数, 手动介入" if status == "dead_letter"
                    else "点击重试按钮重新排队"
                ),
                "created_at": r[8],
                "can_retry": status in ("failed", "waiting_manual"),
                "can_acknowledge": True,
                "raw_ref": {
                    "task_id": r[0], "task_type": r[1],
                    "account_id": r[2], "drama_name": r[3],
                    "retry_count": r[6], "max_retries": r[7],
                },
            })
        return out

    def _degraded_agents(self, hours: int = 48) -> list[dict]:
        try:
            rows = self.db.conn.execute(
                """SELECT id, agent_name, run_id, status, error_code,
                          error_message, latency_ms, created_at
                   FROM agent_runs
                   WHERE status IN ('degraded','error')
                     AND datetime(created_at) >= datetime('now', ?)
                   ORDER BY id DESC LIMIT 100""",
                (f"-{hours} hours",),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            sev = "high" if r[3] == "error" else "medium"
            out.append({
                "id": f"incident_agent_{r[0]}",
                "type": f"agent_{r[3]}",
                "severity": sev,
                "entity_type": "agent_run",
                "entity_id": r[2],
                "title": f"{r[1]} Agent {r[3]}",
                "description": f"{r[4] or '-'}: {(r[5] or '')[:150]}",
                "suggested_action": "打开 Agents 中枢 > 调试 Tab 查看完整 input/output",
                "created_at": r[7],
                "can_retry": True,
                "can_acknowledge": True,
                "raw_ref": {
                    "agent_run_id": r[0], "run_id": r[2],
                    "agent_name": r[1], "error_code": r[4],
                    "latency_ms": r[6],
                },
            })
        return out

    def _low_health(self) -> list[dict]:
        try:
            rows = self.db.conn.execute(
                """SELECT hs.id, hs.account_id, hs.health_score,
                          hs.publish_fail_count_1d, hs.publish_fail_count_7d,
                          hs.notes, hs.snapshot_date,
                          da.account_name
                   FROM account_health_snapshots hs
                   LEFT JOIN device_accounts da ON da.kuaishou_uid = hs.account_id
                   WHERE hs.snapshot_date = (SELECT MAX(snapshot_date) FROM account_health_snapshots)
                     AND hs.health_score < 70
                   ORDER BY hs.health_score ASC LIMIT 100"""
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            score = r[2] or 0
            sev = "critical" if score < 40 else "high" if score < 60 else "medium"
            name = r[7] or r[1]
            out.append({
                "id": f"incident_health_{r[0]}",
                "type": "health_low",
                "severity": sev,
                "entity_type": "account",
                "entity_id": r[1],
                "title": f"账号 {name} 健康度 {score:.0f}",
                "description": f"近 1 日发布失败 {r[3] or 0} 次, 近 7 日 {r[4] or 0} 次; 备注: {(r[5] or '')[:100]}",
                "suggested_action": (
                    "建议立即人工复查 cookie / MCN 绑定" if score < 40
                    else "建议暂停发布并检查登录态"
                ),
                "created_at": r[6],
                "can_retry": False,
                "can_acknowledge": True,
                "raw_ref": {
                    "snapshot_id": r[0],
                    "kuaishou_uid": r[1],
                    "health_score": score,
                    "account_name": name,
                },
            })
        return out

    def _open_system_events(self) -> list[dict]:
        try:
            rows = self.db.conn.execute(
                """SELECT id, event_type, event_level, source_module, entity_type,
                          entity_id, payload, created_at
                   FROM system_events
                   WHERE event_level IN ('warning','error','critical')
                     AND COALESCE(acknowledged, 0) = 0
                   ORDER BY id DESC LIMIT 100"""
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            level = r[2]
            sev = ("critical" if level == "critical"
                   else "high" if level == "error"
                   else "medium")
            try:
                payload = json.loads(r[6] or "{}")
            except Exception:
                payload = {}
            out.append({
                "id": f"incident_event_{r[0]}",
                "type": f"event_{r[1]}",
                "severity": sev,
                "entity_type": "event",
                "entity_id": str(r[0]),
                "title": f"{r[1]} [{r[3]}]",
                "description": json.dumps(payload, ensure_ascii=False)[:200],
                "suggested_action": "检查 source_module 日志后标记已读",
                "created_at": r[7],
                "can_retry": False,
                "can_acknowledge": True,
                "raw_ref": {
                    "event_id": r[0],
                    "source_module": r[3],
                    "entity_type": r[4], "entity_id": r[5],
                },
            })
        return out

    def _mcn_stale(self, stale_hours: int = 24) -> list[dict]:
        """MCN 绑定 last_verified_at 超过 X 小时未刷新 (仅限已登录账号)."""
        try:
            rows = self.db.conn.execute(
                """SELECT b.id, b.kuaishou_uid, b.account_name,
                          b.commission_rate, b.last_verified_at,
                          da.account_name AS local_name
                   FROM mcn_account_bindings b
                   JOIN device_accounts da ON da.kuaishou_uid = b.kuaishou_uid
                   WHERE da.login_status='logged_in'
                     AND (b.last_verified_at IS NULL
                          OR datetime(b.last_verified_at) < datetime('now', ?))
                   ORDER BY b.last_verified_at ASC LIMIT 50""",
                (f"-{stale_hours} hours",),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            hours_ago = "从未验证" if not r[4] else "已过期"
            sev = "high" if not r[4] else "medium"
            name = r[5] or r[2] or r[1]
            out.append({
                "id": f"incident_mcn_{r[0]}",
                "type": "mcn_stale",
                "severity": sev,
                "entity_type": "binding",
                "entity_id": r[1],
                "title": f"MCN 绑定 {name} {hours_ago}",
                "description": f"uid={r[1]} commission_rate={r[3]} last_verified={r[4] or '-'}",
                "suggested_action": "在账号页点击'重新验证 MCN' 或手动跑 sync_mcn_business",
                "created_at": r[4] or "",
                "can_retry": True,
                "can_acknowledge": True,
                "raw_ref": {
                    "binding_id": r[0], "kuaishou_uid": r[1],
                    "account_name": name,
                },
            })
        return out

    def _publish_failures(self, hours: int = 48) -> list[dict]:
        try:
            rows = self.db.conn.execute(
                """SELECT id, account_id, drama_name, channel_type,
                          failure_reason, retry_count, created_at
                   FROM publish_results
                   WHERE publish_status = 'failed'
                     AND datetime(created_at) >= datetime('now', ?)
                   ORDER BY id DESC LIMIT 100""",
                (f"-{hours} hours",),
            ).fetchall()
        except Exception:
            return []
        out = []
        for r in rows:
            retries = r[5] or 0
            sev = "high" if retries >= 2 else "medium"
            out.append({
                "id": f"incident_publish_{r[0]}",
                "type": "publish_failed",
                "severity": sev,
                "entity_type": "publish",
                "entity_id": str(r[0]),
                "title": f"发布失败: {r[2]} ({r[3]})",
                "description": (r[4] or "")[:200],
                "suggested_action": (
                    "重试 3 次仍失败, 需人工复查" if retries >= 3
                    else "点击重试发布"
                ),
                "created_at": r[6],
                "can_retry": True,
                "can_acknowledge": True,
                "raw_ref": {
                    "publish_id": r[0], "account_id": r[1],
                    "drama_name": r[2], "channel": r[3],
                    "retry_count": retries,
                },
            })
        return out

    # ==================================================================
    # Actions
    # ==================================================================

    def acknowledge(self, incident_ids: list[str], operator: str = "dashboard") -> dict:
        """批量标记已读 — 只对 system_events 类型生效."""
        acked = 0
        for iid in incident_ids:
            if not iid.startswith("incident_event_"):
                continue
            try:
                event_db_id = int(iid.split("_")[-1])
                self.db.conn.execute(
                    """UPDATE system_events SET
                         acknowledged = 1,
                         acknowledged_at = datetime('now','localtime'),
                         acknowledged_by = ?
                       WHERE id = ?""",
                    (operator, event_db_id),
                )
                acked += 1
            except Exception:
                continue
        self.db.conn.commit()
        # 审计
        try:
            self.db.conn.execute(
                """INSERT INTO dashboard_bulk_ops
                     (op_code, target_type, target_ids_json, affected_count,
                      operator, note)
                   VALUES ('ack_incidents', 'incident', ?, ?, ?, ?)""",
                (json.dumps(incident_ids, ensure_ascii=False),
                 acked, operator, f"acked {acked}/{len(incident_ids)}"),
            )
            self.db.conn.commit()
        except Exception:
            pass
        return {"acknowledged": acked, "total": len(incident_ids)}

    def retry(self, incident_id: str) -> dict:
        """按 incident type 路由到对应的重试行为 (大部分仅重置任务状态)."""
        if incident_id.startswith("incident_task_"):
            task_id = incident_id.removeprefix("incident_task_")
            try:
                cur = self.db.conn.execute(
                    """UPDATE task_queue
                       SET status='pending', retry_count=0, error_message='',
                           finished_at='', started_at=''
                       WHERE id=? AND status IN ('failed','waiting_manual','waiting_retry')""",
                    (task_id,),
                )
                self.db.conn.commit()
                return {"ok": True, "affected": cur.rowcount,
                        "note": "任务已重新入队为 pending"}
            except Exception as e:
                return {"ok": False, "error": str(e)}

        if incident_id.startswith("incident_mcn_"):
            binding_id = incident_id.removeprefix("incident_mcn_")
            return {"ok": True, "note": f"binding {binding_id} 请在账号页手动重新验证, 或跑 sync_mcn_business"}

        if incident_id.startswith("incident_publish_"):
            return {"ok": True, "note": "已记录, 请在发布结果页单独处理 (publisher.py 需重跑)"}

        return {"ok": False, "note": f"{incident_id} 不支持自动重试, 请手动处理"}
