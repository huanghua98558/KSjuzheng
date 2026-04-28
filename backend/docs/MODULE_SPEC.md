# KS184 后台 26 页面 · 完整模块 Spec

> **版本**: v1.0
> **日期**: 2026-04-25
> **来源**:
> - 用户实地登录 `mcn.zhongxiangbao.com:88` (admin/MCNAdmin@2024) 实测各页面 UI / 字段 / 按钮
> - `D:\KS184\mcn\analysis\BACKEND_REBUILD_BLUEPRINT.md` (KS184 后端反推蓝图 580 行)
> - `D:\KS184\mcn\admin_88\assets\` (26 个前端 chunk)
>
> **每页规范**:
>   - **UI 元素**: 列表列 / 筛选条件 / 按钮 / 弹窗
>   - **API 端点**: METHOD + PATH + 输入 + 输出
>   - **DB 字段**: 完整字段清单 + 索引
>   - **权限点**: page perm + button perm
>   - **隔离边界**: 必须按 organization_id / assigned_user_id / parent_user_id 过滤

---

## 总目录

```
1.   数据概览  (Dashboard / Statistics)
2.   软件账号  (Accounts)
3.   KS账号    (KsAccounts)
4.   云端Cookie (CloudCookies)
5.   机构成员  (OrgMembers)
6.   成员查询  (MemberQuery) ★ 严格隔离
7.   账号违规  (Violations / SparkViolationPhotos)
8.   用户管理  (UserManager)
9.   钱包信息  (WalletInfo)
10.  萤光-本月  (FireflyMembers + this-month)
11.  萤光-历史  (FireflyIncome archive)
12.  萤光-明细  (FireflyIncome detail)
13.  星火-本月  (SparkMembers + this-month)
14.  星火-历史  (SparkArchive)
15.  星火-明细  (SparkIncome detail)
16.  荧光收益  (FluorescentIncome)
17.  短剧收藏池 (CollectPool)
18.  高转化短剧 (HighIncomeDramas)
19.  短剧链接统计 (DramaStatistics → drama-links)
20.  短剧收藏记录 (DramaCollections)
21.  外部URL统计 (ExternalUrlStats)
22.  橙星推用户 (CxtUser)
23.  橙星推视频 (CxtVideos)
24.  机构信息  (Organizations / Settings 子页)
25.  公告管理  (Settings 子页 - announcements)
26.  系统配置  (Settings 子页 - basic + db + role-defaults + about)
```

---

## 1. 数据概览 (Dashboard / Statistics)

### UI

**仪表盘**:
- 卡片: 总账号数 / MCN账号数 / 总执行次数 / 今日执行次数
- 趋势图: 近 7 天 / 30 天 执行次数曲线
- 饼图: 成功 vs 失败比例

**执行统计** (子页):
- 筛选: 日期范围 + UID 模糊搜索
- 表格列: 日期 / 执行次数 / 成功次数 / 失败次数 / 成功率 / 平均耗时

### API

```http
GET /api/client/statistics/overview
  → { total_accounts, mcn_accounts, total_executions, today_executions,
      trend_7d: [{date, count, success, fail}],
      success_ratio: { success, fail } }

GET /api/client/statistics/executions?start=YYYY-MM-DD&end=YYYY-MM-DD&uid=...
  → { items: [{date, exec_count, success_count, fail_count,
                success_rate, avg_duration_ms}], pagination }

GET /api/client/statistics/today-cards    (单独一接口供卡片快速刷)
  → { total_accounts, mcn_accounts, today_executions, ... }
```

### DB 字段 (依赖)

读: `accounts` `account_task_records` `mcn_authorizations`

聚合视图 (可选物化):
```sql
CREATE TABLE statistics_daily (
  date DATE,
  organization_id INT,
  assigned_user_id INT,
  exec_count INT,
  success_count INT,
  fail_count INT,
  total_duration_ms BIGINT,
  PRIMARY KEY (date, organization_id, assigned_user_id)
);
```

### 权限

- **page**: `dashboard:view`
- **button**: (无)
- 隔离: `where organization_id IN tenant_scope AND assigned_user_id IN tenant_scope`

---

## 2. 软件账号 (Accounts)  ★ 核心页

### UI

**筛选**:
- 关键字 (账号名 / 真实UID)
- 机构 (下拉)
- 分组 (下拉)
- 分配用户 (下拉)
- 状态: 全部 / 启用 / 停用 / 已删除
- 签约状态: 未签 / 已签 / 申请中
- MCN状态: 未授权 / 已授权 / 已解除
- 分成比例: 数字范围

**列**:
- ID / 账号名 / 真实UID / 昵称 / 机构 / 分组 / 分配给 / 分成比例 / 签约状态 / MCN状态 / 创建时间 / 操作

**按钮 (页头)**:
- ➕ 添加账号 (单条 modal)
- 📥 批量导入 (Excel / CSV)
- 🔐 批量授权 MCN (选中后)
- ❌ 取消授权 (选中后)
- 🔄 更新授权状态
- 💰 更新收益
- 📂 分组 (打开分组管理)
- 👤 分配用户
- ⚖️ 修改分成比例
- 🏢 修改机构
- 🚫 账号管控
- 🗑️ 批量删除
- 📊 任务记录 (跳详情页)

**列内操作**:
- 编辑 / 查看任务记录 / 删除

### API

```http
GET    /api/client/accounts?keyword=&org_id=&group_id=&assigned_user_id=
                            &status=&sign_status=&mcn_status=
                            &commission_min=&commission_max=
                            &page=1&size=50&sort=created_at.desc

POST   /api/client/accounts                      (单条添加, 弹窗)
POST   /api/client/accounts/batch-import         (Excel/CSV 上传)
GET    /api/client/accounts/:id
PUT    /api/client/accounts/:id                  (编辑)
DELETE /api/client/accounts/:id

# 批量
POST   /api/client/accounts/batch-authorize      ★ 批量授权 MCN
POST   /api/client/accounts/batch-revoke         ★ 取消授权
POST   /api/client/accounts/batch-direct-invite  ★ 直邀
POST   /api/client/accounts/batch-open-spark
POST   /api/client/accounts/sync-mcn-authorization
POST   /api/client/accounts/batch-update-income
POST   /api/client/accounts/batch-update-status  (启用/停用)
POST   /api/client/accounts/batch-delete
POST   /api/client/accounts/batch-set-group
POST   /api/client/accounts/batch-assign-user
POST   /api/client/accounts/batch-change-org
POST   /api/client/accounts/batch-set-commission

# 子资源
GET    /api/client/accounts/:id/tasks            (任务记录)
GET    /api/client/accounts/:id/stats            (账号级统计)
```

### DB

```sql
CREATE TABLE accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT NOT NULL,                    -- ★ 隔离 1
  assigned_user_id INT,                            -- ★ 隔离 2
  group_id INT,
  kuaishou_id VARCHAR(64),                         -- 快手账号名 / 登录名
  real_uid VARCHAR(32),                            -- 真实数字 UID (cookie 提取)
  nickname VARCHAR(100),
  status VARCHAR(20) DEFAULT 'active',             -- active / disabled / deleted
  mcn_status VARCHAR(20),                          -- none / authorized / revoked / pending
  sign_status VARCHAR(20),                         -- none / signed / applying
  commission_rate REAL DEFAULT 0.80,
  remark TEXT,
  device_serial VARCHAR(64),
  cookie_status VARCHAR(20),                       -- valid / expired / unknown
  cookie_last_success_at TIMESTAMP,
  imported_by_user_id INT,
  imported_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
  updated_at TIMESTAMP DEFAULT (datetime('now','localtime')),
  deleted_at TIMESTAMP
);
CREATE INDEX ix_accounts_org ON accounts(organization_id);
CREATE INDEX ix_accounts_user ON accounts(assigned_user_id);
CREATE INDEX ix_accounts_uid ON accounts(real_uid);
CREATE INDEX ix_accounts_status ON accounts(status);

CREATE TABLE account_groups (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  owner_user_id INT,
  name VARCHAR(100),
  created_at TIMESTAMP
);

CREATE TABLE account_task_records (        -- 任务记录子页用
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INT NOT NULL,
  organization_id INT,
  task_type VARCHAR(32),                   -- publish / mcn_verify / cookie_refresh ...
  drama_id INT,
  drama_name VARCHAR(200),
  success BOOLEAN,
  duration_ms INT,
  error_message TEXT,
  created_at TIMESTAMP
);
CREATE INDEX ix_atr_account_date ON account_task_records(account_id, created_at);

CREATE TABLE mcn_authorizations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_id INT NOT NULL,
  organization_id INT NOT NULL,
  mcn_status VARCHAR(20),
  sign_status VARCHAR(20),
  invite_status VARCHAR(20),
  authorized_at TIMESTAMP,
  invited_at TIMESTAMP,
  revoked_at TIMESTAMP,
  UNIQUE(account_id, organization_id)
);
```

### 权限

- **page**: `account:view`
- **button**:
  - `account:create`
  - `account:edit`
  - `account:delete`
  - `account:batch-import`
  - `account:batch-authorize`
  - `account:batch-revoke`
  - `account:batch-invite`
  - `account:batch-open-spark`
  - `account:batch-update-income`
  - `account:assign-user`
  - `account:change-org`
  - `account:change-commission`
  - `account:control`              (账号管控)
  - `account:view-task-records`

隔离: `WHERE organization_id IN tenant_scope.organizations` AND
       (super_admin 全可见 / operator 看自己机构下全部 / captain+ 看 assigned_user_id IN subordinates / normal 看 assigned_user_id = self)

---

## 3. KS账号 (KsAccounts)

### UI

**筛选**: 账号名 / UID / 设备码

**列**:
- ID / 账号名 / 快手UID / 设备码 / 创建时间 / 操作

**按钮**:
- 🗑️ 单条删除 / 批量删除

### API

```http
GET    /api/client/ks-accounts?keyword=&page=&size=
DELETE /api/client/ks-accounts/:id
POST   /api/client/ks-accounts/batch-delete
```

### DB

```sql
CREATE TABLE ks_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_name VARCHAR(100),
  kuaishou_uid VARCHAR(32) UNIQUE,
  device_code VARCHAR(64),
  organization_id INT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
CREATE INDEX ix_ks_uid ON ks_accounts(kuaishou_uid);
CREATE INDEX ix_ks_dev ON ks_accounts(device_code);
```

### 权限

- **page**: `ks-account:view`
- **button**: `ks-account:delete`, `ks-account:batch-delete`
- 隔离: 普通用户**不可全量查**, 必须 `WHERE organization_id IN tenant_scope`

---

## 4. 云端 Cookie (CloudCookies)  ★ 高敏

### UI

**筛选**: 关键字 / owner_code / 状态 (已登录/失效/未知)

**列**:
- ID / UID / 昵称 / owner_code / 状态 / 分配给 / 最后成功时间 / 操作

**按钮**:
- ➕ 单条录入
- 📥 批量导入
- ✏️ 批量修改归属
- 🗑️ 批量删除
- 🔄 刷新登录状态

**列内**: 编辑 / 删除 / **查看明文** (高权限按钮, 触发审计)

### API

```http
GET    /api/client/cloud-cookies?keyword=&owner_code=&status=&page=&size=
       响应: cookie 字段统一为 `preview`: "ses=eyJ***...***" 不返回明文
PUT    /api/client/cloud-cookies/:id
DELETE /api/client/cloud-cookies/:id
POST   /api/client/cloud-cookies/batch-import
POST   /api/client/cloud-cookies/batch-update-owner
POST   /api/client/cloud-cookies/batch-delete
POST   /api/client/cloud-cookies/:id/refresh-status
GET    /api/client/cloud-cookies/:id/reveal       ★ 高权限端点, 单独审计日志
```

### DB

```sql
CREATE TABLE cloud_cookie_accounts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  uid VARCHAR(32),
  owner_code VARCHAR(50),                  -- 黄华 / cpkj888 ...
  organization_id INT,
  assigned_user_id INT,
  account_id INT,                          -- 关联软件账号
  cookie_ciphertext BLOB,                  -- AES-GCM 加密
  cookie_iv BLOB,                          -- 96-bit IV
  cookie_tag BLOB,                         -- 128-bit GCM tag
  login_status VARCHAR(20),                -- valid / expired / unknown
  last_success_at TIMESTAMP,
  imported_by_user_id INT,
  created_at TIMESTAMP,
  updated_at TIMESTAMP
);
```

### 权限

- **page**: `cloud-cookie:view`
- **button**:
  - `cloud-cookie:create`
  - `cloud-cookie:batch-import`
  - `cloud-cookie:batch-update-owner`
  - `cloud-cookie:delete`
  - `cloud-cookie:reveal-plaintext`         ★ 默认仅 super_admin
- 隔离: `WHERE organization_id IN tenant_scope` + 普通用户加 `assigned_user_id = self`

---

## 5. 机构成员 (OrgMembers)

### UI

**筛选**: 关键字 / 机构 / 经纪人 / 续约状态 / 合作类型

**列**:
- 成员ID / 用户ID / 头像 / 昵称 / 机构 / 所属账号 / 粉丝数 / 经纪人 / 合作类型 / 内容分类 / MCN等级 / 续约状态 / 合同过期时间

**按钮**:
- 🔄 同步成员 (从 MCN)
- 📥 导入 Excel
- 📤 导出

### API

```http
GET    /api/client/org-members?org_id=&keyword=&renewal_status=&cooperation_type=
POST   /api/client/org-members/sync             (从 MCN 拉)
POST   /api/client/org-members/import           (Excel)
GET    /api/client/org-members/export
```

### DB

```sql
CREATE TABLE org_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT NOT NULL,
  member_id BIGINT,                        -- MCN member_id (numeric)
  user_id INT,                             -- 关联本地 user (可空)
  account_id INT,                          -- 关联软件账号 (可空)
  nickname VARCHAR(100),
  avatar VARCHAR(500),
  fans_count INT DEFAULT 0,
  broker_name VARCHAR(100),
  cooperation_type VARCHAR(50),
  content_category VARCHAR(50),
  mcn_level VARCHAR(50),
  renewal_status VARCHAR(20),              -- active / expiring / expired / pending
  contract_expires_at DATE,
  synced_at TIMESTAMP,
  UNIQUE(organization_id, member_id)
);
```

### 权限

- **page**: `org-member:view`
- **button**: `org-member:sync`, `org-member:import`, `org-member:export`
- 隔离: `WHERE organization_id IN tenant_scope`

---

## 6. 成员查询 (MemberQuery)  ★ 严格安全

### UI

输入: UID 列表 (多行粘贴) / 时间范围 → 查询返回收益 + 任务统计.

### API

```http
POST /api/client/spark/member-query
body: { uids: ["3xmne9bjww75dt9", ...], start: "2026-04-01", end: "2026-04-25" }
```

### 安全规则 (强约束)

```python
def member_query(req, current_user):
    scope_uids = get_account_uids_in_scope(current_user)
    requested_uids = set(req.uids)

    # ★ 白名单: 不在范围内的 UID 直接拒
    invalid = requested_uids - scope_uids
    if invalid:
        raise BizError(AUTH_403, message="部分 UID 不在您的可见范围",
                       details={"out_of_scope": list(invalid)[:5]})

    # 仅查 valid 的部分
    return query_member_income(requested_uids & scope_uids, ...)
```

### 权限

- **page**: `member-query:view`
- **button**: `member-query:execute`
- 隔离: ★ **逐 UID 校验归属** (而不是只过滤结果集)

---

## 7. 账号违规 (Violations / SparkViolationPhotos)

### UI

**筛选**: 关键字 / 机构 / 业务类型 / 申诉状态 / 时间范围

**列**:
- 作品ID / 缩略图 / 用户名 / 机构 / 所属用户 / 描述 / 播放量 / 点赞数 / 业务类型 / 违规原因 / 申诉状态 / 发布时间

**列内**: 编辑 / 删除 / 查看大图

### API

```http
GET /api/client/violations?org_id=&business_type=&appeal_status=&keyword=&page=&size=
PUT /api/client/violations/:id
DELETE /api/client/violations/:id
```

### DB

```sql
CREATE TABLE violation_photos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  account_id INT,
  work_id VARCHAR(64),                     -- 快手作品 ID
  uid VARCHAR(32),
  thumbnail VARCHAR(500),
  description TEXT,
  business_type VARCHAR(50),               -- spark / firefly / fluorescent
  violation_reason TEXT,
  view_count BIGINT,
  like_count BIGINT,
  appeal_status VARCHAR(20),               -- none / submitted / approved / rejected
  published_at TIMESTAMP,
  detected_at TIMESTAMP,
  created_at TIMESTAMP
);
```

### 权限

- **page**: `violation:view`
- **button**: `violation:edit`, `violation:delete`, `violation:appeal`

---

## 8. 用户管理 (UserManager)

### UI

**筛选**: 关键字 / 角色 / 状态 / 上级

**列**:
- ID / 用户名 / 昵称 / 角色 / 等级 / 上级 / 机构 / 分成比例 / 配额 / 状态 / 最后登录 / 操作

**按钮 (页头)**:
- ➕ 创建用户
- 📋 默认权限模板 (跳设置子页)

**列内**:
- 编辑 / 改密码 / 页面权限 / 按钮权限 / 账号授权 / 分成可见性 / 支付宝信息 / 角色调整 / 启用 / 停用 / 删除

### API

```http
GET    /api/client/users?keyword=&role=&status=&parent_id=&page=&size=
POST   /api/client/users
PUT    /api/client/users/:id
DELETE /api/client/users/:id
PUT    /api/client/users/:id/status
POST   /api/client/users/:id/reset-password
PUT    /api/client/users/:id/commission-rate
PUT    /api/client/users/:id/commission-visibility
PUT    /api/client/users/:id/role
GET    /api/client/users/:id/page-permissions
PUT    /api/client/users/:id/page-permissions
GET    /api/client/users/:id/button-permissions
PUT    /api/client/users/:id/button-permissions
GET    /api/client/users/:id/assigned-accounts
PUT    /api/client/users/:id/assigned-accounts
GET    /api/client/users/:id/wallet
PUT    /api/client/users/:id/wallet
```

### DB (已部分实现)

```sql
-- users 表 已建 (Phase 1)
ALTER TABLE users ADD COLUMN role VARCHAR(20) DEFAULT 'normal_user';
ALTER TABLE users ADD COLUMN level INT DEFAULT 10;
ALTER TABLE users ADD COLUMN parent_user_id INT;     -- ★ 上下级
ALTER TABLE users ADD COLUMN commission_rate REAL DEFAULT 0.80;
ALTER TABLE users ADD COLUMN commission_rate_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN commission_amount_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN total_income_visible BOOLEAN DEFAULT 1;
ALTER TABLE users ADD COLUMN account_quota INT;

CREATE TABLE user_page_permissions (
  user_id INT, permission_code VARCHAR(100),
  PRIMARY KEY(user_id, permission_code)
);

CREATE TABLE user_button_permissions (
  user_id INT, permission_code VARCHAR(100),
  PRIMARY KEY(user_id, permission_code)
);

CREATE TABLE default_role_permissions (
  role VARCHAR(20),
  permission_type VARCHAR(20),  -- 'page' / 'button'
  permission_code VARCHAR(100),
  PRIMARY KEY(role, permission_type, permission_code)
);
```

### 权限

- **page**: `user:view`
- **button**: `user:create`, `user:edit`, `user:delete`,
  `user:reset-password`, `user:set-permissions`, `user:set-commission`,
  `user:assign-accounts`, `user:set-role`, `user:view-wallet`

---

## 9. 钱包信息 (WalletInfo)

### UI

- 当前用户 / 选中用户 (super_admin 可看任意人) 的支付宝姓名 + 账号
- 跳: 收益统计

### API

```http
GET /api/client/wallet                    (我的)
PUT /api/client/wallet                    (改我的)
GET /api/client/users/:id/wallet          (super_admin 看别人)
PUT /api/client/users/:id/wallet
```

### DB

```sql
CREATE TABLE wallet_profiles (
  user_id INT PRIMARY KEY,
  alipay_name VARCHAR(100),
  alipay_account VARCHAR(100),             -- 加密推荐
  updated_at TIMESTAMP
);
```

### 权限

- **page**: `wallet:view`
- **button**: `wallet:edit`, `wallet:view-others` (super_admin)

---

## 10-12. 萤光计划 (Firefly: 本月 + 历史 + 明细)

### UI

**萤光-本月**:
列: 成员 / 账号 / 粉丝数 / 任务数 / 总金额 / 分成比例 / 扣除分成 / 结算状态

**萤光-历史**:
- 按 年/月 归档
- 列: 年月 / 成员 / 总金额 / 分成 / 扣除分成 / 结算状态 (未结/已结)

**萤光-明细**:
- 按 任务粒度
- 列: 日期 / 成员 / 任务名 / 任务ID / 金额 / 分成 / 扣除 / 状态

**操作**:
- 📤 上传 Excel (导入官方下发的收益表)
- 🔄 同步数据 (从 MCN 拉)
- ✅ 批量标记结清
- ⭐ 加入高转化 (单条/批量, 触发 high_income_dramas 入库)

### API

```http
GET  /api/client/firefly/members
POST /api/client/firefly/members/sync
GET  /api/client/firefly/income            (本月)
GET  /api/client/firefly/income/stats      (聚合卡片)
GET  /api/client/firefly/income/detail
POST /api/client/firefly/income/import     (Excel)
GET  /api/client/firefly/archive
POST /api/client/firefly/income/batch-settlement
POST /api/client/fluorescent/add-to-high-income
```

### DB

```sql
CREATE TABLE firefly_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT NOT NULL,
  account_id INT,
  member_id BIGINT,
  fans_count INT,
  broker_name VARCHAR(100),
  total_amount REAL DEFAULT 0,
  org_task_num INT DEFAULT 0,
  hidden BOOLEAN DEFAULT 0,
  synced_at TIMESTAMP,
  UNIQUE(organization_id, member_id)
);

CREATE TABLE firefly_income (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  account_id INT,
  member_id BIGINT,
  task_id VARCHAR(64),
  task_name VARCHAR(200),
  income_amount REAL,
  commission_rate REAL,
  commission_amount REAL,
  income_date DATE,
  settlement_status VARCHAR(20),           -- pending / settled / partial
  archived_year_month VARCHAR(7),          -- '2026-04'
  created_at TIMESTAMP
);
CREATE INDEX ix_firefly_inc_date ON firefly_income(income_date);
CREATE INDEX ix_firefly_inc_settle ON firefly_income(settlement_status);
```

### 权限

- **page**: `firefly:view-monthly`, `firefly:view-archive`, `firefly:view-detail`
- **button**:
  - `firefly:import`
  - `firefly:sync`
  - `firefly:batch-settlement`
  - `firefly:add-to-high-income`

### 安全

收益字段按 `users.commission_rate_visible` / `commission_amount_visible` /
`total_income_visible` 脱敏:
```python
if not user.commission_amount_visible:
    record["commission_amount"] = "***"
```

---

## 13-15. 星火计划 (Spark: 本月 + 历史 + 明细)

结构与萤光基本一致, 仅多 `首播加ID` 维护:

### 额外按钮

- 📋 批量同步分成比例 (新增 spark_member 时, 把上级用户的 commission_rate 复制下来)
- 📊 同步汇总 (聚合各 archive 进 spark_archive_stats)
- 🆔 维护首播加ID (绑定 spark_first_release_id)

### API

```http
GET  /api/client/spark/members
POST /api/client/spark/members/sync
GET  /api/client/spark/income
GET  /api/client/spark/income/detail
POST /api/client/spark/income/import
GET  /api/client/spark/archive
GET  /api/client/spark/archive/stats
POST /api/client/spark/archive/batch-settlement
PUT  /api/client/spark/archive/:id/settlement
POST /api/client/spark/sync-commission-rate
POST /api/client/spark/first-release-id
```

### DB

```sql
CREATE TABLE spark_members (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  account_id INT,
  member_id BIGINT,
  fans_count INT,
  broker_name VARCHAR(100),
  task_count INT DEFAULT 0,
  hidden BOOLEAN DEFAULT 0,
  first_release_id VARCHAR(64),            -- ★ 首播加ID
  synced_at TIMESTAMP
);

CREATE TABLE spark_income (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  member_id BIGINT,
  task_id VARCHAR(64),
  income_amount REAL,
  start_date DATE,
  end_date DATE,
  organization_id INT,
  created_at TIMESTAMP
);

CREATE TABLE income_archives (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  program_type VARCHAR(20),                -- 'spark' / 'firefly' / 'fluorescent'
  year INT,
  month INT,
  member_id BIGINT,
  account_id INT,
  total_amount REAL,
  commission_rate REAL,
  commission_amount REAL,
  settlement_status VARCHAR(20),           -- pending / settled
  archived_at TIMESTAMP,
  UNIQUE(program_type, year, month, member_id)
);

CREATE TABLE settlement_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  archive_id INT,
  settled_by_user_id INT,
  settled_at TIMESTAMP,
  status VARCHAR(20),
  remark TEXT
);
```

### 权限 (类比萤光, 模块 prefix=spark)

---

## 16. 荧光收益 (FluorescentIncome)

只有"明细"页 + "加入高转化"按钮 (荧光是流水, 不归档).

### API

```http
GET  /api/client/fluorescent/income
GET  /api/client/fluorescent/income/stats
POST /api/client/fluorescent/add-to-high-income
```

### DB

```sql
CREATE TABLE fluorescent_income (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  account_id INT,
  member_id BIGINT,
  task_id VARCHAR(64),
  task_name VARCHAR(200),
  income_amount REAL,
  total_amount REAL,
  org_task_num INT,
  income_date DATE,
  created_at TIMESTAMP
);
```

---

## 17. 短剧收藏池 (CollectPool)

### UI

**筛选**: 关键字 / 平台 / 授权码 / 时间 / 异常 (空URL / 异常链接 / 中文链接)

**列**:
- ID / 标题 / URL / 平台 / 授权码 / 状态 / 添加时间 / 操作

**按钮**:
- ➕ 添加
- 📥 批量导入
- 🔁 去重复制 (deduplicate-and-copy: 把当前 owner 的去重后复制给目标 auth_code)
- 🔄 刷新链接状态
- 🗑️ 批量删除

### API

```http
GET    /api/client/collect-pool?keyword=&platform=&auth_code=&abnormal=
POST   /api/client/collect-pool
PUT    /api/client/collect-pool/:id
DELETE /api/client/collect-pool/:id
POST   /api/client/collect-pool/batch-import
POST   /api/client/collect-pool/deduplicate-and-copy
       body: { source_auth_code, target_auth_code }
POST   /api/client/collect-pool/refresh-status
POST   /api/client/collect-pool/batch-delete
```

### DB

```sql
CREATE TABLE collect_pool (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  drama_name VARCHAR(200),
  drama_url VARCHAR(1000),
  platform VARCHAR(50),                    -- kuaishou / douyin / chengxing
  auth_code VARCHAR(50),
  status VARCHAR(20),                      -- active / abnormal / deleted
  abnormal_reason VARCHAR(100),
  imported_by_user_id INT,
  created_at TIMESTAMP
);
CREATE INDEX ix_cp_url ON collect_pool(drama_url);
CREATE INDEX ix_cp_auth ON collect_pool(auth_code);
```

### 权限

- **page**: `collect-pool:view`
- **button**: `collect-pool:create`, `collect-pool:batch-import`,
  `collect-pool:deduplicate`, `collect-pool:refresh-status`,
  `collect-pool:batch-delete`, `collect-pool:edit`

---

## 18. 高转化短剧 (HighIncomeDramas)

### UI

**筛选**: 关键字
**列**: ID / 剧名 / 来源 (收益归档 source_income_id) / 加入时间 / 操作 (查看链接 / 删除)

### API

```http
GET    /api/client/high-income-dramas?keyword=&page=&size=
POST   /api/client/high-income-dramas
DELETE /api/client/high-income-dramas/:id
GET    /api/client/high-income-dramas/:id/links     (跳 collect_pool 联动)
```

### DB

```sql
CREATE TABLE high_income_dramas (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  drama_name VARCHAR(200),
  source_income_id INT,                    -- 来源 firefly_income / spark_income / fluorescent_income
  source_program VARCHAR(20),
  added_by_user_id INT,
  created_at TIMESTAMP
);
```

---

## 19. 短剧链接统计 (DramaStatistics → drama-links)

### UI

**列**:
- ID / 剧ID / URL / 执行次数 / 成功次数 / 失败次数 / 成功率 / 账号数 / 最后执行时间

**按钮**: 导出 Excel / 批量删除 / 清空

### API

```http
GET    /api/client/statistics/drama-links?keyword=&page=&size=&sort=
POST   /api/client/statistics/drama-links/export
POST   /api/client/statistics/drama-links/batch-delete
POST   /api/client/statistics/drama-links/clear
```

### DB (聚合视图, 由 worker 维护)

```sql
CREATE TABLE drama_link_statistics (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  drama_id INT,
  drama_url VARCHAR(1000),
  organization_id INT,
  execute_count INT DEFAULT 0,
  success_count INT DEFAULT 0,
  failed_count INT DEFAULT 0,
  account_count INT DEFAULT 0,
  last_executed_at TIMESTAMP,
  updated_at TIMESTAMP,
  UNIQUE(drama_url, organization_id)
);
```

---

## 20. 短剧收藏记录 (DramaCollections)

### UI

**列**: 账号UID / 账号名 / 总收藏 / 星火收藏 / 萤光收藏 / 最后收藏时间

### API

```http
GET /api/client/drama-collection-records?keyword=&page=&size=
GET /api/client/drama-collection-records/:account_uid/detail
```

### DB

```sql
CREATE TABLE drama_collection_records (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  account_uid VARCHAR(32),
  account_name VARCHAR(100),
  organization_id INT,
  total_count INT,
  spark_count INT,
  firefly_count INT,
  fluorescent_count INT,
  last_collected_at TIMESTAMP,
  updated_at TIMESTAMP,
  UNIQUE(account_uid, organization_id)
);
```

---

## 21. 外部URL统计 (ExternalUrlStats)

外部 (非快手) URL 收集统计.

### API

```http
GET /api/client/statistics/external-urls?keyword=&page=&size=
```

### DB

```sql
CREATE TABLE external_url_stats (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  url VARCHAR(1000),
  source_platform VARCHAR(50),             -- douyin / xigua / wechat ...
  reference_count INT,
  last_seen_at TIMESTAMP,
  organization_id INT
);
```

---

## 22-23. 橙星推 (CxtUser + CxtVideos)

### UI

**CxtUser**: ID / 用户名 / 平台账号 / 状态 / 添加时间
**CxtVideos**: ID / 视频名 / 视频URL / 关联 cxt_user / 状态 / 添加时间

### API

```http
GET  /api/client/cxt/users
POST /api/client/cxt/users/import
GET  /api/client/cxt/videos
POST /api/client/cxt/videos/batch-import
GET  /api/client/cxt/videos/:id
```

### DB

```sql
CREATE TABLE cxt_users (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  username VARCHAR(100),
  platform_uid VARCHAR(64),
  status VARCHAR(20),
  created_at TIMESTAMP
);

CREATE TABLE cxt_videos (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,
  cxt_user_id INT,
  video_name VARCHAR(200),
  video_url VARCHAR(1000),
  cover_url VARCHAR(1000),
  status VARCHAR(20),
  created_at TIMESTAMP
);
```

---

## 24. 机构信息 (Settings 子页)

### UI

**列**:
- 机构代码 / 名称 / 描述 / 状态 / 视频邀约开关 / Cookie 状态 / 创建时间

**按钮**: ➕ 添加机构 / ✏️ 编辑 / 🗑️ 删除 / 🍪 配置机构 Cookie

### API

```http
GET    /api/client/organizations
POST   /api/client/organizations
PUT    /api/client/organizations/:id
DELETE /api/client/organizations/:id
GET    /api/client/organizations/:id/cookie       (脱敏)
PUT    /api/client/organizations/:id/cookie
```

### DB

```sql
ALTER TABLE organizations ADD COLUMN description TEXT;
ALTER TABLE organizations ADD COLUMN status VARCHAR(20) DEFAULT 'active';
ALTER TABLE organizations ADD COLUMN video_invite_required BOOLEAN DEFAULT 0;

CREATE TABLE organization_cookies (
  organization_id INT PRIMARY KEY,
  cookie_ciphertext BLOB,
  cookie_iv BLOB,
  cookie_tag BLOB,
  cookie_status VARCHAR(20),
  updated_at TIMESTAMP
);
```

### 权限

- **page**: `org:view`
- **button**: `org:create`, `org:edit`, `org:delete`, `org:set-cookie`,
  `org:reveal-cookie` (super_admin)

---

## 25. 公告管理 (Settings 子页)

### API

```http
GET    /api/client/announcements
GET    /api/client/announcements/active
POST   /api/client/announcements
PUT    /api/client/announcements/:id
DELETE /api/client/announcements/:id
```

### DB

```sql
CREATE TABLE announcements (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  organization_id INT,                     -- null = 全平台
  title VARCHAR(200),
  content TEXT,
  level VARCHAR(20),                       -- info / warning / urgent
  pinned BOOLEAN DEFAULT 0,
  active BOOLEAN DEFAULT 1,
  start_at TIMESTAMP,
  end_at TIMESTAMP,
  created_by_user_id INT,
  created_at TIMESTAMP
);
```

### 权限

- **page**: `announcement:view`
- **button**: `announcement:create`, `announcement:edit`, `announcement:delete`

---

## 26. 系统配置 (Settings 子页)

包括: 个人信息 / 操作日志 / 基本设置 / 默认权限模板 / 关于系统.

### API

```http
GET  /api/client/settings/basic              (DB host / 服务地址 / 客户端版本 / 上次同步)
PUT  /api/client/settings/basic
GET  /api/client/settings/role-defaults      (默认权限模板)
PUT  /api/client/settings/role-defaults
GET  /api/client/settings/about              (版本号 + GitHub link)
GET  /api/client/audit-logs?user=&action=&module=&start=&end=
GET  /api/client/audit-logs/stats
```

### DB

```sql
CREATE TABLE operation_logs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id INT,
  organization_id INT,
  action VARCHAR(50),                      -- 'create' / 'update' / 'delete' / 'batch' / 'export' / 'login'
  module VARCHAR(50),                      -- 'account' / 'income' / 'cookie' / ...
  target_type VARCHAR(50),
  target_id VARCHAR(100),
  detail TEXT,                             -- JSON: {before, after, payload}
  ip VARCHAR(64),
  user_agent VARCHAR(255),
  trace_id VARCHAR(16),                    -- 关联 envelope.meta.trace_id
  created_at TIMESTAMP
);
CREATE INDEX ix_log_user ON operation_logs(user_id, created_at);
CREATE INDEX ix_log_module ON operation_logs(module, created_at);
```

---

## 通用规约 (所有页都遵守)

### A. 所有列表 API 统一参数

```
?page=1&size=50&sort=created_at.desc&keyword=...&filter=...
size 上限 200, 默认 20
```

### B. 所有写操作建议带 Idempotency-Key

```
强制: /accounts/batch-*, /accounts/add-by-cookie, /publish/manual,
      /spark/income/import, /firefly/income/import,
      /collect-pool/batch-import, /cloud-cookies/batch-import
```

### C. 所有写操作产生 operation_log

```python
# 中间件 / decorator 自动写
@audit("module=account, action=batch-authorize")
async def post_batch_authorize(...): ...
```

### D. 所有列表自动加 tenant scope

```python
# core/deps.py 后续加 get_tenant_scope
scope = get_tenant_scope(current_user)
stmt = stmt.where(SoftwareAccount.organization_id.in_(scope.organization_ids))
if current_user.role == "normal_user":
    stmt = stmt.where(SoftwareAccount.assigned_user_id == current_user.id)
```

### E. 收益字段脱敏

```python
def mask_income_fields(record: dict, user: User) -> dict:
    if not user.commission_rate_visible:
        record["commission_rate"] = None
    if not user.commission_amount_visible:
        record["commission_amount"] = None
    if not user.total_income_visible:
        record["total_amount"] = None
    return record
```

### F. Cookie 默认脱敏

```python
def mask_cookie(c: bytes) -> str:
    plain = decrypt(c)
    if len(plain) > 32:
        return plain[:8] + "***" + plain[-8:]
    return "***"
```
