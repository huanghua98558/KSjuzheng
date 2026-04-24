# -*- coding: utf-8 -*-
"""ReportAgent — 24h 自愈日报 / AI 修复报告.

职责:
  1. 聚合最近 24h autopilot_cycles / healing_diagnoses / healing_actions
  2. 统计 top N 故障类别 + playbook 命中率 + 自愈成功率
  3. 对接 publish_results / task_queue 算"系统可用性 SLO"
  4. 如果启用 LLM (llm_mode=hybrid), 让 LLM 写一段中文总结 + 建议
  5. 落 healing_reports 表 (新) + agent_runs

Controller 每 24h 触发一次 (或手动 /autopilot/report/generate).
"""
from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import datetime
from typing import Any

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.config import DB_PATH


def _wal_conn():
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=120.0,
                        isolation_level=None)
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=120000")
    return c


class ReportAgent(BaseAgent):
    name = "report"
    llm_mode = "hybrid"   # 规则先算统计, LLM 再加一段叙事总结

    def _compute(self, payload: dict) -> dict:
        hours = int(payload.get("hours", 24))
        wc = _wal_conn()

        # 1. 扫 autopilot_cycles
        cycles = wc.execute(
            """SELECT cycle_id, started_at, duration_ms, checks_run,
                      failures_found, heals_proposed, heals_applied,
                      agents_triggered, summary, status
               FROM autopilot_cycles
               WHERE datetime(started_at) >= datetime('now', ?)
               ORDER BY id DESC""",
            (f"-{hours} hours",),
        ).fetchall()

        total_cycles = len(cycles)
        total_failures = sum(c[4] or 0 for c in cycles)
        total_heals_proposed = sum(c[5] or 0 for c in cycles)
        total_heals_applied = sum(c[6] or 0 for c in cycles)
        cycle_error_count = sum(1 for c in cycles if c[9] == "error")

        # 2. 扫 healing_diagnoses
        diagnoses = wc.execute(
            """SELECT playbook_code, task_type, confidence, created_at
               FROM healing_diagnoses
               WHERE datetime(created_at) >= datetime('now', ?)""",
            (f"-{hours} hours",),
        ).fetchall()

        by_code = Counter(d[0] for d in diagnoses)
        by_task_type = Counter(d[1] for d in diagnoses)

        # 3. 扫 healing_actions
        actions = wc.execute(
            """SELECT action, status, playbook_code
               FROM healing_actions
               WHERE datetime(created_at) >= datetime('now', ?)""",
            (f"-{hours} hours",),
        ).fetchall()

        action_total = len(actions)
        action_success = sum(1 for a in actions if a[1] == "success")
        action_success_rate = (action_success / action_total) if action_total else 0.0

        # 4. 扫 playbook 当前置信 + 成功率
        pb = wc.execute(
            """SELECT code, confidence, success_count, fail_count, is_active
               FROM healing_playbook ORDER BY success_count DESC""",
        ).fetchall()
        playbook_snapshot = [
            {
                "code": r[0],
                "confidence": float(r[1]),
                "success": r[2] or 0,
                "fail": r[3] or 0,
                "success_rate": (r[2] / max(1, (r[2] or 0) + (r[3] or 0))) if r else 0,
                "is_active": bool(r[4]),
            }
            for r in pb
        ]

        # 5. 扫 task_queue SLO
        tq_stats = wc.execute(
            """SELECT status, COUNT(*) FROM task_queue
               WHERE datetime(created_at) >= datetime('now', ?)
               GROUP BY status""",
            (f"-{hours} hours",),
        ).fetchall()
        tq_by_status = {r[0]: r[1] for r in tq_stats}
        tq_total = sum(tq_by_status.values())
        tq_success = tq_by_status.get("success", 0)
        tq_fail = tq_by_status.get("failed", 0) + tq_by_status.get("dead_letter", 0)
        availability = (tq_success / max(1, tq_total)) if tq_total else 0.0

        # 6. 最严重的未修复类别 (连续匹配但 remedy fail 的)
        still_hurt = wc.execute(
            """SELECT playbook_code, COUNT(*) as n
               FROM healing_actions
               WHERE status='failed' AND datetime(created_at) >= datetime('now', ?)
               GROUP BY playbook_code ORDER BY n DESC LIMIT 5""",
            (f"-{hours} hours",),
        ).fetchall()

        # 7. 未发布的活账号 (diag: 可能账号下线)
        idle_accounts = wc.execute(
            """SELECT COUNT(*) FROM device_accounts
               WHERE login_status='logged_in'
                 AND kuaishou_uid NOT IN (
                   SELECT DISTINCT account_id FROM task_queue
                   WHERE task_type='PUBLISH_A' AND status='success'
                     AND datetime(finished_at) >= datetime('now', ?))""",
            (f"-{hours} hours",),
        ).fetchone()[0]

        # 8. 汇总 findings
        findings = [
            {
                "type": "cycles_summary",
                "message": (f"近 {hours}h Controller 运行 {total_cycles} 轮"
                            f"{' (含 '+str(cycle_error_count)+' 次异常)' if cycle_error_count else ''}"),
                "total_cycles": total_cycles,
                "total_failures": total_failures,
                "total_heals_applied": total_heals_applied,
                "heal_rate": (total_heals_applied / max(1, total_failures)) if total_failures else 1.0,
                "confidence": 1.0,
            },
            {
                "type": "top_diagnoses",
                "message": "高频故障 TOP 3",
                "top": [{"code": c, "count": n} for c, n in by_code.most_common(3)],
                "by_task_type": dict(by_task_type),
                "confidence": 1.0,
            },
            {
                "type": "remedy_stats",
                "message": (f"修复动作 {action_total} 次,"
                            f" 成功率 {action_success_rate*100:.0f}%"),
                "action_total": action_total,
                "action_success": action_success,
                "action_success_rate": round(action_success_rate, 4),
                "confidence": 1.0,
            },
            {
                "type": "system_slo",
                "message": (f"近 {hours}h 任务成功率 {availability*100:.0f}%"
                            f" ({tq_success}/{tq_total}, 失败 {tq_fail})"),
                "availability": round(availability, 4),
                "total_tasks": tq_total,
                "success_tasks": tq_success,
                "failed_tasks": tq_fail,
                "confidence": 1.0,
            },
            {
                "type": "playbook_evolution",
                "message": f"当前规则库 {len(playbook_snapshot)} 条",
                "playbook": playbook_snapshot,
                "confidence": 1.0,
            },
        ]

        if still_hurt:
            findings.append({
                "type": "unresolved_pain",
                "message": "仍在流血的故障类别 (remedy 已尝试但失败)",
                "items": [{"code": c, "fail_count": n} for c, n in still_hurt],
                "confidence": 0.9,
            })

        if idle_accounts > 0:
            findings.append({
                "type": "idle_accounts",
                "message": f"{idle_accounts} 个活账号近 {hours}h 无成功发布",
                "count": idle_accounts,
                "confidence": 0.8,
            })

        # 9. 写 healing_reports
        report_text = self._text_summary(findings)
        report_id = self._persist_report(wc, hours, report_text, findings)

        recommendations = self._build_recommendations(
            findings, still_hurt, idle_accounts, availability, playbook_snapshot,
        )

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.95,
            findings=findings,
            recommendations=recommendations,
            meta={
                "report_id": report_id,
                "hours": hours,
                "summary_text": report_text,
            },
        )

    # ------------------------------------------------------------------

    def _text_summary(self, findings: list) -> str:
        lines = []
        for f in findings:
            if f["type"] == "cycles_summary":
                lines.append(
                    f"【Controller】{f['total_cycles']} 轮 · "
                    f"发现 {f['total_failures']} 失败 · 修复 {f['total_heals_applied']} 个 · "
                    f"自愈率 {f['heal_rate']*100:.0f}%"
                )
            elif f["type"] == "top_diagnoses":
                top = " / ".join(f"{t['code']}×{t['count']}" for t in f.get("top", []))
                if top:
                    lines.append(f"【高频故障】{top}")
            elif f["type"] == "remedy_stats":
                lines.append(
                    f"【修复】动作 {f['action_total']} 次 · "
                    f"成功率 {f['action_success_rate']*100:.0f}%"
                )
            elif f["type"] == "system_slo":
                lines.append(
                    f"【SLO】任务成功率 {f['availability']*100:.0f}% "
                    f"({f['success_tasks']}/{f['total_tasks']})"
                )
            elif f["type"] == "unresolved_pain":
                pains = " / ".join(f"{i['code']}×{i['fail_count']}"
                                   for i in f.get("items", []))
                lines.append(f"【仍流血】{pains}")
            elif f["type"] == "idle_accounts":
                lines.append(f"【静默账号】{f['count']} 个账号今日未出货")
        return "\n".join(lines)

    def _build_recommendations(self, findings, still_hurt, idle_accounts,
                               availability, playbook) -> list:
        recs = []
        if availability < 0.8:
            recs.append({
                "action": "raise_incident",
                "severity": "high",
                "message": f"任务成功率仅 {availability*100:.0f}% — 建议人工介入",
            })
        if still_hurt:
            code, n = still_hurt[0][0], still_hurt[0][1]
            recs.append({
                "action": "review_playbook_rule",
                "target_code": code,
                "message": f"playbook[{code}] 近期失败 {n} 次 — 建议 UpgradeAgent 提议改进 remedy",
            })
        if idle_accounts >= 3:
            recs.append({
                "action": "check_account_health",
                "count": idle_accounts,
                "message": f"{idle_accounts} 账号静默 — 检查 cookie / 账号封禁 / 配额",
            })
        # 低成功率规则
        low_pb = [p for p in playbook
                  if p["success"] + p["fail"] >= 3 and p["success_rate"] < 0.5]
        if low_pb:
            recs.append({
                "action": "demote_playbook",
                "items": [p["code"] for p in low_pb],
                "message": f"低成功率规则 {len(low_pb)} 条 — 建议标 inactive 或重写",
            })
        if not recs:
            recs.append({
                "action": "system_healthy",
                "message": "无需干预, 自愈闭环运行正常",
            })
        return recs

    def _persist_report(self, wc: sqlite3.Connection, hours: int,
                         summary: str, findings: list) -> int | None:
        # 确保表
        wc.execute("""
            CREATE TABLE IF NOT EXISTS healing_reports (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                window_hours INTEGER,
                summary_text TEXT,
                findings_json TEXT,
                created_at TEXT DEFAULT (datetime('now','localtime'))
            )
        """)
        cur = wc.execute(
            """INSERT INTO healing_reports (window_hours, summary_text, findings_json)
               VALUES (?, ?, ?)""",
            (hours, summary,
             json.dumps(findings, ensure_ascii=False, default=str)[:80000]),
        )
        return cur.lastrowid
