# MCN MySQL 50 张表全景速查 (2026-04-20)

> Source: `im.zhongxiangbao.com:3306/shortju` — 完整字段+样本见同目录 `MCN_SCHEMA.md`
> 完整 DDL 见 `MCN_SCHEMA.sql` (70KB), 机器读 JSON 见 `MCN_SCHEMA.json`
>
> **CLAUDE.md §2.4 只列了 6 张关键表, 实际有 50 张, 44 张未在 CLAUDE.md 文档化**.
> 本文按业务域分 6 大类供你设计本地 SQL 库参考.

---

## A. 剧库 / 视频内容 (8 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **spark_drama_info** ⭐ | 126,296 | id, biz_id, drama_name, promotion_type, view_status, commission_rate, end_at, deleted | **效果计费 CPS 剧主表** (我们已同步到 drama_banner_tasks) |
| **spark_highincome_dramas** ⭐⭐⭐ | 432 | id, title (UNI), created_at | **高收益剧名单** ⭐ (一直 403 的那个 endpoint 真值, 432 部今日热剧) |
| **spark_violation_dramas** ⭐ | 2,434 | drama_name, violation_type, violation_reason, photo_url, status, created_at | **违规剧黑名单** (避雷, 跳过这些就少封号) |
| **spark_violation_photos** | 32,497 | photo_id, account_uid, drama_name, violation_type, ... | 违规视频粒度 (按 photo) |
| **drama_collections** | 113,257 | drama_name, collect_type, account_uid, ... | 收藏池 (账号→剧映射) |
| **kuaishou_urls** | 1,734,694 | photo_id, url, ... | **视频 URL 总库** (173 万!) |
| **wait_collect_videos** | 21,170 | photo_id, status, retry_count, ... | 待采集队列 |
| **collect_pool_auth_codes** | 1,423 | auth_code, valid_until, ... | 采集池授权码 |

## B. 账号 / 收益 / 成员 (10 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **kuaishou_accounts** | 23,075 | uid, nickname, owner_code, login_status, level, ... | KS 账号主库 |
| **ks_account** | 23,251 | uid, ... | KS 账号轻表 (历史) |
| **ks_episodes** | 1,043 | uid, drama_id, episode_no | 已发剧集索引 |
| **kuaishou_account_bindings** | 2 | account_uid, mcn_org_id, ... | 账号 ↔ 机构绑定 |
| **cloud_cookie_accounts** ⭐ | 876 | owner_code, account_name, cookies, last_sync, ... | **云 cookie 池** (我们已在用) |
| **fluorescent_members** ⭐ | 18,812 | member_id, nickname, total_amount, org_task_num, ... | **萤光实时收益** (单账号汇总) |
| **fluorescent_income** ⭐ | 29,472 | task_id, member_id, income, created_at, ... | 萤光收益事件流 |
| **fluorescent_income_archive** | 12,489 | (同上+历史归档) | 老收益归档 |
| **firefly_members** | 218 | member_id, ... | 老萤光成员 |
| **firefly_income** | 3,558 | task_id, member_id, income | 老萤光收益事件 |
| **spark_members** | 1,198 | member_id, nickname, total_amount, ... | Spark 计划成员 |
| **spark_org_members** | 6,029 | member_id, org_id, ... | 机构 × 成员关联 |
| **spark_income** | 80 | task_id, member_id, income, task_period, ... | 新 CPS 收益 |
| **spark_income_archive** | 3,315 | (历史归档) | 新 CPS 归档 |
| **spark_photos** | 0 | photo_id, ... | (空表, 待启用) |
| **account_groups** | 1,593 | group_name, owner_id, accounts | 账号分组 |
| **account_summary** | 1,354 | uid, total_income, last_publish_at, ... | 账号汇总指标 |

## C. 卡密 / 授权 / 权限 (8 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **card_keys** ⭐ | **8** | card_code (16字符 UNI), card_type (monthly/quarterly), status (unused/active/used/expired), used_by_auth_code, expires_at | **卡密体系主表** (16 字符小写英数, 月卡/季卡, 绑授权码) |
| **card_usage_logs** | 54 | card_code, auth_code, action (validated/activated/verified) | 卡密使用流水 |
| **admin_users** ⭐ | 1,419 | username, password_hash, role, default_auth_code, **commission_rate**, **parent_user_id** (团长树), is_oem, oem_config (贴牌 JSON), **organization_access** | **管理员表** (含团长 + 分成比例 + 贴牌系统) |
| **mcm_organizations** ⭐ | **17** | org_name, org_code, is_active, include_video_collaboration | **机构列表** (我们 org=10, 共 17 家) |
| **page_permissions** | 21,578 | user_id, page_path, ... | 页面权限 |
| **role_default_permissions** | 246 | role, page_path | 角色默认权限模板 |
| **user_button_permissions** | 57,042 | user_id, button_id, allowed | 按钮级权限 |
| **user_page_permissions** | 33,564 | user_id, page_id, allowed | 页面级权限 |

> ⚠️ 你的卡密 `TKKN3hjF3i1ThK5CRXDT6AAGKC4DCGT5FC` (34 字符) **不在 card_keys 里** (它是 16 字符).
> 推测是设备授权码 (auth_code), 不是产品卡密.

## D. 设备 / 自动化 / 任务 (5 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **auto_devices** | 472 | device_serial, owner_code, device_name, status, last_active_at, ... | **物理设备主表** (KS184 注册设备) |
| **auto_device_accounts** | 641 | device_serial, account_uid, account_name, ... | 设备 × 账号绑定 |
| **auto_task_history** | 17,745 | device_serial, task_type, status, started_at, ended_at, error_msg, ... | **任务执行历史** (KS184 自动化 audit) |
| **task_statistics** | 84,212 | owner_code, date, task_type, success_count, fail_count, ... | **每日任务统计聚合** |
| **drama_execution_logs** | 0 | (空表) | 预留 |

## E. 验证 / 风控 / 审计 (3 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **mcn_verification_logs** ⭐⭐ | **493,549** | uid, client_ip, status (SUCCESS/FAILED), is_mcn_member, error_message, created_at | **HMAC verify 历史** (49.4 万条, 我们的 sig3 调用都在这!) |
| **admin_operation_logs** | 27,463 | admin_id, action, target, ip, created_at | 管理员操作审计 |
| **operator_quota** | 0 | (空表) | 预留配额表 |

## F. 跨平台扩展 / 系统 (8 表)

| 表 | 行数 | 关键字段 | 业务作用 |
|---|---|---|---|
| **iqiyi_videos** | 7,313 | video_id, title, ... | **爱奇艺视频源** (KS184 跨平台扩展!) |
| **tv_dramas** | 391 | drama_name, total_episodes, ... | TV 剧集主表 |
| **tv_episodes** | 7,496 | drama_id, episode_no, video_url, ... | TV 剧集分集 |
| **tv_publish_record** | 6 | (TV 剧发布记录) | 试运行 |
| **cxt_titles** | 6,096 | title, ... | 标题池 (cxt 命名空间) |
| **cxt_author** | 298 | author_uid, author_name, ... | cxt 作者 |
| **cxt_user** | 150 | user_id, ... | cxt 用户 |
| **cxt_videos** | 1,503 | video_id, title, author_uid, ... | cxt 视频 |
| **system_announcements** | 4 | title, content, level (info/warn), is_active | 系统公告 |

---

## 🔥 给"搭建自己 DB"的 5 个建议

### 1. 必抄表 (P0, 立刻同步)
- `spark_drama_info` — **剧库**, 每日全量同步 (我们已做, 在 `drama_banner_tasks`)
- `spark_highincome_dramas` — **高收益剧**, 432 行, 直接 SELECT 解决我们 403 问题
- `cloud_cookie_accounts` — **cookie 池**
- `fluorescent_members` + `fluorescent_income` — **收益反馈** (Analyzer 闭环依赖)
- `mcm_organizations` — **机构表**

### 2. 高价值新发现 (P1, 你之前不知道)
- `spark_violation_dramas` (2,434) — **违规剧黑名单** (本地建 `drama_blacklist` 表自动跳过)
- `spark_violation_photos` (32,497) — **违规视频粒度** (account_uid 维度风控预警)
- `mcn_verification_logs` (49.4万) — 你能反查自己每个 HMAC 调用结果, **debug 必备**
- `task_statistics` (8.4万) — 每日任务聚合 (省得自己重算)

### 3. 跨平台扩展能力 (P2, 战略)
- `iqiyi_videos` + `tv_dramas` + `tv_episodes` — KS184 已经支持爱奇艺 + TV 剧
- 你可以本地预留 `platform` 字段 (`kuaishou` / `iqiyi` / `tv`), 一开始填 `kuaishou`

### 4. 不必抄但要意识到 (info-only)
- `card_keys` (8) — 你的 34 字符 token 不是卡密
- `admin_users` (1419) — 含**团长树** (`parent_user_id`) + **贴牌系统** (`oem_config`) + **分成可配置** (`commission_rate`)
- `kuaishou_urls` (173 万) — 这是真的 173 万, 别抄, 按需 API 拉

### 5. 本地 SQL 设计建议
```
你的本地 DB                 ← 对应 MCN 表
─────────────────────────────────────────
drama_banner_tasks         ← spark_drama_info (含 commission)
drama_blacklist (新)       ← spark_violation_dramas (违规库, 排程时跳过)
photo_violation_log (新)   ← spark_violation_photos (账号风控)
high_income_dramas (新)    ← spark_highincome_dramas (TOP 432 强信号)
device_accounts.cookies    ← cloud_cookie_accounts (已做)
mcn_member_snapshots       ← fluorescent_members (已做)
publish_daily_metrics      ← fluorescent_income 聚合 (已做)
mcn_organizations (新)     ← mcm_organizations (本地缓存 17 家)
mcn_verify_log_local (新)  ← 自己每次 sig3 调用的本地审计 (无需同步)
```

---

## 同步频率建议

| 频率 | 表 |
|---|---|
| **实时** (业务时) | mcn_verification_logs (写入), spark_violation_* (读) |
| **每小时** | fluorescent_income, fluorescent_members |
| **每日 04:00** | spark_drama_info, spark_highincome_dramas, cloud_cookie_accounts |
| **每周一** | mcm_organizations, admin_users (我们关心的部分), spark_violation_dramas (全量) |
| **按需** | iqiyi_videos, tv_dramas, kuaishou_urls (太大, 别全拉) |
