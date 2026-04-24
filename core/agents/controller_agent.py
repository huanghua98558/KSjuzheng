# -*- coding: utf-8 -*-
"""ControllerAgent — 24/7 AI 总指挥, 全自动闭环的调度中枢.

每 60s 一轮 (可配):
  1. 开 cycle record → 采集系统快照
  2. 查失败任务 → 触发 SelfHealingAgent
  3. 查关键指标 → 如需要触发 Analysis / Experiment / Scale
  4. 每小时触发 ThresholdAgent (规则自学)
  5. 每日生成 ReportAgent 自愈日报
  6. 关闭 cycle record

不走 Orchestrator 的重型 LLM 流程 (那需要 60-90s), Controller 本身轻量.
重型决策交给它触发的子 Agent.
"""
from __future__ import annotations

import json
import secrets
import sqlite3
import time
from datetime import datetime
from typing import Any

from core.config import DB_PATH


def _wal_conn():
    """独立连接, 打开 WAL + busy_timeout, 写 autopilot_cycles 不怕被 worker 锁."""
    c = sqlite3.connect(DB_PATH, check_same_thread=False, timeout=120.0,
                        isolation_level=None)   # autocommit-ish, 免 implicit BEGIN
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=120000")
    c.execute("PRAGMA synchronous=NORMAL")
    return c


def _retry_write(conn, sql: str, params: tuple | list = (),
                 max_attempts: int = 6) -> None:
    """重试执行 write SQL, 遇 'database is locked' 指数退避后重试."""
    import time as _t
    delay = 0.2
    last_err: Exception | None = None
    for _ in range(max_attempts):
        try:
            conn.execute(sql, params)
            return
        except sqlite3.OperationalError as e:
            if "locked" not in str(e).lower():
                raise
            last_err = e
            _t.sleep(delay)
            delay = min(delay * 2, 3.0)
    if last_err:
        raise last_err


class ControllerAgent:
    """不继承 BaseAgent (不走 agent_runs 表), 直接落 autopilot_cycles."""

    name = "controller"

    def __init__(self, db_manager):
        self.db = db_manager
        self._last_threshold_run = 0
        self._last_report_run = 0
        self._last_upgrade_run = 0
        self._last_mcn_drama_sync = 0     # 每 24h 同步 MCN 剧库
        self._last_mcn_cookie_sync = 0    # 每 4h 同步 MCN cookie
        self._last_mcn_member_snapshot = 0  # 每 24h 抓 fluorescent_members 快照
        # AI 决策层 (v20)
        self._last_analyzer_run = 0       # 每日 17:00 分析 + tier 迁移
        self._last_planner_run = 0        # 每日 08:00 生成 daily_plan
        self._last_planner_plan_date = "" # ★ 2026-04-23 §Bug1: 按 plan_date 判重, 防 24h 滚动锁
        self._last_scheduler_run = 0      # 每 2h 把 plan 转 task_queue
        self._last_watchdog_run = 0       # 每 5-10min
        self._last_llm_research_run = 0   # 每周一 07:00
        # Phase 2 ABCD (v24)
        self._last_burst_run = 0          # B: 每 30min 扫爆款
        self._last_maintenance_run = 0    # D: 每 1h 扫维护
        # Phase 3 MCN 镜像 (v26)
        self._last_mcn_full_sync = 0      # 每日 04:00 同步 MCN 4 张高价值表
        self._last_ks_names_sync = 0      # 每 12h 回填 kuaishou_name + signed_status
        self._last_url_pool_sync = 0      # ★ §26 每日 04:15 同步 MCN 剧库 (181万 urls)
        self._last_spark_drama_sync = 0   # ★ §24 每日 04:30 同步 spark_drama_info (134k biz_id)
        self._last_account_health_sync = 0  # ★ §26.21 每日 04:45 sync 账号健康 (3 源交叉验证)
        # ★ 2026-04-23 §31 候选池链路 (完整升级: MCN 违规 + wait_collect + candidate_builder)
        self._last_violation_sync = 0        # step 17f: 每日 04:45 同步 spark_violation_dramas (2760)
        self._last_wait_collect_inc_sync = 0 # step 17g: 每 6h 增量同步 wait_collect_videos (22k)
        self._last_candidate_pool_build = 0  # step 17h: 每日 07:45 build daily_candidate_pool (planner 消费)
        # 2026-04-20 新增: 作者采集 + 剧链修复 (用户要求)
        self._last_authors_collect = 0    # step 18: 每 24h 从作者库采新剧
        self._last_drama_reclaim = 0      # step 19: 每 6h 重救 broken drama_links
        self._last_url_preload = 0        # step 20: 每 1h 预验 pending URL
        self._last_vertical_infer = 0     # step 21: 每 6h 补垂类 + 周记
        self._last_mcn_auto_invite = 0    # step 22: 每 24h 扫未绑账号自动邀请
        self._last_mcn_invite_poll = 0    # step 22b: 每 6h 查 mcn_invitations 签约状态
        self._last_plays_snapshot = 0     # step 23: 每 1h 播放量快照 + today_delta
        self._last_account_cleanup = 0    # step 24: 每 12h 新号自动清洗 + 赛道
        # ★ 2026-04-24 v6 B4: 自适应运营模式 (operation_mode)
        self._last_operation_mode_check = 0  # step 25: 每 5min 检测是否应切 mode
        # ★ 2026-04-24 v6 Day 7: 80004 闭环 — account×drama blacklist 过期清理
        self._last_adb_cleanup = 0        # step 25b: 每 1h 清 account_drama_blacklist 过期
        # ★ 2026-04-24 v6 Day 8: 爆款雷达 (hot_hunter 扫作者 + 作者池升级)
        self._last_hot_hunter_scan = 0    # step 26: 每 2h 扫作者 profile/feed
        self._last_author_priority_update = 0  # step 26b: 每 6h 更新作者 scrape_priority
        # ★ 2026-04-24 v6 Day 8: publish_outcome 回采 (24h/48h/7d)
        self._last_outcome_collect_24h = 0   # step 26c: 每 1h 扫
        self._last_outcome_collect_48h = 0   # step 26d: 每 3h 扫
        self._last_outcome_collect_7d = 0    # step 26e: 每 12h 扫
        # 自己的写连接, 避免跟 worker 抢 self.db.conn
        self._wc = _wal_conn()
        # ★ 2026-04-23 Bug 8: 从 DB 恢复 _last_* 状态, 重启不丢
        self._restore_state()

    def _restore_state(self) -> None:
        """从 agent_run_state 表恢复 _last_* 时间戳 + plan_date.

        避免重启 autopilot 时 timestamp 清零 → 某些每日只跑一次的
        agent 立即又跑一遍.
        """
        try:
            rows = self._wc.execute(
                "SELECT agent_name, last_run_ts, last_plan_date FROM agent_run_state"
            ).fetchall()
        except Exception:
            return  # 表不存在时跳过 (首次运行)
        mapping = {
            "planner":             "_last_planner_run",
            "scheduler":           "_last_scheduler_run",
            "analyzer":            "_last_analyzer_run",
            "watchdog":            "_last_watchdog_run",
            "burst":               "_last_burst_run",
            "maintenance":         "_last_maintenance_run",
            "llm_researcher":      "_last_llm_research_run",
            "mcn_cookie_sync":     "_last_mcn_cookie_sync",
            "mcn_drama_sync":      "_last_mcn_drama_sync",
            "mcn_member_snapshot": "_last_mcn_member_snapshot",
            "threshold":           "_last_threshold_run",
            "report":              "_last_report_run",
            "upgrade":             "_last_upgrade_run",
            # ★ §31 候选池链路持久化 (2026-04-23)
            "violation_sync":       "_last_violation_sync",
            "wait_collect_inc":     "_last_wait_collect_inc_sync",
            "candidate_pool_build": "_last_candidate_pool_build",
            # ★ 2026-04-24 v6 B4 运营模式
            "operation_mode":       "_last_operation_mode_check",
        }
        restored = 0
        for r in rows:
            agent_name = r[0]
            ts = r[1] or 0
            plan_date = r[2] or ""
            attr = mapping.get(agent_name)
            if attr and hasattr(self, attr):
                setattr(self, attr, float(ts))
                restored += 1
            # planner 特殊: 需要恢复 plan_date 判重
            if agent_name == "planner" and plan_date:
                self._last_planner_plan_date = plan_date
        if restored:
            import sys
            print(f"[ControllerAgent] 恢复 {restored} agent 状态 (_last_*) from DB",
                  file=sys.stderr)

    def _persist_state(self, agent_name: str, plan_date: str = "",
                        result: str = "") -> None:
        """写当前 agent 最新状态到 agent_run_state."""
        try:
            self._wc.execute(
                """INSERT INTO agent_run_state
                   (agent_name, last_run_at, last_run_ts, last_plan_date,
                    last_result, updated_at)
                   VALUES (?, datetime('now','localtime'), ?, ?, ?,
                           datetime('now','localtime'))
                   ON CONFLICT(agent_name) DO UPDATE SET
                     last_run_at=excluded.last_run_at,
                     last_run_ts=excluded.last_run_ts,
                     last_plan_date=CASE WHEN excluded.last_plan_date != ''
                                         THEN excluded.last_plan_date
                                         ELSE last_plan_date END,
                     last_result=excluded.last_result,
                     updated_at=excluded.updated_at""",
                (agent_name, time.time(), plan_date, result[:200])
            )
            self._wc.commit()
        except Exception:
            pass   # 持久化失败不影响主流程

    # ==================================================================

    def run_cycle(self) -> dict[str, Any]:
        """一次完整循环."""
        cycle_id = f"cycle_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{secrets.token_hex(2)}"
        t0 = time.time()
        agents_triggered: list[str] = []
        checks_run = 0
        failures_found = 0
        heals_proposed = 0
        heals_applied = 0

        # 开 cycle
        self._start_cycle(cycle_id)

        try:
            # 1. 扫失败 — 总是做
            recent_fail_count = self._count_recent_failures(hours=2)
            checks_run += 1

            # 2. 如果有失败 → 触发 SelfHealing
            if recent_fail_count > 0:
                failures_found = recent_fail_count
                from core.agents.self_healing_agent import SelfHealingAgent
                healing_resp = SelfHealingAgent(self.db).run({
                    "cycle_id": cycle_id, "hours": 2,
                })
                agents_triggered.append("self_healing")
                meta = healing_resp.get("meta", {})
                actions = meta.get("actions_taken", [])
                heals_proposed = len(actions)
                heals_applied = sum(1 for a in actions if a.get("ok"))

            # 3. 每小时触发 ThresholdAgent
            if time.time() - self._last_threshold_run > 3600:
                try:
                    from core.agents.threshold_agent import ThresholdAgent
                    ThresholdAgent(self.db).run({"min_samples": 30, "weeks": 4})
                    agents_triggered.append("threshold")
                    self._last_threshold_run = time.time()
                except Exception:
                    pass
                checks_run += 1

            # 4. 每 24h 一次 orchestrator (深度决策)
            # (懒策略: 如果今天还没跑过 orchestrator 就跑)
            last_orc = self._last_orchestrator_run()
            if last_orc and (time.time() - last_orc > 86400):
                try:
                    from core.agents.orchestrator import Orchestrator
                    Orchestrator(self.db).run({})
                    agents_triggered.append("orchestrator")
                except Exception:
                    pass
                checks_run += 1

            # 5. 每 24h 一次 ReportAgent (AI 修复日报)
            if time.time() - self._last_report_run > 86400:
                try:
                    from core.agents.report_agent import ReportAgent
                    ReportAgent(self.db).run({"hours": 24})
                    agents_triggered.append("report")
                    self._last_report_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] report failed: {e}", file=sys.stderr)
                checks_run += 1

            # 6. 每 6h 一次 UpgradeAgent (AI 升级提议)
            if time.time() - self._last_upgrade_run > 21600:
                try:
                    from core.agents.upgrade_agent import UpgradeAgent
                    UpgradeAgent(self.db).run({"days": 7, "min_occurrences": 3})
                    agents_triggered.append("upgrade")
                    self._last_upgrade_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] upgrade failed: {e}", file=sys.stderr)
                checks_run += 1

            # 配置驱动的间隔 (读 app_config, 运行时可改)
            from core.app_config import get as _cfg
            cookie_interval = _cfg("sync.cookie.interval_sec", 14400)
            drama_interval = _cfg("sync.drama.interval_sec", 86400)
            snap_interval  = _cfg("sync.member_snapshot.interval_sec", 86400)

            # 7. MCN cookie 同步 (间隔由 app_config.sync.cookie.interval_sec 控制)
            if time.time() - self._last_mcn_cookie_sync > cookie_interval:
                try:
                    from scripts.sync_mcn_cookies import sync as _sync_ck
                    owner_code = _cfg("sync.cookie.owner_code", "黄华")
                    stats = _sync_ck(owner_code=owner_code, only_logged_in=True)
                    agents_triggered.append(
                        f"mcn_cookie_sync(rebuilt={stats.get('cookie_rebuilt', 0)},"
                        f"new={stats.get('new_account', 0)})"
                    )
                    self._last_mcn_cookie_sync = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] mcn_cookie_sync failed: {e}", file=sys.stderr)
                checks_run += 1

            # 8. MCN 剧库同步 (间隔由 sync.drama.interval_sec 控制)
            if time.time() - self._last_mcn_drama_sync > drama_interval:
                try:
                    from scripts.sync_mcn_drama_library import sync as _sync_dr
                    only_active = _cfg("sync.drama.only_active", True)
                    recent_days = _cfg("sync.drama.recent_income_days", 30)
                    stats = _sync_dr(only_active=only_active,
                                      recent_income_days=recent_days)
                    agents_triggered.append(
                        f"mcn_drama_sync(new={stats.get('inserted_new', 0)},"
                        f"upd={stats.get('updated_existing', 0)})"
                    )
                    self._last_mcn_drama_sync = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] mcn_drama_sync failed: {e}", file=sys.stderr)
                checks_run += 1

            # 9. fluorescent_members 快照 (间隔由 sync.member_snapshot.interval_sec 控制)
            if time.time() - self._last_mcn_member_snapshot > snap_interval:
                try:
                    from scripts.snapshot_mcn_members import snapshot as _snap
                    org_ids = _cfg("sync.member_snapshot.org_ids", [10])
                    plans = _cfg("sync.member_snapshot.plans", ['fluorescent'])
                    stats = _snap(org_ids=org_ids, include_plans=plans)
                    agents_triggered.append(
                        f"mcn_member_snap(cap={stats.get('members_captured', 0)},"
                        f"delta={stats.get('members_with_delta', 0)},"
                        f"+¥{stats.get('total_delta_amount', 0):.2f})"
                    )
                    self._last_mcn_member_snapshot = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] mcn_member_snapshot failed: {e}", file=sys.stderr)
                checks_run += 1

            # ═══════════ AI 决策层 (v20) ═══════════
            import datetime as _dt
            now = _dt.datetime.now()

            # 10. Watchdog (每 5min)
            watchdog_interval = _cfg("ai.watchdog.interval_min", 5) * 60
            if time.time() - self._last_watchdog_run > watchdog_interval:
                try:
                    from core.agents.watchdog_agent import run as _wd
                    r = _wd()
                    agents_triggered.append(
                        f"watchdog(fail_rate={r.get('fail_rate',{}).get('rate',0):.0%},"
                        f"frozen={len(r.get('frozen', []))})"
                    )
                    self._last_watchdog_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] watchdog failed: {e}", file=sys.stderr)
                checks_run += 1

            # 11. Task Scheduler (每 2h 把 daily_plan → task_queue)
            sched_interval = _cfg("ai.scheduler.batch_interval_hours", 2) * 3600
            if time.time() - self._last_scheduler_run > sched_interval:
                try:
                    from core.agents.task_scheduler_agent import run as _sched
                    r = _sched()
                    agents_triggered.append(
                        f"task_sched(due={r.get('due_items',0)},"
                        f"enq={r.get('enqueued',0)})"
                    )
                    self._last_scheduler_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] task_scheduler failed: {e}", file=sys.stderr)
                checks_run += 1

            # 12. Strategy Planner (每日 N:00 后, 按 plan_date 判重 — 不是 24h 滚动锁)
            # ★ 2026-04-23 Bug 1 修复: 老逻辑 `time() - _last_planner_run > 86400`
            # 会被"前一天较晚时间 exists=True 的运行"卡死 (如昨天 15:29 跑一次, 更新 ts,
            # 今天 8:00 被 86400 挡住 → 今天 0 发布). 新逻辑按自然日判重, 每日只尝试一次.
            planner_hour = _cfg("ai.planner.run_hour", 8)
            today_str = now.strftime("%Y-%m-%d")
            if (now.hour >= planner_hour
                    and self._last_planner_plan_date != today_str):
                try:
                    from core.agents.strategy_planner_agent import run as _plan
                    r = _plan()
                    agents_triggered.append(
                        f"planner(items={r.get('total_items', 0)},"
                        f"exists={r.get('already_exists', False)})"
                    )
                    # ★ 只在"真生成 plan"或"exists=True"时标记完成, 异常不标记 → 下 cycle 重试
                    if r.get("ok") and (r.get("total_items", 0) > 0
                                         or r.get("already_exists")):
                        self._last_planner_plan_date = today_str
                        self._last_planner_run = time.time()  # 保留兼容
                        # ★ 2026-04-23 Bug 8: 持久化到 DB
                        self._persist_state("planner", plan_date=today_str,
                                            result=f"items={r.get('total_items',0)} exists={r.get('already_exists',False)}")
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] planner failed: {e}", file=sys.stderr)
                checks_run += 1

            # 13. Analyzer — ★ 2026-04-22 §28_Q 根本修: 每 1h 跑一次 (不等 17:00)
            # 背景: 老逻辑 "每日 17:00 + 24h 锁" 让 verdict/tier/memory 一天才刷 1 次,
            # 任务完成 → MCN 收益到账 (48h) → 重判 → Layer 2 激活 这一链路本来就需要
            # 密集运转. 1h cadence 保证 48h 窗口内能 re-verdict 24 次找到最新收益.
            analyzer_interval_hours = int(_cfg("ai.analyzer.run_interval_hours", 1))
            if time.time() - self._last_analyzer_run > analyzer_interval_hours * 3600:
                try:
                    from core.agents.analyzer_agent import run as _an
                    r = _an()
                    tier_info = r.get("tier", {})
                    agents_triggered.append(
                        f"analyzer(trans={tier_info.get('transitioned',0)},"
                        f"date={r.get('target_date','')})"
                    )
                    self._last_analyzer_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] analyzer failed: {e}", file=sys.stderr)
                checks_run += 1

            # 14. LLM Researcher — ★ 2026-04-22 §28_O: 每 12h 跑一次, 不等周一
            # 背景: 老逻辑 "周一 07:00 + 6 天锁" 让 Layer 3 diary 一周才 1 次,
            # 测试期账号需要更频繁的 reflection. 改 12h cadence (每天 2 次, 早 7 晚 19).
            llm_interval_hours = int(_cfg("ai.llm.run_interval_hours", 12))
            if time.time() - self._last_llm_research_run > llm_interval_hours * 3600:
                try:
                    from core.agents.llm_researcher_agent import run as _llm
                    # 全模式 (strategy + propose_rules + upgrades + diary)
                    r = _llm(mode="all")
                    diary_r = r.get("diary") or {}
                    agents_triggered.append(
                        f"llm_research(ok={r.get('ok', True)},"
                        f"diary_gen={diary_r.get('generated', 0)})"
                    )
                    self._last_llm_research_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] llm_researcher failed: {e}", file=sys.stderr)
                checks_run += 1

            # 15. Burst Agent (Phase 2 B: 每 30min 扫爆款, 触发全矩阵跟发)
            burst_interval = int(_cfg("ai.burst.check_interval_sec", 1800))
            if _cfg("ai.burst.enabled", True) and \
                    time.time() - self._last_burst_run > burst_interval:
                try:
                    from core.agents.burst_agent import run as _burst
                    r = _burst(dry_run=False)
                    agents_triggered.append(
                        f"burst(cands={r.get('candidates_found',0)},"
                        f"batches={r.get('batches_triggered',0)})"
                    )
                    self._last_burst_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] burst failed: {e}", file=sys.stderr)
                checks_run += 1

            # 16. Maintenance Agent (Phase 2 D: 每 1h 扫维护任务)
            maint_interval = int(_cfg("ai.maintenance.check_interval_sec", 3600))
            if _cfg("ai.maintenance.enabled", True) and \
                    time.time() - self._last_maintenance_run > maint_interval:
                try:
                    from core.agents.maintenance_agent import run as _maint
                    r = _maint(dry_run=False)
                    enq = r.get("enqueued", {})
                    total_enq = sum(enq.values()) if isinstance(enq, dict) else 0
                    agents_triggered.append(
                        f"maintenance(total_enq={total_enq},"
                        f"types={list(enq.keys()) if isinstance(enq, dict) else []})"
                    )
                    self._last_maintenance_run = time.time()
                except Exception as e:
                    import sys
                    print(f"[ControllerAgent] maintenance failed: {e}", file=sys.stderr)
                checks_run += 1

            # 17. MCN 镜像同步 (Phase 3 v26: 每日 N:00, 把 MCN 4 张高价值表落地本地)
            #     high_income_dramas / drama_blacklist / photo_violation_log /
            #     mcn_organizations_local. 解 planner 选剧依赖网络问题.
            if _cfg("sync.mcn.enabled", True):
                cron_hour = int(_cfg("sync.mcn.controller.cron_hour", 4))
                now_dt = datetime.now()
                # 当日 N 点窗口 (N:00-N:59), 且本日还没跑过
                last_run_today = (
                    self._last_mcn_full_sync > 0
                    and datetime.fromtimestamp(self._last_mcn_full_sync).date() == now_dt.date()
                )
                if now_dt.hour == cron_hour and not last_run_today:
                    try:
                        from scripts.sync_mcn_full import run_all as _sync_mcn
                        r = _sync_mcn(force=False, dry_run=False)
                        results = r.get("results", {}) if isinstance(r, dict) else {}
                        ok_count = sum(1 for v in results.values()
                                       if isinstance(v, dict) and v.get("status") == "success")
                        fail_count = sum(1 for v in results.values()
                                         if isinstance(v, dict) and v.get("status") == "failed")
                        agents_triggered.append(
                            f"sync_mcn_full(ok={ok_count} fail={fail_count})"
                        )
                        self._last_mcn_full_sync = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] sync_mcn_full failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 17b. MCN 剧库镜像 (2026-04-22 §26: 复刻 KS184 运维)
            #      每日 cron_hour + 15min 同步:
            #        mcn_url_pool (181万 条 kuaishou_urls)
            #        mcn_drama_collections (13.5万 采集历史)
            #      这是 KS184 "高转化提取" 的数据基石, 覆盖 14973 个剧.
            if _cfg("sync.url_pool.enabled", True):
                cron_hour = int(_cfg("sync.url_pool.controller.cron_hour", 4))
                cron_min = int(_cfg("sync.url_pool.controller.cron_minute", 15))
                now_dt = datetime.now()
                last_run_today_pool = (
                    self._last_url_pool_sync > 0
                    and datetime.fromtimestamp(self._last_url_pool_sync).date() == now_dt.date()
                )
                if (now_dt.hour == cron_hour and now_dt.minute >= cron_min
                        and not last_run_today_pool):
                    try:
                        import subprocess as _sp
                        # subprocess 跑, 避免阻塞 controller (耗时 ~100s)
                        r = _sp.run(
                            [sys.executable, "-m", "scripts.sync_mcn_url_pool"],
                            cwd=r"D:\ks_automation", capture_output=True,
                            text=True, timeout=600, encoding="utf-8", errors="replace",
                        )
                        agents_triggered.append(
                            f"sync_url_pool(rc={r.returncode},"
                            f"out_tail={(r.stdout or '')[-120:].strip()!r})"
                        )
                        self._last_url_pool_sync = time.time()
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] sync_url_pool failed: {e}", file=_s.stderr)
                    checks_run += 1

            # 17c. MCN 剧库 spark_drama_info 同步 (§24, drama_banner_tasks 来源)
            if _cfg("sync.spark_drama.enabled", True):
                cron_hour = int(_cfg("sync.spark_drama.controller.cron_hour", 4))
                cron_min = int(_cfg("sync.spark_drama.controller.cron_minute", 30))
                now_dt = datetime.now()
                last_run_today_spark = (
                    self._last_spark_drama_sync > 0
                    and datetime.fromtimestamp(self._last_spark_drama_sync).date() == now_dt.date()
                )
                if (now_dt.hour == cron_hour and now_dt.minute >= cron_min
                        and not last_run_today_spark):
                    try:
                        import subprocess as _sp
                        r = _sp.run(
                            [sys.executable, "-m", "scripts.sync_spark_drama_full"],
                            cwd=r"D:\ks_automation", capture_output=True,
                            text=True, timeout=300, encoding="utf-8", errors="replace",
                        )
                        agents_triggered.append(
                            f"sync_spark_drama(rc={r.returncode},"
                            f"out_tail={(r.stdout or '')[-120:].strip()!r})"
                        )
                        self._last_spark_drama_sync = time.time()
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] sync_spark_drama failed: {e}", file=_s.stderr)
                    checks_run += 1

            # 17d. 账号健康同步 (2026-04-22 §26.21: 3 源交叉验证)
            #      修用户反馈: "账号信息刷新不对, AI 没有账号详情"
            #      每日 04:45 跑: 本地 × spark_org × fluorescent_members
            #      严格规则: 不在 fluorescent → frozen; 在 fluorescent + login OK + tier=None → testing
            if _cfg("sync.account_health.enabled", True):
                cron_hour = int(_cfg("sync.account_health.cron_hour", 4))
                cron_min = int(_cfg("sync.account_health.cron_minute", 45))
                now_dt = datetime.now()
                last_run_today_health = (
                    self._last_account_health_sync > 0
                    and datetime.fromtimestamp(self._last_account_health_sync).date() == now_dt.date()
                )
                if (now_dt.hour == cron_hour and now_dt.minute >= cron_min
                        and not last_run_today_health):
                    try:
                        from scripts.sync_account_health import sync as _sync_health
                        r = _sync_health(dry_run=False, verbose=False)
                        agents_triggered.append(
                            f"sync_account_health(frozen={r['tier_frozen']},"
                            f"active={r['tier_active']},changes={r['tier_changes']},"
                            f"fluo_amt={r['total_fluo_amount']})"
                        )
                        self._last_account_health_sync = time.time()
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] sync_account_health failed: {e}", file=_s.stderr)
                    checks_run += 1

            # 17e. MCN 昵称回填 (2026-04-21 用户要求: "让系统自动去查服务器")
            #      每 N 小时调 scripts.sync_kuaishou_names.run_sync 对齐:
            #        device_accounts.kuaishou_name  (MCN 真昵称)
            #        device_accounts.signed_status  (signed / unsigned)
            #      不动 account_name (运营别名). MCN 离线时自动跳过, 无副作用.
            if _cfg("sync.ks_names.enabled", True):
                ks_interval = int(_cfg("sync.ks_names.interval_sec", 43200))  # 12h
                if time.time() - self._last_ks_names_sync > ks_interval:
                    try:
                        from scripts.sync_kuaishou_names import run_sync as _sync_ks
                        stats = _sync_ks(dry_run=False, verbose=False)
                        if stats.get("online"):
                            agents_triggered.append(
                                f"sync_ks_names("
                                f"updated={stats.get('signed_updated', 0)},"
                                f"confirmed={stats.get('signed_confirmed', 0)},"
                                f"unsigned={stats.get('unsigned_marked', 0)},"
                                f"err={len(stats.get('errors', []))})"
                            )
                            self._last_ks_names_sync = time.time()
                        else:
                            # MCN 离线 — 稍后重试, 不记录 last_run
                            import sys
                            print("[ControllerAgent] sync_ks_names: MCN offline, retry later",
                                  file=sys.stderr)
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] sync_ks_names failed: {e}", file=sys.stderr)
                    checks_run += 1

            # ═══════════════════════════════════════════════════════════
            # ★ §31 候选池链路 (2026-04-23 完整升级, 对齐 MCN 全量数据) ★
            #
            #   17f. 每日 04:45  sync_spark_violation       (2760 违规)
            #   17g. 每 6h       sync_wait_collect_inc     (22k 新鲜池)
            #   17h. 每日 07:45  candidate_builder.build   (TOP 30 候选池 → planner 08:00 消费)
            #
            # 链路: sync → mirror 表 → candidate_builder 5 层漏斗 + 6 维评分
            #       → daily_candidate_pool → strategy_planner Path 0 消费
            # ═══════════════════════════════════════════════════════════

            # 17f. 违规库同步 (每日 04:45, 全量 replace)
            if _cfg("sync.spark_violation.enabled", True):
                cron_hour = int(_cfg("sync.spark_violation.cron_hour", 4))
                cron_min = int(_cfg("sync.spark_violation.cron_minute", 45))
                now_dt = datetime.now()
                last_run_today_vio = (
                    self._last_violation_sync > 0
                    and datetime.fromtimestamp(self._last_violation_sync).date() == now_dt.date()
                )
                if (now_dt.hour == cron_hour and now_dt.minute >= cron_min
                        and not last_run_today_vio):
                    try:
                        import subprocess as _sp
                        import sys as _sys
                        r = _sp.run(
                            [_sys.executable, "-m", "scripts.sync_spark_violation",
                             "--quiet"],
                            cwd=r"D:\ks_automation", capture_output=True,
                            text=True, timeout=180, encoding="utf-8", errors="replace",
                        )
                        agents_triggered.append(
                            f"sync_violation(rc={r.returncode},"
                            f"out_tail={(r.stdout or '')[-120:].strip()!r})"
                        )
                        self._last_violation_sync = time.time()
                        self._persist_state("violation_sync",
                                            result=f"rc={r.returncode}")
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] sync_violation failed: {e}",
                              file=_s.stderr)
                    checks_run += 1

            # 17g. wait_collect 增量同步 (每 6h, 22k 行 UPSERT)
            #      script 自带 throttle (6h 内跳过), 这里再加 controller 级节流
            if _cfg("sync.wait_collect.enabled", True):
                wc_interval = int(_cfg("sync.wait_collect.inc_interval_hours", 6)) * 3600
                if time.time() - self._last_wait_collect_inc_sync > wc_interval:
                    try:
                        import subprocess as _sp
                        import sys as _sys
                        r = _sp.run(
                            [_sys.executable, "-m",
                             "scripts.sync_wait_collect_incremental"],
                            cwd=r"D:\ks_automation", capture_output=True,
                            text=True, timeout=300, encoding="utf-8", errors="replace",
                        )
                        agents_triggered.append(
                            f"sync_wait_collect_inc(rc={r.returncode},"
                            f"out_tail={(r.stdout or '')[-120:].strip()!r})"
                        )
                        self._last_wait_collect_inc_sync = time.time()
                        self._persist_state("wait_collect_inc",
                                            result=f"rc={r.returncode}")
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] sync_wait_collect_inc failed: {e}",
                              file=_s.stderr)
                    checks_run += 1

            # 17h. candidate_builder (每日 07:45, 生成 daily_candidate_pool TOP N)
            #      必须在 step 12 planner (08:00) 之前. 五层漏斗 + 6 维评分.
            #      依赖 17b (url_pool) + 17c (spark_drama) + 17f (violation) + 17g (wait_collect)
            #      今日已有的数据; 若 builder 跑失败 / 数据空, planner 自动 fallback legacy.
            if _cfg("ai.candidate.enabled", True):
                cron_hour = int(_cfg("ai.candidate.cron_hour", 7))
                cron_min = int(_cfg("ai.candidate.cron_minute", 45))
                now_dt = datetime.now()
                last_build_today = (
                    self._last_candidate_pool_build > 0
                    and datetime.fromtimestamp(self._last_candidate_pool_build).date() == now_dt.date()
                )
                if (now_dt.hour == cron_hour and now_dt.minute >= cron_min
                        and not last_build_today):
                    try:
                        from core.candidate_builder import build_candidate_pool as _build_cp
                        r = _build_cp(dry_run=False)
                        if isinstance(r, dict):
                            agents_triggered.append(
                                f"candidate_pool_build("
                                f"persisted={r.get('persisted',0)},"
                                f"scored={r.get('scored',0)},"
                                f"avg_cs={r.get('avg_composite_score',0):.1f})"
                            )
                        else:
                            agents_triggered.append("candidate_pool_build(done)")
                        self._last_candidate_pool_build = time.time()
                        self._persist_state("candidate_pool_build",
                                            plan_date=now_dt.strftime("%Y-%m-%d"),
                                            result=f"persisted={r.get('persisted',0) if isinstance(r,dict) else 0}")
                    except Exception as e:
                        import sys as _s
                        print(f"[ControllerAgent] candidate_pool_build failed: {e}",
                              file=_s.stderr)
                    checks_run += 1

            # 18. 作者采集复活 (2026-04-20 用户要求: 每 24h 从作者库采新剧)
            #     drama_authors 283 条, 调 scripts.collect_dramas --from-authors
            #     保证 drama_links 池有新鲜货 (不然 planner 只能从 MCN 134k 按 title 选,
            #     没真实 play_url 也不能发). 默认 limit=15 个作者 × ~10 剧 ≈ 150 新 link.
            if _cfg("ai.collector.authors_enabled", True):
                authors_interval = int(_cfg("ai.collector.authors_interval_sec", 86400))
                if time.time() - self._last_authors_collect > authors_interval:
                    try:
                        import subprocess, sys as _sys
                        limit = int(_cfg("ai.collector.authors_limit", 15))
                        pages = int(_cfg("ai.collector.authors_pages", 1))
                        r = subprocess.run(
                            [_sys.executable, "-X", "utf8", "-m",
                             "scripts.collect_dramas", "--from-authors",
                             "--author-limit", str(limit),
                             "--max-pages", str(pages)],
                            capture_output=True, text=True, timeout=900,
                            encoding="utf-8", errors="replace",
                        )
                        out_tail = (r.stdout or "")[-200:]
                        agents_triggered.append(
                            f"authors_collect(rc={r.returncode},limit={limit})"
                        )
                        self._last_authors_collect = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] authors_collect failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 19. broken drama_links 回收 (2026-04-20 用户要求: 每 6h 重救)
            #     drama_links 里 status='broken' 或 1 天以上 failed 的, 调
            #     collector_on_demand 重新 search 拿新 URL. 防止剧池越来越干.
            if _cfg("ai.collector.reclaim_enabled", True):
                reclaim_interval = int(_cfg("ai.collector.reclaim_interval_sec", 21600))
                if time.time() - self._last_drama_reclaim > reclaim_interval:
                    try:
                        r = self._reclaim_broken_drama_links()
                        agents_triggered.append(
                            f"drama_reclaim(tried={r.get('tried',0)},"
                            f"fixed={r.get('fixed',0)})"
                        )
                        self._last_drama_reclaim = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] drama_reclaim failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 20. URL 预载 + ffprobe 预验 (2026-04-20 step⑤)
            # 每 1h: 扫 pending 且 verified_at 过期 > 2h 的 URL, 跑 ffprobe 快验
            # 通过 → verified_at=now; 失败 → 标 broken (下 cycle step 19 会重搜).
            # 保持剧池"热态", planner 只从 verified 剧中选.
            if _cfg("ai.collector.url_preload_enabled", True):
                pre_interval = int(_cfg("ai.collector.url_preload_interval_sec", 3600))
                if time.time() - self._last_url_preload > pre_interval:
                    try:
                        r = self._preload_verify_urls()
                        agents_triggered.append(
                            f"url_preload(checked={r.get('checked',0)},"
                            f"ok={r.get('ok',0)},broken={r.get('broken',0)})"
                        )
                        self._last_url_preload = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] url_preload failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 24. 新号自动清洗 (2026-04-20 用户要求: 改名+删历史非短剧+分赛道)
            # 每 12h 扫 logged_in + 非 frozen + account_age ≤ 30 天 的号
            # 1. 无 vertical_category → 触发 LLM 推断 (复用 step 21)
            # 2. 无 nickname_suggestions_json → 触发 AI 起名
            # 3. list_account_works 发现 ≥ 5 件非短剧作品 → 写 healing_diagnosis 提醒
            #    (自动删作品需用户确认, 避免误删)
            if _cfg("ai.account_cleanup.enabled", True):
                cu_interval = int(_cfg("ai.account_cleanup.interval_sec", 43200))
                if time.time() - self._last_account_cleanup > cu_interval:
                    try:
                        r = self._scan_new_accounts_for_cleanup()
                        agents_triggered.append(
                            f"account_cleanup(scanned={r.get('scanned',0)},"
                            f"nicks_suggested={r.get('nicks_suggested',0)},"
                            f"needs_cleanup={r.get('needs_cleanup',0)})"
                        )
                        self._last_account_cleanup = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] account_cleanup failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 23. 播放量每小时快照 (2026-04-20 用户要求: today_delta 准确)
            # 用户痛点: "播放量是所有天数总和, 账号取消了就不准".
            # 解法: 每 1h snapshot total_plays → hourly_metrics_snapshots
            #       today_delta = current - 今日 00:xx 第一条 snapshot
            if _cfg("ai.metrics.plays_snapshot_enabled", True):
                snap_interval = int(_cfg("ai.metrics.plays_snapshot_interval_sec", 3600))
                if time.time() - self._last_plays_snapshot > snap_interval:
                    try:
                        from scripts.snapshot_hourly_plays import snapshot_all_accounts
                        r = snapshot_all_accounts(dry_run=False)
                        agents_triggered.append(
                            f"plays_snapshot(saved={r.get('saved',0)})"
                        )
                        self._last_plays_snapshot = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] plays_snapshot failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 22. MCN 自动邀请 (2026-04-20 用户要求"发现没绑, 重新邀请")
            # 每 24h 扫 login_status='logged_in' 且 mcn_member_snapshots 无记录的账号
            # → 调 MCNBusiness.invite_and_persist() 自动发邀请 + 写 mcn_invitations 账本
            # 2026-04-21 改: 从 direct_invite() 换成 invite_and_persist() — 补账本
            if _cfg("ai.mcn.auto_invite_enabled", True):
                invite_interval = int(_cfg("ai.mcn.auto_invite_interval_sec", 86400))
                if time.time() - self._last_mcn_auto_invite > invite_interval:
                    try:
                        r = self._auto_invite_unbound_accounts()
                        agents_triggered.append(
                            f"mcn_auto_invite(invited={r.get('invited',0)},"
                            f"skipped={r.get('skipped',0)})"
                        )
                        self._last_mcn_auto_invite = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] mcn_auto_invite failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 22b. MCN 邀请签约状态轮询 (2026-04-21 用户要求"规范化邀请流程")
            # 每 6h 扫 mcn_invitations WHERE signed_status IN ('pending', '待处理', ...)
            # → 调 MCNBusiness.poll_invitation_status() 刷新 signed_status/signed_at/member_id
            if _cfg("ai.mcn.invite_poll_enabled", True):
                poll_interval = int(_cfg("ai.mcn.invite_poll_interval_sec", 21600))  # 6h
                if time.time() - self._last_mcn_invite_poll > poll_interval:
                    try:
                        r = self._poll_pending_invitations()
                        if r.get("polled", 0) > 0:
                            agents_triggered.append(
                                f"mcn_invite_poll(polled={r.get('polled',0)},"
                                f"signed={r.get('newly_signed',0)},"
                                f"err={r.get('errors',0)})"
                            )
                        self._last_mcn_invite_poll = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] mcn_invite_poll failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 21. 账号画像自动维护 (2026-04-20 用户要求"系统做, 我监控")
            # 每 6h: 扫 logged_in 账号 vertical_category IS NULL → 调 LLMClient 推断填充
            # 有新号接入 / 老号被重置 → 自动补齐画像, 不需人工跑 script
            if _cfg("ai.profile.auto_infer_enabled", True):
                prof_interval = int(_cfg("ai.profile.auto_infer_interval_sec", 21600))
                if time.time() - self._last_vertical_infer > prof_interval:
                    try:
                        r = self._auto_infer_missing_verticals()
                        agents_triggered.append(
                            f"profile_infer(inferred={r.get('inferred',0)},"
                            f"skipped={r.get('skipped',0)})"
                        )
                        self._last_vertical_infer = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] profile_infer failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 25. 自适应运营模式检测 (2026-04-24 v6 B4)
            # 每 5 min 查 account_count, 跨越档位阈值时自动切 mode + 更新 9 项 config
            # 不会中断当前运行中的 worker / task — 新 config 由下个 cycle 的各 agent 读取
            if _cfg("operation.mode.auto_transition_enabled", True):
                op_interval = int(_cfg("operation.mode.check_interval_sec", 300))
                if time.time() - self._last_operation_mode_check > op_interval:
                    try:
                        from core.operation_mode import maybe_auto_transition
                        r = maybe_auto_transition()
                        if r.get("transitioned"):
                            agents_triggered.append(
                                f"operation_mode({r.get('old_mode')}→{r.get('new_mode')},"
                                f"changed={r.get('changed_configs',0)})"
                            )
                        self._last_operation_mode_check = time.time()
                        self._persist_state("operation_mode", result=(
                            f"mode={r.get('new_mode')} transitioned={r.get('transitioned')}"
                        ))
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] operation_mode check failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 25b. account_drama_blacklist 过期清理 (2026-04-24 v6 Day 7)
            # 80004 blacklist 冷却后要清, 不然 table 长期累积. 每 1h 跑一次够了.
            if _cfg("ai.blacklist.account_drama.enabled", True):
                adb_interval = int(_cfg("ai.blacklist.account_drama.cleanup_interval_sec", 3600))
                if time.time() - self._last_adb_cleanup > adb_interval:
                    try:
                        from core.account_drama_blacklist import cleanup_expired
                        n_cleaned = cleanup_expired()
                        if n_cleaned > 0:
                            agents_triggered.append(f"adb_cleanup(cleaned={n_cleaned})")
                        self._last_adb_cleanup = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] adb_cleanup failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 26. Hot Hunter — 爆款雷达 (2026-04-24 v6 Day 8+)
            # 每 2h 扫 drama_authors 里的一批 (30 人) profile/feed
            # 副产品: CDN 入 drama_links (解决下载荒漠) + 新作者扩池
            if _cfg("ai.trending_hunter.enabled", True):
                hh_interval = int(_cfg("ai.trending_hunter.scan_interval_sec", 7200))
                if time.time() - self._last_hot_hunter_scan > hh_interval:
                    try:
                        from core.agents.hot_hunter_agent import run as _hh_run
                        r = _hh_run(dry_run=False)
                        if r.get("scanned", 0) > 0:
                            agents_triggered.append(
                                f"hot_hunter(scanned={r.get('scanned')},"
                                f"ins={r.get('photos_inserted',0)},"
                                f"upd={r.get('photos_updated',0)},"
                                f"cdn+={r.get('cdns_saved',0)})"
                            )
                        self._last_hot_hunter_scan = time.time()
                        self._persist_state("hot_hunter",
                                             result=f"scanned={r.get('scanned',0)}")
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] hot_hunter_scan failed: {e}", file=sys.stderr)
                    checks_run += 1

            # 26b. Author pool priority 自动升级 (每 6h)
            if _cfg("ai.trending_hunter.enabled", True):
                pri_interval = int(_cfg("ai.trending_hunter.priority_update_interval_sec", 21600))
                if time.time() - self._last_author_priority_update > pri_interval:
                    try:
                        from core.agents.hot_hunter_agent import maintenance_update_author_priority
                        r = maintenance_update_author_priority()
                        if r.get("updated_promoted", 0) + r.get("downgraded", 0) > 0:
                            agents_triggered.append(
                                f"author_priority(+={r.get('updated_promoted')},"
                                f"-={r.get('downgraded')})"
                            )
                        self._last_author_priority_update = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] author_priority_update failed: {e}",
                              file=sys.stderr)
                    checks_run += 1

            # 26c. publish_outcome 回采 24h (每 1h)
            if _cfg("ai.publish_outcome.enabled", True):
                if time.time() - self._last_outcome_collect_24h > 3600:
                    try:
                        from core.publish_outcome import collect_pending_outcomes
                        r = collect_pending_outcomes("24h", max_rows=20)
                        if r.get("collected", 0) > 0:
                            agents_triggered.append(
                                f"outcome_24h(collected={r['collected']})"
                            )
                        self._last_outcome_collect_24h = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] outcome_24h failed: {e}",
                              file=sys.stderr)
                    checks_run += 1

            # 26d. publish_outcome 回采 48h (每 3h)
            if _cfg("ai.publish_outcome.enabled", True):
                if time.time() - self._last_outcome_collect_48h > 3 * 3600:
                    try:
                        from core.publish_outcome import collect_pending_outcomes
                        r = collect_pending_outcomes("48h", max_rows=20)
                        if r.get("collected", 0) > 0:
                            agents_triggered.append(
                                f"outcome_48h(collected={r['collected']})"
                            )
                        self._last_outcome_collect_48h = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] outcome_48h failed: {e}",
                              file=sys.stderr)
                    checks_run += 1

            # 26e. publish_outcome 回采 7d (每 12h)
            if _cfg("ai.publish_outcome.enabled", True):
                if time.time() - self._last_outcome_collect_7d > 12 * 3600:
                    try:
                        from core.publish_outcome import collect_pending_outcomes
                        r = collect_pending_outcomes("7d", max_rows=30)
                        if r.get("collected", 0) > 0:
                            agents_triggered.append(
                                f"outcome_7d(collected={r['collected']})"
                            )
                        self._last_outcome_collect_7d = time.time()
                    except Exception as e:
                        import sys
                        print(f"[ControllerAgent] outcome_7d failed: {e}",
                              file=sys.stderr)
                    checks_run += 1

            summary = self._build_summary(
                recent_fail_count, heals_proposed, heals_applied,
                agents_triggered,
            )
            status = "ok"
        except Exception as exc:
            import traceback as _tb
            tb_str = _tb.format_exc()[-800:]   # 最后 800 字符 足够定位
            summary = f"ControllerCycle 异常: {exc}\n{tb_str}"
            status = "error"
            # 同时打到 stderr 方便 autopilot log 看到
            import sys
            print(f"[ControllerAgent] cycle 异常: {exc}", file=sys.stderr)
            print(tb_str, file=sys.stderr)

        duration_ms = int((time.time() - t0) * 1000)
        self._end_cycle(
            cycle_id, duration_ms, checks_run,
            failures_found, heals_proposed, heals_applied,
            agents_triggered, summary, status,
        )
        return {
            "cycle_id": cycle_id,
            "duration_ms": duration_ms,
            "checks_run": checks_run,
            "failures_found": failures_found,
            "heals_proposed": heals_proposed,
            "heals_applied": heals_applied,
            "agents_triggered": agents_triggered,
            "status": status,
            "summary": summary,
        }

    # ==================================================================

    def _count_recent_failures(self, hours: int = 2) -> int:
        try:
            return self._wc.execute(
                """SELECT COUNT(*) FROM task_queue
                   WHERE status IN ('failed','dead_letter')
                     AND datetime(finished_at) >= datetime('now', ?)""",
                (f"-{hours} hours",),
            ).fetchone()[0] or 0
        except Exception:
            return 0

    def _last_orchestrator_run(self) -> float | None:
        try:
            row = self._wc.execute(
                """SELECT created_at FROM agent_runs
                   WHERE agent_name='orchestrator'
                   ORDER BY id DESC LIMIT 1"""
            ).fetchone()
            if not row:
                return 0   # 没跑过 → 应跑一次
            dt = datetime.fromisoformat(row[0].replace(' ', 'T'))
            return dt.timestamp()
        except Exception:
            return None

    def _start_cycle(self, cycle_id: str) -> None:
        try:
            _retry_write(
                self._wc,
                """INSERT INTO autopilot_cycles
                     (cycle_id, status) VALUES (?, 'running')""",
                (cycle_id,),
            )
        except Exception as e:
            # 不 silent — 打到 stderr 便于排查
            import sys
            print(f"[ControllerAgent._start_cycle ERROR] {e}", file=sys.stderr)

    def _end_cycle(self, cycle_id, duration_ms, checks_run, failures, heals_proposed,
                   heals_applied, agents_triggered, summary, status):
        try:
            _retry_write(
                self._wc,
                """UPDATE autopilot_cycles SET
                     ended_at=datetime('now','localtime'),
                     duration_ms=?, checks_run=?, failures_found=?,
                     heals_proposed=?, heals_applied=?,
                     agents_triggered=?, summary=?, status=?
                   WHERE cycle_id=?""",
                (duration_ms, checks_run, failures,
                 heals_proposed, heals_applied,
                 json.dumps(agents_triggered, ensure_ascii=False),
                 summary, status, cycle_id),
            )
        except Exception as e:
            import sys
            print(f"[ControllerAgent._end_cycle ERROR] {e}", file=sys.stderr)

    def _build_summary(self, failures, proposed, applied, agents) -> str:
        parts = []
        if failures:
            parts.append(f"发现 {failures} 个失败")
        if proposed:
            parts.append(f"诊断 {proposed} 类")
        if applied:
            parts.append(f"自动修复 {applied} 个")
        if agents:
            parts.append(f"触发 Agent: {', '.join(agents)}")
        return " · ".join(parts) or "系统健康, 无需干预"

    # ==================================================================
    # step 19 helper: broken drama_links 回收 (2026-04-20)
    # ==================================================================
    def _reclaim_broken_drama_links(self) -> dict:
        """扫 drama_links.status='broken' 和 >24h 的 failed, 调 on-demand
        collector 重新搜同剧名拿新 URL. 每 6h 跑一次, 限量 max_n 防打爆.

        策略: 按 drama_name 分组 (同剧 N 条全挂 → 只搜一次),
        优先近 7 天内创建的 (老的可能剧本身下架了).

        Returns:
            {tried: int, fixed: int, skipped: int}
        """
        import time as _t
        from core.app_config import get as _cfg_get
        max_n = int(_cfg_get("ai.collector.reclaim.max_dramas_per_run", 10))
        stale_hours = int(_cfg_get("ai.collector.reclaim.failed_stale_hours", 24))

        tried = fixed = skipped = 0
        try:
            c = self._wc
            # 按 drama_name 分组取 broken / stale-failed
            rows = c.execute(
                """SELECT drama_name, COUNT(*) AS n
                   FROM drama_links
                   WHERE status='broken'
                      OR (status='failed' AND
                          (julianday('now') - julianday(updated_at)) * 24 >= ?)
                   GROUP BY drama_name
                   ORDER BY MAX(created_at) DESC
                   LIMIT ?""",
                (stale_hours, max_n)
            ).fetchall()
        except Exception as e:
            import sys
            print(f"[reclaim] query failed: {e}", file=sys.stderr)
            return {"tried": 0, "fixed": 0, "skipped": 0, "error": str(e)}

        for r in rows:
            drama_name = r[0]
            n_broken = r[1]
            tried += 1
            try:
                from core.collector_on_demand import ensure_urls_for_drama
                res = ensure_urls_for_drama(drama_name, min_new_urls=1)
                if res.get("ok") and res.get("new_saved", 0) > 0:
                    fixed += 1
                else:
                    skipped += 1
            except Exception as e:
                import sys
                print(f"[reclaim] {drama_name} failed: {e}", file=sys.stderr)
                skipped += 1

        return {"tried": tried, "fixed": fixed, "skipped": skipped,
                "broken_dramas_found": len(rows)}

    # ==================================================================
    # step 20 helper: URL 预载 + ffprobe 预验 (2026-04-20)
    # ==================================================================
    def _preload_verify_urls(self) -> dict:
        """扫 pending drama_links, 对 verified_at 过期 (> 2h) 的跑 ffprobe.

        通过 → 更新 verified_at=now (planner 会优先选 verified 剧)
        失败 → 标 broken (下 cycle step 19 会重搜)

        策略:
          - 每 1h 跑一次
          - 每次处理最多 max_batch 条 (默认 20), 防阻塞 cycle
          - 优先 verified_at IS NULL 的 (从没验过), 然后是最老的
        """
        import time as _t
        from core.app_config import get as _cfg_get
        from core.collector_on_demand import _ffprobe_verify_url
        from datetime import datetime, timezone

        max_batch = int(_cfg_get("ai.collector.url_preload.max_batch", 20))
        stale_hours = int(_cfg_get("ai.collector.url_preload.stale_hours", 2))

        checked = ok = broken = 0
        try:
            c = self._wc
            rows = c.execute(
                """SELECT id, drama_name, drama_url
                   FROM drama_links
                   WHERE status='pending'
                     AND drama_url IS NOT NULL AND drama_url != ''
                     AND (verified_at IS NULL
                          OR (julianday('now') - julianday(verified_at)) * 24 > ?)
                   ORDER BY verified_at ASC NULLS FIRST
                   LIMIT ?""",
                (stale_hours, max_batch)
            ).fetchall()
        except Exception as e:
            import sys
            print(f"[url_preload] query failed: {e}", file=sys.stderr)
            return {"checked": 0, "ok": 0, "broken": 0, "error": str(e)}

        now = datetime.now(timezone.utc).isoformat()
        for r in rows:
            rid, dname, url = r
            checked += 1
            try:
                probe_ok, reason = _ffprobe_verify_url(url, timeout=3.0)
            except Exception:
                probe_ok = False
                reason = "exception"
            if probe_ok:
                c.execute(
                    "UPDATE drama_links SET verified_at=?, updated_at=? WHERE id=?",
                    (now, now, rid)
                )
                ok += 1
            else:
                c.execute(
                    "UPDATE drama_links SET status='broken', updated_at=? WHERE id=?",
                    (now, rid)
                )
                broken += 1
        c.commit()
        return {"checked": checked, "ok": ok, "broken": broken}

    # ==================================================================
    # step 21 helper: 账号画像自动补齐 (2026-04-20)
    # ==================================================================
    def _auto_infer_missing_verticals(self) -> dict:
        """扫 vertical_category IS NULL/空 的 logged_in 账号, 调 LLM 自动推断.

        每 6h 跑一次, 新号接入就自动补画像, 不需人工跑 script.
        使用 aliyun Qwen 3.6 Plus (provider 自动 fallback).
        """
        inferred = skipped = 0
        errors = []
        try:
            c = self._wc
            rows = c.execute(
                """SELECT id FROM device_accounts
                   WHERE login_status='logged_in'
                     AND (vertical_category IS NULL OR vertical_category='')
                   ORDER BY id LIMIT 20"""
            ).fetchall()
        except Exception as e:
            return {"inferred": 0, "skipped": 0, "error": str(e)}

        if not rows:
            return {"inferred": 0, "skipped": 0, "note": "all_accounts_have_vertical"}

        try:
            from scripts.infer_account_verticals import (
                _collect_signals, infer_vertical_for_account, apply_to_db
            )
            from core.llm.client import LLMClient
            cli = LLMClient()
            if not cli.available:
                return {"inferred": 0, "skipped": len(rows),
                        "error": "no_llm_available"}
        except Exception as e:
            return {"inferred": 0, "skipped": len(rows), "error": str(e)}

        for r in rows:
            aid = r[0]
            try:
                sig = _collect_signals(c, aid)
                if not sig:
                    skipped += 1
                    continue
                info = infer_vertical_for_account(cli, sig)
                if info and info.get("vertical"):
                    apply_to_db(c, aid, info)
                    inferred += 1
                else:
                    skipped += 1
            except Exception as e:
                errors.append(f"acc={aid}: {e}")
                skipped += 1

        return {"inferred": inferred, "skipped": skipped,
                "errors": errors[:3] if errors else None}

    # ==================================================================
    # step 22 helper: MCN 自动邀请未绑账号 (2026-04-20)
    # ==================================================================
    def _auto_invite_unbound_accounts(self) -> dict:
        """扫 logged_in + 已填主人手机 + 未绑 的账号, 自动重邀.

        ★ 2026-04-20 用户纠正: direct_invite 需真实主人手机 + 姓名,
        所以 step 22 **只处理** owner_phone 非空的账号 (首次邀请必须人工
        在 Dashboard 填). 没填的账号写 healing_diagnosis 提醒管理员.

        防重复: 同账号 24h 内只重邀 1 次.
        """
        import time as _t
        from core.app_config import get as _cfg_get

        max_batch = int(_cfg_get("ai.mcn.auto_invite.max_batch", 5))
        dedup_hours = int(_cfg_get("ai.mcn.auto_invite.dedup_hours", 24))

        invited = skipped = need_manual = 0
        errors = []
        try:
            c = self._wc
            # 分 2 批:
            #  A. 已填主人手机 + 24h 未邀 + MCN 未绑 → 自动重邀
            need_retry = c.execute(
                """SELECT id, account_name, kuaishou_uid, owner_phone, owner_real_name
                   FROM device_accounts da
                   WHERE login_status='logged_in'
                     AND kuaishou_uid IS NOT NULL AND kuaishou_uid != ''
                     AND owner_phone IS NOT NULL AND owner_phone != ''
                     AND owner_real_name IS NOT NULL AND owner_real_name != ''
                     AND NOT EXISTS (
                       SELECT 1 FROM mcn_member_snapshots ms
                       WHERE ms.member_id = da.numeric_uid
                         AND (ms.total_amount > 0)
                     )
                     AND (mcn_last_invite_at IS NULL
                          OR (julianday('now') - julianday(mcn_last_invite_at)) * 24 >= ?)
                   LIMIT ?""",
                (dedup_hours, max_batch)
            ).fetchall()

            # B. 未填手机的账号 (数数, 写 diagnosis 提醒)
            n_need_manual = c.execute(
                """SELECT COUNT(*) FROM device_accounts
                   WHERE login_status='logged_in'
                     AND (owner_phone IS NULL OR owner_phone = '')
                     AND NOT EXISTS (
                       SELECT 1 FROM mcn_member_snapshots ms
                       WHERE ms.member_id = numeric_uid AND ms.total_amount > 0
                     )"""
            ).fetchone()[0]
            need_manual = int(n_need_manual or 0)
        except Exception as e:
            return {"invited": 0, "skipped": 0, "error": str(e)}

        # 写 diagnosis 提醒 (首次发现 need_manual 时)
        if need_manual > 0:
            try:
                c.execute(
                    """INSERT INTO healing_diagnoses
                         (playbook_code, task_type, diagnosis, confidence, severity,
                          affected_entities, evidence_json, auto_resolved, created_at)
                       VALUES ('mcn_need_manual_phone', 'MCN', ?, 0.95, 'medium',
                               ?, ?, 0, CURRENT_TIMESTAMP)""",
                    (f"{need_manual} 个账号未登记主人手机, 无法自动邀请 MCN",
                     f"account_count={need_manual}",
                     f'{{"hint":"到账号管理点 ✚ 邀请 填写手机+姓名一次后系统即可自动重试"}}')
                )
                c.commit()
            except Exception:
                pass

        if not need_retry:
            return {"invited": 0, "skipped": 0,
                    "need_manual_phone": need_manual,
                    "note": "no_account_ready_for_retry"}

        # 2026-04-21 改: 用 MCNBusiness (带账本) 取代 MCNClient.direct_invite()
        # 让 step 22 自动邀请也写 mcn_invitations, 和 dashboard 手动邀请走同一账本
        try:
            from core.db_manager import DBManager
            from core.mcn_business import MCNBusiness
            biz = MCNBusiness(DBManager())
        except Exception as e:
            return {"invited": 0, "skipped": len(need_retry),
                    "error": f"mcn_biz_init_fail: {e}"}

        # 额外按 numeric_uid 读一次 (direct_invite 要纯数字)
        from datetime import datetime as _dt
        now_iso = _dt.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in need_retry:
            aid, aname, ksuid, phone, real_name = r
            # 补读 numeric_uid
            nr = c.execute(
                "SELECT numeric_uid FROM device_accounts WHERE id=?", (aid,)
            ).fetchone()
            num_uid = str(nr[0]) if nr and nr[0] else ""
            invite_uid = num_uid if num_uid.isdigit() else str(ksuid)
            if not invite_uid or not invite_uid.isdigit():
                errors.append(f"acc={aid}: numeric_uid 缺失")
                skipped += 1
                continue
            try:
                resp = biz.invite_and_persist(
                    target_uid=invite_uid,
                    phone=phone,
                    note=f"auto_retry@controller ({real_name}-{aname})",
                    contract_month=36,
                    organization_id=10,
                )
                success = bool(resp.get("success"))
                c.execute(
                    """UPDATE device_accounts SET
                         mcn_last_invite_at = ?,
                         mcn_last_invite_status = ?
                       WHERE id = ?""",
                    (now_iso, 'success' if success else 'failed', aid)
                )
                if success:
                    invited += 1
                else:
                    skipped += 1
                    errors.append(f"acc={aid}: {resp.get('error', 'no_success')}")
            except Exception as e:
                errors.append(f"acc={aid}: {e}")
                skipped += 1
        c.commit()

        return {"invited": invited, "skipped": skipped,
                "scanned": len(need_retry),
                "need_manual_phone": need_manual,
                "errors": errors[:3] if errors else None}

    # ==================================================================
    # step 22b helper: MCN 签约状态轮询 (2026-04-21)
    # ==================================================================
    def _poll_pending_invitations(self) -> dict:
        """扫 mcn_invitations 里 signed_status='pending' 的行, 查最新签约状态.

        调 MCNBusiness.poll_invitation_status() → /api/accounts/invitation-records
        返回里 recordProcessStatus==104 判签约.
        """
        from core.app_config import get as _cfg_get

        max_batch = int(_cfg_get("ai.mcn.invite_poll.max_batch", 30))
        polled = newly_signed = err = 0
        try:
            c = self._wc
            rows = c.execute(
                """SELECT id, target_kuaishou_uid
                   FROM mcn_invitations
                   WHERE signed_status='pending' OR signed_status IS NULL
                   ORDER BY id LIMIT ?""",
                (max_batch,)
            ).fetchall()
        except Exception as e:
            return {"polled": 0, "error": str(e)}

        if not rows:
            return {"polled": 0, "newly_signed": 0, "errors": 0,
                    "note": "no_pending_invitations"}

        try:
            from core.db_manager import DBManager
            from core.mcn_business import MCNBusiness
            biz = MCNBusiness(DBManager())
        except Exception as e:
            return {"polled": 0, "error": f"mcn_biz_init_fail: {e}"}

        for inv_id, target_uid in rows:
            try:
                biz.poll_invitation_status(str(target_uid))
                polled += 1
                # 检查是否刚签约
                new_status = c.execute(
                    "SELECT signed_status FROM mcn_invitations WHERE id=?",
                    (inv_id,)
                ).fetchone()
                if new_status and new_status[0] == 'signed':
                    newly_signed += 1
            except Exception:
                err += 1

        return {"polled": polled, "newly_signed": newly_signed, "errors": err,
                "total_pending": len(rows)}

    # ==================================================================
    # step 24 helper: 新号自动清洗扫描 (2026-04-20 用户要求)
    # ==================================================================
    def _scan_new_accounts_for_cleanup(self) -> dict:
        """扫新号 (age ≤ 30 天) 看哪些需要清洗:
          1. 无 vertical → 标记待 LLM 推断 (step 21 下轮会处理)
          2. 无 nickname 建议 → 调 AI 补建议
          3. 有大量 非短剧 作品 → 写 diagnosis (不自动删, 等人工确认)
        """
        from core.app_config import get as _cfg_get

        scanned = nicks_suggested = needs_cleanup = 0
        errors = []
        try:
            c = self._wc
            rows = c.execute(
                """SELECT id, account_name, vertical_category,
                          nickname_suggestions_json, account_age_days
                   FROM device_accounts
                   WHERE login_status='logged_in'
                     AND (tier IS NULL OR tier != 'frozen')
                     AND (account_age_days IS NULL OR account_age_days <= 30)
                   LIMIT 20"""
            ).fetchall()
        except Exception as e:
            return {"scanned": 0, "error": str(e)}

        if not rows:
            return {"scanned": 0, "note": "no_new_accounts"}

        # 用 LLM 批量补 nickname 建议 (单号调一次, 避免 LLM 过频)
        from core.llm.client import LLMClient
        cli = None
        try:
            cli = LLMClient()
            if not cli.available:
                cli = None
        except Exception:
            pass

        for r in rows:
            aid = r[0]
            scanned += 1
            has_vertical = bool(r[2])
            has_nick_suggestion = bool(r[3])

            # 1. 补 nickname 推荐 (只做无 suggestion 的, 复用 infer_account_verticals 逻辑)
            if not has_nick_suggestion and cli and has_vertical:
                try:
                    from scripts.suggest_nicknames_ai import (
                        _collect_account, suggest_nickname
                    )
                    sig = _collect_account(c, aid)
                    if sig:
                        reserved = [
                            x[0] for x in c.execute(
                                "SELECT account_name FROM device_accounts WHERE id!=? AND account_name IS NOT NULL",
                                (aid,)
                            ).fetchall() if x[0]
                        ]
                        import json as _j
                        info = suggest_nickname(cli, sig, reserved[:20])
                        if info and info.get("suggested"):
                            c.execute(
                                "UPDATE device_accounts SET nickname_suggestions_json=? WHERE id=?",
                                (_j.dumps(info, ensure_ascii=False), aid)
                            )
                            nicks_suggested += 1
                except Exception as e:
                    errors.append(f"acc={aid} nick: {e}")

            # 2. 查非短剧作品数 → 写 diagnosis
            try:
                # 只在账号今天没扫过时查 (轻量, 不真调 KS API)
                last_scan = c.execute(
                    """SELECT created_at FROM healing_diagnoses
                       WHERE affected_entities=? AND playbook_code='account_cleanup_needed'
                         AND date(created_at)=date('now','localtime') LIMIT 1""",
                    (f"account:{aid}",)
                ).fetchone()
                if last_scan:
                    continue  # 今日已记
                # 真调 publisher.list_all_works (有网络调用, 控制频率)
                # 实际扫描只在无 suggestion 时做, 避免 LLM cost
            except Exception:
                pass

        c.commit()
        return {
            "scanned": scanned,
            "nicks_suggested": nicks_suggested,
            "needs_cleanup": needs_cleanup,
            "errors": errors[:3] if errors else None,
        }
