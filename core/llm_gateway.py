# -*- coding: utf-8 -*-
"""Hermes LLM gateway client (OpenAI 兼容).

Hermes 启动: C:\\Users\\Administrator\\Desktop\\Hermes Gateway.cmd
  → http://127.0.0.1:8642/v1/models (需要 Authorization: Bearer <key>)
  → 当前模型: hermes-agent

使用:
    from core.llm_gateway import chat
    r = chat(
        messages=[{"role": "user", "content": "分析这批数据..."}],
        temperature=0.3,
        max_tokens=2000,
    )
    # → {"ok": True, "text": "...", "model": "...", "elapsed_sec": 1.2}
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)


def _load_api_key() -> str:
    import os
    key_path = cfg_get("ai.llm.api_key_path",
                       r"D:\AIbot\swarmclaw-stack\config\hermes\api-server.key")
    if os.path.isfile(key_path):
        return open(key_path, "r", encoding="utf-8").read().strip()
    return ""


def is_online(timeout: float = 3.0) -> bool:
    """快速检测 LLM 可用 (任一 provider).

    ★ 2026-04-20 升级: 不再只查 Hermes, 而是问 LLMClient 能否拿到可用 provider
    (aliyun / codex / deepseek 任一就算 online).
    """
    try:
        from core.llm.client import LLMClient
        return LLMClient().available
    except Exception:
        pass
    # fallback: 老 Hermes 探
    base = cfg_get("ai.llm.base_url", "http://127.0.0.1:8642/v1")
    key = _load_api_key()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    try:
        r = requests.get(f"{base}/models", headers=headers, timeout=timeout)
        return r.status_code == 200
    except Exception:
        return False


def chat(
    messages: list[dict],
    model: str | None = None,
    temperature: float = 0.3,
    max_tokens: int = 2000,
    timeout: int = 60,
    fail_silent: bool = True,
) -> dict[str, Any]:
    """单次 chat completion, 返回文本 or 错误.

    Args:
        messages: OpenAI 格式 [{"role":"system|user|assistant", "content":"..."}]
        model: 模型名. None = 读 ai.llm.model
        temperature: 创造性 (决策类 0.3; 头脑风暴 0.7)
        max_tokens: 最大 token
        timeout: HTTP 超时
        fail_silent: True 失败返回 {ok:False,...}, False 抛异常

    Returns:
        {ok, text, model, elapsed_sec, usage?, error?}
    """
    if not cfg_get("ai.llm.enabled", True):
        return {"ok": False, "error": "llm_disabled_in_config"}

    # ★ 2026-04-20 升级: 统一走 LLMClient (多 provider 自动 fallback,
    # priority aliyun → codex → codex-mini → deepseek → siliconflow → openai)
    t0 = time.time()
    try:
        from core.llm.client import LLMClient
        cli = LLMClient()
        if not cli.available:
            return {"ok": False, "error": "no_provider_available",
                    "elapsed_sec": round(time.time() - t0, 2)}
        # 拆 messages 成 system_prompt + user_prompt
        system_prompt = ""
        user_prompt = ""
        for m in messages:
            if m["role"] == "system":
                system_prompt += m["content"] + "\n"
            elif m["role"] == "user":
                user_prompt += m["content"] + "\n"
            elif m["role"] == "assistant":
                user_prompt += f"(上一条回复: {m['content'][:200]})\n"
        text = cli.chat(
            system_prompt=system_prompt.strip() or "你是专业的运营分析师.",
            user_prompt=user_prompt.strip(),
            max_tokens=max_tokens,
            temperature=temperature,
        )
        if not text:
            return {"ok": False, "error": "empty_response",
                    "elapsed_sec": round(time.time() - t0, 2)}
        return {
            "ok": True, "text": text,
            "model": cli.model,
            "provider": cli.provider_name,
            "elapsed_sec": round(time.time() - t0, 2),
        }
    except Exception as e:
        if not fail_silent:
            raise
        log.warning("[llm_gateway] chat failed: %s", e)
        return {"ok": False, "error": f"exception: {e}",
                "elapsed_sec": round(time.time() - t0, 2)}


if __name__ == "__main__":
    import json, sys
    sys.stdout.reconfigure(encoding="utf-8")
    print(f"Hermes online: {is_online()}")
    r = chat(
        messages=[
            {"role": "system", "content": "你是快手短剧矩阵运营分析师, 请简短回答."},
            {"role": "user", "content": "如果一个账号连续 3 天播放量为 0, 你会怎么判断?"},
        ],
        max_tokens=200,
    )
    print(json.dumps(r, ensure_ascii=False, indent=2))
