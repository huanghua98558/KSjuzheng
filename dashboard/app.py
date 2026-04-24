# -*- coding: utf-8 -*-
"""KS 矩阵运营中台 — FastAPI 主入口.

结构:
  /api/*           JSON API (dashboard/api.py 中定义)
  /legacy/*        旧版 Jinja2 HTML 页面 (开发期回退用)
  /assets/* /vite.svg 等   SPA 构建产物 (Vite 产出的静态文件)
  /                SPA 主入口 (index.html), 前端 React Router 接管
  /任意未匹配路径    SPA catch-all (返回 index.html)
"""
from __future__ import annotations

import sys
from pathlib import Path

# 确保项目根目录在 sys.path
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware

from core.db_manager import DBManager  # noqa: E402
from core.data_insights import DataInsights  # noqa: E402
from core.switches import get_all as get_all_switches, set_switch  # noqa: E402

from dashboard.api import router as api_router  # noqa: E402
from dashboard.auth_api import router as auth_router  # noqa: E402
from dashboard.review_api import router as review_router  # noqa: E402
from dashboard.mcn_api import router as mcn_router  # noqa: E402
from dashboard.analytics_api import router as analytics_router  # noqa: E402
from dashboard.stream_api import router as stream_router  # noqa: E402


# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="KS 矩阵运营中台", version="0.2.0")


@app.on_event("startup")
def _start_worker() -> None:
    """★ 2026-04-24 v6 Day 5-C: 已下线 WorkerManager.

    Worker 进程由 `python -m scripts.run_autopilot` 单独启动, dashboard
    只做 web UI. 原因:
      - 历史 split-brain: WorkerManager + account_executor.Executor 两套
        并存, 任务被 "谁先抢" 决定, 观测混乱.
      - SQLite WAL 多进程写锁竞争: dashboard 长运行 + worker 常驻同 PID,
        SIGINT / reload 会让两者同时不干净.
    保留本 hook 仅提示用户如何启动 worker, 不做任何动作.
    """
    print("[dashboard] worker 由 run_autopilot 单独管理 (不在 app.py 里启动)")


@app.on_event("shutdown")
def _stop_worker() -> None:
    # No-op. Worker 进程由 run_autopilot 自己处理 SIGINT/SIGTERM.
    pass


# ---------------------------------------------------------------------------
# 中间件 — 全部使用 Pure ASGI Middleware (不用 BaseHTTPMiddleware)
#
# 历史 bug (2026-04-20 修): 3 层 BaseHTTPMiddleware 串联导致每 request
# 增加 ~1s 延迟 (总 3-4s). BaseHTTPMiddleware 在 starlette/anyio 组合下
# 会为每层做 request/response body 缓冲 + memory-channel 同步. 改用 ASGI
# middleware 后首字节毫秒级返回.
# 参考: https://github.com/encode/starlette/issues/1438
# ---------------------------------------------------------------------------

_DIAG_LOG = Path(__file__).parent / ".diag_405.log"
import os as _os
from datetime import datetime as _dt_diag

_AUTH_ENFORCE = _os.environ.get("KS_AUTH_ENFORCE", "0") == "1"
_AUTH_EXEMPT_PREFIXES = (
    "/api/auth/login",
    "/api/auth/logout",
    "/api/sig/health",
    "/api/health",
    "/api/home",
    "/api/stream/",
    "/docs", "/redoc", "/openapi.json",
    "/static/", "/assets/",
    "/__reset",
    "/legacy",
)
_MUTATING_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
_AUDIT_SKIP_PREFIXES = (
    "/api/auth/login",
    "/api/auth/logout",
    "/api/autopilot/trigger",
)


class KSCombinedMiddleware:
    """单一 Pure ASGI Middleware 合并 Auth + Audit + Diagnostic 三项.

    为什么合一层: BaseHTTPMiddleware 每层 ~1s 延迟, 合并后净延迟 <1ms.
    """
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope.get("path", "")
        method = scope.get("method", "GET")

        # ─── Auth enforce (只在 KS_AUTH_ENFORCE=1 时拦) ───
        if _AUTH_ENFORCE and path.startswith("/api/") and path != "/":
            exempt = any(path.startswith(p) for p in _AUTH_EXEMPT_PREFIXES)
            if not exempt:
                try:
                    # 手动从 headers 提 Authorization
                    headers = dict((k.decode("latin1").lower(), v.decode("latin1"))
                                   for k, v in scope.get("headers", []))
                    auth_header = headers.get("authorization", "")
                    token = auth_header[7:] if auth_header.startswith("Bearer ") else ""
                    if not token:
                        await self._send_401(send, "not authenticated")
                        return
                    from core.auth import verify_token
                    verify_token(token)
                except Exception as e:
                    code = getattr(e, "status_code", 401)
                    detail = getattr(e, "detail", str(e))
                    await self._send_json(send, code, {"detail": detail})
                    return

        # ─── 包装 send 以拦截 response status (用于 diag 405/404 + audit) ───
        # 只在真需要检查时包装 (减少开销)
        need_wrap = (
            path.startswith("/api/") and (
                (method in _MUTATING_METHODS
                 and not any(path.startswith(p) for p in _AUDIT_SKIP_PREFIXES))
                or True  # 保留 diag 405/404 能力
            )
        )

        if not need_wrap:
            await self.app(scope, receive, send)
            return

        status_holder = {"code": 200}

        async def wrapped_send(message):
            if message["type"] == "http.response.start":
                status_holder["code"] = message.get("status", 200)
            await send(message)

        await self.app(scope, receive, wrapped_send)

        status_code = status_holder["code"]

        # ─── 后置: Audit log (mutating 2xx) ───
        if (method in _MUTATING_METHODS and 200 <= status_code < 300
                and path.startswith("/api/")
                and not any(path.startswith(p) for p in _AUDIT_SKIP_PREFIXES)):
            try:
                from core.auth import optional_user, write_audit
                # 从 scope 构造伪 request 提 user/IP
                ip = ""
                client = scope.get("client")
                if client:
                    ip = client[0]
                headers = dict((k.decode("latin1").lower(), v.decode("latin1"))
                               for k, v in scope.get("headers", []))
                auth = headers.get("authorization", "")

                class _FakeReq:
                    def __init__(self):
                        self.headers = headers
                        self.cookies = {}
                        for c in headers.get("cookie", "").split(";"):
                            if "=" in c:
                                k, v = c.split("=", 1)
                                self.cookies[k.strip()] = v.strip()

                u = optional_user(_FakeReq())
                write_audit(
                    u, action=f"{method} {path}",
                    target_type="http", target_id=path,
                    note=f"status={status_code}", ip=ip,
                )
            except Exception:
                pass

        # ─── 后置: 405/404 diag log ───
        if status_code in (404, 405) and path.startswith("/api/"):
            try:
                ua_hdr = ""
                for k, v in scope.get("headers", []):
                    if k == b"user-agent":
                        ua_hdr = v.decode("latin1", errors="replace")[:80]
                        break
                line = (
                    f"[{_dt_diag.now().isoformat(timespec='seconds')}] "
                    f"{status_code}  {method}  {path}"
                    f"  query={scope.get('query_string', b'').decode() or '-'}"
                    f"  UA={ua_hdr}\n"
                )
                with open(_DIAG_LOG, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass

    async def _send_401(self, send, msg):
        await self._send_json(send, 401, {"detail": msg})

    async def _send_json(self, send, status, payload):
        import json as _j
        body = _j.dumps(payload).encode()
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        })
        await send({"type": "http.response.body", "body": body})


app.add_middleware(KSCombinedMiddleware)

app.include_router(auth_router, prefix="/api/auth")
app.include_router(review_router, prefix="/api/review")
app.include_router(mcn_router, prefix="/api/mcn")
app.include_router(analytics_router, prefix="/api/analytics")
app.include_router(stream_router, prefix="/api/stream")
# Pipeline API — Week 1 MVP: config / selector / executor / events
from dashboard.pipeline_api import router as pipeline_router  # noqa: E402
app.include_router(pipeline_router, prefix="/api/pipeline")
app.include_router(api_router, prefix="/api")


# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

_TEMPLATES_DIR = Path(__file__).parent / "templates"
_STATIC_DIR = Path(__file__).parent / "static"
_SPA_DIST_DIR = Path(__file__).parent / "static" / "app"     # Vite 构建输出
_STATIC_DIR.mkdir(exist_ok=True)
_SPA_DIST_DIR.mkdir(parents=True, exist_ok=True)

templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))

# Vite 构建产物中有 /assets/* — 单独挂
_SPA_ASSETS_DIR = _SPA_DIST_DIR / "assets"
if _SPA_ASSETS_DIR.exists():
    app.mount("/assets", StaticFiles(directory=str(_SPA_ASSETS_DIR)), name="spa_assets")

# 通用静态 (图标、老旧 css)
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# DB helper
# ---------------------------------------------------------------------------

def _db() -> DBManager:
    return DBManager()


# ---------------------------------------------------------------------------
# 旧版 Jinja2 HTML 页面 (开发期保留作为 fallback, 挂在 /legacy)
# ---------------------------------------------------------------------------

@app.get("/legacy", response_class=HTMLResponse)
def legacy_home(request: Request):
    db = _db()
    di = DataInsights(db)
    fv = di.build_feature_vector()
    ctx = {
        "request": request, "nav": "home",
        "feature_vector": fv,
        "matrix_summary": fv["matrix"]["summary"],
        "keyword_heat": fv["market"]["keyword_heat"][:8],
        "top_matrix_works": fv["matrix"]["top_works"][:5],
        "income": fv["income"]["today"][:5],
        "counts": fv["counts"],
    }
    db.close()
    return templates.TemplateResponse(request, "home.html", ctx)


@app.get("/legacy/accounts", response_class=HTMLResponse)
def legacy_accounts(request: Request):
    db = _db()
    rows = db.conn.execute("""
        SELECT
            da.id, da.account_name, da.kuaishou_uid, da.login_status,
            da.is_active, da.kuaishou_name,
            (SELECT health_score FROM account_health_snapshots
                WHERE account_id = da.kuaishou_uid
                ORDER BY snapshot_date DESC LIMIT 1) AS health,
            (SELECT total_plays FROM daily_account_metrics
                WHERE kuaishou_uid = da.kuaishou_uid
                ORDER BY metric_date DESC LIMIT 1) AS plays,
            (SELECT total_likes FROM daily_account_metrics
                WHERE kuaishou_uid = da.kuaishou_uid
                ORDER BY metric_date DESC LIMIT 1) AS likes,
            (SELECT commission_rate FROM mcn_account_bindings
                WHERE kuaishou_uid = da.kuaishou_uid LIMIT 1) AS rate,
            (SELECT plan_type FROM mcn_account_bindings
                WHERE kuaishou_uid = da.kuaishou_uid LIMIT 1) AS plan
        FROM device_accounts da
        WHERE da.login_status = 'logged_in'
        ORDER BY health DESC NULLS LAST, plays DESC NULLS LAST
    """).fetchall()
    cols = ["id","name","uid","login","active","ks_name","health","plays","likes","rate","plan"]
    accounts = [dict(zip(cols, r)) for r in rows]
    db.close()
    return templates.TemplateResponse(request, "accounts.html", {
        "request": request, "nav": "accounts", "accounts": accounts,
    })


@app.get("/legacy/switches", response_class=HTMLResponse)
def legacy_switches(request: Request):
    return templates.TemplateResponse(request, "switches.html", {
        "request": request, "nav": "switches",
        "switches": get_all_switches(),
    })


@app.post("/legacy/switches/{code}/toggle")
def legacy_toggle_switch(code: str, value: str = Form(...)):
    on = value.lower() in ("on", "true", "1", "yes")
    set_switch(code, on, updated_by="legacy-dashboard")
    return RedirectResponse("/legacy/switches", status_code=303)


# ---------------------------------------------------------------------------
# SPA entry + catch-all
# ---------------------------------------------------------------------------

_SPA_INDEX = _SPA_DIST_DIR / "index.html"

_NO_CACHE_HEADERS = {
    "Cache-Control": "no-cache, no-store, must-revalidate",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.get("/__reset", response_class=HTMLResponse)
def reset_cache():
    """强制清浏览器缓存 + Service Worker + localStorage, 然后跳回主页.

    访问: http://127.0.0.1:8080/__reset
    """
    return HTMLResponse("""<!DOCTYPE html>
<html lang="zh-CN" class="dark">
<head>
<meta charset="UTF-8">
<title>清理浏览器缓存中...</title>
<meta http-equiv="Cache-Control" content="no-store">
<style>
body { margin:0; background:#0f1419; color:#e8eaed;
       font-family: system-ui, 'PingFang SC', sans-serif;
       display:flex; flex-direction:column; justify-content:center; align-items:center;
       height:100vh; }
h1 { color:#60d394; font-weight:normal; }
#log { font-family:monospace; font-size:12px; color:#a8b2bd;
       background:#1a1f27; padding:16px; border-radius:8px;
       min-width:400px; min-height:140px; }
.tip { color:#8a929c; font-size:12px; margin-top:20px; }
</style>
</head>
<body>
<h1>⚡ 正在清理浏览器缓存...</h1>
<pre id="log">🔄 启动中</pre>
<p class="tip">几秒后自动跳转到账号页</p>
<script>
(async () => {
  const log = document.getElementById('log');
  const p = (s) => { log.textContent += '\\n' + s; };
  try {
    if ('serviceWorker' in navigator) {
      const regs = await navigator.serviceWorker.getRegistrations();
      for (const r of regs) { await r.unregister(); }
      p('✓ Service Worker 已注销 (' + regs.length + ' 个)');
    }
  } catch(e) { p('⚠ SW: ' + e.message); }
  try {
    if ('caches' in window) {
      const keys = await caches.keys();
      for (const k of keys) { await caches.delete(k); }
      p('✓ Cache API 已清 (' + keys.length + ' 个)');
    }
  } catch(e) { p('⚠ caches: ' + e.message); }
  try {
    sessionStorage.clear();
    localStorage.clear();
    p('✓ localStorage / sessionStorage 已清');
  } catch(e) {}
  try {
    if (indexedDB && indexedDB.databases) {
      const dbs = await indexedDB.databases();
      for (const d of dbs) { indexedDB.deleteDatabase(d.name); }
      p('✓ IndexedDB 已清 (' + dbs.length + ' 个)');
    }
  } catch(e) {}
  p('');
  p('🚀 2 秒后跳转账号页 (带时间戳防缓存)');
  setTimeout(() => {
    location.replace('/accounts?_cb=' + Date.now());
  }, 2000);
})();
</script>
</body>
</html>""", headers=_NO_CACHE_HEADERS)


@app.get("/", response_class=HTMLResponse)
def spa_root():
    if _SPA_INDEX.exists():
        return FileResponse(_SPA_INDEX, headers=_NO_CACHE_HEADERS)
    # SPA 还没构建 — 展示引导页
    return HTMLResponse(
        """<!DOCTYPE html><html lang="zh-CN"><head><meta charset="UTF-8">
        <title>KS 矩阵运营中台 — 初始化中</title>
        <style>body{font-family:system-ui,-apple-system,sans-serif;
        background:#0f1419;color:#e8eaed;padding:40px;max-width:720px;margin:auto}
        h1{color:#60d394}code{background:#1a1f27;padding:2px 6px;border-radius:4px;
        color:#60d394}a{color:#60d394}</style></head><body>
        <h1>⚡ KS 矩阵运营中台 v0.2</h1>
        <p>SPA 前端尚未构建. 请执行:</p>
        <pre style="background:#1a1f27;padding:14px;border-radius:8px;color:#c8d1db">
cd D:\\ks_automation\\web
npm install
npm run build</pre>
        <p>旧版控制台仍可访问: <a href="/legacy">/legacy</a></p>
        <p>API 文档: <a href="/docs">/docs</a></p>
        </body></html>"""
    )


@app.get("/{full_path:path}")
def spa_catch_all(full_path: str):
    # 不拦 api/docs/legacy/static/assets
    for prefix in ("api/", "docs", "redoc", "openapi.json",
                   "legacy", "static/", "assets/"):
        if full_path.startswith(prefix):
            # 由其他 route 处理 — 这里返回 404 (FastAPI 会按 route 匹配顺序处理)
            from fastapi import HTTPException
            raise HTTPException(404)
    if _SPA_INDEX.exists():
        return FileResponse(_SPA_INDEX, headers=_NO_CACHE_HEADERS)
    return RedirectResponse("/", status_code=303)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  KS Automation Dashboard  v0.2")
    print("=" * 60)
    print("  SPA:       http://localhost:8080/")
    print("  API docs:  http://localhost:8080/docs")
    print("  Legacy:    http://localhost:8080/legacy")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=8080, log_level="warning")
