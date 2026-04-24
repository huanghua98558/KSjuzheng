# -*- coding: utf-8 -*-
"""ThresholdAgent — 规则阈值自学习 Agent.

触发方式:
  - Cron: 每周一 02:00 自动跑
  - 手动: /api/rules/analyze 触发
  - 条件触发: publish_results 攒够 200 条后第一次触发

核心逻辑:
  1. 读 publish_results + daily_account_metrics 最近 N 周
  2. 对每条 seed 规则计算"最优值的证据":
     - daily_publish_limit:    按 level 分组看实际发布量分布 + 成功率
     - publish_window_*:       按小时分桶看成功率
     - circuit_breaker_threshold: 看连续失败后账号恢复耗时
     - quota_by_level:         按 level × 成功率倒推合理配额
  3. 生成 rule_proposals (status=pending + confidence + evidence_json)
  4. 高置信 (>=0.85) + auto_apply_enabled 开关开 → 自动落地
  5. 其他等待人工 approve

"演化" 而不是"硬换":
  - seed_value 永不变
  - 每次新值都落 rule_evolution_history
  - 随时能回退到 seed_value (/rules/reset-to-seed)
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from typing import Any

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.config_center import cfg


MIN_SAMPLE_SIZE = 30   # 至少 30 条 publish_results 才开始给建议
CONFIDENCE_AUTO_APPLY = 0.85   # 置信度 >= 此值 + switch 开 → 自动生效


class ThresholdAgent(BaseAgent):
    """种子规则的演化 Agent — 读实际数据, 给规则调整建议."""

    name = "threshold"
    llm_mode = "hybrid"   # 规则层算数据, LLM 层做解释/判定

    # ------------------------------------------------------------------

    def _compute(self, payload: dict) -> dict:
        findings: list = []
        proposals: list = []
        min_samples = int(payload.get("min_samples", MIN_SAMPLE_SIZE))
        weeks = int(payload.get("weeks", 4))

        # 1. 统计准备
        sample_size = self._scalar(
            "SELECT COUNT(*) FROM publish_results", 0,
        )
        findings.append({
            "type": "sample_inventory", "source": "rules",
            "publish_results_total": sample_size,
            "message": f"publish_results 样本总数: {sample_size}",
            "confidence": 1.0,
        })

        if sample_size < min_samples:
            findings.append({
                "type": "insufficient_samples", "source": "rules",
                "message": (
                    f"样本数 {sample_size} < 阈值 {min_samples}, "
                    "ThresholdAgent 暂不出具调整建议, 等数据攒够再跑"
                ),
                "confidence": 1.0,
            })
            return AgentResponse.make(
                self.name, run_id="",
                status=RESPONSE_STATUS_OK,
                confidence=0.5,
                findings=findings, recommendations=[],
                meta={"phase": "warmup", "sample_size": sample_size,
                      "needed": min_samples},
            )

        # 2. 分析各规则
        self._analyze_daily_limit(findings, proposals, weeks)
        self._analyze_publish_window(findings, proposals, weeks)
        self._analyze_circuit_breaker(findings, proposals, weeks)
        self._analyze_quota_by_level(findings, proposals, weeks)

        # 3. 落 rule_proposals 表
        saved = 0
        for p in proposals:
            pid = self._save_proposal(p)
            if pid:
                saved += 1

        findings.append({
            "type": "proposals_saved", "source": "rules",
            "count": saved,
            "message": f"提议 {saved} 条规则调整, 待人工 approve 或 auto_apply",
            "confidence": 1.0,
        })

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.8,
            findings=findings,
            recommendations=[{
                "action": "review_proposals",
                "source": "threshold",
                "count": saved,
                "reason": f"基于近 {weeks} 周 {sample_size} 条 publish_results 分析",
            }] if saved else [],
            meta={"proposals": proposals, "sample_size": sample_size},
        )

    # ==================================================================
    # 分析器
    # ==================================================================

    def _analyze_daily_limit(self, findings: list, proposals: list, weeks: int) -> None:
        """按 account_level 看实际日发布量分布."""
        rows = self._safe(lambda: self.db.conn.execute(
            """SELECT da.account_level, DATE(pr.created_at) d,
                      pr.account_id, COUNT(*) c
               FROM publish_results pr
               JOIN device_accounts da ON da.kuaishou_uid = pr.account_id
               WHERE pr.publish_status = 'success'
                 AND DATE(pr.created_at) >= DATE('now', ?)
               GROUP BY da.account_level, DATE(pr.created_at), pr.account_id""",
            (f"-{weeks*7} days",),
        ).fetchall(), [])
        if not rows:
            return
        # 按 level 聚合 p90 / 平均
        from collections import defaultdict
        buckets: dict[str, list[int]] = defaultdict(list)
        for r in rows:
            buckets[r[0] or "V1_new"].append(r[3])
        import statistics
        for level, counts in buckets.items():
            if len(counts) < 5:
                continue
            p90 = sorted(counts)[int(len(counts) * 0.9)]
            avg = statistics.mean(counts)
            cur_quota_map = cfg.get("rule", "quota_by_level", {}) or {}
            current = cur_quota_map.get(level, 5) if isinstance(cur_quota_map, dict) else 5
            # 建议 = max(ceil(p90 * 1.2), current)  留 20% buffer
            proposed = max(int(p90 * 1.2 + 0.999), int(current))
            if proposed != current:
                confidence = min(0.6 + (len(counts) / 100) * 0.3, 0.9)
                findings.append({
                    "type": f"quota_analysis_{level}", "source": "rules",
                    "level": level, "samples": len(counts),
                    "avg_daily": round(avg, 1), "p90": p90,
                    "current_quota": current, "proposed": proposed,
                    "message": f"[{level}] 实际 p90={p90}, avg={avg:.1f}, "
                               f"建议配额: {current} → {proposed}",
                    "confidence": confidence,
                })
                # quota_by_level 是 dict, 这里暂不自动提议 (太复杂),
                # 只给出单独的 observed_daily_max_<level> 参考
                # (真要 apply, 用户手工在 Config 中心改)

    def _analyze_publish_window(self, findings: list, proposals: list,
                                weeks: int) -> None:
        """各小时分桶成功率."""
        rows = self._safe(lambda: self.db.conn.execute(
            """SELECT CAST(strftime('%H', created_at) AS INT) h,
                      SUM(CASE WHEN publish_status='success' THEN 1 ELSE 0 END) ok,
                      COUNT(*) tot
               FROM publish_results
               WHERE DATE(created_at) >= DATE('now', ?)
               GROUP BY h""",
            (f"-{weeks*7} days",),
        ).fetchall(), [])
        if not rows:
            return
        hours_data = [(r[0], r[1], r[2], r[1] / r[2] if r[2] else 0) for r in rows]
        # 找一个合理的窗口 (成功率 >= 0.7 的最长连续段)
        high_hours = [h for h, ok, tot, rate in hours_data if rate >= 0.7 and tot >= 3]
        if len(high_hours) < 4:
            return
        new_start = min(high_hours)
        new_end = max(high_hours) + 1
        cur_start = int(cfg.get("rule", "publish_window_start", 6))
        cur_end = int(cfg.get("rule", "publish_window_end", 23))
        findings.append({
            "type": "publish_window_observed", "source": "rules",
            "high_rate_hours": high_hours,
            "observed_window": f"{new_start:02d}:00-{new_end:02d}:00",
            "current_window":  f"{cur_start:02d}:00-{cur_end:02d}:00",
            "message": f"历史成功率 ≥70% 的小时段: {new_start}-{new_end}, "
                       f"当前配置 {cur_start}-{cur_end}",
            "confidence": 0.7,
        })
        if new_start != cur_start:
            proposals.append({
                "category": "rule",
                "config_key": "publish_window_start",
                "current_value": str(cur_start),
                "proposed_value": str(new_start),
                "proposer": "ThresholdAgent",
                "reason": f"历史成功率高的时段起点是 {new_start}:00, 当前起点 {cur_start}:00",
                "evidence_json": {"hours_data": hours_data,
                                  "high_hours": high_hours},
                "confidence": 0.7,
            })
        if new_end != cur_end:
            proposals.append({
                "category": "rule",
                "config_key": "publish_window_end",
                "current_value": str(cur_end),
                "proposed_value": str(new_end),
                "proposer": "ThresholdAgent",
                "reason": f"成功率高时段结束点是 {new_end}:00",
                "evidence_json": {"hours_data": hours_data},
                "confidence": 0.7,
            })

    def _analyze_circuit_breaker(self, findings: list, proposals: list,
                                 weeks: int) -> None:
        """连续失败到熔断的最优阈值分析."""
        # 如果熔断误伤很多 (熔断后账号健康度快速恢复) → 阈值调高
        # 如果熔断太晚 (失败累计到 5+ 才熔断) → 阈值调低
        # 这里用简化: 看 publish_results 里账号连续失败长度分布
        rows = self._safe(lambda: self.db.conn.execute(
            """SELECT account_id, publish_status
               FROM publish_results
               WHERE DATE(created_at) >= DATE('now', ?)
               ORDER BY account_id, id""",
            (f"-{weeks*7} days",),
        ).fetchall(), [])
        if not rows:
            return
        # 计算每个账号最长连续失败
        from collections import defaultdict
        streaks: dict[str, int] = defaultdict(int)
        current: dict[str, int] = defaultdict(int)
        for acc, status in rows:
            if status == "failed":
                current[acc] += 1
                if current[acc] > streaks[acc]:
                    streaks[acc] = current[acc]
            else:
                current[acc] = 0
        if not streaks:
            return
        max_streaks = list(streaks.values())
        max_streaks.sort()
        p75 = max_streaks[int(len(max_streaks) * 0.75)]
        findings.append({
            "type": "consecutive_fail_p75", "source": "rules",
            "max_streaks_sample": max_streaks[:10],
            "p75": p75,
            "message": f"账号最长连续失败 p75 = {p75}",
            "confidence": 0.6,
        })
        cur = int(cfg.get("rule", "circuit_breaker_threshold", 3))
        # 只在 p75 显著偏离时提议
        if abs(p75 - cur) >= 2 and len(max_streaks) >= 10:
            proposals.append({
                "category": "rule",
                "config_key": "circuit_breaker_threshold",
                "current_value": str(cur),
                "proposed_value": str(max(2, p75)),
                "proposer": "ThresholdAgent",
                "reason": f"账号连续失败 p75={p75}, 当前阈值 {cur} "
                          f"{'太低' if p75 > cur else '可以放宽'}",
                "evidence_json": {"streaks": max_streaks,
                                  "sample_accounts": len(streaks)},
                "confidence": 0.7,
            })

    def _analyze_quota_by_level(self, findings: list, proposals: list,
                                weeks: int) -> None:
        """调整 quota_by_level JSON (谨慎)."""
        # v1 暂不自动提议 quota_by_level, 因为它是 dict, 调整复杂
        # 仅在 findings 里给观察性指标供参考 (已在 _analyze_daily_limit 里做了)
        pass

    # ==================================================================
    # 提议落表
    # ==================================================================

    def _save_proposal(self, p: dict) -> int | None:
        try:
            cur = self.db.conn.execute(
                """INSERT INTO rule_proposals
                     (category, config_key, current_value, proposed_value,
                      proposer, reason, evidence_json, confidence, status)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                (p["category"], p["config_key"],
                 p["current_value"], p["proposed_value"],
                 p["proposer"], p["reason"],
                 json.dumps(p.get("evidence_json", {}), ensure_ascii=False, default=str)[:8000],
                 float(p.get("confidence", 0.5))),
            )
            self.db.conn.commit()
            return cur.lastrowid
        except Exception:
            return None

    # ==================================================================

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default

    def _scalar(self, sql: str, default=0):
        try:
            r = self.db.conn.execute(sql).fetchone()
            return r[0] if r else default
        except Exception:
            return default


# ---------------------------------------------------------------------------
# 工具: 把 pending proposal 应用到 system_config (保留演化历史)
# ---------------------------------------------------------------------------

def apply_proposal(db_manager, proposal_id: int, *, approver: str = "dashboard",
                   note: str = "") -> dict:
    """把 pending proposal 落地到 system_config, 记录 evolution_history."""
    row = db_manager.conn.execute(
        """SELECT category, config_key, current_value, proposed_value,
                  proposer, reason, evidence_json, confidence
           FROM rule_proposals WHERE id=? AND status='pending'""",
        (proposal_id,),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "proposal 不存在或已处理"}
    (category, key, cur_val, new_val, proposer, reason,
     evidence_json, confidence) = row

    # 更新 system_config
    cur_row = db_manager.conn.execute(
        """SELECT id, value_type, is_readonly, seed_value
           FROM system_config WHERE category=? AND config_key=?""",
        (category, key),
    ).fetchone()
    if not cur_row:
        return {"ok": False, "error": "target 规则不存在"}
    if cur_row[2]:
        return {"ok": False, "error": "目标规则只读"}

    db_manager.conn.execute(
        """UPDATE system_config SET
             config_value=?, last_evolved_at=datetime('now','localtime'),
             evolution_count=evolution_count+1,
             updated_by=?
           WHERE id=?""",
        (new_val, approver, cur_row[0]),
    )
    # 历史
    db_manager.conn.execute(
        """INSERT INTO rule_evolution_history
             (category, config_key, old_value, new_value, changed_by,
              source, reason, evidence_json, confidence, proposal_id)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (category, key, cur_val, new_val, "human_approved",
         proposer, reason, evidence_json, confidence, proposal_id),
    )
    # 更新 proposal 状态
    db_manager.conn.execute(
        """UPDATE rule_proposals SET
             status='approved', decided_by=?, decided_at=datetime('now','localtime'),
             decision_note=?
           WHERE id=?""",
        (approver, note, proposal_id),
    )
    db_manager.conn.commit()
    return {"ok": True, "category": category, "key": key,
            "old": cur_val, "new": new_val}


def reject_proposal(db_manager, proposal_id: int, *,
                    rejector: str = "dashboard", note: str = "") -> dict:
    cur = db_manager.conn.execute(
        """UPDATE rule_proposals SET
             status='rejected', decided_by=?, decided_at=datetime('now','localtime'),
             decision_note=?
           WHERE id=? AND status='pending'""",
        (rejector, note, proposal_id),
    )
    db_manager.conn.commit()
    return {"ok": cur.rowcount > 0}


def reset_to_seed(db_manager, category: str, config_key: str,
                  *, operator: str = "dashboard") -> dict:
    """把某规则重置为 seed_value."""
    row = db_manager.conn.execute(
        """SELECT id, config_value, seed_value FROM system_config
           WHERE category=? AND config_key=? AND is_seed=1""",
        (category, config_key),
    ).fetchone()
    if not row:
        return {"ok": False, "error": "非种子规则或不存在"}
    rid, cur_val, seed_val = row
    if cur_val == seed_val:
        return {"ok": True, "unchanged": True, "value": seed_val}
    db_manager.conn.execute(
        """UPDATE system_config SET
             config_value=?, last_evolved_at=datetime('now','localtime'),
             evolution_count=evolution_count+1, updated_by=?
           WHERE id=?""",
        (seed_val, operator, rid),
    )
    db_manager.conn.execute(
        """INSERT INTO rule_evolution_history
             (category, config_key, old_value, new_value, changed_by,
              source, reason, confidence)
           VALUES (?, ?, ?, ?, 'human', 'reset_to_seed',
                   '回退到种子值', 1.0)""",
        (category, config_key, cur_val, seed_val),
    )
    db_manager.conn.commit()
    return {"ok": True, "old": cur_val, "new": seed_val}
