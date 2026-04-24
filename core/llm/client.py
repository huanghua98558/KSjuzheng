# -*- coding: utf-8 -*-
"""统一 LLM 客户端 — 6 Provider 自动 fallback + trace 集成.

抽自 decision_engine.py 的 LLMClient, 升级为项目级共享模块.

核心特性:
  1. 自动 provider 探测 (Hermes 本地 → Codex → DeepSeek → SiliconFlow → Aliyun → OpenAI)
  2. 每次调用自动回写 agent_runs.llm_calls_json (如传入 run_id)
  3. JSON 模式 (chat_json) 自动剥 markdown code fence
  4. 超时/异常 fallback (provider 切换)
  5. 与 openai 官方 SDK 协议 100% 兼容

用法:
    from core.llm import LLMClient
    llm = LLMClient()                       # 自动探测最优 provider
    llm = LLMClient(provider="codex")       # 强制指定 GPT-5.4
    reply = llm.chat("你是分析员.", "末世为什么热?")
    data  = llm.chat_json(sys, usr)         # 返回 dict, 失败返回 None
"""
from __future__ import annotations

import json
import os
import time
import urllib.request
from typing import Any, Callable, Optional

from core.logger import get_logger

logger = get_logger("llm_client")

try:
    from openai import OpenAI
    OPENAI_SDK_AVAILABLE = True
except ImportError:
    OPENAI_SDK_AVAILABLE = False


# ---------------------------------------------------------------------------
# Provider 元数据
# ---------------------------------------------------------------------------

LLM_PROVIDERS: dict[str, dict[str, Any]] = {
    "codex": {
        "base_url": "http://127.0.0.1:8642/v1",
        "api_key_file": r"D:\AIbot\swarmclaw-stack\config\hermes\api-server.key",
        "model": "gpt-5.4",
        "description": "Codex GPT-5.4 via Hermes (复杂任务, Pro 覆盖)",
        "cost_per_mtoken_in":  0.0,
        "cost_per_mtoken_out": 0.0,
        "is_local": True,
    },
    "codex-mini": {
        "base_url": "http://127.0.0.1:8642/v1",
        "api_key_file": r"D:\AIbot\swarmclaw-stack\config\hermes\api-server.key",
        "model": "gpt-5.4-mini",
        "description": "Codex GPT-5.4 mini via Hermes (快速批量, Pro 覆盖)",
        "cost_per_mtoken_in":  0.0,
        "cost_per_mtoken_out": 0.0,
        "is_local": True,
    },
    "deepseek": {
        "base_url": "https://api.deepseek.com/v1",
        "api_key_env": "DEEPSEEK_API_KEY",
        "api_key": "sk-69b28d14b0374362ab110a99b3164098",
        "model": "deepseek-chat",
        "description": "DeepSeek V3.2 (¥1/M tokens ≈ $0.14)",
        "cost_per_mtoken_in":  0.14,
        "cost_per_mtoken_out": 0.28,
        "is_local": False,
    },
    "siliconflow": {
        "base_url": "https://api.siliconflow.cn/v1",
        "api_key_env": "SILICONFLOW_API_KEY",
        "api_key": "sk-yhntnkjkpfyebhlgknhkbzkmlojihgxhmuplsjdxvppwhynm",
        "model": "deepseek-ai/DeepSeek-V3",
        "description": "SiliconFlow DeepSeek-V3",
        "cost_per_mtoken_in":  0.27,
        "cost_per_mtoken_out": 1.10,
        "is_local": False,
    },
    "aliyun": {
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "api_key_env": "DASHSCOPE_API_KEY",
        "api_key": "sk-92b0cec5b87c4c739794c2b767685cc1",
        "model": "qwen-plus-latest",   # ★ 2026-04-20 用户要求 Qwen 3.6 Plus (latest 指 3.x 最新)
        "description": "阿里云百炼 Qwen 3.6 Plus (主决策模型, priority 1)",
        "cost_per_mtoken_in":  0.80,
        "cost_per_mtoken_out": 2.00,
        "is_local": False,
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "api_key_env": "OPENAI_API_KEY",
        "model": "gpt-4.1-nano",
        "description": "OpenAI 直连 gpt-4.1-nano",
        "cost_per_mtoken_in":  0.10,
        "cost_per_mtoken_out": 0.40,
        "is_local": False,
    },
}

# 默认优先级 (本地优先, 费用最低优先)
DEFAULT_CANDIDATES = ["aliyun", "codex", "codex-mini", "deepseek", "siliconflow", "openai"]


# ---------------------------------------------------------------------------
# 核心客户端
# ---------------------------------------------------------------------------

class LLMClient:
    """统一 LLM 客户端."""

    DEFAULT_TIMEOUT = 120
    DEFAULT_TEMPERATURE = 0.3
    DEFAULT_MAX_TOKENS = 1024
    HEALTH_CHECK_TIMEOUT = 1.5

    def __init__(
        self,
        provider: str | None = None,
        api_key: str | None = None,
        timeout: int = DEFAULT_TIMEOUT,
        temperature: float = DEFAULT_TEMPERATURE,
        max_tokens: int = DEFAULT_MAX_TOKENS,
    ) -> None:
        self.provider_name: str = "none"
        self.model: str = ""
        self.available: bool = False
        self._client: Any = None
        self._cfg: dict[str, Any] = {}
        self.timeout = timeout
        self.temperature = temperature
        self.max_tokens = max_tokens

        # Trace callback — 外部注入, 每次 call 结束自动写 agent_runs
        self._trace_cb: Optional[Callable[[dict], None]] = None

        if not OPENAI_SDK_AVAILABLE:
            logger.warning("openai SDK 未安装 — LLM 模式禁用")
            return

        candidates = [provider] if provider and provider in LLM_PROVIDERS else list(DEFAULT_CANDIDATES)

        for name in candidates:
            cfg = LLM_PROVIDERS.get(name)
            if not cfg:
                continue
            key = self._resolve_key(cfg, api_key)
            if not key:
                continue
            if cfg.get("is_local") and not self._local_alive(cfg):
                logger.debug("Provider %s 本地端点不通, 跳过", name)
                continue
            try:
                self._client = OpenAI(
                    api_key=key,
                    base_url=cfg["base_url"],
                    timeout=self.timeout,
                )
                self.provider_name = name
                self.model = cfg["model"]
                self._cfg = cfg
                self.available = True
                logger.info("LLM 就绪: %s (%s, model=%s)",
                            name, cfg["description"], self.model)
                break
            except Exception as exc:
                logger.debug("init provider %s 失败: %s", name, exc)

        if not self.available:
            logger.warning("所有 LLM provider 不可用 — 回退纯规则模式")

    # ------------------------------------------------------------------
    # Trace hook
    # ------------------------------------------------------------------

    def set_trace_callback(self, cb: Callable[[dict], None]) -> None:
        """Agent 创建 LLMClient 后通过这个注入 trace 写入逻辑."""
        self._trace_cb = cb

    def _emit_trace(self, record: dict) -> None:
        if self._trace_cb is None:
            return
        try:
            self._trace_cb(record)
        except Exception as exc:
            logger.debug("trace 回调失败: %s", exc)

    # ------------------------------------------------------------------
    # 内部: key + 存活性
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_key(cfg: dict, explicit: str | None) -> str | None:
        if explicit:
            return explicit
        if cfg.get("api_key"):
            return cfg["api_key"]
        if cfg.get("api_key_file"):
            try:
                with open(cfg["api_key_file"], "r", encoding="utf-8") as f:
                    return f.read().strip()
            except (FileNotFoundError, PermissionError):
                return None
        if cfg.get("api_key_env"):
            return os.getenv(cfg["api_key_env"]) or None
        return None

    @classmethod
    def _local_alive(cls, cfg: dict) -> bool:
        try:
            req = urllib.request.Request(cfg["base_url"] + "/models", method="GET")
            key = cls._resolve_key(cfg, None)
            if key:
                req.add_header("Authorization", f"Bearer {key}")
            urllib.request.urlopen(req, timeout=cls.HEALTH_CHECK_TIMEOUT)
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # 公开 API
    # ------------------------------------------------------------------

    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        purpose: str = "",
        agent_name: str = "",
        run_id: str = "",
    ) -> str | None:
        """发送 chat completion, 返回文本 (失败返回 None)."""
        if not self.available:
            return None
        t0 = time.time()
        prompt_tokens = completion_tokens = 0
        error_msg = ""
        content: str | None = None
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user",   "content": user_prompt},
                ],
                temperature=self.temperature if temperature is None else temperature,
                max_tokens=self.max_tokens if max_tokens is None else max_tokens,
            )
            content = resp.choices[0].message.content
            prompt_tokens = getattr(resp.usage, "prompt_tokens", 0) or 0
            completion_tokens = getattr(resp.usage, "completion_tokens", 0) or 0
        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.warning("LLM 调用失败 [%s]: %s", self.provider_name, error_msg)
        latency_ms = int((time.time() - t0) * 1000)

        cost = self._estimate_cost(prompt_tokens, completion_tokens)
        record = {
            "provider": self.provider_name,
            "model": self.model,
            "purpose": purpose,
            "agent_name": agent_name,
            "run_id": run_id,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "latency_ms": latency_ms,
            "cost_usd": cost,
            "ok": bool(content) and not error_msg,
            "error": error_msg,
            "system_preview": (system_prompt or "")[:150],
            "user_preview": (user_prompt or "")[:200],
            "response_preview": (content or "")[:300],
            "ts": time.time(),
        }
        self._emit_trace(record)
        return content

    def chat_json(
        self,
        system_prompt: str,
        user_prompt: str,
        **kwargs,
    ) -> dict | None:
        """chat() + 解析 JSON (自动剥 markdown code fence)."""
        system_prompt = (
            system_prompt
            + "\n\n严格以 JSON 对象格式回答, 不要加任何文字解释或 markdown 标记."
        )
        raw = self.chat(system_prompt, user_prompt, **kwargs)
        if raw is None:
            return None
        text = raw.strip()
        # 剥 markdown 围栏
        if text.startswith("```"):
            lines = [l for l in text.split("\n") if not l.strip().startswith("```")]
            text = "\n".join(lines)
        # 尝试截取第一个 { ... }
        if not text.startswith("{"):
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start:end + 1]
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning("JSON 解析失败: %s", text[:200])
            return None

    # ------------------------------------------------------------------
    # 成本估算
    # ------------------------------------------------------------------

    def _estimate_cost(self, p_tokens: int, c_tokens: int) -> float:
        in_price  = self._cfg.get("cost_per_mtoken_in",  0) or 0
        out_price = self._cfg.get("cost_per_mtoken_out", 0) or 0
        return round(p_tokens / 1_000_000 * in_price + c_tokens / 1_000_000 * out_price, 6)

    # ------------------------------------------------------------------
    # 自省
    # ------------------------------------------------------------------

    def info(self) -> dict:
        return {
            "available": self.available,
            "provider": self.provider_name,
            "model": self.model,
            "is_local": bool(self._cfg.get("is_local")),
            "description": self._cfg.get("description", ""),
            "cost_per_mtoken_in": self._cfg.get("cost_per_mtoken_in"),
            "cost_per_mtoken_out": self._cfg.get("cost_per_mtoken_out"),
        }


# ---------------------------------------------------------------------------
# 便捷工厂
# ---------------------------------------------------------------------------

_singleton: LLMClient | None = None


def get_llm(provider: str | None = None, force_new: bool = False) -> LLMClient:
    """返回全局复用的 LLMClient (除非指定 provider 或 force_new)."""
    global _singleton
    if force_new or provider or _singleton is None:
        client = LLMClient(provider=provider)
        if not provider and not force_new:
            _singleton = client
        return client
    return _singleton
