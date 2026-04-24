# -*- coding: utf-8 -*-
"""运营看板 (Streamlit) — 把 B+A+D+E+F 产出的数据可视化.

启动:
    streamlit run dashboard/streamlit_app.py --server.port 8501

3 个页面 (侧边栏切换):
    🏠 总览 — 今日 plan / 账号 tier 分布 / 近 7 天收益 / 系统健康
    📋 任务 — task_queue 实时 / plan_items 跟进 / 失败列表
    🩺 自愈 — healing_diagnoses / rule_proposals 审批 / playbook 效果

设计原则:
    - 只读 (除 approve 按钮), 不直接改业务数据
    - 5 秒 auto-refresh (可配)
    - 大屏友好, 移动端降级
"""
from __future__ import annotations

import json
import sqlite3
import sys
from datetime import datetime, timedelta
from pathlib import Path

# 保证 core/ 可导入
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import streamlit as st

# ══════════════════════════════════════════════════════════════
# 初始化
# ══════════════════════════════════════════════════════════════

st.set_page_config(
    page_title="KS AI 矩阵运营看板",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="expanded",
)

from core.config import DB_PATH  # noqa: E402


@st.cache_resource
def _get_conn():
    """进程级 DB 连接 (Streamlit cache_resource)."""
    c = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
    c.row_factory = sqlite3.Row
    return c


def _query(sql: str, params: tuple = ()) -> pd.DataFrame:
    conn = _get_conn()
    return pd.read_sql_query(sql, conn, params=params)


def _query_one(sql: str, params: tuple = ()) -> dict | None:
    conn = _get_conn()
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None


def _sql_exec(sql: str, params: tuple = ()) -> int:
    conn = _get_conn()
    cur = conn.execute(sql, params)
    conn.commit()
    return cur.lastrowid or cur.rowcount


# ══════════════════════════════════════════════════════════════
# 中文映射 (§27 用户需求: 任务队列 WEB 界面全中文)
# ══════════════════════════════════════════════════════════════

# task_type 中文
TASK_TYPE_CN = {
    "PUBLISH": "🎬 发布视频",
    "PUBLISH_BURST": "🔥 爆款跟发",
    "PUBLISH_DRAMA": "🎬 发布短剧",
    "PUBLISH_A": "🎬 发布 (A)",
    "COOKIE_REFRESH": "🍪 刷新 Cookie",
    "FREEZE_ACCOUNT": "❄️ 冻结账号",
    "UNFREEZE_ACCOUNT": "🔓 解冻账号",
    "QUOTA_BACKFILL": "📥 配额回补",
    "LIBRARY_CLEAN": "🧹 清理剧库",
    "MCN_TOKEN": "🔑 刷新 MCN Token",
}

# task_source 中文
TASK_SOURCE_CN = {
    "planner": "📋 常规计划",
    "burst": "🔥 爆款响应",
    "experiment": "🧪 A/B 实验",
    "maintenance": "🔧 维护风控",
    "self_healing": "🩺 自愈修复",
    "manual": "👤 手工触发",
}

# status 中文
STATUS_CN = {
    "pending": "⏸ 待跑",
    "queued": "📥 排队中",
    "running": "⏳ 运行中",
    "success": "✅ 成功",
    "completed": "✅ 已完成",
    "failed": "❌ 失败",
    "dead_letter": "💀 终死",
    "cancelled": "🚫 已取消",
    "blacklisted": "⛔ 拉黑",
    "retry_scheduled": "🔄 等重试",
}

# tier 中文
TIER_CN = {
    "new": "🆕 新号",
    "testing": "🧪 测试",
    "warming_up": "🌡 养号",
    "established": "⭐ 成熟",
    "viral": "🚀 爆款",
    "frozen": "❄️ 冻结",
}

# 发布类 task_type (用于拆分)
PUBLISH_TASK_TYPES = ("PUBLISH", "PUBLISH_BURST", "PUBLISH_DRAMA", "PUBLISH_A")


def _tt_cn(t: str | None) -> str:
    """task_type 英 → 中."""
    if not t:
        return "(未知)"
    return TASK_TYPE_CN.get(t, t)


def _ts_cn(s: str | None) -> str:
    """task_source 英 → 中."""
    if not s:
        return "📋 常规计划"  # 默认
    return TASK_SOURCE_CN.get(s, s)


def _st_cn(s: str | None) -> str:
    """status 英 → 中."""
    if not s:
        return "(未知)"
    return STATUS_CN.get(s, s)


def _tier_cn(t: str | None) -> str:
    """tier 英 → 中."""
    if not t:
        return "—"
    return TIER_CN.get(t, t)


# ══════════════════════════════════════════════════════════════
# 边栏 + 刷新
# ══════════════════════════════════════════════════════════════

with st.sidebar:
    st.title("🎬 KS 矩阵")
    page = st.radio(
        "页面",
        ["🏠 总览", "📋 任务", "📦 任务监控", "🩺 自愈", "💎 收益",
         "👤 账号详情", "🎬 剧详情", "🔍 全局搜索",
         "🛠️ 批量操作", "📊 导出", "✉️ 邀请管理",
         "🎨 Qitian", "🔀 去重组合", "⚙️ 配置",
         "💎 候选池",         # ★ 2026-04-23 §31
         "🔗 剧库健康",       # ★ 2026-04-22 §26.17
         "🚦 运营模式",       # ★ 2026-04-24 v6 Day 5-D: operation_mode 5 档可视化 + 手动切
         "🔌 熔断监控"],     # ★ 2026-04-24 v6 Day 5-D: MCN breaker A/B + transitions
        label_visibility="collapsed",
    )
    st.divider()
    auto_refresh_sec = st.selectbox(
        "自动刷新",
        [0, 5, 10, 30, 60],
        format_func=lambda x: "关闭" if x == 0 else f"{x} 秒",
        index=0,   # ★ 2026-04-24: 默认关闭 (本地 DB 刷新太频率打扰)
    )
    if st.button("🔄 立即刷新", help="重新查本地 DB (不触网)"):
        st.rerun()

    # 🌐 MCN 手动全量同步 (所有账号, 任一页面都可用)
    st.divider()
    st.caption("**🌐 MCN 服务器同步**")

    # freshness 显示
    _lr = _query_one(
        "SELECT config_value FROM app_config WHERE config_key='sync.ks_names.last_run_at'"
    )
    _iv = _query_one(
        "SELECT config_value FROM app_config WHERE config_key='sync.ks_names.interval_sec'"
    )
    _last = _lr.get("config_value") if _lr else None
    _interval = int(_iv.get("config_value")) if _iv else 43200
    if _last:
        try:
            _age = (datetime.now() - datetime.fromisoformat(_last)).total_seconds()
            if _age < 60:
                _fm = f"✅ {int(_age)}秒前"
            elif _age < 3600:
                _fm = f"✅ {int(_age/60)}分钟前"
            elif _age < 86400:
                _fm = f"{'⏰' if _age > _interval else '✅'} {int(_age/3600)}小时前"
            else:
                _fm = f"⏰ {int(_age/86400)}天前"
            st.caption(f"上次: {_fm}")
        except Exception:
            st.caption(f"上次: {_last}")
    else:
        st.caption("上次: 从未")
    st.caption(f"自动间隔: {_interval//3600}h")

    if st.button("🌐 立即同步所有账号",
                  help="立刻查 MCN 服务器, 回填所有 12 账号的 kuaishou_name + signed_status"):
        with st.spinner("正在查 MCN..."):
            try:
                from scripts.sync_kuaishou_names import run_sync
                _stats = run_sync(dry_run=False, verbose=False)
                if not _stats.get("online"):
                    st.error("MCN 离线, 稍后重试")
                else:
                    _up = _stats.get("signed_updated", 0)
                    _co = _stats.get("signed_confirmed", 0)
                    _un = _stats.get("unsigned_marked", 0)
                    _uc = _stats.get("unchanged", 0)
                    _err = len(_stats.get("errors", []))
                    st.success(
                        f"✓ 更新 {_up} / 确认 {_co} / "
                        f"未签 {_un} / 不变 {_uc}" +
                        (f" / 错 {_err}" if _err else "")
                    )
                    import time as _tm
                    _tm.sleep(1.5)
                    st.rerun()
            except Exception as e:
                st.error(f"同步失败: {e}")

    st.divider()
    st.caption(f"DB: `{Path(DB_PATH).name}`")
    st.caption(f"时间: {datetime.now().strftime('%H:%M:%S')}")

if auto_refresh_sec > 0:
    # Streamlit 原生 auto-refresh
    import time as _t
    _placeholder = st.empty()
    # 注意: auto-refresh 在当前版本用 st_autorefresh 或 time+rerun
    # 这里用简化方案: 页面 meta refresh
    st.markdown(
        f"<meta http-equiv='refresh' content='{auto_refresh_sec}'>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
# 🏠 总览页
# ══════════════════════════════════════════════════════════════

def page_overview():
    st.title("🏠 矩阵总览")

    # ── 顶部 KPI 卡片 ──
    today = datetime.now().strftime("%Y-%m-%d")

    # 1. 今日 plan
    plan = _query_one(
        "SELECT * FROM daily_plans WHERE plan_date=? LIMIT 1", (today,)
    )
    plan_items = _query(
        "SELECT status, COUNT(*) AS n FROM daily_plan_items "
        "WHERE plan_id=? GROUP BY status",
        (plan["id"] if plan else 0,),
    )

    # 2. 账号 tier 分布
    tier_dist = _query(
        "SELECT tier, COUNT(*) AS n FROM device_accounts "
        "WHERE login_status='logged_in' GROUP BY tier"
    )

    # 3. task_queue 实时
    tq = _query(
        "SELECT status, COUNT(*) AS n FROM task_queue "
        "WHERE datetime(created_at) >= datetime('now','-24 hours','localtime') "
        "GROUP BY status"
    )

    # 4. 近 24h 自愈动作
    heals = _query_one(
        "SELECT COUNT(*) AS n FROM healing_actions "
        "WHERE datetime(created_at) >= datetime('now','-24 hours','localtime')"
    )
    heal_ok = _query_one(
        "SELECT COUNT(*) AS n FROM healing_actions "
        "WHERE status='success' AND "
        "datetime(created_at) >= datetime('now','-24 hours','localtime')"
    )

    # KPI cards
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        n_items = plan["total_tasks"] if plan else 0
        st.metric("今日规划任务", n_items,
                   f"{len(plan_items)} 种状态" if not plan_items.empty else "")
    with c2:
        n_active = sum(tier_dist[tier_dist["tier"].isin(
            ["testing", "warming_up", "established", "viral"])]["n"])
        st.metric("活跃账号", int(n_active),
                   f"/ {int(tier_dist['n'].sum())} 总数")
    with c3:
        n_running = int(tq[tq["status"] == "running"]["n"].sum()) if not tq.empty else 0
        n_queued = int(tq[tq["status"] == "queued"]["n"].sum()) if not tq.empty else 0
        st.metric("队列中", f"{n_running} 运行 / {n_queued} 待跑")
    with c4:
        n_heals = heals["n"] if heals else 0
        n_ok = heal_ok["n"] if heal_ok else 0
        rate = f"{100*n_ok/n_heals:.0f}%" if n_heals else "—"
        st.metric("24h 自愈动作", n_heals, f"成功率 {rate}")

    st.divider()

    # ── 账号 tier 分布饼图 ──
    col1, col2 = st.columns([2, 3])

    with col1:
        st.subheader("账号层级分布")
        if not tier_dist.empty:
            import plotly.express as px
            tier_order = {"new": 1, "testing": 2, "warming_up": 3,
                          "established": 4, "viral": 5, "frozen": 6}
            tier_dist["order"] = tier_dist["tier"].map(tier_order).fillna(0)
            tier_dist = tier_dist.sort_values("order")
            fig = px.pie(tier_dist, values="n", names="tier",
                          color="tier",
                          color_discrete_map={
                              "new": "#94a3b8", "testing": "#60a5fa",
                              "warming_up": "#fbbf24", "established": "#34d399",
                              "viral": "#f472b6", "frozen": "#ef4444",
                          })
            fig.update_traces(textposition="inside", textinfo="label+value")
            fig.update_layout(height=320, showlegend=True,
                               margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("尚无账号数据")

    with col2:
        st.subheader("今日任务状态")
        if not plan_items.empty:
            # 状态顺序
            status_order = {"pending": 1, "queued": 2, "running": 3,
                            "success": 4, "failed": 5, "dead_letter": 6}
            plan_items["order"] = plan_items["status"].map(status_order).fillna(99)
            plan_items = plan_items.sort_values("order")
            import plotly.express as px
            fig = px.bar(plan_items, x="status", y="n", text="n",
                          color="status",
                          color_discrete_map={
                              "pending": "#94a3b8", "queued": "#60a5fa",
                              "running": "#fbbf24", "success": "#34d399",
                              "failed": "#ef4444", "dead_letter": "#b91c1c",
                          })
            fig.update_traces(textposition="outside")
            fig.update_layout(height=320, showlegend=False,
                               margin=dict(l=0, r=0, t=0, b=0))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("今日还没生成 plan (每日 8:00 自动跑)")

    st.divider()

    # ── 近 7 天收益趋势 ──
    st.subheader("近 7 天系统收益")
    income_trend = _query("""
        SELECT metric_date, SUM(income_delta) AS income,
               SUM(publishes_success) AS succ,
               SUM(publishes_failed) AS fail
        FROM publish_daily_metrics
        WHERE metric_date >= date('now','-7 days')
        GROUP BY metric_date ORDER BY metric_date
    """)
    if not income_trend.empty:
        import plotly.graph_objects as go
        fig = go.Figure()
        fig.add_trace(go.Bar(x=income_trend["metric_date"],
                              y=income_trend["income"],
                              name="收益 ¥", marker_color="#34d399"))
        fig.add_trace(go.Scatter(x=income_trend["metric_date"],
                                  y=income_trend["succ"],
                                  name="发布成功", yaxis="y2",
                                  line=dict(color="#60a5fa", width=3)))
        fig.update_layout(
            height=300,
            yaxis=dict(title="收益 ¥"),
            yaxis2=dict(title="发布数", overlaying="y", side="right"),
            margin=dict(l=0, r=0, t=0, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("publish_daily_metrics 暂无数据. 每日 17:00 由 Analyzer 聚合.")

    # ── autopilot_cycles 健康 ──
    st.subheader("Autopilot 循环健康")
    cycles = _query("""
        SELECT cycle_id, started_at, status, checks_run,
               failures_found, heals_applied, duration_ms
        FROM autopilot_cycles
        ORDER BY id DESC LIMIT 10
    """)
    if not cycles.empty:
        # 渲染 dataframe
        st.dataframe(cycles, use_container_width=True, hide_index=True)
    else:
        st.info("还没 autopilot 循环")


# ══════════════════════════════════════════════════════════════
# 📋 任务页
# ══════════════════════════════════════════════════════════════

def page_tasks():
    st.title("📋 任务队列")
    st.caption("★ §27 重构: 发布任务 🎬 与 维护任务 ⚙️ 分页显示, 账号显示中文名, 全中文状态")

    today = datetime.now().strftime("%Y-%m-%d")

    # ── 今日 plan_items ──
    st.subheader(f"今日计划任务 (plan_date={today})")
    items = _query("""
        SELECT i.id, i.account_id,
               COALESCE(da.kuaishou_name, da.account_name, '账号#' || i.account_id) AS account_display,
               da.account_name AS account_raw,
               da.numeric_uid,
               i.drama_name, i.recipe, i.account_tier AS tier,
               i.priority, i.match_score,
               i.status, i.scheduled_at, i.task_id
        FROM daily_plan_items i
        LEFT JOIN device_accounts da ON i.account_id = da.id
        JOIN daily_plans p ON i.plan_id = p.id
        WHERE p.plan_date = ?
        ORDER BY i.priority DESC, i.scheduled_at ASC
    """, (today,))

    if not items.empty:
        total = len(items)
        pending = (items["status"] == "pending").sum()
        queued = (items["status"] == "queued").sum()
        running = (items["status"] == "running").sum()
        success = (items["status"] == "success").sum()
        failed = (items["status"] == "failed").sum()
        c1, c2, c3, c4, c5, c6 = st.columns(6)
        c1.metric("总计", total)
        c2.metric("⏸ 待发", pending)
        c3.metric("📥 排队", queued)
        c4.metric("⏳ 运行", running)
        c5.metric("✅ 成功", success, delta_color="off")
        c6.metric("❌ 失败", failed, delta_color="inverse")

        # 中文列名 + 中文 status/tier
        show = items.copy()
        show["状态"] = show["status"].apply(_st_cn)
        show["分层"] = show["tier"].apply(_tier_cn)
        show["账号"] = show["account_display"]
        display_cols = ["id", "账号", "drama_name", "recipe", "分层",
                        "priority", "match_score", "状态", "scheduled_at", "task_id"]
        show = show.rename(columns={
            "drama_name": "剧名", "recipe": "去重方案",
            "priority": "优先级", "match_score": "匹配分",
            "scheduled_at": "排期时间", "task_id": "任务ID",
        })
        rename_map = {
            "id": "id", "账号": "账号", "剧名": "剧名",
            "去重方案": "去重方案", "分层": "分层",
            "优先级": "优先级", "匹配分": "匹配分",
            "状态": "状态", "排期时间": "排期时间",
            "任务ID": "任务ID",
        }
        display_cols_cn = ["id", "账号", "剧名", "去重方案", "分层",
                            "优先级", "匹配分", "状态", "排期时间", "任务ID"]

        status_filter = st.multiselect(
            "按状态过滤",
            options=show["状态"].unique().tolist(),
            default=show["状态"].unique().tolist(),
        )
        filtered = show[show["状态"].isin(status_filter)]
        st.dataframe(filtered[display_cols_cn], use_container_width=True,
                     hide_index=True, height=400)
    else:
        st.info("今日计划尚未生成 (早 8:00 planner 跑完会出现)")

    st.divider()

    # ── 近 2h task_queue — ★ §27: 拆 发布 / 维护 两页 ──
    st.subheader("近 2 小时任务队列")

    tasks = _query("""
        SELECT t.id, t.account_id,
               COALESCE(da.kuaishou_name, da.account_name, '账号#' || CAST(t.account_id AS TEXT)) AS 账号,
               t.drama_name AS 剧名, t.task_type, t.status,
               t.priority AS 优先级, t.retry_count AS 重试次数,
               t.task_source,
               t.worker_name AS 工人,
               t.created_at AS 创建时间,
               t.started_at AS 开始时间,
               t.finished_at AS 结束时间,
               SUBSTR(t.error_message, 1, 80) AS 错误
        FROM task_queue t
        LEFT JOIN device_accounts da ON CAST(t.account_id AS INTEGER) = da.id
        WHERE datetime(t.created_at) >= datetime('now','-2 hours','localtime')
        ORDER BY t.created_at DESC
        LIMIT 200
    """)

    if tasks.empty:
        st.info("近 2 小时无任务")
        return

    # 中文映射
    tasks["任务类型"] = tasks["task_type"].apply(_tt_cn)
    tasks["状态"] = tasks["status"].apply(_st_cn)
    tasks["来源"] = tasks["task_source"].apply(_ts_cn)

    # 拆分: 发布 vs 维护
    is_publish = tasks["task_type"].isin(PUBLISH_TASK_TYPES)
    publish_df = tasks[is_publish].copy()
    maint_df = tasks[~is_publish].copy()

    # 3 tab 对齐用户需求: 🎬 发布 / ⚙️ 维护 / 📊 全部
    tab1, tab2, tab3 = st.tabs([
        f"🎬 发布任务 ({len(publish_df)})",
        f"⚙️ 维护任务 ({len(maint_df)})",
        f"📊 全部 ({len(tasks)})",
    ])

    pub_cols = ["id", "账号", "剧名", "任务类型", "来源", "状态",
                "优先级", "重试次数", "工人", "创建时间", "结束时间", "错误"]
    maint_cols = ["id", "账号", "任务类型", "来源", "状态",
                  "优先级", "重试次数", "工人", "创建时间", "结束时间", "错误"]

    with tab1:
        if publish_df.empty:
            st.info("近 2h 无发布任务")
        else:
            # KPI
            sp = publish_df["status"].value_counts().to_dict()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("总", len(publish_df))
            k2.metric("✅ 成功", sp.get("success", 0))
            k3.metric("❌ 失败", sp.get("failed", 0) + sp.get("dead_letter", 0))
            k4.metric("⏳ 进行中", sp.get("running", 0) + sp.get("queued", 0))
            pub_cols_exist = [c for c in pub_cols if c in publish_df.columns]
            st.dataframe(publish_df[pub_cols_exist],
                         use_container_width=True, hide_index=True, height=450)
    with tab2:
        if maint_df.empty:
            st.info("近 2h 无维护任务")
        else:
            sm = maint_df["status"].value_counts().to_dict()
            k1, k2, k3, k4 = st.columns(4)
            k1.metric("总", len(maint_df))
            k2.metric("✅ 成功", sm.get("success", 0))
            k3.metric("❌ 失败", sm.get("failed", 0) + sm.get("dead_letter", 0))
            k4.metric("⏳ 进行中", sm.get("running", 0) + sm.get("queued", 0))
            maint_cols_exist = [c for c in maint_cols if c in maint_df.columns]
            st.dataframe(maint_df[maint_cols_exist],
                         use_container_width=True, hide_index=True, height=450)
    with tab3:
        all_cols_exist = [c for c in pub_cols if c in tasks.columns]
        st.dataframe(tasks[all_cols_exist],
                     use_container_width=True, hide_index=True, height=450)


# ══════════════════════════════════════════════════════════════
# 🩺 自愈页
# ══════════════════════════════════════════════════════════════

def page_healing():
    st.title("🩺 自愈系统")

    # ── playbook 规则库 ──
    st.subheader("Playbook 规则 (自愈条件反射库)")
    playbook = _query("""
        SELECT id, code, symptom_pattern, task_type,
               remedy_action, confidence, is_active,
               success_count, fail_count,
               (success_count + fail_count) AS total,
               CASE WHEN (success_count + fail_count) > 0
                    THEN ROUND(100.0 * success_count / (success_count + fail_count), 1)
                    ELSE NULL END AS success_rate_pct,
               last_triggered_at, proposed_by
        FROM healing_playbook
        ORDER BY is_active DESC, id ASC
    """)
    if not playbook.empty:
        st.dataframe(playbook, use_container_width=True, hide_index=True)
    else:
        st.warning("playbook 空 — 检查 migrate_v21 是否跑过")

    st.divider()

    # ── 近 24h 诊断 ──
    st.subheader("近 24h 诊断记录")
    diag = _query("""
        SELECT id, cycle_id, playbook_code, diagnosis,
               confidence, auto_resolved,
               created_at, resolved_at
        FROM healing_diagnoses
        WHERE datetime(created_at) >= datetime('now','-24 hours','localtime')
        ORDER BY id DESC
        LIMIT 50
    """)
    if not diag.empty:
        st.dataframe(diag, use_container_width=True, hide_index=True,
                      height=300)
    else:
        st.success("近 24h 无新诊断 — 系统健康")

    st.divider()

    # ── LLM 生成的 pending 建议 (审批!) ──
    st.subheader("📝 LLM 规则建议 (等你审批)")
    pending = _query("""
        SELECT id, proposer, category, config_key,
               proposed_value, reason, confidence, llm_confidence,
               created_at
        FROM rule_proposals
        WHERE status='pending'
        ORDER BY id DESC
    """)
    if not pending.empty:
        st.caption(f"{len(pending)} 条待审批")
        for _, row in pending.iterrows():
            with st.expander(
                f"[{row['id']}] {row['category']}: {row['config_key']} "
                f"(置信 {row['confidence']:.0%})"
            ):
                st.markdown(f"**Proposer**: `{row['proposer']}`")
                st.markdown(f"**Reason**: {row['reason']}")
                try:
                    # proposed_value 是 JSON
                    v = json.loads(row["proposed_value"])
                    st.json(v)
                except Exception:
                    st.code(row["proposed_value"])

                c1, c2 = st.columns(2)
                with c1:
                    if st.button(f"✅ 批准 #{row['id']}",
                                  key=f"approve_{row['id']}"):
                        _sql_exec(
                            "UPDATE rule_proposals SET status='approved', "
                            "decided_by='dashboard', "
                            "decided_at=datetime('now','localtime') "
                            "WHERE id=?",
                            (int(row["id"]),),
                        )
                        st.success(f"已批准 #{row['id']}")
                        st.rerun()
                with c2:
                    if st.button(f"❌ 驳回 #{row['id']}",
                                  key=f"reject_{row['id']}"):
                        _sql_exec(
                            "UPDATE rule_proposals SET status='rejected', "
                            "decided_by='dashboard', "
                            "decided_at=datetime('now','localtime') "
                            "WHERE id=?",
                            (int(row["id"]),),
                        )
                        st.info(f"已驳回 #{row['id']}")
                        st.rerun()
    else:
        st.success("没有待审批的 LLM 规则建议")

    # ── 升级建议 ──
    st.subheader("🔧 升级建议 (upgrade_proposals)")
    upg = _query("""
        SELECT id, upgrade_type, target_file,
               reason, confidence, status, proposer,
               created_at, decided_at
        FROM upgrade_proposals
        ORDER BY id DESC LIMIT 20
    """)
    if not upg.empty:
        st.dataframe(upg, use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# 💎 收益页
# ══════════════════════════════════════════════════════════════

def page_income():
    st.title("💎 收益概览")

    # MCN snapshot 最新一天
    latest = _query_one(
        "SELECT MAX(snapshot_date) AS d FROM mcn_member_snapshots"
    )
    if not latest or not latest["d"]:
        st.info("尚无 MCN 快照数据")
        return

    d = latest["d"]
    st.caption(f"数据日期: {d} (最新快照)")

    # 13 账号当日
    rows = _query("""
        SELECT da.id, da.account_name, da.tier, da.numeric_uid,
               m.total_amount, m.org_task_num
        FROM device_accounts da
        LEFT JOIN mcn_member_snapshots m
            ON m.member_id = da.numeric_uid
            AND m.snapshot_date = ?
        WHERE da.login_status='logged_in'
        ORDER BY m.total_amount DESC NULLS LAST
    """, (d,))

    # 统计
    total = rows["total_amount"].sum() if not rows.empty else 0
    active = (rows["total_amount"] > 0).sum() if not rows.empty else 0
    c1, c2, c3 = st.columns(3)
    c1.metric(f"{d} 总收益 ¥", f"{total:.2f}")
    c2.metric("出单账号数", int(active))
    c3.metric("全员", len(rows) if not rows.empty else 0)

    if not rows.empty:
        st.dataframe(rows, use_container_width=True, hide_index=True)

    # Strategy rewards
    st.divider()
    st.subheader("Bandit Reward (tier × recipe)")
    rewards = _query("""
        SELECT account_tier, recipe,
               trials, ROUND(rewards, 3) AS total_rewards,
               ROUND(rewards * 1.0 / NULLIF(trials, 0), 3) AS avg_reward
        FROM strategy_rewards
        ORDER BY avg_reward DESC NULLS LAST
    """)
    if not rewards.empty:
        st.dataframe(rewards, use_container_width=True, hide_index=True)
    else:
        st.info("Reward 矩阵尚空 (需要 Analyzer 每日跑)")


# ══════════════════════════════════════════════════════════════
# 👤 账号详情页 (K-1)
# ══════════════════════════════════════════════════════════════

def page_account_detail():
    st.title("👤 账号详情")

    # 账号选择器
    accs = _query("""
        SELECT id, account_name, kuaishou_name, signed_status,
               tier, numeric_uid, login_status,
               tier_since, frozen_reason
        FROM device_accounts
        WHERE login_status='logged_in'
        ORDER BY tier, account_name
    """)
    if accs.empty:
        st.warning("无账号数据")
        return

    def _fmt_option(r):
        ks = r["kuaishou_name"] or ""
        sig = r["signed_status"] or "unknown"
        tag = {"signed": "✓", "unsigned": "✗", "unknown": "?"}.get(sig, "?")
        ks_part = f" | ks: {ks}" if ks and ks != r["account_name"] else ""
        return f"{r['id']}: {r['account_name']}{ks_part} [{r['tier']}] {tag}"

    options = [_fmt_option(r) for _, r in accs.iterrows()]
    pick = st.selectbox("选账号", options, key="acc_picker")
    acc_id = int(pick.split(":")[0])
    acc_row = accs[accs["id"] == acc_id].iloc[0]

    # 顶部 KPI (5 列, +快手昵称 / +签约)
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Tier", acc_row["tier"])
    c2.metric("UID", str(acc_row["numeric_uid"] or "N/A"))
    ks_name = acc_row.get("kuaishou_name") or "—"
    c3.metric("快手昵称", ks_name if ks_name else "—")
    sig_status = acc_row.get("signed_status") or "unknown"
    sig_emoji = {"signed": "✅ 已签约", "unsigned": "❌ 未签约",
                  "unknown": "❓ 未知"}.get(sig_status, sig_status)
    c4.metric("MCN 签约", sig_emoji)
    c5.metric("状态", acc_row["login_status"])

    if acc_row.get("frozen_reason"):
        st.warning(f"❄️ 冻结: {acc_row['frozen_reason']}")

    # 本地 vs MCN 对比 (展开)
    with st.expander("📋 本地 vs 快手真身 对比", expanded=False):
        ccol1, ccol2 = st.columns(2)
        ccol1.markdown(
            "**本地 (运营别名)**  \n"
            f"- account_name: `{acc_row['account_name']}`  \n"
            f"- kuaishou_name: `{ks_name}`  \n"
            f"- numeric_uid: `{acc_row['numeric_uid']}`  \n"
            f"- signed_status: `{sig_status}`"
        )
        ccol2.markdown(
            "**说明**  \n"
            "- `account_name` = 运营手起的别名 (可 emoji)  \n"
            "- `kuaishou_name` = 快手真实昵称 (MCN 为准)  \n"
            "- `signed_status` 从 MCN 实时查"
        )

    st.divider()

    # 🌐 MCN 实时面板 (自动后台同步 + 按需强制刷新)
    st.subheader("🌐 MCN 实时数据")

    # freshness 指示
    last_sync_row = _query_one(
        "SELECT config_value FROM app_config WHERE config_key='sync.ks_names.last_run_at'"
    )
    interval_row = _query_one(
        "SELECT config_value FROM app_config WHERE config_key='sync.ks_names.interval_sec'"
    )
    last_sync_iso = last_sync_row.get("config_value") if last_sync_row else None
    interval_sec = int(interval_row.get("config_value")) if interval_row else 43200

    fresh_msg = "⚠️ 从未同步"
    stale = True
    if last_sync_iso:
        try:
            last_dt = datetime.fromisoformat(last_sync_iso)
            age = (datetime.now() - last_dt).total_seconds()
            stale = age > interval_sec
            if age < 60:
                fresh_msg = f"✅ {int(age)}秒 前同步"
            elif age < 3600:
                fresh_msg = f"✅ {int(age/60)}分钟 前同步"
            elif age < 86400:
                fresh_msg = f"{'⏰' if stale else '✅'} {int(age/3600)}小时 前同步"
            else:
                fresh_msg = f"⏰ {int(age/86400)}天 前同步 (陈旧)"
        except Exception:
            fresh_msg = f"? {last_sync_iso}"

    st.caption(
        f"{fresh_msg}  |  本地数据每 {interval_sec//3600}h 后台自动同步 "
        f"(ControllerAgent step 17b sync.ks_names)"
    )

    mcol1, mcol2, mcol3 = st.columns([1, 1, 3])
    do_refresh = mcol1.button("🔄 强制 MCN 刷新", key="mcn_live_refresh",
                               help="立即查 MCN 服务器, 不等 12h 定时任务")
    show_income = mcol2.checkbox("+近 7 天收益", value=False,
                                  key="mcn_live_income")
    if do_refresh:
        try:
            from core.mcn_live import (
                fetch_member_live,
                fetch_member_income_summary,
                is_online,
            )
            if not is_online(timeout=3.0):
                mcol3.error("MCN 离线")
            elif not acc_row["numeric_uid"]:
                mcol3.error("账号缺 numeric_uid, 无法查")
            else:
                uid_i = int(acc_row["numeric_uid"])
                live = fetch_member_live(uid_i)
                if not live:
                    mcol3.warning("MCN 查无此账号 (unsigned)")
                    # 顺便把本地 signed_status 纠正过来
                    _sql_exec(
                        "UPDATE device_accounts SET signed_status='unsigned' "
                        "WHERE id=?", (acc_id,),
                    )
                else:
                    mcol3.success("MCN 最新 ✓")
                    # 同步 kuaishou_name + signed_status
                    mcn_nick = (live.get("member_name") or "").strip()
                    if mcn_nick and mcn_nick != (acc_row.get("kuaishou_name") or ""):
                        _sql_exec(
                            "UPDATE device_accounts "
                            "SET kuaishou_name=?, signed_status='signed' "
                            "WHERE id=?", (mcn_nick, acc_id),
                        )
                    elif sig_status != "signed":
                        _sql_exec(
                            "UPDATE device_accounts SET signed_status='signed' "
                            "WHERE id=?", (acc_id,),
                        )
                    # 展示
                    mk1, mk2, mk3, mk4 = st.columns(4)
                    mk1.metric("MCN member_name", mcn_nick or "—")
                    mk2.metric("org_id", str(live.get("org_id") or "—"))
                    mk3.metric("total_amount ¥",
                                f"{live.get('total_amount') or 0:.2f}")
                    mk4.metric("org_task_num", str(live.get("org_task_num") or 0))
                    st.caption(
                        f"fans: {live.get('fans_count') or 0}  |  "
                        f"broker: {live.get('broker_name') or '未分配'}  |  "
                        f"MCN updated_at: {live.get('updated_at') or '—'}"
                    )

                    if show_income:
                        inc = fetch_member_income_summary(uid_i, days=7)
                        if inc:
                            st.info(
                                f"近 7 天: {inc.get('task_events') or 0} "
                                f"事件 × {inc.get('unique_tasks') or 0} 不同任务 / "
                                f"¥{inc.get('total_income') or 0:.2f}  "
                                f"(最后: {inc.get('last_event_at') or '—'})"
                            )
        except Exception as e:
            mcol3.error(f"查询失败: {e}")

    st.divider()

    # 近 7 天 plan_items 时间轴
    st.subheader("📅 近 7 天 Plan Items")
    items = _query("""
        SELECT p.plan_date, i.drama_name, i.recipe, i.priority,
               i.match_score, i.status, i.scheduled_at, i.task_id
        FROM daily_plan_items i
        JOIN daily_plans p ON i.plan_id = p.id
        WHERE i.account_id = ?
          AND p.plan_date >= date('now','-7 days','localtime')
        ORDER BY p.plan_date DESC, i.priority DESC
    """, (acc_id,))
    if not items.empty:
        st.dataframe(items, use_container_width=True, hide_index=True)
    else:
        st.info("近 7 天无 plan")

    # Task history
    st.subheader("📋 Task History (近 72h)")
    tasks = _query("""
        SELECT id, task_type, drama_name, status, priority, retry_count,
               created_at, started_at, finished_at,
               SUBSTR(error_message, 1, 120) AS error_preview
        FROM task_queue
        WHERE account_id = ?
          AND datetime(created_at) >= datetime('now','-72 hours','localtime')
        ORDER BY created_at DESC
        LIMIT 50
    """, (str(acc_id),))
    if not tasks.empty:
        # 状态色
        total = len(tasks)
        succ = (tasks["status"] == "success").sum()
        fail = (tasks["status"] == "failed").sum()
        rate = f"{100*succ/total:.0f}%" if total else "—"
        sc1, sc2, sc3 = st.columns(3)
        sc1.metric("任务总数 (72h)", total)
        sc2.metric("成功率", rate)
        sc3.metric("失败", fail, delta_color="inverse")
        st.dataframe(tasks, use_container_width=True, hide_index=True, height=300)
    else:
        st.info("近 72h 无任务")

    # Healing 记录
    st.subheader("🩺 自愈记录 (该账号相关)")
    heals = _query("""
        SELECT h.id, h.cycle_id, h.playbook_code, h.diagnosis,
               h.confidence, h.auto_resolved, h.created_at
        FROM healing_diagnoses h
        WHERE h.evidence_json LIKE ?
          AND datetime(h.created_at) >= datetime('now','-7 days','localtime')
        ORDER BY h.id DESC
        LIMIT 20
    """, (f'%"account_id":"{acc_id}"%',))
    if not heals.empty:
        st.dataframe(heals, use_container_width=True, hide_index=True)
    else:
        st.success("近 7 天该账号无诊断记录 — 健康")

    # 收益曲线
    st.subheader("💰 收益曲线 (近 14 天)")
    numeric_uid = acc_row["numeric_uid"]
    if numeric_uid:
        income = _query("""
            SELECT snapshot_date, total_amount, org_task_num
            FROM mcn_member_snapshots
            WHERE member_id = ?
              AND snapshot_date >= date('now','-14 days','localtime')
            ORDER BY snapshot_date
        """, (int(numeric_uid),))
        if not income.empty:
            import plotly.express as px
            fig = px.line(income, x="snapshot_date", y="total_amount",
                           markers=True, title="每日 fluorescent 收益 ¥")
            fig.update_layout(height=300)
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("无 MCN 快照")
    else:
        st.warning("账号缺 numeric_uid, 无法查 MCN 收益")

    # 一键操作
    st.divider()
    st.subheader("⚡ 快速操作")
    op_col1, op_col2, op_col3, op_col4 = st.columns(4)
    new_tier = op_col1.selectbox("改 tier", ["", "new", "testing",
                                              "warming_up", "established",
                                              "viral", "frozen"])
    if op_col1.button("应用 tier"):
        if new_tier:
            _sql_exec(
                "UPDATE device_accounts SET tier=?, tier_since=datetime('now','localtime') "
                "WHERE id=?", (new_tier, acc_id),
            )
            st.success(f"已切换到 {new_tier}")
            st.rerun()

    if op_col2.button("❄️ 冻结"):
        _sql_exec(
            "UPDATE device_accounts SET tier='frozen', frozen_reason=?, "
            "tier_since=datetime('now','localtime') WHERE id=?",
            (f"manual via dashboard @ {datetime.now().isoformat()}", acc_id),
        )
        st.success("已冻结")
        st.rerun()

    if op_col3.button("🔥 解冻 → testing"):
        _sql_exec(
            "UPDATE device_accounts SET tier='testing', frozen_reason=NULL, "
            "tier_since=datetime('now','localtime') WHERE id=?",
            (acc_id,),
        )
        st.success("已解冻到 testing")
        st.rerun()

    if op_col4.button("🗑️ 取消该账号 pending items"):
        n = _sql_exec(
            "UPDATE daily_plan_items SET status='canceled' "
            "WHERE account_id=? AND status='pending'", (acc_id,),
        )
        st.success(f"已取消 {n} 条 pending")
        st.rerun()

    st.divider()

    # ══════════════════════════════════════════════════════════
    # ★ 账号记忆系统 (Layer 2 + Layer 1 + Layer 3)
    # ══════════════════════════════════════════════════════════
    memory_tab, decisions_tab, diary_tab = st.tabs([
        "🧠 AI 记忆 (Layer 2)", "📝 决策历史 (Layer 1)", "📔 AI 周记 (Layer 3)"
    ])

    with memory_tab:
        st.subheader("账号画像 — strategy_memory")
        try:
            from core.account_memory import get_strategy_memory
            mem = get_strategy_memory(acc_id)
        except Exception as e:
            st.error(f"加载失败: {e}")
            mem = None

        if not mem:
            st.info("该账号尚无 strategy_memory. 等 analyzer 运行后生成.")
            if st.button("🔄 立即重建该账号记忆"):
                try:
                    from core.account_memory import rebuild_strategy_memory
                    r = rebuild_strategy_memory(acc_id)
                    st.success(f"重建完成: {r.get('total_decisions')} 决策, "
                                 f"trust={r.get('ai_trust_score')}")
                    st.rerun()
                except Exception as e:
                    st.error(f"失败: {e}")
        else:
            # KPI
            mc1, mc2, mc3, mc4 = st.columns(4)
            trust = mem.get("ai_trust_score")
            mc1.metric("AI 信任分", f"{trust:.2f}" if trust else "N/A",
                         f"{mem.get('correct_count',0)}/{mem.get('total_decisions',0)} 正确")
            mc2.metric("30 天收益", f"¥{mem.get('total_income_30d',0):.2f}")
            mc3.metric("7 天收益", f"¥{mem.get('total_income_7d',0):.2f}")
            mc4.metric("总发布", mem.get("total_published", 0))

            # 偏好雷达 / 表
            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**偏好 Recipe** (命中率)")
                pr = mem.get("preferred_recipes") or {}
                if pr:
                    st.dataframe(
                        pd.DataFrame([(k, f"{v:.0%}") for k, v in pr.items()],
                                      columns=["recipe", "命中率"]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("样本不足")
            with c2:
                st.markdown("**偏好 Image mode**")
                pi = mem.get("preferred_image_modes") or {}
                if pi:
                    st.dataframe(
                        pd.DataFrame([(k, f"{v:.0%}") for k, v in pi.items()],
                                      columns=["image_mode", "命中率"]),
                        hide_index=True, use_container_width=True,
                    )
                else:
                    st.caption("样本不足")

            # 避雷
            avoid = mem.get("avoid_drama_ids") or []
            if avoid:
                st.markdown("**🚫 避雷剧** (历史 over_optimistic/wrong)")
                st.caption(", ".join(avoid[:10]))

            # 详细 JSON
            with st.expander("🔍 完整 memory JSON"):
                st.json({k: v for k, v in mem.items()
                          if k not in ("account_id", "updated_at")})

    with decisions_tab:
        st.subheader("决策历史 (decision_history)")
        days = st.slider("回溯天数", 1, 90, 30, key=f"dec_days_{acc_id}")
        try:
            from core.account_memory import query_account_decisions
            decisions = query_account_decisions(acc_id, days=days, limit=200)
        except Exception as e:
            st.error(f"加载失败: {e}")
            decisions = []

        if not decisions:
            st.info(f"近 {days} 天无决策记录.")
        else:
            # Verdict 分布
            from collections import Counter
            vc = Counter(d.get("verdict", "pending") for d in decisions)
            vc_cols = st.columns(5)
            for i, (v, n) in enumerate([
                ("correct", vc.get("correct", 0)),
                ("over_optimistic", vc.get("over_optimistic", 0)),
                ("under_confident", vc.get("under_confident", 0)),
                ("wrong", vc.get("wrong", 0)),
                ("pending", vc.get("pending", 0)),
            ]):
                vc_cols[i].metric(v, n)

            # Timeline 表
            rows = []
            for d in decisions[:50]:
                expected = d.get("expected_outcome") or {}
                actual = d.get("actual_outcome") or {}
                rows.append({
                    "date": d.get("decision_date"),
                    "drama": (d.get("drama_name") or "")[:20],
                    "recipe": d.get("recipe"),
                    "image_mode": d.get("image_mode"),
                    "confidence": d.get("confidence"),
                    "expected_income": expected.get("income_est") or expected.get("income"),
                    "actual_income": actual.get("income"),
                    "verdict": d.get("verdict"),
                    "notes": (d.get("verdict_notes") or "")[:60],
                })
            st.dataframe(pd.DataFrame(rows),
                          use_container_width=True, hide_index=True, height=400)

    with diary_tab:
        st.subheader("AI 周记 (LLM 自然语言总结)")
        try:
            from core.account_memory import load_recent_diaries, approve_diary
            diaries = load_recent_diaries(acc_id, weeks=8)
        except Exception as e:
            st.error(f"加载失败: {e}")
            diaries = []

        if not diaries:
            st.info("近 8 周无周记. 周一 LLMResearcher 会为活跃账号生成.")
            st.caption("手动触发: `python -m core.agents.llm_researcher_agent --mode diary`")
        else:
            for entry in diaries:
                approved = entry.get("approved", 0)
                badge = "✅ 已审" if approved else "⏳ 待审"
                with st.expander(f"📔 {entry['diary_date']} ({entry.get('week_range','')}) {badge}"):
                    if entry.get("summary"):
                        st.markdown(f"**📌 总结**: {entry['summary']}")
                    if entry.get("performance_review"):
                        st.markdown(f"**🔍 复盘**:")
                        st.markdown(entry["performance_review"])
                    if entry.get("lessons_learned"):
                        st.markdown(f"**💡 经验**:")
                        st.markdown(entry["lessons_learned"])
                    if entry.get("next_week_strategy"):
                        st.markdown(f"**🚀 下周策略**:")
                        st.markdown(entry["next_week_strategy"])
                    if not approved and st.button(
                        f"✅ 审批通过 #{entry['id']}", key=f"appr_diary_{entry['id']}"
                    ):
                        approve_diary(entry["id"], approved_by="dashboard")
                        st.success("已审批")
                        st.rerun()


# ══════════════════════════════════════════════════════════════
# 🎬 剧详情页 (K-2)
# ══════════════════════════════════════════════════════════════

def page_drama_detail():
    st.title("🎬 剧详情")

    # 剧选择: 默认从 plan_items 最近 7 天的
    dramas = _query("""
        SELECT DISTINCT i.drama_name, COUNT(*) AS plan_count,
               MIN(i.match_score) AS min_score,
               MAX(i.match_score) AS max_score
        FROM daily_plan_items i
        JOIN daily_plans p ON i.plan_id = p.id
        WHERE p.plan_date >= date('now','-7 days','localtime')
        GROUP BY i.drama_name
        ORDER BY plan_count DESC
    """)

    if dramas.empty:
        # fallback: 从 drama_banner_tasks top 50
        dramas = _query("""
            SELECT drama_name, NULL AS plan_count,
                   NULL AS min_score, NULL AS max_score
            FROM drama_banner_tasks
            WHERE recent_income_sum > 0
            ORDER BY recent_income_sum DESC LIMIT 50
        """)

    if dramas.empty:
        st.warning("无剧数据")
        return

    options = dramas["drama_name"].tolist()
    drama = st.selectbox("选剧", options, key="drama_picker")

    # 剧本身元数据
    meta = _query_one(
        "SELECT * FROM drama_banner_tasks WHERE drama_name=?",
        (drama,),
    )
    if meta:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("近 30 天收益", f"¥{meta.get('recent_income_sum', 0):.0f}")
        c2.metric("收益次数", meta.get("recent_income_count", 0))
        c3.metric("banner_task_id", meta.get("banner_task_id") or "N/A")
        c4.metric("commission_rate", f"{meta.get('commission_rate', 0):.0f}%")

    st.divider()

    # 被哪些账号发过
    st.subheader("📺 投放矩阵 (近 7 天)")
    matrix = _query("""
        SELECT da.account_name, da.tier,
               i.recipe, i.match_score, i.status,
               i.scheduled_at, i.task_id, p.plan_date
        FROM daily_plan_items i
        JOIN daily_plans p ON i.plan_id = p.id
        LEFT JOIN device_accounts da ON i.account_id = da.id
        WHERE i.drama_name = ?
          AND p.plan_date >= date('now','-7 days','localtime')
        ORDER BY p.plan_date DESC, i.match_score DESC
    """, (drama,))
    if not matrix.empty:
        st.dataframe(matrix, use_container_width=True, hide_index=True)
    else:
        st.info("近 7 天未分派此剧")

    # 发布结果 + 实际效果
    st.subheader("📊 发布结果 (30 天)")
    results = _query("""
        SELECT pr.account_id, da.account_name,
               pr.photo_id, pr.publish_status,
               pr.verified_status, pr.created_at
        FROM publish_results pr
        LEFT JOIN device_accounts da ON pr.account_id = CAST(da.id AS TEXT)
        WHERE pr.drama_name = ?
          AND datetime(pr.created_at) >= datetime('now','-30 days','localtime')
        ORDER BY pr.created_at DESC
    """, (drama,))
    if not results.empty:
        st.dataframe(results, use_container_width=True, hide_index=True)

    # 收益曲线
    if meta and meta.get("banner_task_id"):
        st.subheader("💰 剧收益曲线 (MCN fluorescent_income 近 30 天)")
        # 这个数据要从 MCN MySQL 查, 我们有 drama_banner_tasks 聚合
        # 简化版: 展示 banner_task 元数据
        st.info("(需从 MCN MySQL 查实时曲线, 目前只存 sum)")


# ══════════════════════════════════════════════════════════════
# 🔍 全局搜索 (K-4)
# ══════════════════════════════════════════════════════════════

def page_search():
    st.title("🔍 全局搜索")
    st.caption("跨表搜: 账号 / 剧 / photo_id / task_id")

    q = st.text_input("搜索", placeholder="输入关键字 (3 字符以上)...",
                       key="global_q")
    if not q or len(q) < 2:
        st.info("输入 2 个以上字符开始搜...")
        return

    pattern = f"%{q}%"

    # 1. 账号
    st.subheader("👤 账号")
    accs = _query("""
        SELECT id, account_name, tier, numeric_uid, login_status
        FROM device_accounts
        WHERE account_name LIKE ? OR CAST(id AS TEXT) = ?
           OR CAST(numeric_uid AS TEXT) LIKE ?
        LIMIT 20
    """, (pattern, q, pattern))
    if not accs.empty:
        st.dataframe(accs, use_container_width=True, hide_index=True)
    else:
        st.caption("(无)")

    # 2. 剧
    st.subheader("🎬 剧")
    dramas = _query("""
        SELECT drama_name, banner_task_id, recent_income_sum, recent_income_count
        FROM drama_banner_tasks
        WHERE drama_name LIKE ? OR banner_task_id = ?
        ORDER BY recent_income_sum DESC LIMIT 20
    """, (pattern, q))
    if not dramas.empty:
        st.dataframe(dramas, use_container_width=True, hide_index=True)
    else:
        st.caption("(无)")

    # 3. publish_results (含 photo_id)
    st.subheader("📤 发布记录")
    pubs = _query("""
        SELECT id, account_id, drama_name, photo_id, publish_status,
               verified_status, created_at
        FROM publish_results
        WHERE drama_name LIKE ? OR photo_id LIKE ?
           OR CAST(id AS TEXT) = ?
        ORDER BY id DESC LIMIT 20
    """, (pattern, pattern, q))
    if not pubs.empty:
        st.dataframe(pubs, use_container_width=True, hide_index=True)
    else:
        st.caption("(无)")

    # 4. task_queue
    st.subheader("📋 任务 (含 ID 精确匹配)")
    tasks = _query("""
        SELECT id, account_id, drama_name, task_type, status,
               created_at, finished_at
        FROM task_queue
        WHERE id = ? OR drama_name LIKE ? OR account_id = ?
        ORDER BY created_at DESC LIMIT 20
    """, (q, pattern, q))
    if not tasks.empty:
        st.dataframe(tasks, use_container_width=True, hide_index=True)
    else:
        st.caption("(无)")


# ══════════════════════════════════════════════════════════════
# 🛠️ 批量操作 (K-3)
# ══════════════════════════════════════════════════════════════

def page_batch_ops():
    st.title("🛠️ 批量操作")
    st.caption("⚠️ 直接修改生产数据, 请谨慎")

    op_type = st.radio("操作类型",
                        ["批量切 tier", "批量取消 pending plan_items",
                         "批量重试 failed tasks"])

    if op_type == "批量切 tier":
        accs = _query("""
            SELECT id, account_name, tier FROM device_accounts
            WHERE login_status='logged_in' ORDER BY tier, account_name
        """)
        selected = st.multiselect(
            "选账号 (多选)",
            options=accs["id"].tolist(),
            format_func=lambda i: f"{i}: "
                + accs[accs['id']==i]['account_name'].iloc[0]
                + " [" + accs[accs['id']==i]['tier'].iloc[0] + "]",
        )
        new_tier = st.selectbox("切到 tier",
                                 ["new", "testing", "warming_up",
                                  "established", "viral", "frozen"])
        if st.button(f"应用 ({len(selected)} 个账号 → {new_tier})",
                      disabled=not selected):
            for acc_id in selected:
                _sql_exec(
                    "UPDATE device_accounts SET tier=?, "
                    "tier_since=datetime('now','localtime') WHERE id=?",
                    (new_tier, int(acc_id)),
                )
            st.success(f"已切换 {len(selected)} 账号 → {new_tier}")
            st.rerun()

    elif op_type == "批量取消 pending plan_items":
        st.warning("这会取消今日所有 pending 的 plan_items, 防重发")
        items = _query("""
            SELECT COUNT(*) AS n FROM daily_plan_items i
            JOIN daily_plans p ON i.plan_id=p.id
            WHERE i.status='pending'
              AND p.plan_date=date('now','localtime')
        """)
        n = items["n"].iloc[0] if not items.empty else 0
        st.metric("待取消 pending items", n)
        if st.button(f"取消 {n} 条 pending", disabled=n == 0):
            _sql_exec("""
                UPDATE daily_plan_items SET status='canceled'
                WHERE id IN (
                    SELECT i.id FROM daily_plan_items i
                    JOIN daily_plans p ON i.plan_id=p.id
                    WHERE i.status='pending'
                      AND p.plan_date=date('now','localtime')
                )
            """)
            st.success(f"已取消 {n} 条")
            st.rerun()

    elif op_type == "批量重试 failed tasks":
        st.warning("把近 24h failed tasks 重设为 queued, 重新跑一次")
        fails = _query("""
            SELECT COUNT(*) AS n FROM task_queue
            WHERE status='failed'
              AND datetime(finished_at) >= datetime('now','-24 hours','localtime')
        """)
        n = fails["n"].iloc[0] if not fails.empty else 0
        st.metric("待重试 failed tasks", n)
        if st.button(f"重试 {n} 个", disabled=n == 0):
            _sql_exec("""
                UPDATE task_queue SET status='queued',
                    started_at=NULL, finished_at=NULL, worker_name=NULL,
                    error_message=NULL, retry_count=0
                WHERE status='failed'
                  AND datetime(finished_at) >= datetime('now','-24 hours','localtime')
            """)
            st.success(f"已重排 {n} 个")
            st.rerun()


# ══════════════════════════════════════════════════════════════
# 📊 Excel 导出 (K-5)
# ══════════════════════════════════════════════════════════════

def page_export():
    st.title("📊 数据导出")
    st.caption("导出 CSV / Excel (如有 openpyxl)")

    report_type = st.selectbox("报表类型", [
        "今日 plan_items",
        "近 7 天 publish_results",
        "账号收益总表 (当日 MCN)",
        "自愈诊断 (近 7 天)",
        "strategy_rewards 矩阵",
    ])

    # 生成数据
    if report_type == "今日 plan_items":
        df = _query("""
            SELECT i.id, da.account_name, i.account_tier, i.drama_name,
                   i.recipe, i.priority, i.match_score, i.status,
                   i.scheduled_at, i.task_id
            FROM daily_plan_items i
            LEFT JOIN device_accounts da ON i.account_id = da.id
            JOIN daily_plans p ON i.plan_id = p.id
            WHERE p.plan_date = date('now','localtime')
            ORDER BY i.priority DESC
        """)
    elif report_type == "近 7 天 publish_results":
        df = _query("""
            SELECT pr.id, pr.account_id, da.account_name, pr.drama_name,
                   pr.photo_id, pr.publish_status, pr.verified_status,
                   pr.created_at
            FROM publish_results pr
            LEFT JOIN device_accounts da ON pr.account_id = CAST(da.id AS TEXT)
            WHERE datetime(pr.created_at) >= datetime('now','-7 days','localtime')
            ORDER BY pr.created_at DESC
        """)
    elif report_type == "账号收益总表 (当日 MCN)":
        df = _query("""
            SELECT da.id, da.account_name, da.tier, da.numeric_uid,
                   m.snapshot_date, m.total_amount, m.org_task_num
            FROM device_accounts da
            LEFT JOIN mcn_member_snapshots m
                ON m.member_id = da.numeric_uid
                AND m.snapshot_date = (SELECT MAX(snapshot_date)
                                         FROM mcn_member_snapshots)
            WHERE da.login_status='logged_in'
            ORDER BY m.total_amount DESC NULLS LAST
        """)
    elif report_type == "自愈诊断 (近 7 天)":
        df = _query("""
            SELECT id, cycle_id, playbook_code, diagnosis,
                   confidence, auto_resolved, resolved_at, created_at
            FROM healing_diagnoses
            WHERE datetime(created_at) >= datetime('now','-7 days','localtime')
            ORDER BY id DESC
        """)
    else:
        df = _query("""
            SELECT account_tier, recipe, trials, rewards,
                   ROUND(rewards * 1.0 / NULLIF(trials, 0), 3) AS avg_reward
            FROM strategy_rewards ORDER BY avg_reward DESC NULLS LAST
        """)

    st.dataframe(df, use_container_width=True, hide_index=True, height=400)

    c1, c2 = st.columns(2)
    # CSV
    csv_data = df.to_csv(index=False).encode("utf-8-sig")
    c1.download_button(
        "⬇️ 下载 CSV",
        data=csv_data,
        file_name=f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
        mime="text/csv",
    )

    # Excel (need openpyxl)
    try:
        import io
        import openpyxl  # noqa
        buf = io.BytesIO()
        df.to_excel(buf, index=False, engine="openpyxl")
        c2.download_button(
            "⬇️ 下载 Excel",
            data=buf.getvalue(),
            file_name=f"{report_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    except ImportError:
        c2.caption("(Excel 需 `pip install openpyxl`)")


# ══════════════════════════════════════════════════════════════
# 🎨 Qitian 图片模式预览
# ══════════════════════════════════════════════════════════════

def page_qitian():
    st.title("🎨 Qitian 图片模式预览")
    st.caption("6 种 PIL 风格 — 图文贴用, 无需 ffmpeg")

    from core.qitian import AVAILABLE_STYLES, generate
    import tempfile
    import os

    col1, col2 = st.columns([1, 2])
    with col1:
        drama = st.text_input("剧名", value="小小武神不好惹")
        account = st.text_input("账号", value="思莱短剧")
        style = st.selectbox("风格", AVAILABLE_STYLES + ["all"])

        # 可选视频路径 (mosaic_rotate / frame_transform 用)
        video_path = st.text_input("视频路径 (mosaic_rotate/frame_transform 用, 留空 = fallback 色块)",
                                      value="")
        video_path = video_path.strip() or None
        if video_path and not os.path.isfile(video_path):
            st.warning(f"视频路径不存在: {video_path}")
            video_path = None

        width = st.slider("宽度", 360, 1080, 720, step=60)
        height = st.slider("高度", 480, 1440, 960, step=60)

        btn = st.button("🚀 生成")

    with col2:
        if btn:
            if style == "all":
                cols = st.columns(3)
                for i, s in enumerate(AVAILABLE_STYLES):
                    out_path = os.path.join(tempfile.gettempdir(), f"qitian_{s}.png")
                    r = generate(
                        style=s, drama_name=drama, account_name=account,
                        output_path=out_path, video_path=video_path,
                        width=width, height=height,
                    )
                    if r.get("ok"):
                        with cols[i % 3]:
                            st.image(out_path, caption=f"{s} ({r['size_kb']} KB, {r['elapsed_sec']}s)")
                    else:
                        cols[i % 3].error(f"{s}: {r.get('error')}")
            else:
                out_path = os.path.join(tempfile.gettempdir(), f"qitian_{style}.png")
                r = generate(
                    style=style, drama_name=drama, account_name=account,
                    output_path=out_path, video_path=video_path,
                    width=width, height=height,
                )
                if r.get("ok"):
                    st.image(out_path,
                              caption=f"{style} ({r['size_kb']} KB, {r['elapsed_sec']}s)",
                              use_container_width=True)
                else:
                    st.error(f"失败: {r.get('error')}")
        else:
            st.info("点左侧 🚀 生成 预览图片")


# ══════════════════════════════════════════════════════════════
# 🔀 去重组合预览 (R4-3)
# ══════════════════════════════════════════════════════════════

def page_dedup_combinations():
    st.title("🔀 去重组合预览")
    st.caption("recipe × image_mode × font × style — AI 可选的全部武器组合")

    from core.processor import list_all_recipes
    from core.qitian import AVAILABLE_STYLES

    # 统计总数
    try:
        from core.font_pool import FONT_POOL, _is_drawtext_safe
        safe_fonts = [p for p in FONT_POOL if _is_drawtext_safe(p)]
    except Exception:
        safe_fonts = []

    recipes = list_all_recipes()
    image_modes = AVAILABLE_STYLES
    watermark_styles = ["stroke", "shadow", "glow", "bold", "random"]

    total_combos = len(recipes) * len(image_modes) * max(len(safe_fonts), 1) * len(watermark_styles)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recipe 数", len(recipes))
    c2.metric("Image mode", len(image_modes))
    c3.metric("Drawtext-safe 字体", len(safe_fonts))
    c4.metric("总组合数", f"{total_combos:,}")

    st.divider()

    # ───── 当前配置显示 ─────
    st.subheader("📋 当前默认配置")
    current = {
        "video.process.mode": get_config("video.process.mode", "mvp_trim_wipe_metadata"),
        "video.process.image_mode": get_config("video.process.image_mode", "qitian_art"),
        "video.process.blend_enabled": get_config("video.process.blend_enabled", "true"),
        "video.process.blend_alpha": get_config("video.process.blend_alpha", "0.50"),
        "video.process.image_opacity": get_config("video.process.image_opacity", "0.30"),
        "video.process.cleanup_temp": get_config("video.process.cleanup_temp", "true"),
        "watermark.font.mode": get_config("watermark.font.mode", "random"),
        "cover.watermark.drama_name.style.stroke": get_config("cover.watermark.drama_name.style.stroke", "true"),
        "cover.watermark.drama_name.style.shadow": get_config("cover.watermark.drama_name.style.shadow", "false"),
        "cover.watermark.drama_name.style.glow": get_config("cover.watermark.drama_name.style.glow", "false"),
        "cover.watermark.drama_name.style.bold": get_config("cover.watermark.drama_name.style.bold", "false"),
        "cover.watermark.drama_name.style.random": get_config("cover.watermark.drama_name.style.random", "false"),
    }
    df_current = pd.DataFrame(
        [(k, v) for k, v in current.items()],
        columns=["config_key", "value"],
    )
    st.dataframe(df_current, use_container_width=True, hide_index=True)

    st.divider()

    # ───── Recipe 池 ─────
    st.subheader("🎥 视频 Recipe 池")
    recipe_info = [
        ("mvp_trim_wipe_metadata", "最简", "-c copy 抹 metadata", "✅"),
        ("light_noise_recode", "轻噪", "noise+重编码", "✅"),
        ("zhizun", "至尊别名", "→ zhizun_overlay", "✅"),
        ("zhizun_overlay", "至尊 overlay", "简单 overlay + libx264 crf 18", "✅"),
        ("zhizun_mode5_pipeline", "至尊完整 ⭐", "blend+zoompan+interleave (matroska 伪装)", "✅"),
        ("kirin_mode6", "麒麟 ⭐", "7 步 interleave (Frida 100% 对齐)", "✅"),
        ("yemao", "夜猫", "4×3 马赛克", "✅"),
        ("bushen", "不闪", "cfg64.exe 独占 (noise+eq)", "✅"),
        ("rongyao", "荣耀", "unsharp + slow + crf 18", "✅"),
        ("wuxianliandui", "无限连队", "libx264 + force_key_frames (60% 对齐)", "⚠️"),
        ("touming_9gong", "透明九宫", "9 帧 tile=3x3 + blend", "✅"),
    ]
    df_recipes = pd.DataFrame(recipe_info,
                                 columns=["Recipe", "中文名", "机制", "状态"])
    st.dataframe(df_recipes, use_container_width=True, hide_index=True)

    st.divider()

    # ───── Image Mode 池 ─────
    st.subheader("🎨 Image mode 池 (pattern 素材风格)")
    image_info = [
        ("qitian_art", "齐天艺术", "多层渐变 + 几何 + 光斑", "~70KB"),
        ("gradient_random", "渐变随机", "纯渐变 + 大字", "~15KB"),
        ("random_shapes", "随机图形", "4×6 几何阵列", "~21KB"),
        ("mosaic_rotate", "马赛克旋转", "视频抽 9 帧 + 旋转 3×3", "~59KB"),
        ("frame_transform", "帧变换", "抽 1 帧 + 滤镜", "~14KB"),
        ("random_chars", "随机字符", "字符阵列 + 黑条压字", "~252KB"),
    ]
    df_img = pd.DataFrame(image_info,
                            columns=["image_mode", "中文名", "机制", "输出尺寸"])
    st.dataframe(df_img, use_container_width=True, hide_index=True)

    st.divider()

    # ───── 字体池 ─────
    st.subheader("🔤 字体池 (watermark.font)")
    if safe_fonts:
        df_fonts = pd.DataFrame(
            [(f.name, f"{f.stat().st_size/1024/1024:.1f} MB", "✅ drawtext-safe")
              for f in safe_fonts],
            columns=["文件名", "大小", "状态"],
        )
        st.dataframe(df_fonts, use_container_width=True, hide_index=True)
    else:
        st.warning("无 drawtext-safe 字体 — 跑 scripts/register_dedup_configs.py + 复制 fonts/")

    st.divider()

    # ───── Watermark 样式池 ─────
    st.subheader("🎭 水印样式 (5 选 N)")
    style_info = [
        ("stroke", "描边", "borderw/bordercolor", "✅ 默认开"),
        ("shadow", "投影", "shadowx/y/shadowcolor", "✅ R3-1"),
        ("glow", "发光", "多层 drawtext 光晕", "✅ R3-2"),
        ("bold", "粗体", "切 bold 字体 (prefer_bold)", "✅ R3-3"),
        ("random", "随机组合", "从 5 种挑 1-3 个", "✅ R3-4"),
    ]
    df_style = pd.DataFrame(style_info,
                              columns=["style", "中文", "技术", "状态"])
    st.dataframe(df_style, use_container_width=True, hide_index=True)

    st.divider()

    # ═══════════════════════════════════════════════════════════
    # ⚡ P4: 一键生成 N 种样本
    # ═══════════════════════════════════════════════════════════
    st.subheader("⚡ 一键生成 N 种样本对比")
    st.caption("上传视频 + 选 N 个 recipe × image_mode 组合, 并发生成, 肉眼选最好的")

    c1, c2 = st.columns([2, 3])
    with c1:
        # 输入: 视频路径 (或选已有的)
        src_options = []
        import os
        for root, _, files in os.walk(r"D:/ks_automation/short_drama_videos"):
            for f in files:
                if f.endswith(".mp4"):
                    p = os.path.join(root, f)
                    if os.path.getsize(p) > 1024 * 1024:  # > 1 MB
                        src_options.append(p)
                        if len(src_options) >= 10:
                            break
            if len(src_options) >= 10:
                break

        src_video = st.selectbox(
            "源视频 (从 short_drama_videos/)",
            options=src_options or ["(无)"],
            format_func=lambda p: os.path.basename(p) if p != "(无)" else p,
        )
        drama = st.text_input("剧名", "小小武神不好惹", key="sgen_drama")
        account = st.text_input("账号", "思莱短剧", key="sgen_acc")
        duration = st.slider("目标时长 (秒)", 10, 60, 15)
        recipes_sel = st.multiselect(
            "选 recipes (会 × image_mode)",
            options=list_all_recipes(),
            default=["zhizun_overlay", "kirin_mode6", "yemao"],
        )
        modes_sel = st.multiselect(
            "选 image_mode (会 × recipe)",
            options=AVAILABLE_STYLES,
            default=["qitian_art", "mosaic_rotate"],
        )
        total = len(recipes_sel) * len(modes_sel)
        st.metric("将生成样本数", total)
        gen_btn = st.button(f"🚀 并发生成 {total} 个样本",
                             disabled=not (src_video and src_video != "(无)"
                                           and recipes_sel and modes_sel))

    with c2:
        if gen_btn:
            import tempfile, time as _t
            out_dir = os.path.join(tempfile.gettempdir(), f"dedup_samples_{int(_t.time())}")
            os.makedirs(out_dir, exist_ok=True)

            from core.processor import process_video
            progress = st.progress(0, text=f"准备生成 {total} 个样本...")
            results = []
            done = 0

            for rec in recipes_sel:
                for mode in modes_sel:
                    done += 1
                    progress.progress(done / total,
                                      text=f"[{done}/{total}] {rec} × {mode}")
                    out_path = os.path.join(out_dir, f"{rec}__{mode}.mp4")
                    try:
                        r = process_video(
                            input_path=src_video,
                            output_dir=out_dir,
                            recipe=rec,
                            target_duration_sec=duration,
                            image_mode=mode,
                            drama_name=drama,
                            account_name=account,
                        )
                        # process_video 生成随机文件名, 我们重命名
                        if r.get("ok") and r.get("output_path"):
                            try:
                                import shutil
                                shutil.move(r["output_path"], out_path)
                                r["output_path"] = out_path
                            except Exception:
                                pass
                        results.append((rec, mode, r))
                    except Exception as e:
                        results.append((rec, mode, {"ok": False, "error": str(e)}))

            progress.progress(1.0, text=f"✅ 完成 {total}")
            st.success(f"生成完成, 保存到 {out_dir}")

            # 网格展示
            st.subheader("🖼️ 样本网格")
            cols_per_row = min(3, total)
            for i, (rec, mode, r) in enumerate(results):
                if i % cols_per_row == 0:
                    cols = st.columns(cols_per_row)
                with cols[i % cols_per_row]:
                    st.markdown(f"**{rec}** × `{mode}`")
                    if r.get("ok"):
                        st.caption(f"{r.get('output_size_mb', '?')} MB, "
                                    f"{r.get('elapsed_sec', '?')}s")
                        out_p = r.get("output_path")
                        if out_p and os.path.isfile(out_p):
                            # 显示视频
                            st.video(out_p)
                            # "设为默认" 按钮
                            if st.button(f"✅ 设为默认", key=f"default_{rec}_{mode}"):
                                from core.app_config import set_
                                set_("video.process.mode", rec)
                                set_("video.process.image_mode", mode)
                                st.success(f"已设 mode={rec}, image_mode={mode}")
                    else:
                        st.error(r.get("error", "unknown")[:100])


def get_config(key, default=""):
    """辅助函数 (避免和 streamlit session_state 冲突)."""
    from core.app_config import get
    v = get(key, default)
    return str(v) if v is not None else default


# ══════════════════════════════════════════════════════════════
# ⚙️ 配置页
# ══════════════════════════════════════════════════════════════

def page_config():
    st.title("⚙️ 系统配置")

    configs = _query("""
        SELECT config_key, config_value, updated_at
        FROM app_config
        ORDER BY config_key
    """)
    if configs.empty:
        st.info("app_config 空")
        return

    # 分组 by prefix (第一级 dot)
    configs["group"] = configs["config_key"].apply(
        lambda k: k.split(".")[0] if "." in k else "misc"
    )

    for group, df_group in configs.groupby("group"):
        with st.expander(f"{group} ({len(df_group)})",
                          expanded=(group in ("ai", "publisher", "executor"))):
            st.dataframe(df_group[["config_key", "config_value", "updated_at"]],
                          use_container_width=True, hide_index=True)


# ══════════════════════════════════════════════════════════════
# 📦 任务监控页 (Phase 2 ABCD)
# ══════════════════════════════════════════════════════════════

def page_task_monitor():
    st.title("📦 任务监控 (ABCD 统一视图)")
    st.caption("A=常规批量 · B=爆款响应 · C=实验 · D=维护风控")

    # ── 顶部 KPI ──
    today = datetime.now().strftime("%Y-%m-%d")
    col1, col2, col3, col4 = st.columns(4)

    # 今日 batches
    batches_today = _query_one(
        """SELECT COUNT(*) AS n FROM batches
           WHERE date(created_at) = ?""",
        (today,),
    )
    col1.metric("今日 Batch 数", batches_today["n"] if batches_today else 0)

    # 当前 running tasks
    running = _query_one(
        "SELECT COUNT(*) AS n FROM task_queue WHERE status='running'"
    )
    col2.metric("Running Tasks", running["n"] if running else 0)

    # 当前 queued tasks
    queued = _query_one(
        "SELECT COUNT(*) AS n FROM task_queue WHERE status='queued'"
    )
    col3.metric("Queued Tasks", queued["n"] if queued else 0)

    # Worker 配置
    try:
        from core.app_config import get as cfg_get
        worker_count = cfg_get("executor.worker_count", 4)
        col4.metric("Worker 配置", str(worker_count))
    except Exception:
        col4.metric("Worker 配置", "n/a")

    st.divider()

    # ── task_source 分布 (ABCD 分类) ──
    st.subheader("任务来源分布 (近 24h)")

    source_dist = _query(
        """SELECT
             COALESCE(task_source, 'planner') AS source,
             COALESCE(status, 'unknown') AS status,
             COUNT(*) AS n
           FROM task_queue
           WHERE datetime(created_at) >= datetime('now','-24 hours','localtime')
           GROUP BY source, status
           ORDER BY source, status"""
    )
    if source_dist.empty:
        st.info("近 24h 无任务 (冷启动 OK)")
    else:
        source_dist["来源"] = source_dist["source"].apply(_ts_cn)
        source_dist["状态"] = source_dist["status"].apply(_st_cn)
        pivot = source_dist.pivot_table(
            index="来源", columns="状态", values="n",
            fill_value=0, aggfunc="sum",
        )
        st.dataframe(pivot, use_container_width=True)

    st.divider()

    # ── task_type 分布 — ★ §27 拆 发布 vs 维护 ──
    st.subheader("任务类型分布 (近 24h) — 🎬 发布 vs ⚙️ 维护")
    type_dist = _query(
        """SELECT
             COALESCE(task_type, 'PUBLISH') AS task_type,
             COUNT(*) AS n
           FROM task_queue
           WHERE datetime(created_at) >= datetime('now','-24 hours','localtime')
           GROUP BY task_type
           ORDER BY n DESC"""
    )
    if not type_dist.empty:
        type_dist["中文"] = type_dist["task_type"].apply(_tt_cn)
        # 拆
        pub_types = type_dist[type_dist["task_type"].isin(PUBLISH_TASK_TYPES)]
        maint_types = type_dist[~type_dist["task_type"].isin(PUBLISH_TASK_TYPES)]
        tab_p, tab_m = st.tabs([
            f"🎬 发布任务 ({pub_types['n'].sum() if not pub_types.empty else 0})",
            f"⚙️ 维护任务 ({maint_types['n'].sum() if not maint_types.empty else 0})",
        ])
        with tab_p:
            if pub_types.empty:
                st.info("近 24h 无发布任务")
            else:
                st.bar_chart(pub_types.set_index("中文")["n"])
        with tab_m:
            if maint_types.empty:
                st.info("近 24h 无维护任务")
            else:
                st.bar_chart(maint_types.set_index("中文")["n"])

    st.divider()

    # ── 最近 Batches 列表 ──
    st.subheader("最近 Batches (20 条)")
    filter_col1, filter_col2 = st.columns(2)
    batch_type_filter = filter_col1.selectbox(
        "按 batch_type 过滤",
        ["全部", "planner", "burst", "experiment", "maintenance"],
        index=0,
    )
    status_filter = filter_col2.selectbox(
        "按 status 过滤",
        ["全部", "running", "completed", "failed"],
        index=0,
    )

    where_clauses = []
    params: list = []
    if batch_type_filter != "全部":
        where_clauses.append("batch_type = ?")
        params.append(batch_type_filter)
    if status_filter != "全部":
        where_clauses.append("status = ?")
        params.append(status_filter)

    sql = "SELECT * FROM batches"
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC LIMIT 20"

    batches = _query(sql, tuple(params))
    if batches.empty:
        st.info("无匹配的 batch")
    else:
        # 计算进度百分比
        def _progress(row):
            total = row.get("total_tasks") or 0
            done = (row.get("completed_tasks", 0) +
                    row.get("failed_tasks", 0) +
                    row.get("cancelled_tasks", 0))
            return f"{done}/{total} ({100*done/total:.0f}%)" if total else "0/0"

        batches["progress"] = batches.apply(_progress, axis=1)
        show_cols = ["batch_id", "batch_type", "batch_name",
                     "progress", "status", "created_at"]
        show_cols = [c for c in show_cols if c in batches.columns]
        st.dataframe(batches[show_cols], use_container_width=True, hide_index=True)

        # 选中某 batch 看详情
        batch_ids = batches["batch_id"].tolist()
        chosen = st.selectbox(
            "查看 batch 详情", ["(选择)"] + batch_ids, index=0
        )
        if chosen != "(选择)":
            try:
                from core.task_manager import list_batch_tasks, get_batch_progress
                progress = get_batch_progress(chosen)
                if progress:
                    st.json(progress)
                tasks = list_batch_tasks(chosen)
                if tasks:
                    st.write(f"**{len(tasks)} tasks**")
                    st.dataframe(pd.DataFrame(tasks),
                                  use_container_width=True,
                                  hide_index=True)
                else:
                    st.warning("此 batch 无关联 task")
            except Exception as e:
                st.error(f"加载详情失败: {e}")

    st.divider()

    # ── 实验监控 (C) ──
    st.subheader("🧪 C 实验任务")
    exps = _query(
        """SELECT * FROM strategy_experiments
           ORDER BY id DESC LIMIT 10"""
    )
    if exps.empty:
        st.info("还没有实验记录 (planner 跑过后会自动产生)")
    else:
        # running vs finished tabs
        tab1, tab2 = st.tabs(["🔴 Running", "✅ Finished"])
        with tab1:
            running_exps = exps[exps["status"] == "running"]
            if running_exps.empty:
                st.info("无 running 实验")
            else:
                for _, r in running_exps.iterrows():
                    with st.expander(
                        f"🔴 {r['experiment_code']} — "
                        f"{r.get('experiment_name','')} "
                        f"({r.get('sample_current',0)}/{r.get('sample_target',0)})"
                    ):
                        st.write(f"**假设**: {r.get('hypothesis','')}")
                        st.write(f"**变量**: {r.get('variable_name','')}")
                        st.write(f"**对照组**: {r.get('control_group','')} vs "
                                  f"{r.get('test_group','')}")
                        # assignments
                        assigns = _query(
                            """SELECT group_name, status, COUNT(*) AS n
                               FROM experiment_assignments
                               WHERE experiment_code = ?
                               GROUP BY group_name, status""",
                            (r["experiment_code"],),
                        )
                        if not assigns.empty:
                            st.dataframe(assigns,
                                          use_container_width=True,
                                          hide_index=True)
                        if r.get("result_summary"):
                            try:
                                summary = json.loads(r["result_summary"])
                                st.json(summary)
                            except Exception:
                                st.code(r["result_summary"][:300])

        with tab2:
            finished = exps[exps["status"] == "finished"]
            if finished.empty:
                st.info("无已完成实验")
            else:
                for _, r in finished.iterrows():
                    with st.expander(
                        f"✅ {r['experiment_code']} — "
                        f"{r.get('experiment_name','')}"
                    ):
                        st.write(f"**假设**: {r.get('hypothesis','')}")
                        st.write(f"**开始**: {r.get('started_at','')}  "
                                  f"**结束**: {r.get('ended_at','')}")
                        if r.get("result_summary"):
                            try:
                                summary = json.loads(r["result_summary"])
                                winner = summary.get("winner_group")
                                if winner:
                                    st.success(f"🏆 Winner: Group **{winner}**"
                                                f" (avg_income="
                                                f"{summary.get('best_avg_income',0):.2f})")
                                st.json(summary)
                            except Exception:
                                st.code(r["result_summary"][:500])

    st.divider()

    # ── 并行度配置 (可查看 + 修改) ──
    st.subheader("⚙️ 并行度配置")
    with st.expander("查看/修改 并行度 configs"):
        keys = [
            "executor.worker_count",
            "executor.per_account_concurrency",
            "executor.per_task_type_publish",
            "executor.per_task_type_maintenance",
            "executor.per_task_type_default",
        ]
        for k in keys:
            cfg_row = _query_one(
                "SELECT config_value FROM app_config WHERE config_key=?", (k,)
            )
            cur_val = cfg_row["config_value"] if cfg_row else "(未设)"
            col_k, col_v, col_btn = st.columns([3, 2, 1])
            col_k.code(k)
            new_val = col_v.text_input(f"value_{k}", value=cur_val,
                                         label_visibility="collapsed",
                                         key=f"cfg_{k}")
            if col_btn.button("保存", key=f"save_{k}"):
                try:
                    _sql_exec(
                        """INSERT OR REPLACE INTO app_config
                           (config_key, config_value, updated_at)
                           VALUES (?, ?, datetime('now','localtime'))""",
                        (k, new_val),
                    )
                    st.success(f"已更新 {k}={new_val}")
                except Exception as e:
                    st.error(f"保存失败: {e}")


# ══════════════════════════════════════════════════════════════
# ✉️ 邀请管理 (2026-04-21 用户要求: 规范化 加号/邀请 流程)
# ══════════════════════════════════════════════════════════════

def page_invitations():
    st.title("✉️ 加号 / 邀请 一条龙")
    st.caption("流程: ①加号 (扫码/贴CK) → ②填主人手机+姓名 → ③立刻邀请 → ④跟踪签约")

    # KPI 顶条
    stats = _query("""
        SELECT
          (SELECT COUNT(*) FROM device_accounts
            WHERE (login_status='logged_in' OR login_status IS NULL)
              AND numeric_uid IS NOT NULL
              AND (owner_phone IS NULL OR owner_phone='')) AS need_owner,
          (SELECT COUNT(*) FROM mcn_invitations
            WHERE signed_status='pending' OR signed_status IS NULL) AS pending,
          (SELECT COUNT(*) FROM mcn_invitations
            WHERE signed_status='signed') AS signed,
          (SELECT COUNT(*) FROM mcn_invitations) AS total
    """).iloc[0]

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("📝 待填主人信息", int(stats["need_owner"]))
    c2.metric("⏳ 邀请中 (pending)", int(stats["pending"]))
    c3.metric("✅ 已签约", int(stats["signed"]))
    c4.metric("📒 邀请账本总行数", int(stats["total"]))

    st.divider()

    tab_need, tab_pending, tab_signed, tab_all = st.tabs([
        f"📝 待邀请 ({int(stats['need_owner'])})",
        f"⏳ 邀请中 ({int(stats['pending'])})",
        f"✅ 已签约 ({int(stats['signed'])})",
        f"📒 完整账本 ({int(stats['total'])})",
    ])

    # ── Tab 1: 待邀请 (有 numeric_uid 但 owner 空, 且未签 MCN) ──
    with tab_need:
        st.caption("活跃账号缺 owner_phone / owner_real_name 且**未签约 MCN**. 填完按 **[邀请]** 立即走 MCN")
        # ★ 2026-04-22 §30 Fix 2: 过滤掉已在 mcn_account_bindings (已签)的账号
        # 避免列出实际 MCN 已签但缺 owner 本地信息的账号 (防重复邀请报错)
        need = _query("""
          SELECT da.id, da.account_name, da.kuaishou_name, da.numeric_uid,
                 COALESCE(da.signed_status,'unknown') AS signed_status,
                 COALESCE(da.mcn_last_invite_at,'') AS last_inv,
                 COALESCE(da.mcn_last_invite_status,'') AS last_inv_status
          FROM device_accounts da
          WHERE (da.login_status='logged_in' OR da.login_status IS NULL)
            AND da.numeric_uid IS NOT NULL
            AND (da.owner_phone IS NULL OR da.owner_phone='')
            AND NOT EXISTS (
                SELECT 1 FROM mcn_account_bindings b
                WHERE CAST(b.kuaishou_uid AS TEXT) = CAST(da.numeric_uid AS TEXT)
            )
          ORDER BY da.id
        """)
        if need.empty:
            st.success("✅ 所有活跃账号都已填主人信息 — 邀请可自动走 step 22")
        else:
            for _, row in need.iterrows():
                aid = int(row["id"])
                with st.expander(f"#{aid}  {row['account_name']}  "
                                 f"(uid={row['numeric_uid']}  快手昵称={row['kuaishou_name'] or '-'})  "
                                 f"[{row['signed_status']}]"):
                    c_phone, c_name, c_btn = st.columns([2, 2, 1.2])
                    phone_val = c_phone.text_input(
                        "主人手机 (11 位)", key=f"phone_{aid}", max_chars=11,
                        placeholder="13800138000")
                    name_val = c_name.text_input(
                        "真实姓名", key=f"name_{aid}",
                        placeholder="黄华")
                    do_invite_immediately = c_btn.checkbox(
                        "提交后立刻邀请", key=f"instant_{aid}", value=True)

                    c_save, c_skip = st.columns([1, 1])
                    if c_save.button("💾 保存 + 邀请", key=f"save_{aid}",
                                      type="primary"):
                        if not phone_val or len(phone_val) < 11:
                            st.error("手机号至少 11 位")
                        elif not name_val.strip():
                            st.error("真实姓名必填")
                        else:
                            # 1. 写 owner
                            try:
                                _sql_exec("""
                                    UPDATE device_accounts SET
                                      owner_phone=?, owner_real_name=?,
                                      owner_filled_at=datetime('now','localtime')
                                    WHERE id=?
                                """, (phone_val, name_val.strip(), aid))
                                st.success(f"✓ 主人信息已保存")
                            except Exception as e:
                                st.error(f"保存失败: {e}")
                                continue
                            # 2. 如果勾了"立刻邀请" → 调 MCNBusiness
                            if do_invite_immediately:
                                with st.spinner("正在发 MCN 邀请..."):
                                    try:
                                        from core.db_manager import DBManager
                                        from core.mcn_business import MCNBusiness
                                        biz = MCNBusiness(DBManager())
                                        resp = biz.invite_and_persist(
                                            target_uid=str(row["numeric_uid"]),
                                            phone=phone_val,
                                            note=f"dashboard@{name_val.strip()}-{row['account_name']}",
                                            contract_month=36,
                                            organization_id=10,
                                        )
                                        if resp.get("success"):
                                            st.success(f"✉️ 邀请已发送 → {row['account_name']}")
                                        else:
                                            st.warning(
                                                f"邀请接口回非 success: "
                                                f"{resp.get('error') or resp.get('message') or resp}")
                                    except Exception as e:
                                        st.error(f"邀请失败: {e}")
                            import time as _tm
                            _tm.sleep(1.5)
                            st.rerun()

    # ── Tab 2: 邀请中 (signed_status='pending') ──
    with tab_pending:
        st.caption("已调 MCN direct_invite 等待本人处理 (客服会发短信). 系统每 6h 自动轮询签约状态.")
        pend = _query("""
          SELECT i.id, i.target_kuaishou_uid, i.target_phone, i.note,
                 i.invited_at, i.last_polled_at,
                 COALESCE(da.account_name,'') AS account_name,
                 COALESCE(da.kuaishou_name,'') AS kuaishou_name
          FROM mcn_invitations i
          LEFT JOIN device_accounts da
            ON CAST(i.target_kuaishou_uid AS TEXT) = CAST(da.numeric_uid AS TEXT)
          WHERE i.signed_status='pending' OR i.signed_status IS NULL
          ORDER BY i.id DESC
        """)
        if pend.empty:
            st.info("💤 当前没有 pending 邀请")
        else:
            for _, row in pend.iterrows():
                inv_id = int(row["id"])
                with st.expander(
                    f"#{inv_id}  {row['account_name'] or row['target_kuaishou_uid']}  "
                    f"手机 {row['target_phone'][:3] + '***' if row['target_phone'] else '-'}  "
                    f"| 邀于 {row['invited_at']}"
                ):
                    st.write(f"**备注**: {row['note']}")
                    st.write(f"**上次轮询**: {row['last_polled_at'] or '从未'}")
                    if st.button("🔄 立刻查签约状态", key=f"poll_{inv_id}"):
                        with st.spinner("查 MCN invitation-records..."):
                            try:
                                from core.db_manager import DBManager
                                from core.mcn_business import MCNBusiness
                                biz = MCNBusiness(DBManager())
                                biz.poll_invitation_status(str(row["target_kuaishou_uid"]))
                                st.success("✓ 刷新完成")
                                import time as _tm; _tm.sleep(1.0); st.rerun()
                            except Exception as e:
                                st.error(f"查询失败: {e}")

    # ── Tab 3: 已签约 ──
    with tab_signed:
        st.caption("已成功签约, 即将在 MCN 开始结算")
        done = _query("""
          SELECT i.id, i.target_kuaishou_uid, i.member_id,
                 i.signed_at, i.target_phone,
                 COALESCE(da.account_name,'') AS account_name,
                 COALESCE(da.kuaishou_name,'') AS kuaishou_name
          FROM mcn_invitations i
          LEFT JOIN device_accounts da
            ON CAST(i.target_kuaishou_uid AS TEXT) = CAST(da.numeric_uid AS TEXT)
          WHERE i.signed_status='signed'
          ORDER BY i.signed_at DESC
        """)
        if done.empty:
            st.info("📭 还没有成功签约的账号")
        else:
            st.dataframe(
                done[["account_name", "kuaishou_name", "target_kuaishou_uid",
                      "member_id", "signed_at", "target_phone"]],
                width='stretch', hide_index=True,
            )

    # ── Tab 4: 完整账本 ──
    with tab_all:
        st.caption("所有邀请记录 (最近 200 行)")
        all_rows = _query("""
          SELECT i.id, i.target_kuaishou_uid, i.signed_status,
                 i.invited_at, i.signed_at, i.member_id,
                 i.target_phone, i.note, i.last_polled_at,
                 COALESCE(da.account_name,'') AS account_name
          FROM mcn_invitations i
          LEFT JOIN device_accounts da
            ON CAST(i.target_kuaishou_uid AS TEXT) = CAST(da.numeric_uid AS TEXT)
          ORDER BY i.id DESC LIMIT 200
        """)
        if all_rows.empty:
            st.info("📭 邀请账本为空. 在"
                    "**📝 待邀请** tab 填写主人信息 + 邀请, 即可写入.")
        else:
            st.dataframe(all_rows, width='stretch', hide_index=True)

    st.divider()
    st.caption(
        "💡 **签约状态**: `pending` (邀请已发, 未处理) → `signed` (已签) / 其他 (拒绝/过期). "
        "ControllerAgent step 22b 每 6h 自动轮询 MCN `/api/accounts/invitation-records` "
        "刷新所有 pending 行. 本页 [立刻查] 按钮也走同一 API."
    )


# ══════════════════════════════════════════════════════════════
# 💎 候选池 (2026-04-23 §31: candidate_builder 产出 TOP N + 6 维评分)
# ══════════════════════════════════════════════════════════════

# 候选池字段中文 / emoji
FRESHNESS_TIER_CN = {
    "today":      "🆕 今日",
    "within_48h": "🔥 48h内",
    "legacy":     "📦 历史",
}
VIOLATION_STATUS_CN = {
    "none":             "✅ 无",
    "appealable":       "⚠️ 可申诉",
    "flow_restricted":  "🚫 限流",
    "hard_locked":      "❌ 硬锁",
    None:               "✅ 无",
}
POOL_STATUS_CN = {
    "pending":   "⏸ 待发",
    "published": "✅ 已发",
    "expired":   "💀 过期",
}


def _fresh_cn(t: str | None) -> str:
    if not t:
        return "—"
    return FRESHNESS_TIER_CN.get(t, t)


def _vio_cn(v: str | None) -> str:
    return VIOLATION_STATUS_CN.get(v, v if v else "✅ 无")


def _pool_status_cn(s: str | None) -> str:
    if not s:
        return "(未知)"
    return POOL_STATUS_CN.get(s, s)


def page_candidate_pool():
    """§31 候选池 TOP N 可视化 — planner 上游数据源."""
    st.title("💎 每日候选池 (candidate_builder TOP N)")
    st.caption(
        "数据链路: **MCN 5 层漏斗** (base → url_available → not_blacklisted → "
        "not_hardlocked → scored) → **6 维评分** (时效 40pt + 链路 20pt + "
        "佣金 15pt + 全网热 10pt + 矩阵 10pt + 惩罚硬减) → **planner 08:00 Path 0 消费**"
    )

    # ── 日期选择 ──
    avail_dates = _query("""
        SELECT DISTINCT pool_date, COUNT(*) AS n,
               ROUND(AVG(composite_score), 1) AS avg_cs,
               MAX(generated_at) AS built_at
        FROM daily_candidate_pool
        GROUP BY pool_date ORDER BY pool_date DESC LIMIT 30
    """)
    if avail_dates.empty:
        st.warning(
            "⚠️ `daily_candidate_pool` 尚无数据.\n\n"
            "- 先跑: `python -m core.candidate_builder`\n"
            "- 或等待 ControllerAgent step 17h (每日 07:45 自动)"
        )
        return

    today_str = datetime.now().strftime("%Y-%m-%d")
    date_options = avail_dates["pool_date"].tolist()
    default_idx = 0
    if today_str in date_options:
        default_idx = date_options.index(today_str)
    pool_date = st.selectbox(
        "候选池日期",
        date_options,
        index=default_idx,
        format_func=lambda d: f"{d}" + (" (今日)" if d == today_str else ""),
    )

    # ── 顶部 KPI ──
    summary = _query_one("""
        SELECT COUNT(*) AS total,
               ROUND(AVG(composite_score), 1) AS avg_cs,
               MAX(composite_score) AS max_cs,
               MIN(composite_score) AS min_cs,
               SUM(CASE WHEN status='pending'   THEN 1 ELSE 0 END) AS n_pending,
               SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS n_published,
               SUM(CASE WHEN status='expired'   THEN 1 ELSE 0 END) AS n_expired,
               SUM(CASE WHEN freshness_tier='today'      THEN 1 ELSE 0 END) AS n_today,
               SUM(CASE WHEN freshness_tier='within_48h' THEN 1 ELSE 0 END) AS n_48h,
               SUM(CASE WHEN freshness_tier='legacy'     THEN 1 ELSE 0 END) AS n_legacy,
               SUM(CASE WHEN violation_status IN ('flow_restricted','hard_locked') THEN 1 ELSE 0 END) AS n_risky,
               MAX(generated_at) AS built_at
        FROM daily_candidate_pool
        WHERE pool_date = ?
    """, (pool_date,)) or {}

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("候选总数", summary.get("total", 0))
    c2.metric("平均分", summary.get("avg_cs") or 0)
    c3.metric("最高分", summary.get("max_cs") or 0)
    c4.metric("🆕 今日剧", summary.get("n_today", 0))
    c5.metric("⚠️ 高风险", summary.get("n_risky", 0))

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("⏸ 待发", summary.get("n_pending", 0))
    c2.metric("✅ 已发", summary.get("n_published", 0))
    c3.metric("💀 过期", summary.get("n_expired", 0))
    c4.metric("🔥 48h内", summary.get("n_48h", 0))

    built_at = summary.get("built_at")
    st.caption(f"生成于 `{built_at}` · 今日 TOP N (config: ai.candidate.topN_per_day)")

    st.divider()

    # ── 主表格 ──
    st.subheader("📋 TOP 候选列表 (按 composite_score 降序)")

    top = _query("""
        SELECT ROW_NUMBER() OVER (ORDER BY composite_score DESC) AS rk,
               drama_name,
               composite_score AS cs,
               score_freshness, score_url_ready, score_commission,
               score_heat, score_matrix, score_penalty,
               freshness_tier, w24h_count, w48h_count,
               cdn_count, pool_count,
               income_desc, income_numeric,
               violation_status, violation_count,
               commission_rate, promotion_type,
               banner_task_id, biz_id,
               status, notes
        FROM daily_candidate_pool
        WHERE pool_date = ?
        ORDER BY composite_score DESC
    """, (pool_date,))

    if top.empty:
        st.info("此日期候选池为空")
        return

    # 展示表 (中文化)
    disp = top.copy()
    disp["时效"] = disp["freshness_tier"].apply(_fresh_cn)
    disp["违规"] = disp["violation_status"].apply(_vio_cn)
    disp["状态"] = disp["status"].apply(_pool_status_cn)
    disp["佣金"] = disp["commission_rate"].apply(
        lambda r: f"{r:.0f}%" if r else "—"
    )
    disp["新鲜池"] = disp.apply(
        lambda r: f"{int(r['w24h_count'])} / {int(r['w48h_count'])}", axis=1
    )
    disp["URL 池"] = disp.apply(
        lambda r: f"{int(r['cdn_count'])} / {int(r['pool_count'])}", axis=1
    )

    # 6 维得分紧凑列
    disp["评分分解"] = disp.apply(
        lambda r: (
            f"时{r['score_freshness']:.0f}·链{r['score_url_ready']:.0f}·"
            f"佣{r['score_commission']:.0f}·热{r['score_heat']:.0f}·"
            f"矩{r['score_matrix']:.0f}"
            + (f"·罚{r['score_penalty']:.0f}" if r['score_penalty'] < 0 else "")
        ),
        axis=1,
    )

    show_cols = [
        "rk", "drama_name", "cs", "评分分解",
        "时效", "新鲜池", "URL 池", "佣金",
        "income_desc", "违规", "状态", "banner_task_id",
    ]
    disp_cn = disp[show_cols].rename(columns={
        "rk": "#",
        "drama_name": "剧名",
        "cs": "总分",
        "income_desc": "全网收益",
        "banner_task_id": "banner_id",
    })

    st.dataframe(
        disp_cn,
        use_container_width=True,
        hide_index=True,
        column_config={
            "总分": st.column_config.ProgressColumn(
                "总分",
                min_value=0,
                max_value=100,
                format="%.1f",
            ),
        },
    )

    # ── 6 维评分堆叠柱状图 (TOP 15) ──
    st.divider()
    st.subheader("📊 TOP 15 · 6 维评分拆解 (堆叠柱图)")
    top15 = top.head(15).copy()
    # 只保留正向评分做 stack
    chart_df = top15.set_index("drama_name")[[
        "score_freshness", "score_url_ready", "score_commission",
        "score_heat", "score_matrix",
    ]].rename(columns={
        "score_freshness":  "时效 (40pt)",
        "score_url_ready":  "链路 (20pt)",
        "score_commission": "佣金 (15pt)",
        "score_heat":       "全网热 (10pt)",
        "score_matrix":     "矩阵 (10pt)",
    })
    try:
        st.bar_chart(chart_df, height=420)
    except Exception as e:
        st.warning(f"chart 渲染失败: {e}")
        st.dataframe(chart_df, use_container_width=True)

    # 惩罚分 (负值, 单独显示)
    penalty_df = top15[top15["score_penalty"] < 0][["drama_name", "score_penalty", "violation_status"]]
    if not penalty_df.empty:
        st.caption("⚠️ 负分惩罚 (软扣, 进入 TOP 15 但未被 L4 硬锁剔除)")
        st.dataframe(
            penalty_df.rename(columns={
                "drama_name": "剧名",
                "score_penalty": "惩罚分",
                "violation_status": "违规等级",
            }),
            use_container_width=True, hide_index=True,
        )

    # ── 分布统计 ──
    st.divider()
    c1, c2 = st.columns(2)
    with c1:
        st.subheader("时效分布")
        fresh_dist = top.groupby("freshness_tier").size().reset_index(name="cnt")
        fresh_dist["时效"] = fresh_dist["freshness_tier"].apply(_fresh_cn)
        st.bar_chart(fresh_dist.set_index("时效")["cnt"])
    with c2:
        st.subheader("违规状态分布")
        vio_dist = top.groupby(top["violation_status"].fillna("none")).size().reset_index(name="cnt")
        vio_dist.columns = ["violation_status", "cnt"]
        vio_dist["违规"] = vio_dist["violation_status"].apply(_vio_cn)
        st.bar_chart(vio_dist.set_index("违规")["cnt"])

    # ── 历史趋势 (近 14 天 avg composite) ──
    st.divider()
    st.subheader("📈 近 14 天候选池健康")
    trend = _query("""
        SELECT pool_date,
               COUNT(*) AS total,
               ROUND(AVG(composite_score), 1) AS avg_cs,
               ROUND(MAX(composite_score), 1) AS max_cs,
               SUM(CASE WHEN status='published' THEN 1 ELSE 0 END) AS published
        FROM daily_candidate_pool
        WHERE pool_date >= date('now', '-14 days')
        GROUP BY pool_date ORDER BY pool_date
    """)
    if not trend.empty:
        st.line_chart(trend.set_index("pool_date")[["avg_cs", "max_cs"]])
        st.dataframe(trend, use_container_width=True, hide_index=True)
    else:
        st.info("历史趋势数据不足")

    # ── 漏斗链路说明 ──
    with st.expander("ℹ️ 5 层漏斗机制 + 6 维评分公式"):
        st.markdown("""
**漏斗** (`core/candidate_builder.py`):
- **L1 base_pool**: `drama_banner_tasks ∪ mcn_drama_library` (剧库全量)
- **L2 url_available**: 有 CDN 或 短链池 URL (> 0)
- **L3 not_blacklisted**: 剔 `drama_blacklist.status='active'`
- **L4 not_hardlocked**: 剔 `spark_violation_dramas_local.violation_count ≥ ai.violation.hard_lock_count` (默认 5)
- **L5 scored**: 余下剧做 6 维评分, 排序取 TOP N

**6 维评分** (权重由 config 控制):
| 维 | 权重 | 指标 |
|---|---|---|
| 时效 | 40pt | w24h (今日新鲜池) / w48h (近 48h) |
| 链路 | 20pt | CDN 缓存数 + 短链池可用数 |
| 佣金 | 15pt | commission_rate |
| 全网热 | 10pt | income_desc (¥856K → log10 加分) |
| 矩阵 | 10pt | 我方近 30 天发过该剧的账号数 (越少越好, 避免重复) |
| 惩罚 | 软减 | 可申诉 -20 / 限流 -50 / 不可申诉 -100 |

**planner 消费** (`strategy_planner_agent.py::_cartesian_assign`):
- Path 0 (主): 读 `daily_candidate_pool WHERE pool_date=today AND composite_score ≥ 40`
- fallback: Path 1a/1b/1c (drama_banner_tasks ∪ high_income_dramas ∪ mcn_drama_library)
        """)


# ══════════════════════════════════════════════════════════════
# 🔗 剧库健康 (2026-04-22 §26.17 承诺页; 2026-04-23 §31 补齐 + 候选池)
# ══════════════════════════════════════════════════════════════

def _count_safe(table: str) -> int:
    """健壮 COUNT (表不存在 → 0)."""
    try:
        r = _query_one(f"SELECT COUNT(*) AS n FROM {table}")
        return int((r or {}).get("n", 0))
    except Exception:
        return 0


def _latest_col_safe(table: str, col: str) -> str | None:
    """取 table.col 最大值 (用作最新 synced_at / generated_at)."""
    try:
        r = _query_one(f"SELECT MAX({col}) AS v FROM {table}")
        return (r or {}).get("v")
    except Exception:
        return None


def _age_badge(iso_ts: str | None, warn_hours: int = 24) -> str:
    """age 人读串 + emoji badge."""
    if not iso_ts:
        return "❔ 从未"
    try:
        dt = datetime.fromisoformat(str(iso_ts).replace("T", " ").split(".")[0])
    except Exception:
        return f"❔ {iso_ts}"
    age_sec = (datetime.now() - dt).total_seconds()
    if age_sec < 60:
        label = f"{int(age_sec)}秒前"
    elif age_sec < 3600:
        label = f"{int(age_sec / 60)}分钟前"
    elif age_sec < 86400:
        label = f"{age_sec / 3600:.1f}小时前"
    else:
        label = f"{age_sec / 86400:.1f}天前"
    emoji = "✅" if age_sec < warn_hours * 3600 else "⚠️"
    return f"{emoji} {label}"


def page_library_health():
    """§26.17 承诺页 — drama_pool / firefly fallback / sync 全链路健康."""
    st.title("🔗 剧库健康 (全链路数据源监控)")
    st.caption(
        "系统全链路数据源: **MCN 实时** (:50002 代签 + MySQL) → **本地镜像** "
        "(sync script 每日 04:00-04:45) → **候选池生成** (07:45) → "
        "**planner 消费** (08:00+). 本页监控每一环健康."
    )

    # ── 6 大镜像表 KPI ──
    st.subheader("📊 6 大数据源健康卡片")

    tables = [
        {
            "key":      "drama_banner_tasks",
            "label":    "🎬 drama_banner_tasks",
            "desc":     "spark_drama_info 镜像 (biz_id + commission)",
            "ts_col":   "created_at",
            "cron":     "每日 04:30",
            "warn":     48,
        },
        {
            "key":      "mcn_url_pool",
            "label":    "🔗 mcn_url_pool",
            "desc":     "kuaishou_urls 镜像 (181万 条短链池)",
            "ts_col":   "synced_at",
            "cron":     "每日 04:15",
            "warn":     48,
        },
        {
            "key":      "mcn_wait_collect_videos",
            "label":    "🆕 wait_collect_videos",
            "desc":     "KS184 '高转化提取' 源表 (22k 今日新鲜池)",
            "ts_col":   "synced_at",
            "cron":     "每 6h 增量",
            "warn":     12,
        },
        {
            "key":      "spark_violation_dramas_local",
            "label":    "⚠️ spark_violation_dramas",
            "desc":     "MCN 违规库 (2760, 不可申诉+可申诉)",
            "ts_col":   "synced_at",
            "cron":     "每日 04:45",
            "warn":     48,
        },
        {
            "key":      "mcn_drama_library",
            "label":    "📚 mcn_drama_library",
            "desc":     "spark_drama_info 全量 (134k 含 income_desc)",
            "ts_col":   "synced_at",
            "cron":     "每日 04:30",
            "warn":     48,
        },
        {
            "key":      "daily_candidate_pool",
            "label":    "💎 daily_candidate_pool",
            "desc":     "candidate_builder 产出 TOP N (planner Path 0 源)",
            "ts_col":   "generated_at",
            "cron":     "每日 07:45",
            "warn":     36,
        },
    ]

    health_rows = []
    for t in tables:
        n = _count_safe(t["key"])
        latest = _latest_col_safe(t["key"], t["ts_col"])
        health_rows.append({
            "表": t["label"],
            "描述": t["desc"],
            "行数": f"{n:,}",
            "最新同步": _age_badge(latest, warn_hours=t["warn"]),
            "cron": t["cron"],
        })

    st.dataframe(
        pd.DataFrame(health_rows),
        use_container_width=True, hide_index=True,
    )

    # ── 交集率 (候选池可用性) ──
    st.divider()
    st.subheader("🎯 关键交集率 (可用剧覆盖)")

    try:
        intersect_1 = _query_one("""
            SELECT COUNT(DISTINCT p.name) AS n
            FROM mcn_url_pool p
            WHERE EXISTS (
                SELECT 1 FROM drama_banner_tasks b
                WHERE b.drama_name = p.name
            )
        """) or {}
        intersect_2 = _query_one("""
            SELECT COUNT(DISTINCT v.name) AS n
            FROM mcn_wait_collect_videos v
            WHERE EXISTS (
                SELECT 1 FROM drama_banner_tasks b
                WHERE b.drama_name = v.name
            )
        """) or {}
        intersect_3 = _query_one("""
            SELECT COUNT(DISTINCT v.drama_title) AS n
            FROM spark_violation_dramas_local v
            WHERE EXISTS (
                SELECT 1 FROM drama_banner_tasks b
                WHERE b.drama_name = v.drama_title
            )
        """) or {}
        n_banner = _count_safe("drama_banner_tasks")

        def _pct(a: int, b: int) -> str:
            return f"{(a * 100.0 / b):.1f}%" if b else "—"

        c1, c2, c3 = st.columns(3)
        c1.metric(
            "🎬 有 banner + 短链池",
            f"{intersect_1.get('n', 0):,}",
            f"/ {n_banner:,} banner 剧 ({_pct(intersect_1.get('n', 0), n_banner)})",
        )
        c2.metric(
            "🆕 有 banner + 新鲜池",
            f"{intersect_2.get('n', 0):,}",
            f"/ {n_banner:,} banner 剧 ({_pct(intersect_2.get('n', 0), n_banner)})",
        )
        c3.metric(
            "⚠️ 有 banner + 违规",
            f"{intersect_3.get('n', 0):,}",
            f"(matches in candidate L3 blacklist filter)",
        )
    except Exception as e:
        st.warning(f"交集统计失败: {e}")

    # ── 当日候选池健康 ──
    st.divider()
    st.subheader("💎 今日候选池 · 一眼看全貌")
    today = datetime.now().strftime("%Y-%m-%d")
    today_pool = _query_one("""
        SELECT COUNT(*) AS n,
               ROUND(AVG(composite_score), 1) AS avg_cs,
               MAX(composite_score) AS max_cs,
               SUM(CASE WHEN freshness_tier='today'      THEN 1 ELSE 0 END) AS n_today,
               SUM(CASE WHEN freshness_tier='within_48h' THEN 1 ELSE 0 END) AS n_48h,
               SUM(CASE WHEN violation_status IN ('flow_restricted','hard_locked') THEN 1 ELSE 0 END) AS n_risky,
               MAX(generated_at) AS built_at
        FROM daily_candidate_pool
        WHERE pool_date = ?
    """, (today,)) or {}

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("候选数", today_pool.get("n", 0))
    c2.metric("平均分", today_pool.get("avg_cs") or 0)
    c3.metric("🆕 今日", today_pool.get("n_today", 0))
    c4.metric("🔥 48h内", today_pool.get("n_48h", 0))
    c5.metric("⚠️ 高风险", today_pool.get("n_risky", 0))

    if not today_pool.get("built_at"):
        st.warning(
            f"⚠️ 今日 `{today}` **候选池未生成**. "
            f"应由 ControllerAgent step 17h 每日 07:45 自动生成."
        )
    else:
        st.caption(f"最近生成: `{today_pool['built_at']}`")

    # ── 同步 cron schedule 参考 ──
    st.divider()
    st.subheader("⏰ ControllerAgent 同步 cron 总表")

    cron_rows = [
        ("17a", "mcn_full_sync",          "每日 04:00", "4 张高价值表 (high_income, blacklist, ...)"),
        ("17b", "sync_mcn_url_pool",      "每日 04:15", "kuaishou_urls (181万)"),
        ("17c", "sync_spark_drama_full",  "每日 04:30", "spark_drama_info (134k → drama_banner_tasks)"),
        ("17d", "sync_account_health",    "每日 04:45", "账号健康 3 源交叉"),
        ("17e", "sync_kuaishou_names",    "每 12h",    "账号昵称 + signed_status"),
        ("17f", "sync_spark_violation",   "每日 04:45", "★ §31 新增 - 违规库 (2760)"),
        ("17g", "sync_wait_collect_inc",  "每 6h",     "★ §31 新增 - 新鲜池 (22k 增量)"),
        ("17h", "candidate_builder",      "每日 07:45", "★ §31 新增 - TOP N 候选池"),
    ]
    st.dataframe(
        pd.DataFrame(
            cron_rows,
            columns=["step", "module", "调度", "作用"],
        ),
        use_container_width=True, hide_index=True,
    )

    # ── 最近运行日志 (agent_run_state) ──
    st.divider()
    st.subheader("🪵 最近运行 (agent_run_state)")
    try:
        last_runs = _query("""
            SELECT agent_name, last_run_at, last_result, last_plan_date
            FROM agent_run_state
            WHERE agent_name IN (
                'mcn_full_sync', 'url_pool_sync', 'spark_drama_sync',
                'account_health_sync', 'ks_names_sync',
                'violation_sync', 'wait_collect_inc', 'candidate_pool_build'
            )
            ORDER BY last_run_at DESC
        """)
        if not last_runs.empty:
            last_runs["age"] = last_runs["last_run_at"].apply(lambda x: _age_badge(x, warn_hours=48))
            st.dataframe(
                last_runs.rename(columns={
                    "agent_name":    "agent",
                    "last_run_at":   "最后跑",
                    "last_result":   "结果",
                    "last_plan_date": "日期",
                    "age":           "距今",
                })[["agent", "age", "最后跑", "结果", "日期"]],
                use_container_width=True, hide_index=True,
            )
        else:
            st.info("尚无运行日志 (autopilot 未跑过同步步骤)")
    except Exception as e:
        st.warning(f"agent_run_state 查询失败: {e}")

    # ── 最近 mcn_member_snapshots 收益 ──
    st.divider()
    st.subheader("💰 MCN 收益镜像 (近 7 天)")
    try:
        income_trend = _query("""
            SELECT snapshot_date,
                   COUNT(DISTINCT member_id) AS n_acct,
                   ROUND(SUM(total_amount), 2) AS total,
                   ROUND(AVG(total_amount), 2) AS avg_per_acct
            FROM mcn_member_snapshots
            WHERE snapshot_date >= date('now', '-7 days')
            GROUP BY snapshot_date ORDER BY snapshot_date
        """)
        if not income_trend.empty:
            st.bar_chart(income_trend.set_index("snapshot_date")["total"])
            st.dataframe(income_trend, use_container_width=True, hide_index=True)
        else:
            st.info("近 7 天无 snapshot (MCN sync 可能已停)")
    except Exception as e:
        st.warning(f"snapshot 查询失败: {e}")

    # ── 说明 ──
    with st.expander("ℹ️ §26.17 + §31 数据源治理原则"):
        st.markdown("""
**核心架构** (用户 2026-04-22 原话):
> "我们系统要走服务器. 本地定时拉服务器数据, 作为备份数据源, 在服务器不可用的时候用本地数据"

**主备分离**:
- **L1 主路**: MCN :50002 代签 / MySQL 实时查 (每次发布前)
- **L2 备份**: 本地 mirror 表 (每日 04:00-04:45 sync, TTL 48h)
- **L3 降级**: MCN 断线 60s 内走 local_backup (熔断节流)

**候选池 (§31 新增)**:
- `candidate_builder` 每日 07:45 从 6 个数据源合成 TOP N
- planner 08:00 Path 0 直消费 (跳过 legacy 1a+1b+1c)
- 候选池空 → planner 静默 fallback legacy (不中断)

**查询优先级** (`core/drama_pool.py::pick_share_urls`):
1. `drama_links` 已解析 CDN 直链 (本地长期缓存)
2. `mcn_url_pool` 短链主池 (1.8M)
3. `mcn_drama_collections` 采集历史 (135k)
        """)


# ══════════════════════════════════════════════════════════════
# 🚦 运营模式 (v6 Day 5-D)
# ══════════════════════════════════════════════════════════════
def page_operation_mode():
    st.title("🚦 运营模式 — Adaptive 5-tier")
    st.caption("v6 Week 1 Day 2 落地, 按可用账号数自动选档, 影响 planner / burst / worker 分配.")

    try:
        from core.operation_mode import (
            current_mode, get_policy, apply_policy, maybe_auto_transition,
            mcn_mode, mcn_status_detail, _MODE_POLICIES, _MODE_THRESHOLDS,
        )
        from core.task_pools import describe_allocation
        from core.app_config import get as cfg_get, set_ as cfg_set
    except Exception as e:
        st.error(f"operation_mode 模块不可用: {e}")
        return

    # --- 当前状态 ---
    mode = current_mode()
    policy = get_policy()
    mcn_md = mcn_mode()

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("档位", mode, f"accounts={policy.account_count}")
    c2.metric("Worker", policy.worker_count)
    c3.metric("MCN mode", mcn_md, "B=降额" if mcn_md == "B" else "healthy")
    c4.metric("Daily Budget", f"{policy.account_count * policy.posts_per_account_per_day} items")

    st.divider()

    # --- 全 5 档对照 ---
    st.subheader("📊 5 档完整策略对照")
    import pandas as pd
    rows = []
    cur_mode = mode
    for m in ("startup", "growth", "volume", "matrix", "scale"):
        p = get_policy(m, use_cache=False)
        rows.append({
            "档位": ("⭐ " if m == cur_mode else "   ") + m,
            "账号数下限": next((t for mm, t in _MODE_THRESHOLDS if mm == m), 0),
            "posts/acct/day": p.posts_per_account_per_day,
            "max_daily_items": p.max_daily_items,
            "workers": p.worker_count,
            "burst": "✅" if p.burst_enabled else "—",
            "burst_th": f"{p.burst_threshold_views:,}",
            "explore": f"{p.experiment_explore_rate:.0%}",
            "cooldown_h": p.cooldown_after_fail_hours,
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # --- 三池分配 ---
    st.subheader("🎯 当前 Worker 三池分配")
    try:
        alloc = describe_allocation()
        a = alloc["allocation"]
        cA, cB, cC = st.columns(3)
        cA.metric("🔥 burst", a.get("burst", 0))
        cB.metric("📋 steady", a.get("steady", 0))
        cC.metric("🛠️ maintenance", a.get("maintenance", 0))
        st.caption(f"策略: **{a.get('strategy')}** · 总 workers={a.get('total')} · burst_enabled={alloc['burst_enabled']}")
    except Exception as e:
        st.warning(f"task_pools 不可用: {e}")

    # --- 手动控制 ---
    st.divider()
    st.subheader("⚙️ 手动控制")
    cc1, cc2, cc3 = st.columns(3)

    force_cur = (cfg_get("operation.mode.force", "") or "").strip()
    with cc1:
        force_new = st.selectbox(
            "强制选 mode (空 = auto)",
            ["", "startup", "growth", "volume", "matrix", "scale"],
            index=["", "startup", "growth", "volume", "matrix", "scale"].index(force_cur)
            if force_cur in _MODE_POLICIES else 0,
        )
        if st.button("保存 force 设置"):
            cfg_set("operation.mode.force", force_new)
            st.success(f"已设 operation.mode.force = {force_new!r}")
            st.rerun()

    with cc2:
        if st.button("🔄 apply 当前策略 (写回 9 项 config)"):
            res = apply_policy(dry_run=False, reason="manual_dashboard")
            msg = f"apply {res['mode']}: changed={len(res['changed'])} keys"
            if res.get("transitioned"):
                msg += f" (🔄 transitioned from {res['old_mode']})"
            st.success(msg)
            with st.expander("详细 diff"):
                st.json(res)

    with cc3:
        if st.button("🧪 maybe_auto_transition 检测"):
            r = maybe_auto_transition()
            st.info(str(r))

    # --- 切换历史 ---
    st.divider()
    st.subheader("📜 近 20 条切换历史")
    try:
        conn = get_conn()
        hist = conn.execute(
            """SELECT old_mode, new_mode, account_count, reason, transitioned_at
               FROM operation_mode_history ORDER BY id DESC LIMIT 20"""
        ).fetchall()
        if hist:
            df = pd.DataFrame([dict(r) for r in hist])
            st.dataframe(df, hide_index=True, use_container_width=True)
        else:
            st.caption("暂无切换历史")
    except Exception as e:
        st.warning(f"读历史失败: {e}")

    # --- MCN A/B 摘要 ---
    st.divider()
    st.subheader(f"📡 MCN mode: **{mcn_md}**")
    mcn_det = mcn_status_detail()
    if mcn_det.get("breakers"):
        st.dataframe(
            pd.DataFrame(mcn_det["breakers"])[
                ["name", "state", "consecutive_fails", "total_failures",
                 "total_successes", "transition_count", "seconds_until_half_open"]
            ],
            hide_index=True, use_container_width=True,
        )
    st.caption(f"详情见 🔌 熔断监控 页.")


# ══════════════════════════════════════════════════════════════
# 🔌 熔断监控 (v6 Day 5-D)
# ══════════════════════════════════════════════════════════════
def page_circuit_breakers():
    st.title("🔌 熔断监控 — Circuit Breakers")
    st.caption("v6 Day 4: 统一 3 状态机 (CLOSED/OPEN/HALF_OPEN), 4 MCN breaker 实时.")

    try:
        from core.circuit_breaker import (
            list_all, snapshot_all, get_breaker, mcn_snapshot, State,
        )
        from core.operation_mode import mcn_mode
    except Exception as e:
        st.error(f"circuit_breaker 模块不可用: {e}")
        return

    # --- 顶部 KPI ---
    all_breakers = list_all()
    if not all_breakers:
        # 首次页面进来可能 registry 空 — 主动加载 4 MCN breaker
        for n in ("mcn_mysql", "mcn_url_realtime", "sig3_primary", "sig3_fallback"):
            get_breaker(n)
        all_breakers = list_all()

    mcn_md = mcn_mode()
    n_open = sum(1 for b in all_breakers.values() if b.is_open())
    n_closed = sum(1 for b in all_breakers.values() if b.is_closed())
    n_half = len(all_breakers) - n_open - n_closed

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("MCN mode", mcn_md, "⚠ degraded" if mcn_md == "B" else "healthy")
    c2.metric("🟢 CLOSED", n_closed)
    c3.metric("🔴 OPEN", n_open)
    c4.metric("🟡 HALF_OPEN", n_half)

    st.divider()

    # --- breaker 列表 ---
    st.subheader("📋 所有 Breakers")
    import pandas as pd
    rows = []
    icon_map = {"closed": "🟢", "open": "🔴", "half_open": "🟡"}
    for snap in snapshot_all():
        rows.append({
            "name": snap["name"],
            "state": icon_map.get(snap["state"], "") + " " + snap["state"],
            "consec_fails": snap["consecutive_fails"],
            "total_fails": snap["total_failures"],
            "total_ok": snap["total_successes"],
            "transitions": snap["transition_count"],
            "seconds_until_half_open": round(snap.get("seconds_until_half_open") or 0, 1),
            "fail_threshold": snap["fail_threshold"],
            "cooldown_sec": snap["cooldown_sec"],
        })
    if rows:
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)

    # --- 手动 reset ---
    st.divider()
    st.subheader("🔧 手动 reset")
    if all_breakers:
        chosen = st.selectbox("选 breaker", list(all_breakers.keys()))
        if st.button("强制 reset 到 CLOSED (清 consec_fails)"):
            br = all_breakers[chosen]
            br.mark_success()  # defensive_reset → CLOSED
            st.success(f"{chosen} reset to CLOSED")
            st.rerun()

    # --- 近 50 条 transitions ---
    st.divider()
    st.subheader("📜 近 50 条 Transitions")
    try:
        conn = get_conn()
        hist = conn.execute(
            """SELECT occurred_at, breaker_name, old_state, new_state, reason
               FROM circuit_breaker_events
               ORDER BY id DESC LIMIT 50"""
        ).fetchall()
        if hist:
            df = pd.DataFrame([dict(r) for r in hist])
            # 着色
            def _color_state(val):
                if val == "open": return "background-color: #ffcccc"
                if val == "closed": return "background-color: #ccffcc"
                if val == "half_open": return "background-color: #ffffcc"
                return ""
            st.dataframe(
                df.style.map(_color_state, subset=["new_state", "old_state"]),
                hide_index=True, use_container_width=True,
            )
        else:
            st.caption("暂无 transitions")
    except Exception as e:
        st.warning(f"读历史失败: {e}")

    # ─── Day 7: account×drama blacklist (80004 闭环) ───
    st.divider()
    st.subheader("🚫 Account × Drama Blacklist (80004 闭环)")
    st.caption("publisher 检测 80004 业务拒 → 自动入表, planner match_scorer 避开. "
               "冷却过期 ControllerAgent 每 1h 清.")

    try:
        from core.account_drama_blacklist import stats as adb_stats, list_active
        s = adb_stats()
        c1, c2, c3 = st.columns(3)
        c1.metric("Total 条目", s["total"])
        c2.metric("Active (未过期)", s["active"])
        c3.metric("Expired", s["expired"])

        if s["by_reason"]:
            st.caption(f"按原因: {s['by_reason']}")
        if s["top_accounts"]:
            st.caption(f"受影响 TOP 账号: " + ", ".join(
                [f"acct={r['account_id']}×{r['n']}" for r in s["top_accounts"]]
            ))

        rows = list_active(limit=50)
        if rows:
            import pandas as pd
            df = pd.DataFrame(rows)
            df = df[["account_id", "drama_name", "reason", "source",
                      "block_count", "first_blocked_at", "last_blocked_at",
                      "expires_at"]]
            st.dataframe(df, hide_index=True, use_container_width=True)

            # 解封按钮
            with st.expander("🔧 手动解封"):
                c1, c2 = st.columns(2)
                with c1:
                    acct_to_rm = st.number_input("account_id", min_value=0, step=1)
                with c2:
                    drama_to_rm = st.text_input("drama_name")
                if st.button("解封"):
                    from core.account_drama_blacklist import remove
                    ok = remove(int(acct_to_rm), drama_to_rm, reason="dashboard_manual")
                    if ok:
                        st.success("已解封")
                        st.rerun()
                    else:
                        st.warning("未找到该 (acct, drama) 条目")
        else:
            st.caption("当前无 active 条目")
    except Exception as e:
        st.warning(f"blacklist 读取失败: {e}")


# ══════════════════════════════════════════════════════════════
# Router
# ══════════════════════════════════════════════════════════════

try:
    if page == "🏠 总览":
        page_overview()
    elif page == "📋 任务":
        page_tasks()
    elif page == "📦 任务监控":
        page_task_monitor()
    elif page == "🩺 自愈":
        page_healing()
    elif page == "💎 收益":
        page_income()
    elif page == "👤 账号详情":
        page_account_detail()
    elif page == "🎬 剧详情":
        page_drama_detail()
    elif page == "🔍 全局搜索":
        page_search()
    elif page == "🛠️ 批量操作":
        page_batch_ops()
    elif page == "📊 导出":
        page_export()
    elif page == "🎨 Qitian":
        page_qitian()
    elif page == "🔀 去重组合":
        page_dedup_combinations()
    elif page == "✉️ 邀请管理":
        page_invitations()
    elif page == "⚙️ 配置":
        page_config()
    elif page == "💎 候选池":        # ★ §31
        page_candidate_pool()
    elif page == "🔗 剧库健康":      # ★ §26.17 承诺页, §31 补齐
        page_library_health()
    elif page == "🚦 运营模式":      # ★ 2026-04-24 v6 Day 5-D
        page_operation_mode()
    elif page == "🔌 熔断监控":      # ★ 2026-04-24 v6 Day 5-D
        page_circuit_breakers()
except Exception as e:
    st.error(f"页面加载失败: {e}")
    with st.expander("详细 traceback"):
        import traceback
        st.code(traceback.format_exc())
