# Phase 2 实施计划

> **版本**: v1.0
> **日期**: 2026-04-25
> **依赖**: `MODULE_SPEC.md` (UI/API/DB/perm) + `PERMISSIONS_CATALOG.md` (RBAC)
> **当前状态**: Phase 1 骨架完成 (12/12 pytest + 23/23 smoke pass)
> **执行原则** (用户定调): 用户/权限/机构/账号池 → 任务执行/短剧池 → 收益归档/结算/Cookie池 → 外部项目

---

## 总览 — 4 个 Sprint, ~3 周

```
Sprint 2A — 地基 (P0 + 部分 P1)            5-7 天
Sprint 2B — 任务执行 + 短剧池 (P3 + 部分 P1)  5-7 天
Sprint 2C — 收益归档 + 结算 + 钱包 (P2)      5-7 天
Sprint 2D — Cookie 池 + 外部项目 (P4)        3-5 天
```

每 Sprint 结尾必有: ✅ 全 pytest 通过 + ✅ smoke E2E + ✅ Dashboard / OpenAPI 可访问.

---

## Sprint 2A · 地基 (用户/权限/机构/账号池)

> **目标**: 让团长可以登录, 看到自己机构的账号, 能创建队长/普通用户, 能授权 Cookie.

### 工作量预估

| 任务 | 预估 (h) | 文件 |
|---|---:|---|
| `permissions_data.py` 数据 | 1 | scripts/permissions_data.py |
| 升级 `init_db.py` 喂权限 | 1 | scripts/init_db.py |
| `core/permissions.py` (装饰器 + 加载器) | 3 | app/core/permissions.py |
| `core/tenant_scope.py` (隔离工具) | 3 | app/core/tenant_scope.py |
| `models.user` 扩字段 (role/level/parent/分成/可见性) | 1 | app/models/user.py |
| `models.account` (软件账号) + group + mcn_auth | 3 | app/models/account.py |
| `models.audit` (operation_logs) | 1 | app/models/audit.py |
| `services.account_service` (CRUD + 批量) | 5 | app/services/account_service.py |
| `services.user_service` | 4 | app/services/user_service.py |
| `services.org_service` | 2 | app/services/org_service.py |
| `services.audit_service` (装饰器 + 写日志) | 2 | app/services/audit_service.py |
| `api.v1.users` (10 端点) | 3 | app/api/v1/users.py |
| `api.v1.accounts` (15 端点) | 5 | app/api/v1/accounts.py |
| `api.v1.organizations` (5 端点) | 2 | app/api/v1/organizations.py |
| `api.v1.audit_logs` (3 端点) | 1 | app/api/v1/audit_logs.py |
| pytest 测试 (含隔离 + 越权用例) | 6 | tests/test_account.py + ... |
| 修复 + 联调 | 4 | — |
| **合计** | **47 h ≈ 6 天** | |

### 任务卡

#### 2A-1 数据层

```python
# app/models/user.py 扩字段
ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'normal_user';
ALTER TABLE users ADD COLUMN level INT DEFAULT 10;
ALTER TABLE users ADD COLUMN parent_user_id INT;
ALTER TABLE users ADD COLUMN commission_rate REAL DEFAULT 0.80;
ALTER TABLE users ADD COLUMN commission_rate_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN commission_amount_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN total_income_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN account_quota INT;

# 新模型
app/models/account.py:
  Account                    (软件账号 / 主表)
  AccountGroup               (分组)
  KsAccount                  (KS账号 / 设备绑定)
  CloudCookieAccount         (云Cookie)
  McnAuthorization           (MCN 授权状态)
  InvitationRecord           (邀约记录)
  AccountTaskRecord          (任务记录, 给 Dashboard 用)

app/models/audit.py:
  OperationLog
  UserPagePermission         (per-user override)
  UserButtonPermission
  DefaultRolePermission
```

迁移: SQLite 直接 DROP+CREATE (Phase 1 还没真上线), Phase 2 接 Alembic.

#### 2A-2 权限引擎

```python
# app/core/permissions.py
def load_user_perms(user_id) -> set[str]: ...
def user_has_perm(user, code) -> bool: ...
def require_perm(*codes): ...                # decorator
def require_role(min_role: str): ...

# app/core/tenant_scope.py
@dataclass
class TenantScope:
    unrestricted: bool
    organization_ids: list[int]
    user_ids: list[int]
    account_filter: str | None                 # 'assigned_user_id_eq_self' / None

def compute_tenant_scope(user) -> TenantScope: ...
def apply_to_account_query(stmt, scope, user): ...
def validate_payload_ownership(scope, ids: list[int], db, model): ...
```

测试用例 (强制覆盖):
- super_admin 看到全部
- operator 看到自己组织 (跨机构 0 条)
- normal_user 看到 assigned_user_id=self 的 (≤1 条)
- batch-* 中混入越权 ID → 整批拒 (而不是部分)
- super_admin 也不能跳过 audit log

#### 2A-3 软件账号 API (15 端点)

```http
GET  /api/client/accounts
GET  /api/client/accounts/:id
POST /api/client/accounts
PUT  /api/client/accounts/:id
DELETE /api/client/accounts/:id
POST /api/client/accounts/batch-import
POST /api/client/accounts/batch-authorize
POST /api/client/accounts/batch-revoke
POST /api/client/accounts/batch-direct-invite
POST /api/client/accounts/batch-open-spark
POST /api/client/accounts/batch-update-status
POST /api/client/accounts/batch-set-group
POST /api/client/accounts/batch-assign-user
POST /api/client/accounts/batch-set-commission
GET  /api/client/accounts/:id/tasks
```

每端点都要装 `@require_perm` + `@audit`.

#### 2A-4 KS 账号 + Cloud Cookie API (8 端点)

```http
GET    /api/client/ks-accounts
DELETE /api/client/ks-accounts/:id
POST   /api/client/ks-accounts/batch-delete
GET    /api/client/cloud-cookies
PUT    /api/client/cloud-cookies/:id
POST   /api/client/cloud-cookies/batch-import
POST   /api/client/cloud-cookies/batch-update-owner
POST   /api/client/cloud-cookies/:id/refresh-status
GET    /api/client/cloud-cookies/:id/reveal
```

`reveal` 端点必须:
- `@require_perm("cloud-cookie:reveal-plaintext")` (默认仅 super_admin)
- `@audit("module=cloud-cookie, action=reveal")`
- 先返 200 + 明文, 不分页

#### 2A-5 用户管理 + 机构 API (10 端点)

```http
GET  /api/client/users
POST /api/client/users
PUT  /api/client/users/:id
PUT  /api/client/users/:id/status
POST /api/client/users/:id/reset-password
PUT  /api/client/users/:id/role
PUT  /api/client/users/:id/commission-rate
PUT  /api/client/users/:id/commission-visibility
GET  /api/client/users/:id/permissions
PUT  /api/client/users/:id/permissions

GET  /api/client/organizations
POST /api/client/organizations              (super_admin only)
PUT  /api/client/organizations/:id
GET  /api/client/organizations/:id/cookie
PUT  /api/client/organizations/:id/cookie
```

#### 2A-6 审计日志 API

```http
GET  /api/client/audit-logs?user=&action=&module=&start=&end=
GET  /api/client/audit-logs/stats
```

#### 2A-7 测试 + 收尾

- pytest 加 `tests/test_account.py` `test_users.py` `test_tenant_scope.py`
- smoke test 加新 endpoint 路径
- README 更新启动说明

### 验收标准

| 项 | 标准 |
|---|---|
| **登录隔离** | 4 角色登录后 `GET /accounts` 各自看到对的范围 |
| **批量越权** | normal_user 调 batch-* 即使按钮被绕过, API 也返 403 |
| **审计完整** | 所有写操作 (含登录) 在 `operation_logs` 有记录, 含 trace_id |
| **Cookie 默认脱敏** | `GET /cloud-cookies` 永远不返明文 |
| **明文需独立审计** | `GET /cloud-cookies/:id/reveal` 写一条 reveal 日志 |
| **测试覆盖** | pytest 通过率 100%, 覆盖率 ≥ 60% |
| **OpenAPI 完整** | `/docs` 显示所有新端点 + Pydantic 字段说明 |

---

## Sprint 2B · 任务执行 + 短剧池

> **目标**: 任务记录可写入, 短剧池可管理, Dashboard 能聚合统计.

### 任务清单 (估 6 天)

| 任务 | 预估 (h) |
|---|---:|
| `models.content` (collect_pool, high_income_dramas, drama_link_stat, drama_collection_record, external_url) | 3 |
| `services.collect_pool_service` (CRUD + 去重 + 批量导入) | 4 |
| `services.high_income_service` | 1 |
| `services.statistics_service` (drama-links 聚合 + Dashboard) | 4 |
| `api.v1.collect_pool` | 2 |
| `api.v1.high_income_dramas` | 1 |
| `api.v1.statistics` (overview + executions + drama-links) | 3 |
| `services.task_record_service` (写入 + 聚合) | 3 |
| 工人: `workers.aggregate_drama_stats.py` (定时聚合) | 3 |
| 测试 | 5 |
| **合计** | **29 h ≈ 4 天** |

### 端点

```http
GET    /api/client/collect-pool
POST   /api/client/collect-pool
PUT    /api/client/collect-pool/:id
DELETE /api/client/collect-pool/:id
POST   /api/client/collect-pool/batch-import
POST   /api/client/collect-pool/deduplicate-and-copy
POST   /api/client/collect-pool/refresh-status
POST   /api/client/collect-pool/batch-delete

GET    /api/client/high-income-dramas
POST   /api/client/high-income-dramas
DELETE /api/client/high-income-dramas/:id
GET    /api/client/high-income-dramas/:id/links

GET    /api/client/statistics/overview
GET    /api/client/statistics/today-cards
GET    /api/client/statistics/executions
GET    /api/client/statistics/drama-links
POST   /api/client/statistics/drama-links/export
POST   /api/client/statistics/drama-links/batch-delete
GET    /api/client/statistics/external-urls

GET    /api/client/drama-collection-records
GET    /api/client/drama-collection-records/:account_uid/detail
```

### 验收

- Dashboard 卡片数据全部对得上 `accounts.count` / `account_task_records` 聚合
- `drama-links` 接口返回 join 多表后的 success_rate
- collect-pool 批量去重正确避免同 URL 重复

---

## Sprint 2C · 收益归档 + 结算 + 钱包

> **目标**: 萤光/星火/荧光收益完整可看 + 标结 + 钱包.

### 任务清单 (估 7 天)

| 任务 | 预估 (h) |
|---:|---:|
| `models.member` (org_member, spark_member, firefly_member, fluorescent_member, violation_photo) | 3 |
| `models.income` (income_record, spark_income, firefly_income, fluorescent_income, income_archive, settlement_record, wallet_profile) | 4 |
| `services.member_service` (sync from MCN + member-query 强隔离) | 5 |
| `services.income_service` (导入 Excel + 聚合统计 + 标结) | 6 |
| `services.wallet_service` | 2 |
| 收益脱敏 helper | 2 |
| `api.v1.members` (org / spark / firefly / member-query) | 3 |
| `api.v1.income` (spark / firefly / fluorescent + archive) | 4 |
| `api.v1.violations` | 2 |
| `api.v1.wallet` | 1 |
| Excel 导入 (openpyxl) | 3 |
| 测试 (含敏感字段脱敏 + 越权 UID) | 6 |
| **合计** | **41 h ≈ 5-6 天** |

### 关键安全细节

```python
# 严格 member-query 白名单
def member_query(req, user):
    scope = compute_tenant_scope(user)
    valid_uids = get_account_uids_in_scope(scope)
    requested = set(req.uids)
    invalid = requested - valid_uids
    if invalid:
        raise BizError(AUTH_403,
            message="部分 UID 不在您的可见范围",
            details={"out_of_scope_count": len(invalid)})
    # 只查 valid 的
    return query_member_income(requested & valid_uids)


# 收益脱敏
def list_income(db, user, params):
    rows = query_income_records(db, params).all()
    return [mask_income_record(r.to_dict(), user) for r in rows]
```

### 验收

- 4 角色看收益, 各自范围正确
- normal_user `commission_amount_visible=False` → 字段返 null
- 标结 → archive.settlement_status 'pending' → 'settled'
- member-query 越权 UID 直接 403 (不返部分)

---

## Sprint 2D · Cookie 池 + 外部项目 + Worker

> **目标**: 完成最后 4 个页面 + 启动后台 worker (定时同步 + 聚合).

### 任务清单 (估 5 天)

| 任务 | 预估 (h) |
|---|---:|
| `models.cxt` (cxt_user, cxt_video) | 1 |
| `services.cxt_service` | 2 |
| `api.v1.cxt` | 1 |
| Cookie 加密 helper (AES-GCM) | 2 |
| `models.organization.OrgCookie` 加密落地 | 1 |
| `services.cookie_pool_service` (绑定/分配/配额) | 4 |
| Worker 框架: `workers/__init__.py` + `apscheduler` | 3 |
| `worker.sync_mcn_authorization` | 2 |
| `worker.aggregate_drama_stats` (Sprint 2B 已起的接) | 1 |
| `worker.cookie_status_refresher` | 2 |
| 测试 | 4 |
| 文档收尾 | 2 |
| **合计** | **25 h ≈ 3 天** |

### 端点

```http
GET    /api/client/cxt/users
POST   /api/client/cxt/users/import
GET    /api/client/cxt/videos
POST   /api/client/cxt/videos/batch-import
GET    /api/client/cxt/videos/:id

# 公告
GET    /api/client/announcements
POST   /api/client/announcements
PUT    /api/client/announcements/:id
DELETE /api/client/announcements/:id

# 系统配置
GET    /api/client/settings/basic
PUT    /api/client/settings/basic
GET    /api/client/settings/role-defaults
PUT    /api/client/settings/role-defaults
GET    /api/client/settings/about
```

### 验收

- 4 个 Worker 启动 (apscheduler), 每个有 healthz 显示 last_run / next_run
- Cookie AES-GCM 加密 + 默认脱敏 + reveal 端点单独审计
- 所有 26 页面对应 API 实现 100%
- pytest 总数 ≥ 80, 覆盖率 ≥ 70%

---

## 跨 Sprint 通用任务

| 任务 | 何时 | 估时 |
|---|---|---:|
| Alembic 集成 (Phase 1.5 后) | 2A 开始 | 3h |
| 限流中间件 `slowapi` | 2A 开始 | 2h |
| 幂等 `Idempotency-Key` 中间件 | 2A 开始 | 3h |
| Pydantic schema `from_attributes` 收口 | 每 Sprint | 1h |
| OpenAPI tags + 描述补全 | 每 Sprint | 1h |
| README + dev/prod 部署文档 | 2D 收尾 | 3h |

---

## 风险与应对

| 风险 | 影响 | 应对 |
|---|---|---|
| Excel 导入字段不固定 (KS184 各 owner 上报格式不一) | 收益导入失败率高 | 写**字段映射 YAML** + 失败行写 `import_errors` 表, 不直接 raise |
| MCN 同步可能超时 / 限流 | sync 卡住 | worker 用 `httpx.AsyncClient(timeout=30)` + 熔断 + 30s/60s/120s 退避 |
| SQLite 高并发写阻塞 | 多 worker 写 income 时锁 | WAL 已开 + busy_timeout=30s; Phase 4 切 PG |
| 权限粒度太细 → 配置爆炸 | UI 难管 | 默认权限模板 + 按钮粗粒度合并 (e.g. `account:batch-*` 一个) |
| 组织上下级查询慢 | parent_user_id 层级递归 | 缓存 5min `subordinate_user_ids` + 上限 5 层 |

---

## 我自己的工程 checklist (每次 PR 必跑)

```
1. ruff check .
2. ruff format .
3. pytest -v
4. python -m scripts.smoke_test
5. python -m uvicorn app.main:app & curl /healthz /readyz /openapi.json
6. 检查 audit log 有写
7. 检查 Cookie/收益脱敏没漏
```

---

## 完成定义 (Phase 2 整体)

- [ ] 4 角色全功能登录 + 看到正确范围
- [ ] 26 页面全部 API 可用 + OpenAPI 显示
- [ ] 6 类高敏接口 (member-query / cookie / income / batch-* / 用户管理 / 跨机构) 全部隔离 + 越权拒绝
- [ ] 所有写操作有 operation_log + trace_id 关联
- [ ] pytest ≥ 80 测试 全过
- [ ] smoke test ≥ 50 项目 全过
- [ ] 4 个 worker 跑起来 + healthz 可见
- [ ] README + 部署文档 (dev/prod) 写完
- [ ] 启动 Phase 3 (AI 自动化层 L9-L13) 的入口 (复用 ks_automation/core/* 89 模块包成 service)
