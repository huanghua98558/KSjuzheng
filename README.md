# KS 短剧矩阵运营系统

> Kuaishou Short Drama Matrix Operation System
> 快手短剧 CPS 矩阵运营自动化后端

## 项目简介

本项目是快手短剧矩阵运营的完整后端系统, 包括:

- **AI 自动决策** — 候选池 + match_scorer (20+ 信号) + 3 层记忆
- **爆款雷达** — 主动扫描作者 profile/feed, 预判爆款
- **执行引擎** — 三池 worker (burst / steady / maintenance) + 账号互斥锁
- **自愈系统** — Watchdog + Playbook + LLM 规则建议
- **熔断保护** — 4 个 MCN-touching 端点熔断器
- **自适应运营模式** — 5 档 (startup → growth → volume → matrix → scale)

## 技术栈

```
Python 3.12
SQLite + WAL (本地持久化)
FastAPI + Streamlit (Dashboard)
PyMySQL (MCN 接入)
FFmpeg (视频处理)
```

## 配置

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置 secrets

```bash
# 复制模板
cp .secrets.json.example .secrets.json

# 编辑填真实值 (示例键名见模板)
```

或使用环境变量 (优先级更高):

```bash
export KS_CAPTAIN_PHONE=...
export KS_CAPTAIN_PASSWORD=...
export KS_MCN_MYSQL_PASSWORD=...
```

### 3. 数据库迁移

```bash
# 按 migrate_v1 → v44 顺序运行
python -m scripts.migrate_v40  # 例: account_locks
python -m scripts.migrate_v44  # 例: hot_photos + publish_outcome
```

### 4. 启动

```bash
# Windows
./start_ks.bat

# Linux / macOS
python -m scripts.run_all
```

## 目录结构

```
core/                  核心业务模块
  agents/              9 个后台 Agent
  executor/            三池执行器 + pipeline
  ...                  各种业务模块

scripts/               CLI 工具 + migrations
  migrate_v1 → v44     数据库迁移
  sync_*               MCN 数据同步
  ...

dashboard/             Dashboard API + Streamlit UI

docs/                  设计文档 + 规划 + UI 提示词
```

## 安全提示

**⚠️ 本仓库不含任何真实凭证**. 所有敏感值 (手机号/密码/HMAC 密钥) 都是占位符 `REPLACE_WITH_*`, 使用前必须通过 `.secrets.json` 或环境变量填入.

```
公开字段:
  ✅ 代码结构 / 业务逻辑 / DB Schema
  ✅ Agent 运行框架 / AI 决策逻辑

私有 (不在本仓库):
  ❌ 真实凭证 (用户自行配置)
  ❌ MCN 服务器地址 (部分脱敏)
  ❌ 反编译资料 (商业秘密, 已排除)
  ❌ 破解工具 (yk_codec / Frida probe, 已排除)
```

## 许可证

私有项目, 未开源. 仅限授权使用.

## 维护

作者: huanghua98558

更多文档见 `docs/` 目录.
