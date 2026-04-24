# -*- coding: utf-8 -*-
"""Analysis Agent — 规则先算 + LLM 质疑增强 (hybrid 模式).

流程:
  1. 规则部分 (原有逻辑): SQL 汇总 → findings + 初步 recommendations
  2. LLM 部分: 把事实传给 GPT-5.4, 生成增量归因假设 + 可测实验建议
  3. 合并: LLM 的 findings 加 tag 'llm' 区分, confidence 继承 LLM 输出

LLM 开关关闭时自动退化为纯规则.
"""
from __future__ import annotations

import json
from datetime import datetime

from core.agents.base import (
    BaseAgent, AgentResponse,
    RESPONSE_STATUS_OK, RESPONSE_STATUS_DEGRADED,
)
from core.data_insights import DataInsights
from core.llm.prompts import get_prompt


class AnalysisAgent(BaseAgent):
    name = "analysis"
    llm_mode = "hybrid"     # 默认 hybrid, 子类可改 "rules" / "ai"

    def __init__(self, db_manager):
        super().__init__(db_manager)
        self.di = DataInsights(db_manager)

    # ------------------------------------------------------------------

    def _compute(self, payload: dict) -> dict:
        findings: list = []
        recommendations: list = []
        degraded = False

        # ============================================================
        # RULE LAYER — 100% 确定性事实 (不要变)
        # ============================================================

        kw_heat = self._safe(lambda: self.di.keyword_heat_index(), [])
        if not kw_heat:
            findings.append({
                "type": "market_data_missing",
                "source": "rules",
                "message": "drama_hot_rankings 为空 — 先跑 refresh_hot_rankings",
                "confidence": 1.0,
            })
            degraded = True
        else:
            top, bottom = kw_heat[0], kw_heat[-1]
            findings.append({
                "type": "genre_performance", "source": "rules",
                "top_keyword": top["keyword"],
                "top_avg_score": top["avg_score"],
                "bottom_keyword": bottom["keyword"],
                "bottom_avg_score": bottom["avg_score"],
                "message": f"赛道 {top['keyword']} 最热 (avg={top['avg_score']:.2f}, "
                           f"total_views={top['total_views']}), "
                           f"{bottom['keyword']} 最冷 (avg={bottom['avg_score']:.2f})",
                "confidence": 0.85,
            })

        mx = self._safe(lambda: self.di.matrix_today_summary(),
                        {"accounts": 0, "by_account": []})
        if mx.get("accounts"):
            by = sorted(mx["by_account"], key=lambda a: -a.get("plays", 0))
            best = by[0] if by else None
            active = [a for a in by if a.get("plays", 0) > 0]
            idle = [a for a in by if a.get("plays", 0) == 0]
            if best:
                findings.append({
                    "type": "account_performance", "source": "rules",
                    "best_account": best["name"], "best_uid": best["uid"],
                    "best_plays": best["plays"],
                    "active_count": len(active), "idle_count": len(idle),
                    "total_plays": mx.get("total_plays", 0),
                    "message": f"今日最活跃: {best['name']} ({best['plays']} plays). "
                               f"活跃 {len(active)} / 闲置 {len(idle)}",
                    "confidence": 0.9,
                })
            if idle and len(idle) >= 3:
                recommendations.append({
                    "action": "reactivate_idle_accounts", "source": "rules",
                    "targets": [a["uid"] for a in idle[:5]],
                    "reason": f"{len(idle)} 个账号今日 0 播放",
                    "priority": "high",
                })

        pending = self._safe_scalar(
            "SELECT COUNT(*) FROM drama_links WHERE status='pending'", 0)
        completed = self._safe_scalar(
            "SELECT COUNT(*) FROM drama_links WHERE status IN ('completed','used')", 0)
        findings.append({
            "type": "drama_pool", "source": "rules",
            "pending": pending, "completed": completed,
            "message": f"drama_links: {pending} pending, {completed} used",
            "confidence": 1.0,
        })
        if pending < 10:
            recommendations.append({
                "action": "refill_drama_pool", "source": "rules",
                "reason": f"仅剩 {pending} pending, 低于健康线 10",
                "suggest": "scripts.collect_dramas --from-authors --author-limit 5",
                "priority": "normal",
            })

        total_accts = self._safe_scalar(
            "SELECT COUNT(*) FROM device_accounts WHERE login_status='logged_in'", 0)
        bound = self._safe_scalar(
            """SELECT COUNT(*) FROM mcn_account_bindings
               WHERE commission_rate IS NOT NULL AND commission_rate > 0""", 0)
        if total_accts:
            findings.append({
                "type": "mcn_coverage", "source": "rules",
                "total_logged_in": total_accts, "bound": bound,
                "coverage_ratio": round(bound / max(total_accts, 1), 3),
                "message": f"MCN 绑定覆盖: {bound}/{total_accts} "
                           f"({bound*100//max(total_accts,1)}%)",
                "confidence": 1.0,
            })

        weak = self._safe(lambda: self.db.conn.execute(
            """SELECT account_id, health_score FROM account_health_snapshots
               WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM account_health_snapshots)
               ORDER BY health_score ASC LIMIT 3"""
        ).fetchall(), [])
        if weak:
            findings.append({
                "type": "health_outliers", "source": "rules",
                "weakest": [{"uid": r[0], "health_score": r[1]} for r in weak],
                "message": "最弱 3 账号: "
                           + ", ".join(f"{r[0][:8]}…({r[1]:.0f})" for r in weak),
                "confidence": 0.95,
            })

        # ============================================================
        # LLM LAYER — 增量归因 + 趋势推理 (hybrid 模式才跑)
        # ============================================================

        prompt_version = ""
        if self.llm_mode in ("ai", "hybrid"):
            p = get_prompt("analysis")
            facts = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "keyword_heat_top5": kw_heat[:5],
                "keyword_heat_bottom3": kw_heat[-3:] if len(kw_heat) >= 3 else [],
                "matrix_today": {
                    "total_accounts": mx.get("accounts", 0),
                    "total_plays": mx.get("total_plays", 0),
                    "total_likes": mx.get("total_likes", 0),
                    "top_5_accounts": [
                        {"name": a["name"], "plays": a["plays"], "likes": a["likes"]}
                        for a in mx.get("by_account", [])[:5]
                    ],
                    "idle_account_count": len([
                        a for a in mx.get("by_account", [])
                        if a.get("plays", 0) == 0
                    ]),
                },
                "drama_pool": {"pending": pending, "used": completed},
                "mcn_coverage": {"total": total_accts, "bound_with_rate": bound},
                "weakest_accounts": [{"uid": r[0], "health_score": r[1]} for r in weak],
            }
            llm_output = self.llm_enrich(
                system_prompt=p["system"],
                user_prompt=p["user_template"].format(
                    facts_json=json.dumps(facts, ensure_ascii=False, indent=2)
                ),
                purpose="analysis_enrichment",
                as_json=True,
            )
            prompt_version = p["version"]
            if llm_output:
                for f in llm_output.get("findings", []) or []:
                    f["source"] = "llm"
                    findings.append(f)
                for r in llm_output.get("recommendations", []) or []:
                    r["source"] = "llm"
                    recommendations.append(r)
                # LLM 总结作为独立 finding
                if llm_output.get("summary"):
                    findings.append({
                        "type": "llm_summary", "source": "llm",
                        "message": llm_output["summary"],
                        "confidence": llm_output.get("confidence", 0.75),
                    })
            elif self.llm_mode == "ai":
                # ai 模式下 LLM 失败 = degraded
                degraded = True

        # ============================================================
        # 汇总
        # ============================================================

        status = RESPONSE_STATUS_DEGRADED if degraded else RESPONSE_STATUS_OK
        confidence = 0.6 if degraded else 0.85

        meta = {
            "source_count": len(findings),
            "prompt_version": prompt_version,
            "rule_findings_count": len([f for f in findings if f.get("source") == "rules"]),
            "llm_findings_count": len([f for f in findings if f.get("source") == "llm"]),
        }

        return AgentResponse.make(
            self.name, run_id="",
            status=status, confidence=confidence,
            findings=findings, recommendations=recommendations,
            meta=meta,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _safe(self, fn, default):
        try:
            return fn()
        except Exception:
            return default

    def _safe_scalar(self, sql: str, default=0):
        try:
            r = self.db.conn.execute(sql).fetchone()
            return r[0] if r else default
        except Exception:
            return default
