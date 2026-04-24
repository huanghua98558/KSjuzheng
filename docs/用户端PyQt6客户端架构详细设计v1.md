# 用户端 PyQt6 客户端架构详细设计

> **版本**: v1.0
> **出稿日期**: 2026-04-25
> **文档定位**: 补充 `客户端改造完整计划v2.md`, 专注**客户端工程架构 + 设计模式 + 运行机制**, 不重复 v2 已说的产品页面/Batch/接口契约.
>
> **配套文档**:
> - `docs/客户端改造完整计划v2.md` (产品 22 页 + Batch 节奏 + 兼容策略)
> - `docs/后端开发技术文档与接口规范v1.md` (API 契约)
> - `docs/服务器后端完整蓝图_含AI自动化v1.md` (后端架构)
> - `docs/产品总体规划.md` (战略 + 加固方案)
>
> **本文档讲什么**:
> 客户端**工程内部如何运转** — 进程模型 / 状态管理 / 异步线程 / 数据流 / 错误处理 / 安全 / 性能 / 打包. 这些是 v2.md 没展开的"工程深度"部分.

---

## 前言 · 阅读路径

```
v2.md           : 产品需求 + 5 Batch 节奏 + 文件清单
本文档          : 工程内部 + 模块详细设计 + 运行机制
后端 v1.md      : API 契约 (作为本文档的"外部边界")
后端蓝图 v1.md  : 后端架构 (作为整体系统的"另一半")
```

阅读建议: 先 v2 → 再本文档 → 再后端两份, 形成完整图景.

---

## 第一部分 · 客户端整体架构

### 1.1 6 层客户端架构

```
┌─────────────────────────────────────────────────────────┐
│ Layer 6  Presentation                                    │
│   pages/  widgets/  theme/                               │
│   QWidget 树 + QSS 样式                                   │
├─────────────────────────────────────────────────────────┤
│ Layer 5  ViewModel (页面级状态)                           │
│   每页一个 ViewModel, 持有页面状态 + 动作                  │
│   通过 Signal 通知 View                                   │
├─────────────────────────────────────────────────────────┤
│ Layer 4  Service (业务编排)                               │
│   services/  统一数据入口                                  │
│   缓存策略 / 错误转译 / 权限过滤                            │
├─────────────────────────────────────────────────────────┤
│ Layer 3  Transport (网络层)                               │
│   api_client.py  httpx + retry + envelope               │
│   token 注入 / 心跳 / 离线降级                             │
├─────────────────────────────────────────────────────────┤
│ Layer 2  Storage (本地数据)                               │
│   SQLCipher 加密 SQLite                                  │
│   QSettings 用户偏好 / Token 缓存                         │
├─────────────────────────────────────────────────────────┤
│ Layer 1  Foundation (基础设施)                            │
│   qt_compat / logger / event_bus / error_boundary       │
└─────────────────────────────────────────────────────────┘
```

**严格分层规则**:
- 上层可调下层, 下层不可调上层
- View 层 (Layer 6) **禁止**直接调 Service (Layer 4), 必经 ViewModel (Layer 5)
- ViewModel **禁止**直接调 ApiClient (Layer 3), 必经 Service (Layer 4)
- Service 可直接读 Storage (Layer 2), 用于缓存

### 1.2 进程模型

```
PyQt6 桌面端是单进程 + 多线程, 不是多进程:

┌────────────────────────────────────────────────────────┐
│ 主进程 (KS_Client.exe)                                   │
│                                                         │
│  ┌────────────────────────────┐                        │
│  │ Main Thread (UI 线程)        │                        │
│  │  - QApplication.exec()       │                        │
│  │  - 所有 widget 渲染            │                        │
│  │  - Signal/Slot 派发           │                        │
│  │  - 主事件循环                  │                        │
│  └────────────────────────────┘                        │
│                                                         │
│  ┌────────────────────────────┐                        │
│  │ Worker Thread Pool (QThreadPool)                     │
│  │  - HTTP 请求 (httpx async via QtAsync)               │
│  │  - 文件 I/O (大文件读写)                                │
│  │  - 数据加解密                                          │
│  │  - 计算密集 (排序/聚合)                                 │
│  └────────────────────────────┘                        │
│                                                         │
│  ┌────────────────────────────┐                        │
│  │ Heartbeat Thread             │                        │
│  │  - 每 5min 跑 1 次                                     │
│  │  - 失败 3 次降级模式                                    │
│  └────────────────────────────┘                        │
│                                                         │
│  ┌────────────────────────────┐                        │
│  │ Background Sync Thread       │                        │
│  │  - 缓存预热 (overview / accounts)                      │
│  │  - 视图缓存定时刷新                                     │
│  └────────────────────────────┘                        │
└────────────────────────────────────────────────────────┘
```

**关键约束**:
- 主线程**禁止任何阻塞** (网络 / 文件 / 数据库 > 50ms 必丢线程池)
- 所有线程间通信走 Signal/Slot (不用裸共享变量)
- httpx async 通过 `QtAsync` 适配 (qasync 库)

### 1.3 启动序列 (冷启动 → 进入首页)

```
T=0      QApplication() 创建
T+50ms   加载 theme/tokens + QSS (一次性, ~5MB)
T+100ms  显示 SplashScreen (Logo + 加载动画)
T+150ms  bootstrap.py 启动:
         - 读 QSettings / SQLCipher 解密本地 cache
         - 读 token + license_key
T+300ms  并行启动:
         ├─ ApiClient 构造 (httpx session)
         ├─ Heartbeat thread (后台)
         └─ ServiceContainer 初始化
T+500ms  首次 API:
         GET /api/client/license/status (2s timeout)
         GET /api/client/overview          (并行)
T+800ms  接收响应, 缓存 license/features
T+900ms  根据 plan 渲染 Sidebar (动态过滤菜单)
T+1.0s   切换到 MainWindow, 关闭 Splash
T+1.2s   首页显示完整数据, 启动后台缓存预热

总目标: < 3 秒 (慢网下 < 5 秒)
慢路径降级: 2s 接口超时则用 mock + 显"网络较慢"提示
```

---

## 第二部分 · 模块详细设计

### 2.1 main.py 启动入口

```python
# ui_client/app/main.py
import sys
import os
from ui_client.qt_compat import QApplication
from ui_client.app.bootstrap import bootstrap

def main():
    # 设置高 DPI
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    
    app = QApplication(sys.argv)
    app.setApplicationName("快手短剧矩阵")
    app.setOrganizationName("KsMatrix")
    app.setApplicationVersion(get_version())
    
    # 设置主题
    from ui_client.theme.theme_loader import apply_theme
    apply_theme(app, theme="dark_tech")
    
    # 安装全局错误边界
    from ui_client.app.error_boundary import install_global_handler
    install_global_handler()
    
    # 启动编排
    main_window = bootstrap(app)
    main_window.show()
    
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

### 2.2 bootstrap.py 启动编排

```python
# ui_client/app/bootstrap.py

def bootstrap(app: QApplication) -> MainWindow:
    """
    启动序列编排:
    1. 显示 Splash
    2. 加载本地配置和缓存
    3. 检查 token 状态
    4. 决定走 LoginPage 还是 MainWindow
    """
    splash = SplashScreen()
    splash.show()
    app.processEvents()
    
    # 1. 加载 QSettings + SQLCipher
    splash.update_status("加载本地配置...")
    storage = LocalStorage.instance()
    storage.unlock()
    
    # 2. 检查 token
    splash.update_status("验证登录状态...")
    token = storage.get_token()
    if not token or _is_token_expired(token):
        # 走登录或激活流程
        splash.close()
        login_window = LoginWindow()
        if not login_window.exec():
            sys.exit(0)
    
    # 3. 启动 ServiceContainer (DI 容器)
    splash.update_status("初始化服务...")
    container = ServiceContainer()
    container.register_all_services()
    
    # 4. 加载 license/features
    splash.update_status("加载用户信息...")
    license_status = container.license_service.fetch_status()
    container.permission_service.set_features(license_status.features)
    
    # 5. 启动后台 Worker
    HeartbeatWorker(container).start()
    BackgroundCacheWorker(container).start()
    
    # 6. 创建主窗口
    splash.update_status("启动界面...")
    main_window = MainWindow(container)
    main_window.set_initial_page("overview")
    
    splash.close()
    return main_window
```

### 2.3 ServiceContainer (依赖注入)

```python
# ui_client/app/container.py

class ServiceContainer:
    """单例 DI 容器, 管理所有 service 的生命周期"""
    
    _instance: Optional["ServiceContainer"] = None
    
    def __init__(self):
        self.api_client: ApiClient = None
        self.permission_service: PermissionService = None
        self.license_service: LicenseService = None
        self.overview_service: OverviewService = None
        self.accounts_service: AccountsService = None
        # ... 其他 services
    
    def register_all_services(self):
        # 顺序很重要: 底层先注册
        self.api_client = ApiClient(
            base_url=os.getenv("KS_API_BASE", "http://localhost:8080"),
            timeout=10,
        )
        self.permission_service = PermissionService()
        self.license_service = LicenseService(self.api_client)
        self.overview_service = OverviewService(self.api_client, self.permission_service)
        self.accounts_service = AccountsService(self.api_client, self.permission_service)
        # ...
    
    @classmethod
    def instance(cls) -> "ServiceContainer":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
```

**为什么用 DI**:
- 测试时可替换 ApiClient 为 MockApiClient
- 切 mock/real 模式只改容器
- 服务间依赖清晰, 不出现循环引用

### 2.4 路由系统 (QStackedWidget)

```python
# ui_client/pages/shell/main_window.py

class MainWindow(QMainWindow):
    page_changed = Signal(str)
    
    def __init__(self, container: ServiceContainer):
        super().__init__()
        self.container = container
        
        # 主布局: 左侧栏 + 中间内容 + 顶栏
        self.sidebar = Sidebar(container.permission_service)
        self.topbar = TopBar(container.license_service)
        self.stack = QStackedWidget()
        
        # 页面注册表 (lazy 实例化)
        self._page_registry: dict[str, type] = {
            "overview":         OverviewPage,
            "accounts":         AccountsPage,
            "dramas":           DramasPage,
            "publish":          PublishPage,
            "publish_results":  PublishResultsPage,
            "revenue":          RevenuePage,
            "exceptions":       ExceptionsPage,
            "config":           ConfigCenterPage,
            "subscription":     SubscriptionPage,
            # PRO+
            "burst_radar":      BurstRadarPage,
            "ai_advice":        AiAdvicePage,
            "autopilot":        AutoPilotPage,
            "risk":             RiskCenterPage,
            # TEAM
            "team_dashboard":   TeamDashboardPage,
            "members":          MembersPage,
            "experiments":      ExperimentsPage,
            "runs":             RunRecordsPage,
            "agents":           AgentsViewPage,
            "export":           DataExportPage,
            "account_ops":      AccountOpsPage,
        }
        
        self._page_instances: dict[str, BasePage] = {}
        
        # Sidebar 点击 → 切页
        self.sidebar.menu_clicked.connect(self.navigate_to)
    
    def navigate_to(self, page_key: str):
        # 权限校验
        if not self.container.permission_service.can_access_page(page_key):
            self._show_feature_lock(page_key)
            return
        
        # 懒加载实例化
        if page_key not in self._page_instances:
            page_cls = self._page_registry[page_key]
            page = page_cls(self.container)
            self._page_instances[page_key] = page
            self.stack.addWidget(page)
        
        # 切换
        page = self._page_instances[page_key]
        page.on_enter()  # 生命周期钩子: 拉数据
        self.stack.setCurrentWidget(page)
        self.page_changed.emit(page_key)
    
    def _show_feature_lock(self, page_key: str):
        """显示锁定卡, 引导升级"""
        from ui_client.widgets.feature_lock_card import FeatureLockDialog
        dlg = FeatureLockDialog(page_key, parent=self)
        dlg.exec()
```

### 2.5 BasePage 生命周期

```python
# ui_client/pages/base_page.py

class BasePage(QWidget):
    """所有页面基类, 统一生命周期"""
    
    # 共享 Signal
    error_occurred = Signal(str, str)  # error_code, message
    loading_changed = Signal(bool)
    
    REQUIRED_FEATURE: Optional[str] = None  # 页面需要的 FEATURE_*
    
    def __init__(self, container: ServiceContainer):
        super().__init__()
        self.container = container
        self.viewmodel = self._create_viewmodel()
        self._connect_signals()
        self._setup_ui()
    
    def _create_viewmodel(self):
        """子类 override, 返回页面 ViewModel"""
        raise NotImplementedError
    
    def _connect_signals(self):
        """建 ViewModel ↔ View 信号连接"""
        self.viewmodel.data_changed.connect(self._render)
        self.viewmodel.error_occurred.connect(self.error_occurred.emit)
        self.viewmodel.loading_changed.connect(self.loading_changed.emit)
    
    def _setup_ui(self):
        """子类 override, 建 widget 树"""
        raise NotImplementedError
    
    def _render(self, data):
        """子类 override, 数据 → UI 渲染"""
        raise NotImplementedError
    
    # ━━━ 生命周期钩子 ━━━
    
    def on_enter(self):
        """页面被切换到时调用 (用于拉数据)"""
        self.viewmodel.refresh()
    
    def on_leave(self):
        """页面被切换走时调用 (用于停止 timer)"""
        self.viewmodel.stop_polling()
    
    def on_close(self):
        """页面销毁时调用"""
        self.viewmodel.cleanup()
```

### 2.6 ViewModel 模式

```python
# ui_client/pages/pro/overview_viewmodel.py

class OverviewViewModel(QObject):
    """首页 ViewModel: 持有数据 + 暴露动作"""
    
    # 状态变化 Signal
    data_changed = Signal(dict)
    loading_changed = Signal(bool)
    error_occurred = Signal(str, str)
    
    # 模式切换 (PRO+)
    mode_changed = Signal(str)  # "auto" | "manual"
    
    def __init__(self, overview_service: OverviewService):
        super().__init__()
        self._service = overview_service
        self._data: dict = {}
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self.refresh)
    
    @Slot()
    def refresh(self):
        """异步刷新数据"""
        self.loading_changed.emit(True)
        worker = AsyncWorker(self._service.fetch_overview)
        worker.success.connect(self._on_loaded)
        worker.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(worker)
    
    @Slot(dict)
    def _on_loaded(self, data: dict):
        self._data = data
        self.loading_changed.emit(False)
        self.data_changed.emit(data)
    
    @Slot(str, str)
    def _on_failed(self, code: str, message: str):
        self.loading_changed.emit(False)
        self.error_occurred.emit(code, message)
    
    @Slot(str)
    def switch_mode(self, mode: str):
        """切 auto/manual 模式 (PRO+)"""
        worker = AsyncWorker(lambda: self._service.set_mode(mode))
        worker.success.connect(lambda r: self.mode_changed.emit(mode))
        worker.failed.connect(self._on_failed)
        QThreadPool.globalInstance().start(worker)
    
    def start_polling(self, interval_sec: int = 30):
        self._refresh_timer.start(interval_sec * 1000)
    
    def stop_polling(self):
        self._refresh_timer.stop()
    
    def cleanup(self):
        self.stop_polling()
        self.deleteLater()
```

**ViewModel 设计原则**:
- 不持有 widget 引用 (单向: VM → View, View ← VM 通过 Signal)
- 所有状态变化经 Signal 通知 (便于 UI 重渲染)
- 异步操作走 Worker, **不阻塞主线程**
- 提供 `cleanup()` 释放资源

---

## 第三部分 · 服务层架构

### 3.1 Service 模式

```python
# ui_client/services/overview_service.py

class OverviewService:
    """业务 Service, 包装 ApiClient + 缓存 + 错误转译"""
    
    def __init__(
        self,
        api: ApiClient,
        permission: PermissionService,
        cache: CacheManager = None,
    ):
        self._api = api
        self._permission = permission
        self._cache = cache or CacheManager.instance()
    
    def fetch_overview(self) -> OverviewData:
        # 1. 缓存优先 (10s SWR — stale while revalidate)
        cached = self._cache.get("overview", max_age_sec=10)
        if cached:
            # 立即返缓存, 同时后台刷新
            self._refresh_in_background()
            return cached
        
        # 2. 真正请求
        try:
            envelope = self._api.get("/api/client/overview")
            
            if not envelope.ok:
                raise ServiceError(envelope.error.code, envelope.error.message)
            
            # 3. 数据转换 (按 plan 过滤字段)
            data = self._adapt_for_plan(envelope.data)
            
            # 4. 写缓存
            self._cache.set("overview", data, ttl_sec=10)
            return data
        
        except (NetworkError, TimeoutError) as e:
            # 离线降级: 用过期缓存
            stale = self._cache.get("overview", max_age_sec=3600, allow_stale=True)
            if stale:
                stale["_stale"] = True
                return stale
            raise
    
    def set_mode(self, mode: str) -> bool:
        envelope = self._api.post(
            "/api/client/overview/mode",
            json={"mode": mode},
            idempotency_key=str(uuid4()),
        )
        # 失效缓存
        self._cache.invalidate("overview")
        return envelope.ok
    
    def _adapt_for_plan(self, raw: dict) -> dict:
        """按 plan 过滤字段 (后端已过滤一遍, 前端兜底)"""
        plan = self._permission.current_plan()
        if plan == "manual":
            # 移除 PRO/TEAM 字段
            raw.pop("autopilot", None)
            raw.pop("ai_advice_summary", None)
        return raw
```

### 3.2 ApiClient 实现

```python
# ui_client/services/api_client.py

class ApiClient:
    """HTTP 客户端, 封装 httpx + retry + envelope + auth"""
    
    def __init__(self, base_url: str, timeout: float = 10.0):
        self._base = base_url
        self._timeout = timeout
        self._session = httpx.Client(
            base_url=base_url,
            timeout=timeout,
            limits=httpx.Limits(max_connections=20),
            transport=httpx.HTTPTransport(retries=2),
        )
        self._token: Optional[str] = None
        self._license_key: Optional[str] = None
        self._fingerprint: Optional[str] = None
    
    def set_auth(self, token: str, license_key: str, fingerprint: str):
        self._token = token
        self._license_key = license_key
        self._fingerprint = fingerprint
    
    def get(self, path: str, params: dict = None) -> Envelope:
        return self._request("GET", path, params=params)
    
    def post(self, path: str, json: dict = None,
             idempotency_key: str = None) -> Envelope:
        headers = {}
        if idempotency_key:
            headers["Idempotency-Key"] = idempotency_key
        return self._request("POST", path, json=json, headers=headers)
    
    def _request(
        self, method: str, path: str,
        params: dict = None, json: dict = None,
        headers: dict = None,
    ) -> Envelope:
        # 构造请求
        h = self._default_headers()
        if headers:
            h.update(headers)
        
        try:
            resp = self._session.request(
                method, path,
                params=params, json=json, headers=h,
            )
        except httpx.ConnectError:
            raise NetworkError("无法连接到服务器, 请检查网络")
        except httpx.ReadTimeout:
            raise TimeoutError("请求超时, 请重试")
        
        # 解析 Envelope
        try:
            data = resp.json()
        except json.JSONDecodeError:
            raise ApiError("INVALID_RESPONSE", "服务器响应格式错误")
        
        envelope = Envelope.from_dict(data)
        
        # 自动处理特定错误
        if not envelope.ok:
            code = envelope.error.code
            
            if code == "AUTH_401":
                # 自动 refresh + 重试
                if self._try_refresh_token():
                    return self._request(method, path, params, json, headers)
                else:
                    EventBus.emit("logout_required")
                    raise AuthError(code, envelope.error.message)
            
            elif code == "AUTH_402":
                EventBus.emit("subscription_expired", envelope.error.message)
                raise AuthError(code, envelope.error.message)
            
            elif code == "AUTH_403":
                # 不抛, 让 Service 决定显锁卡
                raise FeatureLockedError(code, envelope.error.message)
            
            elif code == "RATE_LIMIT_429":
                retry_after = int(resp.headers.get("Retry-After", 60))
                raise RateLimitError(code, envelope.error.message, retry_after)
            
            else:
                raise ServiceError(code, envelope.error.message)
        
        return envelope
    
    def _default_headers(self) -> dict:
        h = {
            "Content-Type": "application/json; charset=utf-8",
            "X-Client-Version": __version__,
            "X-Client-Timezone": "Asia/Shanghai",
        }
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        if self._license_key:
            h["X-License-Key"] = self._license_key
        if self._fingerprint:
            h["X-Device-Fingerprint"] = self._fingerprint
        return h
    
    def _try_refresh_token(self) -> bool:
        """JWT 过期时自动 refresh"""
        refresh_token = LocalStorage.instance().get_refresh_token()
        if not refresh_token:
            return False
        
        try:
            resp = self._session.post(
                "/api/client/auth/refresh",
                json={
                    "refresh_token": refresh_token,
                    "fingerprint": self._fingerprint,
                },
            )
            if resp.status_code != 200:
                return False
            
            data = resp.json()
            if not data.get("ok"):
                return False
            
            new_token = data["data"]["token"]
            new_refresh = data["data"]["refresh_token"]
            self._token = new_token
            LocalStorage.instance().save_tokens(new_token, new_refresh)
            return True
        except Exception:
            return False
```

### 3.3 缓存策略 (CacheManager)

```python
# ui_client/services/cache_manager.py

class CacheManager:
    """两层缓存: 内存 + 磁盘 (SQLCipher)"""
    
    _instance: Optional["CacheManager"] = None
    
    def __init__(self):
        self._memory: dict[str, CacheEntry] = {}
        self._disk = LocalStorage.instance().cache_db
    
    @classmethod
    def instance(cls) -> "CacheManager":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    def get(
        self, key: str,
        max_age_sec: int = 60,
        allow_stale: bool = False,
    ) -> Optional[Any]:
        # 1. 内存 cache
        entry = self._memory.get(key)
        if entry and entry.is_fresh(max_age_sec):
            return entry.value
        if entry and allow_stale:
            return entry.value
        
        # 2. 磁盘 cache
        disk_entry = self._disk.get_cache(key)
        if disk_entry and disk_entry.is_fresh(max_age_sec):
            self._memory[key] = disk_entry
            return disk_entry.value
        if disk_entry and allow_stale:
            return disk_entry.value
        
        return None
    
    def set(self, key: str, value: Any, ttl_sec: int = 60):
        entry = CacheEntry(key, value, ts=time.time(), ttl=ttl_sec)
        self._memory[key] = entry
        self._disk.put_cache(key, entry)
    
    def invalidate(self, key: str):
        self._memory.pop(key, None)
        self._disk.delete_cache(key)
    
    def invalidate_pattern(self, pattern: str):
        """e.g. 'accounts.*' 失效所有账号相关缓存"""
        for key in list(self._memory.keys()):
            if fnmatch.fnmatch(key, pattern):
                self._memory.pop(key)
        self._disk.delete_cache_pattern(pattern)
```

**缓存策略汇总**:

| 数据 | 内存 TTL | 磁盘 TTL | SWR | 离线时长 |
|---|---|---|---|---|
| `license_status` | 60s | 24h | ✓ | 24h |
| `overview` | 10s | 30 分 | ✓ | 30 分 |
| `accounts` (列表) | 30s | 1h | ✓ | 1h |
| `dramas` | 5min | 24h | ✓ | 24h |
| `revenue` | 30s | 30 分 | ✓ | 30 分 |
| `config_values` | 5min | 永久 | ✗ | 永久 |
| 写操作后 | 立即失效 | 立即失效 | - | - |

### 3.4 离线模式

```python
# ui_client/services/offline_manager.py

class OfflineManager:
    """离线模式管理器"""
    
    def __init__(self):
        self._heartbeat_failures = 0
        self._last_online_at: float = time.time()
        self._mode: str = "online"  # online | degraded | offline
    
    def on_heartbeat_failed(self):
        self._heartbeat_failures += 1
        elapsed = time.time() - self._last_online_at
        
        if self._heartbeat_failures >= 3 and self._mode == "online":
            self._mode = "degraded"
            EventBus.emit("offline_mode_changed", "degraded")
            # UI 显示 "网络问题, 正在重连"
        
        if elapsed > 300 and self._mode == "degraded":  # 5 分钟
            self._mode = "offline"
            EventBus.emit("offline_mode_changed", "offline")
            # 禁用写操作, 仅可读 cache
        
        if elapsed > 1800:  # 30 分钟
            EventBus.emit("offline_lockdown")
            # 锁定 UI, 强制重连
    
    def on_heartbeat_success(self):
        self._heartbeat_failures = 0
        self._last_online_at = time.time()
        if self._mode != "online":
            self._mode = "online"
            EventBus.emit("offline_mode_changed", "online")
            # 触发 outbox replay
            OutboxReplayer.instance().replay_all()
```

**离线写操作处理**:

```python
class WriteOutbox:
    """离线时缓存写操作, 上线后 replay"""
    
    def enqueue(self, request: PendingRequest):
        """缓存待发送的写请求"""
        idempotency_key = str(uuid4())
        request.idempotency_key = idempotency_key
        self._db.insert_pending(request)
    
    def replay_all(self):
        """网络恢复后, 按时间顺序 replay"""
        pending = self._db.list_pending()
        for req in pending:
            try:
                api_client.request(
                    req.method, req.path,
                    json=req.body,
                    idempotency_key=req.idempotency_key,
                )
                self._db.mark_completed(req.id)
            except Exception:
                # replay 失败, 留待下次
                break
```

---

## 第四部分 · 异步与并发

### 4.1 AsyncWorker 模式

```python
# ui_client/utils/async_worker.py

class AsyncWorker(QRunnable):
    """通用异步任务执行器"""
    
    def __init__(self, fn: Callable, *args, **kwargs):
        super().__init__()
        self._fn = fn
        self._args = args
        self._kwargs = kwargs
        self.signals = WorkerSignals()
    
    @property
    def success(self) -> Signal:
        return self.signals.success
    
    @property
    def failed(self) -> Signal:
        return self.signals.failed
    
    @Slot()
    def run(self):
        try:
            result = self._fn(*self._args, **self._kwargs)
            self.signals.success.emit(result)
        except FeatureLockedError as e:
            self.signals.failed.emit(e.code, e.message)
        except ServiceError as e:
            self.signals.failed.emit(e.code, e.message)
        except Exception as e:
            logger.exception("AsyncWorker fn failed")
            self.signals.failed.emit("INTERNAL_500", "操作失败, 请稍后重试")


class WorkerSignals(QObject):
    success = Signal(object)
    failed = Signal(str, str)  # error_code, message
    progress = Signal(int)     # 0-100
```

**使用场景**:
```python
# ViewModel 里
@Slot()
def refresh(self):
    self.loading_changed.emit(True)
    worker = AsyncWorker(self._service.fetch_data)
    worker.success.connect(self._on_loaded)
    worker.failed.connect(self._on_failed)
    QThreadPool.globalInstance().start(worker)
```

### 4.2 长任务进度反馈

```python
class ProgressWorker(AsyncWorker):
    """支持进度反馈的 Worker"""
    
    def run(self):
        try:
            def report_progress(pct: int):
                self.signals.progress.emit(pct)
            
            result = self._fn(
                *self._args,
                on_progress=report_progress,
                **self._kwargs,
            )
            self.signals.success.emit(result)
        except Exception as e:
            self.signals.failed.emit("INTERNAL_500", str(e))


# 业务侧
class ExportService:
    def export_xlsx(self, data: list, on_progress=None) -> str:
        total = len(data)
        for i, row in enumerate(data):
            # 写一行
            ...
            if on_progress and i % 100 == 0:
                on_progress(int(i / total * 100))
        return file_path
```

### 4.3 防 UI 卡顿规则

```
主线程禁止:
  ✗ httpx 同步请求 (必须丢 worker)
  ✗ 大文件读写 (必须丢 worker)
  ✗ JSON 解析 > 1MB (必须丢 worker)
  ✗ Pandas 计算 (必须丢 worker)
  ✗ ffmpeg 调用 (虽然客户端不做, 但禁止)

主线程允许:
  ✓ Widget 渲染
  ✓ Signal/Slot 派发
  ✓ Cache.get_memory (仅内存)
  ✓ 简单计算 < 50ms

判断标准:
  任何可能 > 50ms 的操作 → AsyncWorker
  Widget 数量 > 1000 个 → 用 QStandardItemModel + delegate
  表格行数 > 100 → 启用虚拟滚动 (QAbstractItemView.setUniformItemSizes)
```

### 4.4 取消机制

```python
class CancellableWorker(AsyncWorker):
    """可取消的 Worker"""
    
    def __init__(self, fn, *args, **kwargs):
        super().__init__(fn, *args, **kwargs)
        self._cancel_token = CancelToken()
        self._kwargs["cancel_token"] = self._cancel_token
    
    def cancel(self):
        self._cancel_token.cancel()


# 业务侧
def export_xlsx(data, cancel_token: CancelToken = None):
    for i, row in enumerate(data):
        if cancel_token and cancel_token.is_cancelled:
            raise CancelledError()
        # ...
```

---

## 第五部分 · 主题与设计系统

### 5.1 Design Tokens (`theme/tokens.py`)

> 详见 `客户端改造完整计划v2.md` §6. 不重复.

### 5.2 QSS 模板系统

```python
# ui_client/theme/theme_loader.py

def apply_theme(app: QApplication, theme: str = "dark_tech"):
    """加载并应用主题"""
    from ui_client.theme import tokens
    
    # 读取 QSS 模板
    qss_files = ["base.qss", "components.qss", "typography.qss"]
    qss_content = ""
    for f in qss_files:
        path = Path(__file__).parent / f"{theme}_{f}"
        qss_content += path.read_text(encoding="utf-8") + "\n"
    
    # 替换 {{ TOKEN }} 占位符
    rendered = render_qss_template(qss_content, tokens.__dict__)
    
    app.setStyleSheet(rendered)


def render_qss_template(template: str, tokens_dict: dict) -> str:
    """简易模板引擎: {{ COLOR_PANEL }} → 'rgb(...)'"""
    import re
    def replace(m):
        var_name = m.group(1).strip()
        value = tokens_dict.get(var_name, "")
        if isinstance(value, int):
            return f"{value}px"
        return str(value)
    return re.sub(r"\{\{\s*(\w+)\s*\}\}", replace, template)
```

QSS 模板示例:

```css
/* ui_client/theme/dark_tech_components.qss */

QPushButton {
    background-color: {{ COLOR_ACCENT }};
    color: {{ COLOR_TEXT_PRIMARY }};
    border: none;
    border-radius: {{ RADIUS_BUTTON }};
    padding: {{ SPACE_2 }} {{ SPACE_4 }};
    font-size: {{ FONT_SIZE_MD }};
}

QPushButton:hover {
    background-color: rgba(47, 128, 237, 0.85);
}

QPushButton:pressed {
    background-color: rgba(47, 128, 237, 0.7);
}

QFrame[role="card"] {
    background-color: {{ COLOR_PANEL }};
    border: 1px solid {{ COLOR_BORDER }};
    border-radius: {{ RADIUS_CARD }};
    padding: {{ SPACE_4 }};
}

KpiCard QLabel[role="kpi-value"] {
    color: {{ COLOR_TEXT_PRIMARY }};
    font-size: {{ FONT_SIZE_XXL }};
    font-weight: 600;
}
```

### 5.3 主题切换 (Phase 2+)

```python
class ThemeManager:
    AVAILABLE = ["dark_tech", "light", "auto"]
    
    def __init__(self, app: QApplication):
        self._app = app
        self._current = "dark_tech"
    
    def switch(self, theme: str):
        if theme == "auto":
            theme = self._detect_system_theme()
        if theme == self._current:
            return
        apply_theme(self._app, theme)
        self._current = theme
        QSettings().setValue("ui.theme", theme)
        EventBus.emit("theme_changed", theme)
    
    def _detect_system_theme(self) -> str:
        # Windows: 读注册表 AppsUseLightTheme
        ...
```

### 5.4 自定义控件

参考 v2.md §3.1 widgets 列表. 重点说几个:

```python
# ui_client/widgets/kpi_card.py

class KpiCard(QFrame):
    """KPI 卡片, 单个数值 + 标签 + 趋势"""
    
    clicked = Signal()
    
    def __init__(
        self,
        label: str,
        value: str = "",
        change_pct: float = None,  # 同比/环比
        icon: str = None,
        color: str = None,
        clickable: bool = False,
    ):
        super().__init__()
        self.setProperty("role", "card")
        self._setup_ui(label, value, change_pct, icon, color)
        if clickable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
            self.mousePressEvent = lambda e: self.clicked.emit()
    
    def _setup_ui(self, label, value, change_pct, icon, color):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        
        # 顶部: 标签 + icon
        top = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setProperty("role", "kpi-label")
        top.addWidget(lbl)
        if icon:
            ic = QLabel(icon)
            ic.setProperty("role", "kpi-icon")
            top.addWidget(ic)
        layout.addLayout(top)
        
        # 数值
        self.value_label = QLabel(str(value))
        self.value_label.setProperty("role", "kpi-value")
        if color:
            self.value_label.setStyleSheet(f"color: {color}")
        layout.addWidget(self.value_label)
        
        # 变化率
        if change_pct is not None:
            arrow = "↑" if change_pct > 0 else "↓"
            change_lbl = QLabel(f"{arrow} {abs(change_pct):.1f}%")
            color = "#27AE60" if change_pct > 0 else "#EB5757"
            change_lbl.setStyleSheet(f"color: {color}")
            layout.addWidget(change_lbl)
    
    def update_value(self, value: str):
        self.value_label.setText(str(value))
```

---

## 第六部分 · 错误处理与恢复

### 6.1 全局错误边界

```python
# ui_client/app/error_boundary.py

import sys
import traceback
from ui_client.qt_compat import QApplication, QMessageBox

def install_global_handler():
    """安装未捕获异常的全局 handler"""
    def excepthook(exc_type, exc_value, exc_traceback):
        # 1. 记日志
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_traceback),
        )
        
        # 2. 上报到服务器 (best effort)
        try:
            CrashReporter.report(exc_type, exc_value, exc_traceback)
        except Exception:
            pass
        
        # 3. 显示友好对话框
        QMessageBox.critical(
            None,
            "程序遇到问题",
            f"很抱歉, 程序出了问题. 错误信息已上报, 我们会尽快修复.\n\n"
            f"如需立即支持, 请提供 Trace ID: {get_current_trace_id()}",
            QMessageBox.StandardButton.Ok,
        )
        
        # 4. 选择性退出 or 继续
        sys.exit(1)
    
    sys.excepthook = excepthook
```

### 6.2 错误用户反馈层级

```
Level 1 (最严重): 全局崩溃
  → QMessageBox.critical + 退出
  → 上报 trace + 堆栈
  
Level 2 (业务严重): AUTH_402 (套餐过期) / AUTH_423 (账号锁)
  → 阻塞对话框, 必须用户操作
  → 跳转相应页面 (订阅 / 客服)

Level 3 (业务警告): AUTH_403 (功能锁) / BUSINESS_BLACKLIST
  → 内联 FeatureLockCard / 状态提示
  → 不阻塞, 用户可继续

Level 4 (操作失败): VALIDATION_422 / RATE_LIMIT_429
  → Toast 通知 (右上角, 5 秒消失)
  → 记入日志, 不上报

Level 5 (轻微): 网络波动 / cache miss
  → 静默重试, 不打扰用户
```

### 6.3 Toast 通知系统

```python
# ui_client/widgets/toast.py

class ToastManager(QObject):
    """全局 Toast 管理器"""
    
    _instance: Optional["ToastManager"] = None
    
    def __init__(self, parent: QMainWindow):
        super().__init__(parent)
        self._parent = parent
        self._queue: list[ToastMessage] = []
        self._showing = False
    
    @classmethod
    def show(cls, level: str, title: str, message: str = "", duration: int = 5000):
        """level: info | success | warning | error"""
        instance = cls._instance
        if not instance:
            return
        instance._queue.append(ToastMessage(level, title, message, duration))
        instance._show_next()
    
    def _show_next(self):
        if self._showing or not self._queue:
            return
        msg = self._queue.pop(0)
        toast = ToastWidget(msg, parent=self._parent)
        toast.show_animated()
        self._showing = True
        QTimer.singleShot(msg.duration, lambda: self._on_dismissed(toast))
    
    def _on_dismissed(self, toast):
        toast.hide_animated()
        self._showing = False
        self._show_next()


# 业务侧使用
ToastManager.show("error", "网络错误", "请检查网络连接", duration=3000)
ToastManager.show("success", "已保存")
```

### 6.4 崩溃恢复

```python
# ui_client/app/crash_recovery.py

class CrashRecovery:
    """崩溃后下次启动时恢复状态"""
    
    SESSION_FILE = "session.json"
    
    @staticmethod
    def save_session(state: dict):
        """每分钟保存一次会话"""
        path = LocalStorage.get_path(CrashRecovery.SESSION_FILE)
        path.write_text(json.dumps({
            "ts": time.time(),
            "current_page": state.get("current_page"),
            "pending_writes": state.get("pending_writes", []),
            # 不保存敏感数据
        }), encoding="utf-8")
    
    @staticmethod
    def restore_session() -> Optional[dict]:
        """启动时调用, 检查上次会话"""
        path = LocalStorage.get_path(CrashRecovery.SESSION_FILE)
        if not path.exists():
            return None
        try:
            session = json.loads(path.read_text(encoding="utf-8"))
            if time.time() - session["ts"] > 3600:
                return None  # 1 小时前的会话不恢复
            return session
        except Exception:
            return None
```

---

## 第七部分 · 本地数据与安全

### 7.1 LocalStorage (SQLCipher 加密 SQLite)

```python
# ui_client/storage/local_storage.py

class LocalStorage:
    """本地数据存储, SQLCipher 加密"""
    
    _instance: Optional["LocalStorage"] = None
    
    DB_PATH = Path.home() / ".ks-matrix" / "client.db"
    KEY_DERIVATION_SALT = b"ks-matrix-salt-v1"
    
    def __init__(self):
        self._conn: Optional[sqlcipher.Connection] = None
    
    def unlock(self):
        """启动时调用, 解密 db"""
        if self._conn:
            return
        
        # 派生密钥: 基于硬件指纹 (不可移植)
        from ui_client.security.fingerprint import get_fingerprint
        fp = get_fingerprint()
        key = hashlib.pbkdf2_hmac(
            "sha256",
            fp.encode(),
            self.KEY_DERIVATION_SALT,
            iterations=100000,
        ).hex()
        
        self.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlcipher.connect(str(self.DB_PATH))
        self._conn.execute(f"PRAGMA key = '{key}'")
        self._conn.execute("PRAGMA cipher_compatibility = 4")
        self._init_schema()
    
    def _init_schema(self):
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS auth (
                key TEXT PRIMARY KEY,
                value TEXT,
                updated_at TIMESTAMP
            );
            CREATE TABLE IF NOT EXISTS cache (
                key TEXT PRIMARY KEY,
                value BLOB,
                ttl_sec INTEGER,
                stored_at REAL
            );
            CREATE TABLE IF NOT EXISTS outbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                method TEXT,
                path TEXT,
                body TEXT,
                idempotency_key TEXT,
                created_at TIMESTAMP,
                status TEXT DEFAULT 'pending'
            );
            CREATE TABLE IF NOT EXISTS audit_local (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action TEXT,
                target TEXT,
                at TIMESTAMP
            );
        """)
        self._conn.commit()
    
    # Token 管理
    def save_tokens(self, jwt: str, refresh: str):
        self._set_auth("jwt", jwt)
        self._set_auth("refresh_token", refresh)
    
    def get_token(self) -> Optional[str]:
        return self._get_auth("jwt")
    
    def get_refresh_token(self) -> Optional[str]:
        return self._get_auth("refresh_token")
    
    def clear_auth(self):
        self._conn.execute("DELETE FROM auth")
        self._conn.commit()
    
    def _set_auth(self, k: str, v: str):
        self._conn.execute(
            "INSERT OR REPLACE INTO auth(key, value, updated_at) VALUES(?, ?, ?)",
            (k, v, datetime.now().isoformat()),
        )
        self._conn.commit()
    
    def _get_auth(self, k: str) -> Optional[str]:
        row = self._conn.execute(
            "SELECT value FROM auth WHERE key = ?", (k,)
        ).fetchone()
        return row[0] if row else None
```

### 7.2 硬件指纹生成

```python
# ui_client/security/fingerprint.py
import hashlib
import platform
import subprocess
import wmi  # Windows 专用

def get_fingerprint() -> str:
    """生成硬件指纹 (Windows)"""
    components = []
    
    # CPU ID
    try:
        c = wmi.WMI()
        for cpu in c.Win32_Processor():
            components.append(cpu.ProcessorId.strip())
            break
    except Exception:
        components.append("cpu-unknown")
    
    # 主板 SN
    try:
        for board in c.Win32_BaseBoard():
            components.append(board.SerialNumber.strip())
            break
    except Exception:
        components.append("mb-unknown")
    
    # 系统盘 SN
    try:
        for disk in c.Win32_PhysicalMedia():
            if disk.SerialNumber:
                components.append(disk.SerialNumber.strip())
                break
    except Exception:
        components.append("disk-unknown")
    
    # 排序后哈希 (避免顺序不一致)
    sorted_str = "|".join(sorted(components))
    return hashlib.sha256(sorted_str.encode()).hexdigest()[:32]
```

**指纹规则** (对齐后端 v1.md §3):
- 不用 MAC 地址 (易篡改)
- 不用计算机名 (易修改)
- 不用 IP (会变化)
- 服务端只存 sha256[:32], 不存原始组件 ID

### 7.3 反调试 (Phase 4 加固)

```
Phase 1-3 (开发期): 不做反调试 (便于自己调试)

Phase 4 (发售): Rust .pyd 实现反调试
  - IsDebuggerPresent
  - PEB.BeingDebugged
  - RDTSC 时间差检测
  - NtQueryInformationProcess

  触发后:
    ✗ 不弹窗 (告诉攻击者哪层触发了)
    ✓ 静默上报到服务器
    ✓ 延迟 30 秒后 abort()
    ✓ 表现为"软件 bug"
```

### 7.4 内存敏感数据清理

```python
# ui_client/security/secure_memory.py

class SecureString:
    """敏感字符串, 使用后立即清零"""
    
    def __init__(self, value: str):
        self._buffer = bytearray(value, "utf-8")
        self._cleared = False
    
    def get(self) -> str:
        if self._cleared:
            raise RuntimeError("Already cleared")
        return self._buffer.decode("utf-8")
    
    def clear(self):
        if not self._cleared:
            for i in range(len(self._buffer)):
                self._buffer[i] = 0
            self._cleared = True
    
    def __del__(self):
        self.clear()


# 使用
password = SecureString(user_input)
api_client.login(password.get())
password.clear()  # 立即清零
```

---

## 第八部分 · 性能优化

### 8.1 启动优化目标

```
T+1.0s   主窗口可见
T+1.5s   首页 KPI 显示
T+3.0s   完全可交互
```

**优化手段**:

```python
1. 延迟加载页面 (lazy):
   - 启动只创建 OverviewPage
   - 其他 21 页用户点击时才创建
   - 节省 ~80% 内存 + 启动时间

2. QSS 预编译:
   - 第一次启动渲染 QSS, 之后缓存到 .qss.cache
   - 节省 100ms

3. 并行 API:
   - license/status + overview 并发请求
   - 不串行等

4. 字体预加载:
   - bootstrap 阶段预热常用字体
   - 避免第一次渲染时卡

5. 图标 SVG → 缓存 QPixmap:
   - 启动时预渲染常用图标
```

### 8.2 大表格 (虚拟滚动)

```python
# 账号管理页可能 1000+ 行
# 普通 QTableWidget 会卡

# 错: QTableWidget (DOM 全渲染)
# 对: QTableView + QAbstractTableModel (虚拟滚动)

class AccountsModel(QAbstractTableModel):
    def __init__(self, accounts: list):
        super().__init__()
        self._data = accounts  # 即使 10k 行也不渲染全部
    
    def rowCount(self, parent=QModelIndex()):
        return len(self._data)
    
    def columnCount(self, parent=QModelIndex()):
        return 8
    
    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if role == Qt.ItemDataRole.DisplayRole:
            row = self._data[index.row()]
            col = index.column()
            return self._format_cell(row, col)


# View 配置
table_view = QTableView()
table_view.setUniformRowHeights(True)  # ★ 关键, 启用虚拟滚动
table_view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
```

### 8.3 图表性能

```
pyqtgraph 配置:
  - useOpenGL=True       (启用 OpenGL 加速)
  - antialias=False      (抗锯齿吃 CPU)
  - downsample=auto      (大数据自动降采样)

数据量 > 10k 点:
  - 启用 LOD (Level of Detail)
  - 用 PlotDataItem 而非 ScatterPlotItem (后者每点都画)

实时刷新:
  - 用 setData() 替代 plot() (避免重建)
  - 限制刷新频率 (10 Hz 已够)
```

### 8.4 懒加载策略

```python
# 配置中心 12 Tab 全部在首次进入时加载?
# → 错, 单 Tab 加载, 切到才加载

class ConfigCenterPage(BasePage):
    def __init__(self, container):
        super().__init__(container)
        self._tab_loaded: dict[str, bool] = {}
        self._tabs.currentChanged.connect(self._on_tab_changed)
    
    @Slot(int)
    def _on_tab_changed(self, index: int):
        tab_key = self._tab_keys[index]
        if not self._tab_loaded.get(tab_key):
            self._load_tab(tab_key)
            self._tab_loaded[tab_key] = True
```

---

## 第九部分 · 国际化与无障碍

### 9.1 多语言 (Phase 4+ 海外市场再开)

**Phase 1-3**: 仅中文
**Phase 4+**: 准备 i18n 框架

```python
# ui_client/i18n/strings.py

LOCALE_ZH = {
    "menu.overview": "首页总览",
    "menu.accounts": "账号管理",
    "btn.publish": "立即发布",
    "msg.confirm_freeze": "确定要冻结此账号吗?",
    # ...
}

LOCALE_EN = {
    "menu.overview": "Overview",
    "menu.accounts": "Accounts",
    # ...
}


def t(key: str, **kwargs) -> str:
    """翻译函数"""
    locale = QSettings().value("ui.locale", "zh")
    table = LOCALE_ZH if locale == "zh" else LOCALE_EN
    text = table.get(key, key)
    if kwargs:
        text = text.format(**kwargs)
    return text


# 使用
self.btn = QPushButton(t("btn.publish"))
```

### 9.2 字体回退

```python
# ui_client/theme/font_loader.py

PREFERRED_FONTS = [
    "Microsoft YaHei",   # Windows 主推
    "PingFang SC",       # macOS
    "Source Han Sans",   # 思源
    "Noto Sans CJK SC",  # 通用
    "sans-serif",        # fallback
]

def setup_fonts(app: QApplication):
    available = QFontDatabase.families()
    chosen = next((f for f in PREFERRED_FONTS if f in available), "sans-serif")
    
    font = QFont(chosen, 10)
    app.setFont(font)
```

### 9.3 高 DPI 支持

```python
# main.py

import os
os.environ["QT_AUTO_SCREEN_SCALE_FACTOR"] = "1"
os.environ["QT_SCALE_FACTOR"] = "1.0"  # 默认
os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "1"

# Qt 6 默认开启高 DPI, 不需要额外配置
# 但 QPainter / 自绘 widget 注意 logicalDpiX / devicePixelRatio
```

---

## 第十部分 · 快捷键

### 10.1 全局快捷键

```python
# ui_client/app/shortcuts.py

class ShortcutManager:
    SHORTCUTS = {
        "Ctrl+1":     "page:overview",
        "Ctrl+2":     "page:accounts",
        "Ctrl+3":     "page:dramas",
        "Ctrl+4":     "page:publish",
        "Ctrl+,":     "page:config",
        "F5":          "action:refresh",
        "Ctrl+L":     "action:logout",
        "Ctrl+R":     "action:refresh",
        "Ctrl+F":     "action:search",
        "F1":          "action:help",
        "Esc":         "action:close_dialog",
    }
    
    def install(self, main_window: QMainWindow):
        for keyseq, action in self.SHORTCUTS.items():
            sc = QShortcut(QKeySequence(keyseq), main_window)
            sc.activated.connect(lambda a=action: self._handle(a, main_window))
    
    def _handle(self, action: str, main_window: QMainWindow):
        if action.startswith("page:"):
            main_window.navigate_to(action.split(":")[1])
        elif action == "action:refresh":
            main_window.current_page().on_enter()
        elif action == "action:logout":
            EventBus.emit("logout_required")
```

### 10.2 用户自定义快捷键 (Phase 4+)

```python
# 配置中心 → 基础设置 → 快捷键
# 用户可改, 写 QSettings
```

---

## 第十一部分 · 用户引导

### 11.1 首启向导 (4 步)

```
Step 1  欢迎页
        - Logo + 产品介绍
        - "您将体验 v3 文档定义的 22 页 (按 plan 显示)"
        - [下一步] 按钮

Step 2  激活授权
        - 输入卡密 + 手机号
        - 客户端自动算硬件指纹
        - [激活] 调 /api/client/auth/activate

Step 3  登录
        - 卡密激活后默认登录
        - 显示当前 plan + 到期日
        - [进入] 按钮

Step 4  入门引导
        - 高亮显示 Sidebar 主要菜单
        - 弹气泡: "点击账号管理添加你的第一个快手号"
        - [跳过] [下一步]
        - 完成后写 QSettings("first_run_completed", true)
```

### 11.2 Tooltip 提示

```python
# 关键控件添加 setToolTip
self.publish_btn.setToolTip(
    "选择剧源 → 选择账号 → 确认发布\n"
    "快捷键: Ctrl+P"
)
```

### 11.3 帮助中心

```
菜单: 帮助 → 帮助中心
内嵌 QWebEngineView 加载 https://docs.ks-matrix.com/help

或本地化: 内嵌 markdown 渲染 (markdown2 + QLabel.setHtml)
```

---

## 第十二部分 · 监控与埋点

### 12.1 客户端日志

```python
# ui_client/utils/logger.py

import logging
from logging.handlers import RotatingFileHandler

def setup_logger():
    log_dir = Path.home() / ".ks-matrix" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    handler = RotatingFileHandler(
        log_dir / "client.log",
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] [%(name)s] %(message)s"
    ))
    
    root = logging.getLogger("ks_client")
    root.setLevel(logging.INFO)
    root.addHandler(handler)
    
    return root
```

**日志规则**:
- 文件路径: `~/.ks-matrix/logs/client.log` (Windows: `%USERPROFILE%\.ks-matrix\logs\`)
- 滚动: 10MB × 5 个 = 最多 50MB
- 内容: 用户操作 / API 请求摘要 / 错误堆栈
- **禁止**记录: token / cookie / 密码 / 卡密原文

### 12.2 关键操作埋点

```python
# ui_client/utils/telemetry.py

class Telemetry:
    """客户端埋点, 上报关键操作"""
    
    @staticmethod
    def track(event: str, properties: dict = None):
        """异步上报, best effort"""
        if not _should_track():
            return
        
        worker = AsyncWorker(_send_telemetry, event, properties or {})
        worker.run_in_background = True  # 不影响主流程
        QThreadPool.globalInstance().start(worker)


def _send_telemetry(event: str, props: dict):
    api_client.post("/api/client/telemetry", json={
        "event": event,
        "properties": props,
        "client_version": __version__,
        "ts": datetime.now().isoformat(),
    })


# 业务侧
Telemetry.track("page_view", {"page": "accounts"})
Telemetry.track("publish_batch", {
    "drama_count": 5,
    "account_count": 13,
    "schedule_mode": "immediate",
})
Telemetry.track("feature_locked", {"feature": "FEATURE_AI_PICK"})
```

**埋点白名单** (避免过度收集):
```
✓ page_view             用户访问哪些页
✓ feature_used          用了什么功能
✓ feature_locked        触发锁定卡 (产品决策依据)
✓ error_shown           显示错误的次数和类型
✗ user_input_content    用户输入内容 (隐私)
✗ account_id            具体账号 (脱敏)
```

### 12.3 异常上报

```python
class CrashReporter:
    """崩溃上报"""
    
    @staticmethod
    def report(exc_type, exc_value, exc_traceback):
        try:
            tb_str = "".join(traceback.format_exception(
                exc_type, exc_value, exc_traceback
            ))
            
            api_client.post("/api/client/crash-report", json={
                "client_version": __version__,
                "platform": platform.platform(),
                "exception_type": exc_type.__name__,
                "exception_message": str(exc_value),
                "traceback": tb_str,
                "trace_id": get_current_trace_id(),
            }, timeout=2)
        except Exception:
            # 上报失败不影响主流程
            pass
```

### 12.4 性能指标

```python
# ui_client/utils/perf.py

class PerfMonitor:
    @staticmethod
    @contextmanager
    def measure(name: str):
        start = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = (time.perf_counter() - start) * 1000
            if elapsed_ms > 100:  # 只上报慢操作
                Telemetry.track("perf_slow", {
                    "operation": name,
                    "elapsed_ms": elapsed_ms,
                })


# 使用
with PerfMonitor.measure("page_render:overview"):
    overview_page._render(data)
```

---

## 第十三部分 · 测试策略

### 13.1 测试金字塔

```
              ╱╲
             ╱  ╲      E2E (10%)
            ╱----╲
           ╱      ╲    UI / 集成 (30%)
          ╱--------╲
         ╱          ╲   单元 (60%)
        ╱------------╲
```

### 13.2 单元测试 (services/widgets)

```python
# ui_client/tests/test_overview_service.py

import pytest
from unittest.mock import Mock
from ui_client.services.overview_service import OverviewService

def test_overview_filters_for_manual_plan():
    api = Mock()
    api.get.return_value = Envelope.ok({
        "today": {...},
        "autopilot": {...},        # PRO 专属字段
        "ai_advice_summary": {...},
    })
    
    permission = Mock()
    permission.current_plan.return_value = "manual"
    
    svc = OverviewService(api, permission)
    data = svc.fetch_overview()
    
    assert "today" in data
    assert "autopilot" not in data        # 应被过滤
    assert "ai_advice_summary" not in data
```

### 13.3 UI 测试 (pytest-qt)

```python
# ui_client/tests/test_overview_page.py

from pytestqt.qtbot import QtBot

def test_overview_page_displays_kpi(qtbot: QtBot):
    container = ServiceContainer()  # 用 mock services
    page = OverviewPage(container)
    qtbot.addWidget(page)
    
    page.viewmodel._on_loaded({
        "today": {"published": 6, "income": 1.39, ...},
    })
    
    # 等待重渲染
    qtbot.wait(100)
    
    # 断言 KPI 显示
    kpi_widget = page.findChild(KpiCard, "today_published")
    assert kpi_widget.value_label.text() == "6"
```

### 13.4 权限矩阵测试 (硬断言)

```python
# ui_client/tests/test_permission_matrix.py

import pytest

@pytest.mark.parametrize("plan,feature,expected", [
    ("manual",  "FEATURE_MANUAL_BATCH",  True),
    ("manual",  "FEATURE_AI_PICK",       False),  # 锁
    ("pro",     "FEATURE_AI_PICK",       True),
    ("pro",     "FEATURE_STRATEGY_LAB",  False),  # 锁
    ("team",    "FEATURE_STRATEGY_LAB",  True),
    # ... 32 FEATURE × 3 PLAN = 96 组合, 全列
])
def test_feature_permission(plan, feature, expected):
    svc = PermissionService()
    svc.set_plan(plan)
    assert svc.has_feature(feature) == expected
```

### 13.5 E2E 测试

```python
# ui_client/tests/test_e2e_publish_flow.py

def test_full_publish_flow(qtbot, mock_server):
    """模拟用户完整发布流程"""
    
    # 1. 启动 (mock server 已 mock 了所有 API)
    main_window = bootstrap(qapp)
    main_window.show()
    
    # 2. 模拟登录
    qtbot.keyClicks(login_form.phone, "13337289759")
    qtbot.keyClicks(login_form.password, "test")
    qtbot.mouseClick(login_form.btn_login, Qt.LeftButton)
    qtbot.waitUntil(lambda: main_window.current_page() == "overview")
    
    # 3. 进入剧源
    main_window.navigate_to("dramas")
    
    # 4. 选 2 部剧
    qtbot.mouseClick(drama_card_1.btn_add, Qt.LeftButton)
    qtbot.mouseClick(drama_card_2.btn_add, Qt.LeftButton)
    
    # 5. 进入发布
    main_window.navigate_to("publish")
    
    # 6. 选 3 个账号
    # ...
    
    # 7. 确认发布
    qtbot.mouseClick(confirm_dialog.btn_confirm, Qt.LeftButton)
    
    # 8. 验证发布请求被发出
    assert mock_server.received_request("/api/client/publish/batch")
```

### 13.6 覆盖率目标

```
单元测试:    > 80% (services / widgets / utils)
UI 测试:     > 60% (主要 page)
权限矩阵:    100% (96 组合全测)
E2E:        > 5 个核心流程
```

---

## 第十四部分 · 打包与分发

### 14.1 Phase 1-3 dev build

```bash
# Makefile

build-dev:
	# 简单 PyInstaller
	pyinstaller \
		--name "KsMatrix" \
		--onedir \
		--windowed \
		--icon ui_client/assets/icons/app.ico \
		--add-data "ui_client/theme:theme" \
		--add-data "ui_client/assets:assets" \
		--add-data "ui_client/mock:mock" \
		ui_client/app/main.py
```

### 14.2 Phase 4 加固构建

```
完整加固链 (规划文档 §6):

Step 1  Nuitka 编译
  python -m nuitka \
    --standalone \
    --windows-console-mode=disable \
    --enable-plugin=pyqt6 \
    --include-data-dir=ui_client/theme=theme \
    --include-data-dir=ui_client/assets=assets \
    ui_client/app/main.py
  
  → KsMatrix.dist/ (可执行)

Step 2  Rust 化关键模块
  rust_modules/
    license_core/      → license_core.pyd
    crypto_core/       → crypto_core.pyd
    anti_tamper/       → anti_tamper.pyd
    net_core/          → net_core.pyd
  
  替换 Nuitka 输出里的对应 .py 文件

Step 3  VMProtect 虚拟化
  vmprotect_console.exe \
    -p ks_protect.vmp \
    KsMatrix.dist/KsMatrix.exe
  
  标记关键函数:
    - license_check
    - fingerprint_compute
    - heartbeat_send
    - sig3_compute

Step 4  Themida 整体壳
  themida.exe -p config.tmd KsMatrix.exe
  
  开启:
    - 反调试
    - 反 VM (VMware/VBox)
    - 代码变形
    - 字符串加密

Step 5  水印 (每卡密独立)
  python build/inject_watermark.py \
    --license_uuid <uuid> \
    --input KsMatrix.exe \
    --output KsMatrix_<uuid>.exe
  
  在 .text 段尾随注入 UUID

Step 6  签名
  signtool sign \
    /tr http://timestamp.digicert.com \
    /td sha256 \
    /fd sha256 \
    /a KsMatrix_<uuid>.exe
```

### 14.3 自动更新机制

```python
# ui_client/app/updater.py

class AutoUpdater:
    UPDATE_URL = "https://updates.ks-matrix.com/check"
    
    @staticmethod
    def check_for_updates():
        """启动时检查更新"""
        try:
            resp = httpx.get(AutoUpdater.UPDATE_URL, params={
                "current_version": __version__,
                "license_id": current_license_id(),
                "fingerprint": current_fingerprint(),
            }, timeout=5)
            
            data = resp.json()
            if data["update_available"]:
                latest = data["latest_version"]
                force = data["force_update"]
                
                if force:
                    AutoUpdater._show_force_update_dialog(latest, data["download_url"])
                else:
                    AutoUpdater._show_optional_update_dialog(latest, data["download_url"])
        except Exception:
            pass  # 更新检查失败不影响启动
    
    @staticmethod
    def _show_force_update_dialog(version: str, url: str):
        """强制更新, 必须更新才能用"""
        # 阻塞对话框
        # 下载 + 替换 + 重启
        ...
```

**更新策略**:
- 每次启动检查
- 灰度发布 (按 license_id 哈希分流, 5% / 20% / 50% / 100%)
- 强制更新阈值: 老版本超过 14 天 / 安全 patch
- 差分更新: 只下变更模块 (Phase 5+)

---

## 第十五部分 · 调试与开发体验

### 15.1 开发模式

```python
# ui_client/app/env.py

KS_UI_MODE = os.getenv("KS_UI_MODE", "real")  # mock | real
KS_API_BASE = os.getenv("KS_API_BASE", "http://localhost:8080")
KS_DEBUG = os.getenv("KS_DEBUG", "0") == "1"
KS_QT_BACKEND = os.getenv("KS_QT_BACKEND", "pyqt6")  # pyqt6 | pyside6
KS_LOG_LEVEL = os.getenv("KS_LOG_LEVEL", "INFO")
```

```bash
# 开发场景
KS_UI_MODE=mock python -m ui_client.app.main         # 不连后端
KS_API_BASE=https://staging.ks.com python -m ui_client.app.main
KS_DEBUG=1 python -m ui_client.app.main              # 显示 debug 工具栏
```

### 15.2 Debug 工具栏 (KS_DEBUG=1)

```python
# ui_client/app/debug_toolbar.py

class DebugToolbar(QToolBar):
    """开发模式下的调试工具栏"""
    
    def __init__(self, main_window):
        super().__init__()
        self._mw = main_window
        
        self.addAction("🔄 强制刷新", lambda: main_window.current_page().on_enter())
        self.addAction("📋 dump state", self._dump_state)
        self.addAction("🌐 toggle mock", self._toggle_mock)
        self.addAction("🔍 inspect", self._open_inspector)
        self.addAction("📈 perf", self._open_perf_monitor)
        self.addAction("📜 logs", self._open_logs)
```

### 15.3 模拟数据

```python
# ui_client/services/mock_data_service.py

class MockDataService:
    """KS_UI_MODE=mock 时, ApiClient 改路由到这里"""
    
    def __init__(self):
        self._mock_dir = Path(__file__).parent.parent / "mock"
    
    def get(self, path: str, params: dict = None) -> dict:
        # /api/client/overview → mock/overview_pro.json
        file_name = path.replace("/api/client/", "").replace("/", "_") + ".json"
        file = self._mock_dir / file_name
        if file.exists():
            return json.loads(file.read_text(encoding="utf-8"))
        return {"ok": False, "error": {"code": "MOCK_NOT_FOUND", "message": "Mock 数据未找到"}}
```

---

## 第十六部分 · 客户端文件清单 (扩展 v2.md)

```
ui_client/
├── __init__.py
├── qt_compat.py                       # Qt 抽象 (PyQt6/PySide6 切换)
│
├── app/
│   ├── __init__.py
│   ├── main.py                        # QApplication 入口
│   ├── bootstrap.py                   # 启动编排
│   ├── constants.py                   # 全局常量 (版本/路径)
│   ├── env.py                         # 环境变量读取
│   ├── container.py                   # ServiceContainer (DI)
│   ├── error_boundary.py              # 全局异常 handler
│   ├── crash_recovery.py              # 崩溃恢复
│   ├── shortcuts.py                   # 全局快捷键
│   ├── updater.py                     # 自动更新
│   ├── debug_toolbar.py               # KS_DEBUG=1 时的工具栏
│   └── splash_screen.py               # 启动 Splash
│
├── theme/
│   ├── __init__.py
│   ├── tokens.py                      # ★ Design Tokens
│   ├── theme_loader.py                # 主题加载 + 模板渲染
│   ├── theme_manager.py               # 主题切换
│   ├── font_loader.py                 # 字体管理
│   ├── dark_tech_base.qss             # 深色基础
│   ├── dark_tech_components.qss       # 深色组件
│   ├── dark_tech_typography.qss       # 深色字体
│   ├── light_base.qss                 # 浅色 (Phase 2+)
│   └── light_components.qss
│
├── widgets/                           # 14 个原子组件 (见 v2.md §3.1)
│   ├── kpi_card.py
│   ├── plan_badge.py
│   ├── feature_lock_card.py
│   ├── confirm_dialog.py
│   ├── status_dot.py
│   ├── empty_state.py
│   ├── data_table.py
│   ├── chart_card.py
│   ├── loading_overlay.py
│   ├── toast.py
│   ├── async_button.py
│   ├── step_progress.py
│   ├── drama_card.py
│   └── risk_card.py
│
├── pages/
│   ├── base_page.py                   # 页面基类
│   ├── shell/
│   │   ├── main_window.py
│   │   ├── sidebar.py
│   │   └── topbar.py
│   ├── manual/                        # 仅 MANUAL 用 (v2.md 中 9 页内, 大多 common)
│   │   └── overview_manual.py
│   ├── pro/                           # PRO 替换/独占
│   │   ├── overview_pro.py
│   │   ├── overview_viewmodel.py
│   │   ├── burst_radar.py
│   │   ├── burst_radar_viewmodel.py
│   │   ├── publish_manage_pro.py
│   │   ├── ai_advice.py
│   │   ├── autopilot.py
│   │   └── risk_center.py
│   ├── team/                          # TEAM 独占 (7 页)
│   │   ├── team_dashboard.py
│   │   ├── account_ops.py
│   │   ├── strategy_lab.py
│   │   ├── members.py
│   │   ├── run_records.py
│   │   ├── agents_view.py
│   │   └── data_export.py
│   └── common/                        # 三版本共用 (9 页)
│       ├── accounts.py
│       ├── dramas.py
│       ├── publish_manual.py
│       ├── publish_results.py
│       ├── revenue.py
│       ├── exceptions.py
│       ├── config_center.py
│       ├── subscription.py
│       ├── login.py
│       ├── wizard_first_run.py
│       └── help.py
│
├── services/                          # 数据适配层 (16 个)
│   ├── api_client.py                  # ★ httpx 客户端
│   ├── auth_service.py
│   ├── license_service.py
│   ├── permission_service.py          # ★ 32 FEATURE × 3 PLAN
│   ├── mock_data_service.py
│   ├── overview_service.py
│   ├── accounts_service.py
│   ├── dramas_service.py
│   ├── publish_service.py
│   ├── revenue_service.py
│   ├── exception_service.py
│   ├── config_service.py
│   ├── ai_service.py                  # PRO+
│   ├── autopilot_service.py           # PRO+
│   ├── radar_service.py               # PRO+
│   ├── risk_service.py                # PRO+
│   ├── team_service.py                # TEAM
│   ├── experiment_service.py          # TEAM
│   ├── agents_service.py              # TEAM
│   ├── export_service.py              # TEAM
│   ├── ui_data_service.py             # 顶层 facade
│   └── cache_manager.py               # 缓存
│
├── storage/
│   ├── local_storage.py               # SQLCipher 加密 SQLite
│   ├── settings_manager.py            # QSettings 包装
│   └── outbox.py                      # 离线写队列
│
├── security/
│   ├── fingerprint.py                 # 硬件指纹
│   ├── secure_memory.py               # 敏感字符串
│   └── crypto.py                      # 加解密 helper
│
├── network/
│   ├── offline_manager.py             # 离线模式
│   ├── heartbeat_worker.py            # 心跳线程
│   └── outbox_replayer.py             # 离线重放
│
├── utils/
│   ├── async_worker.py                # AsyncWorker / ProgressWorker
│   ├── event_bus.py                   # 全局事件总线
│   ├── logger.py
│   ├── telemetry.py                   # 埋点
│   ├── crash_reporter.py              # 崩溃上报
│   ├── perf.py                        # 性能监控
│   ├── format.py                      # 格式化 (时间/数字/状态)
│   ├── env_helper.py
│   └── error_mapper.py                # 错误码 → 用户文案
│
├── i18n/
│   ├── strings.py                     # zh / en (Phase 4+)
│   └── locale.py
│
├── mock/                              # 17 JSON 种子 (见 v2.md §3.1)
├── assets/
│   ├── icons/
│   ├── fonts/
│   └── images/
│
└── tests/
    ├── conftest.py                    # qtbot fixture
    ├── test_qt_compat.py
    ├── test_permission_matrix.py      # ★ 96 组合
    ├── test_services_smoke.py
    ├── test_ui_smoke.py               # 启动冒烟
    ├── test_e2e_publish_flow.py       # E2E
    ├── test_e2e_login_flow.py
    └── unit/
        ├── test_overview_service.py
        ├── test_accounts_service.py
        ├── test_cache_manager.py
        ├── test_offline_manager.py
        └── ... (per service)
```

合计: **~110 个文件**.

---

## 附录 A · 时序图汇总

### A.1 启动时序

```
User → Click exe
         ↓
QApplication 创建
         ↓
SplashScreen 显示
         ↓
LocalStorage.unlock (SQLCipher 解密)
         ↓
读 token 缓存
    ├─ 有效  → ServiceContainer 启动
    └─ 无效  → LoginWindow
         ↓
ApiClient + Heartbeat + BackgroundCache 启动
         ↓
GET /api/client/license/status (并行 GET overview)
         ↓
渲染 Sidebar (按 plan 过滤菜单)
         ↓
切换到 MainWindow.OverviewPage
         ↓
SplashScreen 关闭
```

### A.2 用户操作时序 (批量发布)

```
User → 点 [批量发布] 按钮
         ↓
ConfirmDialog (二次确认)
         ↓
PublishService.start_batch (主线程)
         ↓
AsyncWorker (worker 线程)
         ↓
ApiClient.post /api/client/publish/batch
  Idempotency-Key: <uuid>
         ↓
服务端处理 (60s 内返回)
         ↓
Worker.success → ViewModel
         ↓
ViewModel.data_changed → View
         ↓
Toast 显示"已发起 24 条任务"
         ↓
跳转到 PublishResultsPage
```

### A.3 离线时序

```
心跳失败 1 次 → silent
心跳失败 3 次 → OfflineManager.mode = "degraded"
                EventBus.emit("offline_mode_changed", "degraded")
                TopBar 显示 "网络问题, 正在重连"
         ↓
失败 5 分钟累计 → mode = "offline"
                  禁用所有写按钮 (灰色 + tooltip)
                  TopBar 显示 "离线模式"
         ↓
失败 30 分钟累计 → EventBus.emit("offline_lockdown")
                   全屏遮罩 + "请检查网络连接"
                   仅 [重试] [退出] 可点
```

---

## 附录 B · 状态机图

### B.1 客户端启动状态机

```
[Idle]
   ↓ start
[Splash]
   ↓ unlock_storage_ok
[CheckAuth]
   ├── token_valid → [BootstrapServices]
   └── token_invalid → [LoginRequired]
[LoginRequired]
   ↓ login_success
[BootstrapServices]
   ├── license_valid → [MainReady]
   ├── license_expired → [SubscriptionRequired]
   └── network_fail → [OfflineWelcome]
[MainReady]
   ↓ user_interaction
[Active]
   ├── logout → [LoginRequired]
   ├── crash → [CrashRecovery]
   └── update_required → [Updating]
```

### B.2 网络状态机

```
[Online]
   ├── heartbeat_fail_3 → [Degraded]
   └── (正常)
[Degraded]
   ├── heartbeat_recovered → [Online]
   ├── elapsed_5min → [Offline]
   └── (用户继续操作, 写入 outbox)
[Offline]
   ├── heartbeat_recovered → [Online + replay outbox]
   ├── elapsed_30min → [Lockdown]
   └── (禁写, 仅可读 cache)
[Lockdown]
   ├── reconnect → [Online + replay]
   └── (UI 全屏遮罩)
```

---

## 附录 C · 关键性能基准

```
启动时间:
  T+1.0s   主窗口可见
  T+3.0s   完全可交互
  
页面切换:
  P50 < 100ms (已加载页)
  P95 < 500ms (首次加载, 懒实例化)

API 响应 (端到端):
  P50 < 150ms
  P95 < 600ms
  P99 < 2s

表格渲染:
  100 行    < 50ms
  1000 行   < 100ms (虚拟滚动)
  10k 行    < 200ms (虚拟滚动)

内存占用:
  启动后    ~120MB
  长时间运行 < 200MB
  含浏览大量页 < 300MB

CPU 占用:
  闲置      < 1%
  渲染中    < 15%
  心跳期间  瞬间 < 5%
```

---

## 签字确认

```
□ 6 层客户端架构 (Foundation → Storage → Transport → Service → ViewModel → View) 确认
□ 主线程禁阻塞, 任何 > 50ms 操作丢 QThreadPool                                      确认
□ ServiceContainer (DI) 单例, 测试时可替换 mock                                     确认
□ ViewModel 模式: Signal 通知 View, 不持有 widget 引用                              确认
□ ApiClient: httpx + 自动 refresh + envelope 解析 + 错误自动处理                    确认
□ 缓存策略: 内存 + 磁盘双层 + SWR + 离线降级                                         确认
□ LocalStorage: SQLCipher 加密, 密钥派生自硬件指纹                                  确认
□ AsyncWorker / ProgressWorker / CancellableWorker 三种异步模式                    确认
□ 全局错误边界 + 5 级用户反馈 (崩溃/严重/警告/失败/轻微)                              确认
□ 客户端日志: 10MB×5 滚动, 禁记敏感信息                                              确认
□ 性能目标: 启动 <3s / 切页 <200ms / 10k 行流畅                                     确认
□ 测试覆盖: 单元 80% / UI 60% / 权限 100% / E2E 5+                                  确认
□ Phase 4 加固链: Nuitka + Rust + VMProtect + Themida + 水印                       确认
□ 110 个文件清单                                                                   确认
```

---

## 版本历史

- **v1.0** (2026-04-25) — 初版. 在 `客户端改造完整计划v2.md` 基础上, 补充客户端工程架构 / 设计模式 / 异步并发 / 错误处理 / 安全 / 性能 / 测试 / 打包等工程深度内容.

## 下次 review

- Batch 1 完成后, 根据实际工程实现, 微调:
  - QThreadPool 实际并发数
  - 缓存 TTL 调优
  - 启动序列时间分配
  - 权限矩阵补全
- Phase 4 加固开始前, 重写 §14 加固章节 (实际配置)
