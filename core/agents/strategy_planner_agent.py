# -*- coding: utf-8 -*-
"""StrategyPlannerAgent — 每日早 8:00 跑.

读:  device_accounts.tier + strategy_rewards (reward) + drama_banner_tasks (剧池)
     + 昨日 Analyzer 的建议 + research_notes (LLM 的策略建议)
生成: daily_plans + daily_plan_items (当日 N 条任务, 每条 = account × drama × recipe × time)

三档策略, 按 app_config 自动 fallback:
  Path A 规则 (默认, 永远保底)
  Path B Thompson Sampling Bandit (需样本 ≥ ai.bandit.min_samples)
  Path C LLM 辅助 (从 research_notes 吸取建议)
"""
from __future__ import annotations

import json
import logging
import random
import sqlite3
from datetime import datetime, timedelta
from typing import Any

from core.account_tier import TIERS, list_accounts_by_tier
from core.app_config import get as cfg_get
from core.drama_selector import select_for_account

log = logging.getLogger(__name__)

# Recipe 池 (Thompson Sampling 用 — 只放主力 5 种, 避免样本过稀疏)
AVAILABLE_RECIPES = ["mvp_trim_wipe_metadata", "light_noise_recode",
                      "zhizun", "kirin_mode6", "zhizun_mode5_pipeline"]


# ───────────────────────────────────────────────────────────────
# 2026-04-20 ★ Recipe 强度分级 (对齐 KS184 UI 用户实际选择)
# ───────────────────────────────────────────────────────────────
# 快手查重 5 层 (L1 字节 / L2 元数据 / L3 pHash / L4 音频 / L5 CNN embedding).
# KS184 经验: 只有 kirin_mode6 / zhizun_mode5_pipeline 能同时打穿 L1-L5.
# ⭐ 分级 (1-5 星):
#   ⭐ 弱   : 只抹元数据 (mvp), 易查重
#   ⭐⭐⭐⭐⭐ 王炸: 逐帧交织 + matroska 伪装 (kirin_mode6 / zhizun_mode5_pipeline)
RECIPE_STRENGTH = {
    "mvp_trim_wipe_metadata":  1,
    "light_noise_recode":      2,
    "zhizun":                  3,   # 别名 zhizun_overlay
    "zhizun_overlay":          3,
    "touming_9gong":           3,
    "wuxianliandui":           3,
    "yemao":                   3,
    "bushen":                  4,
    "rongyu":                  4,
    "kirin_mode6":             5,   # 王炸 (7 步 interleave + matroska)
    "zhizun_mode5_pipeline":   5,   # 王炸 (4 步 zoompan interleave)
}


# 按 tier 的 recipe weight 分布 (越高 tier 越偏爱强去重)
# 权重 = 百分比概率 (自动归一化, 不需要和 = 100)
#
# 设计原则 (对齐 KS184 用户习惯):
#   - testing/new:  王炸占比 50% (既探索又保住命中率)
#   - warming_up:   王炸占比 70% (成长期靠强 recipe 过查重冲曝光)
#   - established:  王炸占比 85% (成熟期最大化命中率)
#   - viral:        王炸占比 95% (头部号不容浪费)
_DEFAULT_WEIGHTS = {
    "testing": {
        "kirin_mode6":            30,   # ⭐⭐⭐⭐⭐
        "zhizun_mode5_pipeline":  20,   # ⭐⭐⭐⭐⭐
        "zhizun":                 15,   # ⭐⭐⭐
        "zhizun_overlay":         10,   # ⭐⭐⭐
        "light_noise_recode":     10,   # ⭐⭐
        "touming_9gong":           5,   # ⭐⭐⭐
        "wuxianliandui":           5,   # ⭐⭐⭐
        "rongyu":                  5,   # ⭐⭐⭐⭐
    },
    "new": {
        "kirin_mode6":            30,
        "zhizun_mode5_pipeline":  20,
        "zhizun":                 15,
        "zhizun_overlay":         10,
        "light_noise_recode":     10,
        "touming_9gong":           5,
        "wuxianliandui":           5,
        "rongyu":                  5,
    },
    "warming_up": {
        "kirin_mode6":            40,
        "zhizun_mode5_pipeline":  30,
        "zhizun":                 15,
        "rongyu":                  5,
        "bushen":                  5,
        "zhizun_overlay":          5,
    },
    "established": {
        "kirin_mode6":            45,
        "zhizun_mode5_pipeline":  40,
        "rongyu":                  8,
        "bushen":                  5,
        "zhizun_overlay":          2,
    },
    "viral": {
        "kirin_mode6":            50,
        "zhizun_mode5_pipeline":  45,
        "rongyu":                  5,
    },
    "frozen": {
        "mvp_trim_wipe_metadata": 50,
        "light_noise_recode":     50,
    },
}


def _load_tier_weights(tier: str) -> dict[str, float]:
    """从 app_config 读 recipe weight 分布, fallback 到硬编码 default.

    Config key: ai.planner.recipe.weights.{tier}
    格式: "recipe1:30,recipe2:20,..."
    """
    raw = cfg_get(f"ai.planner.recipe.weights.{tier}", "")
    if raw:
        try:
            parts = [p.strip() for p in str(raw).split(",") if p.strip()]
            result: dict[str, float] = {}
            for p in parts:
                if ":" in p:
                    k, v = p.rsplit(":", 1)
                    w = float(v.strip())
                    if w > 0:
                        result[k.strip()] = w
            if result:
                return result
        except (ValueError, TypeError) as e:
            log.warning("[planner] recipe weights parse failed tier=%s raw=%r err=%s",
                        tier, raw, e)
    return _DEFAULT_WEIGHTS.get(tier, _DEFAULT_WEIGHTS["testing"])


def _connect():
    from core.config import DB_PATH
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.execute("PRAGMA busy_timeout=30000")
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA synchronous=NORMAL")
    c.row_factory = sqlite3.Row
    return c


def _get_quota(tier: str, account: dict | None = None) -> int:
    """每账号每日配额 (对齐用户运营策略种子).

    ★ 2026-04-23 接 operation_policy:
      - 优先用 policy.quota_for_account (按年龄 + creator_level + tier 决策)
      - fallback 到老的 ai.planner.quota.<tier>

    Args:
        tier: account_tier string
        account: 可选, {'account_age_days', 'created_at', 'creator_level', 'tier'}
                 → 走策略种子 (新号 4 / V3-V4 5 / V5+ 15)
                 → None 走老 config (向后兼容)
    """
    if account is not None:
        try:
            from core.operation_policy import policy
            return policy().quota_for_account({**account, "tier": tier})
        except Exception as e:
            log.warning("[planner] policy.quota_for_account failed: %s (fallback cfg)", e)
    return int(cfg_get(f"ai.planner.quota.{tier}", 3) or 3)


# ───────────────────────────────────────────────────────────────
# Recipe 选择: Bandit (Path B) or random (Path A)
# ───────────────────────────────────────────────────────────────

def _pick_recipe_thompson(tier: str, drama_name: str = "") -> tuple[str, str]:
    """Thompson Sampling: 按 reward 分布抽 recipe.

    Returns: (recipe, reason).
    """
    if not cfg_get("ai.bandit.enabled", True):
        return _pick_recipe_random(tier)

    min_samples = cfg_get("ai.bandit.min_samples", 5)
    explore_rate = cfg_get("ai.bandit.explore_rate", 0.15)

    # ε-greedy 探索
    if random.random() < explore_rate:
        r = random.choice(AVAILABLE_RECIPES)
        return r, f"explore ({explore_rate:.0%})"

    with _connect() as c:
        # 每 recipe 在 (tier, *) 上的累计 reward
        rows = c.execute("""
            SELECT recipe, SUM(trials) AS trials, SUM(rewards) AS rewards
            FROM strategy_rewards
            WHERE account_tier = ?
              AND recipe IN ({})
            GROUP BY recipe
        """.format(",".join(["?"] * len(AVAILABLE_RECIPES))),
                          [tier] + AVAILABLE_RECIPES).fetchall()

    stats = {r["recipe"]: (r["trials"] or 0, r["rewards"] or 0.0) for r in rows}
    # 样本不足 → 随机
    total = sum(t for t, _ in stats.values())
    if total < min_samples:
        return _pick_recipe_random(tier, extra=f"not enough samples ({total}<{min_samples})")

    # Thompson Sampling: 每个 recipe 建 Beta 分布抽样
    import math
    best_sample = -1e9
    best_recipe = AVAILABLE_RECIPES[0]
    for recipe in AVAILABLE_RECIPES:
        trials, rewards = stats.get(recipe, (0, 0.0))
        # 归一化 reward 到 [0, 1] 假设单次 reward 期望 0-5
        mean_reward = (rewards / max(trials, 1)) if trials else 0.5
        mean_reward = max(0.01, min(0.99, mean_reward / 5.0))
        alpha = mean_reward * max(trials, 1) + 1
        beta_param = (1 - mean_reward) * max(trials, 1) + 1
        # Beta sample
        sample = random.betavariate(alpha, beta_param)
        if sample > best_sample:
            best_sample = sample
            best_recipe = recipe

    return best_recipe, (f"bandit (trials_sum={total}, "
                          f"{best_recipe} sample={best_sample:.3f})")


def _pick_recipe_random(tier: str, extra: str = "") -> tuple[str, str]:
    """加权随机选 recipe — 高 tier 偏爱 kirin_mode6 / zhizun_mode5_pipeline.

    对齐 KS184 UI 用户实际选择: mode5/mode6 (逐帧交织 + matroska 伪装) 才是主力.

    Strategy:
      testing/new → 50% 王炸 + 50% 中低强度 (探索 Bandit)
      warming_up  → 70% 王炸
      established → 85% 王炸
      viral       → 95% 王炸

    Returns:
        (recipe, reason) — reason 含实际抽中概率%
    """
    weights = _load_tier_weights(tier)
    recipes = list(weights.keys())
    ws = list(weights.values())
    if not recipes:
        return "kirin_mode6", f"fallback empty-weights tier={tier}"
    try:
        picked = random.choices(recipes, weights=ws, k=1)[0]
    except (ValueError, IndexError):
        picked = max(recipes, key=lambda r: weights[r])
    total = sum(ws) or 1.0
    pct = weights[picked] / total * 100
    strength = RECIPE_STRENGTH.get(picked, 0)
    stars = "⭐" * strength
    return picked, (f"weighted tier={tier} {picked}={pct:.0f}% "
                    f"{stars} {extra}").strip()


def _assign_schedule_per_account(items: list[dict], run_date: str) -> None:
    """★ 2026-04-20 用户要求: 发布时间"隔开".

    规则:
      - 每账号内 N 条任务, 任意 2 条间隔 ≥ min_interval_min (默认 30 分钟)
      - 只在优先时段 (7/8/13/14/15/18/19) 分配
      - 跨账号前后 ±jitter 分钟随机 (反批量特征)
      - 同一 hour slot 内不同账号错峰 (第 1 号 0-20min, 第 2 号 20-40min, ...)

    直接改 items[i]['scheduled_at'] in-place.
    """
    import random
    from collections import defaultdict
    from datetime import datetime, timedelta

    pri_hours_raw = cfg_get("ai.planner.scheduled_hours_priority",
                             [7, 8, 13, 14, 15, 18, 19])
    if isinstance(pri_hours_raw, str):
        try:
            import json as _j
            pri_hours = _j.loads(pri_hours_raw)
        except Exception:
            pri_hours = [7, 8, 13, 14, 15, 18, 19]
    else:
        pri_hours = list(pri_hours_raw)
    pri_hours = sorted(set(int(h) for h in pri_hours if 0 <= int(h) <= 23))

    min_interval = int(cfg_get("ai.planner.min_account_interval_min", 30))
    jitter_min = int(cfg_get("ai.planner.scheduled_jitter_min", 3))

    base_dt = datetime.strptime(run_date, "%Y-%m-%d")

    # 1. group items by account
    by_account: dict[int, list[dict]] = defaultdict(list)
    for it in items:
        by_account[it["account_id"]].append(it)

    # 2. 每账号分配时间点, 保证账号内间隔 ≥ min_interval
    # 每账号可用 hour slot 打乱一次 (账号间互不相同, 避免 7 点所有号一起发)
    accounts = sorted(by_account.keys())
    for idx, aid in enumerate(accounts):
        acc_items = by_account[aid]
        n = len(acc_items)
        if n == 0:
            continue
        # 账号级打乱 hour 顺序, 每个账号第一发的 hour 不同 (aid % len)
        offset = idx % len(pri_hours)
        hours_for_this_account = pri_hours[offset:] + pri_hours[:offset]

        # 每账号 base_minute 错开 (第 0 号 0-5min, 第 1 号 6-11min, ...)
        minute_offset = (idx * 7) % 50  # 0,7,14,21,... 散开

        assigned_times = []
        target_h_idx = 0
        base_minute = minute_offset
        for item_idx, item in enumerate(acc_items):
            # 找合适 hour slot
            while target_h_idx < len(hours_for_this_account) * 3:  # 最多循环 3 圈
                h = hours_for_this_account[target_h_idx % len(hours_for_this_account)]
                minute = base_minute + random.randint(-jitter_min, jitter_min)
                minute = max(0, min(59, minute))
                dt = base_dt.replace(hour=h, minute=minute, second=random.randint(0, 59))
                # 检查与已分配时间是否 ≥ min_interval
                ok = True
                for assigned in assigned_times:
                    gap = abs((dt - assigned).total_seconds()) / 60
                    if gap < min_interval:
                        ok = False
                        break
                if ok:
                    assigned_times.append(dt)
                    item["scheduled_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")
                    target_h_idx += 1
                    # base_minute 往后推 35min (保证下条自然隔 35+)
                    base_minute = (base_minute + 35) % 60
                    break
                # 不够间隔 → 往下一个 hour slot 试
                target_h_idx += 1
            else:
                # 所有 hour 都塞不下 → fallback 放最后 hour + 随机
                h = pri_hours[-1]
                minute = random.randint(40, 59)
                dt = base_dt.replace(hour=h, minute=minute, second=0)
                item["scheduled_at"] = dt.strftime("%Y-%m-%d %H:%M:%S")

    log.info("[planner] schedule assigned: %d items across %d accounts, "
             "min_interval=%dmin, hours=%s",
             len(items), len(accounts), min_interval, pri_hours)


def _build_soft_retry_items(accounts_by_tier: dict) -> list[dict]:
    """★ 2026-04-20 B: 软重试 — 扫昨日 dead_letter task, 对 drama 现已 verified 的
    重新生成 plan_item (相同 account + drama, 新 recipe, 高优先级).

    目的: 昨天 URL 挂了导致失败的剧, 今天已 step 19/20 修好, 不让它"一错永错".

    防循环: 同 (account, drama) 24h 内 retry 最多 1 次, 再失败就真 cancel.

    Returns:
        list of plan_item dicts (含 decision_type='soft_retry'), 可直接插 items 首位.
    """
    from core.match_scorer import match_score
    # 近 24h dead_letter 的 (account, drama) pairs
    retry_items = []
    try:
        with _connect() as c:
            rows = c.execute("""
                SELECT DISTINCT tq.account_id, tq.drama_name
                FROM task_queue tq
                WHERE tq.status = 'dead_letter'
                  AND tq.created_at > datetime('now','-24 hours')
                  AND tq.task_type IN ('PUBLISH','PUBLISH_DRAMA','PUBLISH_BURST')
                  AND tq.drama_name IS NOT NULL AND tq.drama_name != ''
            """).fetchall()

            # 筛: drama 现在有 verified URL
            verified_dramas = {r["drama_name"] for r in c.execute("""
                SELECT DISTINCT drama_name FROM drama_links
                WHERE status = 'pending' AND verified_at IS NOT NULL
            """).fetchall()}

            # 活跃账号 tier 映射
            tier_map = {}
            for tier, accs in accounts_by_tier.items():
                if tier == "frozen":
                    continue
                for a in accs:
                    tier_map[a["id"]] = tier

            max_retry = int(cfg_get("ai.planner.soft_retry.max_per_run", 10))

            for r in rows:
                if len(retry_items) >= max_retry:
                    break
                aid = int(r["account_id"])
                drama = r["drama_name"]
                if drama not in verified_dramas:
                    continue
                tier = tier_map.get(aid)
                if not tier:
                    continue  # 账号冻结/不在活跃池
                # 防循环: 24h 内已 retry 过
                already = c.execute("""
                    SELECT 1 FROM daily_plan_items
                    WHERE account_id=? AND drama_name=?
                      AND reason LIKE '%soft_retry%'
                      AND scheduled_at > datetime('now','-24 hours')
                    LIMIT 1
                """, (aid, drama)).fetchone()
                if already:
                    continue

                recipe, recipe_reason = _pick_recipe(tier, drama_name=drama,
                                                       account_id=aid, task_source="planner")
                im_result = _pick_image_mode(tier, aid, recipe)
                # _pick_image_mode 可能返回 (image_mode, reason) tuple
                if isinstance(im_result, tuple):
                    image_mode = im_result[0]
                else:
                    image_mode = im_result
                score, breakdown = match_score(aid, tier, drama, recipe=recipe,
                                                 image_mode=image_mode)
                if score < 10:  # 太低直接丢 (可能冷却了)
                    continue
                retry_items.append({
                    "account_id": aid,
                    "account_name": breakdown.get("account_name", ""),
                    "account_tier": tier,
                    "drama_name": drama,
                    "banner_task_id": "",
                    "recipe": recipe,
                    "image_mode": image_mode,
                    "recipe_config": None,
                    "reason": f"soft_retry: 昨日 dead_letter, drama URL 已 verified ({recipe_reason})",
                    "priority": 80,  # 高优先, 排在 planner 首位
                    "match_score": score,
                    "breakdown": breakdown,
                    "decision_type": "soft_retry",
                    "hypothesis": f"重试 {drama} (昨日URL失效, 今日已修)",
                    "confidence": 0.7,
                    "expected_outcome": {"income_est": 1.5, "success_prob": 0.7},
                })
    except Exception as e:
        log.exception(f"[planner] soft_retry build failed: {e}")
    return retry_items


def _recent_recipes_for_account(account_id: int, n: int = 3) -> set[str]:
    """★ 2026-04-20 C: 查账号近 N 条发布用的 recipe, 下次避开.

    反快手针对某 recipe 建指纹模型. 从 publish_results JOIN task_queue.
    """
    if account_id <= 0 or n <= 0:
        return set()
    try:
        with _connect() as c:
            rows = c.execute(
                """SELECT DISTINCT tq.process_recipe
                   FROM publish_results pr
                   JOIN task_queue tq ON tq.id = pr.task_queue_id
                   WHERE pr.account_id = ?
                     AND pr.publish_status = 'success'
                     AND tq.process_recipe IS NOT NULL
                   ORDER BY pr.created_at DESC LIMIT ?""",
                (str(account_id), n)
            ).fetchall()
            return {r["process_recipe"] for r in rows if r["process_recipe"]}
    except Exception as e:
        log.debug("[planner] recent_recipes query failed: %s", e)
        return set()


def _pick_recipe(tier: str, drama_name: str = "",
                   account_id: int = 0,
                   task_source: str = "planner",
                   experiment_group: str | None = None) -> tuple[str, str]:
    """Unified recipe picker (自动分派 Path A/B/D).

    2026-04-20 ★ 升级:
      - Path D: scenario-aware knowledge pool
      - ★ C 强制轮换: 近 N 条发过的 recipe 排除, 反建模

    决策顺序:
      1. 若 experiment_group 设置 → 上层 (_assign_experiment_groups) 强制 recipe, 这里不调
      2. 查账号 recent_recipes (近 N 条发过的), 加入 exclude set
      3. 若 ai.recipe_knowledge.enabled=true → 走 scenario_scorer 从 knowledge 池选
      4. 若 pick 命中 exclude → 从剩余 pool 再 pick 一次 (保证每次换)
      5. pool 全 excluded → 强制选 pool 首个 (过载保护)
    """
    # ★ C: 查近期 recipe (可 disable)
    excluded_recipes = set()
    if cfg_get("ai.planner.recipe_rotation.enabled", True) and account_id > 0:
        rotate_n = int(cfg_get("ai.planner.recipe_rotation.lookback_count", 3))
        excluded_recipes = _recent_recipes_for_account(account_id, rotate_n)

    # Path D: scenario-aware knowledge pool
    if cfg_get("ai.recipe_knowledge.enabled", True):
        try:
            from core.scenario_scorer import pick_recipe_from_scenario
            account = {"id": account_id, "tier": tier}
            recipe, info = pick_recipe_from_scenario(
                account=account, drama_name=drama_name,
                task_source=task_source, experiment_group=experiment_group,
            )
            if recipe:
                scen = info["scenario"]
                pool_top3 = info.get("pool_top3", [])
                # ★ C: 若命中 exclude, 从 pool_top3 剩余中换
                if recipe in excluded_recipes and pool_top3:
                    for alt_recipe, *_rest in pool_top3:
                        if alt_recipe not in excluded_recipes:
                            reason = (
                                f"scenario={scen['scenario_tag']} "
                                f"pool={info['pool_size']} pick={alt_recipe} "
                                f"(rotated from {recipe}; excluded={list(excluded_recipes)[:2]})"
                            )
                            return alt_recipe, reason
                    # 全 excluded, 用第一个
                reason = (
                    f"scenario={scen['scenario_tag']} "
                    f"min={scen['min_strength']}/L3≥{scen['min_l3']}/"
                    f"ks184≥{int(scen['min_ks184_alignment']*100)}% "
                    f"pool={info['pool_size']} pick={recipe}"
                )
                if excluded_recipes:
                    reason += f" (recent_excl={list(excluded_recipes)[:2]})"
                return recipe, reason
        except Exception as e:
            log.debug("[planner] scenario_scorer failed, fallback: %s", e)

    # Path A/B fallback — 避开 exclude
    for _ in range(5):  # 最多试 5 次
        if tier in ("new", "testing"):
            r, reason = _pick_recipe_random(tier)
        else:
            r, reason = _pick_recipe_thompson(tier, drama_name)
        if r not in excluded_recipes or not excluded_recipes:
            if excluded_recipes:
                reason += f" (excl_recent={list(excluded_recipes)[:2]})"
            return r, reason
    return r, reason


# ★ E-4: image_mode 选择器 (对齐 KS184 UI 6 选 1)
AVAILABLE_IMAGE_MODES = [
    "qitian_art", "gradient_random", "random_shapes",
    "mosaic_rotate", "frame_transform", "random_chars",
]


def _pick_image_mode(tier: str, account_id: int = 0,
                      recipe: str = "") -> tuple[str, str]:
    """选 image_mode (pattern 素材风格).

    策略:
      - viral/established 账号: 偏好有历史数据的 (Thompson Sampling from strategy_memory)
      - testing/new: 随机探索 (给 Bandit 收样本)
      - 默认 fallback config.video.process.image_mode

    Returns:
        (image_mode, reason)
    """
    # 对齐 config 默认值 (UI 的"图片模式"6 选 1)
    default = cfg_get("video.process.image_mode", "random_shapes")

    if tier in ("new", "testing"):
        # 测试/新号: 纯随机探索
        pick = random.choice(AVAILABLE_IMAGE_MODES)
        return pick, f"random (tier={tier}, exploration)"

    # 其他 tier: 先看账号 Layer 2 记忆
    try:
        from core.account_memory import get_strategy_memory
        memory = get_strategy_memory(account_id) if account_id else None
        if memory:
            pref = memory.get("preferred_image_modes") or {}
            # 过滤 affinity > 0.5 的
            good = {k: v for k, v in pref.items() if v >= 0.5}
            if good:
                # 按 affinity 加权选一个
                items = list(good.items())
                weights = [v for _, v in items]
                pick = random.choices([k for k, _ in items],
                                        weights=weights, k=1)[0]
                return pick, f"memory pref (affinity={good[pick]:.2f})"
    except Exception as e:
        log.debug("[planner] pick_image_mode memory lookup failed: %s", e)

    # Fallback: 从剧本身/recipe 匹配 (无数据时)
    # zhizun/kirin 偏好艺术风格
    if recipe in ("zhizun_mode5_pipeline", "kirin_mode6", "zhizun", "zhizun_overlay"):
        pool = ["qitian_art", "random_shapes", "random_chars"]
    elif recipe in ("touming_9gong", "yemao"):
        pool = ["mosaic_rotate", "frame_transform"]  # 本就用视频帧
    else:
        pool = AVAILABLE_IMAGE_MODES
    pick = random.choice(pool)
    return pick, f"fallback_by_recipe (pool={pool})"


# ───────────────────────────────────────────────────────────────
# 时间窗分配 (今天内均匀分散)
# ───────────────────────────────────────────────────────────────

def _plan_schedule_times(n_tasks: int, run_date: str = None) -> list[str]:
    """把 N 条任务分派到今天的发布窗口.

    ★ 2026-04-20 A: 只用"审核宽松时段", 避开 9-11 + 20-22 紧时段.
    默认优先时段: [7,8,13,14,15,18,19] (7 个 hour slots, 1 每 task ±jitter min).
    """
    if not run_date:
        run_date = datetime.now().strftime("%Y-%m-%d")

    # ★ A: 优先时段列表 (审核宽松) — 可 config 覆盖
    pri_hours_raw = cfg_get("ai.planner.scheduled_hours_priority",
                             [7, 8, 13, 14, 15, 18, 19])
    if isinstance(pri_hours_raw, str):
        try:
            import json as _j
            pri_hours = _j.loads(pri_hours_raw)
        except Exception:
            pri_hours = [7, 8, 13, 14, 15, 18, 19]
    else:
        pri_hours = list(pri_hours_raw)
    pri_hours = sorted(set(int(h) for h in pri_hours if 0 <= int(h) <= 23))

    if not pri_hours:
        # fallback 到老逻辑
        pri_hours = list(range(9, 22))

    jitter_min = int(cfg_get("ai.planner.scheduled_jitter_min", 3))

    if n_tasks <= 0:
        return []

    # 每 task 分配一个时段 + 0-59 分钟均摊 + 随机 ±jitter
    import random
    base_dt = datetime.strptime(run_date, "%Y-%m-%d")
    # 每 hour slot 能容纳的 tasks = n_tasks / len(pri_hours) 上取整
    slots_per_hour = max(1, (n_tasks + len(pri_hours) - 1) // len(pri_hours))
    results = []
    idx = 0
    for h in pri_hours:
        for s in range(slots_per_hour):
            if idx >= n_tasks:
                break
            # 在 hour h 内均匀分布 minutes
            minute = (60 * s // slots_per_hour) + random.randint(0, max(1, 60 // slots_per_hour) - 1)
            minute = max(0, min(59, minute))
            # ±jitter 扰动防矩阵批量发
            jitter = random.randint(-jitter_min, jitter_min)
            dt = base_dt.replace(hour=h, minute=minute, second=random.randint(0, 59))
            dt = dt + timedelta(minutes=jitter)
            results.append(dt.strftime("%Y-%m-%d %H:%M:%S"))
            idx += 1
        if idx >= n_tasks:
            break
    # 随机 shuffle 避免按 hour 严格升序 (进一步反批量特征)
    random.shuffle(results)
    # 最终按时间排序 (给 scheduler 处理更顺)
    results.sort()
    return results


# ───────────────────────────────────────────────────────────────
# LLM 建议吸取 (Path C 软融合)
# ───────────────────────────────────────────────────────────────

def _load_llm_suggestions() -> dict:
    """读最新 approved research_notes, 转成 planner 可用的 hints."""
    with _connect() as c:
        r = c.execute("""
            SELECT suggestions_json FROM research_notes
            WHERE approved = 1
            ORDER BY research_date DESC LIMIT 1
        """).fetchone()
    if not r or not r["suggestions_json"]:
        return {}
    try:
        return json.loads(r["suggestions_json"])
    except Exception:
        return {}


# ───────────────────────────────────────────────────────────────
# Week 3 A-3/A-4: 笛卡尔积贪心分派
# ───────────────────────────────────────────────────────────────

def _cartesian_assign(accounts_by_tier: dict) -> list[dict]:
    """账号 × 剧 笛卡尔积评分排序 + 贪心分派.

    替代老的"每账号独立选剧": 现在全局看所有 (账号, 剧) 对 match_score,
    按分数高到低贪心分派, 保证:
      - 每账号配额 ≤ ai.planner.quota.<tier>
      - 每部剧至多分给 ai.planner.max_accounts_per_drama 个账号 (默认 3)
      - 冷却期内硬拒 (24h 内发过同剧)
      - 账号近 1h 多失败的被降权

    Returns:
        items list, 每条含 match_score / reason / tier / recipe.
    """
    from collections import defaultdict
    from core.match_scorer import match_score

    max_per_drama = int(cfg_get("ai.planner.max_accounts_per_drama", 3) or 3)
    score_threshold = float(cfg_get("ai.planner.min_match_score", 30) or 30)

    # ★ 2026-04-24 v6 Day 3: 全矩阵每日 item 硬顶来自 operation_mode
    #   startup(9)=9, growth(50)=100, volume(100)=400, matrix(300)=2000, scale=10000
    #   允许 config ai.planner.daily_budget_override 强制覆盖 (>= 1)
    # ★ v6 Day 4: MCN mode B (degraded) 时降额 (避免失败雪崩)
    try:
        from core.operation_mode import planner_daily_budget, current_mode, mcn_mode
        op_mode = current_mode()
        mcn_md = mcn_mode()
        daily_budget_cap = int(planner_daily_budget())
        if mcn_md == "B":
            degrade_ratio = float(cfg_get("ai.planner.mcn_b_mode_degrade_ratio", 0.3) or 0.3)
            old_cap = daily_budget_cap
            daily_budget_cap = max(1, int(daily_budget_cap * degrade_ratio))
            log.warning("[planner] ⚠️ MCN mode=B (degraded), "
                        "budget %d → %d (ratio=%.2f)",
                        old_cap, daily_budget_cap, degrade_ratio)
    except Exception as _e:
        log.warning("[planner] operation_mode 不可用, fallback 到无硬顶: %s", _e)
        op_mode = "unknown"
        mcn_md = "A"
        daily_budget_cap = 10_000_000  # 极大, 相当于不限
    override = int(cfg_get("ai.planner.daily_budget_override", 0) or 0)
    if override > 0:
        daily_budget_cap = override

    # 1. 收集所有有效账号 (非 frozen) + 剧池
    active_accounts = []
    for tier, accs in accounts_by_tier.items():
        if tier == "frozen":
            continue
        for a in accs:
            # ★ 2026-04-23: 带出 age/created_at/vertical 给 operation_policy 用
            active_accounts.append({
                "id": a["id"],
                "name": a["account_name"],
                "tier": tier,
                "account_age_days": a.get("account_age_days"),
                "created_at": a.get("created_at"),
                "creator_level": a.get("creator_level"),
                "vertical_category": a.get("vertical_category"),
                "vertical_locked": a.get("vertical_locked") or 0,
            })

    # ═══════════════════════════════════════════════════════════════════
    # ★ Path 0 (2026-04-23, §31 候选池链路主路) ★
    # ═══════════════════════════════════════════════════════════════════
    # 如果 candidate_builder (07:45) 已生成当日 daily_candidate_pool,
    # 直接消费这个 TOP N 结果, 跳过 Path 1a/1b/1c (legacy 3 池 UNION).
    #
    # 优势:
    #   - 5 层漏斗已过滤 (违规/时效/URL/佣金/矩阵)
    #   - 6 维 100 分评分完成 (match_scorer 是单账号维度, 这是跨剧维度, 互补)
    #   - 消除 planner 每轮重造 pool 的 SQL 开销
    #
    # 回退: 候选池空 / 关闭 → 保底走 Path 1a/1b/1c (原逻辑)
    drama_pool: list[dict] = []
    candidate_pool_used = False
    if bool(cfg_get("ai.candidate.enabled", True)):
        today_str = datetime.now().strftime("%Y-%m-%d")
        min_cs = float(cfg_get("ai.candidate.min_composite_score", 40))
        try:
            with _connect() as c:
                cp_rows = c.execute(
                    """SELECT drama_name, banner_task_id, biz_id, commission_rate,
                              promotion_type,
                              freshness_tier, w24h_count, w48h_count,
                              cdn_count, pool_count,
                              income_desc, income_numeric,
                              violation_status, violation_count,
                              score_freshness, score_url_ready, score_commission,
                              score_heat, score_matrix, score_penalty, composite_score,
                              notes
                       FROM daily_candidate_pool
                       WHERE pool_date = ?
                         AND (status IS NULL OR status IN ('pending','published'))
                         AND composite_score >= ?
                       ORDER BY composite_score DESC""",
                    (today_str, min_cs),
                ).fetchall()
            if cp_rows:
                for r in cp_rows:
                    rd = dict(r)
                    rd["_source"] = f"candidate_pool(cs={rd.get('composite_score', 0):.1f})"
                    # 统一字段: match_scorer 和 pair 构造都在用 recent_income_sum (legacy).
                    # 候选池没这个字段, 用 income_numeric 等价.
                    if rd.get("recent_income_sum") is None:
                        rd["recent_income_sum"] = rd.get("income_numeric") or 0
                    drama_pool.append(rd)
                candidate_pool_used = True
                log.info("[planner] ★ Path 0 (候选池): %d drama loaded from "
                         "daily_candidate_pool (date=%s, min_score=%.0f)",
                         len(drama_pool), today_str, min_cs)
            else:
                log.info("[planner] Path 0 候选池空 (date=%s, min_score=%.0f), "
                         "回退 Path 1a/1b/1c legacy", today_str, min_cs)
        except Exception as e:
            log.warning("[planner] candidate_pool load failed: %r (回退 legacy)", e)
            drama_pool = []
            candidate_pool_used = False

    # ─── Path 1a: drama_banner_tasks (legacy, 我们自己 30 天聚合) ───
    if not candidate_pool_used:
        with _connect() as c:
            # 只从 drama_banner_tasks 取有收益的剧 (对齐 selector 的 pool)
            min_income = cfg_get("selector.drama.min_income_30d", 50)
            min_count = cfg_get("selector.drama.min_income_count", 3)
            rows = c.execute(
                """SELECT drama_name, banner_task_id, recent_income_sum
                   FROM drama_banner_tasks
                   WHERE recent_income_sum >= ? AND recent_income_count >= ?
                   ORDER BY recent_income_sum DESC
                   LIMIT ?""",
                (float(min_income), int(min_count),
                 cfg_get("selector.drama.topN_pool", 50)),
            ).fetchall()
        drama_pool = [dict(r) for r in rows]

    # ★ Path 1b (2026-04-20): 把 high_income_dramas (MCN 镜像) 的 top-N 也补进来.
    # 这是 spark_highincome_dramas 直接来的 432 部"官方" 高收益剧,
    # 比 drama_banner_tasks (我们自己 30 天聚合) 更权威, 但缺 banner_task_id.
    # ★ 2026-04-21 14:30 hotfix: 强制要求 drama_banner_tasks.drama_name match
    # (之前 LEFT JOIN 允许 NULL banner → 14 条 "师娘/陆总" 简称剧进 pool 全挂 no_urls)
    # ★ 2026-04-23 §31: candidate_pool 已用时跳过 (1a/1b/1c 都跳)
    if not candidate_pool_used and cfg_get("ai.planner.use_high_income_pool", True):
        existing_names = {d["drama_name"] for d in drama_pool}
        topn_high_income = int(cfg_get("ai.planner.high_income.topN_inject", 50))
        with _connect() as c:
            for r in c.execute(
                """SELECT h.title AS drama_name, h.rank_position,
                          d.banner_task_id, d.recent_income_sum
                   FROM high_income_dramas h
                   INNER JOIN drama_banner_tasks d ON d.drama_name = h.title    -- ★ INNER, 强制 banner 有对应
                   WHERE h.rank_position IS NOT NULL
                     AND d.banner_task_id IS NOT NULL                            -- ★ banner_task_id 非空
                     AND NOT EXISTS (
                         SELECT 1 FROM drama_blacklist b
                         WHERE b.drama_name = h.title AND b.status = 'active'
                     )
                   ORDER BY h.rank_position ASC
                   LIMIT ?""",
                (topn_high_income,),
            ):
                if r["drama_name"] in existing_names:
                    continue
                drama_pool.append({
                    "drama_name": r["drama_name"],
                    "banner_task_id": r["banner_task_id"],     # 可能 None (将走 fallback)
                    "recent_income_sum": r["recent_income_sum"] or 0,
                    "_source": f"high_income_rank={r['rank_position']}",
                })
                existing_names.add(r["drama_name"])
        log.info("[planner] drama_pool extended: total=%d (incl. high_income)",
                 len(drama_pool))

    # ★ Path 1c (2026-04-20 v28): 从 mcn_drama_library (134k 全量 MCN 剧库) 二阶筛选.
    # 按 commission_rate + 活跃期 + 非黑名单 → 取 top N.
    # 意义: 让 AI "看到" 快手 MCN 最新高分佣剧, 不再局限已采 4591 条 banner_tasks.
    # ★ 2026-04-23 §31: candidate_pool 已用时跳过 (1a/1b/1c 都跳)
    if not candidate_pool_used and cfg_get("ai.planner.use_drama_library", True):
        existing_names = {d["drama_name"] for d in drama_pool}
        topn_library = int(cfg_get("ai.planner.drama_library.topN_inject", 100))
        min_commission = float(cfg_get("ai.planner.drama_library.min_commission", 30.0))
        prefer_types = cfg_get("ai.planner.drama_library.promotion_types", [0, 7])
        if isinstance(prefer_types, str):
            try:
                import json as _j
                prefer_types = _j.loads(prefer_types)
            except Exception:
                prefer_types = [0, 7]
        require_active = cfg_get("ai.planner.drama_library.require_active_period", True)
        # promotion_type IN (...) — 0/None = 老萤光, 7 = CPS
        type_clause = "AND (ml.promotion_type IS NULL OR ml.promotion_type IN ({}))".format(
            ",".join(str(int(t)) for t in prefer_types)) if prefer_types else ""
        active_clause = ("AND (ml.end_time IS NULL OR ml.end_time >= strftime('%s','now'))"
                         if require_active else "")
        before = len(drama_pool)
        with _connect() as c:
            for r in c.execute(
                f"""SELECT ml.title AS drama_name, ml.biz_id, ml.commission_rate,
                           ml.promotion_type, ml.start_time, ml.end_time,
                           d.banner_task_id, d.recent_income_sum
                   FROM mcn_drama_library ml
                   INNER JOIN drama_banner_tasks d ON d.drama_name = ml.title   -- ★ 2026-04-21 14:30: INNER JOIN
                   WHERE ml.title IS NOT NULL
                     AND ml.commission_rate >= ?
                     AND d.banner_task_id IS NOT NULL                            -- ★ 强制 banner 有
                     {type_clause}
                     {active_clause}
                     AND NOT EXISTS (
                         SELECT 1 FROM drama_blacklist b
                         WHERE b.drama_name = ml.title AND b.status = 'active'
                     )
                   ORDER BY ml.commission_rate DESC, ml.end_time DESC
                   LIMIT ?""",
                (min_commission, topn_library),
            ):
                if r["drama_name"] in existing_names:
                    continue
                drama_pool.append({
                    "drama_name": r["drama_name"],
                    "banner_task_id": r["banner_task_id"],   # 多数为 None, 发布时 fallback
                    "biz_id": r["biz_id"],
                    "commission_rate": r["commission_rate"],
                    "promotion_type": r["promotion_type"],
                    "recent_income_sum": r["recent_income_sum"] or 0,
                    "_source": f"drama_library(c={r['commission_rate']:.0f})",
                })
                existing_names.add(r["drama_name"])
        added = len(drama_pool) - before
        log.info("[planner] drama_pool from mcn_drama_library (134k): +%d (total=%d), "
                 "min_commission=%s, types=%s", added, len(drama_pool),
                 min_commission, prefer_types)

    # ★ 2026-04-21 19:25 emergency hotfix: 只选 drama_links 已有 URL 的剧
    # (放在所有 Path 1a/1b/1c 之后, 一次性过滤全池)
    # 原因: profile/feed + generate_share_link + search_by_keyword 都被快手风控,
    # collector_on_demand 拿不到新 URL. 临时只用已有 URL 的剧避免 no_urls 风暴.
    if bool(cfg_get("ai.planner.require_existing_urls", False)):
        existing = set()
        with _connect() as c:
            for r in c.execute("""
                SELECT DISTINCT dl.drama_name
                FROM drama_links dl
                WHERE dl.status='pending'
                  AND dl.drama_url IS NOT NULL AND dl.drama_url != ''
                  AND (dl.cooldown_until IS NULL OR dl.cooldown_until < datetime('now'))
                  AND (dl.quarantined_at IS NULL OR (julianday('now')-julianday(dl.quarantined_at))>7)
            """):
                existing.add(r["drama_name"])
        before_n = len(drama_pool)
        drama_pool = [d for d in drama_pool if d["drama_name"] in existing]
        log.info("[planner] require_existing_urls final filter: %d → %d",
                 before_n, len(drama_pool))

    # ★ 2026-04-22 §26: 用 mcn_url_pool (181万 KS184 剧库镜像) 作为 final 过滤
    # 确保 planner 选的每条剧在池子里**至少有 N 条 URL 候选**, 对齐 KS184 高转化提取行为.
    # 这是从"本地 drama_links 只能用已下过的" 升级到 "MCN 剧库 14973 部剧都能选".
    if bool(cfg_get("ai.planner.require_mcn_pool_urls", True)):
        min_urls = int(cfg_get("ai.planner.mcn_pool_min_urls", 3))
        try:
            from core.drama_pool import count_urls_for_drama
            before_n = len(drama_pool)
            filtered = []
            for d in drama_pool:
                counts = count_urls_for_drama(d["drama_name"])
                # 任一源有 >= min_urls 条 URL 即可 (drama_links CDN 或 mcn_url_pool 短链)
                total_urls = counts["pool"] + counts["drama_links"]
                if total_urls >= min_urls:
                    d["_url_count"] = total_urls  # 带出字段, 后续排序用
                    filtered.append(d)
            drama_pool = filtered
            log.info("[planner] require_mcn_pool_urls (min=%d): %d → %d",
                     min_urls, before_n, len(drama_pool))
        except Exception as e:
            log.warning("[planner] mcn_url_pool filter failed: %r", e)

    log.info("[planner] cartesian: %d accounts × %d dramas = %d pairs "
             "(source=%s)",
             len(active_accounts), len(drama_pool),
             len(active_accounts) * len(drama_pool),
             "candidate_pool" if candidate_pool_used else "legacy_1a+1b+1c")

    # 2. 计算所有 pair 的 score
    # ★ E-5 硬断修复: 先 pick recipe + image_mode 再调 match_score,
    # 这样 match_scorer 的 4 新信号 (affinity/avoid/trust/novelty) 才能生效
    pairs = []
    for acc in active_accounts:
        for drama in drama_pool:
            # 预选 recipe 和 image_mode (给 match_scorer 用)
            # ★ 2026-04-20: 传 account_id 让 scenario_scorer 看账号失败历史
            pre_recipe, pre_recipe_reason = _pick_recipe(
                acc["tier"], drama["drama_name"],
                account_id=acc["id"],
                task_source="planner",
            )
            pre_image_mode, pre_img_reason = _pick_image_mode(
                acc["tier"], account_id=acc["id"], recipe=pre_recipe
            )

            score, breakdown = match_score(
                account_id=acc["id"], account_tier=acc["tier"],
                drama_name=drama["drama_name"],
                recipe=pre_recipe,           # ★ E-5: 传给 affinity/novelty 信号
                image_mode=pre_image_mode,   # ★ E-5: 传给 affinity/novelty 信号
            )
            if score < score_threshold:
                continue
            pairs.append({
                "account_id": acc["id"], "account_name": acc["name"],
                "account_tier": acc["tier"],
                # ★ 2026-04-23 传给 quota_for_account 做动态判定
                "account_age_days": acc.get("account_age_days"),
                "created_at": acc.get("created_at"),
                "creator_level": acc.get("creator_level"),
                "drama_name": drama["drama_name"],
                "banner_task_id": drama.get("banner_task_id") or "",
                "score": score, "breakdown": breakdown,
                # ★ E-5: 保存预选的 recipe/image_mode, 最终 item 构造时直接用
                "recipe": pre_recipe,
                "recipe_reason": pre_recipe_reason,
                "image_mode": pre_image_mode,
                "image_mode_reason": pre_img_reason,
                # ★ 2026-04-23 §31: 候选池 6 维分, 供 Dashboard/记忆回溯
                "candidate_composite_score": drama.get("composite_score"),
                "candidate_source": drama.get("_source"),
                "freshness_tier": drama.get("freshness_tier"),
                "violation_status": drama.get("violation_status"),
            })

    # 3. 按 score 降序排序, 平局随机打散 (避免前几账号吃满配额)
    # 多加一个随机 tiebreak 让平局时不按账号 id 顺序分派
    random.shuffle(pairs)  # 先洗牌
    pairs.sort(key=lambda p: -p["score"])  # 再按 score 稳定排 (平局保持洗牌后顺序)
    log.info("[planner] %d pairs above threshold (≥%d), sorted + shuffled",
             len(pairs), score_threshold)

    per_account_assigned = defaultdict(int)
    per_drama_assigned = defaultdict(int)
    # ★ 2026-04-23 P2-3: 同账号发多条时, 限制同一赛道占比, 防同质化降权
    # 用户要求: 作品垂直发布, 但同账号 5 条最好分 2-3 个 subtrack
    per_account_subtracks = defaultdict(lambda: defaultdict(int))  # {acc_id: {subtrack: count}}
    items = []

    # ★ 2026-04-22 §28_K: 保证每个 active 账号至少 min_per_account 个任务
    # 背景: 今日 百洁 (acct=3, MCN ¥0.38) 因 income_bonus 太弱被挤出全部 pair.
    # §28_J 已提高 income 权重, 再加保底: 用"两轮排序" — 第一轮优先给每账号最高分 pair,
    # 第二轮填满剩余配额.
    min_per_account = int(cfg_get("ai.planner.min_items_per_account", 1))
    active_account_ids = {a["id"] for a in active_accounts}
    log.info("[planner] min_items_per_account=%d, active=%d",
             min_per_account, len(active_account_ids))

    # 构造 "按账号分组的 pair 列表" — 每账号自己的 pair 按 score 降序
    pairs_by_acct = defaultdict(list)
    for pair in pairs:
        pairs_by_acct[pair["account_id"]].append(pair)

    # 两轮 pair 排序:
    # Round 1: 每账号取自己最高分 N 个 pair (轮换排列), 保证覆盖
    # Round 2: 余下 pair 按全局 score 降序
    ordered_pairs = []
    round1_pairs_set = set()   # (account_id, drama_name) 已在 round 1
    for round_idx in range(min_per_account):
        for acc_id in sorted(active_account_ids):
            plist = pairs_by_acct.get(acc_id, [])
            if round_idx < len(plist):
                p = plist[round_idx]
                ordered_pairs.append(p)
                round1_pairs_set.add((p["account_id"], p["drama_name"]))

    # Round 2: 剩余 pairs (不在 round 1) 按 score 降序
    for pair in pairs:
        key = (pair["account_id"], pair["drama_name"])
        if key not in round1_pairs_set:
            ordered_pairs.append(pair)

    log.info("[planner] round1=%d (保底), round2=%d (贪心). total=%d",
             len(round1_pairs_set), len(ordered_pairs) - len(round1_pairs_set),
             len(ordered_pairs))

    for pair in ordered_pairs:
        # ★ 2026-04-24 v6 Day 3: 全矩阵 daily budget 硬顶 (operation_mode)
        if len(items) >= daily_budget_cap:
            log.info("[planner] ★ reached operation_mode daily_budget_cap=%d "
                     "(mode=%s), stop. pair skipped after: %d",
                     daily_budget_cap, op_mode,
                     len(ordered_pairs) - ordered_pairs.index(pair))
            break

        acc_id = pair["account_id"]
        drama = pair["drama_name"]
        tier = pair["account_tier"]
        # ★ 2026-04-23: 传 account dict 给 quota 用 (按年龄 + creator_level 动态)
        acc_obj = {
            "tier": tier,
            "account_age_days": pair.get("account_age_days"),
            "created_at": pair.get("created_at"),
            "creator_level": pair.get("creator_level"),
        }
        quota = _get_quota(tier, account=acc_obj)

        # 约束检查
        if per_account_assigned[acc_id] >= quota:
            continue
        if per_drama_assigned[drama] >= max_per_drama:
            continue

        # ★ 2026-04-23 P2-3: 同账号同 subtrack 上限 (策略种子: 垂直 + 避免过度集中)
        # 例: 5 条任务不要全是同赛道, 允许一个赛道最多 quota * max_same_pct (默认 60%)
        try:
            from core.operation_policy import policy as _pol
            st_info = _pol().subtrack_for_drama(drama)
            if st_info:
                sub_code = st_info[1]
                max_same_pct = float(cfg_get("ai.planner.subtrack_max_ratio", 0.6) or 0.6)
                max_same = max(2, int(quota * max_same_pct))
                if per_account_subtracks[acc_id][sub_code] >= max_same:
                    continue
        except Exception:
            sub_code = None

        # ★ E-5: 复用 pair 里预选的 recipe 和 image_mode (match_score 已计算用)
        recipe = pair.get("recipe") or _pick_recipe(
            tier, drama, account_id=acc_id, task_source="planner"
        )[0]
        recipe_reason = pair.get("recipe_reason", "")
        image_mode = pair.get("image_mode", "")
        image_mode_reason = pair.get("image_mode_reason", "")

        # Priority (tier 基础分, dynamic 由 scheduler 入队再算)
        priority = {"viral": 90, "established": 70,
                    "warming_up": 50, "testing": 30, "new": 20}.get(tier, 30)

        # ★ P2-2: 丰富 decision_type / hypothesis / confidence 给记忆用
        decision_type = "exploit_high_tier" if tier in ("viral", "established") else \
                         ("explore_new_recipe" if "explore" in (recipe_reason or "").lower()
                          else "test_account")
        # hypothesis 根据 breakdown 合成自然语言
        bd = pair['breakdown']
        hypothesis = (
            f"{tier} 账号 + {drama} "
            f"(热度{bd.get('heat_bonus',0):.0f}, 同剧 div={bd.get('diversity_bonus',0)}) "
            f"→ 预期 {recipe} {recipe_reason[:60] if recipe_reason else ''}"
        )
        # confidence: 原始 match_score normalize 到 0-1 (假设 150 满分)
        confidence = max(0.1, min(0.95, pair["score"] / 150.0))

        # 预期收益 (粗估)
        expected_income = round(
            (bd.get("tier_weight", 0) / 10 + bd.get("heat_bonus", 0) / 3) * confidence,
            2
        )

        items.append({
            "account_id": acc_id,
            "account_name": pair["account_name"],
            "account_tier": tier,
            "drama_name": drama,
            "banner_task_id": pair["banner_task_id"],
            "recipe": recipe,
            "image_mode": image_mode,    # ★ E-5: 确保不为空
            "reason": (
                f"match_score={pair['score']:.1f} "
                f"[tier={bd['tier_weight']} "
                f"+income={bd['income_bonus']} "
                f"+heat={bd['heat_bonus']} "
                f"+div={bd['diversity_bonus']} "
                f"+affinity={bd.get('affinity_signal', 0)} "
                f"+avoid={bd.get('avoid_penalty', 0)} "
                f"+trust={bd.get('trust_signal', 0)} "
                f"+novelty={bd.get('novelty_bonus', 0)} "
                f"cd={bd['cooldown_penalty']}]"
                f"; recipe:{recipe_reason}; img:{image_mode_reason}"
            )[:500],
            "priority": priority,
            "match_score": pair["score"],
            # ★ 新增字段 (给 record_decision 用)
            "breakdown": bd,
            "decision_type": decision_type,
            "hypothesis": hypothesis,
            "confidence": confidence,
            "expected_outcome": {
                "income_est": expected_income,
                "success_prob": confidence,
            },
        })
        per_account_assigned[acc_id] += 1
        per_drama_assigned[drama] += 1
        # ★ 2026-04-23 P2-3: 记录该账号该 subtrack 已分派数
        try:
            if 'sub_code' in locals() and sub_code:
                per_account_subtracks[acc_id][sub_code] += 1
        except Exception:
            pass

    log.info("[planner] assigned %d items: %d unique accounts × %d unique dramas "
             "(mode=%s, budget_cap=%d)",
             len(items),
             len(per_account_assigned), len(per_drama_assigned),
             op_mode, daily_budget_cap)
    return items


# ───────────────────────────────────────────────────────────────
# Phase 2 Round 2.3: C 实验任务 (P2-7)
# ───────────────────────────────────────────────────────────────

# 实验设计模板: 3 组不同的 (recipe, image_mode) 组合
# 用于对照测试: "哪种去重策略收益最好?"
# ★ 2026-04-23: 升级 EXPERIMENT_VARIANTS — B 组从 zhizun_overlay (弱 ⭐⭐⭐)
# 换成 zhizun_mode5_pipeline (王炸 ⭐⭐⭐⭐⭐ interleave + matroska 伪装).
# A 组 kirin_mode6 (王炸) vs B 组 mode5_pipeline (王炸) 对比真实 KS184 主力.
# C 组保留 light_noise 做"对照下限".
EXPERIMENT_VARIANTS = [
    # Group A: 控制组 — kirin_mode6 (王炸, KS184 主力 1)
    {"group": "A", "label": "control_kirin",
     "recipe": "kirin_mode6",              "image_mode": "random_shapes"},
    # Group B: 高强度 — zhizun_mode5_pipeline (王炸, KS184 主力 2)
    {"group": "B", "label": "high_intensity_mode5",
     "recipe": "zhizun_mode5_pipeline",    "image_mode": "qitian_art"},
    # Group C: 对照下限 — 轻噪点 + 帧马赛克
    {"group": "C", "label": "low_intensity_baseline",
     "recipe": "light_noise_recode",       "image_mode": "mosaic_rotate"},
]


def _assign_experiment_groups(items: list[dict]) -> dict:
    """P2-7: 从 items 中选出 ~10% 作实验组 (A/B/C), 强制他们用不同策略.

    核心设计:
      - 只在 testing/warming_up 账号中抽 (保护 viral/established 生产账号)
      - 每组 ≥ ai.experiment.min_group_size (默认 3 账号)
      - 最多 ai.experiment.max_groups 组 (默认 3 = A/B/C)
      - 覆盖 item.recipe + item.image_mode 并标 experiment_group
      - reason 字段加 [EXP-X] 前缀方便运营追踪

    Returns:
        {
          "enabled": bool,
          "assigned": int,            # 被标为实验的 item 数
          "groups": {"A": n, "B": n, ...},
          "variants_used": [{"group": "A", "recipe": "...", ...}]
        }
    """
    result = {"enabled": False, "assigned": 0, "groups": {},
              "variants_used": [], "skip_reason": None}

    if not cfg_get("ai.experiment.enabled", True):
        result["skip_reason"] = "disabled_by_config"
        return result
    if not items:
        result["skip_reason"] = "no_items"
        return result

    result["enabled"] = True
    explore_rate = float(cfg_get("ai.experiment.explore_rate", 0.10))
    min_group = int(cfg_get("ai.experiment.min_group_size", 3))
    max_groups = int(cfg_get("ai.experiment.max_groups", 3))

    # 只在 testing/warming_up 账号中抽 (保护 viral/established)
    # 冷启动: 如果全是 new/testing, 也包含 new
    has_warming_plus = any(i.get("account_tier") in ("warming_up", "established", "viral")
                           for i in items)
    if has_warming_plus:
        candidates = [i for i in items
                      if i.get("account_tier") in ("testing", "warming_up")]
    else:
        # 冷启动: 全是 new/testing, 允许 new 参与
        candidates = [i for i in items
                      if i.get("account_tier") in ("new", "testing", "warming_up")]

    # 自适应 min_group: 小 plan 允许更小的对照组 (保证 2 组对照至少能跑)
    # 规则: total ≥ 60 → full min_group; 20-60 → 降 1; < 20 → 降到 2
    adaptive_min = min_group
    if len(items) < 20:
        result["skip_reason"] = f"plan_too_small ({len(items)} < 20)"
        return result
    if len(items) < 60 and min_group >= 3:
        adaptive_min = 2
    if len(candidates) < adaptive_min * 2:
        result["skip_reason"] = (
            f"candidates<{adaptive_min * 2} ({len(candidates)})")
        return result

    # 计算实验池大小 (受 explore_rate 和候选数限制)
    target_pool = int(len(items) * explore_rate)
    # 对小 plan 保底: 至少尝试 2 组 × adaptive_min, 即使 explore_rate 不够
    target_pool = max(target_pool, adaptive_min * 2)

    # 按 adaptive_min 向下取整让分组整齐
    n_groups = min(max_groups,
                    max(1, target_pool // adaptive_min),
                    len(candidates) // adaptive_min)
    if n_groups < 2:
        result["skip_reason"] = (
            f"n_groups<2 (target_pool={target_pool}, "
            f"candidates={len(candidates)}, adaptive_min={adaptive_min})")
        return result

    pool_size = n_groups * adaptive_min
    variants = EXPERIMENT_VARIANTS[:n_groups]
    # 传给下面的分组循环用
    min_group = adaptive_min

    # 随机抽取 pool_size 个候选 items (洗牌后分组)
    random.shuffle(candidates)
    experiment_items = candidates[:pool_size]

    groups_count = {}
    for gi, variant in enumerate(variants):
        start = gi * min_group
        end = start + min_group
        for item in experiment_items[start:end]:
            item["experiment_group"] = variant["group"]
            # 覆盖 recipe + image_mode (这是实验的关键 — 测不同策略的收益)
            original_recipe = item.get("recipe")
            original_image_mode = item.get("image_mode")
            item["recipe"] = variant["recipe"]
            item["image_mode"] = variant["image_mode"]
            # 把实验信息存到 reason 供追踪
            item["reason"] = (
                f"[EXP-{variant['group']}/{variant['label']}] "
                f"orig_recipe={original_recipe}, orig_img={original_image_mode}; "
                f"{item.get('reason', '')}"
            )[:500]
            # 改 task_source 和 decision_type
            item["task_source"] = "experiment"
            item["decision_type"] = f"experiment_{variant['group']}"
            groups_count[variant["group"]] = groups_count.get(variant["group"], 0) + 1

    result["assigned"] = pool_size
    result["groups"] = groups_count
    result["variants_used"] = variants
    log.info("[planner] experiment: assigned %d items to %d groups: %s",
             pool_size, n_groups, groups_count)
    return result


def _persist_experiment_record(
    plan_date: str,
    plan_id: int,
    experiment_info: dict,
    items: list[dict],
) -> str | None:
    """P2-7: 写一条 strategy_experiments 行, 每个实验 item 写 experiment_assignments.

    Returns:
        experiment_code (或 None 如果没有实验)
    """
    if experiment_info.get("assigned", 0) == 0:
        return None

    variants = experiment_info.get("variants_used", [])
    exp_code = f"exp_{plan_date.replace('-', '')}_{plan_id}"

    with _connect() as c:
        # 主实验记录
        hypothesis = (
            f"比较 {len(variants)} 种去重策略的收益: "
            + " vs ".join(f"{v['group']}={v['recipe']}+{v['image_mode']}" for v in variants)
        )
        c.execute("""
            INSERT INTO strategy_experiments
              (experiment_code, experiment_name, hypothesis, variable_name,
               control_group, test_group, sample_target, sample_current,
               success_metric, success_threshold, stop_condition, status,
               created_by_agent, started_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, 'running',
                    'strategy_planner_agent',
                    datetime('now','localtime'),
                    datetime('now','localtime'))
        """, (
            exp_code,
            f"{plan_date} 实验 {len(variants)}组",
            hypothesis[:500],
            "recipe+image_mode",
            variants[0]["group"] if variants else "A",
            ",".join(v["group"] for v in variants[1:]),
            experiment_info["assigned"],
            "avg_income_per_task",
            1.0,   # 某组比控制组高 1.0 ¥/task 即显著
            f"sample_reached OR day_passed=7",
        ))

        # 每个实验 item 写 assignment
        for item in items:
            if not item.get("experiment_group"):
                continue
            c.execute("""
                INSERT INTO experiment_assignments
                  (experiment_code, account_id, drama_name, strategy_name,
                   group_name, task_id, publish_result_id, status,
                   outcome_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, NULL, NULL, 'pending', NULL,
                        datetime('now','localtime'),
                        datetime('now','localtime'))
            """, (
                exp_code,
                str(item["account_id"]),
                item["drama_name"],
                f"{item['recipe']}+{item.get('image_mode', '')}",
                item["experiment_group"],
            ))
        c.commit()
    log.info("[planner] experiment saved: code=%s, %d assignments",
             exp_code, experiment_info["assigned"])
    return exp_code


# ───────────────────────────────────────────────────────────────
# 主入口
# ───────────────────────────────────────────────────────────────

def run(plan_date: str | None = None, dry_run: bool = False,
        enforce_test_budget: bool = True) -> dict[str, Any]:
    """生成今日 plan.

    Returns:
        {plan_id, plan_date, total_tasks, items: [...]}
    """
    plan_date = plan_date or datetime.now().strftime("%Y-%m-%d")
    log.info("[planner] generating plan for %s (dry_run=%s)", plan_date, dry_run)

    # 已存在今日 plan → 不重复 (除非 dry_run)
    with _connect() as c:
        exist = c.execute("SELECT id FROM daily_plans WHERE plan_date=?",
                          (plan_date,)).fetchone()
        if exist and not dry_run:
            log.info("[planner] plan_date=%s 已存在 (id=%s), 跳过", plan_date, exist["id"])
            return {"ok": True, "already_exists": True, "plan_id": exist["id"]}

    # 1. 按 tier 收集账号
    accounts_by_tier = {t: list_accounts_by_tier(t) for t in TIERS}
    total_accounts = sum(len(a) for a in accounts_by_tier.values())

    # 2. 加载 LLM suggestions (Path C)
    llm_hints = _load_llm_suggestions()

    # 3. ★ Week 3 A-3/A-4: 笛卡尔积贪心分派 (替代 "按 tier 独立选剧")
    items = _cartesian_assign(accounts_by_tier)

    # 3b. ★ B (2026-04-20): 软重试 — 昨日 dead_letter 的 (drama, account) 优先重排
    # 条件: drama 现在有 verified URL (step 20 已验过) + 该账号近 24h 没成功发过同剧
    if cfg_get("ai.planner.soft_retry_enabled", True):
        retry_boost_items = _build_soft_retry_items(accounts_by_tier)
        if retry_boost_items:
            # 把 retry items 放最前 (优先排 schedule 早时段)
            existing_keys = {(i["account_id"], i["drama_name"]) for i in items}
            new_retry = [ri for ri in retry_boost_items
                         if (ri["account_id"], ri["drama_name"]) not in existing_keys]
            if new_retry:
                items = new_retry + items
                log.info("[planner] soft_retry 补入 %d items (昨日失败的 drama 现已 verified)",
                         len(new_retry))

    # 4. 测试预算上限 (防全军覆没在 TESTING)
    # 冷启动 edge: 如果所有账号都 new/testing (没 warming_up+), 跳过截断 (否则直接砍 70%)
    if enforce_test_budget and items:
        test_pct_limit = cfg_get("ai.planner.test_budget_pct", 30)
        n_total = len(items)
        n_test = sum(1 for i in items if i["account_tier"] in ("new", "testing"))
        n_prod = n_total - n_test
        if n_prod == 0:
            log.info("[planner] 冷启动 (全为 new/testing), 跳过 test_budget 截断")
        elif n_test * 100 / n_total > test_pct_limit:
            # 截断测试条目
            max_test = int(n_total * test_pct_limit / 100)
            test_items = [i for i in items if i["account_tier"] in ("new", "testing")][:max_test]
            other_items = [i for i in items if i["account_tier"] not in ("new", "testing")]
            items = test_items + other_items
            log.info("[planner] test_budget 截断: %d → %d items", n_total, len(items))

    # 5. 分配时间窗 ★ 2026-04-20 升级: 按账号分配, 保证同账号 ≥ min_interval_min
    _assign_schedule_per_account(items, run_date=plan_date)

    # 5.5 ★ P2-7: 实验组分派 (C 实验任务)
    # 从 items 中抽 ~10% 标 experiment_group='A'/'B'/'C', 强制用不同 recipe
    experiment_info = _assign_experiment_groups(items)

    # 6. 写 DB
    if dry_run:
        return {
            "ok": True, "dry_run": True, "plan_date": plan_date,
            "total_accounts": total_accounts, "total_items": len(items),
            "items_preview": items[:10],
            "experiment": experiment_info,
            "tier_distribution": {t: len(a) for t, a in accounts_by_tier.items()},
        }

    with _connect() as c:
        cur = c.execute("""
            INSERT INTO daily_plans
              (plan_date, total_accounts, total_tasks, planner, strategy, meta_json)
            VALUES (?, ?, ?, 'strategy_planner_agent', ?, ?)
        """, (plan_date, total_accounts, len(items),
              cfg_get("selector.strategy", "top_weighted_random"),
              json.dumps({"llm_hints_used": bool(llm_hints),
                          "tier_distribution": {t: len(a) for t, a in accounts_by_tier.items()}},
                         ensure_ascii=False)))
        plan_id = cur.lastrowid

        # ★ P2-2 + E-4: INSERT plan_items (含 image_mode + recipe_config_json)
        # 同步写 decision_history (Layer 1)
        from core.account_memory import record_decision

        for item in items:
            # recipe_config 序列化 (供 scheduler 拆 params)
            rc_json = None
            rc = item.get("recipe_config")
            if rc:
                try:
                    rc_json = json.dumps(rc, ensure_ascii=False)
                except Exception:
                    rc_json = None

            cur = c.execute("""
                INSERT INTO daily_plan_items
                  (plan_id, account_id, account_tier, drama_name, banner_task_id,
                   recipe, image_mode, recipe_config_json,
                   scheduled_at, priority, reason, match_score,
                   experiment_group)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (plan_id, item["account_id"], item["account_tier"],
                  item["drama_name"], item["banner_task_id"], item["recipe"],
                  item.get("image_mode", ""),    # ★ E-4
                  rc_json,                         # ★ E-7 预留
                  item["scheduled_at"], item["priority"],
                  item["reason"][:500],
                  item.get("match_score"),
                  item.get("experiment_group")))   # ★ P2-7 实验组
            plan_item_id = cur.lastrowid

            # ★ 同步写 decision_history — 给 AI 记忆一条事件
            breakdown = item.get("breakdown") or {}
            confidence = item.get("confidence", 0.5)
            decision_type = item.get("decision_type", "cartesian_match")
            hypothesis = item.get("hypothesis") or item.get("reason", "")[:200]
            expected = item.get("expected_outcome") or {
                # 简陋预期: 按 breakdown 估一个 income
                "income_est": round(
                    (breakdown.get("tier_weight", 0) / 10 +
                     breakdown.get("heat_bonus", 0) / 5) * confidence, 2
                ),
                "success_prob": confidence,
            }
            # ★ 2026-04-20 bug fix: 复用 planner 的 c 连接批量 insert
            # 避免为每条 item 新开 _connect() 导致 DB lock (WAL 单 writer)
            try:
                c.execute(
                    """INSERT INTO account_decision_history
                         (account_id, decision_date, plan_item_id, task_id,
                          drama_name, recipe, image_mode,
                          decision_type, hypothesis, confidence,
                          score_breakdown, alternatives_json, expected_outcome,
                          verdict)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending')""",
                    (int(item["account_id"]), plan_date, plan_item_id, None,
                     item["drama_name"], item["recipe"],
                     item.get("image_mode", ""),
                     decision_type, hypothesis[:400], float(confidence),
                     json.dumps(breakdown, ensure_ascii=False, default=str),
                     json.dumps(item.get("alternatives", []),
                                ensure_ascii=False, default=str),
                     json.dumps(expected, ensure_ascii=False, default=str)),
                )
            except Exception as e:
                log.warning("[planner] decision_history insert failed: %s "
                             "(account=%s drama=%s)", e,
                             item.get("account_id"), item.get("drama_name"))
        c.commit()

    # ★ P2-7: 实验记录落地 (strategy_experiments + experiment_assignments)
    exp_code = None
    try:
        exp_code = _persist_experiment_record(
            plan_date=plan_date,
            plan_id=plan_id,
            experiment_info=experiment_info,
            items=items,
        )
    except Exception as e:
        log.exception("[planner] persist experiment failed: %s", e)

    log.info("[planner] plan_id=%s items=%s experiment=%s",
             plan_id, len(items), exp_code or "none")
    return {
        "ok": True, "plan_id": plan_id, "plan_date": plan_date,
        "total_accounts": total_accounts, "total_items": len(items),
        "experiment": experiment_info,
        "experiment_code": exp_code,
        "tier_distribution": {t: len(a) for t, a in accounts_by_tier.items()},
    }


if __name__ == "__main__":
    import sys, json as _j
    sys.stdout.reconfigure(encoding="utf-8")
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--plan-date", default=None)
    args = ap.parse_args()
    r = run(plan_date=args.plan_date, dry_run=args.dry_run)
    print(_j.dumps(r, ensure_ascii=False, indent=2, default=str))
