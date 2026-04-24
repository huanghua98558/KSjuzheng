# KS Matrix + Hermes — 一键启动手册

> 2026-04-20 重装后定稿. Hermes v0.10.0 + OpenAI Codex (GPT-5.4) + 完整 AI 矩阵.

---

## 1. 启动方式 (3 种, 任选其一)

### A. 桌面双击 (推荐)

桌面两个快捷方式:
- **KS Matrix Start** — 按序启动 Hermes → Autopilot → Dashboard + 打开浏览器 + 前台实时 tail 3 条 log
- **KS Matrix Stop** — 一键停全部

### B. 命令行

```cmd
D:\ks_automation\start_ks_all.bat     :: 启动
D:\ks_automation\stop_ks_all.bat      :: 停止
```

### C. PowerShell 直接

```powershell
powershell -File D:\ks_automation\start_ks_all.ps1
powershell -File D:\ks_automation\stop_ks_all.ps1
```

---

## 2. 启动顺序 (start_ks_all.ps1 内部)

```
[0/5] Clean old processes (hermes / autopilot / dashboard 全杀)
[1/5] Start Hermes Gateway (端口 8642, 等 /health 通, 最多 30s)
        ├─ 命令: hermes gateway run -v --replace
        ├─ log:  D:\hermes-gateway\logs\gateway.stdout.log
        └─ 验证: curl http://127.0.0.1:8642/health → {"status":"ok"}
[2/5] Start KS Autopilot (ControllerAgent 60s cycle + Phase 2 Executor)
        ├─ 命令: python -u -m scripts.run_autopilot --log-level INFO
        ├─ log:  D:\ks_automation\logs\autopilot_forever.log
        └─ ControllerAgent 17 步 cycle + 4 worker 消费 task_queue
[3/5] Start Dashboard (端口 8080, FastAPI SPA)
        ├─ 命令: python -X utf8 dashboard\app.py
        ├─ log:  D:\ks_automation\logs\dashboard.log
        └─ 访问: http://127.0.0.1:8080/
[4/5] Open browser → http://127.0.0.1:8080/
[5/5] Live tail 3 条 log (前台, Ctrl+C 退出 tail, 后台进程不停)
```

---

## 3. LLM 配置 (已定稿)

### Hermes 身份

| 路径 | 内容 |
|---|---|
| Venv | `D:\AIbot\swarmclaw-stack\.venv-hermes-win\Scripts\hermes.exe` |
| 源码 | `D:\AIbot\swarmclaw-stack\vendor\hermes-agent-main\` |
| Hermes Home | `C:\Users\Administrator\.hermes\` |
| Config | `C:\Users\Administrator\.hermes\config.yaml` |
| .env | `C:\Users\Administrator\.hermes\.env` |
| Auth | `C:\Users\Administrator\.hermes\auth.json` (含 Codex + Anthropic tokens) |
| API Server Key | `D:\AIbot\swarmclaw-stack\config\hermes\api-server.key` |

### 模型路由

| Provider 名 | 端点 | Model | 场景 | 费用 |
|---|---|---|---|---|
| **codex** | `http://127.0.0.1:8642/v1` | `gpt-5.4` | 复杂任务 (Analyzer / Researcher / 核心决策) | 免费 (ChatGPT Pro) |
| **codex-mini** | `http://127.0.0.1:8642/v1` | `gpt-5.4-mini` | 快速批量 (分类 / 简单 QA) | 免费 |
| deepseek | `api.deepseek.com/v1` | `deepseek-chat` | 云端 fallback | ¥1/M ≈ $0.14 |
| siliconflow | `api.siliconflow.cn/v1` | `deepseek-ai/DeepSeek-V3` | 云端 fallback 2 | ¥1.1/M |

Dashboard **⚙️ 配置中心 → LLM Provider** 页可直接测试 / 切 priority.

### Hermes config.yaml 关键字段

```yaml
model:
  provider: openai-codex
  base_url: https://chatgpt.com/backend-api/codex
  default: gpt-5.4           # ← 默认模型 (body.model 留空时用这个)
  max_turns: 90

api_server:
  enabled: true
  host: 127.0.0.1
  port: 8642
  model_name: hermes-agent   # ← 对外暴露的 OpenAI-compat 模型名
```

### 客户端切换 fast/complex

```python
# 复杂 (默认)
curl -H "Authorization: Bearer $KEY" -d '{"model":"hermes-agent", ...}'

# 快速 (通过 model 字段覆盖)
curl -H "Authorization: Bearer $KEY" -d '{"model":"gpt-5.4-mini", ...}'
```

---

## 4. 日志位置

| 组件 | stdout | stderr |
|---|---|---|
| Hermes Gateway | `D:\hermes-gateway\logs\gateway.stdout.log` | `gateway.stderr.log` |
| KS Autopilot | `D:\ks_automation\logs\autopilot_forever.log` | `autopilot_err.log` |
| KS Dashboard | `D:\ks_automation\logs\dashboard.log` | `dashboard_err.log` |

Live tail (start_ks_all.ps1 前台跑, 已自动彩色区分):
- 🟣 `[H]` Hermes (紫色)
- 🟢 `[A]` Autopilot (绿/红/黄)
- 🔵 `[D]` Dashboard (青色)

---

## 5. 常见问题

### Q1: Hermes gateway 起不来, `WinError 87` 参数错误

**原因**: `C:\Users\Administrator\.hermes\gateway.pid` 残留了无效 PID.
**解决**: 启动脚本已自动清理. 手动修复:

```powershell
Remove-Item C:\Users\Administrator\.hermes\gateway.pid -Force
```

### Q2: Hermes 启动即崩 `UnicodeEncodeError: gbk` codec

**原因**: Windows 中文 locale 默认 GBK, Hermes rich UI 输出 emoji 炸.
**解决**: 已用户级设 `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1`. 启动脚本开头再设一次兜底.

```powershell
[Environment]::SetEnvironmentVariable('PYTHONIOENCODING', 'utf-8', 'User')
[Environment]::SetEnvironmentVariable('PYTHONUTF8', '1', 'User')
```

### Q3: Dashboard "LLM Provider" 页 codex 显示"缺失 / 离线"

- **缺失** = `D:\AIbot\swarmclaw-stack\config\hermes\api-server.key` 文件不存在
  - 解决: 运行 `echo -n "<key>" > D:\AIbot\swarmclaw-stack\config\hermes\api-server.key`
  - 当前 KEY: `998df31859011f852026cd7ad146069ca5edccb197c17caa` (同 Hermes .env 里)
- **离线** = Hermes gateway 没跑 / 8642 端口不通
  - 解决: 运行 `start_ks_all.ps1` 或直接 `hermes gateway run --replace`

### Q4: Codex token 过期

Hermes 自带 refresh_token 自动刷新. 如手动刷:

```powershell
$env:PYTHONIOENCODING='utf-8'
D:\AIbot\swarmclaw-stack\.venv-hermes-win\Scripts\python.exe D:\ks_automation\scripts\_import_codex_to_hermes.py
```

### Q5: 我想重装 Hermes

```powershell
# 1. 停所有
powershell -File D:\ks_automation\stop_ks_all.ps1

# 2. 清 venv + egg
Remove-Item -Recurse -Force D:\AIbot\swarmclaw-stack\.venv-hermes-win
Remove-Item -Recurse -Force D:\AIbot\swarmclaw-stack\vendor\hermes-agent-main\hermes_agent.egg-info

# 3. 重装
cd D:\AIbot\swarmclaw-stack\vendor
git clone --depth 1 https://github.com/NousResearch/hermes-agent.git hermes-agent-main-new
Move-Item hermes-agent-main hermes-agent-main-old
Move-Item hermes-agent-main-new hermes-agent-main

C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe -m venv D:\AIbot\swarmclaw-stack\.venv-hermes-win
D:\AIbot\swarmclaw-stack\.venv-hermes-win\Scripts\python.exe -m pip install -e "D:\AIbot\swarmclaw-stack\vendor\hermes-agent-main[cron,cli,mcp]"

# 4. 导入 Codex auth + 启动
D:\AIbot\swarmclaw-stack\.venv-hermes-win\Scripts\python.exe D:\ks_automation\scripts\_import_codex_to_hermes.py
D:\ks_automation\start_ks_all.bat
```

---

## 6. 快速健康检查 (运行中)

```powershell
# Hermes alive
Invoke-WebRequest http://127.0.0.1:8642/health | Select-Object -ExpandProperty Content

# Hermes 真调 gpt-5.4
$k = Get-Content D:\AIbot\swarmclaw-stack\config\hermes\api-server.key -Raw
curl.exe -sS -m 60 -H "Authorization: Bearer $k" -H "Content-Type: application/json" -X POST http://127.0.0.1:8642/v1/chat/completions -d '{\"model\":\"hermes-agent\",\"messages\":[{\"role\":\"user\",\"content\":\"ping\"}]}'

# Dashboard alive
Invoke-WebRequest http://127.0.0.1:8080/ | Select-Object StatusCode

# Autopilot alive
Get-Process python | Where-Object { $_.CommandLine -match 'run_autopilot' } | Select-Object Id, StartTime

# 最近 cycle 日志
Get-Content D:\ks_automation\logs\autopilot_forever.log -Tail 50
```

---

## 7. 端口映射

| 端口 | 服务 | 备注 |
|---|---|---|
| 8080 | KS Dashboard | FastAPI + SPA, 内部管理 |
| 8501 | Streamlit Dashboard (旧版) | 已弃用, 保留 |
| 8642 | Hermes Gateway | OpenAI-compat `/v1/*` + `/health` |

---

## 8. 进程树

```
explorer.exe (桌面)
  └─ cmd.exe (start_ks_all.bat)
      └─ powershell.exe (start_ks_all.ps1 前台 tail)
          ├─ hermes.exe (gateway run, PID 存 D:\hermes-gateway\logs\gateway.pid)
          ├─ python.exe (run_autopilot, PID 存 logs\autopilot.pid)
          │    ├─ ControllerAgent 主线程 (60s cycle)
          │    ├─ Phase 2 Executor × 4 worker
          │    └─ WorkerManager legacy threads
          └─ python.exe (dashboard\app.py, PID 存 logs\dashboard.pid)
```

**关 tail 窗不关后台**: Ctrl+C 只停 `Get-Content -Wait` 循环, 后台 3 个进程不受影响.
真正要停全部 → 运行 stop_ks_all.bat.
