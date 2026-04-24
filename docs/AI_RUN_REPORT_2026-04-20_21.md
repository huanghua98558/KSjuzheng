# AI 矩阵运营系统 — 2026-04-20 ~ 2026-04-21 运行复盘

## 📊 规划 vs 实际 (两天对比)

| 指标 | 规划目标 | 实际 | 差距 | 原因 |
|---|---|---|---|---|
| 每日 plan items | 13账 × 5 = 65 | 50 items | -23% | testing tier 配额 |
| 单日发布成功率 | 60-80% | **8%** (4 成功/50 items) | -72pp | 🔴 URL 采集失败 |
| active 账号 | 13 | 9 → 1 → 9 (抖动) | — | 级联冻号 bug (已修) |
| verdict 闭环 | analyzer 次日打标 | 52 条 pending (无 verdict) | 未闭环 | Analyzer 5 pm 没到 |
| AI Hermes 调用 | Aliyun Qwen 为主 | ✅ 已就绪 | ok | |
| MCN 同步 | 每日 04:00 | ✅ 04:00 + 户内 07:44 | ok | |
| MCN 前 20 排行 | 我们上榜 | **0/20** | -100% | 发布量不足 |

## 🔴 核心问题 — URL 级联失败

### 故障链

```
drama 短链不过期 (kuaishou.com/f/XXX)  ← 99% (328/332) 是这种
       ↓
下载时 resolve 成 CDN 短 URL, TTL ~12h
       ↓
CDN 过期 → 下载失败 → task failed
       ↓
collector_on_demand 被触发重采集
       ↓
但它看 drama_links 还有 18 条 URL → skip, 不真搜     ← Bug B (已修)
       ↓
accumulate 5+ 失败 → watchdog 冻号                 ← 已修 (排除 download:*)
       ↓
该账号后续 task 全 mcn_preflight:already_frozen
       ↓
watchdog 再次阈值触发 → 继续冻号                   ← 已修 (排除 already_frozen:)
       ↓
恶性循环, 8% 成功率
```

### 48h 失败统计 (66 条)

```
download:all_urls_failed    49 (74.2%)  — URL 资源链问题
mcn_preflight:already_frozen 16 (24.2%)  — 级联效应 (已修)
process:ffmpeg_timeout        1 (1.5%)
```

## ✅ 今日修复 (2026-04-21)

| # | 修复 | 文件 | 生效方式 |
|---|---|---|---|
| 1 | migrate_v32: +drama_links.cooldown_until/reason/hit_count | `scripts/migrate_v32.py` | DB schema |
| 2 | watchdog: 排除 `download:*` + `process:*` + `mcn_preflight:already_frozen:*` 冻号 | `core/agents/watchdog_agent.py` | 重启 autopilot |
| 3 | watchdog: 新增 `_detect_drama_url_cooldown()` | 同上 | 每 cycle 扫 2h 失败 |
| 4 | match_scorer: `_drama_url_cooldown_penalty()` -500 | `core/match_scorer.py` | planner 下次 cycle |
| 5 | collector_on_demand: `_has_usable_urls` 加 cooldown + verified_at 过滤 | `core/collector_on_demand.py` | 重启生效 |
| 6 | Dashboard: MCN 绑定查询用 numeric_uid 主 key | `dashboard/api.py` | 重启生效 |
| 7 | 配置调整: freeze 阈值 5→10, url_preload 20→50 | `app_config` | 已生效 |
| 8 | 解冻 8 个级联冻结账号 → testing | DB UPDATE | 已生效 |

## 🎯 当前系统状态

```
活跃号:         9/13  (id=5,6,7,12,14,15,18,21,22 + id=3 贝洁)
   ├─ frozen:  id=9 (星罗棋布, 未登录, 需 cookie 刷新)
   └─ None 级: id=3, 13, 19 (新号未打 tier 标)

drama 冷却:    6 部 (天降心声小福星/公司天塌了/我有一只乾坤袋/团圆梦断/被裁后/这个保镖是武神)
              理由: 近 2h 内 ≥3 账号 download 失败 → 48h 冷却

autopilot:     cycle 60s 跑, live
Hermes:        aliyun Qwen 3.6 Plus priority 1 ✅

Dashboard:     http://127.0.0.1:8080/  (DISABLE_AUTOPILOT=1 防冲突)
               MCN 绑定显示已修 (思莱短剧2 现在 🟢 已绑)
```

## 📉 MCN 同行对比 (2026-04-20)

```
前 20 名号 平均: ¥15-439 / 日, tasks 2-13 条
我们 13 号 合计: ¥ 1.39  / 日, tasks 4 条

运营差距: ~10-100x
```

根本原因:
1. 其他号早上线 / 运营久, 有基础粉丝
2. 他们发布成功率 ≥60%, 我们因 URL 问题 8%
3. 我们有长期 URL 池失配 / CDN 重采集失效

## 🔜 明日早晨 08:00 planner 跑时, 期待

| 指标 | 今天 | 明天期待 |
|---|---|---|
| 活跃号 | 9 | ≥9 (watchdog 不会误冻了) |
| plan items | 50 | ≥60 (9账×6-7 item) |
| drama 冷却跳过 | 0 → 6 | ≥6 (避开死剧) |
| 成功率 | 8% | 30-50% (短链仍需 resolve 测试, 但不会再累积级联失败) |
| MCN 前 20 | 0 | 不期待, 需要几天 |

## ⚠️ 仍待解决 (明后天做)

### P0 - collector 拿不到直链 CDN
`profile/feed result=2 for uid=...` — 5 作者全返回 result=2 (auth/rate limit). 导致无法从作者页抓直链, 只能存短链. 下载时 resolve 失败率高.

**候选方案**:
- 换 browser_account_pk 轮换多个号 cookie 避免单号 rate limit
- profile/feed 加 sig3 (如果是签名问题)
- 改用 `www.kuaishou.com/graphql userProfileQuery` 接口

### P1 - analyzer 定时跑
近 7 天 52 条 decision 全 `pending` (verdict 没判), 说明 Analyzer 每日 17:00 没跑或有 bug. 查 ControllerAgent step 13.

### P2 - 账号画像喂回决策
3 个号 tier=None (id=3, 13, 19), account_tier 评估 agent 还没给它们分级.

---
生成于 2026-04-21 凌晨 / Claude 自动总结
