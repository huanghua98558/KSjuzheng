# -*- coding: utf-8 -*-
"""
feed/selection 解析器 — xinhui sharePhotoId → CDN URL.

CLAUDE.md §26.9 (2026-04-22): KS184 下载完整链路 4 步:
  1. 短链 HTML → 限流
  2. xinhui/getSharePhotoId → sharePhotoId + feedInject (已破 §25)
  3. ★ feed/selection → main_mv_urls (CDN URL) ← 本模块
  4. GET CDN → mp4

实测 (trace 12 次 feed/selection):
  - 20 个静态字段 12 次完全相同 (clientRealReportData / global_id / did / ...)
  - 1 个动态字段 (feedInjectionParams = xinhui 返的 feedInject)
  - __NS_sig3 每次不同, 通过 MCN :50002 代签拿到

用法:
    from core.feed_selection_resolver import resolve_share_to_cdn
    cdn_url = resolve_share_to_cdn(share_id="18918548604598",
                                     encrypt_pid="3x46xyewsufx7tk")
    # → "http://k0u76yfdya0y6zw240exc2x1800xe3xx6z.djvod.ndcimgs.com/.../mp4"
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
from typing import Optional

import requests

log = logging.getLogger(__name__)

# az1-api-idc.ksapisrv.com/rest/nebula/feed/selection — iOS 端点
FEED_SELECTION_URL = "https://az1-api-idc.ksapisrv.com/rest/nebula/feed/selection"
MCN_RELAY_URL = "http://im.zhongxiangbao.com:50002/xh"

# 从 KS184 trace 2026-04-21 20:24 抓取 — 12 次调用 20 字段一致
# 可以一直复用, 直到 KS184 升级 iOS 设备指纹
FEED_SEL_STATIC_BODY = {
    # iOS 设备指纹 (一次性采好)
    "clientRealReportData": (
        "IPfulOYpLtsrBhhdVQaCo1NroH+8kR+OXzD8IShUopHBgjYY1QKv7KaznFGkTBi+"
        "kzCn/C6ZiF8R6bfk1aUk7JmeYj5FiB5cteSsQIYfj5S9DARiMsXtDV3yYrCibqw4+"
        "xXmzF6SABSijO7rFG5GKfx07QHU8EQaAytKoUqKrHh4uYLzN6BDXn+Rgzem6ohwU"
        "BTLj87ERz8Md4ak1Bzb46uTGe2OzJvY0TTw36mUqNQE2ObijWvy2NI8u0R/8/uhX"
        "3QzKfPLz+m2vqmhIsu8plJ9Ugu88DnTFAcIiuFYB57IWwdHK/pu4sAnlNnmWqGn"
    ),
    "global_id": "DFP400C780F1B6DFA55A18A94D72B618A167653DDEA9C843EBEB8F86FED1E261",
    "realShowPhotoIds": "5198842987561059053,5212635258151015268",
    "recoReportContext": json.dumps(
        {
            "enableAdClientRerank": True,
            "refresh_id": "KSFeedTypeHomeFeaturedTab_1752846399.47",
            "isGpsAuthorized": False,
            "videoPlayedDuration": 0,
            "isFeedLocationAuthorized": 1,
            "apiCost": 600.80231944223272,
            "adClientInfo": {"gestureType": 0, "updateMark": "1752846399"},
        },
        ensure_ascii=False, separators=(',', ':'),
    ),

    # 账号/设备 常量
    "client_key": "56c3713c",
    "country_code": "cn",
    "cs": "false",
    "edgeRecoBit": "2",
    "edgeRerankConfigVersion": "9BDD1DD88657FE08C35F0EE249B7A1E8",
    "id": "10",
    "isFeedLocationAuthorized": "1",
    "isGpsAuthorized": "0",
    "isOpenAutoPlay": "false",
    "language": "zh-Hans-CN;q=1",
    "newUserRefreshTimes": "10",
    "newerAction": '{"like":[],"follow":[],"click":[]}',
    "page": "1",
    "power_mode": "0",
    "count": "6",
}

# URL query (28 字段全静态)
FEED_SEL_URL_QUERY = {
    "c": "a",
    "did": "9736585F-31AD-C51B-585D-CF9D6F579173",
    "kpn": "KUAISHOU",
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
    # 比 xinhui 多: kpf / keyconfig_state / cdid_tag / grant_browse_type / sw / deviceBit / is_background
    "kpf": "IPHONE",
    "keyconfig_state": "2",
    "cdid_tag": "2",
    "grant_browse_type": "AUTHORIZED",
    "sw": "1170",
    "deviceBit": "0",
    "is_background": "0",
}


def _sig3_via_relay(payload_json: str, timeout: int = 8) -> Optional[str]:
    """调 MCN :50002/xh 代签拿 sig3. payload 先 base64 encode."""
    b64 = base64.b64encode(payload_json.encode("utf-8")).decode("ascii")
    url = f"{MCN_RELAY_URL}?kuaishou{b64}"
    try:
        r = requests.get(url, timeout=timeout)
        if r.status_code != 200: return None
        text = r.text.strip()
        # sig3 = 56 字符 hex
        if len(text) == 56 and all(c in "0123456789abcdefABCDEF" for c in text):
            return text.lower()
        return None
    except Exception as e:
        log.warning("[feed_selection] :50002 relay failed: %r", e)
        return None


def compute_feed_selection_sig(body_str: str, salt: str = "23caab00356c") -> str:
    """复用 xinhui 同算法 (假设 A). 待验证."""
    return hashlib.md5((body_str + salt).encode("utf-8")).hexdigest()


def build_feed_selection_body(feed_inject: str) -> dict:
    """构造完整 21 字段 body. feed_inject 来自 xinhui 响应."""
    body = dict(FEED_SEL_STATIC_BODY)
    body["feedInjectionParams"] = feed_inject
    return body


def resolve_share_to_cdn(share_id: str,
                          encrypt_pid: Optional[str] = None,
                          timeout: int = 15) -> Optional[dict]:
    """完整链路: shareId → xinhui → feedInject → feed/selection → CDN URL.

    Returns:
        {"cdn_urls": ["http://djvod...", ...], "photo_id": "...", "_raw": {...}}
        or None.
    """
    # Step 1: xinhui 拿 feedInject
    try:
        from core.xinhui_resolver import resolve_share as _xinhui
    except ImportError:
        log.error("[feed_selection] xinhui_resolver not available")
        return None

    xh_info = _xinhui(share_id, encrypt_pid or "", timeout=timeout)
    if not xh_info:
        log.warning("[feed_selection] xinhui resolve failed for shareId=%s", share_id)
        return None

    feed_inject = xh_info.get("feedInject")
    share_photo_id = xh_info.get("sharePhotoId")
    enc_spid = xh_info.get("encryptSharePhotoId")
    if not feed_inject:
        log.warning("[feed_selection] xinhui OK but no feedInject")
        return None

    log.info("[feed_selection] xinhui OK: sharePhotoId=%s", share_photo_id)

    # Step 2: 构造 feed/selection body (21 字段)
    body = build_feed_selection_body(feed_inject)

    # Step 3: 通过 :50002 代签拿 sig3
    # 策略 A: 直接把 body (form encoded, 按字母序拼接) 发给 :50002
    from urllib.parse import quote_plus
    items = sorted(body.items())
    body_form = "&".join(f"{k}={quote_plus(v, safe=';:,+/')}" for k, v in items)

    # 策略尝试 1: path-sign mode (和 §23 trace 对齐)
    client_sig = compute_feed_selection_sig(
        "".join(f"{k}={v}" for k, v in items)
    )
    relay_payload = json.dumps(
        {"path": "/rest/nebula/feed/selection", "sig": client_sig},
        ensure_ascii=False, separators=(',', ':'),
    )
    sig3 = _sig3_via_relay(relay_payload, timeout=timeout)
    if not sig3:
        log.warning("[feed_selection] :50002 path-sign mode returned no sig3")
        # 策略尝试 2: 直接发 full body
        sig3 = _sig3_via_relay(body_form, timeout=timeout)
    if not sig3:
        log.error("[feed_selection] :50002 无论如何都返空 sig3")
        return None

    log.info("[feed_selection] sig3=%s (body 128 hash=%s)",
              sig3[:16], client_sig[:16])

    # Step 4: 构造 URL + POST feed/selection
    q_items = sorted(FEED_SEL_URL_QUERY.items())
    query_str = "&".join(f"{k}={quote_plus(v, safe=';:,+/')}" for k, v in q_items)
    url = f"{FEED_SELECTION_URL}?{query_str}&__NS_sig3={sig3}"

    headers = {
        "User-Agent": ("Kwai-iphone 13.1 iPhone iOS18.4.1 "
                       "Scale/3.00 NetType/CMCC"),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "*/*",
        "Accept-Language": "zh-Hans-CN;q=1",
    }

    try:
        r = requests.post(url, data=body_form, headers=headers, timeout=timeout)
    except Exception as e:
        log.warning("[feed_selection] POST failed: %r", e)
        return None

    if r.status_code != 200:
        log.warning("[feed_selection] HTTP %d: %s", r.status_code, r.text[:200])
        return None

    try:
        data = r.json()
    except Exception:
        log.warning("[feed_selection] non-json: %s", r.text[:200])
        return None

    if data.get("result") != 1:
        log.warning("[feed_selection] result=%s: %s", data.get("result"),
                     str(data)[:300])
        return None

    # 拿 feeds[0].main_mv_urls
    feeds = data.get("feeds", [])
    if not feeds:
        log.warning("[feed_selection] no feeds in response")
        return None
    main_urls = feeds[0].get("main_mv_urls", [])
    cdn_urls = [u.get("url") for u in main_urls if u.get("url")]
    if not cdn_urls:
        log.warning("[feed_selection] no CDN URLs in feeds[0]")
        return None

    log.info("[feed_selection] SUCCESS: %d CDN URLs for shareId=%s",
              len(cdn_urls), share_id)
    return {
        "cdn_urls": cdn_urls,
        "photo_id": share_photo_id,
        "encrypt_share_photo_id": enc_spid,
        "feed": feeds[0],
    }


if __name__ == "__main__":
    import argparse, sys
    try: sys.stdout.reconfigure(encoding="utf-8")
    except Exception: pass
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    ap = argparse.ArgumentParser()
    ap.add_argument("--share-id", type=str, required=True)
    ap.add_argument("--encrypt-pid", type=str, default="")
    args = ap.parse_args()

    r = resolve_share_to_cdn(args.share_id, args.encrypt_pid)
    if r:
        print(json.dumps({
            "photo_id": r["photo_id"],
            "cdn_urls": r["cdn_urls"],
        }, ensure_ascii=False, indent=2))
    else:
        print("FAILED")
        sys.exit(1)
