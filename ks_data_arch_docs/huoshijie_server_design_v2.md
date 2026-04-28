# 火视界 SaaS 服务器架构设计报告 v2

> 2026-04-28 业务方拍板后修订
> 基于 v1 + 关键决策 + 客户端代码现状盘点

---

## 0. 关键决策（已拍板，✓ 锁定）

| # | 决策点 | ✅ 拍板结果 |
|---|---|---|
| 1 | 平台默认抽成 | **不设置默认值，后台手动配置**（默认 0%，每个 MCN 单独设） |
| 2 | 跨 MCN 转账 | **不支持**（账号不能跨 MCN 流转） |
| 3 | 结算周期 | **全线下结算**（系统只统计预估，不调支付接口） |
| 4 | 用户层级 | **5 级**：平台 / MCN / 团长 / 队长 / 号主 |
| 5 | 比例修改 | 实时生效（< 1s）+ 完整审计 |
| 6 | 一人多节点 | 不支持（一人一节点） |

---

## 一、5 级层级精确化（最终版）

```
🏢 平台（火视界 admin）       depth=0   ──── 我们自己
  │ 后台手动配 MCN 比例（可 100% / 90% / 任何值）
  ▼
🌳 MCN 机构（租户）           depth=1   ──── 租户
  │ 后台配团长比例（≤ MCN 自己 total）
  ▼
👔 团长                      depth=2
  │ 后台配队长比例（≤ 团长 total）
  ▼
🪖 队长                      depth=3
  │ 后台配号主比例（≤ 队长 total）
  ▼
👤 号主（持有快手账号 = APP2 登录用户）depth=4   ── 末级，直接持账号
```

**号主 = 实际持有快手账号的人**，登录 APP2 操作。所有快手账号必挂在某个号主名下。

**禁止跨 MCN 转账户**：账号一旦绑定到 MCN-A 树下，不能转到 MCN-B 树下（业务隔离）。仅允许在**同一 MCN 内**调整归属（号主→号主）。

---

## 二、客户端代码现状盘点（重要！服务器侧据此对接）

### A. 客户端 services（24 个 service 模块）

| 模块 | 用途 | 当前状态 |
|---|---|---|
| **api_client.py** | HTTP + mock 路由 | USE_MOCK=True，60+ mock 端点；切真服务器改 1 行 |
| **auth_service.py** | 登录 / 心跳 / 登出 | ★ 测试期直连中翔宝 mcn:88 |
| **captain_session.py** | 船长 token 单例 | ★ 直连中翔宝（生产期改火视界） |
| **mcn_service.py** | MCN 邀约/查询/同步 | ★ 直连中翔宝 mcn:88（4 端点 + firefly/members） |
| **sig_service.py** | sig3 签名 | ★ 直连中翔宝 im:50002/xh |
| **cookie_service.py** | Cookie 池 + 元数据 | 本地 SQLite，AES-GCM 加密 |
| **avatar_service.py** | 头像缓存 | 本地，visionProfile + firefly 双源 |
| **cookie_keepalive.py** | 4 层 Cookie 保活 | 本地 daemon |
| **task_service.py** | 7 池任务调度 | 本地 |
| **publish_service.py** | 8 步发布流水线 | 本地，含 sig3 远端调用 |
| **collector_service.py** | 184 采集 | 本地 |
| **ks_migrate.py** | KS_AUTOMATION 迁移 | ★ 测试期种子（生产期废弃） |
| **upload_service.py** | 数据回流 | mock，待对接火视界 |
| **ai_service.py** | AI 决策接口 | mock 17 端点，待对接火视界 |
| **data_proxy.py** | 数据 KPI 代理 | mock 12 个 /data/* 端点 |
| **lifecycle_service.py** | 账号生命周期诊断 | 本地 |
| **drama_service.py** | 剧管理 | 本地 |
| **preflight_service.py** | 发布前校验 | mock |
| **update_service.py** | 强制更新 | mock |
| **ffmpeg_service.py** | 视频处理 | 本地 |
| **mock_server.py** | 全部 mock 实现 | 60+ 端点 |
| **settings_service.py** | 用户设置 | 本地 |
| **crash_service.py** | 异常上报 | 本地 |
| **ui_data_service.py** | UI 数据兜底 | 走 data_proxy |

### B. 客户端 client.db schema（账号管理已有 8 张表）

```sql
-- 已实装（cookie_service.py 创建）
hsj_cookies_meta         (即 client.db.cookies_meta)
hsj_mcn_bindings         (即 client.db.mcn_bindings) ★ 含 fans_count/task_num/income_total/member_head
hsj_account_strategies   (即 client.db.account_strategies)
hsj_publish_results      (即 client.db.publish_results)
hsj_local_tasks          (7 池任务)
hsj_local_logs           (实时日志)
hsj_app_kv               (KV 配置)
hsj_drama_links          (剧链接池)

-- 已迁移：cookies_meta 加扩展字段（v2 升级）
+ tags_json / vertical_category / owner_phone / owner_real_name
+ browser_port / device_serial / last_chrome_pid
+ deleted_at（软删）

-- mcn_bindings 加字段
+ fans_count / task_num / member_head / broker_name
+ org_id / org_name / user_commission_rate
```

### C. 客户端调用的 60+ HTTP 端点（mock_server 全覆盖）

```
auth (4):       /auth/{login,heartbeat,activate,logout}
update (1):     /update/check
sig (1):        /sig/sign
collect (5):    /collect/{search,url_realtime,sync_pool,seed_pack,ensure_urls}
preflight (1):  /preflight/check
upload (5):     /upload/{result,event,cookie,account,account_health}
llm (1):        /llm/chat
ai (19):        /ai/{advices,run_one,cycles,agents/*,decisions/*,
                     memories,rules*,cost,mode*,emergency_stop,
                     confidence_trend,candidate_pool/mine,insights*,audit_logs}
seed (2):       /seed/{list_mine,submit}
global (1):     /global/dispatch/my_history
cookie (2):     /cookie/{qrcode,qrcode_poll}
data (13):      /data/{health,publish_results,dashboard_kpis,accounts,
                       dramas,anomalies,risks,revenue,line_values,bars,
                       donut,top_accounts_today,publish_status_donut}
mcn (4):        /mcn/{invite,poll,sync_bindings,income_snapshot}
              ★ 这 4 个测试期直连中翔宝；生产期改走火视界代理
```

---

## 三、服务器侧端点 1:1 对接清单（按客户端调用归类）

### 🔴 优先级 P0 — 测试期立刻要

| 客户端调 | 火视界服务器要做 | 工作量 |
|---|---|---|
| `POST /api/v1/accounts/upload` | 接收账号扫码上传 → 写 hsj_account_ownership + hsj_revenue_nodes 关联 | 0.5 天 |
| `POST /api/v1/accounts/cookies/upload` | Cookie 加密备份（云端） | 0.3 天 |
| `GET /api/v1/accounts/cookies/restore` | 换电脑恢复 | 0.2 天 |
| `POST /api/v1/invitations/upload` | 邀请记录上传 | 0.3 天 |
| `GET /api/v1/me/income/preview` | 我本月预估到手 | 0.5 天 |
| `POST /upload/llm_call` | LLM trace 合规归档 | 0.3 天 |
| `POST /api/v1/auth/heartbeat` | 心跳（plan 续期） | 0.2 天 |

**P0 总计 ≈ 2.3 天**，APP2 测试期立刻能用。

### 🟡 优先级 P1 — 1-2 周内

| 端点 | 用途 | 工作量 |
|---|---|---|
| `/api/v1/revenue_nodes/*` (8 端点) | 树形分账 CRUD + 预览 | 2 天 |
| `/api/v1/me/children/estimates` | 上级查下级预估 | 0.5 天 |
| `/api/v1/me/income/by_account` | 按账号拆分收益 | 0.5 天 |
| `/admin/api/*` 后台接口（10+） | 平台 / MCN 后台 CRUD | 3 天 |

### 🟢 优先级 P2 — 1 个月内

| 端点 | 用途 |
|---|---|
| `/api/candidates/*` | AI 决策候选池（替代 mock） |
| `/ai/seed/*` | 19 agent 配置 / 9 节点决策图 |
| `/ai/strategy/*` | 全局 bandit 后验 |
| `/upload/agent_run` | agent 决策完整 trace |
| `/upload/decision_outcome` | 决策结果回流 |
| `/mcn/drama_collision` | 跨 MCN 撞剧 |

### 🔵 优先级 P3 — 2-3 个月内（脱离中翔宝）

| 端点 | 用途 |
|---|---|
| `/api/v1/sig/sign` | 自营 sig3 签名服务 |
| `/api/v1/mcn/invite` | 自营 MCN 邀约（直连快手） |
| `/api/v1/mcn/poll` | 自营查询 |
| `/api/v1/mcn/income_snapshot` | 自营收益拉取 |
| 自家 drama 池采集 | 替代中翔宝 spark_drama_info |

---

## 四、数据库设计（基于 5 级层级 + 决策定稿）

### 表数量精简：30 → 25 张

```
huoshijie 数据库（MySQL 8.x，utf8mb4）
│
├─ A. 用户体系（5）
│   hsj_platforms                平台层（默认 1 行：火视界）
│   hsj_users                    所有登录用户
│   hsj_user_cards               卡密激活
│   hsj_app2_sessions            APP2 会话
│   hsj_app2_actions             操作审计
│
├─ B. 5 级树 + 分账（2）
│   hsj_revenue_nodes            5 级树（platform/mcn/captain/team_leader/host）
│   hsj_revenue_node_audit       配置变更审计
│
├─ C. 账号 + Cookie + 邀请（4）
│   hsj_account_ownership        账号归属（含 revenue_node_id）
│   hsj_account_transfers        同 MCN 内转户审计
│   hsj_account_cookies          Cookie 云备份（端到端加密）
│   hsj_invitations              邀请发起 + 状态机
│
├─ D. 自营大数据（6）
│   hsj_drama_pool
│   hsj_kuaishou_accounts
│   hsj_mcn_members
│   hsj_violation_dramas
│   hsj_wait_collect_videos
│   hsj_drama_authors
│
├─ E. 收益分账（3）
│   hsj_income_raw               原始（自拉快手 / 同步中翔宝）
│   hsj_income_records           分账后（含 splits_json + path_snapshot）
│   hsj_payout_disputes          异议处理（线下结算时用）
│
├─ F. AI（4）
│   hsj_agent_runs
│   hsj_llm_calls
│   hsj_decision_outcomes
│   hsj_strategy_rewards_global
│
└─ G. 系统（1）
    hsj_audit_logs               全局审计
```

废除（v1 → v2 简化）：
- ❌ hsj_payout_runs（不结算无需此表）
- ❌ hsj_commission_configs（被 hsj_revenue_nodes 取代）
- ❌ hsj_experiments / experiment_assignments（暂不做 A/B）
- ❌ hsj_circuit_breakers（应用层用 Redis）
- ❌ hsj_drama_collisions（P2 再加）

### 核心表 hsj_revenue_nodes（精简定稿）

```sql
CREATE TABLE hsj_revenue_nodes (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,

  -- 树结构
  parent_id BIGINT NULL,
  level ENUM('platform','mcn','captain','team_leader','host') NOT NULL,
  depth TINYINT NOT NULL,                       -- 0-4
  path VARCHAR(255),                             -- "1/3/12/45/78"

  -- 关联
  user_id BIGINT,                                -- 节点对应的 APP2 用户（platform 节点为 NULL）
  mcn_id BIGINT,                                 -- 该节点所在 MCN（platform 节点为 NULL）
                                                  -- 用于"禁止跨 MCN 转户"约束
  name VARCHAR(100),
  contact_phone VARCHAR(20),

  -- 分账（绝对总额%）
  total_share_pct DECIMAL(5,2) NOT NULL,
  -- platform 节点 = 100（用于约束："给 MCN 配的总和 ≤ 100"）
  -- mcn 节点 = 配置值（如 100 / 90 / 80）
  -- captain/team_leader/host 都按上级配的算

  -- 配置
  configured_by_user_id BIGINT,
  configured_at DATETIME,
  effective_from DATETIME NOT NULL,
  effective_until DATETIME NULL,
  status ENUM('active','suspended','removed') DEFAULT 'active',
  notes TEXT,

  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

  FOREIGN KEY (parent_id) REFERENCES hsj_revenue_nodes(id),
  INDEX idx_parent (parent_id, status),
  INDEX idx_path (path),
  INDEX idx_user (user_id),
  INDEX idx_mcn (mcn_id),                        -- ★ 跨 MCN 隔离查询用

  CHECK (total_share_pct BETWEEN 0 AND 100)
);
```

### 账号归属转移（**同 MCN 内可转，跨 MCN 禁止**）

#### 业务场景（同 MCN 内允许的转移）

| 场景 | 流向 | 触发方 | 审批方 |
|---|---|---|---|
| 号主辞职 / 跑路 | 号主 A → 号主 B | 队长 | 上级团长 + MCN 二级审批 |
| 队长换人 | 整个队长子树 → 新队长 | 团长 | MCN 二级审批 |
| 团长合并/拆分 | 团长 A 部分账号 → 团长 B | MCN | MCN 自审 |
| 号主主动转给同事 | 号主 A → 号主 B（同队） | 当前号主 + 接收方 | 队长审批 |

#### 不允许的转移

```
❌ MCN-火视界 → MCN-客户A 树下             跨 MCN，DB 拦截
❌ 号主 → 平台直管（绕过 MCN 树）           跳级，业务规则拦截
❌ 号主 → 已 removed 的节点                 状态校验拦截
```

#### 转户校验（应用层 + DB 双层）

```python
def transfer_account(kuaishou_uid, new_node_id, reason, operator_user_id):
    """同 MCN 内账号转户。"""
    cur = get_current_ownership(kuaishou_uid)
    if not cur:
        raise BusinessError("账号不存在")
    cur_node = get_node(cur.revenue_node_id)
    new_node = get_node(new_node_id)

    # 1. 跨 MCN 拦截
    if new_node.mcn_id != cur_node.mcn_id:
        raise BusinessError("不允许跨 MCN 转户")
    # 2. 目标节点状态
    if new_node.status != 'active':
        raise BusinessError("目标节点不可用")
    # 3. 必须 host 级别（号主才持账号）
    if new_node.level != 'host':
        raise BusinessError("账号只能挂到号主节点上")
    # 4. 操作权限：当前归属树的上级 / MCN 管理员
    if not can_operate_on_node(operator_user_id, cur.revenue_node_id):
        raise PermissionError("无权操作")
    # 5. 接收方同意（如非操作员强制）
    if not has_accept_token(new_node.user_id, kuaishou_uid):
        raise BusinessError("待接收方在 APP2 内确认")

    with db.transaction():
        # 6. 写转户审计（before/after 完整快照）
        INSERT hsj_account_transfers (
          kuaishou_uid, from_node_id=cur.revenue_node_id,
          to_node_id=new_node_id,
          from_owner_user_id=cur.owner_user_id,
          to_owner_user_id=new_node.user_id,
          reason, operator_user_id,
          transferred_at=NOW()
        )
        # 7. 更新归属
        UPDATE hsj_account_ownership SET
          owner_user_id = new_node.user_id,
          revenue_node_id = new_node_id
        WHERE kuaishou_uid = ?
        # 8. 历史收益不追溯（按 income_records.path_snapshot 不变）
```

#### DB 触发器辅助拦截（兜底）

```sql
DELIMITER $$
CREATE TRIGGER trg_ownership_no_cross_mcn
BEFORE UPDATE ON hsj_account_ownership
FOR EACH ROW
BEGIN
  IF NEW.revenue_node_id != OLD.revenue_node_id THEN
    DECLARE old_mcn BIGINT;
    DECLARE new_mcn BIGINT;
    SELECT mcn_id INTO old_mcn FROM hsj_revenue_nodes WHERE id = OLD.revenue_node_id;
    SELECT mcn_id INTO new_mcn FROM hsj_revenue_nodes WHERE id = NEW.revenue_node_id;
    IF old_mcn != new_mcn THEN
      SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'cross-MCN transfer forbidden';
    END IF;
  END IF;
END$$
DELIMITER ;
```

#### 历史收益归属（关键）

转户**不追溯历史收益**。即：

```
账号 X 在 2026-04 月归 号主 A
账号 X 在 2026-05-15 转给 号主 B
  ↓
2026-04 月所有 income_records 的 splits_json 仍按 A 路径分（不动）
2026-05-15 之后的新 income_records 按 B 路径分

实现：每条 hsj_income_records 写入时拍快照 path_snapshot
      未来再查时按 snapshot 算，不会被节点变更影响
```

#### 转户 API

```
POST /api/v1/accounts/{kuaishou_uid}/transfer
权限：cur owner 的上级（队长 / 团长 / MCN）
Body:
{
  "new_owner_user_id": 1234,           // 新号主
  "new_revenue_node_id": 5678,          // 新节点 id
  "reason": "号主辞职，转给同队 B",
  "require_accept": true                // 是否需要接收方在 APP2 确认
}
Response:
{
  "ok": true,
  "transfer_id": 9012,
  "status": "pending_accept" | "completed",
  "expires_at": "..."  // 接收方未在 24h 内确认 → 自动撤销
}
```

#### 转户记录表（hsj_account_transfers）

```sql
CREATE TABLE hsj_account_transfers (
  id BIGINT PRIMARY KEY,
  kuaishou_uid VARCHAR(64),
  
  -- 转出方
  from_node_id BIGINT,
  from_owner_user_id BIGINT,
  
  -- 转入方
  to_node_id BIGINT,
  to_owner_user_id BIGINT,
  
  -- 同 MCN 校验冗余
  mcn_id BIGINT NOT NULL,                -- 双方共属的 MCN
  
  -- 操作
  operator_user_id BIGINT,                -- 谁发起的（队长/团长/MCN）
  reason TEXT,
  status ENUM('pending_accept','completed','rejected','expired'),
  
  initiated_at DATETIME,
  accepted_at DATETIME,
  completed_at DATETIME,
  
  INDEX idx_uid (kuaishou_uid, completed_at),
  INDEX idx_mcn (mcn_id),
  INDEX idx_status (status, initiated_at)
);
```

---

## 五、API 端点完整清单（35 个）

### 用户体系 (5)
```
POST /api/v1/auth/login              手机号+密码+owner_code
POST /api/v1/auth/heartbeat          60s 心跳
POST /api/v1/auth/logout             登出
POST /api/v1/auth/activate           卡密激活
GET  /api/v1/me                      我的资料 + 节点信息
```

### 账号归属 (5)
```
POST /api/v1/accounts/upload         ★ APP2 扫码后必调
GET  /api/v1/accounts/my             我名下账号列表
POST /api/v1/accounts/cookies/upload Cookie 云备份
GET  /api/v1/accounts/cookies/restore?uid=  换电脑恢复
POST /api/v1/accounts/{id}/transfer  同 MCN 内转户（跨 MCN 拒绝）
```

### 邀请 (4)
```
POST /api/v1/invitations/create      发起邀请（火视界自营 or 转发中翔宝）
GET  /api/v1/invitations/my          我发的邀请
POST /api/v1/invitations/{id}/poll   主动查询状态
DELETE /api/v1/invitations/{id}      撤销
```

### 分账树 (8)
```
GET  /api/v1/revenue_nodes/me                我的节点信息
GET  /api/v1/revenue_nodes/me/effective_pct  我的实际自留 %
GET  /api/v1/revenue_nodes/{id}/children     下级列表
POST /api/v1/revenue_nodes/{parent_id}/child 创建下级
PUT  /api/v1/revenue_nodes/{id}/share_pct    改子节点比例
DELETE /api/v1/revenue_nodes/{id}            删除节点
POST /api/v1/revenue_nodes/preview           改前预览
GET  /api/v1/revenue_nodes/audit             变更历史
```

### 收益预估 (5)
```
GET  /api/v1/me/income/preview?period=YYYY-MM  我本月预估到手
GET  /api/v1/me/income/by_account              按账号拆分
GET  /api/v1/me/children/estimates             下级预估
GET  /api/v1/me/income/history                 历史
POST /api/v1/me/income/dispute                 提出异议
```

### MCN 转发（冷启动期）(4)
```
POST /api/v1/mcn/invite              → 转发中翔宝 mcn:88/api/accounts/direct-invite
POST /api/v1/mcn/poll                → 转发 invitation-records
GET  /api/v1/mcn/sync_bindings       → cloud-cookies
GET  /api/v1/mcn/income_snapshot     → firefly/members + firefly-external/income
```

### AI 合规 (3)
```
POST /upload/llm_call                LLM 调用 trace
POST /upload/agent_run               19 Agent 决策记录
POST /upload/decision_outcome        决策结果回流
```

### sig3 (1)
```
POST /api/v1/sig/sign                → 转发中翔宝 im:50002/xh（生产期自营）
```

---

## 六、各级后台 UI（4 套独立 Web）

| 后台 | 域名 | 角色 | 核心模块 |
|---|---|---|---|
| 平台后台 | admin.huoshijie.com | 火视界管理员 | MCN 管理 / 撞剧 / 全平台 KPI / 卡密发放 / 系统配置 |
| MCN 后台 | mcn.huoshijie.com | MCN 租户 | 团长管理 / MCN 树下账号 / MCN 自留收益 |
| 团长后台 | team.huoshijie.com | 团长 | 队长管理 / 团下账号 / 团长自留收益 |
| 队长后台 | leader.huoshijie.com | 队长 | 号主管理 / 队下账号 / 队长自留收益 |

号主无独立后台 — 直接在 APP2 客户端【收益分析】页查看。

---

## 七、测试期 → 生产期 阶段过渡

### 测试期（**当前**，2026-04 ~ 2026-06）

```
APP2 客户端：
├ 登录          → 中翔宝 mcn:88/api/auth/login（船长账号）
├ 账号同步       → 中翔宝 cloud-cookies
├ MCN 邀约/查询   → 中翔宝 direct-invite / invitation-records
├ 收益数据       → 中翔宝 firefly/members（实测可拉 15/20 真数据）
├ sig3          → 中翔宝 im:50002/xh
└ 上传归属       → 火视界 /api/v1/accounts/upload

火视界服务器最小集（Phase 1）：
✓ /api/v1/accounts/upload          已设计
✓ /api/v1/invitations/upload       已设计
✓ /api/v1/revenue_nodes/*          已设计
✓ /api/v1/me/income/preview        已设计
✓ /upload/llm_call                 已设计
✓ /api/v1/auth/heartbeat           已设计
```

### 过渡期（3-6 个月）— 逐步切除中翔宝依赖

| 顺序 | 内容 | 切换风险 |
|---|---|---|
| 1️⃣ | 收益自拉：`hsj_income_raw` 自拉快手 firefly API | 低（数据双源对比可灰度） |
| 2️⃣ | sig3：自营或换签名服务商 | 中（要 Frida 抓 / 商务对接） |
| 3️⃣ | 邀约：火视界自营对接快手 MCN | 高（要快手商务授权） |
| 4️⃣ | drama 池：自家采集（已有 184 链路） | 低（采集器已实装） |

### 生产期

```
APP2 → 全部 huoshijie.com:443
火视界 → 不再调用 zhongxiangbao.com
中翔宝镜像表（zxb_mirror_*）下线
```

---

## 八、客户端代码现状的"测试 → 生产"切换 checklist

| 文件 | 测试期行为 | 生产期改动 |
|---|---|---|
| `services/api_client.py` | USE_MOCK=True | 改 `USE_MOCK=False` + `BASE_URL='https://api.huoshijie.com/v1'` |
| `services/captain_session.py` | MCN_BASE 直连中翔宝 | 改 `MCN_BASE='https://api.huoshijie.com'` |
| `services/sig_service.py` | 调中翔宝 :50002 | 改调火视界 `/api/v1/sig/sign`（透明转发或自营） |
| `services/mcn_service.py` | _DIRECT_HANDLERS 直连 | 删除 _DIRECT_HANDLERS，统一走 api_client.post() |
| `services/auth_service.py` | login 直调中翔宝 | login 调火视界 `/api/v1/auth/login`（火视界内部转发或自验证） |
| `services/ks_migrate.py` | 测试期种子 | 生产期废弃（用户自己扫码注册） |
| `services/mock_server.py` | 60+ 端点 mock | 生产期不加载（USE_MOCK=False 时跳过） |
| `services/upload_service.py` | upload mock | 改真 `/upload/*` |
| `services/ai_service.py` | 19 个 ai_* mock | 改真 `/ai/*` 火视界 |

**全部改动 = ~10 行**（主要是 BASE_URL + USE_MOCK 切换）。

---

## 九、Phase 1 实施 — 立刻可做（最小可用）

### 服务器侧（火视界后端开发者）

| 任务 | 工作量 | 输出 |
|---|---|---|
| 建库 + 12 张核心表 | 0.5 天 | DDL 脚本 |
| 7 个 P0 端点 | 2 天 | FastAPI / Flask 路由 |
| 简单后台原型（admin） | 2 天 | Vue / React 页面 |
| 部署 + Nginx + Redis | 0.5 天 | docker-compose |

**Phase 1 总计 5 天**，APP2 测试期立刻可用。

### 客户端侧（APP2 已有）

```
✓ services/auth_service.py        测试期已直连中翔宝
✓ services/captain_session.py     已实装
✓ services/mcn_service.py         已实装（含 firefly/members 拉真数据）
✓ services/cookie_service.py      schema 已就位
✓ services/ks_migrate.py          KS_AUTOMATION 迁移
✓ pages/pro/accounts.py           账号管理页（含分账列）
✓ pages/pro/burst_radar.py        爆款雷达
✓ pages/team/ai_hub/              5 Tab AI 中枢

待补：
→ services/huoshijie_client.py   新建（封装火视界 API 调用）
→ pages/common/income_analysis.py 收益分析页（显示 self_pct + 预估）
→ services/upload_service.py     接通 /api/v1/accounts/upload
```

---

## 十、风险与缓解

| 风险 | 缓解 |
|---|---|
| 中翔宝接口变化导致同步中断 | 抓异常 → 降级用上次缓存；监控告警；优先迁自营 |
| 节点配置错误导致比例混乱 | DB CHECK + API 校验 + 后台预览 + 完整审计可回滚 |
| Cookie 上传被竞争（多设备登录同账号） | cookie_version 递增 + 旧版本拒收 |
| 跨 MCN 误转户 | DB CHECK + 应用层校验双保险 |
| 收益数据延迟（中翔宝/自营拉取慢） | 标 "数据来源时间" 给用户；缓存 30min |
| 大量节点导致 path 查询慢 | 物化路径 + 索引 + Redis 缓存（按 user_id） |

---

## 十一、关键约束（红线）

```
✓ 火视界 = 独立 MCN，不是中翔宝下游
✓ 5 级树：平台 / MCN / 团长 / 队长 / 号主
✓ 跨 MCN 不可转账户（DB + 应用层双校验）
✓ 系统只统计预估，结算线下进行
✓ 比例修改实时生效 + 完整审计可回滚
✓ 平台抽成默认 0%，按 MCN 后台配置
✓ Cookie / Token / 配置变更全部 audit_log
✓ 客户端不缓存比例（每次实时查）
✗ 不暴露原始 sig3 / token / Captain 凭证给客户端
✗ 不让低权限看高权限的数据（行级隔离按 path 前缀）
✗ 不调用任何支付接口（结算线下）
```

---

## 十二、附录 A — 与 CLAUDE.md v4 红线对齐

| CLAUDE.md 红线 | 本设计 |
|---|---|
| #1 客户端不实现 sig3 | ✅ 测试期走中翔宝；生产期走火视界 |
| #2 客户端不存 LLM key 明文 | ✅ AES-GCM 加密落 cookies.enc |
| #3 客户端跑 19 Agent | ✅ 火视界服务器只提供数据 + 知识种子 |
| #5 决策跑客户端 | ✅ 一致 |
| #6 184 采集本地 | ✅ 火视界镜像辅助 |
| #7 200 号硬上限 | ✅ cookie_service 已实装 |
| 数据流单向 | ✅ 客户端拉数据 + 客户端 → 服务器回流 |

---

## 十三、附录 B — 客户端 Phase 1 切换代码 diff（≈ 10 行）

```python
# services/api_client.py 顶部
- USE_MOCK = True
+ USE_MOCK = False
+ BASE_URL = "https://api.huoshijie.com/v1"

# services/captain_session.py
- MCN_BASE = "http://mcn.zhongxiangbao.com:88"
+ MCN_BASE = "https://api.huoshijie.com"

# services/sig_service.py
- SIG_BASE = "http://im.zhongxiangbao.com:50002"
+ # 走 api_client.post('/sig/sign', ...) 由火视界服务器侧透明转发

# services/mcn_service.py
- 删除 _DIRECT_HANDLERS（4 个直连函数）
+ 全部走 api_client.post('/mcn/invite' ...)

# main.py
- _trigger_login_migrate()  # 测试期 KS_AUTOMATION 迁移
+ # 生产期不需要：用户扫码 → /api/v1/accounts/upload 自动归属

# pages/pro/accounts.py 默认数据源
- _load_real_accounts_or_mock 优先 mcn_bindings + ks_migrate fallback
+ 优先 GET /api/v1/accounts/my （返回已经 JOIN 好的）
```

---

## 十四、下一步

| 选项 | 工作量 | 解锁 |
|---|---|---|
| **A.** Phase 1 完整 12 表 DDL（约 1500 行 SQL） | 我 1 天 | 后端建库 |
| **B.** Phase 1 7 个 P0 API 详细规格书（payload / response / 错误码 / SQL） | 我 1 天 | 后端对接 |
| **C.** 各级后台 UI 详细线框图（4 套 30+ 页面） | 我 1 天 | 前端开工 |
| **D.** 客户端"切真服务器"的 10 行 diff PR | 我 0.5 天 | 测试期切自营预演 |

报告 v2 完毕，待业务方进一步指示。

---

**文档结束** | 修订记录：
- v1（2026-04-28 上午）：初稿，待业务方拍板
- v2（2026-04-28 下午）：业务方拍板 4 项决策 + 客户端代码现状盘点 + 5 级层级精确化
