# -*- coding: utf-8 -*-
"""wechat_channels_cookie_keeper — 视频号 Cookie 7-30 天保活器.

基于逆向 小V猫 2.0.0 (Electron + Playwright Chromium 架构) 得出的核心发现:

1. 视频号助手网页版 cookie 默认 24h 过期 (微信开放社区官方确认)
2. 但通过**定期调用 store.weixin.qq.com 的 refresh_session 端点**, 可以无限续期
3. 端点 1 (简单, 推荐): POST https://store.weixin.qq.com/shop/commkf/refresh_session?scene=8
4. 端点 2 (复杂, 小程序伪装): POST https://store.weixin.qq.com/faas/mmbizwxalogin/biz/bizLoginV2
   (需要 Biz_magic header 签名, 目前在 bytenode 编译里未解出算法)

策略:
  - Playwright 持久化 userDataDir (每账号独立), 扫码一次
  - 定时 (每 6h / 12h) 后台调 refresh_session
  - 浏览器自动保存新 Set-Cookie 到 userDataDir/<profile>/Network/Cookies

Tested endpoints (2026-04-22):
  - refresh_session?scene=8 → 200 (无 cookie 时 ret=30000 "鉴权失败", 端点 live)
  - bizLoginV2 → 403 (无 Biz_magic, 端点存在)
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# 常量 (逆向自小V猫 server.jsc)
# ────────────────────────────────────────────────────────────────

CHANNELS_HOME = "https://channels.weixin.qq.com/"
CHANNELS_PLATFORM = "https://channels.weixin.qq.com/platform"
CHANNELS_LOGIN = "https://channels.weixin.qq.com/login.html"
STORE_TALENT = "https://store.weixin.qq.com/talent/"
STORE_TALENT_KF = "https://store.weixin.qq.com/talent/kf"

# 核心续期端点
REFRESH_SESSION_URL = "https://store.weixin.qq.com/shop/commkf/refresh_session?scene=8"

# 小V猫 UA (Electron 22 + Chrome 108)
XIAOV_UA_WIN = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "WeixinStoreAssistant/3.1.1 Chrome/108.0.5359.215 "
    "Electron/22.3.27 Safari/537.36 ShopWebview"
)

XIAOV_UA_COMMON = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/136.0.0.0 Safari/537.36"
)

REFRESH_SESSION_HEADERS = {
    "User-Agent": XIAOV_UA_WIN,
    "pcapp_version": "3.1.1",
    "Referer": STORE_TALENT_KF,
    "sec-ch-ua": '"Not A(Brand";v="8", "Chromium";v="108"',
    "Content-Type": "application/json",
}

# 推荐 refresh 间隔: 6-12h (cookie 默认 24h, 留 50% 余量)
DEFAULT_REFRESH_INTERVAL_SEC = 6 * 3600


# ────────────────────────────────────────────────────────────────
# 1. Playwright 扫码登录 + 持久化 userDataDir
# ────────────────────────────────────────────────────────────────

async def login_and_persist(
    user_data_dir: str,
    uid_label: str = "default",
    headless: bool = False,
    timeout: int = 600,
    entry: str = "talent",  # "talent" (带货助手, 推荐) or "channels" (视频号助手)
) -> dict:
    """启动 Playwright Chromium, 引导用户扫码登录, 持久化 session.

    ★ 2026-04-22 修订: 核心入口是 store.weixin.qq.com/talent/ (带货助手),
    不是 channels.weixin.qq.com/. 因为:
      - 小V猫用的就是 talent 系统 (CPS 带货)
      - refresh_session?scene=8 是 store.weixin.qq.com 下的端点
      - 带货助手已升级, 需用手机微信扫码 (不是 PC 同设备识别)

    参数:
        user_data_dir: 用户数据目录
        uid_label: 账号标识
        headless: 扫码时必须 False
        timeout: 等待扫码完成超时 (默认 600s / 10分钟)
        entry: 登录入口 — 'talent' (默认, store.weixin) 或 'channels' (channels.weixin)
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        raise RuntimeError("需要 pip install playwright && playwright install chromium")

    user_data_dir = os.path.abspath(user_data_dir)
    os.makedirs(user_data_dir, exist_ok=True)
    log.info(f"[wechat/{uid_label}] launching Chromium (entry={entry})")
    log.info(f"[wechat/{uid_label}] profile={user_data_dir}")

    # 根据 entry 选择入口 URL 和成功判定 URL
    if entry == "talent":
        entry_url = STORE_TALENT  # https://store.weixin.qq.com/talent/
        # 成功判定: URL 跳到 talent 二级页面 (通常是 /talent/home 或 /talent/kf 或 /shop/...)
        success_pattern = "/talent"
    else:
        entry_url = CHANNELS_HOME
        success_pattern = "/platform"

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=headless,
            user_agent=XIAOV_UA_COMMON,
            viewport={"width": 1280, "height": 860},
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else await context.new_page()

        # 访问入口
        try:
            await page.goto(entry_url, wait_until="domcontentloaded", timeout=30000)
        except Exception as e:
            log.warning(f"[wechat/{uid_label}] initial goto warning: {e}")

        log.info(f"[wechat/{uid_label}] 请用手机微信扫屏幕上的二维码登录...")
        log.info(f"[wechat/{uid_label}] 超时 {timeout}s; 登录成功或关闭浏览器都会结束")

        # 轮询检查: 登录是否成功 (检查 cookie + URL)
        start = time.time()
        success = False
        last_log = 0
        while time.time() - start < timeout:
            try:
                # 检查浏览器是否还活着
                if page.is_closed():
                    log.info(f"[wechat/{uid_label}] 浏览器被关闭, 退出")
                    break

                current_url = page.url
                # 关键登录 cookie 判断
                cookies = await context.cookies()
                has_wx_session = any(
                    c["name"] in ("sessionid", "wxuin", "biz_uin", "finder_uin",
                                    "talent_rand", "talent_uin", "uuid")
                    and c.get("value") and len(c["value"]) > 4
                    for c in cookies
                )
                # URL 含登录成功标志
                on_logged_page = (success_pattern in current_url and
                                  "login" not in current_url.lower() and
                                  "qrcode" not in current_url.lower())

                elapsed = int(time.time() - start)
                if elapsed - last_log >= 15:
                    log.info(f"[wechat/{uid_label}] 等待中 t={elapsed}s url={current_url[:60]!r} "
                             f"cookies={len(cookies)} has_wx={has_wx_session}")
                    last_log = elapsed

                if has_wx_session and on_logged_page:
                    log.info(f"[wechat/{uid_label}] ✅ 检测到登录成功 (t={elapsed}s)")
                    success = True
                    break

                await asyncio.sleep(2)
            except Exception as e:
                log.warning(f"[wechat/{uid_label}] polling warning: {e}")
                await asyncio.sleep(2)

        if not success:
            try:
                if not page.is_closed():
                    # 最后再检查一次, 不关闭浏览器 (留给用户)
                    cookies = await context.cookies()
                    has_wx_session = any(
                        c["name"] in ("sessionid", "wxuin", "biz_uin", "talent_rand")
                        and c.get("value") for c in cookies
                    )
                    if has_wx_session:
                        log.info(f"[wechat/{uid_label}] 超时但 cookie 已存在, 当作登录成功")
                        success = True
            except Exception:
                pass

        # 登录成功后: 额外访问 talent/kf 建立 talent_rand
        if success:
            try:
                await page.goto(STORE_TALENT_KF,
                                 wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(3000)
                # 再访问 channels.weixin 让两套 cookie 都建立
                await page.goto(CHANNELS_HOME,
                                 wait_until="domcontentloaded", timeout=15000)
                await page.wait_for_timeout(2000)
            except Exception as e:
                log.warning(f"[wechat/{uid_label}] post-login nav warning: {e}")

        # 统计
        try:
            cookies = await context.cookies()
        except Exception:
            cookies = []

        cookie_sample = [{"name": c.get("name"),
                          "domain": c.get("domain"),
                          "expires": c.get("expires"),
                          "len": len(c.get("value", ""))}
                          for c in cookies[:20]]

        # 脱敏关键 session info
        key_cookies = {}
        for c in cookies:
            name = c.get("name", "")
            if name in ("sessionid", "wxuin", "biz_uin", "finder_uin", "talent_rand",
                         "talent_uin", "biz_expire", "uuid", "biz_ticket"):
                v = c.get("value", "")
                key_cookies[name] = v[:10] + "..." if len(v) > 10 else v

        try:
            await context.close()
        except Exception:
            pass

        return {
            "ok": success,
            "uid_label": uid_label,
            "entry_used": entry,
            "profile_path": user_data_dir,
            "cookies_total": len(cookies),
            "cookies_sample": cookie_sample,
            "key_cookies": key_cookies,
            "logged_at": time.time(),
        }


# ────────────────────────────────────────────────────────────────
# 2. 定时续期 — 核心 !
# ────────────────────────────────────────────────────────────────

async def refresh_session_once(user_data_dir: str, uid_label: str = "?") -> dict:
    """调一次 refresh_session 续期. 必须在**已登录的 userDataDir** 上执行.

    ★ 2026-04-22 修正: talent_* cookies 是 session cookie (expires=-1),
    浏览器关闭就丢. 所以用 cookies.json 文件持久化, 每次 refresh 前注入.

    关键流程:
      1. 启动 context (persistent profile)
      2. 从 cookies.json 注入之前保存的 cookies
      3. 访问 talent/home + talent/kf 让 cookie 激活
      4. POST refresh_session
      5. 导出新 cookies 到 cookies.json (覆盖旧的)
    """
    from playwright.async_api import async_playwright

    user_data_dir = os.path.abspath(user_data_dir)
    if not os.path.isdir(user_data_dir):
        return {"ok": False, "error": f"profile not found: {user_data_dir}"}

    cookies_file = os.path.join(user_data_dir, "_vcat_cookies.json")
    if not os.path.exists(cookies_file):
        return {"ok": False, "error": f"cookies.json 不存在, 需要先 login: {cookies_file}"}

    try:
        with open(cookies_file, "r", encoding="utf-8") as f:
            saved_cookies = json.load(f)
        log.info(f"[wechat/{uid_label}] 加载 cookies {len(saved_cookies)} 条 from {cookies_file}")
    except Exception as e:
        return {"ok": False, "error": f"cookies.json 读取失败: {e}"}

    async with async_playwright() as p:
        context = await p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=True,
            user_agent=XIAOV_UA_WIN,
            args=["--no-sandbox", "--disable-blink-features=AutomationControlled"],
        )

        # Step 0: 注入之前的 cookies (恢复 session)
        try:
            await context.add_cookies(saved_cookies)
            log.info(f"[wechat/{uid_label}] 注入 cookies 成功")
        except Exception as e:
            log.warning(f"[wechat/{uid_label}] add_cookies warning: {e}")

        page = await context.new_page()

        # Step 1: 访问 talent/home 让 cookie 激活
        try:
            await page.goto("https://store.weixin.qq.com/talent/home?from=platform",
                             wait_until="domcontentloaded", timeout=20000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"[wechat/{uid_label}] talent/home 访问 warning: {e}")

        # Step 2: 访问 talent/kf 引导 talent_rand
        try:
            await page.goto(STORE_TALENT_KF,
                             wait_until="domcontentloaded", timeout=15000)
            await page.wait_for_timeout(2000)
        except Exception as e:
            log.warning(f"[wechat/{uid_label}] talent/kf 访问 warning: {e}")

        # 诊断: 看现在的 cookies
        cur_cookies = await context.cookies()
        log.info(f"[wechat/{uid_label}] 当前 context cookies: {len(cur_cookies)}")
        for c in cur_cookies:
            if c['name'] in ('talent_token', 'talent_rand', 'talent_magic',
                             'sessionid', 'wxuin'):
                log.info(f"  [{c['domain']}] {c['name']} len={len(c['value'])} "
                         f"expires={c.get('expires', -1)}")

        # Step 3: 调 refresh_session
        try:
            response = await context.request.post(
                REFRESH_SESSION_URL,
                headers=REFRESH_SESSION_HEADERS,
                data=json.dumps({}),
                timeout=15000,
            )
            status = response.status
            body = await response.text()
            try:
                body_json = json.loads(body)
            except Exception:
                body_json = {"raw": body[:500]}
        except Exception as e:
            await context.close()
            return {"ok": False, "error": f"refresh request failed: {e}"}

        ret_code = body_json.get("base_resp", {}).get("ret")
        ret_msg = body_json.get("base_resp", {}).get("err_msg", "")

        # Step 4: 导出新 cookies (无论成败都更新)
        try:
            new_cookies = await context.cookies()
            with open(cookies_file, "w", encoding="utf-8") as f:
                json.dump(new_cookies, f, ensure_ascii=False, indent=2)
            log.info(f"[wechat/{uid_label}] 保存 {len(new_cookies)} 条 cookies")
        except Exception as e:
            log.warning(f"[wechat/{uid_label}] 保存 cookies 失败: {e}")

        result = {
            "ok": ret_code == 0,
            "uid_label": uid_label,
            "status": status,
            "ret_code": ret_code,
            "ret_msg": ret_msg,
            "body_preview": str(body_json)[:400],
            "cookies_before": len(saved_cookies),
            "cookies_after": len(cur_cookies),
            "refreshed_at": time.time(),
        }

        if ret_code == 0:
            log.info(f"[wechat/{uid_label}] ✅ refresh_session OK (ret=0)")
        else:
            log.warning(
                f"[wechat/{uid_label}] ⚠ refresh_session ret={ret_code} msg={ret_msg!r}"
            )
            if ret_code == 30000:
                result["need_rescan"] = True

        await context.close()
        return result


# ────────────────────────────────────────────────────────────────
# 3. 定时任务 (每 6h 循环续期)
# ────────────────────────────────────────────────────────────────

async def keep_alive_loop(
    user_data_dir: str,
    uid_label: str = "?",
    interval_sec: int = DEFAULT_REFRESH_INTERVAL_SEC,
    max_cycles: int = 0,
):
    """持续续期循环. max_cycles=0 表示无限循环.

    推荐: 把这个函数在 asyncio task 或独立进程里跑,
    或者每 6h 走 cron / Windows Task Scheduler 调一次
    `refresh_session_once(user_data_dir)`.
    """
    cycle = 0
    while max_cycles == 0 or cycle < max_cycles:
        result = await refresh_session_once(user_data_dir, uid_label)
        log.info(f"[keeper/{uid_label}] cycle {cycle} result: {result}")

        if result.get("need_rescan"):
            log.error(f"[keeper/{uid_label}] 🚨 需要重新扫码! cookie 已真正过期")
            # 这里可触发通知 (钉钉 / email / dashboard 提示)
            return {"ok": False, "cycles": cycle, "need_rescan": True}

        await asyncio.sleep(interval_sec)
        cycle += 1

    return {"ok": True, "cycles": cycle}


# ────────────────────────────────────────────────────────────────
# 4. 读 Chrome Partition Cookie DB (跨进程取 cookie)
# ────────────────────────────────────────────────────────────────

def read_chromium_cookies(user_data_dir: str,
                           domain_filter: str = "") -> list[dict]:
    """直接读 Chromium 的 Network/Cookies SQLite (对齐小V猫做法).

    注意: 读取时 Chromium 进程不能同时运行 (SQLite 锁).
    我们只在 refresh 循环间隔时读.
    """
    cookies_db = Path(user_data_dir) / "Default" / "Network" / "Cookies"
    if not cookies_db.exists():
        # Playwright 可能用不同路径
        cookies_db = Path(user_data_dir) / "Network" / "Cookies"
    if not cookies_db.exists():
        return []

    try:
        conn = sqlite3.connect(f"file:{cookies_db}?mode=ro", uri=True, timeout=5)
        cols = ["name", "value", "host_key", "path", "expires_utc", "is_secure"]
        query = f"SELECT {', '.join(cols)} FROM cookies"
        if domain_filter:
            query += f" WHERE host_key LIKE '%{domain_filter}%'"
        rows = conn.execute(query).fetchall()
        conn.close()
        return [dict(zip(cols, r)) for r in rows]
    except Exception as e:
        log.warning(f"cookie db read failed: {e}")
        return []


# ────────────────────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────────────────────

def _main():
    import argparse
    import sys
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_login = sub.add_parser("login", help="首次扫码登录 + 持久化")
    p_login.add_argument("--profile", required=True, help="user_data_dir 路径")
    p_login.add_argument("--uid", default="default")
    p_login.add_argument("--timeout", type=int, default=600)
    p_login.add_argument("--entry", default="talent",
                          choices=["talent", "channels"],
                          help="talent=store.weixin带货助手(默认) / channels=视频号助手")

    p_refresh = sub.add_parser("refresh", help="单次 refresh_session")
    p_refresh.add_argument("--profile", required=True)
    p_refresh.add_argument("--uid", default="default")

    p_loop = sub.add_parser("keeper", help="守护循环, 定时续期")
    p_loop.add_argument("--profile", required=True)
    p_loop.add_argument("--uid", default="default")
    p_loop.add_argument("--interval", type=int, default=DEFAULT_REFRESH_INTERVAL_SEC)
    p_loop.add_argument("--max-cycles", type=int, default=0)

    p_ck = sub.add_parser("dump-cookies", help="读 Chromium cookie DB")
    p_ck.add_argument("--profile", required=True)
    p_ck.add_argument("--domain", default="weixin.qq.com")

    args = ap.parse_args()

    if args.cmd == "login":
        r = asyncio.run(login_and_persist(
            args.profile, args.uid, headless=False,
            timeout=args.timeout, entry=args.entry,
        ))
    elif args.cmd == "refresh":
        r = asyncio.run(refresh_session_once(args.profile, args.uid))
    elif args.cmd == "keeper":
        r = asyncio.run(keep_alive_loop(
            args.profile, args.uid, args.interval, args.max_cycles,
        ))
    elif args.cmd == "dump-cookies":
        r = read_chromium_cookies(args.profile, args.domain)
        for c in r:
            print(c)
        return

    print(json.dumps(r, ensure_ascii=False, indent=2, default=str))


if __name__ == "__main__":
    _main()
