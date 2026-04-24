# -*- coding: utf-8 -*-
"""Scale Agent — hybrid 模式:
  1. 规则: 列出候选 winner (已完成实验 + 高置信记忆 + 高播放量剧)
  2. LLM: 判断 winner 是"真信号"还是"偶然", 并给出具体扩量方案
     (到哪些账号 / 多少个 / 观察多久 / 止损条件)
  3. 开关 auto_scale_enabled=OFF 时, 所有建议自动标 pending_human
"""
from __future__ import annotations

import json

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.llm.prompts import get_prompt
from core.switches import is_enabled


class ScaleAgent(BaseAgent):
    name = "scale"
    llm_mode = "hybrid"

    def _compute(self, payload: dict) -> dict:
        findings: list = []
        recommendations: list = []

        auto_scale_on = is_enabled("auto_scale_enabled")
        min_plays = int(payload.get("min_plays", 10000))
        max_variants = int(payload.get("max_variants", 3))

        # ============================================================
        # RULE LAYER — 候选 winner 清单
        # ============================================================

        # 1. 已完成实验
        finished_exp = self._safe(lambda: self.db.conn.execute(
            """SELECT experiment_code, experiment_name, variable_name,
                      control_group, test_group, sample_current, success_metric
               FROM strategy_experiments
               WHERE status = 'completed'
                 AND sample_current >= sample_target
               ORDER BY id DESC LIMIT 5"""
        ).fetchall(), [])
        findings.append({
            "type": "completed_experiments", "source": "rules",
            "count": len(finished_exp),
            "message": f"已完成并达样本的实验: {len(finished_exp)}",
            "confidence": 1.0,
        })

        # 2. 高置信策略记忆
        memories = self._safe(lambda: self.db.conn.execute(
            """SELECT id, memory_type, drama_genre, strategy_name,
                      publish_window, title, recommendation,
                      confidence_score, impact_score, hit_count
               FROM strategy_memories
               WHERE confidence_score >= 0.7
                 AND (valid_to IS NULL OR valid_to > datetime('now'))
               ORDER BY confidence_score DESC, impact_score DESC LIMIT 10"""
        ).fetchall(), [])
        findings.append({
            "type": "validated_patterns", "source": "rules",
            "count": len(memories),
            "message": f"高置信策略记忆: {len(memories)}",
            "confidence": 1.0,
        })

        # 3. 高播放量作品 (从 work_metrics / daily_account_metrics 推导)
        top_works = self._safe(lambda: self.db.conn.execute(
            """SELECT photo_id, account_id, account_name, drama_name,
                      play_count, like_count, comment_count, created_at
               FROM work_metrics
               WHERE play_count >= ?
                 AND DATE(created_at) >= DATE('now','-3 days')
               ORDER BY play_count DESC LIMIT 10""",
            (min_plays,),
        ).fetchall(), [])
        findings.append({
            "type": "winner_candidates", "source": "rules",
            "count": len(top_works),
            "threshold": min_plays,
            "message": f"近 3 天播放≥{min_plays} 的作品: {len(top_works)}",
            "confidence": 1.0,
        })

        # 可用放量账号池
        available_accounts = self._safe(lambda: self.db.conn.execute(
            """SELECT da.id, da.account_name, da.kuaishou_uid,
                      (SELECT health_score FROM account_health_snapshots
                       WHERE account_id=da.kuaishou_uid
                       ORDER BY snapshot_date DESC LIMIT 1) AS health
               FROM device_accounts da
               WHERE da.login_status='logged_in'
               ORDER BY health DESC NULLS LAST LIMIT 15"""
        ).fetchall(), [])

        # 规则层建议 (保留, 给 LLM 参考)
        rule_recs: list = []
        for m in memories[:3]:
            rule_recs.append({
                "action": "scale_pattern", "source": "rules",
                "memory_id": m[0], "memory_type": m[1],
                "drama_genre": m[2], "strategy_name": m[3],
                "publish_window": m[4], "title": m[5],
                "content": m[6], "confidence": m[7],
                "recommended_account_count": 5,
                "reason": f"记忆 confidence {m[7]:.2f} >= 0.7",
                "hitl_status": "pending" if not auto_scale_on else "",
            })

        # ============================================================
        # LLM LAYER — 审核 winner + 给具体放量方案
        # ============================================================

        prompt_version = ""
        llm_recommendations: list = []
        if self.llm_mode in ("ai", "hybrid") and (top_works or memories):
            p = get_prompt("scale")
            winners_payload = [
                {
                    "id": f"work_{w[0]}",
                    "type": "work",
                    "drama_name": w[3],
                    "account_name": w[2],
                    "play_count": w[4],
                    "like_count": w[5],
                    "comment_count": w[6],
                    "created_at": w[7],
                } for w in top_works[:5]
            ] + [
                {
                    "id": f"memory_{m[0]}",
                    "type": "memory",
                    "title": m[5],
                    "drama_genre": m[2],
                    "strategy_name": m[3],
                    "confidence": m[7],
                    "impact": m[8],
                    "hit_count": m[9],
                } for m in memories[:5]
            ]
            account_pool = [
                {"id": a[0], "name": a[1], "uid": a[2],
                 "health": a[3] or 0}
                for a in available_accounts
            ]
            llm_output = self.llm_enrich(
                system_prompt=p["system"],
                user_prompt=p["user_template"].format(
                    winners_json=json.dumps(winners_payload, ensure_ascii=False, indent=2),
                    account_pool_json=json.dumps(account_pool, ensure_ascii=False, indent=2),
                ),
                purpose="scale_validation",
                as_json=True,
            )
            prompt_version = p["version"]
            if llm_output:
                for sr in llm_output.get("scale_recommendations", []) or []:
                    if not sr.get("is_real_signal"):
                        continue     # LLM 判偶然, 跳过
                    llm_recommendations.append({
                        "action": sr.get("scale_action", "replicate_drama"),
                        "source": "llm",
                        "winner_id": sr.get("winner_id"),
                        "winner_type": sr.get("winner_type"),
                        "confidence": sr.get("confidence", 0.75),
                        "reason": sr.get("reason", ""),
                        "target_accounts": sr.get("target_accounts", []),
                        "max_spawns": min(int(sr.get("max_spawns", 3) or 3), max_variants),
                        "monitor_hours": sr.get("monitor_hours", 48),
                        "stop_if": sr.get("stop_if", ""),
                        "hitl_status": "pending" if not auto_scale_on else "",
                        "priority": "high" if sr.get("confidence", 0) >= 0.8 else "normal",
                    })
                # 被 LLM 判偶然的也记录下, 方便审查
                for s in llm_output.get("skipped", []) or []:
                    findings.append({
                        "type": "llm_rejected_winner", "source": "llm",
                        "rejected_id": s.get("id"),
                        "message": f"LLM 判偶然: {s.get('reason', '')}",
                        "confidence": 0.75,
                    })

        # ============================================================
        # 合并
        # ============================================================

        # LLM 有建议就用 LLM, 否则用规则
        if llm_recommendations:
            recommendations.extend(llm_recommendations)
        else:
            recommendations.extend(rule_recs)

        # 无任何可放量内容
        if not memories and not top_works and not finished_exp:
            findings.append({
                "type": "bootstrap_scale", "source": "rules",
                "message": "无验证模式可放量; 建议先跑实验产生数据",
                "confidence": 0.5,
            })
            recommendations.append({
                "action": "bootstrap", "source": "rules",
                "reason": "无记忆 / 无完成实验 / 无高播放作品",
                "priority": "low",
            })

        # 全局开关警告
        if not auto_scale_on and recommendations:
            findings.append({
                "type": "auto_scale_gate", "source": "rules",
                "message": "auto_scale_enabled=OFF, 所有建议标记 pending_human",
                "confidence": 1.0,
            })

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.80 if llm_recommendations else 0.65,
            findings=findings, recommendations=recommendations,
            meta={
                "prompt_version": prompt_version,
                "llm_scale_count": len(llm_recommendations),
                "rule_scale_count": len(rule_recs),
                "auto_scale_on": auto_scale_on,
                "min_plays_threshold": min_plays,
            },
        )

    # ------------------------------------------------------------------

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default
