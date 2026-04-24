# -*- coding: utf-8 -*-
"""
xinhui/share/getSharePhotoId 短链解析 — 纯自主实现.

CLAUDE.md §25 (2026-04-22): Frida 注入 hashlib.md5 hook 破解完成.
  算法: MD5(sorted_kv_joined_no_sep + "23caab00356c")
  Salt: 硬编码 "23caab00356c" 接在 sorted join 末尾.
  字段: URL query + body + iOS 客户端硬编码 (appver/client_key/...)

对齐 KS184 7-layer Frida (2026-04-21 §23.2 #2): www.kuaishou.com/f/ 100% 限流,
    xinhui/share/getSharePhotoId 100% 成功 — 这是真正能用的解析路径.

用法:
    from core.xinhui_resolver import resolve_share
    info = resolve_share("18902266413235")  # shareId from short link
    # → {sharePhotoId: "...", encryptSharePhotoId: "...", feedInject: "..."}

注意: Kuaishou 短链 `www.kuaishou.com/f/XXXXXX` 需先从 HTML 拿到 shareId + encryptPid
    (这一步不用 sig, 只是 HTML 解析). Wait — 实测 HTML 也限流返 result=2.
    只能从 mcn 或其他渠道拿 shareId/encryptPid, 或者用户直接提供.

TODO: 研究 shareId/encryptPid 的**初始获取**方式 — 目前 KS184 从**全局匹配记录**
    (drama_collection 之类) 里拿到 share_url 对应的 shareId (跳过短链解析).
"""
from __future__ import annotations

import hashlib
import logging
from typing import Any, Optional
from urllib.parse import quote_plus

import requests

log = logging.getLogger(__name__)

# 已破解的硬编码 salt (CLAUDE.md §25)
XINHUI_SIG_SALT = "23caab00356c"

XINHUI_API_URL = "https://az1-api.ksapisrv.com/rest/n/xinhui/share/getSharePhotoId"

# iOS 13.1.10.9110 / iPhone17,2 客户端指纹 (抓自 KS184, 可复用)
# 这些字段**参与 sig 计算**, 和 KS184 保持一致
IOS_FINGERPRINT: dict[str, str] = {
    # URL query 部分
    "c": "a",
    "did": "9736585F-31AD-C51B-585D-CF9D6F579173",
    "kpn": "KUAISHOU",
    "grant_browse_type": "AUTHORIZED",
    "cdid_tag": "2",
    "keyconfig_state": "2",
    "deviceBit": "0",
    "sw": "1170",
    "is_background": "0",
    "kpf": "IPHONE",
    "did_gt": "1752841549200",
    "sys": "ios18.4.1",
    "sh": "2532",
    "kcv": "1599",
    "browseType": "4",
    "earphoneMode": "1",
    "net": "中国移动_5",
    "darkMode": "true",
    "ver": "13.1",
    "mod": "iPhone17,2",
    "cold_launch_time_ms": "1752841549230",
    "isp": "CMCC",
    "did_tag": "0",
    "oDid": "A695B5B5-CB08-4265-9103-D3C2A309B440",
    "icaver": "1",
    "rdid": "A695B5B5-CB08-4265-9103-D3C2A309B440",
    "vague": "1",
    "egid": "DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D",

    # Body 部分固定字段
    "appver": "5.3.0",
    "client_key": "56c3713c",
    "country_code": "cn",
    "cs": "false",
    "global_id": "DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D",
    "language": "zh-Hans-CN;q=1",
    "power_mode": "0",
    "thermal": "10000",
    "token": "",
}


def compute_xinhui_sig(share_id: str, encrypt_pid: str,
                        extra: Optional[dict] = None) -> str:
    """Compute MD5 sig for xinhui/share/getSharePhotoId.

    算法 (CLAUDE.md §25, 2026-04-22 Frida 破解):
        1. 收集所有参数 (固定指纹 + shareId + encryptPid)
        2. 按 key 字母序排序
        3. 拼接 "key1=value1key2=value2..." (无分隔符)
        4. 末尾 append salt "23caab00356c"
        5. MD5 + hex

    Returns:
        32 字符 MD5 hex.
    """
    params: dict[str, Any] = dict(IOS_FINGERPRINT)
    params["shareId"] = share_id
    params["encryptPid"] = encrypt_pid
    if extra:
        params.update({str(k): str(v) for k, v in extra.items()})

    items = sorted(params.items())
    joined = "".join(f"{k}={v}" for k, v in items)
    to_hash = joined + XINHUI_SIG_SALT
    return hashlib.md5(to_hash.encode("utf-8")).hexdigest()


def resolve_share(share_id: str, encrypt_pid: Optional[str] = None,
                   timeout: int = 10) -> Optional[dict]:
    """调 xinhui/share/getSharePhotoId 解析 shareId → photoId + CDN 信息.

    Args:
        share_id: 18 位数字 share ID (来自短链).
        encrypt_pid: 加密 photoId (可选; 若无, 传空字符串, 服务端也可返回).

    Returns:
        {
            "sharePhotoId": "...",           # 真 photoId (字符串)
            "encryptSharePhotoId": "3x...",  # 加密 photoId (可用于 feed/selection)
            "feedInject": "...",             # 推荐 feed 注入 base64+gzip
            "host_name": "...",
        }
        or None on failure.
    """
    enc_pid = encrypt_pid or ""

    sig = compute_xinhui_sig(share_id, enc_pid)

    # Build form body (字母序 + URL encoded value)
    body_params = {
        "client_key": IOS_FINGERPRINT["client_key"],
        "country_code": IOS_FINGERPRINT["country_code"],
        "cs": IOS_FINGERPRINT["cs"],
        "encryptPid": enc_pid,
        "global_id": IOS_FINGERPRINT["global_id"],
        "language": IOS_FINGERPRINT["language"],
        "power_mode": IOS_FINGERPRINT["power_mode"],
        "shareId": share_id,
        "thermal": IOS_FINGERPRINT["thermal"],
        "token": IOS_FINGERPRINT["token"],
        "sig": sig,
    }
    body_str = "&".join(f"{k}={quote_plus(v, safe=';')}" for k, v in body_params.items())

    # Build URL query (字母序 URL encoded)
    query_keys = [
        "c", "did", "kpn", "grant_browse_type", "cdid_tag", "keyconfig_state",
        "deviceBit", "sw", "is_background", "kpf", "did_gt", "sys", "sh", "kcv",
        "browseType", "earphoneMode", "net", "darkMode", "ver", "mod",
        "cold_launch_time_ms", "isp", "did_tag", "oDid", "icaver", "rdid",
        "vague", "egid",
    ]
    query_str = "&".join(
        f"{k}={quote_plus(IOS_FINGERPRINT[k], safe=';')}" for k in query_keys
    )

    url = f"{XINHUI_API_URL}?{query_str}"

    # ★ 2026-04-22 v6 hook 实测: KS184 只用 6 字符 "kwai-ios" UA, 无 Cookie
    # 之前用长 UA 被服务端拒 result=50 — 真相就是 UA 不对
    headers = {
        "User-Agent": "kwai-ios",
        "Accept": "application/json",
        "Accept-Language": "zh-Hans-CN;q=1",
        "Content-Type": "application/x-www-form-urlencoded",
        "Host": "az1-api.ksapisrv.com",
    }

    try:
        resp = requests.post(url, data=body_str, headers=headers, timeout=timeout)
    except Exception as e:
        log.warning("[xinhui_resolver] request failed: %r", e)
        return None

    if resp.status_code != 200:
        log.warning("[xinhui_resolver] HTTP %d: %s", resp.status_code, resp.text[:200])
        return None

    try:
        data = resp.json()
    except Exception:
        log.warning("[xinhui_resolver] non-json response: %s", resp.text[:200])
        return None

    if data.get("result") != 1:
        log.warning("[xinhui_resolver] result=%s: %s", data.get("result"),
                     str(data)[:300])
        return None

    return {
        "sharePhotoId": data.get("sharePhotoId"),
        "encryptSharePhotoId": data.get("encryptSharePhotoId"),
        "feedInject": data.get("feedInject"),
        "host_name": data.get("host-name"),
        "_raw": data,
    }


def verify_sig_algorithm() -> list[tuple[str, str, bool]]:
    """Self-test: verify algorithm against captured (input, digest) pairs from Frida hook.

    Returns list of (sample_name, expected, matches).
    """
    # 2 full-captured samples (from hits.jsonl 2026-04-22 00:22)
    samples = [
        # (input_preview_full_738, expected_digest)
        (
            "appver=5.3.0browseType=4c=acdid_tag=2client_key=56c3713c"
            "cold_launch_time_ms=1752841549230country_code=cncs=false"
            "darkMode=truedeviceBit=0"
            "did=9736585F-31AD-C51B-585D-CF9D6F579173"
            "did_gt=1752841549200did_tag=0earphoneMode=1"
            "egid=DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D"
            "encryptPid=3xud9k7yb8j6a39"
            "global_id=DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D"
            "grant_browse_type=AUTHORIZEDicaver=1is_background=0"
            "isp=CMCCkcv=1599keyconfig_state=2kpf=IPHONEkpn=KUAISHOU"
            "language=zh-Hans-CN;q=1mod=iPhone17,2net=中国移动_5"
            "oDid=A695B5B5-CB08-4265-9103-D3C2A309B440"
            "power_mode=0"
            "rdid=A695B5B5-CB08-4265-9103-D3C2A309B440"
            "sh=2532shareId=18902266413235sw=1170sys=ios18.4.1"
            "thermal=10000token=vague=1ver=13.1",
            "0e547ef1b11f65f4a7da5a92cf3329cf",
            "18902266413235", "3xud9k7yb8j6a39",
        ),
        (
            "appver=5.3.0browseType=4c=acdid_tag=2client_key=56c3713c"
            "cold_launch_time_ms=1752841549230country_code=cncs=false"
            "darkMode=truedeviceBit=0"
            "did=9736585F-31AD-C51B-585D-CF9D6F579173"
            "did_gt=1752841549200did_tag=0earphoneMode=1"
            "egid=DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D"
            "encryptPid=3x5wdua9teq76xu"
            "global_id=DFPD97A119BC0E30185925C3C43C613F6C69D7B0D58360E250CA0505262B792D"
            "grant_browse_type=AUTHORIZEDicaver=1is_background=0"
            "isp=CMCCkcv=1599keyconfig_state=2kpf=IPHONEkpn=KUAISHOU"
            "language=zh-Hans-CN;q=1mod=iPhone17,2net=中国移动_5"
            "oDid=A695B5B5-CB08-4265-9103-D3C2A309B440"
            "power_mode=0"
            "rdid=A695B5B5-CB08-4265-9103-D3C2A309B440"
            "sh=2532shareId=18918098874214sw=1170sys=ios18.4.1"
            "thermal=10000token=vague=1ver=13.1",
            "55b036fc4a1bc0c19e30ef3afae1fcfb",
            "18918098874214", "3x5wdua9teq76xu",
        ),
    ]
    results = []
    for raw_input, expected, sid, epid in samples:
        # 1. 直接用 captured raw input + salt
        direct = hashlib.md5((raw_input + XINHUI_SIG_SALT).encode("utf-8")).hexdigest()
        # 2. 通过 compute_xinhui_sig 计算
        computed = compute_xinhui_sig(sid, epid)
        name = f"shareId={sid} encPid={epid}"
        # 两种都要 match
        results.append((name, expected, direct == expected and computed == expected))
    return results


if __name__ == "__main__":
    import sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass

    logging.basicConfig(level=logging.INFO)

    print("=== xinhui sig self-test ===")
    for name, expected, ok in verify_sig_algorithm():
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  → {expected}")

    # CLI: resolve
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--share-id", type=str, default=None)
    ap.add_argument("--encrypt-pid", type=str, default="")
    ap.add_argument("--test-only", action="store_true")
    args = ap.parse_args()
    if args.test_only:
        sys.exit(0)
    if args.share_id:
        r = resolve_share(args.share_id, args.encrypt_pid)
        import json as _j
        print(_j.dumps(r, ensure_ascii=False, indent=2) if r else "FAILED")
