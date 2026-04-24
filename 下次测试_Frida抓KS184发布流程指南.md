# 下次测试 — Frida 抓 KS184 真实发布流程指南

> **目标**: 找出 publisher.py 发的视频为什么不进快手, 对比 KS184 payload 差异, 修完后实现自动化发布.
> **时长**: 约 10 分钟 (含用户操作)
> **工具准备状态**: ✅ 都已就位

---

## 一、一张图看清流程

```
┌──────────────────────────────────────────────────────────────────┐
│  用户操作                           │ 我(后台跑)的工具            │
├─────────────────────────────────────┼────────────────────────────┤
│ 1. 先不要开 KS184                    │                            │
│                                      │ A 终端: python -m          │
│                                      │   tools.watch_and_attach   │
│                                      │   (等新 Q_x64 出现自动挂) │
│                                      │                            │
│                                      │ B 终端: python -m          │
│                                      │   tools.capture_publish_   │
│                                      │   session                  │
│                                      │                            │
│ 2. 打开 KS184, 登 13337289759       │                            │
│    进入百洁短剧工厂账号                │                            │
│                                      │ (A 会自动 attach 新 pid)   │
│                                      │                            │
│ 3. 点"发视频", 选一个视频素材         │                            │
│    选一部剧, 填标题, 提交              │                            │
│                                      │ (B 实时打印每步 HTTP)      │
│                                      │                            │
│ 4. 等 KS184 提示"发布成功"            │                            │
│                                      │ B 自动检测 /submit 响应 → │
│                                      │ 导出 session + 对比报告   │
│                                      │                            │
│ 5. 去快手 App 刷新百洁账号主页        │                            │
│    应该看到刚发的视频                   │                            │
│                                      │ 我看 diff 报告, 改 publisher.py │
│                                      │                            │
│ 6. 跑 publisher.py 再发一条 (修好后)  │                            │
│    等快手审核通过                      │                            │
│                                      │ 次日查 fluorescent_members │
│                                      │ 看收益是否增加              │
└──────────────────────────────────────┴────────────────────────────┘
```

---

## 二、我开机后要做的 3 条命令 (准备期)

### 命令 1 — A 终端: 启动自动挂钩器
```powershell
cd D:\ks_automation
python -m tools.watch_and_attach
```
出现 `[baseline] 当前已在运行的 Q_x64 pids: (无)` 就对了.

### 命令 2 — B 终端: 启动发布会话分析器
```powershell
cd D:\ks_automation
python -m tools.capture_publish_session
```
出现 `[!] 找不到 trace dir` 是正常的 (KS184 还没启动). 脚本会自动等.

→ 或者 —— 如果你不想我在 watch_and_attach, 直接:
```powershell
python -m tools.trace_ks184_live
```
这个是"KS184 已经开机状态" 下的手动 attach.

### 命令 3 — 一切准备好后告诉我
你说 "好了, 我要开 KS184 了", 我回复 "等你发".

---

## 三、你要做的 4 步 (操作期)

1. **打开 KS184** (桌面快捷方式 `kuaishou_multi_control_ZUFN.exe`)
2. **进百洁短剧工厂账号** (账号 3)
3. **点"发视频"按钮**:
   - 选一个视频素材 (最好是刚下载的新视频, 不要用过去发过的)
   - 选一部剧: **优先选有分佣历史的** (比如少年叶飞鸿 `162859` 或 陆总今天要离婚 `250979`, 今天我更新了本地库有 1559 个真赚钱剧)
   - 填标题 (短的, 带 2-3 个 emoji)
   - 点提交, 等 KS184 提示"发布成功"
4. **到快手 App 确认视频出现在百洁账号主页**

这 4 步做完后, 你告诉我 "发了", 我看 diff 报告.

---

## 四、我看到 B 终端会有的东西 (监控期)

```
[12:34:56] 🎬 新发布会话启动 (首条: banner /rest/cp/works/v2/banner/list)
  [12:34:56] 🎯 banner    requests.Session   /rest/cp/works/v2/banner/list
  [12:34:58] 📋 pre       requests.Session   /rest/cp/works/v2/upload/apply
  [12:34:59] 📦 fragment  requests.Session   /upload/fragment?fragmentId=0
  [12:35:01] 📦 fragment  requests.Session   /upload/fragment?fragmentId=1
  [12:35:05] ✅ finish    requests.Session   /rest/cp/works/v2/upload/finish
  [12:35:07] 🖼️ cover     requests.Session   /rest/cp/works/v2/upload/cover
  [12:35:09] 🚀 submit    requests.Session   /rest/cp/works/v2/submit
[12:35:09] 🏁 submit 响应收到, dump session

✨ session 保存: D:\ks_automation\tools\trace_publish\publish_session_20260419_123509
  打开 summary.md 查看对比报告
```

这时候自动产物:
- `tools/trace_publish/publish_session_<timestamp>/raw_events.jsonl`
- `tools/trace_publish/publish_session_<timestamp>/step_*.jsonl` (pre/fragment/finish/submit 等每步分文件)
- `tools/trace_publish/publish_session_<timestamp>/summary.md` ← 人眼看的摘要
- `tools/trace_publish/publish_session_<timestamp>/diff_vs_publisher.md` ← 关键, 和 publisher.py 最新尝试对比

---

## 五、对比要看的关键字段 (分析期)

分析报告会并排展示 KS184 和 publisher.py 的:

### 5.1 请求 URL 结构

| 步骤 | KS184 实际 | publisher.py 当前 | 可能问题 |
|---|---|---|---|
| pre (申请 upload token) | `/rest/cp/works/v2/upload/apply?__NS_sig3=xxx` | 见 publisher.py | URL 参数 (sig3) 算法 |
| fragment | `/upload/fragment?fragmentId=N&fileId=xxx` | 见 publisher.py | fileId 源头 |
| finish | `/rest/cp/works/v2/upload/finish?__NS_sig3=xxx` | 见 publisher.py | 完成信号字段 |
| submit | `/rest/cp/works/v2/submit?__NS_sig3=xxx` | 见 publisher.py | 42 字段完整性 |

### 5.2 请求 body (最关键)

重点对比 **submit body** 的 42 字段:
- caption / title / description
- bannerTaskId / entranceType / bindTaskType
- photoId / fileId / mediaId
- coverKey / coverId / thumbnailKey
- chapters / chapter_count
- privacyStatus / visibility
- photoType / mediaType
- mountBindId / mount_type
- author_statement / interaction_setting
- xxx 其他隐藏字段

### 5.3 请求 headers

- `User-Agent` — 必须像浏览器
- `Referer` — 必须是 `https://cp.kuaishou.com/`
- `Origin` — 必须是 `https://cp.kuaishou.com`
- `Cookie` — 必须含 `kuaishou.web.cp.api_st`, `kuaishou.web.cp.api_ph`, `userId`, `did`, `passToken`

### 5.4 签名 `__NS_sig3` 生成算法

目前我们: `HMAC_SHA256(key=_HMAC_SECRET, msg=f"{uid}:{ts}:{nonce}:{_HMAC_SECRET}")` 再 hexdigest

抓到的 KS184 有没有:
- 不同的 key?
- 不同的 msg 格式?
- 不同的输出 (hexdigest vs base64 vs 前 N 位)?

---

## 六、修完 publisher.py 后的验证

1. 跑 `python -m scripts.test_publisher_dryrun --account 百洁短剧工厂 --drama 少年叶飞鸿` (dry run)
2. 如果 dry run OK, 真跑 `python -m scripts.run_single_publish --account 3 --drama-id 162859` (挑有钱剧)
3. 查 `publish_results` 最新一行, 要求 `photo_id` 非空
4. 去快手 App 刷百洁账号主页, 确认视频在
5. 明天跑 `python -m scripts.snapshot_mcn_members --report`, 看账号 3 `total_amount` 是否 > ¥0.07

---

## 七、如果遇到问题

### 7.1 watch_and_attach 没反应

说明 Q_x64.dll 启动了但名字不对. 手动:
```powershell
Get-Process | Where-Object { $_.ProcessName -like "*q_x64*" -or $_.ProcessName -like "*kuaishou*" } | Select-Object Id,ProcessName,Path
```
找到后复制 pid, 手动挂: `python -m tools.trace_ks184_live --pid <PID>`

### 7.2 capture_publish_session 说"找不到 trace dir"

等 `watch_and_attach` 先真的 attach 成功 (它会 print `[+] attached`). 或者手动指定:
```powershell
python -m tools.capture_publish_session --trace-dir D:\ks_automation\tools\trace_publish\ks184_live_<timestamp>
```

### 7.3 KS184 闪退 / PyArmor 抗 debug

我们踩过这个坑. 补救:
1. 关所有 KS184 进程 (Task Manager 强杀 `kuaishou_multi_control_ZUFN.exe` 和 `Q_x64.dll`)
2. 重来一次

### 7.4 发布成功但 capture_publish_session 没 dump

可能 KS184 这次发的 URL pattern 不匹配我们的 regex. 检查:
```powershell
Get-Content D:\ks_automation\tools\trace_publish\ks184_live_<timestamp>\http.jsonl | Select-String "submit|publish|photo/create"
```
把匹配的 URL 贴给我, 我加到 STEP_PATTERNS 里.

---

## 八、文件清单 (本次准备交付)

| 文件 | 作用 |
|---|---|
| `tools/trace_ks184_live.py` | 已有 — 原始 HTTP/hash/hmac/url/urllib3/socket 全栈 hook |
| `tools/watch_and_attach.py` | 已有 — 轮询新 Q_x64, 自动挂钩 |
| `tools/capture_publish_session.py` | **新** — 实时归类 + 发布完成自动出报告 |
| `下次测试_Frida抓KS184发布流程指南.md` | **新** — 本指南 |
| `账号分佣归零问题分析与下次测试方案.md` | 已更新 — 分佣机制真相 + 测试步骤 |
| `scripts/snapshot_mcn_members.py` | 已有 — 每日监控 (已接 ControllerAgent) |
