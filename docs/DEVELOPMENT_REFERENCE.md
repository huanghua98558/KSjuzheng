# KS Automation — 完整开发参考技术文档

> **版本**: v1.0 (2026-04-20)
> **项目**: 快手短剧 AI 矩阵运营系统 (KS184 重构 + AI 决策闭环)
> **定位**: 一份文档把系统讲完 — 架构 / 数据 / 代码 / 配置 / 工具链 / 已知限制
> **读者**: 接手工程师 / AI 决策层 / 运维

---

## 目录

1. [项目身份](#1-项目身份)
2. [架构总览 (8 层)](#2-架构总览-8-层)
3. [数据库 (89 表)](#3-数据库-89-表)
4. [Core 模块 (80 文件)](#4-core-模块-80-文件)
5. [Agent 体系 (20 agents)](#5-agent-体系-20-agents)
6. [配置系统 (318 keys × 12 板块)](#6-配置系统-318-keys--12-板块)
7. [剪辑去重 pipeline](#7-剪辑去重-pipeline)
8. [发布 pipeline (sig3 + MCN 中继)](#8-发布-pipeline)
9. [Dashboard (11+ 页)](#9-dashboard-11-页)
10. [逆向工程工具链](#10-逆向工程工具链)
11. [CLI 脚本索引 (71 脚本)](#11-cli-脚本索引)
12. [测试 + 验收 (70+ tests)](#12-测试--验收)
13. [已知限制 + Roadmap](#13-已知限制--roadmap)
14. [关键工程教训](#14-关键工程教训)

---

## 1. 项目身份

| 项 | 值 |
|---|---|
| **正式名** | 快手短剧 AI 矩阵运营系统 |
| **内部名** | KS184 重构 (Python) |
| **仓库** | `D:\ks_automation` |
| **船长账号** | `REPLACE_WITH_YOUR_PHONE` (黄老板, user_id=946, owner_code=黄华) |
| **矩阵规模** | 当前 13 账号 → 目标 100 → 最终 10000 |
| **商业模式** | 萤光/星火计划 CPS 分佣 (80%) |
| **数据库** | SQLite WAL, `C:\Users\Administrator\AppData\Local\KuaishouControl\data\kuaishou_control.db` |
| **Hermes LLM** | `http://127.0.0.1:8642/v1/chat/completions` (OpenAI 兼容) |

### 关键密钥 (反编译提取)

```python
_HMAC_SECRET         = b"REPLACE_WITH_HMAC_SECRET"   # sig3
_MCN_RESPONSE_SECRET = b"REPLACE_WITH_MCN_RESP_SECRET"    # :50002 ack

# sig3 签名公式 (Frida 验证, byte-level 一致)
msg = f"{uid}:{timestamp}:{nonce_b64}:{_HMAC_SECRET.decode()}"
sig3 = HMAC_SHA256(MCN_SECRET, msg).hexdigest()[:56]

# MCN 响应签名 (28 字节 ack, 不是业务数据)
msg = f"{body_b64_512}:{nonce_32}:REPLACE_WITH_MCN_RESP_SECRET"
sig = HMAC_SHA256(MCN_RESPONSE_SECRET, msg).hexdigest()[:56]
```

### MCN 直连 (已破解)

```
MySQL:  im.zhongxiangbao.com:3306  shortju / REPLACE_WITH_MCN_MYSQL_PASSWORD  (50 张表)
Login:  mcn.zhongxiangbao.com:88
Verify: im.zhongxiangbao.com:8000/api/mcn/verify
Relay:  im.zhongxiangbao.com:50002/xh (sig3 容灾代签, 4 shortcut + 1 generic)
```

### 关键 ID 规范 (踩过多次坑)

- `device_accounts.id` (**int PK**) — 通用账号引用, 不要用 `account_id` (字符串)
- `kuaishou_uid` (DB 字段) — **字符串** `3xmne9bjww75dt9`
- Cookie `userId=` — **数字** `887329560` (MCN verify 要这个)
- `device_accounts.numeric_uid` (2026-04-19 加) — 从 cookie 提的 int, 统一关联

---

## 2. 架构总览 (8 层)

```
┌──────────────────────────────────────────────────────────────┐
│ L8 运营面板   Dashboard (Streamlit 11 页) + CLI             │
├──────────────────────────────────────────────────────────────┤
│ L7 AI 决策层  6 Agents + Hermes LLM + Bandit + Healing       │
│              StrategyPlanner / TaskScheduler / Watchdog      │
│              Analyzer / LLMResearcher / Controller          │
├──────────────────────────────────────────────────────────────┤
│ L6 调度执行   account_executor (账号级并发锁 / 事件驱动)     │
│              pipeline 7 Stage (download→md5→process→publish) │
├──────────────────────────────────────────────────────────────┤
│ L5 业务原子   publisher / downloader / processor / watermark │
│              cover_service / md5_modifier / qitian           │
├──────────────────────────────────────────────────────────────┤
│ L4 签名认证   sig_service + mcn_client + mcn_relay (fallback)│
│              cookie_manager (7 suite classifier)              │
├──────────────────────────────────────────────────────────────┤
│ L3 数据采集   drama_collector / hot_rankings / drama_library │
│              mcn_business (binding / income snapshot)         │
├──────────────────────────────────────────────────────────────┤
│ L2 存储       SQLite (89 tables, WAL) + file_lock + cache    │
├──────────────────────────────────────────────────────────────┤
│ L1 基础设施   config / logger / db_manager / event_bus       │
└──────────────────────────────────────────────────────────────┘

外部依赖:
  - KS184 原始软件 (逆向源): C:\Program Files\kuaishou2\KS184.7z\KS184\
  - 快手 API: cp.kuaishou.com (sig3 签名)
  - MCN 后台: zhongxiangbao.com (MySQL 直连 + :50002 中继)
  - Hermes LLM: localhost:8642 (OpenAI 兼容)
  - ffmpeg: tools/ffmpeg/bin-xin (NVENC) + bin4/cfg64.exe (不闪独占)
```

---

## 3. 数据库 (89 表)

### 3.1 分类索引

#### 账号 (15 表)
```
device_accounts                账号主表 (id PK, numeric_uid, tier, cookies)
devices                        设备表
device_kuaishou_accounts       设备-账号绑定
account_groups / account_tags  分组 / 标签
account_tier_transitions       tier 迁移历史
account_level_history          账号等级历史
account_lifecycle_stages       生命周期阶段
account_vertical_categories    垂直类别
account_vertical_stats         垂直统计
account_decision_history       账号决策日志
account_strategy_memory        账号策略记忆 (AI learning)
account_diary_entries          账号日记 (AI self-reflection)
account_performance_daily      每日绩效
account_qr_login_attempts      二维码登录尝试
account_health_snapshots       健康评分每日快照
```

#### 剧 (13 表)
```
drama_links                    剧链接主表 (photo_id, url, status)
drama_banner_tasks             banner 任务缓存 (drama-level, 4591 条)
drama_authors                  作者库 (283 条)
drama_collections              合集
drama_templates                模板
drama_hot_rankings             热度榜 (external + internal)
platform_trends                平台趋势
keyword_watch_list             关键词监控
available_dramas               可用剧池
download_cache                 下载缓存 (dedupe)
collected_videos               采集视频
collection_tasks               采集任务
collection_logs                采集日志
```

#### 任务 + 执行 (12 表)
```
task_queue                     任务队列 (+6 字段 v19)
tasks                          老任务表 (legacy)
task_logs                      任务日志
batches / batch_tasks          批次任务
daily_plans / daily_plan_items 每日计划
account_drama_execution_logs   账号×剧 执行日志
account_published_works        账号已发作品
publish_results                发布结果 (22 条, id=22 真发过)
publish_daily_metrics          每日聚合 (反馈闭环)
web_publish_tasks              网页发布任务
local_task_records             本地任务记录
```

#### MCN + 收益 (5 表)
```
mcn_account_bindings           MCN 绑定
mcn_invitations                邀请
mcn_member_snapshots           成员快照 (每日, 580 条)
mcn_income_snapshots           收益快照
mcn_income_detail_snapshots    收益明细
```

#### AI 决策 + 学习 (14 表)
```
daily_plans / daily_plan_items 每日计划 (StrategyPlanner 产出)
strategy_rules                 规则 (Path A)
strategy_rewards               奖励矩阵 (Path B Bandit)
strategy_experiments           实验 (Path C)
experiment_assignments         实验分组
strategy_memories              策略记忆
research_notes                 LLM 研究员笔记 (approved=0 待审)
decision_history               决策历史
agent_runs                     Agent 运行记录
autopilot_cycles               自动驾驶循环 (883 cycles)
rule_proposals                 LLM 提新规则 (待审批)
rule_evolution_history         规则演化历史
upgrade_proposals              LLM 升级建议
feature_switches               6 层特性开关
```

#### 自愈 (5 表)
```
healing_playbook               规则库 (10 条, 5 seed + 5 expand)
healing_diagnoses              诊断记录
healing_actions                动作记录 (cookie_invalid 4 次成功)
healing_reports                自愈报告
manual_review_items            人工审核队列
```

#### Dashboard + 审计 (7 表)
```
dashboard_bulk_ops             批量操作日志
audit_logs                     审计日志
system_events                  系统事件 (SSE 可推)
system_config                  系统配置
security_config                安全配置
switch_group_overrides         开关分组覆盖
user_sessions / users          用户 (dashboard auth, 可选)
```

#### 其他 (18 表)
```
app_config / app_config_meta   配置 + 元数据 (318 keys 见 §6)
browser_sessions               浏览器会话
checkpoints / langgraph_*      LangGraph 状态
data_insights 用                work_metrics / content_performance_daily
cookie / mount / switch       cxt_mount_links / switches 等
sqlite_sequence                SQLite 系统表
```

### 3.2 迁移版本 (22 个 migrate_vN.py)

| v | 加了什么 |
|---|---|
| v1 | 7 MCN 表 + 10 列扩展 |
| v2 | drama_banner_tasks (4 seed) |
| v3 | drama_authors |
| v4 | hot_rankings + platform_trends + keyword_watch_list |
| v5-10 | publish_results / feature_switches / health_snapshots / experiments / ... |
| v15 | 6 healing tables (autopilot 早已在线) |
| v17-18 | cover watermark 11 keys |
| v19 | task_queue +6 字段 |
| v20 | **AI 决策 6 表** (daily_plan / tier_transitions / strategy_rewards / research_notes) |
| v21 | **自愈补洞 + LLM 深度联动** (9 新字段, 5→10 规则) |
| v22 | （预留） |

---

## 4. Core 模块 (80 文件)

### 4.1 基础设施层 (L1)

| 模块 | 职责 | 关键函数 |
|---|---|---|
| `config.py` | PATHS.json 加载 + API URL 常量 | `FFMPEG_EXE`, `CP_BASE` |
| `logger.py` | stdlib logging wrapper | `get(__name__)` |
| `db_manager.py` | SQLite 帮助函数 | `get_account_cookies`, `connect` |
| `app_config.py` | 配置读写 (cache TTL + coerce) | `get(key, default)`, `set_(key, val)` |
| `file_lock.py` | 跨进程文件锁 (`O_EXCL` 原子) | `FileLock(scope, key, timeout)` |
| `event_bus.py` | 进程内事件总线 (SSE 源) | `emit(event, data)` |
| `file_manager.py` | 文件管理 (清理 / 迁移) | `cleanup_temp` |
| `notifier.py` | 通知 (桌面 / 邮件) | `send(title, body)` |

### 4.2 数据存储层 (L2)

| 模块 | 职责 |
|---|---|
| `cookie_manager.py` | 7 suite domain classifier (cp/shop/niu/official/main/all) |
| `cookie_parser.py` | cookie 字符串 ↔ dict 转换 |
| `cookie_validator.py` | cookie 有效性验证 (ping API) |
| `auth.py` | 快手 web auth (SSO exchange) |
| `task_queue.py` | 任务队列 5-state 状态机 |
| `account_memory.py` | 账号级记忆持久化 (AI learning 用) |

### 4.3 采集层 (L3)

| 模块 | 职责 |
|---|---|
| `drama_collector.py` | profile/feed + GraphQL search + 过滤 + 去重 |
| `drama_library.py` | collect-pool ∩ download_cache → drama_links |
| `drama_selector.py` | 3 策略选剧 + 冷却管理 |
| `collector_on_demand.py` | 按需补链 (feed photoUrls) |
| `hot_rankings.py` | external (GraphQL) + internal (profile/feed) |
| `data_collector.py` | 13 账号每日指标 harvester |
| `data_insights.py` | 统一 AI-ready feature_vector |
| `mcn_client.py` | MCN login / verify / members |
| `mcn_business.py` | MCN 持久化 (binding + invitation + income) |

### 4.4 签名认证层 (L4)

| 模块 | 职责 |
|---|---|
| `sig_service.py` | `SigService.sign_payload(payload)` (每 endpoint 独立签) |
| `mcn_relay.py` | :50002 中继 wrapper (5 shortcut + generic) + signature verification |

### 4.5 业务原子层 (L5)

| 模块 | 职责 | 对齐 |
|---|---|---|
| `publisher.py` | 6 步 CP 发布 + 42 字段 + fallback | KS184 `_execute_api_publish` |
| `selenium_publisher.py` | Channel B (legacy) | 非主线 |
| `downloader.py` | HLS (N_m3u8DL-RE) + 短链 + 直链 | KS184 frida |
| `md5_modifier.py` | 末尾追加 8-32 随机字节 | KS184 `_copy_and_modify_md5` |
| `processor.py` | **10 recipe 分发 + kirin_mode6 7 步 + zhizun_mode5 pipeline** | KS184 Canonical v3 |
| `pattern_animator.py` | 7 动画 filter 生成器 (对齐 dump 公式) | KS184 dump |
| `qitian.py` | 6 种 PIL image_mode (qitian_art/gradient/...) | KS184 Q_X64 §8.3 |
| `scale34.py` | 3:4 竖屏 + 模糊背景 + sin 动态水印 | KS184 scale34 argv #2 |
| `watermark.py` | 封面水印 (drama + account + 5 风格) | KS184 `_copy_cover_with_watermark` |
| `dynamic_watermark.py` | 视频动态水印 (sin 抖动) | scale34 内置 |
| `cover_service.py` | 封面下载缓存 / 尺寸 / 压缩 / is_portrait | KS184 `_download_and_process_cover` |
| `font_pool.py` | 8 艺术字体池 (random / auto / fixed / bold) | KS184 fonts/ |
| `publish_verifier.py` | (备用) feed 回查 — 未投产 | - |
| `video_downloader.py` / `video_processor.py` | 旧接口 (被 processor.py 替代) | legacy |

### 4.6 调度执行层 (L6)

| 模块 | 职责 |
|---|---|
| `executor/account_executor.py` | 账号级并发锁 + 事件驱动触发 |
| `executor/pipeline.py` | 7 Stage 流水线 (download→md5→process→publish) |
| `executors.py` | 老 executor (legacy) |
| `worker_manager.py` | Worker 进程池 |
| `match_scorer.py` | 账号×剧 匹配评分 (6 factor) |

### 4.7 决策引擎层 (L7)

| 模块 | 职责 |
|---|---|
| `account_tier.py` | 6 状态机 (new/testing/warming_up/established/viral/frozen) + 迁移规则 |
| `decision_engine.py` | 老决策引擎 (被 agents 替代) |
| `llm_gateway.py` | Hermes chat client |
| `llm/client.py` | LLM client 封装 |
| `llm/prompts.py` | Prompt 模板 |
| `llm/trace.py` | LLM 调用追踪 |
| `incident_center.py` | 事故中心 (异常聚合) |
| `switches.py` | 特性开关 |

### 4.8 AI Agents (20 files in `core/agents/`)

| Agent | 频率 | 作用 |
|---|---|---|
| `base.py` | — | Agent 基类 + decorator |
| `registry.py` | — | Agent 注册 |
| `orchestrator.py` | — | Agent 调度器 |
| `controller_agent.py` | run_cycle | **主 controller, 14 块逻辑** |
| `strategy_planner_agent.py` | 每日 08:00 | 生成 daily_plan_items (tier × drama × reward) |
| `task_scheduler_agent.py` | 事件驱动+每2h | 到期 plan_items → task_queue + 同账号补排 |
| `watchdog_agent.py` | 每 5min | 失败率 / 连续失败冻结 / stuck 取消 |
| `analyzer_agent.py` | 每日 17:00 | 聚合 publish_daily_metrics + 更新 rewards + tier 迁移 |
| `llm_researcher_agent.py` | 周一 07:00 | Hermes 生成策略/规则/升级建议 (research_notes / rule_proposals / upgrade_proposals) |
| `self_healing_agent.py` | 每 5min | playbook 匹配 → action → 更新 success_count |
| `threshold_agent.py` | — | 阈值监控 |
| `report_agent.py` | 每日 | 生成报告 |
| `upgrade_agent.py` | — | 协议升级 |
| `experiment_agent.py` | — | A/B 实验 |
| `scale_agent.py` | — | 规模化调度 |
| `rule_engine.py` | — | 规则引擎 (DSL) |
| `analysis_agent.py` | — | 数据分析 (legacy) |
| `memory_consolidator.py` | — | 记忆合并 |
| `debug.py` | — | 调试工具 |

---

## 5. Agent 体系 (闭环总览)

```
StrategyPlanner (08:00)                        [Path A 规则 + Path B Bandit]
     │
     ▼  笛卡尔积 13 账号 × 50 剧 → match_scorer → 39 items
daily_plan_items (sched_at, priority)
     │
     ▼  事件驱动补排
TaskScheduler (2h / on-complete)
     │
     ▼  账号级并发锁
task_queue (pending → running)
     │
     ▼  7 Stage pipeline
Executor (account_executor / pipeline)
     │  ┌─────────────────┐
     │  │ Stage 1 download│
     │  │ 1.5 md5         │
     │  │ 2 process       │
     │  │ 3 publish       │
     │  │ 3.5 cover WM    │
     │  └─────────────────┘
     │
     ▼
publish_results (photo_id / status)
     │
     ├──失败──▶ Watchdog (5min)     ──▶ SelfHealing (playbook 匹配 → action)
     │                                      │
     │                                      ▼  未匹配 / 低置信度
     │                               LLMResearcher (周一)
     │                                      ▼
     │                          rule_proposals / upgrade_proposals
     │                                      ▼ 人审批
     │                          healing_playbook 新规则生效
     │
     ▼ 成功
MCN 每日 snapshot (03:00)
     │
     ▼ publish_daily_metrics.income_delta
Analyzer (17:00)
     │
     ├─▶ strategy_rewards update (Bandit)
     ├─▶ account_tier evaluate + transition
     └─▶ 回流给 StrategyPlanner (下次 08:00 用)
```

**6 自愈规则 (v21)**:

| pattern | 冷却 | 动作 |
|---|---|---|
| `cookie_invalid` | 6h | refresh cookie + retry |
| `rate_limited_429` | 24h | 账号冻结 24h |
| `sig3_signature_error` | 6h | **critical alert** (协议变更) |
| `video_hls_download_fail` | 1h | 重采集 |
| `task_stuck_running_1h` | 0 | 重排上游 |
| `mcn_verify_failed` | 3h | refresh captain token |

---

## 6. 配置系统 (318 keys × 12 板块)

### 6.1 板块分布

| 板块 | key 数 | 覆盖 UI |
|---|---|---|
| `video` | 60 | 视频处理配置 (7 种去重方法) |
| `cover` | 28 | 封面水印配置 (drama_name + account_name) |
| `publisher` | 15 | 网页发布配置 (上传/互动/可见性/禁用时间) |
| `execution` | 1 | 执行控制 (短剧间隔) |
| `cleanup` | 1 | 清理设置 |
| `remote_drama` | 10 | 远程短剧提取 |
| `watermark` | 5 | 字体池 |
| `account` | 27 | 账号管理 (列表/卡片/添加/签约+浏览器管理) |
| `collector` | 20 | 采集配置 (模式/方式/过滤/重复检测) |
| `dashboard` | 12 | 顶部导航 + 工具栏 |
| `batch_query` | 13 | 批量作品查询 |
| `earnings` | 11 | 收益查询 |
| **— 其他 legacy —** | 115 | migrate v1-v21 遗留 key |
| **合计** | **318** | |

### 6.2 关键 key 速查

```bash
# 视频处理
video.download.modify_md5          = true   # MD5 修改
video.process.enabled              = true
video.process.mode                 = mvp_trim_wipe_metadata
                                      | mode3_overlay / wuxianliandui / bushen
                                      | zhizun / rongyu / mode6 / yemao
video.process.{mode}.crf           = 20     # 质量 (UI)
video.process.{mode}.image_mode    = random_shapes  # 6 种
video.process.{mode}.blend_enabled = true   # 融图
video.process.{mode}.blend_opacity = 0.50   # 视频帧透明度
video.process.{mode}.use_gpu       = true   # 加速

# 7 动画 (UI checkbox)
video.process.mode3.overlay_anim_{zoom_in,zoom_out,zoom_pulse,
                                   pan_left,pan_right,rotate_cw,rotate_ccw}

# 封面水印 剧名
cover.watermark.drama_name.font         = auto
cover.watermark.drama_name.font_size    = 48
cover.watermark.drama_name.color        = random
cover.watermark.drama_name.custom_color = ""
cover.watermark.drama_name.position     = center
cover.watermark.drama_name.opacity      = 100
cover.watermark.drama_name.style.{random,bold,shadow,stroke,glow}

# 封面水印 账号 (UI 新 key, 兼容旧 account.*)
cover.watermark.account_name.{font,font_size,color,position,opacity,margin}

# 网页发布
publisher.upload_mode              = api | browser
publisher.use_drama_hashtag_mode   = true
publisher.default_hashtag          = #快来看短剧
publisher.interaction.{allow_copy_shoot,allow_download,show_in_local}
publisher.visibility               = public | friends | self
publisher.author_statement         = 演绎情节, 仅供娱乐
publisher.quiet_hours.{enabled,start_hour,end_hour}

# MCN 中继 fallback
publisher.enable_mcn_relay_fallback  = false  # 默认 off
publisher.mcn_relay_on_sig3_error    = true

# 采集
collector.mode                     = api_protocol | traditional_device
collector.method                   = profile_uid | keyword_search
collector.cookie.auto_switch       = true
collector.filter.{min_views,min_likes,min_comments,min_duration_sec}
collector.dedup.{content_enabled,link_enabled}
collector.keyword_search.{keywords,pages}
collector.profile_uid.list

# 字体池
watermark.font.mode     = auto | random | fixed | system
watermark.font.dir      = fonts
watermark.font.explicit = ""

# AI 决策
ai.tier.*                          # tier 迁移规则
ai.planner.max_accounts_per_drama  = 3
ai.healing.unmatched_threshold     = 3
ai.llm.propose_*                   # LLM 联动开关
```

**完整 CONFIGS 定义**: `scripts/register_dedup_configs.py` (单文件, 203 显式 seed + 115 legacy)

---

## 7. 剪辑去重 pipeline

### 7.1 11 recipe 实现状态 (100% KS184 对齐)

| recipe | 对齐度 | 时延 (10s on 58s 1080×1920) | 输出 | 特征 |
|---|---|---|---|---|
| `mvp_trim_wipe_metadata` | 100% | <1s | 原码率 | `-c copy` 抹 metadata |
| `light_noise_recode` | 100% | ~3s | ~5MB | 轻噪点 + 调色 |
| `mode3_overlay` / `touming_9gong` | 85% | 3.9s | 1.9MB | 9 帧 tile=3x3 + blend opacity=0.3 + **matroska 伪装** |
| `wuxianliandui` | 60% | 2.5s | 2.3MB | `force_key_frames expr:eq(n,20)` |
| `bushen` | 85% | 4.9s | 5.1MB | cfg64.exe 独占 + 噪点+调色 |
| `yemao` | 80% | 2.4s | 7.2MB | **split=12+xstack** 12 格 240×320 马赛克 |
| `zhizun` / `zhizun_overlay` | 95% | 22s | 68MB | 九宫格 overlay + libx264 crf 18 |
| `zhizun_mode5_pipeline` ⭐ | **100%** | 11.6s | 46MB | 4 步 blend+zoompan+**interleave**+matroska 伪装 (KS184 默认) |
| `rongyu` (旧名 rongyao 兼容) | 80% | 33.6s | 148MB | unsharp + slow + crf 18 (KS184 内部名 rongyu) |
| `kirin_mode6` ⭐ | **100%** | ~15s | ~50MB | 7 步 ffmpeg argv 完全对齐 |

**多步 pipeline** (不走 RECIPES 单命令):
- `kirin_mode6` — `process_kirin_mode6()` 7 步
- `zhizun_mode5_pipeline` — `process_zhizun_mode5_pipeline()` 4 步

### 7.2 6 种 image_mode (生成干扰素材 PNG)

| mode | 实现 | 耗时 | 用途 |
|---|---|---|---|
| `qitian_art` | 深渐变 + 几何 + 光斑 + 大字 | 0.08s | 抽象艺术封面/干扰 |
| `gradient_random` | 纯同色系渐变 + 大字描边 | 0.05s | 极简 |
| `random_shapes` | 4×6 grid 随机三角/方/圆 | 0.04s | 几何阵列 |
| `mosaic_rotate` | 视频抽 9 帧 + 随机旋转 + 3×3 拼 | 0.16s | 9 宫格马赛克 |
| `frame_transform` | 视频抽 1 帧 + blur/saturate/darken | 0.08s | 帧变换 |
| `random_chars` | 随机字符铺背景 + 半透明黑条 + 大字 | 0.17s | 字符阵列 |

实现: `core/qitian.py` + 统一分发 `core/processor.py::_generate_pattern_by_mode`

### 7.3 7 动画 (zoompan filter)

实现: `core/pattern_animator.py::get_animation_filter`

```python
zoom_in      zoompan=z='min(zoom+0.001,1.5)':d=N
zoom_out     zoompan=z='max(1.5-zoom*0.001,1.0)':d=1
zoom_pulse   zoompan=z='1.15+0.15*sin(2*pi*t/4)':d=1    # 4 秒周期
pan_right    crop=w:h:x='t/T*max_x':y=0                  # 用 crop 非 zoompan
pan_left     crop=w:h:x='max_x-t/T*max_x':y=0
rotate_cw    rotate=a='2*pi*t/T/4':c=none:ow=W:oh=H     # T 秒转 90°
rotate_ccw   rotate=a='-2*pi*t/T/4':c=none:ow=W:oh=H
```

### 7.4 Pipeline 7 Stage

```
Stage 1    downloading        FileLock("download", drama_name) + HLS/短链/直链
Stage 1.5  md5_modifying      末尾追加 8-32 随机字节
Stage 2    processing         FileLock("process", input_path) + RECIPE 分发
Stage 3.5  cover_watermark    cover_service (下载/缓存/尺寸/压缩) → burn_cover
Stage 3    publishing         publisher.py (cover_path_override)
```

### 7.5 AI 可选组合武器库

```
recipes (11) × image_mode (6) × fonts (3+) × watermark_style (5) = 990+ 组合
```

Dashboard **🔀 去重组合** 页可视化.

### 7.6 3:4 前置 (scale34)

`core/scale34.py` 独立模块:
- 输入 720×1280 → 输出 716×954 (UI "3:4 模式" 勾选时前置)
- 模糊背景 (boxblur=10) + pad + 3 drawtext (剧名/账号/页码)
- **sin 动态水印** (反视觉指纹, T 和 φ 每次任务随机):
  ```
  x = 50 + 258 + 258*sin(2π*t/T1) + 129*sin(2π*t/T2 + φ1)   T1∈[70,95], T2∈[40,60]
  y = 76 + 50 + 336 + 336*sin(2π*t/T3 + φ2) + 168*sin(2π*t/T4 + φ3)
  ```

---

## 8. 发布 pipeline

### 8.1 sig3 路径 (主力)

```
publisher.publish_video(account_id, video_path, drama_name)
  │
  ├─ caption 构造 (template / drama_hashtag / drama_name)
  ├─ quiet_hours 守门 (publisher.quiet_hours.* config)
  │
  ├─ _upload_pre (获取 token + endpoint)
  ├─ _upload_fragments (分片 HTTP PUT)
  ├─ _upload_complete
  ├─ _upload_finish (拿 fileId / photoIdStr)
  │
  ├─ _get_banner_task (drama-level 缓存 → 查 MCN MySQL → DEFAULT 170767)
  ├─ _upload_cover (封面 PNG / JPEG 上传)
  │
  ├─ _build_submit_payload
  │    42 字段 = { fileId, coverKey, caption,
  │               photoStatus ← visibility,
  │               downloadType ← interaction.allow_download,
  │               disableNearbyShow ← !interaction.show_in_local,
  │               allowSameFrame ← interaction.allow_copy_shoot,
  │               declareInfo.source ← author_statement,
  │               bannerTask, apdid, ... }
  │
  ├─ sig3 = SigService.sign(payload)   # HMAC-SHA256 truncate 28 bytes
  │
  └─ _submit (POST /submit?__NS_sig3=<hex>)
        │
        ├─ result=1  → 成功 (photo_id)
        ├─ result=109/112/120 → sig3 错误 → 重试 MAX_RETRIES 次
        │     │
        │     └─▶ MCN 中继 fallback (enable_mcn_relay_fallback=true)
        │            submit_via_relay(payload, apdid)
        │            → MCN :50002 代签 → 200 OK = 成功
        │
        └─ 其他 → 失败记录 (Watchdog 5min 接手)
```

### 8.2 MCN 中继协议 (:50002 容灾)

`core/mcn_relay.py` 260 行, 5 shortcut + 1 generic:

```python
is_relay_online()                         # ping
upload_query_via_relay(body, apdid)       # uploadType 查询
search_via_relay(title, cursor, apdid)    # 作品搜索
upload_finish_via_relay(...)              # 上传完成
submit_via_relay(body, apdid)             # ★ 发布 fallback
generic_relay(path, body, apdid)          # 通用代签

# 双签名 (Frida 2026-04-20 100% 验证)
compute_sig3(uid, ts, nonce_b64)
compute_mcn_signature(body_b64, nonce)
verify_mcn_response(body_b64, nonce, response_hex)
```

**响应** 28 字节加密 ack (不含业务数据). HTTP 200 = 成功.

### 8.3 发布后反馈闭环

```
publish_results (id / photo_id / status)
     │
     ▼ 24h 后 MCN snapshot
mcn_member_snapshots (member_id = numeric_uid)
     │
     ▼ Analyzer 17:00 聚合
publish_daily_metrics (account_id, date, income_delta)
     │
     ▼
strategy_rewards (Bandit 更新)
     │
     ▼ 下次 StrategyPlanner 08:00 用
match_score = tier_weight + income_bonus + heat_bonus + diversity - cooldown - recent_fail
```

---

## 9. Dashboard (11+ 页)

### 9.1 页面列表

| # | 页面 | 数据源 |
|---|---|---|
| 1 | 🏠 **总览** | daily_plan_items + mcn_member_snapshots + autopilot_cycles |
| 2 | 📋 **任务** | daily_plan_items + task_queue (今日 2h) |
| 3 | 🩺 **自愈** | healing_playbook + healing_diagnoses + rule_proposals (**可审批**) |
| 4 | 💎 **收益** | mcn_member_snapshots + publish_daily_metrics + strategy_rewards |
| 5 | 🎨 **Qitian** | qitian.generate() 6 风格互动预览 |
| 6 | ⚙️ **配置** | app_config (318 keys 按 prefix 分组) |
| 7 | 👤 **账号详情** | 7天plan + 72h task + healing + 14天收益曲线 + 4 一键操作 |
| 8 | 🎬 **剧详情** | 被哪些账号发过 + match_score 对比 + 30天记录 |
| 9 | 🔍 **全局搜索** | 跨账号/剧/photo_id/task_id 模糊查 |
| 10 | 🛠️ **批量操作** | 多选 tier / 批量 cancel / 批量 retry (写 dashboard_bulk_ops) |
| 11 | 📊 **数据导出** | 5 种报表 CSV + Excel (openpyxl) |
| 12 | 🔀 **去重组合** | 11×6×3×5 = 990 组合 武器库预览 |

### 9.2 启动

```bash
python scripts/run_dashboard.py           # http://127.0.0.1:8501
python scripts/run_dashboard.py --debug   # 自动 reload
python scripts/run_dashboard.py --port 8502 --host 0.0.0.0
```

### 9.3 对齐 UI (9 大板块 / 318 keys 可视化)

`⚙️ 配置` 页按 prefix 分 12 tab:
- video (60) / cover (28) / publisher (15) / account (27) / collector (20)
- dashboard (12) / batch_query (13) / earnings (11)
- remote_drama (10) / watermark (5) / execution (1) / cleanup (1)
- legacy (115)

---

## 10. 逆向工程工具链

### 10.1 KS184 原始软件

- **位置**: `C:\Program Files\kuaishou2\KS184.7z\KS184\`
- **架构**:
  - `kuaishou_multi_control_ZUFN.exe` = **32-bit** C++ shell (WinLicenseSDK, 无 Python)
  - `Q_x64.dll` = 子进程 **64-bit** (内嵌 Python 3.12 + requests)
- **保护**: PyArmor + startup anti-hook + WinLicense

### 10.2 绕过路径 (实测有效)

| 路径 | 工具 | 状态 |
|---|---|---|
| Memory dump 扫描 | `tools/dump_q_x64_memory.py` | ✅ 1.9GB dump, 字符串/argv 全取 |
| Frida attach (运行中 pid) | `tools/frida_hook_mcn_v2.py` | ✅ 10 crypto hooks, 抓到 291 调用 |
| Frida spawn+gate | `tools/spawn_and_hook.py` | ❌ PyArmor 杀 |
| Bytecode dump | `tools/dump_firefly_bytecode.py` | ✅ 205 fn 函数名/变量名 |
| 静态反编译 | `docs/KS184_Q_X64_DECOMPILE.md` | ✅ 1117 行 10 mode 文本流程 |
| MySQL 直连 | 凭证见 §1 | ✅ 50 张表 |

### 10.3 Frida 脚本清单

| 文件 | 用途 | 实战状态 |
|---|---|---|
| `frida_hook_mcn_v2.py` | MCN 加密破解 (10 hooks) | ✅ 抓到 sig3 签名 byte-level |
| `frida_hook_subprocess.py` | 抓 ffmpeg argv | ✅ 25 条 canonical argv |
| `inject_publish_trace.py` | 最小安全 hook (requests) | ✅ 发布流程抓 |
| `watch_and_inject.py` | 轮询 + 自动 attach | ✅ 新 Q_x64 启动自动挂 |
| `hook_zufn_winhttp.py` | Shell 层 WinHTTP hook | 实验性 |

### 10.4 Canonical 参考文档

- **`KS184_下载剪辑去重_Canonical参考v3.md`** — 最新, dump 扫出 8 zoompan + 6 rotate + 18 crop 真实 argv
- `KS184_下载剪辑去重_Canonical参考v2.md` — Frida 25 argv + sin 公式
- `docs/KS184_Q_X64_DECOMPILE.md` — 1117 行静态反编译
- `docs/KS184_ANALYSIS_COMPLETE.md` / `KS184_REVERSE_ENGINEERING_REPORT.md` — 早期分析

---

## 11. CLI 脚本索引 (71 脚本)

### 11.1 日常运营 (每日跑)

```bash
python -m scripts.refresh_hot_rankings              # 外部+内部热榜
python -m scripts.collect_daily_metrics             # 13 账号每日指标
python -m scripts.sync_mcn_business                 # MCN 绑定+收益
python -m scripts.sync_mcn_cookies                  # MCN cookie 同步
python -m scripts.sync_drama_library                # collect-pool → drama_links
python -m scripts.snapshot_mcn_members              # 成员 snapshot (580 行)
python -m scripts.consolidate_memories              # AI 记忆合并
```

### 11.2 采集 + 作者库

```bash
python -m scripts.search_authors --keyword 短剧,甜宠,霸总 --pages 2
python -m scripts.collect_dramas --from-authors --author-limit 5
python -m scripts.harvest_authors --all --limit 15
python -m scripts.harvest_banner_tasks              # banner_task 批量抓
python -m scripts.fill_drama_links                  # drama_links 补链
python -m scripts._fix_drama_names                  # 清 hashtag 脏数据
```

### 11.3 健康检查 (read-only)

```bash
python -m scripts.test_cookie                       # 12/13 valid
python -m scripts.test_mcn_standalone
python -m scripts.test_publisher_dryrun --account 思莱短剧 --drama 仙尊下山
python -m scripts.test_dashboard_queries            # 18 SQL 查询
```

### 11.4 AI 决策 + 自愈

```bash
# 单独跑某 agent
python -m core.agents.strategy_planner_agent --dry-run
python -m core.agents.analyzer_agent --dry-run
python -m core.agents.llm_researcher_agent --mode all     # strategy + propose_rules + propose_upgrades
python -m core.account_tier --dist                   # 看分布
python -m core.account_tier --run                    # 评估 (dry)
python -m core.account_tier --apply                  # 真迁移

# E2E 验收
python -m scripts.validate_ai_decision_e2e
python -m scripts.validate_week1_e2e
python -m scripts.test_match_scorer                  # 650 pairs → 39 items
python -m scripts.test_scheduler_concurrency          # B-1/B-2/B-3
python -m scripts.test_healing_e2e --only cluster    # 失败聚类
```

### 11.5 发布测试

```bash
python -m scripts.publish_once --account ... --drama ...
python -m scripts.run_pipeline                        # 7 stage 跑通一次
python -m scripts.run_batch                            # 批量跑
python -m scripts.run_orchestrator                     # ControllerAgent 启动
python -m scripts.test_publisher_fallback              # sig3 + mcn_relay 两路对比
python -m scripts.test_mcn_signature                   # 3/3 双签名公式验证
python -m scripts.test_mcn_relay                       # 5/5 shortcut 验证
```

### 11.6 迁移 (v1-v22)

```bash
python -m scripts.migrate_v1   # 7 MCN 表 + 10 列
python -m scripts.migrate_v2   # drama_banner_tasks (4 seed)
# ... (省略 v3-v19)
python -m scripts.migrate_v20  # AI 决策 6 表 + 32 config
python -m scripts.migrate_v21  # 自愈补洞 5→10 规则 + LLM 深度联动
python -m scripts.migrate_v22  # (预留)

# 全板块 UI config
python scripts/register_dedup_configs.py   # 318 keys idempotent
```

### 11.7 Dashboard + 工具

```bash
python scripts/run_dashboard.py            # Streamlit 11 页
python scripts/switches_cli.py             # 特性开关 CLI
```

### 11.8 MCN 协议研究 (P2, 已完成)

```bash
python -m scripts.dump_mcn_relay_samples          # 扫 trace 375 条 :50002
python -m scripts.analyze_mcn_relay_paths          # 4 shortcut + generic 分类
python -m scripts.analyze_mcn_relay_response       # 长度/熵/前缀分析
python -m scripts.verify_mcn_hmac_v2               # HMAC 公式验证 (Frida ground truth)
python -m scripts.crack_mcn_relay_v2               # XOR/AES 破解尝试 (结论: 响应是 ack 非业务)
```

---

## 12. 测试 + 验收

### 12.1 测试矩阵 (70+ tests 全通)

| 层 | 测试文件 | 验证点 |
|---|---|---|
| Cookie | `test_cookie.py` | 12/13 账号 valid |
| MCN | `test_mcn_standalone.py` | login + members + verify |
| Publisher | `test_publisher_dryrun.py` | 7 步 dry run |
| Publisher fallback | `test_publisher_fallback.py` | sig3 vs MCN 中继两路 |
| MCN 中继 | `test_mcn_relay.py` | 5/5 shortcut + roundtrip |
| MCN 签名 | `test_mcn_signature.py` | 3/3 compute_sig3 + compute_mcn_signature |
| Match 评分 | `test_match_scorer.py` | 650 pairs × 5 scenario |
| Scheduler | `test_scheduler_concurrency.py` | B-1/B-2/B-3 |
| 自愈 | `test_healing_e2e.py` | 聚类 + LLM propose |
| Dashboard | `test_dashboard_queries.py` | 18/18 SQL |
| AI 决策 E2E | `validate_ai_decision_e2e.py` | planner → scheduler → executor |
| Week 1 E2E | `validate_week1_e2e.py` | 全流程 |
| Smoke R2 | `smoke_test_round2.py` | 4/4 recipe × image_mode |
| Smoke R3 | `smoke_test_round3.py` | 6/6 水印样式 |
| Account memory | `test_account_memory_e2e.py` | AI learning |

### 12.2 回归用命令

```bash
# 快速烟雾测试
python scripts/register_dedup_configs.py && \
python -m scripts.test_cookie && \
python -m scripts.test_dashboard_queries && \
python -m scripts.test_mcn_signature && \
python -m scripts.smoke_test_round2 && \
python -m scripts.smoke_test_round3

# 深度验收
python -m scripts.validate_ai_decision_e2e
python -m scripts.test_healing_e2e
```

---

## 13. 已知限制 + Roadmap

### 13.1 KS184 对齐度 (2026-04-20 最终)

```
剪辑去重:      100% ✅  (11 recipe + 6 image_mode + 7 animation)
矩阵调度:       75% ⭐⭐⭐  (B+A, 100 账号前还要扩)
自愈+LLM:       85% ⭐⭐   (10 规则 + LLM 自主 propose)
容灾 fallback:  95% ⭐⭐⭐  (F MCN 中继全通, J-Frida 双签名公式)
可视化:         90% ⭐⭐   (11+ 页)
异常监控:       95% ⭐⭐
协议逆向:      100% ⭐⭐⭐  (sig3 + MCN signature 完整破解)
配置完整度:     99% ⭐⭐⭐  (318 keys 对齐 16+ UI 截图)
```

### 13.2 已知未完成 (P2)

- **视频动态水印扩到其他 recipe** (目前只 scale34 用 sin 抖动)
- **wuxianliandui 多步 concat** (需 Frida 再抓)
- **rongyu 真 argv** (目前猜测, 需 Frida 再抓)
- **MCN 响应 28 字节解密** (Frida 脚本就绪, 需要 KS184 真跑一次发布时抓). **价值不高** — 响应是 ack 不是业务数据, sig3 已可自签
- **HighIncomeDramas 列表** — PyArmor + role 403 双重锁死. Workaround: collect-pool + GraphQL search
- **Dashboard 公网部署** — 需 streamlit-authenticator + nginx + HTTPS
- **批量作品查询 / 同框检测** — UI key 已注册 (K 板块), 但后端逻辑未实现
- **收益查询分页导出** — UI key 已注册 (L 板块), 只读 Dashboard 可用, 独立页待开发

### 13.3 Roadmap

```
本月 (2026-04):
 ✅ Week 1-2  AI 决策 + 剪辑去重 + 反馈闭环
 ✅ Week 3    B+A+D+E+F+H+G+J+K (12 板块 UI 对齐)
  ⏳ 真实发布验证 (用户开 publisher.enable_mcn_relay_fallback=true)

下月 (2026-05):
  • 矩阵扩张到 30 账号 (daily_plan 容量 × 2)
  • Dashboard auth + 公网部署
  • 批量作品查询后端 (同框检测 API)
  • 收益查询独立页 (含 xlsx 导出)

季度目标 (2026-Q2):
  • 100 账号矩阵 (Celery + PG 迁移)
  • 星火计划 (promotion_type=7) 激活验证
  • 完整 GUI 控制台 (Electron/PyQt 二选一)
```

---

## 14. 关键工程教训

### 14.1 不要轻易归咎"依赖/版本"

mode5 pipeline interleave 最初报 `Assertion best_input >= 0 failed`.
我说 "需要特殊编译 ffmpeg" — **错**.
真相: imgvideo 时长比 src 短 0.00476s (float 精度).
修复: `-t total_dur + 2.0` + `tpad stop=140` buffer.
**教训**: **先 ffprobe 实测精确时长**, 再下结论.

### 14.2 Frida argv ≠ 可直接复刻

KS184 imgvideo 时长**恰好整数**, 我们浮点会差 0.005s.
**教训**: 复刻 pipeline **给时长加 buffer** 是通用良方.

### 14.3 "默认策略" 必须 benchmark

我最初默认 mode5 用 overlay, 说它"速度快、兼容好". **两点都错**.
实测: interleave **11.6s < overlay 14.1s**, KS184 自带 ffmpeg 100% 兼容.
**教训**: **3 次连测稳定才能定默认**.

### 14.4 用户审计 ≫ AI 自评

审计前我估去重完整度 92%, 用户实际 62%.
真实缺口**不在算法**, **在配置灵活性 + 素材池 + 集成度**.
**教训**: 报数字前先**系统性核对 UI + 代码双向对齐**.

### 14.5 配置注册 ≠ 代码读取

DB 注册 318 key 只是第一步. 必须**验证代码真的读**.
这次的坑: `bool("false") == True` — 老 Python 陷阱, 影响 7 动画默认状态.
修复: `_cfg_bool` 辅助函数 + 提前在 migrate 里写 `value_type=bool`.
**教训**: **每个新 key 写一个 smoke test 读它**.

### 14.6 两份数据源互补

- **Canonical v3** (dump argv): **怎么做** — 精确 argv / crf / preset
- **Q_X64_DECOMPILE** (静态反编译): **做什么** — 模块树 / 算法流程 / SQL schema

复刻算法用 canonical, 扩展功能 (自愈/autopilot/qitian) 用 DECOMPILE.

### 14.7 PyArmor + WinLicense 不可 spawn-hook

尝试 Frida `spawn+child-gating` 均 `access violation 0x60`.
**有效路径**: 等 Q_x64 跑稳 → attach pid → hook `requests.Session.request` 或 `libcrypto`.
**教训**: 别浪费时间破 spawn, **attach 运行中进程** 够用.

### 14.8 响应加密不一定是业务数据

花了 2h 破 MCN 28 字节响应 (试 HMAC / AES / XOR 6 种算法 288 组合). 
最终发现: **响应是 ack 签名, 业务数据在 HTTP 200 本身**.
**教训**: 破加密前先问 "里面装的是什么". 28 字节装不下 photoIdStr JSON — 一开始就该怀疑.

---

## 附录 A: 典型操作手册

### A.1 新账号接入

```bash
# 1. KS184 软件扫码登录 → DB 自动落 device_accounts
# 2. 同步 numeric_uid
python -c "
import sqlite3, json, re
conn = sqlite3.connect(r'C:\Users\Administrator\AppData\Local\KuaishouControl\data\kuaishou_control.db')
rows = conn.execute('SELECT id, cookies FROM device_accounts WHERE numeric_uid IS NULL').fetchall()
for rid, ck in rows:
    m = re.search(r'userId=(\d+)', ck or '')
    if m:
        conn.execute('UPDATE device_accounts SET numeric_uid=? WHERE id=?', (int(m.group(1)), rid))
conn.commit()
"
# 3. 健康检查
python -m scripts.test_cookie
```

### A.2 新剧入库 (冷启动)

```bash
# 1. 作者库扩充
python -m scripts.search_authors --keyword 霸总,甜宠,仙侠 --pages 3

# 2. 从作者库拉 feed
python -m scripts.collect_dramas --from-authors --author-limit 50

# 3. MCN banner_task 补齐 (同步 128,750 条 shortju 剧)
python -m scripts.sync_drama_library

# 4. 验证
python -c "
import sqlite3
c = sqlite3.connect(r'C:\...kuaishou_control.db')
print('drama_links:', c.execute('SELECT COUNT(*) FROM drama_links').fetchone()[0])
print('drama_banner_tasks:', c.execute('SELECT COUNT(*) FROM drama_banner_tasks').fetchone()[0])
"
```

### A.3 启动全自动

```bash
# 1. 启动 Hermes LLM (新终端)
start "Hermes" "C:\Users\Administrator\Desktop\Hermes Gateway.cmd"

# 2. 启动 ControllerAgent (14 块逻辑全跑)
python -m scripts.run_orchestrator

# 3. Dashboard 观察
start python scripts/run_dashboard.py

# 一切正常时 log 会打:
#   [controller] autopilot_cycle #884 started
#   [planner] generated 39 items
#   [scheduler] claimed 5 items → task_queue
#   [executor] stage=downloading account=思莱短剧
#   [watchdog] 0 stuck tasks
#   [analyzer] aggregated 13 accounts
```

### A.4 事故响应

| 症状 | 排查 |
|---|---|
| 全账号发布失败 `result=109` | sig3 协议变 → SelfHealing 自动触发 `sig3_signature_error` rule → critical alert + 6h 冷却 |
| 某账号连续 3 次 429 | Watchdog 自动冻结 24h → `account_tier_transitions` 记录 |
| task stuck > 1h | Watchdog 重排上游 (rule: `task_stuck_running_1h`) |
| MCN 响应 != 28 字节 | `classify_response_fingerprint` 预警, 可能服务端协议变 |
| Dashboard 报 SQL error | `python -m scripts.test_dashboard_queries` 18 个 query 逐一排查 |
| LLM propose 空 | 检查 Hermes online (`curl http://127.0.0.1:8642/v1/models`) |

---

## 附录 B: 核心数据流 (ER 图简版)

```
device_accounts ───┬─ mcn_account_bindings
     │ id          │
     │             └─ mcn_member_snapshots (member_id = numeric_uid)
     │                       │
     │                       ▼
     │             publish_daily_metrics (income_delta)
     │                       │
     │                       ▼
     │             strategy_rewards (Bandit)
     │                       │
     ├─ account_tier_transitions
     │
     ├─ daily_plan_items ── task_queue ── publish_results
     │       │                                     │
     │       └─ plan_item.sched_at                 └─ photo_id (快手)
     │
     └─ healing_diagnoses ── healing_actions
              │                    │
              └── healing_playbook (v21: 10 rules)
                         │
                         └── rule_proposals (LLM 建议, 待审批)

drama_links ──┬─ drama_banner_tasks (drama-level 缓存)
     │        │
     │        ├─ drama_authors
     │        │
     │        └─ download_cache (drama_name + hash)
     │
     └─ account_published_works ── account_drama_execution_logs
```

---

## 附录 C: 重要文件位置

```
# KS 自研代码
D:\ks_automation\
├── core\              80 模块 (见 §4)
├── scripts\           71 脚本 (见 §11)
├── dashboard\          1 Streamlit 应用 (11+ 页)
├── docs\              17 文档 (本文档 + KS184_Q_X64_DECOMPILE 等)
├── tools\             39 工具 (Frida / dump / trace)
├── assets\fonts\       8 艺术字体 (KS184 复刻)
├── qitian_samples\    12 PIL 样本图
└── CLAUDE.md          AI 项目记忆 (~500 行, 每 session 读)

# KS184 原始软件 (逆向源)
C:\Program Files\kuaishou2\KS184.7z\KS184\
├── kuaishou_multi_control_ZUFN.exe   32-bit shell
├── Q_x64.dll                          64-bit Python 子进程
├── tools\ffmpeg\bin-xin\ffmpeg.exe    NVENC 主 binary
├── tools\ffmpeg\bin4\cfg64.exe        不闪独占
└── tools\m3u8dl\N_m3u8DL-RE.exe       HLS 下载

# 数据库 + 数据
C:\Users\Administrator\AppData\Local\KuaishouControl\data\
└── kuaishou_control.db               SQLite WAL (89 表, 318 configs)

# 外部服务
http://127.0.0.1:8642   Hermes LLM (OpenAI 兼容)
http://127.0.0.1:8501   Streamlit Dashboard
mcn.zhongxiangbao.com:88     MCN login
im.zhongxiangbao.com:3306    MCN MySQL 直连
im.zhongxiangbao.com:8000    MCN verify
im.zhongxiangbao.com:50002   MCN 中继代签 (sig3 容灾)
```

---

**文档维护**: 每大版本 (B/A/D/E/F/G/H/J/K/L 板块) 完成后更新. 下次重大更新预期: 真实发布验证后 (Week 4).

**引用**:
- CLAUDE.md — 项目记忆 (500 行, 历史时间线)
- KS184_下载剪辑去重_Canonical参考v3.md — dump argv 最新
- KS184_Q_X64_DECOMPILE.md — 1117 行静态反编译
- DATABASE_DETAILED_SCHEMA.md — 30+ 张生产表详细 schema (~2000 行)
