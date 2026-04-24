# UI 重设计 AI 提示词 — 完整系统版 v2

> 用途: 让 AI 真正理解本系统的完整架构、运行模式、业务逻辑, 然后做出**合理的 UI**.
>
> 使用: 整块复制下方 "提示词正文", 粘贴给 AI (Cursor / v0.dev / Lovable / Claude 等).

---

# 📋 提示词正文 (以下整块复制)

```markdown
# 角色

你是资深产品设计师 + 全栈工程师, 擅长:
- Windows 桌面商业软件 (PyQt / Electron)
- 数据可视化仪表盘
- B2C SaaS 产品 UX
- 付费软件的订阅和激活流程设计

接下来我会给你**完整的系统背景** (A 部分) + **UI 设计任务** (B 部分).

请先仔细读完 A 部分, 再做 B 部分. 不要跳过或简化 A.

---

# A 部分: 系统全景 (务必细读)

## A.1 产品本质

**一句话**: 这是一个"让快手短剧 CPS 矩阵运营 **全自动**" 的 Windows 桌面软件.

**用户装上它之后**:
1. 加 10-500 个快手账号 (扫码或 Cookie)
2. 绑定 MCN (已内置 `zhongxiangbao` 机构接入)
3. 点"开始" → 软件 24/7 自动跑
4. 每天打开看收益即可

**软件 24/7 都在干什么** (用户看不到但后台在做):
- 自动扫描快手作者, 发现爆款剧 (🔥 爆款雷达)
- 自动选剧 (AI 综合评分 20+ 信号)
- 自动下载视频 (从 CDN 直链)
- 自动剪辑去重 (11 种算法 + 水印)
- 自动发布到矩阵账号 (模拟真人操作 + sig3 签名)
- 自动记录每条视频的效果 (发布后 24h/48h/7d)
- 自动学习 — 发现"哪种剧哪个账号效果好"(3 层 AI 记忆)
- 自动调整策略 (每周一 LLM 研究员出建议)
- 自动自愈 — cookie 过期/账号冻结/服务故障全自动修
- 自动风控 — 限频/黑名单/熔断保护

**对用户而言**: 就是"一键挂机挣钱", 像炉石传说的"自动"模式.

## A.2 完整架构 (8 层)

```
┌───────────────────────────────────────────────────────┐
│ L8 用户界面 (本次 UI 重做的目标)                      │
│    - 桌面窗口 (PyQt / Electron)                        │
│    - 新手模式 + 高级模式                               │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L7 Autopilot (24/7 主循环, 每 60 秒 1 cycle)         │
│    ControllerAgent.run_cycle()                        │
│    按 26 个 step 检查, 到期的触发                      │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L6 9 个后台 Agent (定时任务)                          │
│   - StrategyPlanner  每日 08:00 生成计划              │
│   - TaskScheduler    每 2h 把计划转入队列             │
│   - BurstAgent       每 30min 爆款响应                │
│   - Maintenance      每 1h 维护 (刷 cookie/token)     │
│   - Analyzer         每 1h 聚合数据                   │
│   - Watchdog         每 5min 自愈                     │
│   - LLMResearcher    每 12h 写周记 + 规则建议        │
│   - HotHunter        每 2h 扫爆款雷达 (新!)           │
│   - OutcomeCollector 每 1/3/12h 回采结果             │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L5 Executor (三池并发 worker)                         │
│   - burst 池       (爆款跟发 priority=99)             │
│   - steady 池      (planner 主力)                     │
│   - maintenance 池 (cookie 刷新/维护)                 │
│   每池 N 个 worker 从 task_queue 抢任务               │
│   account_locks 表保证"同账号同时只能跑 1 个"          │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L4 Pipeline (发布流水线, 每任务跑一次)                │
│   Stage 1  下载       (HLS / CDN 直链 / 短链)          │
│   Stage 1.5 MD5 修改  (末尾追加随机字节)               │
│   Stage 2  去重处理   (11 recipe × 6 image_mode)       │
│   Stage 3.5 封面水印  (自动烧字幕 + 动态位置)          │
│   Stage 3  发布上传   (6 步: upload/finish/submit)     │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L3 决策层 (AI 选剧 + 选账号)                          │
│   - candidate_builder  7 层漏斗 (134k 剧 → TOP 30)    │
│   - match_scorer       20+ 信号 (account×drama 打分)  │
│   - 3 层 AI 记忆       Layer 1/2/3 (决策→聚合→周记)   │
│   - LLM 批量介入       Phase 1 100% → Phase 4 5%      │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L2 数据源                                              │
│   - MCN MySQL 实时     (spark_drama_info 134k 剧库)   │
│   - MCN 本地镜像       (wait_collect_videos 22k URL)  │
│   - 快手原生 API       (profile/feed + graphql 爆款)   │
│   - publish_outcome   (发布结果 → 反向学习)            │
└──────────────────────┬────────────────────────────────┘
                       ↓
┌───────────────────────────────────────────────────────┐
│ L1 基础设施                                            │
│   - SQLite + WAL + 80+ 表                              │
│   - MCN 代签 :50002 (sig3) / :50003 (sig4)            │
│   - 熔断器 (4 MCN breakers: mysql/url/sig3_p/sig3_f)   │
│   - 运营模式 5 档 (startup/growth/volume/matrix/scale) │
└───────────────────────────────────────────────────────┘
```

## A.3 数据流 (端到端)

### 流程 1: 爆款雷达 → 选剧 → 发布 → 学习 (核心流)

```
[每 2 小时]
  HotHunterAgent 扫 30 个高权重作者
    ↓ 调 profile/feed API (带 KWW 签名)
  拿到 20+ 条最新作品 (含 views/likes/cdn)
    ↓
  宽容过滤 (age<14天 + views>1k + 非机刷)
    ↓
  UPSERT hot_photos 表 (加副产品: CDN 进 drama_links, 作者进 drama_authors)

[每日 08:00]
  StrategyPlanner.run()
    ↓ 1. 从 candidate_builder 拿 TOP 30 候选剧
        (7 层漏斗: L0 hot_photos + L1 base + L2 url + L3 非黑 + L4 非违规 + L5 新鲜 + L6 scored)
    ↓ 2. 对每 (account × drama) 组合打分
        (match_scorer 20+ 信号加总)
    ↓ 3. 贪心分派 (好机会→好账号)
    ↓ 4. 每账号保底 1 条 (不饿死)
    ↓ 5. A/B 实验组抽 10% (探索)
  写 daily_plan_items 表 (10-50 条)
  同时写 decision_history (Layer 1 记忆, 记录 hypothesis)

[每 2 小时]
  TaskScheduler.run()
    ↓ 找 scheduled_at < now 的 plan_items
    ↓ 读 drama 的 banner_task_id (MCN lookup)
    ↓ 插 task_queue (status='queued')
  更新 decision_history.task_id (关联已入队)

[实时, worker 抢任务]
  Executor 三池 worker
    ↓ _claim_task (BEGIN IMMEDIATE + account_locks PRIMARY KEY 互斥)
    ↓ 拿到 task, pipeline 开跑

  Pipeline.run_publish_pipeline():
    ↓ Stage 1  下载 (downloader._candidate_urls)
        L1 本地 drama_links  ← 先试
        L2 MCN wait_collect 实时  ← 再试
        L0.5 ks_profile_collector  ← 最后兜底 (按需采)
    ↓ Stage 1.5 MD5 修改
    ↓ Stage 2  去重 (process_video: kirin_mode6 / zhizun_mode5 / 等 11 种)
    ↓ Stage 3.5 封面水印 (drama_name 居中 + @账号右下)
    ↓ Stage 3  发布 (6 步: upload_pre/fragments/complete/finish/cover/submit)
    ↓ 成功 → 写 publish_outcome 表 (Layer 1 反馈入口!)
    ↓ account_lock 释放

[发布 24h / 48h / 7d 后]
  OutcomeCollector.collect_pending_outcomes(mode)
    ↓ 调 ks_profile_collector.search_drama_by_name
    ↓ 找我们的 photo_id, 拿 views/likes
    ↓ 更新 publish_outcome.views_24h/views_48h/views_7d

[每日 17:00]
  Analyzer.run()
    ↓ 从 publish_outcome 算 verdict (correct/over_optimistic/wrong)
    ↓ 更新 decision_history.verdict (闭环)
    ↓ 聚合到 account_strategy_memory (Layer 2)
    ↓ 触发 tier 评估 (可能 new → testing → warming_up → established → viral)
    ↓ 调 signal_calibrator (Week 3+) 自动算信号-ROI 相关性
    ↓ 可能自动调 match_scorer 权重

[每 12 小时]
  LLMResearcher.run(mode='all')
    ↓ 读 Layer 1 + Layer 2
    ↓ 调 Hermes LLM 写周记 (Layer 3)
    ↓ 分析未匹配 failed 任务, 提新 healing 规则
    ↓ 审计低成功率规则, 提升级建议
    ↓ 写 research_notes + rule_proposals (等人审批)

[用户手工审批 (或 Dashboard 一键)]
  research_notes.approved = 1
    ↓ 规则进入 match_scorer 权重
    ↓ 下周 planner 跑时生效
```

### 流程 2: 自愈 (故障自动修)

```
[每 5 分钟]
  Watchdog.run()
    ↓ 查近 1h failed task, 聚类 error
    ↓ 检查 account_locks 有无僵尸
    ↓ 检查 frozen 账号是否到 48h 可恢复
    ↓ 检测 violation burst (24h 违规 >3 → 自动 FREEZE)
    ↓ 连 3 次 session 错 (109/112/120) → 自动 FREEZE

[SelfHealing (watchdog 触发后)]
  查 healing_playbook (12 条规则)
    ↓ 匹配 error_message 模式
    ↓ 执行 action:
        - REFRESH_KUAISHOU_COOKIE (109 错)
        - COOLDOWN_DRAMA (短链限流)
        - ENQUEUE_FREEZE_ACCOUNT (违规)
        - BLOCK_PLAN_ITEM (MCN 黑名单)
    ↓ 更新 healing_playbook.success_count/fail_count
    ↓ 写 healing_diagnoses 流水
```

### 流程 3: 熔断保护 (外部故障自适应)

```
客户端调 MCN / 快手 API
    ↓
circuit_breaker 3 状态机:
    CLOSED → 3 次失败 → OPEN (熔断, fast-fail)
    OPEN → 60s 冷却 → HALF_OPEN (试探)
    HALF_OPEN → probe 成功 → CLOSED
               → probe 失败 → OPEN

4 个 MCN breaker:
    mcn_mysql          (drama_lookup + url_realtime 共享)
    mcn_url_realtime   (wait_collect 实时查)
    sig3_primary       (:50002 主端点)
    sig3_fallback      (:50003 备端点)

任一 OPEN → MCN mode = B (degraded)
    planner 降额 budget × 0.3
    burst 跳过
    依赖本地镜像
全 CLOSED → MCN mode = A (healthy)
```

## A.4 核心功能详表 (按重要性)

### 🔥 功能 1: 爆款雷达 (v6 Day 8 新做)

**干什么**: 每 2 小时从作者池扫最新作品, 发现全网爆款潜力股

**采集过程**:
```
1. 选 30 个高权重作者 (scrape_priority 1-3)
2. 对每作者调 www.kuaishou.com/rest/v/profile/feed
   带 KWW 签名 header (AES-CBC 加密的指纹)
   带用户 cookie (从 cookie 池选一个)
3. 响应含 20 条最新作品:
   {photo_id, caption, viewCount, likeCount, 
    timestamp, duration, photoUrls (CDN 直链!)}
4. 宽容入池 hot_photos 表
5. 副产品: CDN 直链 → drama_links (解决下载荒漠)
            作者信息 → drama_authors (自增长作者池)
```

**关键指标**:
- 每 2h 扫 30 作者
- 每轮采 600 条潜在作品
- 副产品: ~200 条 CDN 入库
- Cookie 池轮换 12 账号 (单账号 5min 限频 cooldown)

**决策使用**:
- candidate_builder L0 层 (近 24h 内 hot_photos 直接进 TOP 候选)
- match_scorer 额外加分 (views_per_hour 归一)
- planner 优先排 hot 剧到 burst_pool

### 🎯 功能 2: AI 决策 (core)

**match_scorer 20+ 信号** (对每 account × drama × recipe × image_mode 打分):

```
账号维度:
  _base_weight       tier 基础分 (viral=90 ... testing=30)
  _income_bonus      账号历史收益 (log 缩放)
  _cooldown_penalty  该账号对该剧 24/72h 冷却
  _recent_fail_penalty 近 1h 失败次数

剧维度:
  _heat_bonus        近 30 天剧收益 (mcn_drama_library)
  _high_income_bonus MCN high_income_dramas 加分
  _blacklist_penalty drama_blacklist 硬/软扣
  _violation_penalty spark_violation_dramas 硬扣
  _income_desc_bonus 实际 ¥X.XX log 缩放
  _freshness_bonus   24h/48h/legacy 新鲜度
  _banner_existence  无 banner -5000 硬拒

匹配维度:
  _vertical_match    账号 vertical × 剧关键词 (甜宠/霸总/穿越)
  _diversity_bonus   近 3 天未发过该剧加分

记忆维度 (Layer 2):
  _affinity_signal   该账号对此 recipe/image_mode 历史命中率
  _avoid_penalty     该账号对此剧历史 over_optimistic/wrong 扣
  _trust_signal      AI 对该账号决策准确率校准
  _novelty_bonus     新 (recipe, image_mode) 组合加分

风控:
  _account_drama_blacklist 80004 闭环 72h 冷却
  _quarantined_penalty     URL 全死的剧扣分
  _drama_url_cooldown      watchdog 级联失败冷却

外部 (Week 3+):
  _external_burst_bonus    hot_photos burst_score
  _drama_type_match        账号 preferred_drama_types × 剧类型
```

**候选池 7 层漏斗** (candidate_builder):

```
L0 (新) hot_photos       近 24h 爆款雷达直进 TOP 候选
L1 base_pool             134k MCN 剧库
L2 url_available         有 CDN 或 MCN 池 URL
L3 not_blacklisted       排除活跃黑名单
L4 not_violation_hardlock 排除硬锁 (违规 ≥5 次)
L5 scored                6 维打分 (freshness + url + commission + heat + matrix + penalty)
L6 final                 TOP 30 (按 composite_score desc, min_score=40)
```

### 🧠 功能 3: 3 层 AI 记忆

**Layer 1 — account_decision_history** (事件级, append-only)
- 每次 planner 决策写 1 条
- 字段: hypothesis (预期收益) / expected / confidence / actual / verdict
- verdict: correct / over_optimistic / under_confident / wrong (自动判定)

**Layer 2 — account_strategy_memory** (聚合级, 每账号 1 行)
- Analyzer 每日重建
- 字段: preferred_recipes / preferred_image_modes / avoid_drama_ids
         trust_score (≥5 样本才有) / preferred_drama_types (未来)

**Layer 3 — account_diary_entries** (周记, LLM 写)
- LLMResearcher 每 12h 调 Hermes
- 内容: 4 段 (summary / review / lessons / strategy)
- 用户审批后进 match_scorer

### 🚦 功能 4: 5 档自适应运营模式

**ControllerAgent step 25 每 5 min 检测**, 按 signed 账号数自动切:

| 档位 | 账号范围 | Worker | Burst | Explore | 描述 |
|---|---|---|---|---|---|
| startup | 0-10 | 2 | ❌ | 20% | 少量尝试, 人工观察 |
| growth | 10-50 | 4 | ❌ | 15% | AI 起势, 规则优化 |
| volume | 50-100 | 8 | 100k+ | 10% | 规模化, burst 保守 |
| matrix | 100-300 | 12 | 50k+ | 8% | 矩阵化 |
| scale | 300+ | 16 | 30k+ | 5% | 集群化, 准备 PG |

**切换时**自动写 operation.current.* 9 个 config, 下一 cycle 各 agent 读新值自动生效, 无重启.

### 💰 功能 5: 三池预算 (Executor)

**按 operation_mode 分 burst / steady / maintenance worker**:

```
startup (2 workers):
  burst=0, steady=1, maintenance=1   # burst 合并到 steady

matrix (12 workers):
  burst=3, steady=7, maintenance=2   # 独立互不抢

每个池 worker 只监听该池 task_type:
  burst      → PUBLISH_BURST (priority=99)
  steady     → PUBLISH, PUBLISH_DRAMA, PUBLISH_A
  maintenance→ COOKIE_REFRESH, MCN_TOKEN, LIBRARY_CLEAN, 
               QUOTA_BACKFILL, FREEZE_ACCOUNT, UNFREEZE_ACCOUNT
```

### 🔌 功能 6: 4 熔断器 (circuit_breaker)

统一 3 状态机, 保护 4 个 MCN-touching 关键调用:

```
CLOSED  (健康, 直通)
  ↓ fail_threshold 次失败
OPEN    (熔断, fast-fail)
  ↓ cooldown_sec 冷却后
HALF_OPEN (试探, 允许 1 probe)
  ↓ probe 成功 → CLOSED
  ↓ probe 失败 → OPEN

4 breakers:
  mcn_mysql        fail=3, cooldown=60s
  mcn_url_realtime fail=3, cooldown=30s
  sig3_primary     fail=5, cooldown=60s  (:50002)
  sig3_fallback    fail=5, cooldown=120s (:50003)

任一 OPEN → MCN mode=B → planner 自动降额
每次 transition 写 circuit_breaker_events + system_events (SSE)
```

### 🏷 功能 7: 账号生命周期

```
new       新加, 无数据 (直接 testing)
testing   验证期, 单日最多 1-2 条
warming_up 3 次成功 AND 成功率 ≥ 50%
established ≥ 10 次成功 AND ≥ ¥3 累计
viral     日均 ≥ ¥5
frozen    (任一触发): 违规 / 80004×3 / session error×3
           → 48h 后自动 unfreeze → 回 testing
```

### 📋 功能 8: 任务生命周期

```
daily_plan_items.status:
  pending     Plan 里待排
  queued      已入 task_queue
  running     worker 在跑
  success     发布成功
  failed      失败 (可重试)
  dead_letter 重试耗尽
  canceled    被 watchdog/scheduler 取消
  blacklisted 被 blacklist 拦

task_queue.status:
  queued      等待领取
  running     worker 持锁中
  success     ok
  failed      失败待重试 (next_retry_at)
  dead_letter ≥ 3 次失败
```

### 🎨 功能 9: 去重 + 水印系统

**11 种 recipe**:
```
mvp_trim_wipe_metadata  最简 (-c copy 抹 metadata)
light_noise_recode      轻噪点重编码
zhizun_overlay          zhizun 简单叠加
zhizun_mode5_pipeline   zhizun 4 步流水线 (⭐ 默认)
kirin_mode6             KS184 Mode6 麒麟 (⭐ 100% 对齐)
wuxianliandui           无限连队
yemao                   夜猫 3x4 马赛克
bushen                  不闪 (cfg64.exe)
touming_9gong           透明 9 宫格
rongyao                 荣耀 (unsharp + 慢 + 高 crf)
scale34                 3:4 前置 (716×954 + 模糊背景 + sin 动态水印)
```

**6 种 image_mode (干扰素材)**:
```
qitian_art        PIL 抽象艺术
gradient_random   纯渐变极简
random_shapes     4×6 grid 几何
mosaic_rotate     视频 9 帧旋转拼
frame_transform   抽 1 帧 blur/saturate
random_chars      字符阵列
```

**水印样式 5 种**:
```
stroke / shadow / glow / bold / random
```

**组合总数**: 11 recipe × 6 image_mode × 5 样式 × 3 字体 = **990 种可选**

### 🔒 功能 10: 风控 + 黑名单体系

```
drama_blacklist          MCN 机构级黑名单 (镜像 spark_violation)
                         active: -9999 硬拒 / flagged: -200 软扣

account_drama_blacklist  80004 闭环 (v6 Day 7)
                         (account×drama) 72h 冷却
                         阻止浪费 ffmpeg pipeline

account_tier=frozen      账号级冻结 48h
                         触发: violation burst / 80004×3 / session error×3

drama_url_cooldown       级联失败冷却 (watchdog 检测)
                         drama 近 2h 全下载失败 → 标 drama_links.cooldown_until
                         planner -500 扣
```

## A.5 完整数据表清单 (80+ 表)

### 核心业务表
```
device_accounts               13 账号, 含 tier, cookies, numeric_uid
drama_banner_tasks            134k MCN 剧库镜像 (biz_id + commission)
drama_links                   多源 URL 池 (CDN + 短链)
task_queue                    任务队列 (所有发布任务)
daily_plan_items              每日计划 (planner 产出)
daily_plans                   plan 元数据
publish_results               发布流水 (photo_id 追溯)
publish_daily_metrics         每日聚合
publish_outcome               ⭐ Day 8 新 — 决策-结果绑定 (学习根基)
account_locks                 账号互斥锁 (PRIMARY KEY)
```

### 爆款雷达表 (v6 Day 8)
```
hot_photos                    爆款候选库
  photo_id, author_id, caption, drama_name
  view_count, like_count, vph, like_ratio
  cdn_url (副产品)
  first_seen_at / last_seen_at (时间序列)
  follow_opportunity (综合分, 初期为空)
  status: pending/followed/stale/red_ocean

drama_authors                 作者池 (283 起, 自增长)
  kuaishou_uid, nickname, scrape_priority (1-5)
  burst_count_30d, last_burst_found_at
  consecutive_failures (淘汰机制)
```

### AI 决策表
```
account_decision_history      Layer 1 (每决策)
account_strategy_memory       Layer 2 (每账号)
account_diary_entries         Layer 3 (LLM 周记)
match_scorer_snapshots        评分快照 (debug)
strategy_rewards              Bandit Thompson Sampling
strategy_experiments          A/B/C 组
experiment_assignments        实验分配

daily_candidate_pool          candidate_builder TOP 30
research_notes                LLM 研究建议 (approved 状态)
rule_proposals                LLM 提新规则
upgrade_proposals             LLM 审计低效规则
```

### 系统运行表
```
autopilot_cycles              每 cycle 1 行
agent_run_state               每 agent 最近运行
system_events                 事件流 (SSE 推送)

healing_playbook              12 自愈规则
healing_diagnoses             诊断流水
healing_actions               执行动作

circuit_breaker_events        熔断 transition 历史
operation_mode_history        运营模式切换历史
account_tier_transitions      账号升降历史
account_drama_blacklist       80004 闭环
```

### 配置
```
app_config                    300+ 条配置 (key-value)
app_config_meta               配置元数据 (type/default/comment)
```

## A.6 技术栈 (现有)

```
客户端:
  Python 3.12
  Streamlit (现有 UI, 本次要重做)
  FastAPI + React (老的 Dashboard, 可能并入)
  SQLite + WAL (本地数据)

外部依赖:
  MCN MySQL (im.zhongxiangbao.com:3306, 活, 必需)
  MCN 代签 :50002 sig3 (活, 必需)
  MCN 代签 :50003 sig4 (活, 采集用)
  快手 API (cp/profile/feed/graphql)
  Hermes LLM Gateway (localhost:8642, 策略研究)

关键库:
  pymysql, sqlite3
  requests (http)
  ffmpeg (去重)
  frida (反编译研究)
  PyCryptodome (AES)
```

## A.7 规划 (重要!)

本产品**正在从"自用工具" → "商业软件"转型**.

**现在 (Phase 1)**: 自用期, 创始人自己运营
**3-6 月后 (Phase 2)**: 自己的服务端搭建, 业务秘密上云
**6-8 月 (Phase 3)**: PyQt 重做 UI, 做成真 Windows 软件
**8-10 月 (Phase 4)**: 加固 (Nuitka + Rust + VMProtect + Themida) + 发售
**10 月+ (Phase 5)**: 运营期 (每 2 周迭代)

**付费模型** (对外版):
```
基础版: ¥1500 永久买断 (10 账号)
专业版: ¥399/月 (50 账号 + 云爆款雷达)
企业版: ¥1299/月 (500 账号 + 优先客服 + API)
```

**护城河**:
1. 云爆款雷达 (停订看不到新爆款)
2. 公共作者池 (用户越多越值钱)
3. 协议跟进 (快手反爬升级 48h 跟上)
4. AI 权重训练 (所有用户数据优化 signal_calibrator)

---

# B 部分: UI 设计任务

## B.1 你的任务

基于 A 部分的**完整系统认知**, 设计**全套用户界面**:
- 目标: 从"Streamlit 技术感"升级到"桌面商业软件"
- 对标: KS184 的 PyQt 外观 + 更现代化
- 用户: 不懂技术的短剧运营者

## B.2 必须做的页面 (按优先级)

### 🏠 Tier 1 (日常 90% 时间看)

#### P1. **仪表盘首页** (启动默认页)

**用户心智**: 看一眼就知道 "系统在不在跑 / 今天赚了多少 / 有没出问题"

```
顶部状态条 (fixed):
  [🟢 运行中] | 模式: 🎯 startup (9 账号) | MCN: ✅ A | 云雷达: 已启用
  [⏸ 暂停] [🔄 立即检查]

左 1/3 — 操作区 (4 个大按钮):
  [▶ 立即发布]           主色按钮, 发一轮
  [👥 管理账号]           次色
  [🔥 爆款雷达]           次色
  [📊 收益分析]           次色

中 1/3 — 账号健康 (13 张卡片式):
  每张卡:
    [头像] 昵称
    等级徽章 (🌱 新 / 🌿 测试 / 🌳 成熟 / ⭐ 爆款 / ❄ 冻结)
    今日: 3/5 条 | ¥1.2
    cookie: 🟢 2h 前
    [详情 →]

右 1/3 — 今日进度:
  环形图: 今日 67% 完成 (8/12)
  柱图: 近 7 天收益趋势
  列表: 正在运行 (task_id + 剧名 + 进度)
  最新爆款: 3 张缩略 (封面 + 剧名 + vph)

底部 AI 洞察 (LLM Research 摘要):
  💡 "本周成功率最高的 recipe 是 zhizun_mode5, 建议加权重"
  💡 "账号 12 连续 3 天下降, 可能需要休息"
  [查看完整周记 →]
```

**关键实现要点**:
- 数据源: autopilot_cycles + device_accounts + publish_daily_metrics + hot_photos
- 刷新: 手动 (默认), 可选 30s 自动 (本地 DB 不是实时流)
- 空状态: 0 账号/0 发布/0 收益 都有友好提示 + 引导下一步

#### P2. **账号管理**

**用户心智**: "加新账号 / 看哪个账号有问题 / 批量操作"

```
顶部操作栏:
  [+ 扫码加号]  (主按钮, 橙色)
  [+ Cookie 粘贴]
  [📤 批量导入 CSV]
  
  筛选: [全部 13] [🟢 正常 9] [🟡 警告 2] [🔴 冻结 2]
  搜索: [昵称/UID 模糊...]

列表 (卡片式):
  每张卡:
    [头像] 昵称
    tier 徽章 + 成长进度条 (testing → warming_up 还差 2 次成功)
    今日发布: 3/5 条 (环形小图)
    本月收益: ¥45.60 (对比上月 +12%)
    cookie: 🟢 2h 前 刷新
    MCN 签约: ✅ 已签 | 或 🟡 未邀请 [发邀请]
    
    [▶ 立即发布] [⏸ 暂停] [⚙️ 详情] [🗑]

底部 (勾选后吸附):
  "已选 3 个账号" 
  [批量暂停] [批量切档] [批量刷 Cookie] [取消选择]

加号弹窗:
  Tab 1: 扫码 (生成二维码, WebSocket 轮询状态)
  Tab 2: Cookie (大文本框粘贴, 自动识别 7 域)
```

#### P3. **爆款雷达** ⭐ (核心卖点)

**用户心智**: "今天有什么剧在爆, 哪个值得我跟"

```
顶部过滤:
  🏷 类型: [全部 ▾]
  ⏰ 新鲜度: [<24h] [24-48h] [7d]
  📊 排序: [opportunity ↓] [vph ↓] [low competition ↑]
  [🔄 立即扫描]  (手动触发 hot_hunter)

主体双栏:

左 50% — 爆款卡片流 (滚动):
  TOP 30 hot_photos:
  每张卡:
    [封面 120×67]
    #剧名 (可点进详情)
    作者: 六翼短剧场 (可点进作者画像)
    
    核心数据:
      👁 50万/h  (超速图标)
      👍 3.2% 互动率 (健康)
      🕐 6h 前发布
      🎯 竞争度: 5 人跟 (蓝海)
    
    AI 判断:
      🟢 跟发机会 ROI: ¥12.5/条
      或 🟡 起势期, 可跟
      或 🔴 红海, 建议跳过
    
    操作:
      [▶ 全矩阵跟发] 或 [💎 高 tier 跟] 或 [🙈 跳过]

右 50% — 选中剧详情:
  [封面大图]
  完整剧名 + 作者
  
  数据曲线 (近 48h 播放量增长):
    线图: 12h 前 5w → 现在 50w  (加速度可视化)
  
  同剧全网视频数 (竞争度):
    "这剧已有 5 位作者/搬运者跟过"
    缩略图列表 (点击跳到对方主页)
  
  历史跟发效果 (如果我们跟过):
    "我们矩阵 3 账号发过, avg ROI: ¥8.5"
  
  相关剧 (同作者其他剧):
    缩略图 4 张
  
  LLM 洞察 (如果已生成):
    "这类剧在 tier=warming_up 账号 78% 转化率"
  
  [▶ 加入今日计划]  (主按钮)
```

#### P4. **收益分析**

**用户心智**: "这月挣多少? 哪个账号最能赚? 跟哪个策略最赚?"

```
顶部 4 KPI 卡:
  今日  | 本周 | 本月 | 累计
  ¥23.7 | ¥165 | ¥412 | ¥3,200
  对比昨日 +15% | +8% | +23% | —

中间双栏:

左 60% — 收益趋势:
  折线图: 近 30 天 (可切换日/周/月)
  同时叠加: 发布条数柱图 (次轴)
  过滤: [全部账号] [Top 5] [指定某账号]

右 40% — 构成分析:
  饼图: 账号贡献
  饼图: 剧贡献 (Top 10 + 其他)
  列表: 哪个 recipe 最赚 (按 avg ROI)

底部:
  MCN 实时同步状态
  "数据来源: MCN fluorescent_members (✅ 最新 10min 前)"
  [🔄 立即同步]
```

### 🎯 Tier 2 (中频, 建议每周看几次)

#### P5. **AI 建议审批**

**用户心智**: "AI 觉得该改啥, 我批不批"

```
顶部 Tab:
  [💡 新建议 (3)] [📔 AI 周记] [🔧 规则升级]

新建议列表:
  每张卡:
    [🔵 待审] #042  (置信度 85% · 数据样本 127 条)
    
    标题: "建议降低 touming_9gong 权重 -30%"
    
    依据:
      "近 30 天该 recipe 成功率从 65% 降到 42%,
       可能因账号风控升级. 其他 recipe 表现更好."
    
    影响预览:
      "采纳后: 下次 planner 不再优先选此 recipe"
      "预期: 每日 ROI +8%"
    
    [✅ 采纳 (立即生效)] [❌ 驳回] [💬 我有话说]

AI 周记 tab:
  时间线 (按周):
    本周总结:
      成功: 8 爆款命中 (+3 vs 上周)
      失败: 2 账号触发 80004
      教训: 甜宠类剧在 warming_up 账号转化 +23%
      下周策略: 加权 tier=warming_up 抢早期甜宠爆款
      
    [查看上周 →] [历史存档 →]
```

#### P6. **账号画像 (点账号卡进入)**

**用户心智**: "看 AI 怎么认识我这账号"

```
顶部账号信息条:
  [头像] 诗草莓酱 (uid 887xxx) [⭐ warming_up]
  📊 今日发 3 条 · 本月 ¥45 · 累计 ¥328
  [🔄 刷新 Cookie] [❄ 冻结] [🗑 删除]

4 Tab:

Tab 1 概况:
  近 7 天发布时间轴 (每条 mini 卡片)
  错误模式分析 (如果有)
  健康指标 (cookie 活跃度 / 发布成功率 / 等)

Tab 2 🧠 AI 记忆 (Layer 2):
  trust_score: 仪表盘 0.82
  preferred_recipes: 6 横向柱图 (kirin_mode6 最偏好)
  preferred_image_modes: 6 横向
  avoid_drama_ids: 列表 (历史 over_optimistic 的)
  novelty: 未试过的组合列表

Tab 3 📝 决策历史 (Layer 1):
  时间线表格:
    日期 | 剧 | recipe | 预期 | 实际 | verdict
    2026-04-20 | A | kirin_mode6 | ¥5 | ¥4.5 | ✅ correct
    2026-04-19 | B | zhizun | ¥8 | ¥0.3 | ❌ over_optimistic

Tab 4 📔 AI 周记 (Layer 3):
  本周 LLM 写的 4 段:
    summary / review / lessons / strategy
  [💬 手工添加笔记]
```

#### P7. **任务队列 / 运行中**

**用户心智**: "现在在跑啥, 进度多少"

```
Tab 栏:
  [🎬 发布任务] [⚙️ 维护任务] [📊 全部]

每 tab 顶部 4 KPI:
  总 | ✅ 成功 | ❌ 失败 | ⏳ 进行中

运行中任务 (优先显示):
  每张卡:
    task_id + drama_name + account_name
    recipe + image_mode
    进度: Stage 2 去重中 (已 45%) 
    [👁 查看日志] [🗑 取消]

已完成 (表格):
  时间 | 账号 | 剧 | 状态 | 收益 | recipe
```

### ⚙️ Tier 3 (低频, 偶尔查)

#### P8. **运营模式**

**用户心智**: "系统现在在哪个档位, 是不是合理"

```
顶部大卡:
  当前档位: 🎯 startup (9 活跃账号)
  
  阶梯可视化:
    startup → growth → volume → matrix → scale
    [●        ][         ][         ][         ][         ]
    (当前位置)
  
  下一档位触发: 再加 2 账号达到 growth (预期月收益翻倍)

中间:
  当前策略参数:
    Worker 分配:
      [burst 0] [steady 1] [maintenance 1]  (堆叠条)
    每账号每日: 1 条
    爆款跟发: ❌ 关闭 (账号太少)
    AI 探索率: 20%
    实验组: A/B/C 每组 3 账号
  
  对比其他档位 (表格):
    |       | startup | growth | volume | matrix | scale |
    | 账号  | 0-10    | 10-50  | 50-100 | 100-300 | 300+  |
    | ...   | ...     | ...    | ...    | ...     | ...   |

高级 (折叠):
  [🔧 手动 force mode] (警告: 不推荐)
  [📜 近 20 条切换历史]
```

#### P9. **熔断 + 系统健康**

**用户心智**: "MCN 通不通, 有没有卡住"

```
顶部大指示:
  MCN 模式: 🟢 A (全健康)
  autopilot: 🟢 运行中 (上 cycle 35s 前)
  数据库: 🟢 45MB (正常)

4 个熔断器 (横向 4 卡):
  🟢 mcn_mysql      CLOSED   fail=3 cd=60s
  🟢 mcn_url_realtime CLOSED fail=3 cd=30s  
  🟢 sig3_primary   CLOSED   fail=5 cd=60s
  🟢 sig3_fallback  CLOSED   fail=5 cd=120s
  
  任一 🔴 OPEN 时显示冷却倒计时 + [手动 reset]

底部:
  近 50 transitions (技术用户折叠, 默认隐藏)
  
🚫 Account × Drama Blacklist (80004 闭环):
  KPI: Total 5 | Active 3 | Expired 2
  列表 (可解封)
```

### 💰 Tier 4 (商业化, 首次/续费看)

#### P10. **订阅中心**

```
顶部当前套餐大卡:
  🏆 专业版
  到期: 2026-06-24 (还有 61 天)
  使用: 38/50 账号
  云爆款雷达: ✅ 已启用
  [💳 续费] [⬆️ 升级] [📋 订单历史]

3 档对比 (横向):
  ┌ 基础 ─────────┐ ┌ 专业 ⭐ (当前)┐ ┌ 企业 ─────────┐
  │ ¥1,500 永久   │ │ ¥399/月       │ │ ¥1,299/月    │
  │ 10 账号单机   │ │ 50 账号 + 云  │ │ 500 账号     │
  │ [购买]        │ │ [✓ 当前]     │ │ [升级]       │
  └───────────────┘ └───────────────┘ └───────────────┘

底部价值说明 (激发续费):
  💎 您的专业版价值:
  - 过去 30 天, 云爆款雷达发现 42 个潜力剧
  - AI 建议 15 次权重优化, 成功率 +23%
  - 协议跟进: 快手 3 次反爬, 我们 48h 跟上
  [🎁 邀请好友 (赠 7 天免费)]
```

#### P11. **激活 / 首启向导** (未激活时显示)

```
居中大卡:
  🎬 欢迎使用 KS 短剧矩阵
  
  [________-________-________-________] 输入激活码
  
  或: [💰 立即购买] | [🆓 免费试用 7 天]
  
  您的设备: Windows 10 / 指纹 fp_a1b2c3... [复制]
  
  已有账号? [登录恢复数据]
```

### 🛠 Tier 5 (高级, 技术用户)

#### P12. **高级设置** (默认隐藏)

```
Tab:
  [⚙️ 基础] [🎛 AI 参数] [🧪 实验室] [📊 导出]

基础 (非技术):
  - 自启动开机
  - 托盘图标
  - 通知中心
  - 日志级别 (精简/详细/调试)

AI 参数 (300+ config 分组):
  - 决策: 权重 / 阈值 / LLM 介入率
  - 发布: recipe 偏好 / 时机 / 重试
  - 采集: hunter 间隔 / 深度

实验室:
  - A/B 测试组管理
  - 11 recipe × 6 image 预览
  - 去重组合生成器
```

#### P13. **数据导出** (企业版)

```
5 种报表:
  1. 账号日报 (每日发布 + 收益)
  2. 剧效果报告 (哪剧最赚)
  3. Recipe 对比
  4. LLM 建议采纳统计
  5. 全量数据 (JSON)

导出格式: CSV / Excel / JSON
时间范围: [日期选择]
```

## B.3 交互关键细节

### 启动体验
```
冷启动 2-3 秒 (Python + 依赖):
  显示 splash screen: LOGO + "正在启动..."
  后台: autopilot 初始化 / DB 迁移 / cookie 池载入

加载完成:
  淡入首页
  托盘图标变绿
  右下角 toast: "✅ 已启动, 3 账号在发布中"
```

### 状态同步机制
```
Streamlit 现状: meta refresh 整页刷 → 频繁打断
新版: 
  - 关键数据 (今日发布数 / 收益) 每 30s 轻量拉
  - 用户正在输入表单时绝不刷新
  - WebSocket 推送 autopilot_cycles (可选)
  - 或 SSE (server-sent events) 推新事件
```

### 通知中心
```
右上角🔔 (有未读红点):
  - 新发布成功 (聚合, 5 分钟合并 1 条)
  - AI 新建议 (待审)
  - 账号冻结
  - 系统故障
  - 订阅到期提醒

不弹系统通知 (太烦), 都在软件内.
```

### 错误信息人性化
```
Before: "sqlite3.OperationalError: no such column"
After:  "数据库格式较旧, 正在自动升级 (30s) — [查看详情]"

Before: "HTTP 403 Forbidden"
After:  "快手拒绝访问, 可能 Cookie 过期 — [重新登录]"

Before: "Signature validation failed"
After:  "签名服务暂时不可用, 30s 后自动重试..."
```

## B.4 颜色规范

```
主品牌色: #FF6B35 (短剧橙, 热情)
辅色:     #4A90E2 (信任蓝)
深色背景: #1A1A1A (主背景)
次深:    #2A2A2A (卡片)
强调深: #0F0F0F (输入框)

状态色:
  🟢 #4CAF50  健康/成功
  🟡 #FFC107  警告
  🔴 #F44336  错误/冻结
  🔵 #2196F3  信息
  🟣 #9C27B0  VIP/企业版
  🟠 #FF9800  重要操作

文字:
  主文字:  #FFFFFF / #E0E0E0
  次文字:  #AAAAAA
  禁用:    #666666

边框/分割:
  #333333 (浅)
  #444444 (重)
```

## B.5 付费差异化 UI

### 免费/试用 (顶部黄横条)
```
"🔔 试用还剩 6 天 (1/7 天) — [💰 立即购买]"

功能限制:
  - 云爆款雷达 🔒 (悬停 "专业版解锁")
  - 作者池共享 🔒
  - AI 建议 🔒
  - > 10 账号 🔒
  - 导出 🔒 (企业版)

升级提示 (无感植入):
  侧栏底部: "⚡ 首月 ¥99 体验专业版"
  收益页: "💰 专业版预计再提升 ¥X/月"
  爆款雷达: 50% 蒙层 + "解锁完整榜单"
```

### 基础版 (绿横条)
```
"✅ 基础版 永久 | 10 账号 (7/10)"

隐藏云服务按钮
追加销售:
  "🎁 升级专业版首月 ¥99, 不满意退款"
```

### 专业版 (紫横条)
```
"🏆 专业版 | 到期 2026-06-24 (61 天) | [续费]"
全功能开放
"🎁 邀请好友 (赠 7 天)"
```

### 企业版 (金横条)
```
"👑 企业版 | 500 账号 | [💬 专属客服]"
API 密钥管理入口
```

## B.6 技术栈建议

**推荐**: **PyQt6** (对标 KS184 + 真原生)

```
结构:
  main.py                      主入口
  ui/
    main_window.py             主窗口 (QMainWindow)
    pages/
      dashboard_page.py        首页
      accounts_page.py         账号
      burst_radar_page.py      爆款雷达
      revenue_page.py          收益
      ai_advice_page.py        AI 建议
      account_profile_page.py  账号画像
      tasks_page.py            任务
      operation_mode_page.py   运营模式
      circuit_health_page.py   熔断
      subscription_page.py     订阅
      activate_page.py         激活
      advanced_page.py         高级设置
    widgets/
      account_card.py          账号卡
      hot_photo_card.py        爆款卡
      stat_kpi_card.py         KPI 卡
      progress_ring.py         环形进度
      chart_line.py            折线图 (QtCharts)
    dialogs/
      add_account_dialog.py    加账号
      activate_dialog.py       激活
      ai_advice_dialog.py      LLM 建议
    styles/
      dark.qss                 QSS 样式
  
  backend/  (Python 核心保留)
    (现有代码几乎不改)
```

**备选**: Electron + React (如果想要跨平台 + 现代)

## B.7 输出要求

请按以下交付物顺序输出:

1. **整体窗口架构** 图示 + 描述
2. **顶 6 页** (P1-P6) 详细 UI 设计 (每页: 布局 ASCII 图 + 组件清单 + 关键交互 + 数据来源)
3. **3 个商业化页面** (P10-P11) 设计 + 付费差异化 UI 对比
4. **色彩规范** + **组件库清单**
5. **交互细节**: 启动/刷新/通知/错误提示
6. **代码示例**: PyQt6 选 2 个代表性页面 (建议: 仪表盘 + 爆款雷达)

## B.8 设计原则总结

```
✅ 基于 A 部分真实系统功能设计 (不要凭空想象新功能)
✅ 新手 2 分钟上手 (首页 4 按钮 + 大字体)
✅ 重度用户 10h/天不累眼 (深色专业风)
✅ 付费引导自然 (价值展示 > 骚扰)
✅ 每个细节有商业化意识 (从免费到企业的渐进升级)

❌ 不要 Material Design 纯 web 风
❌ 不要花哨动效 (桌面软件稳重)
❌ 不要暴露代码/日志/技术细节在主界面
❌ 不要让用户选算法/改复杂 config (AI 自动)
```

---

请基于以上全部信息, 开始设计.
```

---

# 📌 这份提示词和上一版的区别

## v1 (UI重设计AI提示词.md) — 简洁版 (~18KB)

```
侧重: UI 风格 + 付费差异 + 页面列表
适合: 快速出视觉稿 (v0.dev / Figma AI)
缺点: AI 不懂系统运行逻辑, 容易出"看着好看但不实用"的设计
```

## v2 (UI重设计AI提示词_完整版.md) — 完整版 (本文件, ~35KB)

```
侧重: 
  A 部分: 系统全景百科 (让 AI 懂业务)
  B 部分: UI 设计任务 (基于真理解设计)

适合: 
  - Cursor / Windsurf / Claude Code 改代码 (AI 要懂才敢动)
  - 出高质量可落地方案 (不是空中楼阁)
  - 给团队新人入门读 (也是个系统文档)

优点:
  ✅ AI 不需要反复追问 "这个 step 是啥意思"
  ✅ AI 能判断 "这功能在哪页合适"
  ✅ AI 能预测 "用户为啥需要这按钮"
```

## 使用方式

```bash
# 方式 1: 一口气给 Cursor
打开 Cursor → 新对话 → 复制 "提示词正文" 整段 (A+B)
→ 加一句: "基于 dashboard/streamlit_app.py, 输出 PyQt6 版本"
→ AI 开始生成

# 方式 2: 分阶段给 Claude
第 1 轮: 只给 A 部分, 问 "理解了吗, 请复述系统"
第 2 轮: 给 B 部分, 让出设计
第 3 轮: 让它出 P1 首页代码
第 4 轮: P2 P3 ...

# 方式 3: 给 v0.dev
缩简 A 部分 (保留 A.2 + A.4 + A.7), 完整给 B
"出 React + TypeScript + Tailwind 版"
```

## 关键差异提示词

```
给 AI 的时候, 多一句可以极大提升质量:

"设计时必须满足:
  1. 我有 18 页 Streamlit 代码, 每个功能都能在现有 DB 里找到数据源
  2. 你的 UI 必须映射到真实代码, 不要假设不存在的功能
  3. 不确定时, 按 A.4 的功能表优先级取舍
  4. 告诉我每个 UI 组件的数据是从哪张表/哪个 API 来"
```

---

**版本**: v2.0 (2026-04-24) — 完整系统百科 + UI 设计任务
**文件大小**: ~35 KB
**章节**: 11 章 (A: 7 + B: 8)
