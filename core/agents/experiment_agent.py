# -*- coding: utf-8 -*-
"""Experiment Agent — hybrid 模式:
  1. 规则: 列出当前活跃实验 + 账号池容量
  2. LLM: 基于数据现状生成 0-3 个建议启动的 A/B 实验
  3. 默认兜底: LLM 不给建议时, 用 DEFAULT_EXPERIMENTS 填充

生成的实验**不**自动启动 (status='draft'), Orchestrator 或人工确认后再走 start.
"""
from __future__ import annotations

import json

from core.agents.base import BaseAgent, AgentResponse, RESPONSE_STATUS_OK
from core.llm.prompts import get_prompt


# 兜底实验库 (当 LLM 不可用时用)
DEFAULT_EXPERIMENTS = [
    {
        "code": "exp_genre_comparison_v1",
        "name": "赛道对比: 末世 vs 穿越",
        "hypothesis": "末世类 avg_score 领先穿越 38%, 若控制其他条件后仍如此则应放量末世",
        "variable_name": "drama_genre",
        "groups": ["末世", "穿越"],
        "sample_target": 12,
        "duration_days": 3,
        "success_metric": "views_24h",
        "success_threshold": 5000,
    },
    {
        "code": "exp_publish_time_v1",
        "name": "发布时段 A/B: 下午 vs 晚间",
        "hypothesis": "矩阵账号晚间发布 CTR 是否比下午更高",
        "variable_name": "publish_window",
        "groups": ["14:00-16:00", "19:00-21:00"],
        "sample_target": 8,
        "duration_days": 3,
        "success_metric": "views_24h",
        "success_threshold": 5000,
    },
    {
        "code": "exp_multi_segment_v1",
        "name": "分段发布 vs 单集发布",
        "hypothesis": "同一剧切多段引流是否优于单段",
        "variable_name": "multi_segment",
        "groups": ["single", "multi"],
        "sample_target": 10,
        "duration_days": 5,
        "success_metric": "views_24h",
        "success_threshold": 8000,
    },
]


class ExperimentAgent(BaseAgent):
    name = "experiment"
    llm_mode = "hybrid"

    # ------------------------------------------------------------------

    def _compute(self, payload: dict) -> dict:
        findings: list = []
        recommendations: list = []

        # 1. 规则事实
        active_count = self._scalar(
            """SELECT COUNT(*) FROM strategy_experiments
               WHERE status IN ('draft','running')""", 0)
        findings.append({
            "type": "experiment_inventory", "source": "rules",
            "active_count": active_count,
            "message": f"当前 draft+running 实验: {active_count}",
            "confidence": 1.0,
        })

        testing_accts = self._scalar(
            "SELECT COUNT(*) FROM device_accounts WHERE login_status='logged_in'", 0)
        findings.append({
            "type": "available_sample", "source": "rules",
            "logged_in_accounts": testing_accts,
            "message": f"可用测试账号: {testing_accts}",
            "confidence": 1.0,
        })

        # 已有实验名 — 供 LLM 去重
        running_names = [
            r[0] for r in self._safe(lambda: self.db.conn.execute(
                """SELECT experiment_code FROM strategy_experiments
                   WHERE status IN ('draft','running')"""
            ).fetchall(), [])
        ]

        # 2. LLM 层: 生成新实验建议
        prompt_version = ""
        llm_recommendations: list = []
        if self.llm_mode in ("ai", "hybrid") and active_count < 3 and testing_accts >= 4:
            p = get_prompt("experiment")
            context = self._gather_experiment_context()
            llm_output = self.llm_enrich(
                system_prompt=p["system"],
                user_prompt=p["user_template"].format(
                    context_json=json.dumps(context, ensure_ascii=False, indent=2),
                    running_experiments=json.dumps(running_names, ensure_ascii=False),
                ),
                purpose="experiment_design",
                as_json=True,
            )
            prompt_version = p["version"]
            if llm_output:
                for exp in llm_output.get("experiments", []) or []:
                    exp_code = exp.get("code") or exp.get("experiment_code")
                    if not exp_code or exp_code in running_names:
                        continue
                    llm_recommendations.append({
                        "action": "create_experiment", "source": "llm",
                        "experiment_code": exp_code,
                        "experiment_name": exp.get("name", exp_code),
                        "hypothesis": exp.get("hypothesis", ""),
                        "variable_name": exp.get("variable_name", ""),
                        "groups": [exp.get("control_group", ""), exp.get("test_group", "")],
                        "sample_target": int(exp.get("sample_target") or 10),
                        "duration_days": 3,
                        "success_metric": exp.get("success_metric", "total_plays"),
                        "success_threshold": float(exp.get("success_threshold", 1.2)),
                        "priority": exp.get("priority", "normal"),
                        "reason": exp.get("reason", ""),
                    })
                recommendations.extend(llm_recommendations)

        # 3. 兜底: LLM 没给 → 用默认库
        if not llm_recommendations and active_count < 3 and testing_accts >= 4:
            for defn in DEFAULT_EXPERIMENTS:
                if defn["code"] in running_names:
                    continue
                if len(recommendations) >= 3 - active_count:
                    break
                recommendations.append({
                    "action": "create_experiment", "source": "default",
                    "experiment_code": defn["code"],
                    "experiment_name": defn["name"],
                    "hypothesis": defn["hypothesis"],
                    "variable_name": defn["variable_name"],
                    "groups": defn["groups"],
                    "sample_target": defn["sample_target"],
                    "duration_days": defn["duration_days"],
                    "success_metric": defn["success_metric"],
                    "success_threshold": defn["success_threshold"],
                    "priority": "normal",
                })

        if testing_accts < 4:
            findings.append({
                "type": "sample_shortage", "source": "rules",
                "message": f"账号池太小 ({testing_accts}), 先恢复 idle 账号",
                "confidence": 0.9,
            })

        return AgentResponse.make(
            self.name, run_id="",
            status=RESPONSE_STATUS_OK,
            confidence=0.80 if llm_recommendations else 0.70,
            findings=findings, recommendations=recommendations,
            meta={
                "prompt_version": prompt_version,
                "llm_generated_count": len(llm_recommendations),
                "default_battery_size": len(DEFAULT_EXPERIMENTS),
            },
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _scalar(self, sql: str, default=0):
        try:
            r = self.db.conn.execute(sql).fetchone()
            return r[0] if r else default
        except Exception:
            return default

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default

    def _gather_experiment_context(self) -> dict:
        """给 LLM 喂足够的运营快照."""
        # 最热关键词 Top 5
        kw_top5 = self._safe(lambda: self.db.conn.execute(
            """SELECT keyword, AVG(hot_score) AS s, SUM(view_count) AS v
               FROM drama_hot_rankings
               WHERE platform='kuaishou_search'
                 AND snapshot_date=(SELECT MAX(snapshot_date) FROM drama_hot_rankings)
               GROUP BY keyword ORDER BY s DESC LIMIT 5"""
        ).fetchall(), [])
        # 今日发布分布
        today_pub = self._safe(lambda: self.db.conn.execute(
            """SELECT kuaishou_uid, COUNT(*) FROM account_drama_execution_logs
               WHERE DATE(created_at)=DATE('now','localtime') AND status='success'
               GROUP BY kuaishou_uid"""
        ).fetchall(), [])
        return {
            "hot_keywords_top5": [
                {"keyword": r[0], "avg_score": round(r[1] or 0, 3),
                 "total_views": r[2] or 0}
                for r in kw_top5
            ],
            "today_publishes_per_account": [
                {"uid": r[0], "count": r[1]} for r in today_pub
            ],
            "total_today_publishes": sum(r[1] for r in today_pub),
        }

    # ------------------------------------------------------------------
    # Approve-to-DB 辅助 (供 Orchestrator 调用)
    # ------------------------------------------------------------------

    def create_from_recommendation(self, rec: dict,
                                   *, created_by: str = "experiment_agent") -> int | None:
        code = rec.get("experiment_code")
        if not code:
            return None
        groups = rec.get("groups") or []
        control = groups[0] if groups else ""
        test = "|".join(groups[1:]) if len(groups) > 1 else ""
        try:
            self.db.conn.execute(
                """INSERT INTO strategy_experiments
                     (experiment_code, experiment_name, hypothesis, variable_name,
                      control_group, test_group, sample_target, success_metric,
                      success_threshold, status, created_by_agent)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'draft', ?)
                   ON CONFLICT(experiment_code) DO NOTHING""",
                (code, rec.get("experiment_name", code),
                 rec.get("hypothesis", ""), rec.get("variable_name", ""),
                 control, test,
                 int(rec.get("sample_target", 0)),
                 rec.get("success_metric", ""),
                 float(rec.get("success_threshold", 0)),
                 created_by),
            )
            self.db.conn.commit()
            row = self.db.conn.execute(
                "SELECT id FROM strategy_experiments WHERE experiment_code = ?",
                (code,),
            ).fetchone()
            return row[0] if row else None
        except Exception:
            return None
