# KS 短剧矩阵系统数据库详细表结构设计文档

## 1. 文档目标

本文档以 `D:\ks_automation` 现有 SQLite 库和当前代码为基础，输出可直接用于开发和迁移的数据库详细设计。

目标：

- 对现有表做角色归类
- 明确哪些保留，哪些扩展，哪些新增
- 给出生产级矩阵系统所需核心表结构
- 给出 SQLite 到 PostgreSQL 的演进路线

---

## 2. 现有数据库基础盘点

## 2.1 当前已存在的核心表

根据 `schema_sqlite.sql`、迁移脚本和 `db_manager.py`，当前已存在或已被代码依赖的主要表有：

- `devices`
- `device_statistics`
- `tasks`
- `task_logs`
- `batches`
- `batch_tasks`
- `drama_links`
- `collection_tasks`
- `collected_videos`
- `collection_logs`
- `device_accounts`
- `device_kuaishou_accounts`
- `local_task_records`
- `drama_collections`
- `web_publish_tasks`
- `mode2_configs`
- `account_published_works`
- `decision_history`
- `task_queue`

## 2.2 当前库的特点

- 现有库已经覆盖设备、账号、采集、基础任务、发布和部分决策历史
- 数据模型偏“功能驱动”，适合快速落地
- 还缺少正式的账号生命周期、实验系统、策略记忆、日级表现快照、系统事件和统一配置层

---

## 3. 数据库设计原则

- 保留现有表，避免推翻重建
- 所有新增表都要能与现有 `device_serial`、`account_id`、`drama_name`、`share_link` 等关键字段关联
- 优先使用“快照表 + 结果表 + 状态表”的方式，便于回放和分析
- 设计时兼容 SQLite，命名与字段类型向 PostgreSQL 靠拢
- 业务状态不要只存在代码里，要落表

## 3.1 事实主表原则

为避免后续开发出现“双写冲突”和“统计口径不一致”，这里先明确事实主表：

- `device_accounts`
  账号运行主表，负责账号基础信息、当前登录状态、当前账号阶段
- `account_authorizations`
  授权事实主表，负责 Cookie / Bearer / refresh_token 等授权材料
- `mcn_sessions`
  MCN 会话事实主表，负责 Bearer Token、WebSocket 状态、heartbeat 时间和同步状态
- `mcn_account_bindings`
  MCN 绑定事实主表，负责“账号是否绑定到我方 MCN”的最新快照
- `mcn_invitations`
  MCN 邀约事实主表，负责邀约请求、待确认状态和邀约记录留痕
- `task_queue`
  执行事实主表，负责当前任务状态、重试、依赖、人工接管状态
- `batches`
  计划批次主表，负责一次决策或一次批量执行的任务集合
- `publish_results`
  发布事务事实主表，负责“某次发布动作最终是否成功”
- `account_published_works`
  平台作品快照表，负责“平台上已经存在的作品实体”
- `content_performance_daily`
  作品日级表现快照事实表
- `account_performance_daily`
  账号日级表现快照事实表
- `mcn_income_snapshots`
  MCN 收益快照事实表，负责成员收入、分佣和结算审计
- `decision_history`
  决策事实主表，负责总控 Agent 的最终决策输出
- `agent_runs`
  Agent 运行事实表，负责每次 Agent 调用输入输出留痕

## 3.2 双写边界原则

- 新功能上线后，所有“执行状态”优先写入 `task_queue`
- 历史 `tasks` 表只作为兼容和业务层总表，不再承担实时调度事实表职责
- 新功能上线后，所有“发布动作结果”优先写入 `publish_results`
- `account_published_works` 只记录平台作品快照，不作为发布成功与否的唯一判定依据
- `decision_history` 记录最终决策结果，Agent 中间运行过程写 `agent_runs`

## 3.3 结算凭证原则

对于带收益归属的发布链路，系统必须保留完整的“本地可追溯证据”：

- 账号与 MCN 的绑定快照以 `mcn_account_bindings` 为准
- 邀约发起、待确认、已确认过程以 `mcn_invitations` 为准
- 每次发布的绑定校验结果、`mount_bind_id`、结算状态以 `publish_results` 为准
- 每日收益与分佣审计以 `mcn_income_snapshots` 为准

结论：

- 远端 MCN 接口是事实来源之一，但不是唯一留档位置
- 结算相关字段必须本地落库，避免后续对账无证据

---

## 4. 总体表分层

建议按 8 组来管理：

1. 基础资源层
2. 账号与授权层
3. 剧源与采集层
4. 素材与处理层
5. 任务与执行层
6. 发布与回流层
7. AI 决策与实验层
8. 配置与观测层

---

## 5. 基础资源层

## 5.1 `devices`

来源：现有表，保留。

用途：

- 设备基础信息
- Web 登录信息
- 设备状态

建议保留字段：

- `id`
- `serial`
- `alias`
- `model`
- `brand`
- `android_version`
- `device_group`
- `status`
- `last_online_time`
- `web_cookies`
- `web_login_time`
- `web_login_status`
- `web_user_id`
- `web_username`
- `kuaishou_uid`
- `kuaishou_name`
- `created_at`
- `updated_at`

建议新增字段：

- `risk_level`
- `env_tag`
- `owner`
- `last_heartbeat_at`
- `notes`

状态建议：

- `offline`
- `online`
- `busy`
- `error`
- `disabled`

## 5.2 `device_statistics`

来源：现有表，保留。

用途：

- 设备维度任务成功率
- 设备维度平均耗时

建议保留，不做大改。

---

## 6. 账号与授权层

## 6.1 `device_accounts`

来源：现有表，保留并扩展。

用途：

- 设备与账号绑定
- Cookie/登录态
- 账号 UID 和名称
- 基础成功失败计数

建议保留字段：

- `id`
- `device_serial`
- `account_id`
- `account_name`
- `account_index`
- `browser_port`
- `cookies`
- `login_time`
- `login_status`
- `is_active`
- `kuaishou_uid`
- `kuaishou_name`
- `success_count`
- `fail_count`
- `created_at`
- `updated_at`

建议新增字段：

- `account_stage`
- `account_type`
- `mcn_id`
- `mcn_binding_status`
- `mcn_binding_verified_at`
- `authorization_type`
- `cookie_last_success_at`
- `cookie_expire_at`
- `last_publish_at`
- `publish_success_rate_7d`
- `health_status`
- `risk_status`
- `settlement_proof_status`
- `is_paused`
- `pause_reason`
- `tags`

建议索引：

- `(device_serial, is_active)`
- `(account_id)`
- `(kuaishou_uid)`
- `(account_stage)`
- `(health_status)`

枚举建议：

- `login_status`: `not_logged_in`, `logged_in`, `expired`, `error`
- `account_stage`: `testing`, `warming`, `formal`, `scaling`, `cooling`, `disabled`
- `account_type`: `test`, `formal`, `viral`, `backup`
- `health_status`: `healthy`, `warning`, `broken`

## 6.2 `account_authorizations` 新增

用途：

- 把授权信息从账号主表里独立出来
- 兼容 Cookie / Bearer / refresh_token 等方式

字段建议：

- `id` INTEGER PK
- `account_id` TEXT NOT NULL
- `platform` TEXT NOT NULL
- `auth_type` TEXT NOT NULL
- `access_token` TEXT
- `refresh_token` TEXT
- `cookies_json` TEXT
- `issued_at` TEXT
- `expires_at` TEXT
- `last_refresh_at` TEXT
- `refresh_status` TEXT DEFAULT 'unknown'
- `last_success_at` TEXT
- `last_failure_at` TEXT
- `failure_reason` TEXT
- `created_at` TEXT
- `updated_at` TEXT

索引建议：

- `(account_id, platform)`
- `(expires_at)`
- `(refresh_status)`

## 6.3 `account_health_snapshots` 新增

用途：

- 记录账号健康快照
- 给风控判断和总控 Agent 使用

字段建议：

- `id`
- `account_id`
- `snapshot_date`
- `login_status`
- `publish_status`
- `last_publish_success`
- `publish_fail_count_1d`
- `publish_fail_count_7d`
- `channel_a_fail_rate`
- `channel_b_fail_rate`
- `risk_score`
- `health_score`
- `notes`
- `created_at`

唯一键建议：

- `(account_id, snapshot_date)`

## 6.4 `mcn_organizations` 新增

用途：

- MCN 主体管理

字段建议：

- `id`
- `mcn_id`
- `mcn_name`
- `platform`
- `status`
- `access_config`
- `notes`
- `created_at`
- `updated_at`

## 6.5 `mcn_sessions` 新增

用途：

- 维护 MCN 登录态
- 维护 Bearer Token / 过期时间 / WebSocket 在线状态
- 记录最近一次 heartbeat 和同步结果

字段建议：

- `id`
- `mcn_id`
- `owner_code`
- `auth_type`
- `access_token`
- `refresh_token`
- `token_expires_at`
- `ws_status`
- `ws_session_id`
- `ws_connected_at`
- `last_heartbeat_at`
- `last_sync_at`
- `sync_status`
- `failure_count`
- `failure_reason`
- `created_at`
- `updated_at`

状态建议：

- `ws_status`: `connected`, `reconnecting`, `disconnected`, `fallback_polling`
- `sync_status`: `ok`, `degraded`, `failed`

## 6.6 `mcn_account_bindings` 新增

用途：

- 保存账号与我方 MCN 的绑定快照
- 作为发布前绑定校验和结算归属的本地主依据

字段建议：

- `id`
- `account_id`
- `kuaishou_uid`
- `account_name`
- `mcn_id`
- `owner_code`
- `member_id`
- `plan_type`
- `bind_status`
- `verify_channel`
- `verify_status`
- `last_verified_at`
- `invitation_status`
- `bound_at`
- `raw_snapshot_json`
- `created_at`
- `updated_at`

唯一键建议：

- `(kuaishou_uid, owner_code)`

状态建议：

- `bind_status`: `bound`, `unbound`, `pending_confirm`, `unknown`
- `verify_status`: `verified`, `unverified`, `stale`, `error`

## 6.7 `mcn_invitations` 新增

用途：

- 记录 `direct_invite` 请求与响应
- 记录 `invitation_records` 轮询结果
- 形成邀约与待确认过程的不可抵赖证据

字段建议：

- `id`
- `target_kuaishou_uid`
- `target_phone`
- `account_id`
- `account_name`
- `auth_code`
- `organization_id`
- `note`
- `invite_request_json`
- `invite_response_json`
- `record_process_status`
- `record_process_status_desc`
- `record_type`
- `settled`
- `invited_at`
- `confirmed_at`
- `last_polled_at`
- `created_at`
- `updated_at`

唯一键建议：

- `(target_kuaishou_uid, auth_code)`

## 6.8 `mcn_income_snapshots` 新增

用途：

- 保存按日收益快照
- 为结算、对账、分佣审计提供依据

字段建议：

- `id`
- `snapshot_date`
- `mcn_id`
- `account_id`
- `member_id`
- `kuaishou_uid`
- `plan_type`
- `total_amount`
- `commission_amount`
- `commission_rate`
- `settled`
- `raw_response_json`
- `captured_at`
- `created_at`

唯一键建议：

- `(snapshot_date, member_id)`

---

## 7. 剧源与采集层

## 7.1 `drama_links`

来源：现有表，保留并扩展。

用途：

- 短剧链接池
- 链接状态管理
- 分配记录

建议保留字段：

- `id`
- `drama_name`
- `drama_url`
- `description`
- `remark`
- `publish_description`
- `status`
- `assigned_device`
- `use_count`
- `last_used_at`
- `created_at`
- `updated_at`
- `completed_at`
- `source_file`
- `link_mode`

建议新增字段：

- `platform`
- `genre`
- `heat_score`
- `rank_value`
- `source_type`
- `download_status`
- `last_download_at`
- `is_active`

建议状态：

- `pending`
- `assigned`
- `downloaded`
- `processed`
- `published`
- `used`
- `archived`
- `failed`

## 7.2 `drama_rank_snapshots` 新增

用途：

- 记录热榜/排名快照
- 支撑热榜分析和趋势分析

字段建议：

- `id`
- `platform`
- `rank_type`
- `drama_name`
- `drama_url`
- `rank_value`
- `heat_score`
- `source_payload`
- `snapshot_time`
- `created_at`

索引建议：

- `(platform, rank_type, snapshot_time)`
- `(drama_name)`

## 7.3 `collection_tasks`

来源：现有表，保留。

用途：

- 采集任务主表

建议新增字段：

- `batch_id`
- `collector_type`
- `source_platform`
- `result_count`
- `payload`

## 7.4 `collected_videos`

来源：现有表，保留并作为采集结果明细表。

用途：

- 存放采集到的作品明细

建议新增字段：

- `drama_link_id`
- `drama_genre`
- `is_downloadable`
- `download_status`
- `rank_snapshot_id`

## 7.5 `collection_logs`

来源：现有表，保留。

用途：

- 采集日志

---

## 8. 素材与处理层

## 8.1 `download_cache`

来源：代码依赖表，保留。

用途：

- 防止重复下载

建议字段统一为：

- `id`
- `drama_link_id`
- `drama_name`
- `drama_url`
- `url_hash`
- `video_path`
- `status`
- `file_size`
- `duration`
- `download_tool`
- `created_at`
- `updated_at`

## 8.2 `media_assets` 新增

用途：

- 统一管理原始素材、处理后素材、封面、变体素材

字段建议：

- `id`
- `asset_id`
- `source_type`
- `source_ref_id`
- `account_id`
- `drama_name`
- `file_path`
- `file_type`
- `mime_type`
- `duration`
- `width`
- `height`
- `file_size`
- `checksum`
- `status`
- `created_at`
- `updated_at`

## 8.3 `processing_jobs` 新增

用途：

- 跟踪下载后的视频处理任务

字段建议：

- `id`
- `job_id`
- `task_id`
- `account_id`
- `drama_name`
- `input_asset_id`
- `output_asset_id`
- `strategy_name`
- `strategy_params`
- `status`
- `retry_count`
- `error_message`
- `started_at`
- `finished_at`
- `created_at`

## 8.4 `processing_results` 新增

用途：

- 记录去重/处理效果
- 供策略分析与回放

字段建议：

- `id`
- `job_id`
- `strategy_name`
- `strategy_version`
- `param_hash`
- `output_asset_id`
- `quality_score`
- `dedup_signature`
- `estimated_risk_score`
- `created_at`

## 8.5 `edit_templates` 新增

用途：

- 管理剪辑模板和默认参数

字段建议：

- `id`
- `template_code`
- `template_name`
- `template_type`
- `default_params`
- `status`
- `created_at`
- `updated_at`

---

## 9. 任务与执行层

## 9.1 `tasks`

来源：现有表，保留。

定位：

- 历史通用任务表

建议：

- 作为“业务任务总表”继续保留
- 与新 `task_queue` 表形成互补，不建议直接删除

## 9.2 `task_logs`

来源：现有表，保留。

用途：

- 历史任务日志

## 9.3 `batches`

来源：现有表，保留。

用途：

- 任务批次管理

建议新增字段：

- `owner`
- `source`
- `plan_type`
- `trigger_type`

## 9.4 `batch_tasks`

来源：现有表，保留。

用途：

- 批次与任务关联

## 9.5 `task_queue`

来源：`task_queue.py` 动态创建，保留并升级。

用途：

- 当前实际执行队列表

建议字段：

- `id`
- `task_type`
- `account_id`
- `drama_name`
- `priority`
- `params`
- `status`
- `retry_count`
- `max_retries`
- `created_at`
- `started_at`
- `finished_at`
- `error_message`
- `result`
- `depends_on`

建议新增字段：

- `batch_id`
- `parent_task_id`
- `queue_name`
- `worker_name`
- `next_retry_at`
- `manual_status`
- `resource_key`

建议状态：

- `pending`
- `queued`
- `running`
- `waiting_retry`
- `waiting_manual`
- `success`
- `failed`
- `skipped`
- `dead_letter`
- `canceled`

## 9.6 `local_task_records`

来源：现有表，保留。

用途：

- 轻量本地执行记录

建议：

- 逐步让其定位为“历史操作记录表”
- 主要执行状态由 `task_queue` 和新任务结果表承接

## 9.7 `manual_review_items` 新增

用途：

- 接住 `waiting_manual`、账号异常、素材异常、规则冲突等人工处理项
- 形成独立的人工工作台数据源

字段建议：

- `id`
- `review_id`
- `source_type`
- `source_id`
- `task_queue_id`
- `batch_id`
- `account_id`
- `manual_status`
- `manual_reason`
- `suggested_action`
- `assigned_to`
- `decided_action`
- `decision_notes`
- `created_at`
- `updated_at`
- `resolved_at`

建议状态：

- `open`
- `processing`
- `resolved`
- `rejected`
- `expired`

---

## 10. 发布与回流层

## 10.1 `web_publish_tasks`

来源：现有表，保留。

用途：

- Web 发布任务

建议新增字段：

- `account_id`
- `channel_type`
- `decision_id`
- `verify_status`
- `verified_at`
- `mount_bind_id`

## 10.2 `publish_results` 新增

用途：

- 统一发布结果表
- 将 API/Selenium/Web 多种通道结果统一

字段建议：

- `id`
- `publish_task_id`
- `task_queue_id`
- `batch_id`
- `account_id`
- `device_serial`
- `channel_type`
- `drama_name`
- `input_asset_id`
- `output_asset_id`
- `caption`
- `photo_id`
- `share_url`
- `publish_status`
- `verify_status`
- `mount_bind_id`
- `banner_task_id`
- `mcn_binding_id`
- `mcn_binding_status`
- `binding_verified_at`
- `settlement_status`
- `settlement_evidence_json`
- `failure_reason`
- `published_at`
- `verified_at`
- `created_at`
- `updated_at`

## 10.3 `account_published_works`

来源：现有迁移脚本，保留。

用途：

- 已发布作品快照

建议新增字段：

- `publish_result_id`
- `drama_name`
- `account_stage`
- `source_channel`

## 10.4 `content_performance_daily` 新增

用途：

- 每日作品表现快照

字段建议：

- `id`
- `photo_id`
- `account_id`
- `snapshot_date`
- `view_count`
- `like_count`
- `comment_count`
- `share_count`
- `favorite_count`
- `follow_count`
- `revenue_amount`
- `cpm`
- `status`
- `created_at`

唯一键建议：

- `(photo_id, snapshot_date)`

## 10.5 `account_performance_daily` 新增

用途：

- 每日账号表现快照

字段建议：

- `id`
- `account_id`
- `snapshot_date`
- `publish_count`
- `success_publish_count`
- `total_views`
- `total_likes`
- `total_comments`
- `total_shares`
- `followers_delta`
- `revenue_amount`
- `avg_cpm`
- `health_score`
- `created_at`

唯一键建议：

- `(account_id, snapshot_date)`

---

## 11. AI 决策与实验层

## 11.1 `decision_history`

来源：`decision_engine.py` 自动创建，保留。

用途：

- 记录总控/决策引擎输出

现有字段已较合理：

- `account_id`
- `drama_name`
- `strategy_name`
- `channel`
- `publish_count`
- `decision_reasoning`
- `outcome_views`
- `outcome_cpm`
- `outcome_approved`
- `created_at`
- `outcome_updated_at`

建议新增字段：

- `decision_mode`
- `batch_id`
- `source_state_json`
- `decision_schema_version`

## 11.2 `strategy_experiments` 新增

用途：

- 管理实验定义

字段建议：

- `id`
- `experiment_code`
- `experiment_name`
- `hypothesis`
- `variable_name`
- `control_group`
- `test_group`
- `sample_target`
- `sample_current`
- `success_metric`
- `success_threshold`
- `stop_condition`
- `status`
- `started_at`
- `ended_at`
- `created_at`

## 11.3 `experiment_assignments` 新增

用途：

- 实验任务分配到账号/作品/策略

字段建议：

- `id`
- `experiment_code`
- `account_id`
- `drama_name`
- `strategy_name`
- `group_name`
- `task_id`
- `publish_result_id`
- `status`
- `created_at`

## 11.4 `strategy_memories` 新增

用途：

- 持久化长期策略记忆

字段建议：

- `id`
- `memory_type`
- `platform`
- `account_stage`
- `drama_genre`
- `strategy_name`
- `publish_window`
- `title`
- `description`
- `recommendation`
- `confidence_score`
- `impact_score`
- `valid_from`
- `valid_to`
- `invalidation_reason`
- `tags`
- `created_at`
- `updated_at`

## 11.5 `strategy_rules` 新增

用途：

- 把硬规则和可调策略阈值结构化

字段建议：

- `id`
- `rule_code`
- `rule_name`
- `rule_scope`
- `rule_type`
- `rule_payload`
- `priority`
- `status`
- `created_at`
- `updated_at`

## 11.6 `agent_runs` 新增

用途：

- 记录各 Agent 每次运行输入输出与耗时

字段建议：

- `id`
- `agent_name`
- `run_id`
- `batch_id`
- `account_id`
- `input_json`
- `output_json`
- `status`
- `latency_ms`
- `error_message`
- `created_at`

---

## 12. 配置与观测层

## 12.1 `feature_switches` 新增

用途：

- 系统开关管理

字段建议：

- `id`
- `switch_code`
- `switch_name`
- `switch_scope`
- `switch_value`
- `description`
- `updated_by`
- `updated_at`

建议初始开关：

- `collect_enabled`
- `download_enabled`
- `process_enabled`
- `publish_enabled`
- `ai_decision_enabled`
- `auto_scale_enabled`

## 12.2 `system_events` 新增

用途：

- 统一记录重要事件

字段建议：

- `id`
- `event_type`
- `event_level`
- `source_module`
- `entity_type`
- `entity_id`
- `payload`
- `created_at`

## 12.3 `audit_logs` 新增

用途：

- 手动干预、配置修改、运营操作留痕

字段建议：

- `id`
- `operator`
- `action`
- `target_type`
- `target_id`
- `before_json`
- `after_json`
- `created_at`

---

## 13. 主键、外键与关键关联

建议核心关联规则：

- `device_accounts.device_serial -> devices.serial`
- `account_authorizations.account_id -> device_accounts.account_id`
- `account_health_snapshots.account_id -> device_accounts.account_id`
- `drama_links.assigned_device -> devices.serial`
- `collection_tasks.device_serial -> devices.serial`
- `collected_videos.task_id -> collection_tasks.task_id`
- `processing_jobs.input_asset_id -> media_assets.asset_id`
- `publish_results.account_id -> device_accounts.account_id`
- `account_published_works.account_id -> device_accounts.account_id`
- `content_performance_daily.photo_id -> account_published_works.photo_id`
- `decision_history.account_id -> device_accounts.account_id`
- `experiment_assignments.experiment_code -> strategy_experiments.experiment_code`
- `manual_review_items.task_queue_id -> task_queue.id`

SQLite 前期可弱外键，PostgreSQL 阶段建议加强约束。

---

## 13.1 事实主表职责矩阵

为避免实现阶段出现“到底查哪张表”的分歧，职责矩阵如下：

| 场景 | 主表 | 辅助表 | 说明 |
|---|---|---|---|
| 当前账号状态 | `device_accounts` | `account_authorizations`, `account_health_snapshots` | 查当前可不可发、授权是否健康 |
| 当前任务状态 | `task_queue` | `batches`, `manual_review_items` | 队列、重试、人工接管都以这里为准 |
| 历史业务任务 | `tasks` | `task_logs`, `batch_tasks` | 老逻辑兼容，逐步弱化实时职责 |
| 某次发布是否成功 | `publish_results` | `web_publish_tasks`, `task_queue` | 发布事务真相表 |
| 平台上有哪些作品 | `account_published_works` | `content_performance_daily` | 外部平台作品快照 |
| 某次总控决策 | `decision_history` | `agent_runs` | 决策结果与执行建议 |
| 某个实验定义与分配 | `strategy_experiments` | `experiment_assignments` | 实验规则和样本归属 |

---

## 14. 迁移建议

## Phase 1

- 保留现有表
- 新增：
  - `account_authorizations`
  - `account_health_snapshots`
  - `manual_review_items`
  - `publish_results`
  - `content_performance_daily`
  - `account_performance_daily`
  - `feature_switches`
  - `system_events`

## Phase 2

- 新增：
  - `processing_jobs`
  - `processing_results`
  - `strategy_experiments`
  - `experiment_assignments`
  - `strategy_memories`
  - `strategy_rules`
  - `agent_runs`

## Phase 3

- 从 SQLite 平滑迁移到 PostgreSQL
- 对 JSON 字段优先改用 `JSONB`
- 对快照表和结果表补充更强索引

---

## 14.1 数据保留与归档策略

高增长表如果不提前规划清理，SQLite 阶段会很快变慢。建议策略如下：

- `task_queue`
  热数据保留 90 天；每月归档到 `task_queue_archive`
- `task_logs` / `collection_logs`
  热数据保留 30 天；归档后只保留失败和警告日志
- `content_performance_daily`
  热数据保留 180 天；更旧数据汇总成月级表
- `account_performance_daily`
  热数据保留 365 天；更旧数据可聚合到月级
- `agent_runs`
  输入输出全文保留 30 天；更旧仅保留摘要和耗时
- `system_events`
  热数据保留 90 天；严重级别事件长期保留
- `manual_review_items`
  已处理数据保留 180 天；逾期未处理项自动升级告警

建议 SQLite 阶段设置预警阈值：

- `task_queue` 超过 50 万行时进入归档强制模式
- 全库文件超过 5GB 时进入 PostgreSQL 迁移准备

---

## 15. 推荐落地顺序

最先落地的 6 张表建议是：

1. `account_authorizations`
2. `account_health_snapshots`
3. `publish_results`
4. `content_performance_daily`
5. `strategy_experiments`
6. `feature_switches`

原因：

- 这几张表最直接支撑账号稳定性、发布确认、数据回流、实验和开关控制

---

## 附录 A：首批落地表 DDL 草案

以下 DDL 以 SQLite 兼容写法为主，同时尽量贴近 PostgreSQL 迁移习惯。

### A.1 `account_authorizations`

```sql
CREATE TABLE IF NOT EXISTS account_authorizations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    auth_type TEXT NOT NULL,
    access_token TEXT DEFAULT '',
    refresh_token TEXT DEFAULT '',
    cookies_json TEXT DEFAULT '',
    issued_at TEXT,
    expires_at TEXT,
    last_refresh_at TEXT,
    refresh_status TEXT NOT NULL DEFAULT 'unknown',
    last_success_at TEXT,
    last_failure_at TEXT,
    failure_reason TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(account_id, platform, auth_type)
);

CREATE INDEX IF NOT EXISTS idx_account_auth_account
ON account_authorizations(account_id);

CREATE INDEX IF NOT EXISTS idx_account_auth_expire
ON account_authorizations(expires_at);

CREATE INDEX IF NOT EXISTS idx_account_auth_refresh_status
ON account_authorizations(refresh_status);
```

### A.2 `account_health_snapshots`

```sql
CREATE TABLE IF NOT EXISTS account_health_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    login_status TEXT NOT NULL DEFAULT 'unknown',
    publish_status TEXT NOT NULL DEFAULT 'unknown',
    last_publish_success INTEGER NOT NULL DEFAULT 0,
    publish_fail_count_1d INTEGER NOT NULL DEFAULT 0,
    publish_fail_count_7d INTEGER NOT NULL DEFAULT 0,
    channel_a_fail_rate REAL NOT NULL DEFAULT 0,
    channel_b_fail_rate REAL NOT NULL DEFAULT 0,
    risk_score REAL NOT NULL DEFAULT 0,
    health_score REAL NOT NULL DEFAULT 0,
    notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(account_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_account_health_account
ON account_health_snapshots(account_id);

CREATE INDEX IF NOT EXISTS idx_account_health_date
ON account_health_snapshots(snapshot_date);
```

### A.3 `manual_review_items`

```sql
CREATE TABLE IF NOT EXISTS manual_review_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    review_id TEXT NOT NULL UNIQUE,
    source_type TEXT NOT NULL,
    source_id TEXT NOT NULL,
    task_queue_id TEXT DEFAULT '',
    batch_id TEXT DEFAULT '',
    account_id TEXT DEFAULT '',
    manual_status TEXT NOT NULL DEFAULT 'open',
    manual_reason TEXT NOT NULL DEFAULT '',
    suggested_action TEXT DEFAULT '',
    assigned_to TEXT DEFAULT '',
    decided_action TEXT DEFAULT '',
    decision_notes TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    resolved_at TEXT
);

CREATE INDEX IF NOT EXISTS idx_manual_review_status
ON manual_review_items(manual_status);

CREATE INDEX IF NOT EXISTS idx_manual_review_account
ON manual_review_items(account_id);

CREATE INDEX IF NOT EXISTS idx_manual_review_batch
ON manual_review_items(batch_id);
```

### A.4 `publish_results`

```sql
CREATE TABLE IF NOT EXISTS publish_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    publish_task_id TEXT DEFAULT '',
    task_queue_id TEXT DEFAULT '',
    batch_id TEXT DEFAULT '',
    account_id TEXT NOT NULL,
    device_serial TEXT DEFAULT '',
    channel_type TEXT NOT NULL,
    drama_name TEXT DEFAULT '',
    input_asset_id TEXT DEFAULT '',
    output_asset_id TEXT DEFAULT '',
    caption TEXT DEFAULT '',
    photo_id TEXT DEFAULT '',
    share_url TEXT DEFAULT '',
    publish_status TEXT NOT NULL DEFAULT 'pending',
    verify_status TEXT NOT NULL DEFAULT 'unverified',
    failure_reason TEXT DEFAULT '',
    published_at TEXT,
    verified_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_publish_results_account
ON publish_results(account_id);

CREATE INDEX IF NOT EXISTS idx_publish_results_status
ON publish_results(publish_status, verify_status);

CREATE INDEX IF NOT EXISTS idx_publish_results_photo
ON publish_results(photo_id);
```

### A.5 `content_performance_daily`

```sql
CREATE TABLE IF NOT EXISTS content_performance_daily (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    photo_id TEXT NOT NULL,
    account_id TEXT NOT NULL,
    snapshot_date TEXT NOT NULL,
    view_count INTEGER NOT NULL DEFAULT 0,
    like_count INTEGER NOT NULL DEFAULT 0,
    comment_count INTEGER NOT NULL DEFAULT 0,
    share_count INTEGER NOT NULL DEFAULT 0,
    favorite_count INTEGER NOT NULL DEFAULT 0,
    follow_count INTEGER NOT NULL DEFAULT 0,
    revenue_amount REAL NOT NULL DEFAULT 0,
    cpm REAL NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
    UNIQUE(photo_id, snapshot_date)
);

CREATE INDEX IF NOT EXISTS idx_content_perf_account
ON content_performance_daily(account_id);

CREATE INDEX IF NOT EXISTS idx_content_perf_date
ON content_performance_daily(snapshot_date);
```

### A.6 `strategy_experiments`

```sql
CREATE TABLE IF NOT EXISTS strategy_experiments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    experiment_code TEXT NOT NULL UNIQUE,
    experiment_name TEXT NOT NULL,
    hypothesis TEXT DEFAULT '',
    variable_name TEXT NOT NULL,
    control_group TEXT DEFAULT '',
    test_group TEXT DEFAULT '',
    sample_target INTEGER NOT NULL DEFAULT 0,
    sample_current INTEGER NOT NULL DEFAULT 0,
    success_metric TEXT NOT NULL DEFAULT '',
    success_threshold REAL NOT NULL DEFAULT 0,
    stop_condition TEXT DEFAULT '',
    status TEXT NOT NULL DEFAULT 'draft',
    started_at TEXT,
    ended_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_strategy_experiments_status
ON strategy_experiments(status);

CREATE INDEX IF NOT EXISTS idx_strategy_experiments_metric
ON strategy_experiments(success_metric);
```

### A.7 `feature_switches`

```sql
CREATE TABLE IF NOT EXISTS feature_switches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    switch_code TEXT NOT NULL UNIQUE,
    switch_name TEXT NOT NULL,
    switch_scope TEXT NOT NULL DEFAULT 'global',
    switch_value TEXT NOT NULL DEFAULT 'false',
    description TEXT DEFAULT '',
    updated_by TEXT DEFAULT 'system',
    updated_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_feature_switch_scope
ON feature_switches(switch_scope);
```

### A.8 `agent_runs`

```sql
CREATE TABLE IF NOT EXISTS agent_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name TEXT NOT NULL,
    run_id TEXT NOT NULL UNIQUE,
    batch_id TEXT DEFAULT '',
    account_id TEXT DEFAULT '',
    input_json TEXT DEFAULT '{}',
    output_json TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    error_message TEXT DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now','localtime'))
);

CREATE INDEX IF NOT EXISTS idx_agent_runs_agent
ON agent_runs(agent_name, created_at);

CREATE INDEX IF NOT EXISTS idx_agent_runs_account
ON agent_runs(account_id);
```

## 16. 结论

当前 `D:\ks_automation` 的数据库已经有一套能跑的基础骨架，但还不是完整的矩阵生产库。

最合理的路线不是重建，而是：

- 保留现有 `devices / device_accounts / drama_links / task_queue / account_published_works / decision_history`
- 在其上补足“授权、健康、发布结果、每日快照、实验、策略记忆、配置开关”这些生产表
- 先在 SQLite 中扩展，随后在业务稳定后切 PostgreSQL
