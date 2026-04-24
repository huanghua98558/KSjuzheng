# 全数据库总览 (2026-04-20)

> **目的**: 用户准备搭建自己的 SQL 库. 这份文档列**所有可访问的数据源**, 包括:
> - MCN 服务器 MySQL (云端业务库)
> - 本地 SQLite (KS184 继承 + 我们扩张, 含"经验/犯错"机制)
> - MCN Web/API 端点 (除 MySQL 外的活数据源)
> - ZUFN YK 协议 (设备验证, 加密 TCP)

---

## 0. 总账速览

| 数据源 | 类型 | 表/端点数 | 大小 | 我们权限 | 价值 |
|---|---|---|---|---|---|
| **MCN MySQL** `im.zhongxiangbao.com:3306/shortju` | MySQL 5.7 | **50 张表** | **800 MB** | 全 SELECT (账号 `shortju`) | ⭐⭐⭐ 主数据源 |
| **本地 SQLite** `kuaishou_control.db` | SQLite WAL | **89 张表** | **7.3 MB** | RW (我们的 db) | ⭐⭐⭐ 决策/记忆/犯错 |
| **MCN Web SPA** `mcn.zhongxiangbao.com:88` | Vite/Vue (nginx) | 1 个 SPA | 1.15 MB JS | 已登录 | ⭐ 仅前端 |
| **MCN HTTP API** `mcn.zhongxiangbao.com:88/api/*` | REST | **14+ 个 endpoint** | — | Bearer token | ⭐⭐ 14 个已用, 38 个待测 |
| **MCN Verify API** `im.zhongxiangbao.com:8000/api/mcn/verify` | Express | 1 个 endpoint | — | HMAC-SHA256 | ⭐⭐ HMAC 验证流 |
| **MCN 中继协议** `im.zhongxiangbao.com:50002` | TCP | 1 个 endpoint | — | apdid 鉴权 | ⭐⭐ 5 种 shortcut + path 代签 |
| **ZUFN YK 协议** `210.16.171.50:8003` | 自定义 TCP | 4 帧/会话 | — | machine_id 已知 | ⭐ 设备授权 (XOR 加密未破) |

**总计 unique 表**: 50 (MCN) + 89 (本地) - 重叠 ~12 = **~127 unique 表**.

---

## 1. MCN MySQL (50 张表, 800 MB)

### 1.1 元信息

```
host:    im.zhongxiangbao.com:3306
db:      shortju (唯一业务 db, 已确认无遗漏)
user:    shortju
pass:    REPLACE_WITH_MCN_MYSQL_PASSWORD
charset: utf8mb4
mysqld:  5.7.38-log on C:\BtSoft\mysql\MySQL5.7\ (宝塔面板)
views:   0
procs:   1 (manual_kill_sleep_connections, 运维用)
funcs:   0
triggers: 0
```

### 1.2 50 张表按 storage 排序 (TOP 20)

| # | 表 | 行数 | 大小 | 业务 |
|---|---|---|---|---|
| 1 | **kuaishou_urls** | 1,735,000 | **184.7 MB** | 视频 URL 总库 (3× 重复, 514K distinct url) |
| 2 | **task_statistics** | 84,212 | 146.3 MB | 每日任务统计 (按 owner_code) |
| 3 | **spark_drama_info** | 126,296 | **109.5 MB** | 剧库主表 (CPS) ⭐ 已同步 |
| 4 | **mcn_verification_logs** | 493,927 | 70.1 MB | HMAC verify 历史 (我们 sig3 调用) |
| 5 | **spark_violation_photos** | 32,497 | 52.7 MB | 违规视频 (+10K/日 新违规!) |
| 6 | **drama_collections** | 113,257 | 48.7 MB | 收藏池 (账号 → 剧映射) |
| 7 | ks_episodes | 952 | 21.7 MB | 已发剧集 (大字段) |
| 8 | **kuaishou_accounts** | 23,075 | 20.0 MB | KS 账号主库 ⭐ |
| 9 | auto_task_history | 17,745 | 18.7 MB | 任务执行历史 |
| 10 | wait_collect_videos | 21,184 | 18.1 MB | 待采集队列 |
| 11 | iqiyi_videos | 3,635 | 16.2 MB | 爱奇艺视频源 (跨平台) |
| 12 | **fluorescent_members** | 18,812 | 12.1 MB | 萤光实时收益 ⭐ |
| 13 | user_button_permissions | 57,042 | 11.9 MB | 按钮级权限 |
| 14 | admin_operation_logs | 27,469 | 11.4 MB | 管理员操作审计 |
| 15 | **fluorescent_income** | 29,472 | 11.1 MB | 收益事件流 (29,422 unsettled vs 1 settled) |
| 16 | user_page_permissions | 33,564 | 8.0 MB | 页面级权限 |
| 17 | fluorescent_income_archive | 12,489 | 5.6 MB | 老收益归档 |
| 18 | page_permissions | 21,578 | 5.2 MB | 页面权限 |
| 19 | ks_account | 23,251 | 5.0 MB | KS 账号轻表 (历史) |
| 20 | tv_episodes | 6,716 | 3.6 MB | TV 剧集分集 |

### 1.3 6 大业务域分类 (完整 50 张)

详见 `docs/MCN_TABLES_OVERVIEW.md`. 摘要:
- **A. 剧库/视频** (8 表): spark_drama_info, **spark_highincome_dramas (432, 解决 403)**, spark_violation_dramas, spark_violation_photos, drama_collections, kuaishou_urls, wait_collect_videos, collect_pool_auth_codes
- **B. 账号/收益** (17 表): kuaishou_accounts, ks_account, ks_episodes, **cloud_cookie_accounts (876)**, **fluorescent_members/income/income_archive**, firefly_*, spark_*, account_groups, account_summary, kuaishou_account_bindings
- **C. 卡密/权限** (8 表): card_keys (8 行死表), admin_users (1419, **149 captains**), **mcm_organizations (17 家, 我们 org_id=10="火视界短剧")**, page/role/user_*_permissions
- **D. 设备/任务** (5 表): auto_devices, auto_device_accounts, auto_task_history, task_statistics, drama_execution_logs
- **E. 验证/审计** (3 表): **mcn_verification_logs (493K, +18,949 24h)**, admin_operation_logs, operator_quota
- **F. 跨平台/系统** (8 表): **iqiyi_videos (7,313)**, tv_dramas, tv_episodes, tv_publish_record, cxt_titles/author/user/videos, system_announcements

### 1.4 死表 (0 增长, 不必同步)

- `card_keys` (8) — 卡密体系未启用
- `firefly_income` / `firefly_members` — 老萤光归档
- `tv_episodes` / `ks_episodes` — TV 试运行废弃
- `spark_photos` / `drama_execution_logs` / `operator_quota` — 0 行预留表

### 1.5 完整 schema 资源

```
docs/MCN_SCHEMA.md          173 KB  人读
docs/MCN_SCHEMA.json        362 KB  机读
docs/MCN_SCHEMA.sql         70 KB   DDL (可一键 import)
docs/MCN_SCHEMA_DEEP.md     35 KB   字段分布 + 我们足迹 + 跨表关系 + 24h 活跃
docs/MCN_SCHEMA_DEEP.json   134 KB  机读
docs/MCN_TABLES_OVERVIEW.md  6 KB   分类导航
```

---

## 2. 本地 SQLite (89 张表, 7.3 MB) — KS184 经验/犯错机制

> 路径: `C:\Users\Administrator\AppData\Local\KuaishouControl\data\kuaishou_control.db`
>
> **这就是 KS184 客户端遗留 + 我们扩展后的 db**. KS184 的"经验/犯错"系统全在这里:
> healing_playbook (10 规则), autopilot_cycles (883 循环), decision_history (22 决策).

### 2.1 [AI 经验/记忆] 10 张

| 表 | 行数 | 用途 |
|---|---|---|
| `account_decision_history` | 0 | Layer 1 事件级 (每决策 1 行) — v22 新建未启用 |
| `account_strategy_memory` | 1 | Layer 2 聚合级 (每账号 1 行, analyzer 每日重建) |
| `account_diary_entries` | 0 | Layer 3 文本级 (LLM 每周日记) |
| `decision_history` | **22** | 旧版决策日志 (LLM provider + prompt version) |
| `research_notes` | 0 | LLM 研究员产出 (待审批) |
| `strategy_rewards` | **1** | Bandit Thompson Sampling 奖励 |
| `strategy_rules` | 0 | 规则模板 |
| `strategy_memories` | 3 | 旧版记忆 |
| `daily_plans` | 0 | 每日方案主表 |
| `daily_plan_items` | 0 | 方案细项 (account × drama × recipe × image_mode × sched_at) |

### 2.2 [自愈/犯错] 8 张 ⭐ "184 的犯错机制"

| 表 | 行数 | 用途 |
|---|---|---|
| **healing_playbook** | **10** | 规则库 (rate_limited/sig3_error/hls_fail/stuck/mcn_verify_failed + 5) |
| **healing_diagnoses** | 8 | 诊断记录 (auto_resolved + severity) |
| **healing_actions** | 8 | 行动记录 |
| **healing_reports** | **26** | 报告 |
| `rule_proposals` | 0 | LLM 提的新规则 (待审) |
| `upgrade_proposals` | 2 | LLM 提的规则升级 |
| **autopilot_cycles** | **883** | ⭐⭐⭐ 全自动循环! 这是 KS184 的核心 |
| `system_events` | 55 | SSE 事件流 (通知 + 审计) |

### 2.3 [实验 A/B/C] 2 张

| 表 | 行数 | 用途 |
|---|---|---|
| `strategy_experiments` | 0 | 实验主表 (Phase 2 C 任务) |
| `experiment_assignments` | 0 | 账号 × 组分配 |

### 2.4 [任务/批次] 8 张

| 表 | 行数 | 用途 |
|---|---|---|
| **task_queue** | 16 | ⭐ 当前任务队列 (v19 6 字段) |
| `tasks` | 0 | 旧任务 |
| `task_logs` | 0 | 任务日志 |
| `batches` | 0 | 批次 (Phase 2 v24) |
| `batch_tasks` | 0 | 批次任务 |
| `local_task_records` | 0 | 本地任务记录 |
| `web_publish_tasks` | 0 | Web 发布 (legacy) |
| `collection_tasks` | 6 | 采集任务 |

### 2.5 [账号] 7 张

| 表 | 行数 | 用途 |
|---|---|---|
| **device_accounts** | **14** | ⭐ 主账号表 (我们 13 + 1 测试) |
| `devices` | 5 | 物理设备 |
| `device_kuaishou_accounts` | 0 | 设备 × 账号映射 (legacy) |
| `account_groups` | 1 | 账号分组 |
| `account_tier_transitions` | 0 | tier 迁移历史 |
| `account_health_snapshots` | **26** | 健康分快照 |
| `account_performance_daily` | 0 | 每日表现 (待启用) |

### 2.6 [剧/视频] 10 张

| 表 | 行数 | 用途 |
|---|---|---|
| **drama_banner_tasks** | **4,591** | ⭐ MCN 剧库本地镜像 (commission 含 1331 近 30 天分佣) |
| **drama_links** | 33 | 当前可用链接 (清洗后) |
| `drama_authors` | **283** | 作者池 |
| `drama_collections` | 0 | 收藏池 (v3) |
| `drama_templates` | 5 | 剧模板 |
| `drama_hot_rankings` | **225** | 热度榜 (v4 外部 + 内部) |
| `collected_videos` | 215 | 已采集 |
| `wait_collect_videos` | 0 | 待采集 |
| `download_cache` | 25 | 下载缓存 |
| `available_dramas` | 0 | 可用剧池 (v1) |

### 2.7 [收益] 8 张

| 表 | 行数 | 用途 |
|---|---|---|
| **mcn_member_snapshots** | **1,210** | ⭐ MCN 收益快照 (org=10, 580 个) |
| `mcn_income_snapshots` | 18 | 收益历史 |
| `publish_daily_metrics` | 5 | 按账号每日聚合 |
| `publish_results` | **19** | ⭐ 发布结果 (id=22 真发成功) |
| `work_metrics` | 110 | 作品指标 |
| `daily_account_metrics` | 26 | 账号每日指标 |
| `mcn_invitations` | 0 | MCN 邀请记录 |
| **mcn_account_bindings** | **803** | ⭐ 账号 ↔ MCN 绑定关系 |

### 2.8 [配置/审计] 6 张

| 表 | 行数 | 用途 |
|---|---|---|
| **app_config** | **356** | ⭐ 全局配置 (108 → 318 keys 完整对齐 KS184) |
| `app_config_meta` | 99 | 配置元信息 |
| `feature_switches` | 41 | 6 层开关 |
| `audit_logs` | **51** | 审计日志 |
| `admin_operation_logs` | 0 | 管理操作 |
| `platform_trends` | 0 | 平台趋势 |
| `keyword_watch_list` | 15 | 关键词监控 |

### 2.9 [其他] 30 张 (legacy + agent + 中间表)

```
account_drama_execution_logs    50    旧执行日志
account_lifecycle_stages         5    生命周期阶段
account_tags                     8    账号标签
account_vertical_categories      7    垂类分类
agent_runs                     135    Agent 运行记录
browser_sessions                 1    浏览器会话
checkpoints                     22    LangGraph checkpoint
collection_logs              2,018    采集日志 (大量)
content_performance_daily        0    内容每日表现
dashboard_bulk_ops              12    Dashboard 批量操作
device_statistics                3    设备统计
langgraph_checkpoints / writes   0    LangGraph (未用)
manual_review_items              0    人审项
mcn_income_detail_snapshots      0    MCN 详细收益快照 (v22 待启用)
rule_evolution_history          12    规则演进历史
security_config                  1    安全配置
sqlite_sequence                 50    SQLite 内部
strategy_results                 0    策略结果
switch_group_overrides           0    开关组覆盖
system_config                   52    系统配置 (旧)
user_sessions                   23    用户会话
users                            3    用户
writes                          60    LangGraph writes
account_qr_login_attempts        0    QR 登录尝试
account_level_history            0    等级历史
account_published_works          0    已发布作品
account_vertical_stats           0    垂类统计
cxt_mount_links                  0    挂载链接
mode2_configs                    0    Mode2 配置
```

---

## 3. MCN 外部端点 (4 个网络服务)

### 3.1 :88 / :80 / :443 — Vite Vue SPA 后台

```
url:        http://mcn.zhongxiangbao.com:88/
            http://im.zhongxiangbao.com/   (同源)
            https://*:443                   (HTTPS 重定向)
title:      总控台
bundle:     /assets/index-BXe01rQ4.js (1.15 MB after gunzip)
            /assets/index-C9Icgld6.css
status:     200 OK (nginx)
SPA 路由:   /login, /dashboard, /member-query, /page  (从 bundle 反编译)
```

**bundle 已 minified**, /api/* 端点是动态拼接, 只能 grep 出 `/api/auth/my-page-permissions` 一个明文.
真实 endpoint 名单只能通过登录后调 `/api/auth/my-page-permissions` 拿菜单, 或反编译 lazy-load chunks.

### 3.2 /api/* — 14 个已知可用 endpoint (mcn_client.py 实测)

| Endpoint | 方法 | 用途 |
|---|---|---|
| `/api/auth/login` | POST | captain 登录, 返回 64-hex token |
| `/api/auth/my-page-permissions` | GET | 当前用户的菜单权限 |
| `/api/firefly/members` | POST | 萤光成员列表 |
| `/api/firefly/income` | POST | 萤光收益事件 |
| `/api/firefly-external/income` | POST | 外部口径收益 |
| `/api/spark/members` | POST | Spark 成员 |
| `/api/cloud-cookies` | POST | 云 cookie 拉取 |
| `/api/cloud-cookies/owner-codes` | POST | owner_code 列表 |
| `/api/cloud-cookies/batch-update-owner` | POST | 批量改 owner |
| `/api/accounts/direct-invite` | POST | 直接邀请 |
| `/api/accounts/invitation-records` | POST | 邀请记录 |

### 3.3 38 个待测 endpoint (probe_mcn_endpoints.py)

```
/api/auth/me, /api/auth/profile, /api/user/info
/api/firefly/{dramas, hot-dramas, high-income-dramas, pool, collect-pool,
              tasks, banner-tasks, recommend, match, search, query,
              member-tasks, member/tasks, task-list}
/api/firefly-external/{tasks, pool, hot, dramas}
/api/spark/{dramas, pool, tasks, high-income-dramas}
/api/drama/{hot, list, pool, high-income, recommend, collect, match}
/api/collect-pool, /api/high-income-dramas
```

**测试方法** (有 captain token 直接打):
```python
from core.mcn_client import MCNClient
c = MCNClient(); token = c.login()
import requests
r = requests.post(f'{c.base}/api/firefly/dramas',
                  headers={'Authorization': f'Bearer {token}'},
                  json={'page':1,'page_size':10}, timeout=8)
```

### 3.4 :8000 — Express MCN Verify API

```
url:        http://im.zhongxiangbao.com:8000/api/mcn/verify
method:     POST
auth:       HMAC-SHA256(MCN_SECRET, "{uid}:{ts}:{nonce}:{secret_str}")
            (sig3 协议, 已 100% 破解, see CLAUDE.md §J-Frida)
身份:       Express + nodejs (X-Powered-By)
日记录:     493K 条 (mcn_verification_logs), +18,949/24h
```

### 3.5 :50002 — MCN 中继协议

```
url:        im.zhongxiangbao.com:50002 (HTTP/1.1)
auth:       apdid (kuaishou.web.cp.api_ph 字段)
shortcuts:  upload_query, search, upload_finish, submit, generic_relay
encoding:   {path, sig, ...body} 或 {fileName, fileLength, token, apdid}
response:   28-byte HMAC-SHA256[:56] ack 签名 (无业务数据)
client:     core/mcn_relay.py (5 函数 + verify_mcn_response)
```

### 3.6 :8003 — ZUFN YK 验证协议 (210.16.171.50)

```
host:        210.16.171.50:8003 (不是 zhongxiangbao 域名!)
protocol:    自定义 TCP, 非 HTTPS
frame:       magic(6)+len(4 LE)+body
encryption:  WLBufferCrypt XOR keystream (deterministic, no IV)
状态:        密钥未破, 但 4-pad 攻击发现 R4 plaintext 字节级结构
            (pos 0-5: const, pos 6-12: ASCII digits 7 个, pos 13-43: const)
触发时机:    ZUFN.exe 启动时一次, GUI 不可重触发
工具:        tools/probe_wl_full.py (待 ZUFN 启动时跑)
```

---

## 4. 表名重叠分析 (MCN 50 vs 本地 89)

**完全同名 12 张** (本地是 MCN 的客户端缓存或镜像):

| 同名表 | MCN 行数 | 本地行数 | 关系 |
|---|---|---|---|
| device_accounts | 0 (本地概念) | 14 | **本地独有** (KS184 客户端表) |
| drama_collections | 113,257 | 0 | MCN 是云端池, 本地是缓存 |
| drama_templates | (无) | 5 | 本地独有 |
| drama_links | (无) | 33 | 本地独有 (从 collect-pool 同步) |
| collected_videos | (无) | 215 | 本地独有 |
| wait_collect_videos | 21,184 | 0 | MCN 是云端待采队列 |
| download_cache | (无) | 25 | 本地独有 |
| video_processing_cache | (无) | 0 | 本地独有 |
| collection_tasks | (无) | 6 | 本地独有 |
| collection_logs | (无) | 2,018 | 本地独有 |
| account_summary | 1,354 | (无) | MCN 是云端聚合 |
| device_statistics | (无) | 3 | 本地独有 |

**结论**: 同名但语义不同 — MCN 50 张是云端业务库, 本地 89 张大部分是客户端运行库. 真正"信息重叠"只有 `drama_*` (我们从 MCN sync 到本地).

**Unique 表总数 ≈ 50 + 89 - 12 = 127 张**.

---

## 5. 同步频率建议 (按活跃度)

### 5.1 实时镜像 (业务时)
- `mcn_verification_logs` 写入 (我们每次 sig3)
- `spark_violation_*` 读 (避雷)
- `cloud_cookie_accounts` 读 (cookie 失效时)

### 5.2 每小时
- `fluorescent_income` (29K, 持续增加)
- `fluorescent_members` (18K, 收益更新)

### 5.3 每日 04:00
- `spark_drama_info` (126K, +真实 30 天活跃)
- `spark_highincome_dramas` (432, 432 部今日高收益)
- `cloud_cookie_accounts` (876, cookie 池)
- `kuaishou_accounts` (23K, +861/24h)

### 5.4 每周一
- `mcm_organizations` (17, 极少变)
- `admin_users` (1419, 我们关心 captain 树)
- `spark_violation_dramas` (2,434, 全量)

### 5.5 按需
- `iqiyi_videos` (7K), `tv_dramas` (391) — 跨平台扩展时
- `kuaishou_urls` (1.73M) — **太大别同步**, 按 photo_id 单查

### 5.6 死表 (永不同步)

```
card_keys, firefly_income, firefly_members, firefly_income_archive,
tv_episodes, tv_publish_record, ks_episodes, spark_photos,
drama_execution_logs, operator_quota
```

---

## 6. 我们的足迹定位 (确认数据归属)

| Marker | 命中位置 | 数量 | 含义 |
|---|---|---|---|
| `黄华` (owner_code) | `cloud_cookie_accounts.owner_code` | **13** | ✅ 我们 13 账号在 cookie 池 |
| `org_id=10` (火视界短剧) | `fluorescent_members.org_id` | 630 | 我们机构 580+50 历史成员 |
| `REPLACE_WITH_YOUR_PHONE` (captain phone) | `admin_users.username/phone` | 1+ | 黄老板账户 |
| `946` (captain user_id) | `admin_users.id` | 1 | 黄老板主键 |
| `887329560` (captain numeric uid) | `kuaishou_accounts.kuaishou_uid_num` | — | 待验证 |
| `cpkj888` (auth_code) | 多个表 | 待查 | 设备授权码 |
| `TKKN3hjF...` (34字符 token) | (无) | **0** | ❌ **不是 MCN 卡密**, 是 KS184 设备授权 |
| `103876290866` (machine_id) | (无) | **0** | ❌ 纯客户端哈希输入 |

---

## 7. 推荐: 你本地 SQL 库的设计

### 7.1 P0 必抄 (今天就做)

```sql
-- 1. 高收益剧 (解决 CLAUDE.md §6 blocker 4)
CREATE TABLE high_income_dramas LIKE spark_highincome_dramas;  -- 432 行

-- 2. 违规剧黑名单 (避雷)
CREATE TABLE drama_blacklist (
  drama_name VARCHAR(255),
  violation_type VARCHAR(64),
  violation_reason TEXT,
  status VARCHAR(32),
  created_at DATETIME,
  PRIMARY KEY (drama_name)
);  -- 同步 spark_violation_dramas 2,434 行

-- 3. 视频违规 (账号风控)
CREATE TABLE photo_violation_log (
  photo_id BIGINT,
  account_uid VARCHAR(64),
  drama_name VARCHAR(255),
  violation_type VARCHAR(64),
  created_at DATETIME,
  INDEX(account_uid), INDEX(photo_id)
);  -- 同步 spark_violation_photos 32K, +9991/24h

-- 4. MCN 机构 (本地缓存)
CREATE TABLE mcn_organizations LIKE mcm_organizations;  -- 17 行
```

### 7.2 P1 增强 (本周)

```sql
-- 5. MCN HMAC 调用本地审计 (无需同步, 自己产生)
CREATE TABLE mcn_verify_log_local (
  id BIGINT AUTO_INCREMENT,
  uid VARCHAR(64), timestamp INT, nonce VARCHAR(64),
  sig3 VARCHAR(64), result_code INT, response_bytes BLOB,
  fingerprint VARCHAR(32), created_at DATETIME,
  PRIMARY KEY(id), INDEX(uid), INDEX(created_at)
);

-- 6. 任务统计快照 (同步 task_statistics 我们的 owner 部分)
CREATE TABLE task_statistics_local (
  date DATE, owner_code VARCHAR(64), task_type VARCHAR(64),
  success_count INT, fail_count INT,
  PRIMARY KEY (date, owner_code, task_type)
);

-- 7. 跨平台预留
ALTER TABLE drama_links ADD COLUMN platform VARCHAR(16) DEFAULT 'kuaishou';
-- 后续可值 'iqiyi' / 'tv'
```

### 7.3 P2 战略 (随时)

```sql
-- 8. 跨平台视频源镜像
CREATE TABLE iqiyi_videos LIKE iqiyi_videos;     -- 7,313
CREATE TABLE tv_dramas LIKE tv_dramas;            -- 391
CREATE TABLE tv_episodes LIKE tv_episodes;        -- 6,716

-- 9. 经纪人池
ALTER TABLE mcn_member_snapshots ADD COLUMN broker_name VARCHAR(64);
-- fluorescent_members.broker_name 仅 6 distinct, 是关键策略字段
```

---

## 8. Dump 工具 (用户决定后跑)

| 模式 | 内容 | 输出大小 | 工时 |
|---|---|---|---|
| **schema** | 仅 DDL (50 张 CREATE TABLE) | 70 KB ✅ 已在 `MCN_SCHEMA.sql` | 0 |
| **ours** | DDL + 我们 owner=黄华/org=10 相关行 | ~50-100 MB | ~10min |
| **full** | DDL + 全 50 张 800 MB raw | ~1.2-2 GB SQL | ~1-2h |

需要时说"跑 ours" / "跑 full". 我会写 `tools/dump_mcn_data.py`.

---

## 9. 引用

- `docs/MCN_SCHEMA.md` / `MCN_SCHEMA.sql` / `MCN_SCHEMA.json` — 50 张 DDL + sample
- `docs/MCN_SCHEMA_DEEP.md` — 字段分布 + 我们足迹
- `docs/MCN_TABLES_OVERVIEW.md` — 6 域分类
- `docs/KS184_Q_X64_DECOMPILE.md` 第 6 章 — 45 张 SQLite 表 schema (KS184 客户端)
- `core/mcn_client.py` — 14 endpoint 客户端
- `core/mcn_relay.py` — :50002 中继协议
- `tools/mcn_spa_bundle.js` — Vite SPA bundle (1.15 MB, minified)
- `tools/mcn_spa_paths_full.txt` — bundle 提取路径
- `tools/mcn_endpoint_probe_results.json` — endpoint 探测结果

---

## 10. 你下一步选项

| 选项 | 内容 | 工时 |
|---|---|---|
| **(a)** 立刻同步 spark_highincome_dramas 432 行 | 解决今晚 planner 的 403 困境 | ~20min |
| **(b)** 跑 dump_mcn_data.py mode=ours | 抓我们 owner 相关 ~50-100MB 数据到本地 | ~30min |
| **(c)** 跑 dump_mcn_data.py mode=full | 完整 800MB MCN 抓到本地 (1.2GB SQL) | ~1-2h |
| **(d)** 写 sync_mcn_full.py | 4 张表自动同步 (high_income/blacklist/photo_violation/orgs) 接 ControllerAgent | ~2h |
| **(e)** 探完 38 个未测 endpoint | 找到 MCN 暴露但我们没用的额外数据 API | ~30min |
| **(f)** 反编译 SPA lazy-load chunks | 拿全 endpoint 名单 (router config + axios calls) | ~1h |

**推荐**: (a) → (d) → (b). 先解决最痛点, 再建增量同步, 再补全量.
