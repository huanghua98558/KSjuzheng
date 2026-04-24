# -*- coding: utf-8 -*-
"""统一 secrets 读取 — 中心化所有凭证.

★ 2026-04-24 v6 Week 2: 把 20 文件 35 处硬编码凭证 全部迁到这里.

★ 设计:
  3 级优先级 (先高级后低级):
    1. 环境变量              KS_MCN_PHONE / KS_MCN_PASS / ...
    2. .secrets.json 文件     位于 repo root
    3. 硬编码 fallback        保留历史值, 但 log WARNING

  所有消费方只调 `get("KEY")`, 看不到具体来源 (除非开 KS_SECRETS_DEBUG=1).

★ 已知凭证 (完整清单):
  captain 登录:
    KS_CAPTAIN_PHONE      默认 "REPLACE_WITH_YOUR_PHONE"
    KS_CAPTAIN_PASSWORD   默认 "REPLACE_WITH_YOUR_PASSWORD"
    KS_CAPTAIN_OWNER_CODE 默认 "黄华"
    KS_CAPTAIN_USER_ID    默认 "946"

  MCN MySQL 直连:
    KS_MCN_MYSQL_HOST     默认 "im.zhongxiangbao.com"
    KS_MCN_MYSQL_PORT     默认 3306
    KS_MCN_MYSQL_USER     默认 "shortju"
    KS_MCN_MYSQL_PASSWORD 默认 "REPLACE_WITH_MCN_MYSQL_PASSWORD"
    KS_MCN_MYSQL_DB       默认 "shortju"

  MCN API base:
    KS_MCN_API_BASE       默认 "http://im.zhongxiangbao.com:8000"
    KS_MCN_SIG3_URL       默认 "http://im.zhongxiangbao.com:50002"

  HMAC 签名密钥 (Frida 破解得):
    KS_HMAC_SECRET         默认 "REPLACE_WITH_HMAC_SECRET"
    KS_MCN_RESPONSE_SECRET 默认 "REPLACE_WITH_MCN_RESP_SECRET"

★ 用法:
  from core.secrets import get, get_mcn_mysql_config

  phone = get("KS_CAPTAIN_PHONE")
  mcn_db = get_mcn_mysql_config()     # → pymysql 直用的 dict

★ 快速部署 (第一次设):
  1. cp .secrets.json.example .secrets.json
  2. 编辑 .secrets.json 填真实值
  3. chmod 600 .secrets.json (防 git 误提交, 已在 .gitignore)

  或:
  export KS_CAPTAIN_PHONE=...
  export KS_CAPTAIN_PASSWORD=...

★ 审计:
  python -m core.secrets --audit
  → 列出所有 key 的当前来源 + 是否用 fallback
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

log = logging.getLogger(__name__)

# 所有已知 secret 的硬编码 fallback (历史兼容, 迁完清理)
_HARDCODED_FALLBACKS: dict[str, str] = {
    # captain
    "KS_CAPTAIN_PHONE": "REPLACE_WITH_YOUR_PHONE",
    "KS_CAPTAIN_PASSWORD": "REPLACE_WITH_YOUR_PASSWORD",
    "KS_CAPTAIN_OWNER_CODE": "黄华",
    "KS_CAPTAIN_USER_ID": "946",

    # MCN MySQL 直连
    "KS_MCN_MYSQL_HOST": "im.zhongxiangbao.com",
    "KS_MCN_MYSQL_PORT": "3306",
    "KS_MCN_MYSQL_USER": "shortju",
    "KS_MCN_MYSQL_PASSWORD": "REPLACE_WITH_MCN_MYSQL_PASSWORD",
    "KS_MCN_MYSQL_DB": "shortju",

    # MCN HTTP API
    "KS_MCN_API_BASE": "http://im.zhongxiangbao.com:8000",
    "KS_MCN_SIG3_URL": "http://im.zhongxiangbao.com:50002",

    # HMAC secrets (Frida 2026-04-17 破解)
    "KS_HMAC_SECRET": "REPLACE_WITH_HMAC_SECRET",
    "KS_MCN_RESPONSE_SECRET": "REPLACE_WITH_MCN_RESP_SECRET",
}


# 读 .secrets.json 一次 (进程级 cache)
_JSON_CACHE: dict[str, str] | None = None
_WARNED_KEYS: set[str] = set()   # 只警告一次


def _secrets_file_path() -> Path:
    """默认在 repo root. 允许 KS_SECRETS_FILE 指定."""
    override = os.environ.get("KS_SECRETS_FILE", "").strip()
    if override:
        return Path(override)
    # repo root = core/../  (core/secrets.py → D:/ks_automation/)
    return Path(__file__).resolve().parent.parent / ".secrets.json"


def _load_json() -> dict[str, str]:
    global _JSON_CACHE
    if _JSON_CACHE is not None:
        return _JSON_CACHE
    path = _secrets_file_path()
    if not path.is_file():
        _JSON_CACHE = {}
        return _JSON_CACHE
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            log.warning("[secrets] %s 不是 dict, 忽略", path)
            _JSON_CACHE = {}
            return _JSON_CACHE
        # 全转字符串 (避免 int/bool 混入)
        _JSON_CACHE = {k: str(v) for k, v in data.items()}
    except Exception as e:
        log.warning("[secrets] 读 %s 失败: %s", path, e)
        _JSON_CACHE = {}
    return _JSON_CACHE


def invalidate_cache() -> None:
    """清 .secrets.json cache (测试 / 运维手动改 json 后调)."""
    global _JSON_CACHE
    _JSON_CACHE = None


def get(key: str, default: str | None = None) -> str:
    """读 secret. 3 级优先级.

    Args:
        key: 如 "KS_CAPTAIN_PHONE"
        default: 当 env / json / fallback 都缺时返这个. None → 抛 KeyError

    Returns:
        字符串 value (所有 secret 统一 str)
    """
    # 1. 环境变量
    v = os.environ.get(key)
    if v is not None and v != "":
        return v

    # 2. .secrets.json
    jd = _load_json()
    if key in jd and jd[key] != "":
        return jd[key]

    # 3. 硬编码 fallback
    if key in _HARDCODED_FALLBACKS:
        if key not in _WARNED_KEYS and os.environ.get("KS_SECRETS_WARN", "").strip() in ("1", "true"):
            log.warning("[secrets] %s 用 hardcoded fallback — 建议 .secrets.json 覆盖", key)
            _WARNED_KEYS.add(key)
        return _HARDCODED_FALLBACKS[key]

    # 4. 用户默认
    if default is not None:
        return default

    raise KeyError(f"secret '{key}' 未定义 (查 env, .secrets.json, fallback 都缺)")


def source_of(key: str) -> str:
    """查某 key 当前从哪来 (env / json / hardcoded / missing)."""
    if os.environ.get(key):
        return "env"
    if key in _load_json() and _load_json()[key] != "":
        return "secrets.json"
    if key in _HARDCODED_FALLBACKS:
        return "hardcoded"
    return "missing"


def all_keys() -> list[str]:
    """已知的所有 secret key (union of json, env-matching, hardcoded)."""
    keys = set(_HARDCODED_FALLBACKS.keys())
    keys.update(_load_json().keys())
    for k in os.environ:
        if k.startswith("KS_"):
            keys.add(k)
    return sorted(keys)


# ──────────────────────────────────────────────────────────────────────
# Convenience helpers — 常用组合
# ──────────────────────────────────────────────────────────────────────
def get_mcn_mysql_config() -> dict:
    """返 pymysql.connect() 可直接用的 dict."""
    import pymysql
    return {
        "host": get("KS_MCN_MYSQL_HOST"),
        "port": int(get("KS_MCN_MYSQL_PORT", "3306")),
        "user": get("KS_MCN_MYSQL_USER"),
        "password": get("KS_MCN_MYSQL_PASSWORD"),
        "database": get("KS_MCN_MYSQL_DB"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "connect_timeout": 5,
        "read_timeout": 10,
        "write_timeout": 10,
    }


def get_captain_login() -> dict:
    """返 captain 登录 dict (老 MCN_CONFIG 兼容)."""
    return {
        "phone": get("KS_CAPTAIN_PHONE"),
        "password": get("KS_CAPTAIN_PASSWORD"),
        "owner_code": get("KS_CAPTAIN_OWNER_CODE"),
        "base_url": get("KS_MCN_API_BASE"),
        "sig_url": get("KS_MCN_SIG3_URL"),
    }


def get_hmac_secret() -> bytes:
    """sig3 HMAC 主密钥."""
    return get("KS_HMAC_SECRET").encode("utf-8")


def get_mcn_response_secret() -> bytes:
    """MCN 响应签名密钥."""
    return get("KS_MCN_RESPONSE_SECRET").encode("utf-8")


# ──────────────────────────────────────────────────────────────────────
# CLI — 审计 / 诊断
# ──────────────────────────────────────────────────────────────────────
def main():
    import argparse
    ap = argparse.ArgumentParser(description="Secrets 审计工具")
    ap.add_argument("--audit", action="store_true", default=True,
                     help="列所有 key + 来源 + 是否 fallback")
    ap.add_argument("--show-values", action="store_true",
                     help="打印实际 value (危险 — 仅本地调试!)")
    ap.add_argument("--write-example", action="store_true",
                     help="生成 .secrets.json.example (所有 key + 空值)")
    args = ap.parse_args()

    if args.write_example:
        path = Path(__file__).resolve().parent.parent / ".secrets.json.example"
        template = {k: "" for k in sorted(_HARDCODED_FALLBACKS.keys())}
        with path.open("w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2, sort_keys=True)
        print(f"✅ 写入 {path}")
        return

    print("═══ Secrets 审计 ═══")
    print(f"  .secrets.json: {_secrets_file_path()}")
    print(f"  存在?            {_secrets_file_path().is_file()}")
    print()
    print(f"{'key':<35} {'source':<14} {'masked_value'}")
    print("─" * 80)
    for k in all_keys():
        src = source_of(k)
        try:
            v = get(k)
            if args.show_values:
                display = v
            else:
                # masked
                if len(v) <= 4:
                    display = "****"
                else:
                    display = v[:2] + "*" * (len(v) - 4) + v[-2:]
        except KeyError:
            display = "(missing)"
        print(f"{k:<35} {src:<14} {display}")

    # 判断是否全 fallback
    hc_count = sum(1 for k in _HARDCODED_FALLBACKS if source_of(k) == "hardcoded")
    total = len(_HARDCODED_FALLBACKS)
    print()
    print(f"── 用 hardcoded 的: {hc_count}/{total}")
    if hc_count > 0:
        print(f"   建议: 创建 .secrets.json 覆盖 (模板: python -m core.secrets --write-example)")


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    main()
