# -*- coding: utf-8 -*-
"""SelfHealingAgent — 失败自动归因 + 自动修复下发.

职责:
  1. 扫描 task_queue 最近 N 小时的 failed task
  2. 按 error_message 模式聚类 (用 healing_playbook 里的 symptom_pattern)
  3. 匹配到诊断 → 生成 healing_actions
  4. 自动执行修复 (不需要人工 approve 的常规动作)

内置修复动作 (remedy_action 分发):
  trigger_recollect_and_fallback_browser:
    → 触发 COLLECT task 重采集 + 把失败的 drama_links 标 deprecated
  mark_account_needs_relogin:
    → 设 signed_status=need_refresh + lifecycle_stage=dormant
  cancel_orphan_publish_and_reenqueue_upstream:
    → 取消 PUBLISH_A + 重新跑 DOWNLOAD→PROCESS
  pause_account_enter_cooldown:
    → 设 lifecycle_stage=dormant + 记 cooldown_until
  trigger_bulk_collect:
    → 批量入队 COLLECT task

每次执行成功/失败自动写 healing_actions 表,
成功率用来演化 healing_playbook.confidence.
"""
from __future__ import annotations

import json
import re
import secrets
from collections import defaultdict, Counter
from datetime import datetime
from typing import Any

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK


class SelfHealingAgent(BaseAgent):
    name = "self_healing"
    llm_mode = "rules"   # 规则驱动, 不必 LLM (可配 hybrid 让 LLM 参与诊断)

    def _compute(self, payload: dict) -> dict:
        hours = int(payload.get("hours", 2))
        cycle_id = payload.get("cycle_id") or f"cycle_{secrets.token_hex(4)}"
        findings: list = []
        actions: list = []

        # 1. 拉最近失败任务
        failed = self._safe(lambda: self.db.conn.execute(
            """SELECT id, task_type, account_id, drama_name,
                      error_message, params, batch_id, created_at
               FROM task_queue
               WHERE status IN ('failed','dead_letter')
                 AND datetime(finished_at) >= datetime('now', ?)
               ORDER BY id DESC""",
            (f"-{hours} hours",),
        ).fetchall(), [])

        if not failed:
            findings.append({
                "type": "no_failures", "source": "rules",
                "message": f"近 {hours}h 无失败任务, 系统健康",
                "confidence": 1.0,
            })
            return AgentResponse.make(
                self.name, run_id="",
                status=RESPONSE_STATUS_OK,
                confidence=1.0, findings=findings,
                recommendations=[],
                meta={"cycle_id": cycle_id, "failures_analyzed": 0},
            )

        findings.append({
            "type": "failures_found", "source": "rules",
            "count": len(failed),
            "message": f"近 {hours}h 扫到 {len(failed)} 个失败任务",
            "confidence": 1.0,
        })

        # 2. 读 playbook
        playbook = self._safe(lambda: self.db.conn.execute(
            """SELECT id, code, symptom_pattern, task_type, min_occurrences,
                      diagnosis, remedy_action, remedy_params, confidence
               FROM healing_playbook WHERE is_active=1"""
        ).fetchall(), [])

        # 3. 按 playbook 聚类
        # matches[playbook_code] = [task_dict, ...]
        matches: dict[str, list[dict]] = defaultdict(list)
        for (tid, tt, acct, drama, err, params, batch, created) in failed:
            err = err or ""
            task_dict = {
                "task_id": tid, "task_type": tt, "account_id": acct,
                "drama_name": drama, "error": err[:500],
                "batch_id": batch, "created_at": created,
            }
            for pb in playbook:
                (pb_id, code, pattern, pb_tt, min_occ, diag,
                 action, params_json, conf) = pb
                if pb_tt not in ("*", tt):
                    continue
                try:
                    if re.search(pattern, err, re.IGNORECASE):
                        matches[code].append(task_dict)
                except re.error:
                    continue

        # 4. 对每类匹配: 记录 diagnosis + 执行修复
        for code, tasks in matches.items():
            # 找 playbook
            pb_row = next((p for p in playbook if p[1] == code), None)
            if not pb_row:
                continue
            (pb_id, _code, _pattern, _tt, min_occ, diag,
             action, params_json, conf) = pb_row
            if len(tasks) < min_occ:
                continue

            # 落诊断
            diag_id = self._record_diagnosis(
                cycle_id=cycle_id, code=code, task_type=pb_row[3],
                evidence=tasks[:10], diagnosis=diag, confidence=conf,
            )
            findings.append({
                "type": "diagnosis", "source": "healing",
                "playbook_code": code,
                "affected_tasks": len(tasks),
                "diagnosis": diag,
                "confidence": conf,
                "message": f"[{code}] {diag} — 影响 {len(tasks)} 个任务",
            })

            # 执行修复
            try:
                remedy_params = json.loads(params_json or "{}")
            except Exception:
                remedy_params = {}
            result = self._execute_remedy(
                cycle_id, diag_id, code, action, remedy_params, tasks,
            )
            actions.append(result)

            # 更新 playbook 成功率
            self._update_playbook_stats(pb_id, result.get("ok", False))

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.9,
            findings=findings,
            recommendations=[{
                "action": "self_heal_applied",
                "count": len([a for a in actions if a.get("ok")]),
                "cycle_id": cycle_id,
                "source": "healing",
            }],
            meta={
                "cycle_id": cycle_id,
                "failures_analyzed": len(failed),
                "diagnoses_matched": len(matches),
                "actions_taken": actions,
            },
        )

    # ==================================================================
    # 修复动作分发
    # ==================================================================

    def _execute_remedy(self, cycle_id: str, diag_id: int, code: str,
                        action: str, params: dict,
                        affected_tasks: list[dict]) -> dict:
        """分发到具体的修复函数."""
        handlers = {
            "trigger_recollect_and_fallback_browser":
                self._heal_recollect_and_fallback,
            "mark_account_needs_relogin":
                self._heal_mark_relogin,
            "cancel_orphan_publish_and_reenqueue_upstream":
                self._heal_reenqueue_upstream,
            "pause_account_enter_cooldown":
                self._heal_pause_account,
            "trigger_bulk_collect":
                self._heal_bulk_collect,
            # 2026-04-21 §23.5: kuaishou result=109 auto-refresh
            "REFRESH_KUAISHOU_COOKIE":
                self._heal_refresh_kuaishou_cookie,
        }
        fn = handlers.get(action)
        action_row_id = self._start_action(
            cycle_id=cycle_id, diag_id=diag_id, code=code,
            action=action, params=params, tasks=affected_tasks,
        )
        if not fn:
            self._finish_action(action_row_id, ok=False,
                                error=f"未实现的 remedy_action: {action}")
            return {"ok": False, "action": action, "error": "unknown"}
        try:
            res = fn(params, affected_tasks)
            self._finish_action(action_row_id, ok=True, result=res)
            return {"ok": True, "action": action, **res}
        except Exception as e:
            self._finish_action(action_row_id, ok=False, error=str(e))
            return {"ok": False, "action": action, "error": str(e)}

    # ------------------------------------------------------------------
    # 具体修复手术
    # ------------------------------------------------------------------

    def _heal_recollect_and_fallback(self, params: dict,
                                     tasks: list[dict]) -> dict:
        """m3u8 抓不到 → ①把相关 drama 标 deprecated, ②入队 COLLECT task 重采集."""
        affected_drama_names = list({t["drama_name"] for t in tasks if t.get("drama_name")})
        # 把这些 drama_links 标 deprecated
        deprecated = 0
        for name in affected_drama_names:
            try:
                cur = self.db.conn.execute(
                    """UPDATE drama_links SET status='deprecated'
                       WHERE drama_name=? AND status IN ('pending','downloading','failed')""",
                    (name,),
                )
                deprecated += cur.rowcount
            except Exception:
                continue
        self.db.conn.commit()

        # 入队 COLLECT 重采集
        author_limit = int(params.get("collect_new_authors", 3))
        enqueued = self._enqueue_bulk_collect(author_limit)

        return {
            "deprecated_dramas": deprecated,
            "affected_names_sample": affected_drama_names[:5],
            "collect_tasks_enqueued": enqueued,
            "fallback": params.get("fallback_downloader", ""),
        }

    def _heal_mark_relogin(self, params: dict, tasks: list[dict]) -> dict:
        """账号 cookie 失效 → 标 need_refresh."""
        account_ids = list({t["account_id"] for t in tasks if t.get("account_id")})
        status = params.get("signed_status", "need_refresh")
        updated = 0
        for acct in account_ids:
            try:
                cur = self.db.conn.execute(
                    """UPDATE device_accounts SET
                         signed_status=?,
                         lifecycle_stage='dormant',
                         signed_updated_at=datetime('now','localtime'),
                         signed_note='cookie 失效 - SelfHealingAgent 自动标记'
                       WHERE kuaishou_uid=?""",
                    (status, acct),
                )
                updated += cur.rowcount
            except Exception:
                continue
        self.db.conn.commit()
        return {"marked_accounts": updated, "account_ids": account_ids}

    def _heal_reenqueue_upstream(self, params: dict,
                                 tasks: list[dict]) -> dict:
        """PUBLISH_A 缺 video_path → 取消这 task + 找上游重跑."""
        cancelled = 0
        for t in tasks:
            tid = t["task_id"]
            try:
                cur = self.db.conn.execute(
                    """UPDATE task_queue SET
                         status='canceled',
                         error_message='SelfHealingAgent: upstream 参数缺失, 取消此孤儿 task'
                       WHERE id=? AND status IN ('failed','dead_letter')""",
                    (tid,),
                )
                cancelled += cur.rowcount
            except Exception:
                continue
        self.db.conn.commit()
        # 注: 真实重建 upstream 链路需要有 batch_id + 完整 drama_url, v1 只取消
        return {"cancelled_orphans": cancelled,
                "note": "v1 仅取消, 未自动重建 upstream (需要 batch_id 完整)"}

    def _heal_pause_account(self, params: dict, tasks: list[dict]) -> dict:
        """账号连续失败 → 暂停进入 cooldown."""
        account_ids = list({t["account_id"] for t in tasks if t.get("account_id")})
        hours = int(params.get("cooldown_hours", 6))
        paused = 0
        for acct in account_ids:
            try:
                cur = self.db.conn.execute(
                    """UPDATE device_accounts SET
                         lifecycle_stage='dormant',
                         signed_note=?
                       WHERE kuaishou_uid=?""",
                    (f"SelfHealingAgent: {hours}h cooldown (连续失败)", acct),
                )
                paused += cur.rowcount
            except Exception:
                continue
        self.db.conn.commit()
        return {"paused_accounts": paused, "cooldown_hours": hours}

    def _heal_bulk_collect(self, params: dict, tasks: list[dict]) -> dict:
        """批量采集."""
        enqueued = self._enqueue_bulk_collect(
            params.get("author_limit", 5),
        )
        return {"collect_tasks_enqueued": enqueued}

    def _heal_refresh_kuaishou_cookie(self, params: dict,
                                       tasks: list[dict]) -> dict:
        """KS184 result=109 → 对每个受影响账号 enqueue 一个 COOKIE_REFRESH task.

        对齐 CLAUDE.md §23.5 KS184 自愈行为:
          1. 从 tasks 里提取 account_id (去重)
          2. 为每个账号 enqueue 一条 COOKIE_REFRESH (priority=99 插队)
          3. 老 PUBLISH task 标 failed 让 scheduler 下一轮触发

        failed task 不动 (已是 failed), 只补 cookie refresh. planner/scheduler 会
        在冷静期后重新 pick up 该 drama×account.
        """
        account_ids = list({
            t.get("account_id") for t in tasks
            if t.get("account_id") not in (None, 0, "")
        })
        if not account_ids:
            return {"refreshed": 0, "reason": "no_account_ids_in_tasks"}

        timeout_sec = int(params.get("timeout_sec", 120))
        try:
            from core.task_manager import create_batch, add_task_to_batch
            from core.executor.account_executor import enqueue_publish_task
        except Exception as e:
            return {"refreshed": 0, "error": f"import failed: {e!r}"}

        batch_id = create_batch(
            batch_name="healing_auth_109_refresh",
            batch_type="maintenance",
            total_tasks=len(account_ids),
        )
        # ★ 2026-04-22 §27_I: 账号 cooldown — 近 10min 已 enqueue COOKIE_REFRESH 则跳过
        # 避免 acct 15 每分钟 2 次 enqueue 的污染
        enqueued = 0
        skipped = 0
        for i, acc_id in enumerate(account_ids):
            try:
                # 近 10min 是否已有该账号 COOKIE_REFRESH queued/running/success?
                recent = self.db.conn.execute(
                    """SELECT COUNT(*) FROM task_queue
                       WHERE account_id = ? AND task_type = 'COOKIE_REFRESH'
                         AND datetime(created_at) >= datetime('now','-10 minutes','localtime')""",
                    (str(acc_id),),
                ).fetchone()
                if recent and recent[0] > 0:
                    skipped += 1
                    continue

                # priority=99 与 burst 同级, 插队执行
                task_id = enqueue_publish_task(
                    account_id=int(acc_id),
                    drama_name="",
                    priority=99,
                    batch_id=batch_id,
                    task_type="COOKIE_REFRESH",
                    task_source="self_healing",
                    source_metadata={
                        "triggered_by": "kuaishou_auth_expired_109",
                        "timeout_sec": timeout_sec,
                    },
                )
                add_task_to_batch(batch_id, task_id, order=i)
                enqueued += 1
            except Exception:
                continue
        return {
            "refreshed": enqueued,
            "skipped_cooldown": skipped,
            "batch_id": batch_id,
            "affected_accounts": account_ids,
            "note": "priority=99 cookie refresh enqueued; publish will retry on next scheduler tick",
        }

    # ------------------------------------------------------------------

    def _enqueue_bulk_collect(self, author_limit: int) -> int:
        """从 drama_authors 里选 N 个高优先级作者, 入队 COLLECT task."""
        authors = self._safe(lambda: self.db.conn.execute(
            """SELECT kuaishou_uid, nickname FROM drama_authors
               WHERE is_active=1
               ORDER BY COALESCE(scrape_priority, 50) DESC,
                        COALESCE(last_success_at, created_at) ASC
               LIMIT ?""",
            (author_limit,),
        ).fetchall(), [])
        if not authors:
            return 0
        # 拿一个 logged-in 账号做 cookie 来源
        cookie_acct = self.db.conn.execute(
            """SELECT id FROM device_accounts
               WHERE login_status='logged_in' ORDER BY id LIMIT 1"""
        ).fetchone()
        account_pk = cookie_acct[0] if cookie_acct else 0

        from core.task_queue import Task
        enqueued = 0
        for uid, name in authors:
            task = Task(
                task_type="COLLECT",
                account_id=str(uid),
                drama_name=name or "",
                priority=40,
                params={"author_uid": uid, "account_pk": account_pk,
                        "max_pages": 2},
                created_by="SelfHealingAgent",
            )
            d = task.to_dict()
            cols = ", ".join(d.keys())
            placeholders = ", ".join("?" for _ in d)
            try:
                self.db.conn.execute(
                    f"INSERT INTO task_queue ({cols}) VALUES ({placeholders})",
                    list(d.values()),
                )
                enqueued += 1
            except Exception:
                continue
        self.db.conn.commit()
        return enqueued

    # ==================================================================
    # 表落地
    # ==================================================================

    def _record_diagnosis(self, *, cycle_id: str, code: str, task_type: str,
                          evidence: list, diagnosis: str,
                          confidence: float) -> int | None:
        """★ 2026-04-22 §27_I: 同 playbook_code + 同 affected accounts 近 30min 已诊断则跳过,
        避免 self_healing 对同一批 dead_letter task 反复触发 (历史一天 900+ 噪声)."""
        import logging as _log_mod
        _dedupe_log = _log_mod.getLogger("self_healing.dedupe")
        try:
            # sorted 需要元素类型一致 — 全部转 str 防 mixed int/str
            aff_accounts = sorted(
                str(x.get("account_id")) for x in evidence
                if x.get("account_id") is not None and x.get("account_id") != ''
            )
            # 再 dedupe (因 str 转换后可能有重复)
            aff_accounts = sorted(set(aff_accounts))
            aff_json = json.dumps(aff_accounts, ensure_ascii=False)
            # ★ 2026-04-23 Bug 7 修复: 去重窗口从 30min → config (默认 24h).
            # 老 30min 对 "账号不在 MCN 萤光" 这种长期状态不够 — 每 30min 重插 1 条,
            # 14 条同规则同账号堆积 (诗 14 条观察). 改为按规则查配置的 dedup 窗口.
            from core.app_config import get as _cfg_get
            dedupe_min = int(_cfg_get("ai.healing.dedupe_window_minutes", 1440))
            dup = self.db.conn.execute(
                f"""SELECT id FROM healing_diagnoses
                   WHERE playbook_code = ?
                     AND affected_entities = ?
                     AND (auto_resolved IS NULL OR auto_resolved = 0)
                     AND datetime(created_at) >= datetime('now','-{dedupe_min} minutes','localtime')
                   LIMIT 1""",
                (code, aff_json),
            ).fetchone()
            _dedupe_log.info(
                "[dedupe] code=%s aff=%s dup=%s", code, aff_json, dup,
            )
            if dup:
                return dup[0]  # 沿用老 diag id, 不建新
            cur = self.db.conn.execute(
                """INSERT INTO healing_diagnoses
                     (cycle_id, playbook_code, task_type, evidence_json,
                      affected_entities, diagnosis, confidence)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (cycle_id, code, task_type,
                 json.dumps(evidence, ensure_ascii=False, default=str)[:8000],
                 aff_json, diagnosis, float(confidence)),
            )
            self.db.conn.commit()
            return cur.lastrowid
        except Exception:
            return None

    def _start_action(self, *, cycle_id: str, diag_id: int | None, code: str,
                       action: str, params: dict, tasks: list[dict]) -> int | None:
        try:
            cur = self.db.conn.execute(
                """INSERT INTO healing_actions
                     (cycle_id, diagnosis_id, playbook_code, action,
                      params_json, target_type, target_ids, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (cycle_id, diag_id, code, action,
                 json.dumps(params, ensure_ascii=False),
                 "task",
                 json.dumps([t["task_id"] for t in tasks[:20]],
                            ensure_ascii=False)),
            )
            self.db.conn.commit()
            return cur.lastrowid
        except Exception:
            return None

    def _finish_action(self, action_id: int | None, *, ok: bool,
                        result: dict | None = None, error: str = "") -> None:
        if not action_id:
            return
        try:
            self.db.conn.execute(
                """UPDATE healing_actions SET
                     status=?, result_json=?, error_message=?,
                     completed_at=datetime('now','localtime')
                   WHERE id=?""",
                ("success" if ok else "failed",
                 json.dumps(result or {}, ensure_ascii=False, default=str)[:4000],
                 (error or "")[:500], action_id),
            )
            self.db.conn.commit()
        except Exception:
            pass
        # system_events 埋点 — 让 dashboard 实时看到自愈发生
        try:
            from core.event_bus import emit_event
            emit_event(
                "heal.applied" if ok else "heal.failed",
                entity_type="healing_action",
                entity_id=str(action_id),
                payload={"result": result or {}, "error": error},
                level="info" if ok else "warn",
                source_module="self_healing",
            )
        except Exception:
            pass

    def _update_playbook_stats(self, pb_id: int, ok: bool) -> None:
        try:
            col = "success_count" if ok else "fail_count"
            self.db.conn.execute(
                f"UPDATE healing_playbook SET {col}={col}+1,"
                "  updated_at=datetime('now','localtime') WHERE id=?",
                (pb_id,),
            )
            self.db.conn.commit()
        except Exception:
            pass

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default
