# -*- coding: utf-8 -*-
"""独立浏览器启动器 — 脱离 KS184, 自己启 Chrome + 注入 cookie.

方案:
  1. 找本机 Chrome 可执行文件
  2. 为每个账号创建独立的 user-data-dir (隔离 profile)
  3. 启动 Chrome + remote-debugging-port (9222+) + 打开 cp.kuaishou.com
  4. 通过 DevTools Protocol 注入 cookie
  5. 返回 pid, 供 /stop-browser 用

用法:
    launcher = BrowserLauncher()
    result = launcher.launch_for_account(account_id, target_url="https://cp.kuaishou.com")
    # → {"pid": 1234, "port": 9222, "profile_dir": "...", "url": "..."}
    launcher.stop(pid)
"""
from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from core.logger import get_logger

log = get_logger("browser_launcher")


# 候选 Chrome 路径
_CHROME_CANDIDATES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Users\Administrator\AppData\Local\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def find_chrome() -> str | None:
    """返回第一个可执行的 Chrome / Edge 路径."""
    for p in _CHROME_CANDIDATES:
        if os.path.isfile(p):
            return p
    # PATH 里找
    for name in ("chrome.exe", "chrome", "msedge.exe"):
        p = shutil.which(name)
        if p:
            return p
    return None


def _find_free_port(start: int = 9222, end: int = 9322) -> int | None:
    for p in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return None


class BrowserLauncher:
    """启动独立 Chrome 进程 + cookie 注入."""

    def __init__(self, db_manager=None, profiles_root: str | None = None):
        self.db = db_manager
        root = profiles_root or str(Path(__file__).resolve().parent.parent
                                   / "data" / "browser_profiles")
        self.profiles_root = Path(root)
        self.profiles_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------

    def launch_for_account(
        self,
        account_id: int,
        target_url: str = "https://cp.kuaishou.com/",
        inject_cookies: bool = True,
        headless: bool = False,
    ) -> dict[str, Any]:
        """启动浏览器, 返回 {ok, pid, port, profile_dir, url, chrome_path}"""
        chrome = find_chrome()
        if not chrome:
            return {
                "ok": False,
                "error": "未找到 Chrome 或 Edge. 请安装或手动添加到 PATH.",
            }

        profile_dir = self.profiles_root / f"acct_{account_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)

        port = _find_free_port()
        if not port:
            return {"ok": False, "error": "找不到 9222-9322 空闲端口"}

        # 读该账号 cookie 供注入参考 (可选)
        cookies_preview = []
        if inject_cookies and self.db is not None:
            cookies_preview = self._collect_cookies(account_id)

        args = [
            chrome,
            f"--user-data-dir={profile_dir}",
            f"--remote-debugging-port={port}",
            # ★ 2026-04-20 关键修复: Chrome 147+ 默认拒 WebSocket CDP 连接,
            # 导致 cookie 注入 403 Forbidden. 必须加 --remote-allow-origins=*
            "--remote-allow-origins=*",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=TranslateUI",
            target_url,
        ]
        if headless:
            args.append("--headless=new")

        try:
            proc = subprocess.Popen(
                args,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=(subprocess.CREATE_NEW_PROCESS_GROUP
                               if sys.platform == "win32" else 0),
            )
        except Exception as e:
            return {"ok": False, "error": f"启动 Chrome 失败: {e}"}

        # 异步注入 cookie (DevTools Protocol 需要 Chrome 启动完成)
        if inject_cookies and cookies_preview:
            import threading
            threading.Thread(
                target=self._inject_cookies_via_cdp,
                args=(port, cookies_preview),
                daemon=True,
            ).start()

        return {
            "ok": True,
            "pid": proc.pid,
            "port": port,
            "profile_dir": str(profile_dir),
            "url": target_url,
            "chrome_path": chrome,
            "cookie_count": len(cookies_preview),
        }

    # ------------------------------------------------------------------

    def stop(self, pid: int) -> dict[str, Any]:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/F", "/PID", str(pid), "/T"],
                    capture_output=True, timeout=10,
                )
            else:
                os.kill(pid, 15)
            return {"ok": True, "pid": pid}
        except Exception as e:
            return {"ok": False, "error": str(e)}

    # ------------------------------------------------------------------

    def _collect_cookies(self, account_id: int) -> list[dict]:
        """从 device_accounts.cookies JSON 中提取 cookie (按各 suite 的 domain 分派)."""
        if self.db is None:
            return []
        try:
            row = self.db.conn.execute(
                "SELECT cookies FROM device_accounts WHERE id=?",
                (account_id,),
            ).fetchone()
        except Exception:
            return []
        if not row or not row[0]:
            return []

        # 解析 JSON
        try:
            data = json.loads(row[0])
        except Exception:
            # 有可能直接是字符串 "k=v; ..." - 回退解析
            data = None

        cookies: list[dict] = []

        def _add(name: str, value: str, domain: str, **extra):
            if not name or value is None:
                return
            cookies.append({
                "name": name, "value": str(value),
                "domain": domain, "path": "/",
                "secure": True, "httpOnly": False,
                **extra,
            })

        if isinstance(data, dict):
            # 1. cookies[] 主站列表 (保留完整元数据)
            for c in (data.get("cookies") or []):
                if isinstance(c, dict) and c.get("name"):
                    _add(c["name"], c.get("value"),
                         c.get("domain") or ".kuaishou.com",
                         httpOnly=c.get("httpOnly", False),
                         secure=c.get("secure", True),
                         sameSite=c.get("sameSite", "None"),
                         **({"expires": int(c["expires"])} if c.get("expires") else {}))

            # 2. 各 suite 字符串
            for suite_key, domain in [
                ("creator_cookie",  ".cp.kuaishou.com"),
                ("shop_cookie",     ".cps.kuaishou.com"),
                ("niu_cookie",      ".niu.e.kuaishou.com"),
                ("official_cookie", ".kuaishou.com"),
            ]:
                suite_str = data.get(suite_key)
                if not isinstance(suite_str, str):
                    continue
                for pair in suite_str.split(";"):
                    pair = pair.strip()
                    if "=" not in pair:
                        continue
                    k, _, v = pair.partition("=")
                    _add(k.strip(), v.strip(), domain)
        elif isinstance(data, list):
            # 纯数组 (老格式)
            for c in data:
                if isinstance(c, dict) and c.get("name"):
                    _add(c["name"], c.get("value"),
                         c.get("domain") or ".kuaishou.com")
        elif isinstance(row[0], str) and "=" in row[0]:
            # 直接字符串
            for pair in row[0].split(";"):
                pair = pair.strip()
                if "=" not in pair:
                    continue
                k, _, v = pair.partition("=")
                _add(k.strip(), v.strip(), ".kuaishou.com")

        # 去重 (按 name+domain)
        seen = set()
        unique = []
        for c in cookies:
            key = (c["name"], c["domain"])
            if key in seen:
                continue
            seen.add(key)
            unique.append(c)
        return unique

    def _inject_cookies_via_cdp(self, port: int, cookies: list[dict]) -> None:
        """等 Chrome 起来, 通过 CDP 批量注入 cookie. 成功后导航目标页."""
        import urllib.request

        # 先等 remote-debugging ready (15s)
        for attempt in range(30):
            time.sleep(0.5)
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/json/version", timeout=1)
                break
            except Exception:
                continue
        else:
            log.warning("Chrome DevTools 未就绪, 放弃 cookie 注入")
            return

        # ★ 2026-04-20 关键修复: 必须用 **tab-level** ws (Network 域只在 tab 有).
        # browser-level ws (来自 /json/version) 不支持 Network.setCookies → -32601.
        # 等 3s 让 Chrome 初始 tab 就绪.
        for _ in range(10):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as r:
                    tabs = json.loads(r.read())
                # 过滤可 attach 的 page 类型 tab
                candidate_tabs = [t for t in tabs
                                   if t.get("type") == "page"
                                      and t.get("webSocketDebuggerUrl")]
                if candidate_tabs:
                    ws_url = candidate_tabs[0]["webSocketDebuggerUrl"]
                    break
            except Exception as e:
                pass
            time.sleep(0.5)
        else:
            log.warning("无可用 tab ws_url, 放弃注入")
            return

        try:
            import websocket  # type: ignore
        except ImportError:
            log.info("websocket-client 未安装. 跳过 CDP 注入.")
            return

        # 规范化 cookie: 补 sameSite / expires
        normalized = []
        for c in cookies:
            entry = {
                "name": c["name"],
                "value": c["value"],
                "domain": c.get("domain", ".kuaishou.com"),
                "path": c.get("path", "/"),
                "secure": c.get("secure", True),
                "httpOnly": c.get("httpOnly", False),
            }
            # sameSite (CDP 要求 "Strict"/"Lax"/"None")
            ss = c.get("sameSite", "")
            if isinstance(ss, str):
                ss_norm = ss.lower()
                if ss_norm in ("none", "no_restriction"):
                    entry["sameSite"] = "None"
                elif ss_norm == "strict":
                    entry["sameSite"] = "Strict"
                elif ss_norm in ("lax", "unspecified"):
                    entry["sameSite"] = "Lax"
            # expires (epoch seconds, 可选)
            if "expires" in c and c["expires"]:
                try:
                    entry["expires"] = float(c["expires"])
                except Exception:
                    pass
            normalized.append(entry)

        try:
            # ★ Chrome 147+ 要求 origin, 传空字符串绕过 (browser 已允许 *)
            ws = websocket.create_connection(ws_url, timeout=5, origin="")

            # 先 Network.enable (某些 Chrome 版本需要)
            ws.send(json.dumps({"id": 0, "method": "Network.enable"}))
            try: ws.recv()
            except Exception: pass

            # 方式 1 (推荐): Network.setCookies 批量
            ws.send(json.dumps({
                "id": 1,
                "method": "Network.setCookies",
                "params": {"cookies": normalized},
            }))
            resp = ws.recv()
            result = json.loads(resp) if resp else {}
            ok_count = 0
            fail_count = 0
            if "error" in result:
                # 回退: 逐条 setCookie (旧 Chrome 只支持单条)
                log.warning("setCookies 批量失败, 回退逐条: %s", result.get("error"))
                req_id = 2
                for c in normalized:
                    ws.send(json.dumps({
                        "id": req_id, "method": "Network.setCookie", "params": c,
                    }))
                    try:
                        r1 = json.loads(ws.recv())
                        if r1.get("result", {}).get("success"):
                            ok_count += 1
                        else:
                            fail_count += 1
                    except Exception:
                        fail_count += 1
                    req_id += 1
            else:
                ok_count = len(normalized)

            ws.close()
            log.info("CDP 注入 cookie: %d/%d 成功 (port %d)",
                     ok_count, len(normalized), port)
        except Exception as e:
            log.warning("CDP 注入失败: %s", e)


# ---------------------------------------------------------------------------
# 独立工具: 从运行中的 Chrome 里反向拉 cookie
# ---------------------------------------------------------------------------

def fetch_cookies_from_chrome(port: int, url_filter: str | None = None) -> list[dict]:
    """通过 CDP 从运行中的 Chrome 拉所有 cookie.
    给浏览器登录流程用: 用户登录后, 我们从 Chrome 读 cookie 回库.
    """
    import urllib.request
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/version", timeout=2,
        ) as r:
            ver = json.loads(r.read())
        ws_url = ver.get("webSocketDebuggerUrl", "")
    except Exception:
        return []
    if not ws_url:
        return []

    try:
        import websocket  # type: ignore
    except ImportError:
        return []

    try:
        ws = websocket.create_connection(ws_url, timeout=5)
        if url_filter:
            ws.send(json.dumps({
                "id": 1, "method": "Network.getCookies",
                "params": {"urls": [url_filter]},
            }))
        else:
            ws.send(json.dumps({"id": 1, "method": "Storage.getCookies"}))
        resp = ws.recv()
        ws.close()
        data = json.loads(resp or "{}")
        cookies = data.get("result", {}).get("cookies", [])
        return cookies
    except Exception as e:
        log.warning("fetch_cookies_from_chrome 失败: %s", e)
        return []
