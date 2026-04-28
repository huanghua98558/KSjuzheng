"""请求频率限制器（防快手风控）

实测 www.kuaishou.com 限制约 25 次/分钟。
cp.kuaishou.com 没观察到风控（业务后台限制更宽松）。
"""
from __future__ import annotations

import threading
import time
from collections import deque


class RateLimiter:
    def __init__(self, max_requests: int = 25, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window = window_seconds
        self._timestamps: deque = deque()
        self._lock = threading.Lock()

    def acquire(self) -> float:
        """阻塞直到可以发请求。返回等待秒数。"""
        with self._lock:
            now = time.monotonic()
            # 清理过期
            while self._timestamps and now - self._timestamps[0] > self.window:
                self._timestamps.popleft()

            if len(self._timestamps) >= self.max_requests:
                wait = self.window - (now - self._timestamps[0]) + 0.5
                if wait > 0:
                    time.sleep(wait)
                    return wait
            self._timestamps.append(time.monotonic())
            return 0.0

    def stats(self) -> dict:
        with self._lock:
            now = time.monotonic()
            active = sum(1 for t in self._timestamps if now - t <= self.window)
            return {"active": active, "max": self.max_requests, "window_s": self.window}
