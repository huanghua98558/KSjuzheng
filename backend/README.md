# KSJuzheng Backend

> **定位**: KS184 业务中台 (L0-L8) + AI 自动化扩展 (L9-L13) 的后端服务
> **技术栈**: FastAPI 0.110+ / SQLAlchemy 2.0 / Pydantic v2 / SQLite (Phase 1) → PostgreSQL (Phase 2+)
> **客户端**: PyQt6 桌面 (`docs/客户端改造完整计划v2.md`) + React 后台 (`D:\ks_automation\web`)
> **架构蓝图**: `D:\ks_automation\docs\服务器后端完整蓝图_含AI自动化v1.md`
> **接口契约**: `D:\ks_automation\docs\后端开发技术文档与接口规范v1.md`

---

## 快速启动

```bash
# 1. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # Linux

# 2. 安装依赖
pip install -r requirements.txt

# 3. 准备 .env
copy .env.example .env

# 4. 初始化 DB (首次)
python -m scripts.init_db

# 5. 启动 (开发)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8800

# 6. 测试健康
curl http://127.0.0.1:8800/healthz
```

OpenAPI 文档: <http://127.0.0.1:8800/docs>

---

## 目录结构

```
bendi/
├── app/
│   ├── main.py                # FastAPI entry
│   ├── core/                  # 核心: config / db / security / errors / logging
│   ├── api/v1/                # REST 端点 (按业务模块分文件)
│   ├── models/                # SQLAlchemy ORM 模型 (按层 L0-L13)
│   ├── schemas/               # Pydantic 请求/响应模型
│   ├── services/              # 业务服务层
│   └── middleware/            # ASGI 中间件 (Envelope / TraceID / RateLimit)
├── migrations/                # Alembic 迁移
├── scripts/                   # 运维脚本 (init_db / seed / 同步等)
├── tests/                     # pytest
├── data/                      # SQLite 文件 (gitignored)
├── logs/                      # 日志 (gitignored)
├── pyproject.toml
├── requirements.txt
├── .env.example
└── README.md
```

---

## 14 层架构对应

| 层 | 模块 | 状态 |
|---|---|---|
| L0 平台 | `app/models/platform.py` | Phase 1 |
| L1 租户机构 | `app/models/organization.py` | Phase 1 |
| L2 用户权限 | `app/models/user.py` `role.py` `permission.py` | Phase 1 |
| L3 账号资产 | `app/models/account.py` | Phase 2 |
| L4 计划业务 | `app/models/plan.py` | Phase 2 |
| L5 任务执行 | `app/models/task.py` | Phase 2 |
| L6 收益结算 | `app/models/income.py` | Phase 2 |
| L7 内容资产 | `app/models/content.py` | Phase 2 |
| L8 运维审计 | `app/models/audit.py` | Phase 2 |
| L9 AI 决策 | `app/services/decision/*` | Phase 3 |
| L10 Agent | `app/services/agents/*` | Phase 3 |
| L11 AI 记忆 | `app/models/memory.py` | Phase 3 |
| L12 风控自愈 | `app/services/healing/*` | Phase 3 |
| L13 SaaS 卡密 | `app/models/license.py` | Phase 1 |

---

## 协议要点

- **Envelope 强制**: 所有 `/api/client/*` 返 `{ok, data|error, meta}`
- **JWT**: HS256, access 30min + refresh 30d
- **硬件指纹**: SHA256(cpu_id + mb_sn + disk_sn)[:32], 与 license 绑定
- **限流**: 用户 120/min + IP 60/min, /auth/* 5/min
- **幂等**: 写操作建议带 `Idempotency-Key`
- **时区**: Asia/Shanghai (UTC+8), ISO 8601

详见 `D:\ks_automation\docs\后端开发技术文档与接口规范v1.md`.

---

## 开发约定

```bash
# 代码风格
ruff check . --fix
ruff format .

# 测试
pytest -v

# 迁移
alembic revision --autogenerate -m "<message>"
alembic upgrade head
```
