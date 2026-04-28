@echo off
REM KSJuzheng Backend — 开发模式启动 (Windows)

cd /d "%~dp0"

if not exist .env (
  echo [start_dev] .env 不存在, 复制 .env.example -^> .env
  copy .env.example .env
)

if not exist data\ksjuzheng.db (
  echo [start_dev] DB 不存在, 自动初始化 + seed
  python -m scripts.init_db --seed
)

echo [start_dev] 启动 uvicorn (http://127.0.0.1:8800)
python -m uvicorn app.main:app --reload --host 0.0.0.0 --port 8800
