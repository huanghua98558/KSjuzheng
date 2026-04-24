# -*- coding: utf-8 -*-
"""Signature service for Kuaishou __NS_sig3 generation.

__NS_sig3 是快手 CP API 的混淆 JS 签名 (非 HMAC), 目前依赖远程签名服务.
本模块在此基础上增加生产级韧性:

  1. 多端点失败转移: 50002 → 50003 → 配置里的额外 endpoints
  2. 自动重试: 3 次 exp backoff
  3. 短 TTL 签名缓存: 60s 内相同 payload 直接复用 (重试/断线续传友好)
  4. 健康状态追踪: 每个端点记录 last_success / last_fail / consecutive_fails
  5. Optional 本地 Node bridge: 如果存在 tools/sig3_local.js 作为最后退路
     (避免"所有远程挂了就全站停摆")
  6. 明确日志: 哪条路径服务了请求, 让运维能定位
"""

import base64
import hashlib
import json
import logging
import os
import subprocess
import threading
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

# 默认端点链 (按顺序尝试), 可通过环境变量 KS_SIG_ENDPOINTS 覆盖
_DEFAULT_ENDPOINTS = [
    "http://im.zhongxiangbao.com:50002",
    "http://im.zhongxiangbao.com:50003",
]


def _load_endpoints() -> list[str]:
    env = os.environ.get("KS_SIG_ENDPOINTS", "").strip()
    if env:
        return [e.strip().rstrip("/") for e in env.split(",") if e.strip()]
    return list(_DEFAULT_ENDPOINTS)


# ★ 2026-04-24 v6 Day 4: _EndpointHealth 迁移到 core/circuit_breaker.
# 保留同名 class 为向后兼容, 内部代理到 CircuitBreaker.
class _EndpointHealth:
    """endpoint 健康状态 — 薄代理到 core/circuit_breaker.CircuitBreaker."""

    def __init__(self, endpoint: str = ""):
        self.endpoint = endpoint
        # breaker 名字: sig3_{port} / sig3_primary (主端点默认)
        bname = _endpoint_to_breaker_name(endpoint)
        from core.circuit_breaker import get_breaker
        self._breaker = get_breaker(bname)

    def mark_success(self) -> None:
        self._breaker.mark_success()

    def mark_fail(self) -> None:
        self._breaker.mark_failure(reason="sig3_endpoint_fail")

    @property
    def is_open(self) -> bool:
        return self._breaker.is_open()

    @property
    def consecutive_fails(self) -> int:
        return self._breaker._consecutive_fails

    @property
    def last_success(self) -> float:
        return self._breaker._last_success

    @property
    def last_fail(self) -> float:
        return self._breaker._last_failure

    def to_dict(self) -> dict:
        s = self._breaker.snapshot()
        return {
            "last_success": s["last_success"],
            "last_fail": s["last_failure"],
            "consecutive_fails": s["consecutive_fails"],
            "total_success": s["total_successes"],
            "total_fail": s["total_failures"],
            "circuit_open": s["state"] == "open",
        }


def _endpoint_to_breaker_name(endpoint: str) -> str:
    """把 endpoint URL 映射到 breaker 名字.

    "http://im.zhongxiangbao.com:50002"        → "sig3_primary"
    "http://im.zhongxiangbao.com:50003"        → "sig3_fallback"
    其他 (含本地 Node)                          → "sig3_<last_segment>"
    """
    if not endpoint:
        return "sig3_primary"
    # 提端口
    import re
    m = re.search(r":(\d+)$", endpoint.rstrip("/"))
    if m:
        port = m.group(1)
        if port == "50002":
            return "sig3_primary"
        if port == "50003":
            return "sig3_fallback"
        return f"sig3_{port}"
    # 没有端口 (如 local node) → sig3_node
    return "sig3_node"


# 全局单例 (SigService 常被多处实例化, 但状态 / 缓存应共享)
_HEALTH_LOCK = threading.Lock()
_HEALTH: dict[str, _EndpointHealth] = {}
_CACHE_LOCK = threading.Lock()
_CACHE: dict[str, tuple[str, float]] = {}   # payload_hash → (sig3, expires_at)
_CACHE_TTL = 60.0   # 秒


def _payload_hash(payload: dict) -> str:
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()


def _cache_get(key: str) -> Optional[str]:
    with _CACHE_LOCK:
        item = _CACHE.get(key)
        if item and item[1] > time.time():
            return item[0]
        if item:
            _CACHE.pop(key, None)
    return None


def _cache_set(key: str, sig: str) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (sig, time.time() + _CACHE_TTL)


def _get_health(endpoint: str) -> _EndpointHealth:
    with _HEALTH_LOCK:
        h = _HEALTH.get(endpoint)
        if not h:
            h = _EndpointHealth(endpoint=endpoint)
            _HEALTH[endpoint] = h
        return h


class SigService:
    """Multi-endpoint resilient __NS_sig3 signer."""

    def __init__(self, base_url: str | None = None,
                 endpoints: list[str] | None = None):
        """
        base_url : 单个端点 (兼容老调用). 会被加到 endpoints 开头.
        endpoints : 完整的端点链, 优先级按顺序. 默认从 env / _DEFAULT_ENDPOINTS.
        """
        self.endpoints = endpoints[:] if endpoints else _load_endpoints()
        if base_url:
            base_url = base_url.rstrip("/")
            if base_url not in self.endpoints:
                self.endpoints.insert(0, base_url)
        self.base_url = self.endpoints[0] if self.endpoints else _DEFAULT_ENDPOINTS[0]
        self._sess = requests.Session()

    # ------------------------------------------------------------------

    @staticmethod
    def _encode_payload(payload: dict) -> str:
        raw = json.dumps(payload, ensure_ascii=False)
        return base64.b64encode(raw.encode("utf-8")).decode("ascii")

    @staticmethod
    def _encode_params(api_ph: str, extra_params: Optional[dict] = None) -> str:
        payload: dict = {
            "uploadType": 1,
            "kuaishou.web.cp.api_ph": api_ph,
        }
        if extra_params:
            payload.update(extra_params)
        return SigService._encode_payload(payload)

    # ------------------------------------------------------------------
    # Core: signing attempt loop
    # ------------------------------------------------------------------

    def _try_endpoint(self, endpoint: str, encoded: str, timeout: int) -> str:
        health = _get_health(endpoint)
        if health.is_open:
            raise RuntimeError(f"{endpoint} circuit open (fails={health.consecutive_fails})")
        url = f"{endpoint}/xh?kuaishou{encoded}"
        resp = self._sess.get(url, timeout=timeout)
        resp.raise_for_status()
        sig3 = resp.text.strip()
        if not sig3:
            raise RuntimeError(f"{endpoint} returned empty sig3")
        health.mark_success()
        return sig3

    def _try_local_node_bridge(self, payload: dict) -> Optional[str]:
        """Optional 最后退路: 调本地 node 跑 tools/sig3_local.js.
        不存在或失败返回 None, 不抛."""
        script = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "tools", "sig3_local.js",
        )
        if not os.path.isfile(script):
            return None
        try:
            p = subprocess.run(
                ["node", script],
                input=json.dumps(payload, ensure_ascii=False),
                capture_output=True, text=True, timeout=15, encoding="utf-8",
            )
            if p.returncode != 0:
                log.warning("[SigService] local node bridge rc=%s: %s",
                            p.returncode, p.stderr[:200])
                return None
            sig = (p.stdout or "").strip()
            if sig:
                log.info("[SigService] sig3 served by LOCAL Node bridge")
                return sig
        except (subprocess.TimeoutExpired, FileNotFoundError,
                OSError) as e:
            log.warning("[SigService] local node bridge failed: %s", e)
        return None

    def sign_payload(self, payload: dict, *, timeout: int = 10,
                     max_attempts: int = 3) -> str:
        """Sign a payload, with cache + multi-endpoint failover + local fallback.
        """
        cache_key = _payload_hash(payload)
        cached = _cache_get(cache_key)
        if cached:
            log.debug("[SigService] cache hit for payload keys=%s", list(payload.keys()))
            return cached

        encoded = self._encode_payload(payload)
        last_err: Exception | None = None
        attempts = 0

        for endpoint in self.endpoints:
            for attempt in range(1, max_attempts + 1):
                attempts += 1
                try:
                    sig3 = self._try_endpoint(endpoint, encoded, timeout)
                    log.info("[SigService] sig3 OK via %s (attempt %d)",
                             endpoint, attempt)
                    _cache_set(cache_key, sig3)
                    return sig3
                except Exception as e:
                    _get_health(endpoint).mark_fail()
                    last_err = e
                    log.warning(
                        "[SigService] %s attempt %d/%d failed: %s",
                        endpoint, attempt, max_attempts, e,
                    )
                    # 只对 network/5xx 重试, 其他直接下一 endpoint
                    if not isinstance(e, requests.RequestException):
                        break
                    time.sleep(min(2 ** attempt, 8))

        # 所有远程都败 → 试本地 Node bridge
        local_sig = self._try_local_node_bridge(payload)
        if local_sig:
            _cache_set(cache_key, local_sig)
            return local_sig

        raise RuntimeError(
            f"sig_service all endpoints failed ({attempts} attempts). "
            f"Last error: {last_err}"
        )

    # ------------------------------------------------------------------
    # Back-compat helpers
    # ------------------------------------------------------------------

    def get_sig3(
        self,
        api_ph: str,
        extra_params: Optional[dict] = None,
        *,
        timeout: int = 10,
    ) -> str:
        payload: dict = {"uploadType": 1, "kuaishou.web.cp.api_ph": api_ph}
        if extra_params:
            payload.update(extra_params)
        return self.sign_payload(payload, timeout=timeout)

    def get_sig3_v2(
        self,
        api_ph: str,
        extra_params: Optional[dict] = None,
        *,
        timeout: int = 10,
    ) -> str:
        """保留 API 兼容. 现在 v2 等同 get_sig3 (内部会自动 failover)."""
        return self.get_sig3(api_ph, extra_params, timeout=timeout)

    # ------------------------------------------------------------------
    # Health / Observability
    # ------------------------------------------------------------------

    @staticmethod
    def health_report() -> dict:
        """返回所有端点健康状态 — 供 /execution/status 或 dashboard 展示."""
        with _HEALTH_LOCK:
            return {ep: h.to_dict() for ep, h in _HEALTH.items()}

    @staticmethod
    def cache_size() -> int:
        with _CACHE_LOCK:
            # 顺带清过期
            now = time.time()
            expired = [k for k, v in _CACHE.items() if v[1] <= now]
            for k in expired:
                _CACHE.pop(k, None)
            return len(_CACHE)
