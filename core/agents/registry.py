# -*- coding: utf-8 -*-
"""Agent 注册表 — 统一对外暴露所有 Agent 类 + 元数据.

供控制台使用:
  - list_agents()       列出所有 Agent 的元信息 (给 UI 展示下拉选择)
  - get_agent_class(name)    拿到类, 供 debug.py 动态实例化
  - trigger_agent(name, payload, db)    手动触发 + 返回响应

Agent 注册是显式的 — 避免 import 时副作用, 便于测试.
"""
from __future__ import annotations

from typing import Any, Type

from core.agents.base import BaseAgent
from core.agents.analysis_agent import AnalysisAgent
from core.agents.experiment_agent import ExperimentAgent
from core.agents.scale_agent import ScaleAgent
from core.agents.orchestrator import Orchestrator
from core.agents.threshold_agent import ThresholdAgent


# ---------------------------------------------------------------------------
# Agent 元信息
# ---------------------------------------------------------------------------

AGENT_REGISTRY: dict[str, dict[str, Any]] = {
    "analysis": {
        "name": "analysis",
        "display_name": "分析 Agent",
        "description": "归因 + 趋势分析 — 输出 findings (事实) 与 recommendations (建议), 不写数据",
        "cls": AnalysisAgent,
        "switch_code": "analysis_agent_enabled",
        "category": "analyst",      # analyst / experimenter / scaler / orchestrator
        "typical_payload": {},      # 空 payload 即可运行
        "payload_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": True,
        },
        "outputs": [
            "findings: 赛道热度 / 账号表现 / MCN 覆盖率 / 矩阵风险点",
            "recommendations: 优先投哪个赛道 / 扩容哪个账号 / 暂停哪个账号",
        ],
        "risk_level": "low",       # 只读, 不触发任何写操作
    },
    "experiment": {
        "name": "experiment",
        "display_name": "实验 Agent",
        "description": "生成 A/B 假设 + 分组分配 — 通过 variable_name / control_group / test_group 定义实验",
        "cls": ExperimentAgent,
        "switch_code": "experiment_agent_enabled",
        "category": "experimenter",
        "typical_payload": {},
        "payload_schema": {
            "type": "object",
            "properties": {
                "drama_name": {"type": "string", "description": "针对哪部剧做实验 (可空)"},
                "variable":   {"type": "string", "description": "实验变量 (如 publish_hour / edit_mode / caption_style)"},
                "sample_target": {"type": "integer", "default": 20},
            },
            "additionalProperties": True,
        },
        "outputs": [
            "findings: 当前可测试的 hypothesis",
            "recommendations: 建议启动的实验 + 分组方案",
        ],
        "risk_level": "medium",    # 会向 strategy_experiments 写数据
    },
    "scale": {
        "name": "scale",
        "display_name": "放大 Agent",
        "description": "识别 winner 并批量复制 — 仅在 auto_scale_enabled=ON 时执行",
        "cls": ScaleAgent,
        "switch_code": "scale_agent_enabled",
        "category": "scaler",
        "typical_payload": {},
        "payload_schema": {
            "type": "object",
            "properties": {
                "min_plays":     {"type": "integer", "default": 10000, "description": "成为 winner 的最低播放门槛"},
                "max_variants":  {"type": "integer", "default": 3, "description": "每个 winner 最多衍生几个变体"},
            },
            "additionalProperties": True,
        },
        "outputs": [
            "findings: 最近 24h 的 winners 列表 (play_count, like_rate)",
            "recommendations: 待复制到哪些账号 + 建议剪辑模式",
        ],
        "risk_level": "high",
    },
    "threshold": {
        "name": "threshold",
        "display_name": "阈值 Agent",
        "description": "读真实发布数据, 提议规则阈值 (daily_limit/time_window/circuit_breaker) 调整. "
                       "种子规则永不变, 演化历史可追溯可回退.",
        "cls": ThresholdAgent,
        "switch_code": "memory_consolidation_enabled",
        "category": "analyst",
        "typical_payload": {"min_samples": 30, "weeks": 4},
        "payload_schema": {
            "type": "object",
            "properties": {
                "min_samples": {"type": "integer", "default": 30},
                "weeks": {"type": "integer", "default": 4},
            },
        },
        "outputs": [
            "findings: 各规则的实际观察值 / 当前值 / 建议值",
            "proposals: 落 rule_proposals 表, 待人工 approve 或 auto_apply",
        ],
        "risk_level": "medium",
    },
    "orchestrator": {
        "name": "orchestrator",
        "display_name": "总控 Agent",
        "description": "调度 Analysis/Experiment/Scale 串行跑一圈, 合并 findings, 过 rule_engine, 生成 execution_plan 并落 decision_history",
        "cls": Orchestrator,
        "switch_code": "orchestrator_enabled",
        "category": "orchestrator",
        "typical_payload": {},
        "payload_schema": {
            "type": "object",
            "properties": {
                "batch_id":           {"type": "string", "description": "自定义批次 ID (留空自动生成)"},
                "skip_analysis":      {"type": "boolean", "default": False},
                "skip_experiment":    {"type": "boolean", "default": False},
                "skip_scale":         {"type": "boolean", "default": False},
            },
            "additionalProperties": True,
        },
        "outputs": [
            "findings + recommendations + rule_rejections 三路聚合",
            "execution_plan: 按 priority 排好序的待执行任务 (不自动投递)",
            "decision_history 落库 (用于 Agent 复盘)",
        ],
        "risk_level": "high",
    },
}


def list_agents() -> list[dict[str, Any]]:
    """返回 Agent 列表 (不含 class 对象, 纯元数据, 便于 JSON 序列化)."""
    out = []
    for code, meta in AGENT_REGISTRY.items():
        m = {k: v for k, v in meta.items() if k != "cls"}
        out.append(m)
    return out


def get_agent_class(name: str) -> Type[BaseAgent] | None:
    meta = AGENT_REGISTRY.get(name)
    if meta is None:
        return None
    return meta["cls"]


def agent_exists(name: str) -> bool:
    return name in AGENT_REGISTRY
