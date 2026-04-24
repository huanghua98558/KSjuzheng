# -*- coding: utf-8 -*-
"""MCN 中继协议 wrapper — sig3 容灾 fallback.

背景:
  KS184 发布有两套路径:
    路径 A: 直连 cp.kuaishou.com, 自签 sig3 (当前 publisher.py 走这条)
    路径 B: im.zhongxiangbao.com:50002/xh?kuaishou<BASE64(JSON)>, MCN 代签转发

  路径 B 的价值: sig3 是逆向破解出来的, 快手改算法时路径 A 瞬间全崩.
  路径 B 传 JWT/token 做鉴权, 不依赖破解的 sig3.

协议 (来自 375 条真实 Frida trace, 2026-04-17 抓):
  GET http://im.zhongxiangbao.com:50002/xh?kuaishou<BASE64_JSON>

  payload 两种:
    模式 A (path 代签): {"path": "/rest/cp/works/...", "sig": "<原签名>", ...body}
    模式 B (shortcut):  {"fileName": "...", "fileLength": ...} 等 KS184 定义好的快捷

  5 类 shortcut (按 key 集合识别):
    1. upload_query:   {uploadType, kuaishou.web.cp.api_ph}
    2. search:         {title, cursor, type, kuaishou.web.cp.api_ph}
    3. upload_finish:  {fileName, fileType, fileLength, token, kuaishou.web.cp.api_ph}
    4. submit:         {caption, bannerTask, activityIds, ...41 字段}
    5. generic (path): {path, sig, ...body}

使用:
    from core.mcn_relay import submit_via_relay, upload_finish_via_relay
    result = submit_via_relay(payload_body, apdid=account.apdid)
"""
from __future__ import annotations

import base64
import json
import logging
import time
from typing import Any

import requests

from core.app_config import get as cfg_get

log = logging.getLogger(__name__)

RELAY_URL = "http://im.zhongxiangbao.com:50002/xh"
DEFAULT_TIMEOUT = 30


# ─────────────────────────────────────────────────────────────────
# J-Frida 完整破解 (2026-04-20, Frida hook libcrypto-3.dll HMAC_Update)
# ★ 2026-04-24 v6 Day 6: 迁 core/secrets.py
# ─────────────────────────────────────────────────────────────────

try:
    from core.secrets import get_hmac_secret, get_mcn_response_secret
    _MCN_RESPONSE_SECRET = get_mcn_response_secret()
    _HMAC_SECRET = get_hmac_secret()
except Exception:
    _MCN_RESPONSE_SECRET = b"REPLACE_WITH_MCN_RESP_SECRET"
    _HMAC_SECRET = b"REPLACE_WITH_HMAC_SECRET"


def compute_mcn_signature(body_b64: str, nonce: str) -> str:
    """计算 MCN 请求/响应的 HMAC 签名 (28 字节 hex, 56 chars).

    KS184 canonical (Frida 抓 HMAC_Update 确认):
        msg = f"{body_b64}:{nonce}:REPLACE_WITH_MCN_RESP_SECRET"
        digest = HMAC-SHA256(key=b"REPLACE_WITH_MCN_RESP_SECRET", msg)
        signature = digest.hex()[:56]   # 前 28 字节 hex

    服务器收到请求, 用同样公式算, 返回到 :50002 响应 body.
    客户端可用本函数算预期值, 对比响应 = 认证服务器身份.

    Args:
        body_b64: URL 里 "xh?kuaishou<BASE64>" 那段 BASE64 (512 chars)
        nonce:    32 字符 base64 随机串 (每次请求随机生成)

    Returns:
        hex string (56 chars = 28 bytes).
    """
    import hmac
    import hashlib
    msg = f"{body_b64}:{nonce}:{_MCN_RESPONSE_SECRET.decode()}"
    return hmac.new(
        _MCN_RESPONSE_SECRET,
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:56]


def compute_sig3(uid: int, timestamp: int, nonce_b64: str) -> str:
    """计算快手原生 sig3 签名 (用于 cp.kuaishou.com 签).

    KS184 canonical (Frida 抓 HMAC_Update 确认):
        msg = f"{uid}:{ts}:{nonce_b64}:REPLACE_WITH_HMAC_SECRET"
        sig3 = HMAC-SHA256(key=b"REPLACE_WITH_HMAC_SECRET", msg).hex()[:56]

    Args:
        uid: 账号 numeric_uid (如 2995089200)
        timestamp: Unix 秒 (请求时刻)
        nonce_b64: 随机 base64 (24 chars, 如 '1ACnb3ktZIrCIxabzDs/CQ==')

    Returns:
        sig3 hex (56 chars = 28 bytes).
    """
    import hmac
    import hashlib
    msg = f"{uid}:{timestamp}:{nonce_b64}:{_HMAC_SECRET.decode()}"
    return hmac.new(
        _HMAC_SECRET,
        msg.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()[:56]


def verify_mcn_response(body_b64: str, nonce: str,
                          response_hex: str) -> dict:
    """验证 :50002 响应合法性 (本地算 HMAC 对比服务器返回).

    用途: 增加安全层 — 确认响应真来自 MCN 服务器, 不是中间人.

    Args:
        body_b64: 请求 BASE64 payload
        nonce: 请求时用的 nonce
        response_hex: :50002 返回的 56 chars hex

    Returns:
        {valid: bool, expected: str, received: str, ...}
    """
    expected = compute_mcn_signature(body_b64, nonce)
    received = response_hex.strip().lower()
    valid = expected == received
    return {
        "valid": valid,
        "expected": expected,
        "received": received,
        "mismatch_bytes": None if valid else sum(
            1 for a, b in zip(expected, received) if a != b
        ),
    }


# ─────────────────────────────────────────────────────────────────
# J-6 响应指纹与异常监控 (不解密, 只记指纹)
# ─────────────────────────────────────────────────────────────────

def classify_response_fingerprint(response_bytes: bytes) -> dict:
    """对 :50002 响应做指纹分析, 监控异常 (不解密).

    发现:
        - 响应固定 28 字节
        - 熵 4.6 (xor-like)
        - 末尾 8 字节有 'XY XY YZ YZ' 重复对 pattern (见 KS184 canonical docs)
        - 每个请求响应不同 (签名含时间戳/nonce), 无法直接分类为"success/error"

    实用用途:
        - 记录响应长度 + 熵 + 尾部 pattern → 如果某天突变 → 预警
        - 给 Watchdog / LLMResearcher 提供异常信号
    """
    import hashlib

    if not response_bytes:
        return {"anomaly": True, "reason": "empty_response"}

    length = len(response_bytes)

    # 熵
    freq = {}
    for b in response_bytes:
        freq[b] = freq.get(b, 0) + 1
    import math
    entropy = -sum(
        (c / length) * math.log2(c / length) for c in freq.values()
    ) if length else 0

    # 尾部 pattern 检测 (KS184 真实响应都有 XY XY YZ YZ 的 8 字节尾)
    tail = response_bytes[-8:]
    has_pair_pattern = (
        tail[0] == tail[1] and tail[2] == tail[3]
        if len(tail) >= 4 else False
    )

    # 指纹 (MD5 前 8 字节, 用于统计唯一响应数)
    fp = hashlib.md5(response_bytes).hexdigest()[:16]

    # 异常判定
    anomaly = False
    reason = []
    if length != 28:
        anomaly = True
        reason.append(f"unusual_length={length}")
    if entropy < 3.0 or entropy > 7.0:
        anomaly = True
        reason.append(f"unusual_entropy={entropy:.2f}")
    if length == 28 and not has_pair_pattern:
        anomaly = True
        reason.append("no_tail_pair_pattern")

    return {
        "length": length,
        "entropy": round(entropy, 2),
        "fingerprint": fp,
        "tail_hex": tail.hex(),
        "has_pair_pattern": has_pair_pattern,
        "anomaly": anomaly,
        "reason": ";".join(reason) if reason else None,
    }


# ─────────────────────────────────────────────────────────────────
# 低层: 编码 + 发请求
# ─────────────────────────────────────────────────────────────────

def _encode_payload(payload: dict) -> str:
    """把 payload JSON base64 encode (标准 base64, 不是 URL-safe)."""
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return base64.b64encode(raw.encode("utf-8")).decode("ascii")


def _decode_response_hex(hex_str: str) -> bytes | None:
    """Trace 里的 `r` 字段是 hex — 实际响应 body bytes. 用于理解响应格式."""
    try:
        return bytes.fromhex(hex_str)
    except Exception:
        return None


def _call_relay(payload: dict, timeout: int = DEFAULT_TIMEOUT) -> dict:
    """调用中继, 返回 {ok, status_code, response_text, elapsed_sec, error?}.

    Args:
        payload: 业务 payload (会被 base64 encode 到 URL)
    """
    b64 = _encode_payload(payload)
    url = f"{RELAY_URL}?kuaishou{b64}"

    t0 = time.time()
    try:
        r = requests.get(url, timeout=timeout)
        elapsed = time.time() - t0
        result = {
            "ok": r.status_code == 200,
            "status_code": r.status_code,
            "elapsed_sec": round(elapsed, 2),
            "url_preview": url[:120] + "..." if len(url) > 120 else url,
        }
        # 响应体可能是 JSON, 可能是 binary, 试解
        try:
            result["response_json"] = r.json()
        except Exception:
            result["response_text"] = r.text[:2000]
            result["response_bytes_len"] = len(r.content)

            # ★ J-6: 响应指纹分析
            # KS184 trace 显示 MCN 响应 body 是 **hex string** (56 chars = 28 bytes)
            # 先 hex decode 再做指纹
            raw_bytes = None
            try:
                # 响应是 hex 字符串
                text = r.text.strip()
                if len(text) == 56 and all(c in "0123456789abcdefABCDEF" for c in text):
                    raw_bytes = bytes.fromhex(text)
            except Exception:
                pass
            if raw_bytes is None:
                # fallback: 直接用 r.content
                raw_bytes = r.content

            if raw_bytes:
                result["response_fingerprint"] = classify_response_fingerprint(raw_bytes)
                if result["response_fingerprint"].get("anomaly"):
                    log.warning("[mcn_relay] 响应异常: %s",
                                result["response_fingerprint"]["reason"])
        return result
    except requests.exceptions.Timeout:
        return {"ok": False, "error": "timeout",
                "elapsed_sec": round(time.time() - t0, 2)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300],
                "elapsed_sec": round(time.time() - t0, 2)}


# ─────────────────────────────────────────────────────────────────
# 高层 API: 5 类 shortcut + 1 个 generic
# ─────────────────────────────────────────────────────────────────

def upload_query_via_relay(upload_type: int, apdid: str,
                             timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Shortcut 1: 查上传类型配置 (uploadType 相关).

    对齐 trace shortcut:
        {"uploadType": 1, "kuaishou.web.cp.api_ph": "<apdid>"}
    """
    payload = {
        "uploadType": upload_type,
        "kuaishou.web.cp.api_ph": apdid,
    }
    return _call_relay(payload, timeout=timeout)


def search_via_relay(title: str, cursor: str = "", type_: int = 10,
                      apdid: str = "",
                      timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Shortcut 2: 搜索作品 / 视频.

    对齐 trace:
        {"type":10, "title":"财源滚滚小厨神", "cursor":"",
         "kuaishou.web.cp.api_ph":"<apdid>"}
    """
    payload = {
        "type": type_,
        "title": title,
        "cursor": cursor,
        "kuaishou.web.cp.api_ph": apdid,
    }
    return _call_relay(payload, timeout=timeout)


def upload_finish_via_relay(file_name: str, file_type: str, file_length: int,
                              token: str, apdid: str,
                              timeout: int = 60) -> dict:
    """Shortcut 3: 上传完成通知 (通过中继, 不用自签 sig3).

    对齐 trace:
        {"token": "Cg51cGx...",
         "fileName": "video_9f25155d_20260417_051646_processed.mp4",
         "fileType": "video/mp4",
         "fileLength": 571531344,
         "kuaishou.web.cp.api_ph": "01c124..."}
    """
    payload = {
        "token": token,
        "fileName": file_name,
        "fileType": file_type,
        "fileLength": file_length,
        "kuaishou.web.cp.api_ph": apdid,
    }
    return _call_relay(payload, timeout=timeout)


def submit_via_relay(submit_body: dict, apdid: str,
                      timeout: int = 60) -> dict:
    """Shortcut 4: 发布视频 (通过中继).

    对齐 trace submit shortcut (41 字段): caption / bannerTask / activityIds /
      fileId / coverKey / photoType / photoIdStr / ... 等.

    自动注入 apdid 字段; 其他字段从 submit_body 透传.
    """
    payload = dict(submit_body)  # copy
    payload.setdefault("kuaishou.web.cp.api_ph", apdid)
    return _call_relay(payload, timeout=timeout)


def generic_relay(path: str, sig: str, body: dict | None = None,
                   apdid: str = "",
                   timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Mode 5: 通用 path 代签.

    对齐 trace:
        {"path": "/rest/nebula/feed/selection", "sig": "c4cc1826..."}
        (299 次在 trace)

    传任意 kuaishou 原生 path + 你已经算好的 sig, 服务器代转 + 如有需要补签.
    """
    payload = {"path": path, "sig": sig}
    if body:
        payload.update(body)
    if apdid:
        payload["kuaishou.web.cp.api_ph"] = apdid
    return _call_relay(payload, timeout=timeout)


# ─────────────────────────────────────────────────────────────────
# 健康检查 / 可用性
# ─────────────────────────────────────────────────────────────────

def is_relay_online(timeout: int = 5) -> bool:
    """快速 ping 看 :50002 是否可达 (不调真业务, 发个空的试一下)."""
    try:
        r = requests.get(RELAY_URL, timeout=timeout)
        # 期望 200 或 4xx (有错误但服务器在)
        return r.status_code < 500
    except Exception:
        return False


# ─────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import argparse
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    logging.basicConfig(level=logging.INFO,
                        format="[%(asctime)s] %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--ping", action="store_true",
                    help="快速 ping :50002")
    ap.add_argument("--search", type=str,
                    help="搜索测试, 如 --search 财源滚滚")
    ap.add_argument("--apdid", default="01c124063def656355fea4704defa945bfff",
                    help="api_ph (apdid), 默认用 trace 样本里的")
    args = ap.parse_args()

    if args.ping:
        print(f"ping :50002 → {'online' if is_relay_online() else 'offline'}")
    elif args.search:
        r = search_via_relay(args.search, apdid=args.apdid)
        print(json.dumps(r, ensure_ascii=False, indent=2, default=str))
    else:
        ap.print_help()
