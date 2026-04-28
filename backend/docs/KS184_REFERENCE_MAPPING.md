# KS184 后台 → 我们后端 映射参考

> **生成日期**: 2026-04-25
> **数据源**:
> - `D:\KS184\mcn\analysis\BACKEND_REBUILD_BLUEPRINT.md` (580 行, KS184 后端反推蓝图)
> - `D:\KS184\mcn\admin_88\assets\` (26 个前端页面 chunks)
> - `D:\KS184\mcn\frontend\_api_probe\` (52 条 API probe)
> - `mcn.zhongxiangbao.com:88` (admin / MCNAdmin@2024) — KS184 真实后台
>
> **定位**: 这份文档把 KS184 的 26 页面 / 80+ 接口 / 业务边界, 完整映射到本仓库 14 层架构 (L0-L13).

---

## 一、KS184 后台 26 个页面 (按业务域分组)

| 业务域 | 页面 (asset chunk) | 中文名 | 我们层级 | 状态 |
|---|---|---|---|---|
| **登录/布局** | Login | 登录 | L13 → L2 | ✅ done (Phase 1.4) |
| 登录/布局 | MainLayout | 主布局 | 前端 | (PyQt6 / React) |
| 登录/布局 | Dashboard | 概览 | L2/L8 | Phase 2 |
| **账号资产** | Accounts | 软件账号 | L3 | Phase 2 P0 |
| 账号资产 | KsAccounts | 快手账号 | L3 | Phase 2 P0 |
| 账号资产 | CloudCookies | 云Cookie | L3 | Phase 2 P0 |
| 账号资产 | UserManager | 用户管理 | L2 | Phase 2 P0 |
| 账号资产 | Settings | 设置 | L8 | Phase 2 |
| **机构/成员** | OrgMembers | 机构成员 | L4 | Phase 2 P1 |
| 机构/成员 | MemberQuery | 成员查询 | L4 | Phase 2 P1 (强隔离) |
| **短剧池** | CollectPool | 采集池 | L7 | Phase 3 P3 |
| 短剧池 | DramaCollections | 短剧收藏 | L7 | Phase 3 P3 |
| 短剧池 | DramaStatistics | 剧统计 | L7 | Phase 3 P3 |
| 短剧池 | HighIncomeDramas | 高转化短剧 | L7 | Phase 3 P3 |
| **萤光 firefly** | FireflyMembers | 萤光成员 | L4 | Phase 3 P1 |
| 萤光 firefly | FireflyIncome | 萤光收益 | L6 | Phase 3 P2 |
| **星火 spark** | SparkMembers | 星火成员 | L4 | Phase 3 P1 |
| 星火 spark | SparkIncome | 星火收益 | L6 | Phase 3 P2 |
| 星火 spark | SparkArchive | 星火归档 | L6 | Phase 3 P2 |
| 星火 spark | SparkViolationPhotos | 星火违规图 | L4 | Phase 3 P1 |
| **荧光** | FluorescentIncome | 荧光收益 | L6 | Phase 3 P2 |
| **橙星推 cxt** | CxtUser | 橙星推用户 | L7 | Phase 4 |
| 橙星推 cxt | CxtVideos | 橙星推视频 | L7 | Phase 4 |
| **统计** | Statistics | 总览统计 | L8 | Phase 3 |
| 统计 | ExternalUrlStats | 外部URL统计 | L8 | Phase 3 |
| **钱包** | WalletInfo | 钱包 | L6 | Phase 3 P2 |

**共 26 页**, 我们后端需逐个对应业务模块.

---

## 二、URL 命名空间策略

KS184 用 `/api/*` (无前缀). 我们用 `/api/client/*`. 为了兼容现有前端 `D:\ks_automation\web` (它已用 `/api/...`), 我们提供 **两套挂载**:

```
/api/client/...      新客户端 (PyQt6) 用, 走 envelope 格式 + 严格鉴权
/api/legacy/...      兼容旧前端 (React + KS184 反推前端) 用, 走 {success, data} 格式
```

实际实现: 同一 router 模块, 仅在 main.py 挂两次.

---

## 三、API 端点清单 (KS184 → 我们)

### 3.1 已实现 (Phase 1)

| KS184 | 我们 | 状态 |
|---|---|---|
| POST /api/auth/login | POST /api/client/auth/login | ✅ |
| (无) | POST /api/client/auth/activate | ✅ (我们 SaaS 卡密扩展) |
| (无) | POST /api/client/auth/refresh | ✅ |
| (无) | POST /api/client/auth/heartbeat | ✅ |
| GET /api/auth/me | GET /api/client/auth/me | ✅ |
| (无) | POST /api/client/auth/logout | ✅ |

### 3.2 待实现 — Phase 2 P0 (账号 + 机构 + 用户)

```http
GET    /api/client/users
POST   /api/client/users
PUT    /api/client/users/:id
DELETE /api/client/users/:id
PUT    /api/client/users/:id/status
POST   /api/client/users/:id/reset-password
PUT    /api/client/users/:id/commission-rate
GET    /api/client/users/:id/permissions

GET    /api/client/organizations
POST   /api/client/organizations
PUT    /api/client/organizations/:id
DELETE /api/client/organizations/:id

GET    /api/client/accounts
POST   /api/client/accounts/batch-import
GET    /api/client/accounts/:id
PUT    /api/client/accounts/:id
DELETE /api/client/accounts/:id
POST   /api/client/accounts/assign
POST   /api/client/accounts/set-status
POST   /api/client/accounts/batch-operate-by-uids
GET    /api/client/accounts/:id/tasks
GET    /api/client/accounts/:id/stats

GET    /api/client/ks-accounts
DELETE /api/client/ks-accounts/:id
POST   /api/client/ks-accounts/batch-delete

GET    /api/client/cloud-cookies
PUT    /api/client/cloud-cookies/:id
DELETE /api/client/cloud-cookies/:id
POST   /api/client/cloud-cookies/batch-delete
POST   /api/client/cloud-cookies/batch-update-owner

GET    /api/client/audit-logs
GET    /api/client/audit-logs/stats
```

### 3.3 待实现 — Phase 2 P1 (账号生命周期 + 计划)

```http
POST   /api/client/mcn/verify
POST   /api/client/accounts/sync-mcn-authorization
POST   /api/client/accounts/batch-authorize
POST   /api/client/accounts/batch-direct-invite
POST   /api/client/accounts/batch-open-spark

GET    /api/client/org-members
POST   /api/client/org-members/sync

GET    /api/client/spark/members
POST   /api/client/spark/member-query        ★ 严格隔离白名单
GET    /api/client/spark/violations

GET    /api/client/firefly/members
POST   /api/client/firefly/members/sync
```

### 3.4 待实现 — Phase 3 P2 (收益结算)

```http
GET    /api/client/spark/income
GET    /api/client/spark/income/stats
GET    /api/client/spark/archive
POST   /api/client/spark/archive/batch-settlement

GET    /api/client/firefly/income
GET    /api/client/firefly/income/stats
POST   /api/client/firefly/income/batch-settlement

GET    /api/client/fluorescent/income
GET    /api/client/fluorescent/income/stats

GET    /api/client/wallet
PUT    /api/client/wallet
```

### 3.5 待实现 — Phase 3 P3 (短剧池)

```http
GET    /api/client/collect-pool
POST   /api/client/collect-pool
PUT    /api/client/collect-pool/:id
DELETE /api/client/collect-pool/:id
POST   /api/client/collect-pool/batch-import
POST   /api/client/collect-pool/deduplicate-and-copy

GET    /api/client/high-income-dramas
POST   /api/client/high-income-dramas
DELETE /api/client/high-income-dramas/:id
GET    /api/client/high-income-dramas/links

GET    /api/client/statistics/overview
GET    /api/client/statistics/drama-links
GET    /api/client/statistics/external-urls
```

### 3.6 待实现 — Phase 4 (我们 AI 自动化层 L9-L13)

```http
GET    /api/client/ai/candidate-pool          (L9 候选池)
GET    /api/client/ai/account-tier            (L9 分层)
POST   /api/client/ai/decision-explain        (L9 决策可解释)

GET    /api/client/agents                     (L10 9 个 Agent)
GET    /api/client/agents/:name/runs          (L10 历史)
POST   /api/client/agents/:name/trigger       (L10 手动触发)
GET    /api/client/autopilot/cycles           (L10 主循环健康)

GET    /api/client/memory/decision-history    (L11 Layer 1)
GET    /api/client/memory/strategy            (L11 Layer 2)
GET    /api/client/memory/diary               (L11 Layer 3)

GET    /api/client/healing/playbook           (L12 自愈规则)
GET    /api/client/healing/diagnoses          (L12 诊断流)

GET    /api/client/license/me                 (L13 当前卡密状态)
GET    /api/client/license/lifecycle          (L13 客户端版本/升级)
```

---

## 四、数据模型对照

### KS184 表 → 我们 SQLAlchemy 模型

| KS184 表名 | 我们模型 (`app/models/`) | 状态 |
|---|---|---|
| `admin_users` | `user.User` | ✅ |
| `roles` | `role.Role` | ✅ |
| `page_permissions` + `button_permissions` | `role.Permission` | ✅ (合并简化) |
| `user_organizations` | `organization.Organization` + `user.User.organization_id` | ✅ |
| `organizations` | `organization.Organization` | ✅ |
| `organization_cookies` | (TODO) `organization.OrgCookie` | Phase 2 |
| `mcn_authorizations` | (TODO) `account.McnAuthorization` | Phase 2 |
| `accounts` | (TODO) `account.SoftwareAccount` | Phase 2 |
| `ks_accounts` | (TODO) `account.KsAccount` | Phase 2 |
| `account_groups` | (TODO) `account.AccountGroup` | Phase 2 |
| `cloud_cookie_accounts` | (TODO) `account.CloudCookieAccount` | Phase 2 |
| `invitation_records` | (TODO) `account.InvitationRecord` | Phase 2 |
| `account_task_records` | (TODO) `task.AccountTaskRecord` | Phase 3 |
| `org_members` | (TODO) `member.OrgMember` | Phase 2 |
| `spark_members` | (TODO) `member.SparkMember` | Phase 3 |
| `firefly_members` | (TODO) `member.FireflyMember` | Phase 3 |
| `fluorescent_members` | (TODO) `member.FluorescentMember` | Phase 3 |
| `violation_photos` | (TODO) `member.ViolationPhoto` | Phase 3 |
| `income_records` | (TODO) `income.IncomeRecord` | Phase 3 |
| `spark_income` | (TODO) `income.SparkIncome` | Phase 3 |
| `firefly_income` | (TODO) `income.FireflyIncome` | Phase 3 |
| `income_archives` | (TODO) `income.IncomeArchive` | Phase 3 |
| `settlement_records` | (TODO) `income.SettlementRecord` | Phase 3 |
| `wallet_profiles` | (TODO) `income.WalletProfile` | Phase 3 |
| `collect_pool` | (TODO) `content.CollectPool` | Phase 3 |
| `high_income_dramas` | (TODO) `content.HighIncomeDrama` | Phase 3 |
| `drama_link_statistics` | (TODO) `content.DramaLinkStat` | Phase 3 |
| `drama_collection_records` | (TODO) `content.DramaCollectionRecord` | Phase 3 |
| `operation_logs` | (TODO) `audit.OperationLog` | Phase 2 |

---

## 五、关键安全要求 (来自 KS184 跨租户分析报告)

KS184 现网**已发现的漏洞**, 我们 Day 1 就要堵:

| # | 漏洞 | 我们对策 |
|---|---|---|
| 1 | `POST /api/spark/member-query` 可任意 UID 跨租户查 | **白名单**: 校验 UID 在 `tenant_scope.account_uids` 内 |
| 2 | `GET /api/cloud-cookies` 整体暴露 cookie 明文 | **AES-GCM** 加密入库, 默认返脱敏 (`cookie.preview` = "ses=...***"), 明文需独立 RBAC + 审计 |
| 3 | `GET /api/accounts` 不按机构过滤 | 中间件 `apply_tenant_scope()` 自动追 `WHERE organization_id IN (...)` |
| 4 | `GET /api/ks-accounts` 普通用户可全量查 | 普通用户限 `assigned_user_id = current_user.id` |
| 5 | `GET /api/*/income` 不应用佣金可见性 | `commission_amount` 字段按 `commission_rate_visible` 配置脱敏 |
| 6 | `POST /api/accounts/batch-*` 仅校验按钮权限不校验归属 | 每条 ID 调 `validate_payload_ownership(id, scope)` |

实现参考: `app/middleware/tenant_scope.py` (Phase 2 待写).

---

## 六、推荐实施顺序 (Phase 2 起)

> 不要并行铺所有模块. 按 P0 → P1 → P2 → P3 → P4, 每阶段尽量不留半成品.

```
Phase 2 (P0 + P1) — 4-6 天
  ① 模型: organization 扩展 / account / ks_account / cloud_cookie / org_cookie
       audit_log
  ② 中间件: tenant_scope.py (核心安全)
  ③ API: /accounts /ks-accounts /cloud-cookies /audit-logs
  ④ 用户管理 + 角色分配 API: /users
  ⑤ 邀约 + MCN 授权 API: /mcn/* /accounts/sync-mcn-authorization

Phase 3 (P2 + P3) — 5-7 天
  ① 收益模型 spark_income / firefly_income / fluorescent_income / income_archive
  ② 短剧模型 collect_pool / high_income / drama_link_stat
  ③ 收益 + 短剧 API
  ④ Wallet API

Phase 4 (P4 + L9-L13) — 7-10 天
  ① 复用 ks_automation/core/* 现成 89 个 Python 模块, 包成 service 层
  ② 接入 Agents (Watchdog / Planner / Analyzer / 等 9 个)
  ③ AI 记忆 / 候选池 / 决策引擎 endpoints
  ④ 卡密 + 客户端版本管理 endpoints
```

---

## 七、CHANGELOG 跟踪

| 日期 | 阶段 | 完成度 | 行数 | 测试 |
|---|---|---|---|---|
| 2026-04-25 | Phase 1 骨架 | 100% (7 步全过) | ~2000 | 12/12 pytest + 23/23 smoke |
