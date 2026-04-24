# -*- coding: utf-8 -*-
"""运营策略种子 — 从 app_config.ai.policy.operation.seed_json 读.

★ 2026-04-23: 固化用户"思维导图"为系统唯一决策源 (docs/OPERATION_POLICY_SEED.md).

核心契约:
  - 7 赛道 (女频 3 + 男频 4) 每个账号锁定 1 个子赛道
  - 新号前 3 天 → 每天 4 条
  - V3-V4 → 每天 5 条
  - V5+ → 无上限 (保底 15)
  - 作品必须垂直发布 (subtrack 匹配)

用法:
    from core.operation_policy import policy
    pol = policy()
    pol.quota_for_account(account_row)     # 返回每日配额
    pol.subtrack_for_drama(drama_name)     # 返回 (track, subtrack) 或 None
    pol.is_vertical_match(account_subtrack, drama_subtrack)
"""
from __future__ import annotations

import datetime
import json
import logging
import threading
from typing import Any

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


# 默认 fallback (万一 app_config 被误删)
_DEFAULT_SEED = {
    "version": "1.0",
    "source": "builtin_fallback",
    "tracks": {
        "female": {"name": "女频", "subtracks": {
            "modern_emotion":   {"name": "现代情感", "tags": ["甜宠", "虐渣", "先婚后爱"]},
            "ancient_romance":  {"name": "古风言情", "tags": ["古风", "宫斗", "重生"]},
            "imaginative":      {"name": "脑洞爽剧", "tags": ["快穿", "系统", "末世"]},
        }},
        "male": {"name": "男频", "subtracks": {
            "workplace_war":        {"name": "职场商战", "tags": ["职场", "商战"]},
            "fantasy_cultivation":  {"name": "玄幻修仙", "tags": ["玄幻", "修仙", "战神"]},
            "system_flow":          {"name": "系统流",   "tags": ["系统流", "签到"]},
            "historical_travel":    {"name": "历史穿越", "tags": ["历史", "穿越"]},
        }},
    },
    "publishing_rules": {
        "first_3_days": {"count_per_day": 4},
        "day_4_onwards": {
            "creator_level_v1_v2": {"count": 4},
            "creator_level_v3_v4": {"count": 5},
            "creator_level_v5_plus": {"count": 15},
        },
    },
    "tier_mapping": {
        "new":         {"target_quota": 4},
        "testing":     {"target_quota": 5},
        "warming_up":  {"target_quota": 5},
        "established": {"target_quota": 8},
        "viral":       {"target_quota": 15},
    },
}


class OperationPolicy:
    """从 app_config 读 seed, 提供决策 API."""

    _singleton: "OperationPolicy | None" = None
    _lock = threading.Lock()

    @classmethod
    def load(cls, force_reload: bool = False) -> "OperationPolicy":
        with cls._lock:
            if cls._singleton is None or force_reload:
                cls._singleton = cls()
            return cls._singleton

    def __init__(self):
        self._seed: dict[str, Any] = _DEFAULT_SEED
        self._tag_to_subtrack: dict[str, tuple[str, str]] = {}
        self._reload()

    def _reload(self) -> None:
        try:
            raw = cfg_get("ai.policy.operation.seed_json", None)
            if raw:
                self._seed = json.loads(raw) if isinstance(raw, str) else raw
        except Exception as e:
            log.warning("[policy] load seed failed: %s (use fallback)", e)
            self._seed = _DEFAULT_SEED

        # 建 tag → (track, subtrack) 倒排索引
        self._tag_to_subtrack.clear()
        for tk_code, tk in (self._seed.get("tracks") or {}).items():
            for sub_code, sub in (tk.get("subtracks") or {}).items():
                self._tag_to_subtrack[sub.get("name", "")] = (tk_code, sub_code)
                for tag in sub.get("tags", []):
                    self._tag_to_subtrack[tag] = (tk_code, sub_code)

    # ───────────────────────────────────────────────────────────
    # 1. 赛道分类: drama_name → (track, subtrack)
    # ───────────────────────────────────────────────────────────

    def subtrack_for_drama(self, drama_name: str) -> tuple[str, str] | None:
        """按剧名关键词匹配到最精确的 subtrack.

        匹配顺序 (长的优先 → 避免 "古代" 吃掉 "古代言情"):
          - 按 tag/name 长度降序
          - 第一个出现在 drama_name 的就是
        """
        if not drama_name:
            return None
        keys = sorted(self._tag_to_subtrack.keys(), key=lambda k: -len(k))
        for tag in keys:
            if tag and tag in drama_name:
                return self._tag_to_subtrack[tag]
        return None

    def subtrack_name(self, subtrack_code: str) -> str:
        """subtrack_code → 中文名 (modern_emotion → 现代情感)."""
        for tk in (self._seed.get("tracks") or {}).values():
            sub = (tk.get("subtracks") or {}).get(subtrack_code)
            if sub:
                return sub.get("name", subtrack_code)
        return subtrack_code

    def all_subtracks(self) -> list[dict]:
        """所有 7 个子赛道: [{code, name, track, tags}]."""
        out = []
        for tk_code, tk in (self._seed.get("tracks") or {}).items():
            for sub_code, sub in (tk.get("subtracks") or {}).items():
                out.append({
                    "code": sub_code,
                    "name": sub.get("name", ""),
                    "track": tk_code,
                    "track_name": tk.get("name", ""),
                    "tags": sub.get("tags", []),
                })
        return out

    # ───────────────────────────────────────────────────────────
    # 2. 配额 quota: account_row → 每日条数
    # ───────────────────────────────────────────────────────────

    def quota_for_account(self, account: dict) -> int:
        """按账号年龄 + tier 决定每日配额 (对齐用户思维导图).

        Args:
            account: {'tier': str, 'account_age_days': int, 'created_at': str,
                      'creator_level': str | None}

        Logic:
          - account_age_days < 3 → 4 条 (前 3 天新号期)
          - 有 creator_level = v5+ → 15 条 (无上限)
          - 有 creator_level = v3/v4 → 5 条
          - 否则按 tier_mapping 落 (默认 5)
        """
        rules = (self._seed.get("publishing_rules") or {})
        first3 = int((rules.get("first_3_days") or {}).get("count_per_day") or 4)
        day4 = rules.get("day_4_onwards") or {}

        # 账号年龄
        age = self._age_days(account)
        if age is not None and age < 3:
            return first3

        # 创作者等级 (如果数据里有)
        level = str(account.get("creator_level") or "").lower()
        if level in ("v5", "v6", "v7", "v8", "v9", "v10"):
            return int((day4.get("creator_level_v5_plus") or {}).get("count") or 15)
        if level in ("v3", "v4"):
            return int((day4.get("creator_level_v3_v4") or {}).get("count") or 5)
        if level in ("v1", "v2"):
            return int((day4.get("creator_level_v1_v2") or {}).get("count") or 4)

        # fallback: tier_mapping
        tier = str(account.get("tier") or "testing")
        tm = (self._seed.get("tier_mapping") or {})
        return int((tm.get(tier) or {}).get("target_quota") or 5)

    def _age_days(self, account: dict) -> int | None:
        age = account.get("account_age_days")
        if age is not None:
            try:
                return int(age)
            except Exception:
                pass
        # fallback: 从 created_at 计算
        c = account.get("created_at") or ""
        if not c:
            return None
        try:
            c_dt = datetime.datetime.strptime(str(c)[:19], "%Y-%m-%d %H:%M:%S")
            return int((datetime.datetime.now() - c_dt).total_seconds() / 86400)
        except Exception:
            return None

    # ───────────────────────────────────────────────────────────
    # 3. 垂直锁定: 账号-剧 匹配
    # ───────────────────────────────────────────────────────────

    def is_vertical_match(self, account_subtrack: str | None,
                          drama_subtrack: str | None) -> bool:
        """账号 subtrack 是否匹配剧的 subtrack (垂直发布核心规则)."""
        if not account_subtrack or not drama_subtrack:
            return False
        return account_subtrack == drama_subtrack

    def principles(self) -> list[str]:
        return list(self._seed.get("key_principles") or [])

    def raw(self) -> dict:
        return dict(self._seed)


# 模块级单例
def policy() -> OperationPolicy:
    return OperationPolicy.load()


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    pol = policy()
    print("=== 策略种子摘要 ===")
    print(f"版本: {pol.raw().get('version')}")
    print(f"来源: {pol.raw().get('source')}")
    print()
    print("7 赛道:")
    for s in pol.all_subtracks():
        print(f"  {s['track_name']} / {s['name']:<10} ({s['code']}) "
              f"tags={s['tags']}")
    print()
    print("核心原则:")
    for p in pol.principles():
        print(f"  - {p}")
    print()
    print("=== 剧名分类测试 ===")
    for d in ["财源滚滚小厨神", "甜宠小娇妻", "仙尊重生之路",
              "霸道总裁的小娇妻", "职场大女主归来", "修仙修了十万年",
              "系统流之大佬人生", "穿越古代当皇帝", "未知短剧 ABC"]:
        r = pol.subtrack_for_drama(d)
        if r:
            print(f"  {d:<20} → {r[0]} / {pol.subtrack_name(r[1])}")
        else:
            print(f"  {d:<20} → (未分类)")
    print()
    print("=== Quota 测试 ===")
    for desc, acc in [
        ("1 天新号", {"tier": "new", "created_at": (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d %H:%M:%S")}),
        ("5 天试号", {"tier": "testing", "account_age_days": 5}),
        ("10 天", {"tier": "warming_up", "account_age_days": 10}),
        ("V3 创作者", {"creator_level": "v3", "account_age_days": 30}),
        ("V5 创作者", {"creator_level": "v5", "account_age_days": 60}),
    ]:
        q = pol.quota_for_account(acc)
        print(f"  {desc:<12} quota={q}")
