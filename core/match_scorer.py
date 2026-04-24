# -*- coding: utf-8 -*-
"""账号 × 剧 match 评分 — Week 3 Task A + §31 候选池升级 (2026-04-23).

目的: 把 "按 tier 均摊配额" 升级到 "账号×剧笛卡尔积 + 评分分派".

match_score(account, drama) 核心因子:
    + tier_weight               (20-90, 账号等级)
    + income_bonus              (0-50, 账号近 7 天收益)
    + heat_bonus                (0-30, drama_banner_tasks 近 30 天收益热度)
    + diversity_bonus           (0-20, 账号最近没发过此剧)
    - cooldown_penalty          (0 ~ -1000, 24h 内同剧硬拒)
    - recent_fail_penalty       (0 ~ -20, 近 1h 失败)

MCN 镜像信号 (依赖定时同步):
    + high_income_bonus         (0-30, spark_highincome_dramas TOP)
    + hot_ranking_bonus         (0-25, drama_hot_rankings 近 7 天)
    + url_readiness_bonus       (-10 ~ +10, drama_links 验证状态)
    + vertical_match_bonus      (±20, 账号垂类 ∩ 剧关键词)
    - blacklist_penalty         (-200 软 / -9999 硬, drama_blacklist)
    - drama_cooldown_penalty    (-500, watchdog 写的 drama_links.cooldown_until)
    - quarantined_penalty       (-1000, drama_links.quarantined_at ≥ 5次失败)
    - banner_existence_check    (-5000 硬, drama_name 不在 drama_banner_tasks)

★ §31 候选池升级 (2026-04-23, 对齐 migrate_v39):
    - violation_penalty         (-20/-50/-100 软 / -9999 硬锁, spark_violation_dramas_local 2760 行)
    + income_desc_bonus         (0-30, mcn_drama_library.income_desc ¥ log10 映射)
    + freshness_bonus           (0-20, mcn_wait_collect_videos 24h/48h 新鲜池 depth)

记忆信号 (Layer 2):
    + affinity_signal (0-15) + avoid_penalty (-50) + trust_signal (±10) + novelty_bonus (+8)

注: 评分不涉及时间窗分配 — 那是 planner 后续步骤.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


# Tier 基础权重
_TIER_WEIGHT = {
    "viral": 90, "established": 70,
    "warming_up": 50, "testing": 30, "new": 20,
    "frozen": -1000,  # 冻结账号永不分派
}


def _connect() -> sqlite3.Connection:
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


# ─────────────────────────────────────────────────────────────────
# 单因子评分函数
# ─────────────────────────────────────────────────────────────────

def _tier_weight(account_tier: str) -> float:
    return _TIER_WEIGHT.get(account_tier, 0)


def _account_recent_income(account_id: int, days: int = 7) -> float:
    """账号近 N 天 fluorescent 收益总和."""
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT SUM(COALESCE(total_amount, 0)) AS total
                   FROM mcn_member_snapshots
                   WHERE member_id = (SELECT numeric_uid FROM device_accounts
                                       WHERE id = ?)
                     AND snapshot_date >= date('now', ?)""",
                (int(account_id), f"-{days} days"),
            ).fetchone()
            return float(r["total"] or 0.0)
    except Exception as e:
        log.debug("[match] account_recent_income failed: %s", e)
        return 0.0


def _drama_heat(drama_name: str) -> float:
    """剧本身近 30 天收益热度."""
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT recent_income_sum FROM drama_banner_tasks
                   WHERE drama_name = ?
                   ORDER BY recent_income_sum DESC LIMIT 1""",
                (drama_name,),
            ).fetchone()
            return float(r["recent_income_sum"] or 0.0) if r else 0.0
    except Exception as e:
        log.debug("[match] drama_heat failed: %s", e)
        return 0.0


# ─────────────────────────────────────────────────────────────────
# 2026-04-20 ★ Path 1+2: high_income_dramas + drama_blacklist 镜像表接入
# ─────────────────────────────────────────────────────────────────
# planner 一个 cycle 调 match_score 650 次 (13 acc × 50 dramas), 每次都 SQL 太慢.
# 用 module-level cache + 2 min TTL 摊销.
_HIGH_INCOME_CACHE: dict[str, int] = {}    # drama_name -> rank_position
_BLACKLIST_CACHE: dict[str, str] = {}      # drama_name -> status ('active' | 'flagged')
_HOT_RANK_CACHE: dict[str, int] = {}       # drama_name -> best_rank (近 N 天 caption 命中 min rank)
_VERIFIED_CACHE: dict[str, str] = {}       # drama_name -> 'verified'|'pending'|'broken' (step 20 2026-04-20)
_COOLDOWN_CACHE: dict[str, str] = {}       # drama_name -> cooldown_until ISO  (drama level URL cooldown, 2026-04-21)
_QUARANTINED_CACHE: dict[str, int] = {}    # drama_name -> n_quarantined (所有 URL 都 quarantined 的剧, 2026-04-21)
_BANNER_DRAMA_SET: set[str] = set()        # ★ 2026-04-21 14:30 hotfix: drama_banner_tasks.drama_name 集合 (在集合内才合法)
# ★ 2026-04-23 §31 候选池升级: 3 个新缓存对齐 migrate_v39 新表
_VIOLATION_CACHE: dict[str, dict] = {}     # drama_name -> {"max_count", "worst_status", "sub_bizs"}  (spark_violation_dramas_local 聚合)
_INCOME_DESC_CACHE: dict[str, float] = {}  # drama_name -> parsed ¥ amount (mcn_drama_library.income_desc, log scale)
_FRESHNESS_CACHE: dict[str, dict] = {}     # drama_name -> {"w24h", "w48h", "total"}  (mcn_wait_collect_videos)
_CACHE_LOADED_AT: float = 0
_CACHE_TTL_SEC: float = 120                # 2 min, 一个 planner cycle 内复用


def _maybe_reload_caches():
    """加载/刷新 high_income + blacklist + hot_ranking 缓存. 调一次后 2min 内复用."""
    import time as _t
    global _CACHE_LOADED_AT
    if _t.time() - _CACHE_LOADED_AT < _CACHE_TTL_SEC and _HIGH_INCOME_CACHE:
        return  # 缓存仍新鲜
    try:
        with _connect() as c:
            _HIGH_INCOME_CACHE.clear()
            for r in c.execute(
                "SELECT title, rank_position FROM high_income_dramas "
                "WHERE rank_position IS NOT NULL"
            ):
                _HIGH_INCOME_CACHE[r["title"]] = r["rank_position"]

            _BLACKLIST_CACHE.clear()
            for r in c.execute(
                "SELECT drama_name, status FROM drama_blacklist "
                "WHERE status IN ('active','flagged')"
            ):
                _BLACKLIST_CACHE[r["drama_name"]] = r["status"]

            # ★ 2026-04-20 新增 hot_ranking cache
            # drama_hot_rankings 按 keyword+rank 存, 没 drama_name 字段.
            # 做法: 对剧池每个 drama, 用 caption 包含 drama_name 来匹配.
            # 但剧池是动态的, 不能预先 join. 换思路:
            # 预先建 "(drama_name in caption/tags, best_rank)" 的反向索引.
            # 由于 pool 可大到 134k, 只缓存近 N 天 hot_rankings 条目
            # 解释 caller 每次 match_score 时 O(1) 查 dict.
            lookback = int(cfg_get("ai.planner.hot_ranking.lookback_days", 7))
            _HOT_RANK_CACHE.clear()
            try:
                # 取近 N 天所有 hot_rankings row, 每条: caption + tags + rank
                # 我们看 pool 中任何 drama_name 是否作为子串出现过 (O(pool × rows))
                # planner cycle pool ~200, hot_rankings 近 7 天典型 < 1000 → 20万次 substring, ~秒级 OK
                hot_rows = c.execute(
                    """SELECT caption, COALESCE(tags,''), rank
                       FROM drama_hot_rankings
                       WHERE snapshot_date >= date('now', ? || ' days')""",
                    (f"-{lookback}",)
                ).fetchall()
                # 扫 drama_banner_tasks + mcn_drama_library + high_income 当作候选 drama_name set
                drama_names = set()
                for rr in c.execute("SELECT drama_name FROM drama_banner_tasks"):
                    if rr["drama_name"]:
                        drama_names.add(rr["drama_name"])
                for rr in c.execute(
                    "SELECT title FROM mcn_drama_library WHERE title IS NOT NULL"
                ):
                    drama_names.add(rr["title"])
                for rr in c.execute("SELECT title FROM high_income_dramas"):
                    if rr["title"]:
                        drama_names.add(rr["title"])
                # 构反索 (sub-string match)
                # 优化: drama_name 通常 >= 3 字符, 直接 substring in big text
                for caption, tags, rank in hot_rows:
                    blob = f"{caption or ''} {tags or ''}"
                    if not blob:
                        continue
                    for name in drama_names:
                        if len(name) < 3:
                            continue
                        if name in blob:
                            cur = _HOT_RANK_CACHE.get(name)
                            if cur is None or rank < cur:
                                _HOT_RANK_CACHE[name] = rank
            except Exception as ee:
                log.debug("[match] hot_ranking cache build failed: %s", ee)

        # ★ 2026-04-20 step⑤: drama_links 验证状态 → verified/pending/broken
        _VERIFIED_CACHE.clear()
        try:
            with _connect() as c:
                for r in c.execute(
                    """SELECT drama_name,
                              MAX(CASE
                                WHEN status='pending' AND verified_at IS NOT NULL THEN 'verified'
                                WHEN status='pending' THEN 'pending'
                                WHEN status='broken' THEN 'broken'
                                ELSE 'other'
                              END) AS best_status
                       FROM drama_links
                       WHERE drama_name IS NOT NULL
                       GROUP BY drama_name"""
                ):
                    _VERIFIED_CACHE[r["drama_name"]] = r["best_status"]
        except Exception as ee:
            log.debug("[match] verified cache failed: %s", ee)

        # ★ 2026-04-21 drama cooldown cache (URL 级联失败冷却)
        _COOLDOWN_CACHE.clear()
        try:
            with _connect() as c:
                for r in c.execute(
                    """SELECT drama_name, MAX(cooldown_until) AS cd
                       FROM drama_links
                       WHERE cooldown_until IS NOT NULL
                         AND cooldown_until > datetime('now')
                       GROUP BY drama_name"""
                ):
                    _COOLDOWN_CACHE[r["drama_name"]] = r["cd"]
        except Exception as ee:
            log.debug("[match] cooldown cache failed: %s", ee)

        # ★ 2026-04-21 14:30 hotfix: banner 存在校验 cache
        # 今日事故: AI 选了 "师娘" 等简称剧, 本地 banner 没对应, 14 条 PUBLISH 全挂 no_urls
        # 修: 只让 AI 选 drama_banner_tasks 里有的剧 (有真 banner_task_id, 可发可结算)
        _BANNER_DRAMA_SET.clear()
        try:
            with _connect() as c:
                for r in c.execute(
                    "SELECT DISTINCT drama_name FROM drama_banner_tasks "
                    "WHERE drama_name IS NOT NULL AND drama_name != ''"
                ):
                    _BANNER_DRAMA_SET.add(r["drama_name"])
        except Exception as ee:
            log.debug("[match] banner drama set cache failed: %s", ee)

        # ★ 2026-04-21 Top 3: drama 全部 URL quarantined 的 → 禁派
        # 判定: drama 的所有 drama_url 都 quarantined_at IS NOT NULL AND < quarantine_days
        _QUARANTINED_CACHE.clear()
        try:
            quarantine_days = int(cfg_get("ai.url_health.quarantine_days", 7))
            with _connect() as c:
                for r in c.execute(
                    f"""SELECT drama_name,
                               COUNT(*) AS total,
                               SUM(CASE
                                     WHEN quarantined_at IS NOT NULL
                                       AND (julianday('now') - julianday(quarantined_at))
                                           <= {quarantine_days}
                                     THEN 1 ELSE 0
                                   END) AS n_quarantined
                        FROM drama_links
                        WHERE drama_name IS NOT NULL AND drama_name != ''
                        GROUP BY drama_name
                        HAVING n_quarantined > 0 AND n_quarantined = total"""
                ):
                    _QUARANTINED_CACHE[r["drama_name"]] = r["n_quarantined"]
        except Exception as ee:
            log.debug("[match] quarantined cache failed: %s", ee)

        # ★ 2026-04-23 §31 新表 1/3: spark_violation_dramas_local 聚合
        # 按 drama_title 聚合: MAX(violation_count), 最严 status_desc, 所有 sub_biz.
        # "不可申诉" > "可申诉" (严重度); "屏蔽流量" > "限制流量"
        _VIOLATION_CACHE.clear()
        try:
            with _connect() as c:
                for r in c.execute(
                    """SELECT drama_title,
                              MAX(violation_count) AS max_count,
                              MAX(CASE WHEN status_desc='不可申诉' THEN 2
                                       WHEN status_desc='可申诉' THEN 1
                                       ELSE 0 END) AS status_level,
                              MAX(CASE WHEN sub_biz='屏蔽流量' THEN 2
                                       WHEN sub_biz='限制流量' THEN 1
                                       ELSE 0 END) AS biz_level,
                              MAX(COALESCE(is_blacklisted,0)) AS any_blacklisted,
                              COUNT(DISTINCT user_id) AS acct_count
                       FROM spark_violation_dramas_local
                       WHERE drama_title IS NOT NULL AND drama_title != ''
                       GROUP BY drama_title"""
                ):
                    status = {2: "不可申诉", 1: "可申诉", 0: ""}.get(r["status_level"], "")
                    biz = {2: "屏蔽流量", 1: "限制流量", 0: ""}.get(r["biz_level"], "")
                    _VIOLATION_CACHE[r["drama_title"]] = {
                        "max_count": int(r["max_count"] or 0),
                        "worst_status": status,
                        "worst_biz": biz,
                        "any_blacklisted": int(r["any_blacklisted"] or 0),
                        "acct_count": int(r["acct_count"] or 0),
                    }
        except Exception as ee:
            log.debug("[match] violation cache failed: %s", ee)

        # ★ 2026-04-23 §31 新表 2/3: mcn_drama_library.income_desc (全网热度)
        # 解析 ¥ 金额 (如 "¥856K" → 856000, "¥1.2M" → 1200000)
        # 当前 MCN 0 条有 ¥, 都 "持续增长中" — cache 空是正常
        _INCOME_DESC_CACHE.clear()
        try:
            import re
            _money_re = re.compile(r"¥\s*([\d.]+)\s*([KMWwB万亿]?)", re.IGNORECASE)
            _multipliers = {"": 1, "K": 1e3, "k": 1e3, "M": 1e6, "m": 1e6,
                            "W": 1e4, "w": 1e4, "万": 1e4, "亿": 1e8, "B": 1e9, "b": 1e9}
            with _connect() as c:
                for r in c.execute(
                    """SELECT title, MAX(income_desc) AS inc
                       FROM mcn_drama_library
                       WHERE income_desc LIKE '¥%'
                       GROUP BY title"""
                ):
                    title = r["title"]
                    desc = r["inc"] or ""
                    m = _money_re.search(desc)
                    if m:
                        try:
                            val = float(m.group(1)) * _multipliers.get(m.group(2), 1)
                            if val > 0:
                                _INCOME_DESC_CACHE[title] = val
                        except Exception:
                            pass
        except Exception as ee:
            log.debug("[match] income_desc cache failed: %s", ee)

        # ★ 2026-04-23 §31 新表 3/3: mcn_wait_collect_videos 时效信号
        # 按 name (drama 名) 聚合: 24h 内采集数 + 48h 内采集数 + total
        _FRESHNESS_CACHE.clear()
        try:
            with _connect() as c:
                for r in c.execute(
                    """SELECT name,
                              COUNT(*) AS total,
                              SUM(CASE WHEN created_at >= datetime('now','-24 hours') THEN 1 ELSE 0 END) AS w24h,
                              SUM(CASE WHEN created_at >= datetime('now','-48 hours') THEN 1 ELSE 0 END) AS w48h
                       FROM mcn_wait_collect_videos
                       WHERE name IS NOT NULL AND name != ''
                       GROUP BY name"""
                ):
                    _FRESHNESS_CACHE[r["name"]] = {
                        "total": int(r["total"] or 0),
                        "w24h": int(r["w24h"] or 0),
                        "w48h": int(r["w48h"] or 0),
                    }
        except Exception as ee:
            log.debug("[match] freshness cache failed: %s", ee)

        _CACHE_LOADED_AT = _t.time()
        log.debug("[match] caches loaded: high_income=%d, blacklist=%d, hot_rank=%d, verified=%d, "
                  "violation=%d, income_desc=%d, freshness=%d",
                  len(_HIGH_INCOME_CACHE), len(_BLACKLIST_CACHE), len(_HOT_RANK_CACHE),
                  len(_VERIFIED_CACHE), len(_VIOLATION_CACHE), len(_INCOME_DESC_CACHE),
                  len(_FRESHNESS_CACHE))
    except Exception as e:
        log.warning("[match] cache reload failed: %s", e)


# ═══════════════════════════════════════════════════════════════
# 2026-04-20 用户要求: 账号垂类对齐 (账号 vertical ∩ 剧关键词)
# ═══════════════════════════════════════════════════════════════

# 10 垂类 → 剧 title 关键词映射
# 从 mcn_drama_library 真实 134k 剧统计出来 (每垂类下都有成千上万剧)
_VERTICAL_KEYWORDS = {
    "都市情感": ["甜宠", "婚后", "离婚", "霸总", "总裁", "初恋", "白月光",
                 "恋爱", "我的", "他的", "心声", "娇妻", "娇软"],
    "古代言情": ["穿越", "重生", "王爷", "将军", "公主", "娘娘", "宫", "嫁",
                 "侯爷", "皇", "丞相", "郡主", "侧妃", "冷王", "古代"],
    "玄幻修仙": ["修仙", "仙尊", "仙女", "渡劫", "修真", "仙帝", "仙魔",
                 "灵", "仙", "道祖", "飞升", "玄", "剑仙"],
    "战神逆袭": ["战神", "赘婿", "归来", "隐藏", "龙王", "大佬", "逆袭",
                 "大人物", "狂婿", "真龙", "霸道", "马甲", "身份"],
    "家庭伦理": ["婆婆", "嫂", "妈妈", "亲情", "家人", "儿媳",
                 "重组", "继母", "丈母娘"],
    "悬疑推理": ["刑警", "推理", "谋杀", "命案", "真相", "悬疑", "卧底",
                 "探案", "破案", "警探"],
    "职场励志": ["职场", "创业", "商战", "董事长", "实习生", "CEO", "老板"],
    "美食生活": ["厨神", "美食", "厨房", "烹饪", "下厨", "家常菜", "小厨娘"],
    "搞笑娱乐": ["搞笑", "整蛊", "沙雕", "奇葩", "笑", "逗", "鬼畜", "段子"],
    "军旅热血": ["军婚", "军营", "军人", "边疆", "特种", "抗战", "战士",
                 "狙击", "兵王", "特警"],
}


def _detect_drama_verticals(drama_name: str, description: str = "") -> list[str]:
    """检测一部剧匹配的垂类 list (可多个).

    在 title + description 里搜关键词, 至少命中 1 个关键词就算该垂类.
    """
    text = (drama_name or "") + " " + (description or "")
    if not text.strip():
        return []
    matched = []
    for vertical, kws in _VERTICAL_KEYWORDS.items():
        for kw in kws:
            if kw in text:
                matched.append(vertical)
                break
    return matched


def _vertical_match_bonus(account_id: int, drama_name: str,
                            account_tier: str = "") -> tuple[float, str]:
    """★ 2026-04-20 v2: 账号垂类对齐 —— 软约束, 新号探索.

    用户需求 (2026-04-20 19:xx):
      "有些账号并不严垂也跑得很好. 新号都没有垂类, 需要 AI 决策发哪个赛道."

    新规则 (软约束):
      - 新号 (tier=new/testing 且 vertical 空) → +5 探索赛道 (不固定)
      - 新号 已有 vertical (LLM 建议) → 匹配 +10, 不匹配 -5 (轻约束)
      - warming_up 账号 → 匹配 +15, 不匹配 -10 (中约束, 开始收敛)
      - established/viral 账号 → 匹配 +20, 不匹配 -15 (强约束)
      - vertical_locked=1 且不匹配 → -9999 硬拒 (仅人工锁定生效)
    """
    try:
        with _connect() as c:
            r = c.execute(
                "SELECT vertical_category, vertical_locked, tier FROM device_accounts WHERE id=?",
                (int(account_id),)
            ).fetchone()
            if not r:
                return 0.0, "account_not_found"
            acc_vertical = r["vertical_category"]
            locked = int(r["vertical_locked"] or 0)
            tier = account_tier or r["tier"] or ""
            # 取剧 description (mcn_drama_library)
            d = c.execute(
                "SELECT description FROM mcn_drama_library WHERE title=? LIMIT 1",
                (drama_name,)
            ).fetchone()
            desc = (d["description"] if d else "") or ""
    except Exception as e:
        log.debug("[match] vertical query failed: %s", e)
        return 0.0, "query_error"

    matched = _detect_drama_verticals(drama_name, desc)

    # 完全无垂类 (新账号未被 LLM 推断) — 微弱鼓励探索
    if not acc_vertical:
        if matched:
            explore_bonus = float(cfg_get("ai.planner.vertical.explore_bonus", 5.0))
            return explore_bonus, f"explore:new_account_no_vertical_yet"
        return 0.0, "account_no_vertical + drama_no_kw"

    # 剧没关键词 — 无信息, 不加分
    if not matched:
        return 0.0, f"drama_no_kw (acc={acc_vertical})"

    # 按 tier 动态调节力度
    tier_l = tier.lower()
    if tier_l in ("new", "testing"):
        bonus_match = float(cfg_get("ai.planner.vertical.match_bonus_testing", 10.0))
        penalty_mismatch = float(cfg_get("ai.planner.vertical.mismatch_penalty_testing", -5.0))
    elif tier_l == "warming_up":
        bonus_match = float(cfg_get("ai.planner.vertical.match_bonus_warming", 15.0))
        penalty_mismatch = float(cfg_get("ai.planner.vertical.mismatch_penalty_warming", -10.0))
    else:  # established / viral / frozen (不应该选剧了)
        bonus_match = float(cfg_get("ai.planner.vertical.match_bonus_established", 20.0))
        penalty_mismatch = float(cfg_get("ai.planner.vertical.mismatch_penalty_established", -15.0))

    if acc_vertical in matched:
        return bonus_match, f"match:{acc_vertical}(tier={tier_l})"
    # 不匹配
    if locked:
        return -9999.0, f"locked_mismatch (acc={acc_vertical} vs {matched[:2]})"
    return penalty_mismatch, f"soft_mismatch (acc={acc_vertical} vs {matched[:2]}, tier={tier_l})"


def _url_readiness_bonus(drama_name: str) -> tuple[float, str]:
    """★ 2026-04-20 step⑤: drama 有 verified URL → +10; 只 pending → 0; 全 broken → -10; 无记录 → 0.

    让 planner 隐式避开下不了的剧 (step 20 预验 + downloader refresh 的信号反哺).
    """
    _maybe_reload_caches()
    s = _VERIFIED_CACHE.get(drama_name)
    bonus_verified = float(cfg_get("ai.planner.url_readiness.bonus_verified", 10.0))
    penalty_broken = float(cfg_get("ai.planner.url_readiness.penalty_broken", -10.0))
    if s == "verified":
        return bonus_verified, "url_verified"
    if s == "broken":
        return penalty_broken, "url_all_broken"
    if s == "pending":
        return 0.0, "url_pending_unverified"
    return 0.0, "url_no_record"


def _hot_ranking_bonus(drama_name: str) -> tuple[float, str]:
    """剧在近 7 天 drama_hot_rankings 中出现过 → 按最佳 rank 加分.

    映射 (可通过 config 调):
      rank ≤ 3   → +25  (top 3)
      rank ≤ 10  → +20  (top 10)  ← 用户要求的默认分值
      rank ≤ 30  → +10  (top 30)
      未命中     →  0

    数据源: drama_hot_rankings (keyword 热榜采集, 115 条/关键词 × 15 关键词).
    """
    _maybe_reload_caches()
    rank = _HOT_RANK_CACHE.get(drama_name)
    if rank is None:
        return 0.0, "not_in_hot_rankings"
    bonus_top3 = float(cfg_get("ai.planner.hot_ranking.bonus_top3", 25.0))
    bonus_top10 = float(cfg_get("ai.planner.hot_ranking.bonus_top10", 20.0))
    bonus_top30 = float(cfg_get("ai.planner.hot_ranking.bonus_top30", 10.0))
    if rank <= 3:
        return bonus_top3, f"hot_rank={rank}_top3"
    if rank <= 10:
        return bonus_top10, f"hot_rank={rank}_top10"
    if rank <= 30:
        return bonus_top30, f"hot_rank={rank}_top30"
    return 0.0, f"hot_rank={rank}_below30"


def _high_income_bonus(drama_name: str) -> tuple[float, str]:
    """高收益剧加分: rank 1-10 → +30, 11-50 → +20, 51-100 → +10, >100 → 0.

    数据源: high_income_dramas (镜像 spark_highincome_dramas, 432 行).
    """
    _maybe_reload_caches()
    rank = _HIGH_INCOME_CACHE.get(drama_name)
    if rank is None:
        return 0.0, "not_in_high_income_top432"
    bonus_top = float(cfg_get("ai.planner.high_income.bonus_top10", 30.0))
    bonus_mid = float(cfg_get("ai.planner.high_income.bonus_top50", 20.0))
    bonus_low = float(cfg_get("ai.planner.high_income.bonus_top100", 10.0))
    if rank <= 10:
        return bonus_top, f"high_income_rank={rank}_top10"
    if rank <= 50:
        return bonus_mid, f"high_income_rank={rank}_top50"
    if rank <= 100:
        return bonus_low, f"high_income_rank={rank}_top100"
    return 0.0, f"high_income_rank={rank}_below100"


def _blacklist_penalty(drama_name: str) -> tuple[float, str]:
    """黑名单扣分:
       'active' (is_blacklisted=1, 已确认拉黑) → -9999 (硬拒)
       'flagged' (出现在 spark_violation_dramas 但未确认) → 软扣 (默认 -200)
       未命中 → 0

    数据源: drama_blacklist (镜像 spark_violation_dramas).
    """
    _maybe_reload_caches()
    status = _BLACKLIST_CACHE.get(drama_name)
    if status == "active":
        return -9999.0, "BLACKLISTED_active"
    if status == "flagged":
        soft = float(cfg_get("ai.planner.blacklist.flagged_penalty", -200.0))
        return soft, "BLACKLISTED_flagged"
    return 0.0, "not_blacklisted"


# ★ 2026-04-24 v6 Day 7: account × drama 级 blacklist (细粒度, 不冻账号)
# 数据源: account_drama_blacklist (migrate_v43).
# 直查无 cache — 单次 index lookup 极快 (2ms级). 若未来评分频繁可加 TTL cache.
def _account_drama_blacklist_penalty(account_id: int | str,
                                        drama_name: str) -> tuple[float, str]:
    """(account × drama) 黑名单命中 → 硬扣 -999 (基本不会选).

    来源: 80004 业务拒 / 重复失败 → publisher 自动写入表.
    过期由 ControllerAgent step 25b 每 1h 清.
    """
    if not cfg_get("ai.blacklist.account_drama.enabled", True):
        return 0.0, "disabled"
    try:
        from core.account_drama_blacklist import is_blocked
        ok, meta = is_blocked(account_id, drama_name)
        if ok:
            penalty = float(cfg_get("ai.blacklist.account_drama.penalty", -999.0))
            reason = meta.get("reason", "unknown")
            count = meta.get("block_count", 1)
            return penalty, f"ACCT_DRAMA_BL_{reason}_cnt{count}"
    except Exception as _e:
        # 表不存在 / 查询失败 → 静默返 0
        pass
    return 0.0, "acct_drama_ok"


def _drama_url_cooldown_penalty(drama_name: str) -> tuple[float, str]:
    """Drama URL 级联失败冷却扣分 (2026-04-21).

    当 watchdog 检测到一个剧在近 2h 多账号下载失败 → 写 drama_links.cooldown_until.
    planner 再遇到这剧时, 直接大额扣分 (默认 -500) 让其排到最后.

    数据源: drama_links.cooldown_until (由 watchdog._detect_drama_url_cooldown 写入).
    """
    _maybe_reload_caches()
    if drama_name in _COOLDOWN_CACHE:
        penalty = float(cfg_get("ai.planner.drama_cooldown_penalty", -500.0))
        return penalty, f"DRAMA_URL_COOLDOWN_until={_COOLDOWN_CACHE[drama_name][:19]}"
    return 0.0, "not_cooled"


def _banner_existence_check(drama_name: str) -> tuple[float, str]:
    """★ 2026-04-21 14:30 hotfix: 校验 drama_name 在 drama_banner_tasks 里有真 banner.

    事故背景: MCN spark_highincome_dramas.title 是展示简称 (师娘/陆总), JOIN 不上 banner.
    AI 选中后 drama_links 搜不到 → 14 条 PUBLISH 全挂 no_urls.

    此校验硬扣 -5000 (类似 blacklist 短路, 不会被其他加分救回).
    """
    _maybe_reload_caches()
    if not _BANNER_DRAMA_SET:
        # cache 空 (启动期) — 不扣, 不然全卡
        return 0.0, "banner_cache_empty"
    if drama_name in _BANNER_DRAMA_SET:
        return 0.0, "banner_exists"
    return -5000.0, f"NO_BANNER_for_{drama_name[:15]}"


def _quarantined_penalty(drama_name: str) -> tuple[float, str]:
    """★ 2026-04-21 Top 3: drama 所有 URL 都 quarantined → 大额硬扣.

    比 cooldown_penalty 更重 (默认 -1000): cooldown 是 "2h 内失败多次",
    quarantined 是 "5+ 次 refresh 失败", 说明 URL 压根废了.

    数据源: drama_links.quarantined_at (由 _refresh_stale_urls / _mark_url_broken 写入).
    """
    _maybe_reload_caches()
    if drama_name in _QUARANTINED_CACHE:
        penalty = float(cfg_get("ai.planner.quarantined_penalty", -1000.0))
        n = _QUARANTINED_CACHE[drama_name]
        return penalty, f"QUARANTINED_all_{n}_urls_dead"
    return 0.0, "not_quarantined"


# ═════════════════════════════════════════════════════════════════
# ★ 2026-04-23 §31 候选池升级: 3 个新信号 (对齐 migrate_v39 镜像表)
# ═════════════════════════════════════════════════════════════════

def _violation_penalty(drama_name: str) -> tuple[float, str]:
    """★ 违规库扣分 — MCN spark_violation_dramas_local (2760 条违规记录).

    规则 (对齐 migrate_v39 configs):
      hard_lock: max_count >= 5 OR (不可申诉 AND count >= 2) → -9999 (硬锁, ai.violation.hard_lock_penalty)
      不可申诉        → -100 (ai.violation.unappealable_penalty)
      限制流量/屏蔽流量 → -50  (ai.violation.flow_restricted_penalty)
      可申诉          → -20  (ai.violation.appealable_penalty)

    注: 同 drama 多账号违规会聚合为最严格规则生效.
    """
    _maybe_reload_caches()
    v = _VIOLATION_CACHE.get(drama_name)
    if not v:
        return 0.0, "no_violation"

    max_count = v["max_count"]
    status = v["worst_status"]
    biz = v["worst_biz"]
    acct_n = v["acct_count"]

    hard_lock_count = int(cfg_get("ai.violation.hard_lock_count", 5))
    # 硬锁判定
    if max_count >= hard_lock_count or (status == "不可申诉" and max_count >= 2):
        penalty = float(cfg_get("ai.violation.hard_lock_penalty", -9999.0))
        return penalty, f"HARD_LOCK: count={max_count}, status={status}, accts={acct_n}"

    # 分级软扣
    if status == "不可申诉":
        penalty = float(cfg_get("ai.violation.unappealable_penalty", -100.0))
        return penalty, f"unappealable: count={max_count}, biz={biz}"
    if biz in ("限制流量", "屏蔽流量"):
        penalty = float(cfg_get("ai.violation.flow_restricted_penalty", -50.0))
        return penalty, f"{biz}: count={max_count}"
    if status == "可申诉":
        penalty = float(cfg_get("ai.violation.appealable_penalty", -20.0))
        return penalty, f"appealable: count={max_count}"
    return 0.0, f"unknown_pattern: count={max_count}"


def _income_desc_bonus(drama_name: str) -> tuple[float, str]:
    """★ 全网热度加分 — mcn_drama_library.income_desc (¥金额) log 映射.

    公式: bonus = min(max_bonus, log10(income_yuan) * scale)
    默认: scale=10.0, max=30.0
      income=¥1000 → log10=3 × 10 = 30 (达上限)
      income=¥856K → log10≈5.9 × 10 = 59 → 限到 30
      income=¥100  → log10=2 × 10 = 20

    当前 MCN 0 条有 ¥ (都是 "持续增长中"), cache 空, 全返 0.
    未来若 MCN 补 ¥ 数据, 此信号自动生效.
    """
    _maybe_reload_caches()
    income_yuan = _INCOME_DESC_CACHE.get(drama_name)
    if not income_yuan or income_yuan <= 1:
        return 0.0, "no_income_desc"

    import math
    scale = float(cfg_get("ai.heat.income_desc_log_scale", 10.0))
    max_bonus = float(cfg_get("ai.heat.income_desc_max_bonus", 30.0))
    bonus = min(max_bonus, math.log10(income_yuan) * scale)
    return round(bonus, 2), f"income_desc=¥{int(income_yuan)}_log10={math.log10(income_yuan):.1f}"


def _freshness_bonus(drama_name: str) -> tuple[float, str]:
    """★ 时效加分 — mcn_wait_collect_videos 24h/48h 新鲜池 depth.

    分档 (对齐 migrate_v39 ai.candidate.freshness_*):
      w24h ≥ 10 → +20 (今日热门池, 有充足素材可挑)
      w24h ≥ 3  → +15 (今日有货)
      w24h ≥ 1  → +10 (今日偶见)
      w48h ≥ 3  → +5  (近期有, 可用)
      total > 0 但 48h 内无新增 → 0 (陈旧)
      无记录 → 0
    """
    _maybe_reload_caches()
    f = _FRESHNESS_CACHE.get(drama_name)
    if not f:
        return 0.0, "not_in_wait_collect"

    w24h = f["w24h"]
    w48h = f["w48h"]
    total = f["total"]

    if w24h >= 10:
        return 20.0, f"freshness_today_hot(24h={w24h})"
    if w24h >= 3:
        return 15.0, f"freshness_today(24h={w24h})"
    if w24h >= 1:
        return 10.0, f"freshness_today_sparse(24h={w24h})"
    if w48h >= 3:
        return 5.0, f"freshness_48h({w48h})"
    if total > 0:
        return 0.0, f"stale(total={total},no_recent)"
    return 0.0, "empty"


def _diversity_bonus(account_id: int, drama_name: str, days: int = 3) -> float:
    """账号最近 N 天发过这剧 → 0; 没发过 → +20."""
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT COUNT(*) AS n FROM publish_results
                   WHERE account_id = ?
                     AND drama_name = ?
                     AND datetime(created_at) >= datetime('now', ?)""",
                (str(account_id), drama_name, f"-{days} days"),
            ).fetchone()
            return 0.0 if r["n"] > 0 else 20.0
    except Exception:
        return 20.0  # 查失败当作没发过


def _cooldown_penalty(account_id: int, drama_name: str) -> tuple[float, str]:
    """冷却扣分:
       24h 内发过同剧 → -1000 (硬拒)
       72h 内发过     → -200
       其他         → 0
    Returns: (penalty, reason).
    """
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT datetime(created_at) AS last
                   FROM publish_results
                   WHERE account_id = ?
                     AND drama_name = ?
                     AND publish_status = 'success'
                   ORDER BY created_at DESC LIMIT 1""",
                (str(account_id), drama_name),
            ).fetchone()
            if not r:
                return 0.0, "no_history"
            last_dt = datetime.fromisoformat(r["last"])
            hours = (datetime.now() - last_dt).total_seconds() / 3600
            if hours < 24:
                return -1000.0, f"hard_cooldown_{hours:.1f}h"
            if hours < 72:
                return -200.0, f"soft_cooldown_{hours:.1f}h"
            return 0.0, f"ok_{hours:.0f}h"
    except Exception:
        return 0.0, "cooldown_query_failed"


def _recent_fail_penalty(account_id: int, hours: int = 1) -> float:
    """账号近 N 小时失败次数 × 10 扣分 (最多 -20)."""
    try:
        with _connect() as c:
            r = c.execute(
                """SELECT COUNT(*) AS n FROM task_queue
                   WHERE account_id = ?
                     AND status = 'failed'
                     AND finished_at >= datetime('now', ?, 'localtime')""",
                (str(account_id), f"-{hours} hour"),
            ).fetchone()
            return -min(20.0, (r["n"] or 0) * 10.0)
    except Exception:
        return 0.0


# ─────────────────────────────────────────────────────────────────
# 主入口
# ─────────────────────────────────────────────────────────────────

# ═════════════════════════════════════════════════════════════════
# ★ 账号记忆集成 (2026-04-20 Layer 2): 4 个新信号
# ═════════════════════════════════════════════════════════════════

def _affinity_signal(account_id: int, recipe: str, image_mode: str) -> tuple[float, str]:
    """★ 偏好信号 — 该账号对这个 (recipe, image_mode) 组合历史命中率.

    Returns: (+0 ~ +15) 分 + 说明
    """
    try:
        from core.account_memory import get_strategy_memory
        memory = get_strategy_memory(account_id)
        if not memory:
            return 0.0, "no_memory"

        weight = float(cfg_get("ai.memory.planner.affinity_weight", 15.0))
        score = 0.0
        parts = []

        pref_recipes = memory.get("preferred_recipes") or {}
        if recipe and recipe in pref_recipes:
            r_affinity = pref_recipes[recipe]  # 0-1
            score += r_affinity * weight * 0.7
            parts.append(f"recipe_{recipe}={r_affinity:.2f}")

        pref_images = memory.get("preferred_image_modes") or {}
        if image_mode and image_mode in pref_images:
            i_affinity = pref_images[image_mode]
            score += i_affinity * weight * 0.3
            parts.append(f"img_{image_mode}={i_affinity:.2f}")

        return round(score, 2), ",".join(parts) if parts else "no_history"
    except Exception as e:
        log.debug("[affinity] %s", e)
        return 0.0, f"err:{e}"[:50]


def _avoid_penalty(account_id: int, drama_name: str) -> tuple[float, str]:
    """★ 避雷信号 — 该账号历史 over_optimistic / wrong 的剧直接扣分.

    Returns: (-0 ~ -50) 分 + 说明
    """
    try:
        from core.account_memory import get_strategy_memory
        memory = get_strategy_memory(account_id)
        if not memory:
            return 0.0, "no_memory"

        avoid_ids = memory.get("avoid_drama_ids") or []
        if drama_name in avoid_ids:
            penalty = -float(cfg_get("ai.memory.planner.avoid_penalty", 50.0))
            return penalty, f"avoid_list: {drama_name}"
        return 0.0, "not_in_avoid"
    except Exception:
        return 0.0, "err"


def _trust_signal(account_id: int, account_tier: str) -> tuple[float, str]:
    """★ 校准信号 — AI 对该账号判断的历史准确率.

    高 trust (>0.7) → 加分 (AI 懂这账号)
    低 trust (<0.3) → 减分 (AI 不懂, 需探索)
    NULL (样本不足) → 0 分

    Returns: (-10 ~ +10) 分 + 说明
    """
    try:
        from core.account_memory import get_strategy_memory
        memory = get_strategy_memory(account_id)
        if not memory:
            return 0.0, "no_memory"

        trust = memory.get("ai_trust_score")
        if trust is None:
            return 0.0, "insufficient_samples"

        weight = float(cfg_get("ai.memory.planner.trust_weight", 10.0))
        # trust 0-1 映射到 -weight ~ +weight (trust 0.5 = 0)
        score = (float(trust) - 0.5) * 2 * weight
        return round(score, 2), f"trust={trust:.2f}"
    except Exception:
        return 0.0, "err"


def _novelty_bonus(account_id: int, recipe: str, image_mode: str) -> tuple[float, str]:
    """★ 探索信号 — 该账号从未试过的 (recipe, image_mode) 组合加分.

    目的: 扩大样本, 避免 Bandit 锁定在少数几个组合.

    Returns: (+0 或 +8) 分 + 说明
    """
    try:
        from core.account_memory import query_account_decisions
        decisions = query_account_decisions(account_id, days=90, limit=100)
        if not decisions:
            return 0.0, "no_history"

        # 该账号历史所有 (recipe, image_mode) 组合
        tried = set(
            (d.get("recipe") or "", d.get("image_mode") or "")
            for d in decisions
        )
        if (recipe, image_mode) not in tried:
            bonus = float(cfg_get("ai.memory.planner.novelty_bonus", 8.0))
            return bonus, f"novel_combo"
        return 0.0, "already_tried"
    except Exception:
        return 0.0, "err"


def match_score(
    account_id: int,
    account_tier: str,
    drama_name: str,
    context: dict | None = None,
    recipe: str = "",
    image_mode: str = "",
) -> tuple[float, dict]:
    """计算 (account, drama) 的 match score. ⭐ 升级版 (2026-04-20): 加 4 记忆信号.

    Returns:
        (score, breakdown_dict)  — breakdown 记录每个因子贡献, 方便 explain.

    新参数:
        recipe:     AI 预选的 recipe (用于 affinity/novelty 评分)
        image_mode: AI 预选的 image_mode
    """
    ctx = context or {}

    # 各因子
    tier_w = _tier_weight(account_tier)
    if tier_w <= 0:
        return tier_w, {"reason": "frozen_or_unknown_tier", "tier": account_tier}

    income = _account_recent_income(account_id, days=7)
    # income 映射: 可 config 的 scale (默认 每 ¥1 +10 分, 最多 +50)
    # ★ 2026-04-22 §28_J: 原来每 ¥10 +1 太弱 (百洁 ¥1.53 只 +0.15 分), 导致"赚钱账号反而被挤出".
    # 新公式: 每 ¥1 +10 分 (比老公式 100x 权重), 最多 +50.
    # 同时加 "base bonus" — 只要 MCN 有任何收益记录就 +5, 激励历史有业绩的账号.
    income_scale = float(cfg_get("ai.planner.income_bonus_scale", 10.0))
    income_max = float(cfg_get("ai.planner.income_bonus_max", 50.0))
    income_base = float(cfg_get("ai.planner.income_bonus_base_if_any", 5.0))
    income_bonus = min(income_max, income * income_scale)
    if income > 0:
        income_bonus = max(income_bonus, income_base)   # 至少给 base, 不让微收益被忽略

    heat = _drama_heat(drama_name)
    # heat 映射: 每 ¥1 剧收益 +0.3 分, 最多 +30
    heat_bonus = min(30.0, heat * 0.3)

    # ★ Path 1+2 (2026-04-20): high_income 加分 + blacklist 硬/软扣
    hi_bonus, hi_reason = _high_income_bonus(drama_name)
    bl_pen, bl_reason = _blacklist_penalty(drama_name)
    # ★ Path 1d (2026-04-20 用户要求): 热榜信号喂回 planner
    hot_bonus, hot_reason = _hot_ranking_bonus(drama_name)
    # ★ step⑤ (2026-04-20): URL 可下载性信号
    url_bonus, url_reason = _url_readiness_bonus(drama_name)
    # ★ 2026-04-21 drama 级 URL 冷却扣分 (watchdog 写的, 避免级联失败)
    dcd_pen, dcd_reason = _drama_url_cooldown_penalty(drama_name)
    # ★ 2026-04-21 Top 3: URL 全 quarantined 扣分 (更重)
    qtn_pen, qtn_reason = _quarantined_penalty(drama_name)
    # ★ 2026-04-21 14:30 hotfix: banner 不在表里 → -5000 硬扣 (短路)
    banner_pen, banner_reason = _banner_existence_check(drama_name)
    if banner_pen <= -4000:
        # 短路: 无 banner 的剧不许选
        return banner_pen, {
            "reason": banner_reason,
            "banner_check_penalty": banner_pen,
            "drama_name": drama_name,
        }
    # ★ 2026-04-23 §31 候选池升级: 3 新 MCN 镜像信号
    viol_pen, viol_reason = _violation_penalty(drama_name)
    # 违规库硬锁短路 (hard_lock <= -9000)
    if viol_pen <= -9000:
        return viol_pen, {
            "reason": viol_reason,
            "violation_penalty": viol_pen,
            "drama_name": drama_name,
        }

    # ★ 2026-04-24 v6 Day 7: account × drama 级 blacklist (80004 闭环)
    # 短路: 该账号对该剧在冷却期内, 其他信号无意义, 直接 return
    acct_bl_pen, acct_bl_reason = _account_drama_blacklist_penalty(account_id, drama_name)
    if acct_bl_pen <= -500:
        return acct_bl_pen, {
            "reason": acct_bl_reason,
            "account_drama_blacklist_penalty": acct_bl_pen,
            "account_id": account_id,
            "drama_name": drama_name,
        }
    heat_desc_bonus, heat_desc_reason = _income_desc_bonus(drama_name)
    fresh_bonus, fresh_reason = _freshness_bonus(drama_name)
    # ★ 垂类对齐 (2026-04-20 用户要求): 账号 vertical 匹配剧关键词 — 软约束按 tier
    vert_bonus, vert_reason = _vertical_match_bonus(account_id, drama_name,
                                                      account_tier=account_tier)
    # 硬拒 (vertical_locked=1 且不匹配)
    if vert_bonus <= -9000:
        return vert_bonus, {
            "reason": vert_reason,
            "vertical_match_penalty": vert_bonus,
            "drama_name": drama_name,
        }
    if bl_pen <= -9000:
        # 'active' 拉黑短路: 直接 return, 跳过其他 SQL (省 5 个 query)
        return bl_pen, {
            "reason": bl_reason,
            "blacklist_penalty": bl_pen,
            "drama_name": drama_name,
        }
    # 'flagged' 不短路, 走 total 累加 (软扣)

    diversity = _diversity_bonus(account_id, drama_name)
    cooldown, cd_reason = _cooldown_penalty(account_id, drama_name)
    fail_pen = _recent_fail_penalty(account_id)

    # ★ 4 个记忆信号 (有 recipe / image_mode 时才生效)
    use_memory = cfg_get("ai.memory.planner.use_memory", True)
    if use_memory and (recipe or image_mode):
        affinity, aff_notes = _affinity_signal(account_id, recipe, image_mode)
        avoid, av_notes = _avoid_penalty(account_id, drama_name)
        trust, tr_notes = _trust_signal(account_id, account_tier)
        novelty, nv_notes = _novelty_bonus(account_id, recipe, image_mode)
    else:
        affinity, aff_notes = 0.0, "disabled"
        avoid, av_notes = 0.0, "disabled"
        trust, tr_notes = 0.0, "disabled"
        novelty, nv_notes = 0.0, "disabled"

    total = (tier_w + income_bonus + heat_bonus + diversity
             + cooldown + fail_pen
             + affinity + avoid + trust + novelty
             + hi_bonus       # ★ Path 1: high_income +0/+10/+20/+30
             + bl_pen         # ★ Path 2: 'flagged' 软扣 (默认 -200)
             + hot_bonus      # ★ Path 1d: hot_ranking +0/+10/+20/+25
             + url_bonus      # ★ step⑤: url_verified +10 / broken -10
             + vert_bonus     # ★ 垂类对齐: match +20, mismatch -30
             + dcd_pen        # ★ 2026-04-21 drama URL 冷却 -500 (watchdog 写)
             + qtn_pen        # ★ 2026-04-21 Top 3: 所有 URL quarantined -1000
             + viol_pen       # ★ 2026-04-23 §31: 违规库软扣 (hard_lock 已 short-circuit)
             + heat_desc_bonus  # ★ 2026-04-23 §31: income_desc ¥ 热度加分
             + fresh_bonus)   # ★ 2026-04-23 §31: wait_collect 时效加分
                              # 'active' blacklist + 'locked_mismatch' + 'hard_lock' 已 short-circuit

    breakdown = {
        # 原 6 个因子
        "tier_weight": tier_w,
        "income_bonus": round(income_bonus, 2),
        "heat_bonus": round(heat_bonus, 2),
        "diversity_bonus": diversity,
        "cooldown_penalty": cooldown,
        "cooldown_reason": cd_reason,
        "recent_fail_penalty": fail_pen,
        # ★ 4 个记忆信号
        "affinity_signal": affinity,
        "affinity_notes": aff_notes,
        "avoid_penalty": avoid,
        "avoid_notes": av_notes,
        "trust_signal": trust,
        "trust_notes": tr_notes,
        "novelty_bonus": novelty,
        "novelty_notes": nv_notes,
        # ★ Path 1+2 (2026-04-20): MCN 镜像表信号
        "high_income_bonus": round(hi_bonus, 2),
        "high_income_reason": hi_reason,
        "blacklist_penalty": bl_pen,    # 0 (未命中); 命中走短路, 此处不会执行
        "blacklist_reason": bl_reason,
        # ★ Path 1d (2026-04-20): 热榜信号
        "hot_ranking_bonus": round(hot_bonus, 2),
        "hot_ranking_reason": hot_reason,
        # ★ step⑤ (2026-04-20): URL 可下载性
        "url_readiness_bonus": round(url_bonus, 2),
        "url_readiness_reason": url_reason,
        # ★ 垂类对齐 (2026-04-20 用户要求)
        "vertical_match_bonus": round(vert_bonus, 2),
        "vertical_match_reason": vert_reason,
        # ★ 2026-04-21 drama URL 冷却
        "drama_cooldown_penalty": round(dcd_pen, 2),
        "drama_cooldown_reason": dcd_reason,
        # ★ 2026-04-21 Top 3: URL quarantined 扣分
        "quarantined_penalty": round(qtn_pen, 2),
        "quarantined_reason": qtn_reason,
        # ★ 2026-04-23 §31 候选池升级: 3 新 MCN 镜像信号
        "violation_penalty": round(viol_pen, 2),
        "violation_reason": viol_reason,
        "income_desc_bonus": round(heat_desc_bonus, 2),
        "income_desc_reason": heat_desc_reason,
        "freshness_bonus": round(fresh_bonus, 2),
        "freshness_reason": fresh_reason,
        # 参考数据
        "account_income_7d": round(income, 2),
        "drama_heat_30d": round(heat, 2),
        "recipe": recipe,
        "image_mode": image_mode,
    }
    return round(total, 2), breakdown


def explain(account_id: int, account_tier: str, drama_name: str) -> str:
    """生成 human-readable 解释."""
    score, b = match_score(account_id, account_tier, drama_name)
    if b.get("cooldown_penalty", 0) <= -1000:
        return (f"score={score} ❌硬拒({b['cooldown_reason']}): "
                f"近 24h 已发过, 跳过")
    return (
        f"score={score} = tier({b['tier_weight']}) + income({b['income_bonus']}) "
        f"+ heat({b['heat_bonus']}) + diversity({b['diversity_bonus']}) "
        f"+ cooldown({b['cooldown_penalty']}) "
        f"+ fail_penalty({b['recent_fail_penalty']})"
    )


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse, json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--account-id", type=int, required=True)
    ap.add_argument("--tier", required=True,
                    choices=list(_TIER_WEIGHT.keys()))
    ap.add_argument("--drama", required=True)
    args = ap.parse_args()

    score, breakdown = match_score(args.account_id, args.tier, args.drama)
    print(f"match_score = {score}")
    print(json.dumps(breakdown, ensure_ascii=False, indent=2))
    print(f"\nexplain: {explain(args.account_id, args.tier, args.drama)}")
