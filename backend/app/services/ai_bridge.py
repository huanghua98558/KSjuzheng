"""ks_automation/core/* lazy bridge.

后端不直接 import ks_automation 模块 (避免循环依赖 + 客户端环境差异),
仅在手动 trigger 时调用 (后台 thread).

设计:
  - import 失败 silent 忽略, 不让后端起不来
  - 调用 ks_automation.core.agents.<agent>_agent.run() (或类似)
  - 完成后回写 agent_runs.status
"""
from __future__ import annotations

import importlib
import os
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path

from app.core.logging import logger


_now = lambda: datetime.now(timezone.utc)  # noqa: E731

# ks_automation 路径 — 默认猜在 D:/ks_automation, 可被 ENV 覆盖
KS_AUTOMATION_PATH = os.environ.get(
    "KS_AUTOMATION_PATH",
    str(Path(r"D:/ks_automation").resolve()),
)


# Agent name → ks_automation 模块路径 (Python module string)
_AGENT_MODULE_MAP = {
    "strategy_planner": "core.agents.strategy_planner_agent",
    "task_scheduler": "core.agents.task_scheduler_agent",
    "watchdog": "core.agents.watchdog_agent",
    "analyzer": "core.agents.analyzer_agent",
    "llm_researcher": "core.agents.llm_researcher_agent",
    "burst": "core.agents.burst_agent",
    "maintenance": "core.agents.maintenance_agent",
    "self_healing": "core.agents.self_healing_agent",
    "controller": "core.agents.controller_agent",
}


def _ensure_path():
    p = KS_AUTOMATION_PATH
    if p and p not in sys.path and Path(p).is_dir():
        sys.path.insert(0, p)


def _load_agent_module(agent_name: str):
    _ensure_path()
    mod_path = _AGENT_MODULE_MAP.get(agent_name)
    if not mod_path:
        return None
    try:
        return importlib.import_module(mod_path)
    except Exception as ex:  # noqa: BLE001
        logger.warning(
            f"[ai_bridge] 无法 import {mod_path}: {ex}. "
            f"\u8bf7\u786e\u8ba4 KS_AUTOMATION_PATH=`{KS_AUTOMATION_PATH}` \u8def\u5f84\u5b58\u5728."
        )
        return None


def is_agent_available(agent_name: str) -> bool:
    return _load_agent_module(agent_name) is not None


def list_available_agents() -> dict:
    out = {}
    for name in _AGENT_MODULE_MAP:
        out[name] = is_agent_available(name)
    return out


def dispatch_agent_async(
    run_db_id: int, agent_name: str, organization_id: int | None, dry_run: bool,
) -> None:
    """\u540e\u53f0\u7ebf\u7a0b\u8df3\u8d77 — \u4e0d\u963b\u585e\u8c03\u7528\u8005."""
    t = threading.Thread(
        target=_run_agent_safely,
        args=(run_db_id, agent_name, organization_id, dry_run),
        daemon=True,
        name=f"agent-{agent_name}-{run_db_id}",
    )
    t.start()


def _run_agent_safely(
    run_db_id: int, agent_name: str, organization_id: int | None, dry_run: bool,
):
    """\u5b9e\u9645\u8c03 ks_automation. \u5b8c\u6210\u540e\u56de\u5199 agent_run."""
    from app.core.db import get_session_factory
    from app.models import AgentRun

    session_factory = get_session_factory()
    started = _now()
    output = None
    error = None
    status = "success"

    try:
        mod = _load_agent_module(agent_name)
        if not mod:
            status = "failed"
            error = f"agent module {agent_name} not loadable"
        else:
            # ks_automation \u6bcf\u4e2a agent \u4e0d\u540c\u5165\u53e3, \u5c1d\u8bd5 run / main / __main__:
            run_fn = (
                getattr(mod, "run", None)
                or getattr(mod, "main", None)
                or getattr(mod, "execute", None)
            )
            if not callable(run_fn):
                status = "failed"
                error = f"agent {agent_name} \u672a\u5bfc\u51fa run/main/execute"
            else:
                try:
                    result = run_fn(dry_run=dry_run, organization_id=organization_id)
                except TypeError:
                    # \u5176\u4e2d\u4e00\u4e9b\u53ea\u6536 dry_run
                    try:
                        result = run_fn(dry_run=dry_run)
                    except TypeError:
                        result = run_fn()
                output = str(result)[:2000] if result is not None else None
    except Exception as ex:  # noqa: BLE001
        status = "failed"
        error = f"{type(ex).__name__}: {ex}"[:1000]
        logger.error(f"[ai_bridge] agent {agent_name} \u8df3\u8d77\u51fa\u9519: {ex}")

    finished = _now()

    # 回写
    try:
        with session_factory() as db:
            run = db.get(AgentRun, run_db_id)
            if run:
                run.status = status
                run.finished_at = finished
                run.duration_ms = int(
                    (finished - started).total_seconds() * 1000
                )
                run.output_json = output
                run.error_message = error
                db.commit()
    except Exception as ex:
        logger.error(f"[ai_bridge] \u56de\u5199 agent_run \u5931\u8d25: {ex}")
