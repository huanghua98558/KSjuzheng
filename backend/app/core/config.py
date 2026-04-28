"""全局配置 — 从 .env 加载, 单例 Settings.

使用方式:
    from app.core.config import settings
    settings.SECRET_KEY
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


BASE_DIR = Path(__file__).resolve().parent.parent.parent  # bendi/


class Settings(BaseSettings):
    """全部 .env 变量, 类型校验由 Pydantic 处理."""

    model_config = SettingsConfigDict(
        env_file=str(BASE_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )

    # === 服务 ===
    APP_NAME: str = "KSJuzheng-Backend"
    APP_VERSION: str = "0.1.0"
    APP_ENV: str = "dev"
    DEBUG: bool = True
    HOST: str = "0.0.0.0"
    PORT: int = 8800
    TIMEZONE: str = "Asia/Shanghai"

    # === 安全 ===
    SECRET_KEY: str = "dev-secret-please-change"
    JWT_ALG: str = "HS256"
    JWT_ACCESS_TTL_MIN: int = 30
    JWT_REFRESH_TTL_DAYS: int = 30
    PASSWORD_MIN_LEN: int = 8

    # === DB ===
    DATABASE_URL: str = "sqlite:///./data/ksjuzheng.db"
    DB_POOL_SIZE: int = 10
    DB_BUSY_TIMEOUT_MS: int = 30000

    # === Redis ===
    REDIS_URL: str | None = None

    # === CORS ===
    CORS_ORIGINS: str = "http://localhost:3000,http://localhost:5173,http://127.0.0.1:5173"

    # === 限流 ===
    RATE_LIMIT_DEFAULT: str = "120/minute"
    RATE_LIMIT_AUTH: str = "5/minute"
    RATE_LIMIT_PUBLISH_BATCH: str = "10/minute"

    # === 日志 ===
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = "./logs"
    LOG_RETENTION_DAYS: int = 14

    # === 派生属性 ===
    @property
    def base_dir(self) -> Path:
        return BASE_DIR

    @property
    def data_dir(self) -> Path:
        d = BASE_DIR / "data"
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def log_dir(self) -> Path:
        d = Path(self.LOG_DIR)
        if not d.is_absolute():
            d = BASE_DIR / d
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def cors_origins_list(self) -> list[str]:
        return [o.strip() for o in self.CORS_ORIGINS.split(",") if o.strip()]

    @property
    def is_sqlite(self) -> bool:
        return self.DATABASE_URL.startswith("sqlite")

    @field_validator("APP_ENV")
    @classmethod
    def _check_env(cls, v: str) -> str:
        if v not in ("dev", "prod", "test"):
            raise ValueError(f"APP_ENV must be dev/prod/test, got {v}")
        return v


@lru_cache
def get_settings() -> Settings:
    return Settings()


# 模块级单例
settings = get_settings()
