# -*- coding: utf-8 -*-
"""★ 2026-04-20: 通过 Chrome CDP 网络监听, 在用户手动操作时
抓下目标 XHR 的 URL + body + header, 用于逆向未知 API.

核心用法 (改快手昵称 API 抓取):
  1. open_with_sniffing(account_id, target_url="cp.kuaishou.com/creator-center/profile")
  2. 用户在 Chrome 里点"修改资料" → 改名 → 保存
  3. 我们后台 CDP 监听 Network.requestWillBeSent + Network.responseReceived
  4. 过滤符合 "user|nickname|profile|update|modify" 的 POST
  5. 保存 {url, method, body, headers, response} → tools/trace_publish/sniff_*.json
  6. 后续从 trace 写成 publisher.change_nickname() 自动调

使用:
  from core.browser_api_sniffer import BrowserAPISniffer
  s = BrowserAPISniffer(account_id=3, port=9223,
                          patterns=["user.*update", "modify.*info", "nickname"])
  s.start_sniffing(duration=300)  # 监听 5 分钟
  captures = s.stop_sniffing()
"""
from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


class BrowserAPISniffer:
    """通过 Chrome DevTools Protocol 监听网络请求, 按 pattern 过滤感兴趣的 XHR."""

    def __init__(self, account_id: int, port: int,
                 patterns: list[str] | None = None,
                 out_dir: str = "tools/trace_publish"):
        self.account_id = account_id
        self.port = port
        self.patterns = [re.compile(p, re.I) for p in
                         (patterns or ["user.*update", "user.*modify",
                                        "nickname", "profile.*update",
                                        "modify.*user"])]
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self._captures: list[dict] = []
        self._ws = None
        self._thread = None
        self._stop = threading.Event()
        self._req_pool: dict[str, dict] = {}  # requestId -> request info

    def _connect_ws(self):
        """拿 page 级 ws url (用 browser 级 + Target domain 监听所有 target)."""
        import urllib.request
        import websocket
        try:
            with urllib.request.urlopen(
                f"http://127.0.0.1:{self.port}/json/version", timeout=3
            ) as r:
                ver = json.loads(r.read())
            # browser-level ws (能监听所有 target)
            ws_url = ver.get("webSocketDebuggerUrl")
            if not ws_url:
                with urllib.request.urlopen(
                    f"http://127.0.0.1:{self.port}/json", timeout=3
                ) as r:
                    tabs = json.loads(r.read())
                candidate = next(
                    (t for t in tabs if t.get("type") == "page" and t.get("webSocketDebuggerUrl")),
                    None
                )
                if candidate:
                    ws_url = candidate["webSocketDebuggerUrl"]
            if not ws_url:
                return None
            ws = websocket.create_connection(ws_url, timeout=5, origin="")
            return ws
        except Exception as e:
            log.warning("[sniffer] ws connect failed: %s", e)
            return None

    def _listen_loop(self, duration: float):
        """主循环: 收 Network 事件, 过滤, 抓 body."""
        ws = self._ws
        if not ws:
            return
        # 跳到所有 target (page) + enable Network
        # Browser-level ws 需要用 Target.attachToTarget, 简单做法: 直接用 page ws 即可
        ws.send(json.dumps({"id": 1, "method": "Network.enable"}))
        try: ws.recv()
        except Exception: pass
        ws.send(json.dumps({"id": 2, "method": "Network.enable",
                             "params": {"maxTotalBufferSize": 10*1024*1024}}))
        try: ws.recv()
        except Exception: pass

        req_id_counter = 100
        deadline = time.time() + duration
        ws.settimeout(1.0)
        while time.time() < deadline and not self._stop.is_set():
            try:
                msg = ws.recv()
            except Exception:
                continue
            try:
                ev = json.loads(msg)
            except Exception:
                continue
            method = ev.get("method")
            p = ev.get("params", {})
            if method == "Network.requestWillBeSent":
                r = p.get("request", {}) or {}
                url = r.get("url", "")
                if r.get("method") not in ("POST", "PUT", "PATCH"):
                    continue
                # 匹配 pattern
                if not any(pat.search(url) for pat in self.patterns):
                    continue
                rid = p.get("requestId")
                self._req_pool[rid] = {
                    "url": url,
                    "method": r.get("method"),
                    "headers": r.get("headers", {}),
                    "post_data": r.get("postData", ""),
                    "timestamp": datetime.now().isoformat(timespec="seconds"),
                }
                log.info("[sniffer] 🎯 match: %s %s", r.get("method"), url[:100])
            elif method == "Network.responseReceived":
                rid = p.get("requestId")
                if rid not in self._req_pool:
                    continue
                resp = p.get("response", {}) or {}
                self._req_pool[rid]["status"] = resp.get("status")
                self._req_pool[rid]["mimeType"] = resp.get("mimeType")
                # 取 response body
                try:
                    req_id_counter += 1
                    ws.send(json.dumps({
                        "id": req_id_counter,
                        "method": "Network.getResponseBody",
                        "params": {"requestId": rid},
                    }))
                except Exception:
                    pass
            elif method == "Network.loadingFinished":
                rid = p.get("requestId")
                if rid not in self._req_pool:
                    continue
                # 此 requestId 已完成, finalize
                entry = self._req_pool.pop(rid)
                self._captures.append(entry)
                log.info("[sniffer] ✅ captured: %s (status=%s)",
                         entry["url"][:80], entry.get("status"))
            else:
                # getResponseBody 的 result
                if ev.get("id") and ev.get("result", {}).get("body"):
                    # 简化: 找 request pool 里缺 response_body 的那条
                    for rid, entry in self._req_pool.items():
                        if "response_body" not in entry:
                            entry["response_body"] = ev["result"]["body"][:2000]
                            break

    def start_sniffing(self, duration: float = 300) -> bool:
        """启动监听 N 秒."""
        self._ws = self._connect_ws()
        if not self._ws:
            return False
        self._stop.clear()
        self._thread = threading.Thread(target=self._listen_loop,
                                          args=(duration,), daemon=True)
        self._thread.start()
        log.info("[sniffer] 启动 %ds sniffing on port %d", duration, self.port)
        return True

    def stop_sniffing(self) -> list[dict]:
        """停止 + 返回 captures + 写 trace 文件."""
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)
        if self._ws:
            try: self._ws.close()
            except: pass

        # 把 req_pool 剩的也 flush
        for rid, entry in list(self._req_pool.items()):
            self._captures.append(entry)
            del self._req_pool[rid]

        # 存 trace
        if self._captures:
            out_file = self.out_dir / f"sniff_acc{self.account_id}_{int(time.time())}.json"
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump({
                    "account_id": self.account_id,
                    "port": self.port,
                    "patterns": [p.pattern for p in self.patterns],
                    "captured_at": datetime.now().isoformat(timespec="seconds"),
                    "count": len(self._captures),
                    "captures": self._captures,
                }, f, ensure_ascii=False, indent=2)
            log.info("[sniffer] 📁 saved %d captures → %s", len(self._captures), out_file)
        return self._captures
