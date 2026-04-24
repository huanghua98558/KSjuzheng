# -*- coding: utf-8 -*-
"""candidate_builder — 每日候选池生成器 (2026-04-23, §31 候选池链路).

【目的】
  把 134k 剧库收敛到 TOP 20-30, 每天 08:00 之前由 ControllerAgent 触发.
  Planner 读 daily_candidate_pool 而不是重新扫 mcn_drama_library — 决策更快 + 更准.

【5 层漏斗】
  L1 (134K→40K)  mcn_drama_library: promotion_type IS NULL / =0 (老萤光 CPS 分佣主力)
                  AND business_type != 2 (排查企业广告)
                  AND (end_time IS NULL OR end_time > now)  (未下架)
  L2 (40K→1.5K)  INNER JOIN mcn_wait_collect_videos (有高转化采集池证据)
                  name = title (剧名精确匹配)
  L3 (1.5K→1.3K) NOT EXISTS drama_blacklist.status='active'  (已拉黑短路)
                  OR (flagged 软保留继续进下一步, 在 score_penalty 处理)
  L4 (1.3K→800)  NOT EXISTS spark_violation_dramas_local 硬锁规则:
                  violation_count >= 5 (累计高频违规, 一律硬锁)
                  OR (status_desc='不可申诉' AND violation_count >= 2)
  L5 (800→TOP 30) 6 维 100 分评分 → TOP N 入 daily_candidate_pool

【6 维评分】
  score_freshness    40pt  wait_collect.created_at 越新越高
                           today=40, within_48h=25, legacy=5
  score_url_ready    20pt  drama_links CDN 直链数 + mcn_url_pool 池容量
                           >=3 CDN → 20, 1-2 CDN → 15, pool≥50 → 10
  score_commission   15pt  commission_rate
                           >=80% → 15, 70-79 → 12, 60-69 → 8, <60 → 3
  score_heat         10pt  income_desc 文本解析 (¥856K 等)
                           log10(yuan) * 2 (cap 10)
  score_matrix       10pt  同剧矩阵账号容量 (已发未超配额数)
                           现阶段默认 +5 (未来接入 account_performance)
  score_penalty      硬减  -9999 (hard_lock) / -100 (不可申诉) / -50 (限制流量)
                           实际硬锁在 L4 已过滤, 此处只处理软扣

【数据依赖】
  mcn_drama_library          (134k, sync_mcn_full 每日)
  mcn_wait_collect_videos    (23k, sync_wait_collect 每 6h)
  spark_violation_dramas_local (2760, sync_spark_violation 每日)
  drama_blacklist            (2760, 历史存量)
  drama_links                (1000, 本地 CDN 缓存)
  mcn_url_pool               (1.8M, 短链主池)
  drama_banner_tasks         (50k, banner_task_id 来源, L1 join 可选)

【调度】 每日 07:45 由 ControllerAgent 触发 (configs §31.6 ai.candidate.*)
"""
from __future__ import annotations

import argparse
import logging
import math
import re
import sqlite3
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core.app_config import get as cfg_get
from core.config import DB_PATH

log = logging.getLogger(__name__)

try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _connect() -> sqlite3.Connection:
    c = sqlite3.connect(DB_PATH, timeout=60)
    c.execute("PRAGMA busy_timeout=60000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


_INCOME_DESC_PATTERN = re.compile(
    r"¥\s*([\d,]+(?:\.\d+)?)\s*([KMB万千百亿]?)", re.IGNORECASE
)

_UNIT_MULTIPLIER = {
    "": 1,
    "千": 1_000,
    "K": 1_000, "k": 1_000,
    "万": 10_000,
    "百": 100,
    "M": 1_000_000, "m": 1_000_000,
    "亿": 100_000_000,
    "B": 1_000_000_000, "b": 1_000_000_000,
}


def _chunked_in(titles: list[str], chunk_size: int = 500):
    """Yield title chunks ≤ chunk_size to avoid SQLite 'too many variables'."""
    for i in range(0, len(titles), chunk_size):
        yield titles[i:i + chunk_size]


def _parse_income_desc(desc: str | None) -> float:
    """解析 MCN income_desc 文本为数值 (元).

    示例:
      '¥856K'      → 856000
      '¥1.2M'      → 1200000
      '¥500'       → 500
      '¥8.5亿'     → 850000000
      None / '' / '待定' → 0
    """
    if not desc or not isinstance(desc, str):
        return 0.0
    m = _INCOME_DESC_PATTERN.search(desc)
    if not m:
        return 0.0
    try:
        num_str = m.group(1).replace(",", "")
        num = float(num_str)
        unit = m.group(2) or ""
        mult = _UNIT_MULTIPLIER.get(unit, 1)
        return num * mult
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────
# 5 层漏斗
# ─────────────────────────────────────────────────────────────────

def funnel_layer1_base_pool(c: sqlite3.Connection) -> list[dict]:
    """L1: mcn_drama_library 筛选老萤光 CPS 主力.

    只留:
      - promotion_type IS NULL OR promotion_type = 0  (CLAUDE.md §2 铁证: 新 CPS type=7 不分佣)
      - business_type != 2 (排查企业广告)
      - end_time 未过期 OR 为空
    """
    now_ts = int(time.time())
    # GROUP BY title: 同名剧可能有 N 条记录 (不同 biz_id / account 绑定)
    # 聚合到最权威的一条: MIN(biz_id) 稳定 + MAX(commission_rate) 最乐观 + 任一有效 income_desc
    rows = c.execute("""
        SELECT title,
               MIN(biz_id)          AS biz_id,
               MAX(commission_rate) AS commission_rate,
               MIN(promotion_type)  AS promotion_type,
               MAX(CASE WHEN income_desc LIKE '¥%' THEN income_desc ELSE NULL END) AS income_desc,
               MAX(end_time)        AS end_time,
               MIN(business_type)   AS business_type
        FROM mcn_drama_library
        WHERE (promotion_type IS NULL OR promotion_type = 0)
          AND (business_type IS NULL OR business_type != 2)
          AND (end_time IS NULL OR end_time = 0 OR end_time > ?)
          AND title IS NOT NULL
          AND LENGTH(TRIM(title)) > 0
        GROUP BY title
    """, (now_ts,)).fetchall()
    return [dict(r) for r in rows]


def funnel_layer2_url_available(
    c: sqlite3.Connection, base: list[dict]
) -> list[dict]:
    """L2: INNER JOIN wait_collect_videos (有高转化采集池证据的 drama).

    只留那些 name 出现过在 wait_collect 的剧 — 证明 MCN 系统之前真的采集过素材.
    同时统计 w24h_count / w48h_count 作为新鲜度信号.

    实现: **反向查** — wait_collect 只 3-4K unique, L1 可能 40K-128K,
    从 wait_collect 聚合所有 stats (一次 SQL), 在 Python 里做交集.
    """
    title_set = {d["title"] for d in base if d.get("title")}
    if not title_set:
        return []

    # 一次 SQL 全拉 wait_collect stats (23K 行, 聚合 ~4K unique name)
    stats_map = {}
    for r in c.execute("""
        SELECT name,
               COUNT(*) AS total_count,
               SUM(CASE WHEN created_at >= datetime('now','-24 hours') THEN 1 ELSE 0 END) AS w24h,
               SUM(CASE WHEN created_at >= datetime('now','-48 hours') THEN 1 ELSE 0 END) AS w48h,
               MAX(created_at) AS latest_created
        FROM mcn_wait_collect_videos
        WHERE name IS NOT NULL AND LENGTH(TRIM(name)) > 0
        GROUP BY name
    """).fetchall():
        if r["name"] in title_set:
            stats_map[r["name"]] = dict(r)

    out = []
    for d in base:
        s = stats_map.get(d["title"])
        if s:
            d["wait_collect_total"] = s["total_count"]
            d["w24h_count"] = s["w24h"] or 0
            d["w48h_count"] = s["w48h"] or 0
            d["latest_collect_at"] = s["latest_created"]
            out.append(d)
    return out


def funnel_layer3_not_blacklisted(
    c: sqlite3.Connection, pool: list[dict]
) -> tuple[list[dict], int]:
    """L3: 过滤 drama_blacklist status='active' 硬拉黑."""
    titles = list({d["title"] for d in pool if d.get("title")})
    if not titles:
        return [], 0
    bl_active = set()
    for batch in _chunked_in(titles):
        placeholders = ",".join("?" * len(batch))
        for r in c.execute(f"""
            SELECT drama_name FROM drama_blacklist
            WHERE drama_name IN ({placeholders}) AND status='active'
        """, batch).fetchall():
            bl_active.add(r["drama_name"])
    out = [d for d in pool if d["title"] not in bl_active]
    return out, len(bl_active)


def funnel_layer4_violation_hardlock(
    c: sqlite3.Connection, pool: list[dict]
) -> tuple[list[dict], int]:
    """L4: 过滤 spark_violation_dramas_local 硬锁规则.

    硬锁条件:
      1. 任一账号 violation_count >= hard_lock_count (默认 5, config)
      2. status_desc='不可申诉' AND violation_count >= 2 (轻微 + 不可申诉 累加)
    """
    hard_lock_count = int(cfg_get("ai.violation.hard_lock_count", 5))
    titles = list({d["title"] for d in pool if d.get("title")})
    if not titles:
        return [], 0
    hardlocked = set()
    for batch in _chunked_in(titles):
        placeholders = ",".join("?" * len(batch))
        for r in c.execute(f"""
            SELECT DISTINCT drama_title
            FROM spark_violation_dramas_local
            WHERE drama_title IN ({placeholders})
              AND (
                violation_count >= ?
                OR (status_desc='不可申诉' AND violation_count >= 2)
              )
        """, list(batch) + [hard_lock_count]).fetchall():
            hardlocked.add(r["drama_title"])
    out = [d for d in pool if d["title"] not in hardlocked]
    return out, len(hardlocked)


# ─────────────────────────────────────────────────────────────────
# 6 维评分 (L5)
# ─────────────────────────────────────────────────────────────────

def score_freshness(w24h: int, w48h: int) -> tuple[float, str]:
    """时效评分 40pt.

    - today (w24h>=1)     → 40
    - within_48h (w48h>=1) → 25
    - 更旧               → 5
    """
    if w24h >= 1:
        return 40.0, "today"
    if w48h >= 1:
        return 25.0, "within_48h"
    return 5.0, "legacy"


def score_url_ready(drama_name: str, cdn_count: int, pool_count: int) -> tuple[float, str]:
    """链路稳定评分 20pt.

    - drama_links CDN>=3 → 20
    - CDN 1-2           → 15
    - pool_count >=50   → 10
    - pool 1-49         → 5
    - 0 0               → 0
    """
    if cdn_count >= 3:
        return 20.0, f"cdn={cdn_count}"
    if cdn_count >= 1:
        return 15.0, f"cdn={cdn_count}_partial"
    if pool_count >= 50:
        return 10.0, f"pool={pool_count}"
    if pool_count >= 1:
        return 5.0, f"pool={pool_count}_thin"
    return 0.0, "no_url"


def score_commission(rate: float | None) -> tuple[float, str]:
    """商业主路评分 15pt.

    rate: 70.0 = 70%
    """
    if rate is None or rate <= 0:
        return 3.0, f"rate={rate}_unknown"
    if rate >= 80:
        return 15.0, f"rate={rate}%"
    if rate >= 70:
        return 12.0, f"rate={rate}%"
    if rate >= 60:
        return 8.0, f"rate={rate}%"
    return 3.0, f"rate={rate}%_low"


def score_heat(income_desc: str | None) -> tuple[float, str, float]:
    """全网热度评分 10pt. 返 (score, reason, income_numeric)."""
    income_num = _parse_income_desc(income_desc)
    if income_num <= 0:
        return 0.0, "no_income_desc", 0.0
    # log10(1) = 0, log10(1万)=4, log10(100万)=6, log10(1亿)=8
    max_bonus = float(cfg_get("ai.heat.income_desc_max_bonus", 30.0))
    scale = float(cfg_get("ai.heat.income_desc_log_scale", 10.0))
    # 实际分档 (10pt cap): log10(income) * 1.25, cap 10
    val = math.log10(income_num + 1) * 1.25
    score = min(10.0, val)
    return score, f"income≈¥{income_num:.0f} log10={math.log10(income_num+1):.2f}", income_num


def score_matrix(c: sqlite3.Connection, drama_name: str) -> tuple[float, str]:
    """矩阵配合评分 10pt.

    基础 5pt, 若 account_performance 有数据则按账号平均收益加分.
    未来可细化 (每个账号历史 income ratio × matrix size).
    """
    try:
        r = c.execute("""
            SELECT COUNT(DISTINCT account_id) AS n_acct
            FROM account_drama_execution_logs
            WHERE drama_name = ?
              AND execution_started_at >= date('now', '-30 days')
        """, (drama_name,)).fetchone()
        n = r["n_acct"] if r else 0
        if n >= 5:
            return 10.0, f"matrix_n={n}"
        if n >= 2:
            return 7.0, f"matrix_n={n}"
        if n >= 1:
            return 5.0, f"matrix_n={n}"
        return 5.0, "matrix_new"  # 新剧默认 +5, 鼓励探索
    except Exception:
        return 5.0, "matrix_default"


def score_penalty_soft(c: sqlite3.Connection, drama_name: str) -> tuple[float, str, str]:
    """软惩罚 (L4 已硬锁) + 分类 violation_status.

    返 (penalty, reason, violation_status)
    violation_status ∈ {none, appealable, flow_restricted, hard_locked}
    """
    try:
        r = c.execute("""
            SELECT sub_biz, status_desc, SUM(violation_count) AS tv, COUNT(*) AS acc_n
            FROM spark_violation_dramas_local
            WHERE drama_title = ?
            GROUP BY sub_biz, status_desc
            ORDER BY tv DESC LIMIT 1
        """, (drama_name,)).fetchone()
        if not r:
            return 0.0, "clean", "none"
        sub_biz, status_desc = r["sub_biz"], r["status_desc"]
        if status_desc == "不可申诉":
            pen = float(cfg_get("ai.violation.unappealable_penalty", -100.0))
            return pen, f"unappealable_tv={r['tv']}", "hard_locked"
        if sub_biz == "限制流量":
            pen = float(cfg_get("ai.violation.flow_restricted_penalty", -50.0))
            return pen, f"flow_restricted_tv={r['tv']}", "flow_restricted"
        if status_desc == "可申诉":
            pen = float(cfg_get("ai.violation.appealable_penalty", -20.0))
            return pen, f"appealable_tv={r['tv']}", "appealable"
        return 0.0, f"other_sub_biz={sub_biz}", "none"
    except Exception:
        return 0.0, "err", "none"


# ─────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────

def build_candidate_pool(pool_date: str | None = None, dry_run: bool = False) -> dict:
    """生成 N 个候选剧进 daily_candidate_pool.

    Args:
        pool_date: YYYY-MM-DD, 缺省用今天
        dry_run: 不写 DB, 只返结果

    Returns:
        {
            "pool_date": "2026-04-23",
            "layer_counts": {L1: 40000, L2: 1500, L3: 1300, L4: 800},
            "top_n_inserted": 30,
            "elapsed_sec": 12.5,
            "top_list": [{drama_name, composite_score, ...}, ...]
        }
    """
    t0 = time.time()
    pool_date = pool_date or datetime.now().strftime("%Y-%m-%d")
    top_n = int(cfg_get("ai.candidate.topN_per_day", 30))
    min_score = float(cfg_get("ai.candidate.min_composite_score", 40.0))

    log.info(f"[candidate] start build pool_date={pool_date} topN={top_n}")

    w_fresh = float(cfg_get("ai.candidate.w_freshness", 40.0))
    w_url = float(cfg_get("ai.candidate.w_url_ready", 20.0))
    w_comm = float(cfg_get("ai.candidate.w_commission", 15.0))
    w_heat = float(cfg_get("ai.candidate.w_heat", 10.0))
    w_matrix = float(cfg_get("ai.candidate.w_matrix", 10.0))

    # 5 层漏斗
    with _connect() as c:
        L1 = funnel_layer1_base_pool(c)
        log.info(f"  L1 base_pool:      {len(L1):,}")

        L2 = funnel_layer2_url_available(c, L1)
        log.info(f"  L2 url_available:  {len(L2):,}")

        L3, bl_n = funnel_layer3_not_blacklisted(c, L2)
        log.info(f"  L3 not_blacklisted:{len(L3):,} (剔 {bl_n} 黑名单)")

        L4, hl_n = funnel_layer4_violation_hardlock(c, L3)
        log.info(f"  L4 not_hardlocked: {len(L4):,} (剔 {hl_n} 硬锁)")

        # L5: 6 维评分
        #   URL stats 批量拉 (chunked, 避免每 drama 一次 SQL + 避 SQLite 999 var 限制)
        titles = [d["title"] for d in L4]
        cdn_stats, pool_stats, banner_map = {}, {}, {}
        for batch in _chunked_in(titles):
            ph = ",".join("?" * len(batch))
            for r in c.execute(f"""
                SELECT drama_name, COUNT(*) AS cnt
                FROM drama_links
                WHERE drama_name IN ({ph})
                  AND (url_resolved_at IS NOT NULL OR status='verified')
                GROUP BY drama_name
            """, batch).fetchall():
                cdn_stats[r["drama_name"]] = r["cnt"]
            for r in c.execute(f"""
                SELECT name, COUNT(*) AS cnt
                FROM mcn_url_pool
                WHERE name IN ({ph})
                GROUP BY name
            """, batch).fetchall():
                pool_stats[r["name"]] = r["cnt"]
            for r in c.execute(f"""
                SELECT drama_name, banner_task_id, commission_rate, promotion_type
                FROM drama_banner_tasks
                WHERE drama_name IN ({ph})
            """, batch).fetchall():
                banner_map[r["drama_name"]] = dict(r)

        # 逐 drama 打分
        scored = []
        for d in L4:
            title = d["title"]
            w24h = d.get("w24h_count", 0)
            w48h = d.get("w48h_count", 0)
            cdn_n = cdn_stats.get(title, 0)
            pool_n = pool_stats.get(title, 0)
            br = banner_map.get(title, {})

            s_fresh, r_fresh = score_freshness(w24h, w48h)
            s_url, r_url = score_url_ready(title, cdn_n, pool_n)
            # 优先用 banner 的 commission_rate (更权威), 否则 mcn_drama_library
            comm_rate = br.get("commission_rate") or d.get("commission_rate")
            s_comm, r_comm = score_commission(comm_rate)
            s_heat, r_heat, income_num = score_heat(d.get("income_desc"))
            s_matrix, r_matrix = score_matrix(c, title)
            s_pen, r_pen, violation_status = score_penalty_soft(c, title)

            # 权重 scale (按 config 比例调)
            norm_fresh = s_fresh * (w_fresh / 40.0)
            norm_url = s_url * (w_url / 20.0)
            norm_comm = s_comm * (w_comm / 15.0)
            norm_heat = s_heat * (w_heat / 10.0)
            norm_matrix = s_matrix * (w_matrix / 10.0)

            composite = norm_fresh + norm_url + norm_comm + norm_heat + norm_matrix + s_pen

            # freshness tier
            if w24h >= 1:
                fresh_tier = "today"
            elif w48h >= 1:
                fresh_tier = "within_48h"
            else:
                fresh_tier = "legacy"

            scored.append({
                "drama_name": title,
                "banner_task_id": br.get("banner_task_id"),
                "biz_id": d.get("biz_id"),
                "commission_rate": comm_rate,
                "promotion_type": br.get("promotion_type") or d.get("promotion_type"),
                "freshness_tier": fresh_tier,
                "w24h_count": w24h,
                "w48h_count": w48h,
                "cdn_count": cdn_n,
                "pool_count": pool_n,
                "income_desc": d.get("income_desc"),
                "income_numeric": income_num,
                "violation_status": violation_status,
                "violation_count": 0,   # L4 已过滤, 残留 violation 等级较低
                "score_freshness": round(norm_fresh, 2),
                "score_url_ready": round(norm_url, 2),
                "score_commission": round(norm_comm, 2),
                "score_heat": round(norm_heat, 2),
                "score_matrix": round(norm_matrix, 2),
                "score_penalty": round(s_pen, 2),
                "composite_score": round(composite, 2),
                "_reasons": {
                    "freshness": r_fresh,
                    "url": r_url,
                    "comm": r_comm,
                    "heat": r_heat,
                    "matrix": r_matrix,
                    "penalty": r_pen,
                },
            })

        # ★ 2026-04-24 v6 Day 8+: L0 层 hot_photos 补充
        # 热点剧即使没在 L1-L4 漏斗里 (未必有 banner), 也要进候选
        # 宽松策略: 近 24h 任何 hot_photo 都入, 用 views_per_hour 打分
        if cfg_get("ai.candidate.use_hot_photos_layer0", True):
            layer0_hours = int(cfg_get("ai.candidate.hot_photos_layer0_hours", 24))
            layer0_top = int(cfg_get("ai.candidate.hot_photos_layer0_topN", 30))

            # 已入 scored 的剧名集合 (避免重复)
            scored_dramas = {s["drama_name"] for s in scored if s.get("drama_name")}

            hot_rows = c.execute(f"""
                SELECT drama_name,
                       MAX(view_count) AS max_views,
                       MAX(views_per_hour) AS max_vph,
                       MAX(like_ratio) AS max_like_ratio,
                       MIN(age_hours_at_discover) AS min_age,
                       COUNT(*) AS n_photos,
                       MAX(first_seen_at) AS latest_seen
                FROM hot_photos
                WHERE first_seen_at > datetime('now', '-' || ? || ' hours', 'localtime')
                  AND drama_name IS NOT NULL AND drama_name != ''
                GROUP BY drama_name
                ORDER BY max_vph DESC
                LIMIT ?
            """, (layer0_hours, layer0_top)).fetchall()

            l0_added = 0
            for r in hot_rows:
                drama_name = r["drama_name"]
                if drama_name in scored_dramas:
                    continue   # 已在 L1-L4 scored 里, 下面会自然合并

                # L0 简单打分: 热度驱动, 不做复杂维度
                max_vph = r["max_vph"] or 0
                max_views = r["max_views"] or 0
                import math
                s_hot = min(50.0, math.log10(max_vph + 1) * 10)

                # 构造简化 scored 条目 (用占位字段, banner / commission 等后续补)
                # 关键: composite_score 用热度分, 让它能进 TOP N
                scored.append({
                    "drama_name": drama_name,
                    "banner_task_id": None,    # 后续 planner 会查 mcn_drama_lookup 补
                    "biz_id": None,
                    "commission_rate": None,
                    "promotion_type": None,
                    "freshness_tier": "hot",    # 新档
                    "w24h_count": r["n_photos"],
                    "w48h_count": r["n_photos"],
                    "cdn_count": 0,              # 未 JOIN, 但 hot_photos.cdn_url 已存 drama_links
                    "pool_count": 0,
                    "income_desc": None,
                    "income_numeric": 0,
                    "violation_status": "none",
                    "violation_count": 0,
                    "score_freshness": 0.0,
                    "score_url_ready": 0.0,
                    "score_commission": 0.0,
                    "score_heat": round(s_hot, 2),   # 热度分放到 heat 维
                    "score_matrix": 0.0,
                    "score_penalty": 0.0,
                    "composite_score": round(s_hot, 2),  # 纯热度驱动
                    "_reasons": {
                        "source": "hot_photos_layer0",
                        "max_views": max_views,
                        "max_vph": round(max_vph, 1),
                        "min_age_h": round(r["min_age"] or 0, 1),
                    },
                })
                l0_added += 1
            if l0_added:
                log.info(f"  L0 hot_photos:     +{l0_added:,} (近{layer0_hours}h 热点剧补充)")

        # 排序 + 截 TOP N + 门槛
        scored.sort(key=lambda x: x["composite_score"], reverse=True)
        final = [s for s in scored if s["composite_score"] >= min_score][:top_n]
        log.info(f"  L5 scored:         {len(scored):,}, final TOP {len(final):,} "
                 f"(min_score>={min_score})")

        if not dry_run and final:
            # 写 DB (同 pool_date 先删 pending, 留 published)
            c.execute("""
                DELETE FROM daily_candidate_pool
                WHERE pool_date=? AND status='pending'
            """, (pool_date,))
            c.commit()
            inserted = 0
            for s in final:
                try:
                    c.execute("""
                        INSERT OR REPLACE INTO daily_candidate_pool
                        (pool_date, drama_name, banner_task_id, biz_id,
                         commission_rate, promotion_type,
                         freshness_tier, w24h_count, w48h_count,
                         cdn_count, pool_count,
                         income_desc, income_numeric,
                         violation_status, violation_count,
                         score_freshness, score_url_ready, score_commission,
                         score_heat, score_matrix, score_penalty, composite_score,
                         status, notes)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """, (
                        pool_date, s["drama_name"], s["banner_task_id"], s["biz_id"],
                        s["commission_rate"], s["promotion_type"],
                        s["freshness_tier"], s["w24h_count"], s["w48h_count"],
                        s["cdn_count"], s["pool_count"],
                        s["income_desc"], s["income_numeric"],
                        s["violation_status"], s["violation_count"],
                        s["score_freshness"], s["score_url_ready"], s["score_commission"],
                        s["score_heat"], s["score_matrix"], s["score_penalty"],
                        s["composite_score"],
                        "pending",
                        f"fresh={s['_reasons']['freshness']}/url={s['_reasons']['url']}"
                        f"/comm={s['_reasons']['comm']}/heat={s['_reasons']['heat']}",
                    ))
                    inserted += 1
                except Exception as e:
                    log.warning(f"  INSERT fail drama={s['drama_name']}: {e}")
            c.commit()

    elapsed = time.time() - t0
    return {
        "pool_date": pool_date,
        "layer_counts": {"L1": len(L1), "L2": len(L2), "L3": len(L3), "L4": len(L4),
                         "L5_scored": len(scored), "final": len(final)},
        "top_n_inserted": 0 if dry_run else (len(final) if final else 0),
        "elapsed_sec": round(elapsed, 1),
        "top_list": final,
    }


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description="每日候选池生成器")
    ap.add_argument("--dry-run", action="store_true", help="不写 DB")
    ap.add_argument("--pool-date", help="YYYY-MM-DD, 默认今天")
    ap.add_argument("--top-preview", type=int, default=10, help="打印 TOP N")
    args = ap.parse_args()

    result = build_candidate_pool(pool_date=args.pool_date, dry_run=args.dry_run)
    print(f"\n=== pool_date={result['pool_date']} ({result['elapsed_sec']}s) ===")
    print(f"层级漏斗:")
    for k, v in result["layer_counts"].items():
        print(f"  {k:10s} {v:,}")
    print(f"\n写入 {result['top_n_inserted']} 条 (dry_run={args.dry_run})")

    print(f"\n=== TOP {args.top_preview} (by composite_score) ===")
    for i, s in enumerate(result["top_list"][:args.top_preview], 1):
        print(f"\n{i:2d}. {s['drama_name']:20s}  score={s['composite_score']}")
        print(f"    freshness={s['score_freshness']:>5.1f} ({s['_reasons']['freshness']})")
        print(f"    url      ={s['score_url_ready']:>5.1f} ({s['_reasons']['url']})")
        print(f"    comm     ={s['score_commission']:>5.1f} ({s['_reasons']['comm']})")
        print(f"    heat     ={s['score_heat']:>5.1f} ({s['_reasons']['heat']})")
        print(f"    matrix   ={s['score_matrix']:>5.1f} ({s['_reasons']['matrix']})")
        print(f"    penalty  ={s['score_penalty']:>5.1f} ({s['_reasons']['penalty']})")

    return 0


if __name__ == "__main__":
    sys.exit(main())
