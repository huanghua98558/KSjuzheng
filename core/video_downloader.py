# -*- coding: utf-8 -*-
"""Video downloader using N_m3u8DL-RE for HLS streams.

Downloads Kuaishou drama videos from m3u8 URLs captured via share links,
saving them as MP4 files organized by account and drama name.
"""

from __future__ import annotations

import hashlib
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Optional

import requests

from core.config import (
    FFMPEG_EXE,
    N_M3U8DL_EXE,
    RETRY_CONFIG,
    VIDEO_DOWNLOAD_DIR,
)

logger = logging.getLogger(__name__)

_WEB_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
}

# Regex to extract m3u8 URLs from page source or network responses
_M3U8_PATTERN = re.compile(
    r'(https?://[^\s"\'<>]+?_hlsb?\.m3u8[^\s"\'<>]*)',
    re.IGNORECASE,
)


class VideoDownloader:
    """Download HLS video streams via N_m3u8DL-RE.

    N_m3u8DL-RE command template::

        N_m3u8DL-RE.exe {m3u8_url}
            --save-dir {save_dir}
            --save-name {video_name}
            -mt --thread-count 16
            --ffmpeg-binary-path {ffmpeg_path}
    """

    def __init__(
        self,
        n_m3u8dl_path: str = N_M3U8DL_EXE,
        ffmpeg_path: str = FFMPEG_EXE,
        save_base_dir: str = VIDEO_DOWNLOAD_DIR,
    ) -> None:
        """
        Parameters
        ----------
        n_m3u8dl_path : str
            Absolute path to ``N_m3u8DL-RE.exe``.
        ffmpeg_path : str
            Absolute path to ``ffmpeg.exe`` (used by N_m3u8DL-RE for muxing).
        save_base_dir : str
            Root directory for all downloaded videos.
        """
        self.n_m3u8dl = n_m3u8dl_path
        self.ffmpeg = ffmpeg_path
        self.save_base_dir = Path(save_base_dir) if save_base_dir else Path(r"D:\ks_automation\downloads")

        if not self.n_m3u8dl:
            logger.warning("[VideoDownloader] N_m3u8DL-RE path not configured")
        if not self.ffmpeg:
            logger.warning("[VideoDownloader] ffmpeg path not configured")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _make_safe_name(name: str) -> str:
        """Sanitize a string for use as a file or directory name."""
        safe = re.sub(r'[\\/:*?"<>|]', "_", name)
        safe = safe.strip(". ")
        return safe[:80] if safe else "untitled"

    @staticmethod
    def _short_hash(url: str) -> str:
        """Return a 6-char hex hash of a URL for uniqueness."""
        return hashlib.md5(url.encode()).hexdigest()[:6]

    # ------------------------------------------------------------------
    # Download
    # ------------------------------------------------------------------

    def download_video(
        self,
        m3u8_url: str,
        account_id: str,
        drama_name: str,
    ) -> str:
        """Download a video from an m3u8 URL using N_m3u8DL-RE.

        Saves the output to::

            {save_base_dir}/{account_id}/{drama_name}/video_{hash}_{timestamp}.mp4

        Parameters
        ----------
        m3u8_url : str
            Full m3u8 playlist URL.
        account_id : str
            Account identifier (used for directory organization).
        drama_name : str
            Drama title (used for subdirectory naming).

        Returns
        -------
        str
            Absolute path to the downloaded MP4 file, or empty string on failure.
        """
        if not self.n_m3u8dl:
            logger.error("[VideoDownloader] N_m3u8DL-RE path not set")
            return ""

        safe_drama = self._make_safe_name(drama_name)
        safe_account = self._make_safe_name(str(account_id))
        url_hash = self._short_hash(m3u8_url)
        timestamp = int(time.time())
        video_name = f"video_{url_hash}_{timestamp}"

        save_dir = self.save_base_dir / safe_account / safe_drama
        save_dir.mkdir(parents=True, exist_ok=True)

        expected_output = save_dir / f"{video_name}.mp4"

        cmd = [
            self.n_m3u8dl,
            m3u8_url,
            "--save-dir", str(save_dir),
            "--save-name", video_name,
            "-mt",
            "--thread-count", "16",
        ]
        if self.ffmpeg:
            cmd.extend(["--ffmpeg-binary-path", self.ffmpeg])

        max_retry = RETRY_CONFIG.get("max_retry", 3)
        retry_delay = RETRY_CONFIG.get("retry_delay", 10)
        use_backoff = RETRY_CONFIG.get("exponential_backoff", True)

        for attempt in range(max_retry):
            logger.info(
                "[VideoDownloader] Downloading (attempt %d/%d): %s -> %s",
                attempt + 1, max_retry, m3u8_url[:80], expected_output,
            )
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=600,  # 10 minute timeout per attempt
                )
                if result.returncode == 0 and expected_output.exists():
                    file_size = expected_output.stat().st_size
                    logger.info(
                        "[VideoDownloader] Download success: %s (%d bytes)",
                        expected_output, file_size,
                    )
                    return str(expected_output)

                # Check for output file even if return code was non-zero
                if expected_output.exists() and expected_output.stat().st_size > 0:
                    logger.warning(
                        "[VideoDownloader] N_m3u8DL-RE returned code %d but file exists, accepting",
                        result.returncode,
                    )
                    return str(expected_output)

                logger.warning(
                    "[VideoDownloader] Download attempt %d failed (rc=%d)\nstdout: %s\nstderr: %s",
                    attempt + 1, result.returncode,
                    result.stdout[-500:] if result.stdout else "",
                    result.stderr[-500:] if result.stderr else "",
                )

            except subprocess.TimeoutExpired:
                logger.error(
                    "[VideoDownloader] Download timed out (attempt %d/%d)",
                    attempt + 1, max_retry,
                )
            except FileNotFoundError:
                logger.error(
                    "[VideoDownloader] N_m3u8DL-RE executable not found: %s",
                    self.n_m3u8dl,
                )
                return ""
            except OSError as exc:
                logger.error(
                    "[VideoDownloader] OS error running N_m3u8DL-RE: %s", exc,
                )
                return ""

            if attempt < max_retry - 1:
                delay = retry_delay * (2 ** attempt if use_backoff else 1)
                logger.info("[VideoDownloader] Retrying in %d seconds...", delay)
                time.sleep(delay)

        logger.error(
            "[VideoDownloader] Failed to download after %d attempts: %s",
            max_retry, m3u8_url[:100],
        )
        return ""

    # ------------------------------------------------------------------
    # Extract m3u8 URL from drama page
    # ------------------------------------------------------------------

    def get_m3u8_url_from_drama_page(
        self,
        drama_url: str,
        cookie_str: str = "",
    ) -> str:
        """Visit a kuaishou.com/f/ share page and extract the m3u8 URL.

        The page's HTML or embedded JSON data typically contains a direct
        link to the HLS manifest (``*_hlsb.m3u8``).

        Parameters
        ----------
        drama_url : str
            Share link, e.g. ``https://www.kuaishou.com/f/XXXXXX``.
        cookie_str : str
            Optional cookie header for authenticated access.

        Returns
        -------
        str
            The m3u8 URL if found, or empty string on failure.
        """
        headers = {**_WEB_HEADERS}
        if cookie_str:
            headers["Cookie"] = cookie_str

        max_retry = RETRY_CONFIG.get("max_retry", 3)
        retry_delay = RETRY_CONFIG.get("retry_delay", 10)
        use_backoff = RETRY_CONFIG.get("exponential_backoff", True)

        for attempt in range(max_retry):
            try:
                resp = requests.get(
                    drama_url,
                    headers=headers,
                    timeout=15,
                    allow_redirects=True,
                )
                resp.raise_for_status()
                page_text = resp.text

                # Search for m3u8 URL in the page content
                matches = _M3U8_PATTERN.findall(page_text)
                if matches:
                    # Prefer _hlsb variant (higher quality) over plain _hls
                    for url in matches:
                        if "_hlsb" in url:
                            logger.info(
                                "[VideoDownloader] Found m3u8 (hlsb): %s", url[:100],
                            )
                            return url
                    # Fall back to first match
                    m3u8_url = matches[0]
                    logger.info(
                        "[VideoDownloader] Found m3u8: %s", m3u8_url[:100],
                    )
                    return m3u8_url

                # ↓ Chrome headless fallback 在此加 (找不到 m3u8 时自动升级)
                # (下面的循环会继续 retry requests; retry 全挂后 get_m3u8_via_chrome_fallback)
                logger.warning(
                    "[VideoDownloader] No m3u8 URL found in page (attempt %d/%d): %s",
                    attempt + 1, max_retry, drama_url,
                )

            except requests.RequestException as exc:
                logger.warning(
                    "[VideoDownloader] Page fetch failed (attempt %d/%d): %s",
                    attempt + 1, max_retry, exc,
                )

            if attempt < max_retry - 1:
                delay = retry_delay * (2 ** attempt if use_backoff else 1)
                time.sleep(delay)

        logger.warning(
            "[VideoDownloader] requests fallback 失败, 自动升级到 Chrome headless: %s",
            drama_url,
        )
        # Chrome headless fallback — 监听 Network 抓 m3u8
        chrome_url = self._get_m3u8_via_chrome(drama_url, cookie_str)
        if chrome_url:
            logger.info("[VideoDownloader] ✓ Chrome fallback got m3u8: %s", chrome_url[:100])
            return chrome_url
        logger.error(
            "[VideoDownloader] Chrome fallback 也失败: %s", drama_url,
        )
        return ""

    # ------------------------------------------------------------------

    def _get_m3u8_via_chrome(self, drama_url: str, cookie_str: str = "",
                              timeout_seconds: int = 30) -> str:
        """启独立 Chrome + Network 监听 — 自动抓 m3u8.

        流程:
          1. BrowserLauncher 启 headless Chrome
          2. CDP Network.enable + 订阅 Network.responseReceived
          3. 导航到 drama_url
          4. 等 m3u8 请求出现 (最多 30s)
          5. 关 Chrome 返回 m3u8
        """
        try:
            from core.browser_launcher import BrowserLauncher, find_chrome
            import urllib.request
            import websocket  # type: ignore
        except ImportError as e:
            logger.error("[VideoDownloader] Chrome fallback 依赖缺失: %s", e)
            return ""
        if not find_chrome():
            logger.error("[VideoDownloader] Chrome 未找到")
            return ""

        launcher = BrowserLauncher()
        info = launcher.launch_for_account(
            account_id=0, target_url="about:blank",
            inject_cookies=False, headless=True,
        )
        if not info.get("ok"):
            logger.error("[VideoDownloader] Chrome 启动失败: %s", info.get("error"))
            return ""
        port = info["port"]
        pid = info["pid"]

        try:
            # 等 DevTools 就绪
            for _ in range(30):
                time.sleep(0.5)
                try:
                    urllib.request.urlopen(
                        f"http://127.0.0.1:{port}/json/version", timeout=1,
                    )
                    break
                except Exception:
                    continue
            # 拿 tab ws_url
            import json as _json
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/json") as r:
                tabs = _json.loads(r.read())
            if not tabs:
                return ""
            ws_url = tabs[0].get("webSocketDebuggerUrl", "")
            if not ws_url:
                return ""

            ws = websocket.create_connection(ws_url, timeout=5)
            # 1. Enable Network
            ws.send(_json.dumps({"id": 1, "method": "Network.enable"}))
            ws.recv()
            # 2. 注入 cookie
            if cookie_str:
                cookies = []
                for pair in cookie_str.split(";"):
                    pair = pair.strip()
                    if "=" not in pair:
                        continue
                    k, _, v = pair.partition("=")
                    cookies.append({
                        "name": k.strip(), "value": v.strip(),
                        "domain": ".kuaishou.com", "path": "/",
                        "secure": True, "httpOnly": False,
                    })
                if cookies:
                    ws.send(_json.dumps({
                        "id": 2, "method": "Network.setCookies",
                        "params": {"cookies": cookies},
                    }))
                    ws.recv()
            # 3. 导航
            ws.send(_json.dumps({
                "id": 3, "method": "Page.navigate",
                "params": {"url": drama_url},
            }))
            ws.recv()
            # 4. 轮询 events 抓 m3u8
            ws.settimeout(1.5)
            deadline = time.time() + timeout_seconds
            found_m3u8 = ""
            while time.time() < deadline and not found_m3u8:
                try:
                    msg = ws.recv()
                    data = _json.loads(msg)
                    method = data.get("method", "")
                    if method in ("Network.responseReceived",
                                   "Network.requestWillBeSent"):
                        params = data.get("params", {})
                        req = params.get("request") or {}
                        resp = params.get("response") or {}
                        for url in (req.get("url", ""), resp.get("url", "")):
                            if ".m3u8" in url.lower():
                                # 优先 hlsb
                                if "_hlsb" in url:
                                    found_m3u8 = url
                                    break
                                if not found_m3u8:
                                    found_m3u8 = url
                        if found_m3u8:
                            break
                except Exception:
                    continue

            try:
                ws.close()
            except Exception:
                pass
            return found_m3u8
        finally:
            try:
                launcher.stop(pid)
            except Exception:
                pass
