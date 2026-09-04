"""
统一配置（T006）—— 全后端唯一配置入口（pydantic-settings）

读取优先级（高 → 低）：
  1. 进程环境变量
  2. .env.{APP_ENV}（环境特定覆盖文件，可选）
  3. .env（基础环境文件，可选）
  4. 本文件内的代码默认值（仅适配本地开发）

环境划分：APP_ENV ∈ local / development（两者等价，均指开发环境）
                            / staging / production
（保留 local 是为兼容 start_dev.py 注入的 APP_ENV=local）

业务代码统一用法：
    from config import settings
    settings.DB_HOST / settings.JWT_SECRET / settings.CORS_ORIGINS ...

兼容层：本模块同时平铺导出历史常量（DB_HOST、JWT_SECRET 等），
tools/ 与一次性迁移脚本按旧方式 `from config import DB_HOST` 依然可用，
业务代码（db.py / core / routes / modules）应改用 settings。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent

_DEV_ENVS = {"local", "development"}
PRODUCTION_ENVS = {"staging", "production"}
_ALLOWED_ENVS = _DEV_ENVS | PRODUCTION_ENVS


def _detect_app_env() -> str:
    """决定加载哪个 .env.{APP_ENV}：进程环境变量优先，其次 .env 内的 APP_ENV。"""
    env = os.environ.get("APP_ENV", "").strip()
    if env:
        return env
    base_env = BASE_DIR / ".env"
    if base_env.exists():
        for line in base_env.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if s.startswith("APP_ENV=") and not s.startswith("#"):
                return s.split("=", 1)[1].strip().strip("'\"") or "local"
    return "local"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # 列表内后列出的文件优先级更高：.env.{APP_ENV} 覆盖 .env（进程环境变量仍最高）
        env_file=[BASE_DIR / ".env", BASE_DIR / f".env.{_detect_app_env()}"],
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # ── 应用 ────────────────────────────────────────────────
    APP_ENV: str = "local"
    APP_NAME: str = "tech-transfer-service"
    APP_VERSION: str = "1.0.0"
    DEBUG: bool = False
    HOST: str = "0.0.0.0"
    PORT: int = 8787

    # ── 宿主与身份（staging/production 禁止 local/mock）─────
    HOST_MODE: str = "local"
    AUTH_PROVIDER: str = "mock"

    # ── 对外 API 地址（staging/production 必须为真实域名）───
    API_BASE: str = "http://127.0.0.1:8787"
    API_PREFIX: str = "/api/tech-transfer/v1"

    # ── 业务库（PostgreSQL / psycopg2）──────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres123"  # 本地开发默认值；staging/production 必须由环境提供
    DB_NAME: str = "tech_transfer"

    # ── 存量资本库（MySQL，仅 tools/etl_institutions.py 过渡期使用）──
    CAPITAL_DB_HOST: str = "127.0.0.1"
    CAPITAL_DB_PORT: int = 3306
    CAPITAL_DB_USER: str = "root"
    CAPITAL_DB_PASSWORD: str = "123456"  # 本地开发默认值

    # ── JWT（staging/production 必须提供强密钥）─────────────
    JWT_SECRET: str = "tech-transfer-dev-secret-key"  # 本地开发默认值
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES: int = 7200  # 秒
    REFRESH_TOKEN_EXPIRES_DAYS: int = 14

    # ── CORS（staging/production 需显式白名单）──────────────
    # NoDecode：跳过 pydantic-settings 的 JSON 预解码，交给下方 validator
    # 同时支持逗号分隔与 JSON 数组两种环境变量写法
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # ── 文件代理（第三方源站 + 本地缓存目录）────────────────
    SZTE_FILE_URL: str = (
        "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"
    )
    FILE_CACHE_DIR: str = "cache/logos"  # 相对 BASE_DIR，也可配绝对路径

    @field_validator("APP_ENV")
    @classmethod
    def _validate_app_env(cls, v: str) -> str:
        v = v.strip().lower()
        if v not in _ALLOWED_ENVS:
            raise ValueError(
                f"APP_ENV 必须是 {' / '.join(sorted(_ALLOWED_ENVS))} 之一，当前: {v}"
            )
        return v

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _parse_cors_origins(cls, v):
        # 同时支持逗号分隔（CORS_ORIGINS=https://a.com,https://b.com）
        # 与 JSON 数组（CORS_ORIGINS=["https://a.com"]）两种写法
        if isinstance(v, str):
            v = v.strip()
            if not v:
                return []
            if v.startswith("["):
                import json

                try:
                    return json.loads(v)
                except ValueError:
                    pass
            return [o.strip() for o in v.split(",") if o.strip()]
        return v

    # ── 环境判定 ────────────────────────────────────────────
    @property
    def is_local(self) -> bool:
        return self.APP_ENV in _DEV_ENVS

    @property
    def is_production_like(self) -> bool:
        return self.APP_ENV in PRODUCTION_ENVS

    @property
    def database_url(self) -> str:
        """统一生成的连接串（展示/工具用；运行时连接仍用离散字段）。"""
        return (
            f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}"
            f"@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"
        )

    @property
    def cors_origin_regex(self) -> str | None:
        """local：放行本机/局域网 H5 dev server（5173）与 frp 隧道入口（8077）；
        staging/production：无 regex，仅 CORS_ORIGINS 显式白名单。"""
        if self.is_local:
            return r"^https?://(localhost|127\.0\.0\.1|\d{1,3}(\.\d{1,3}){3}):(5173|8077)$"
        return None

    @property
    def file_cache_path(self) -> Path:
        p = Path(self.FILE_CACHE_DIR)
        return p if p.is_absolute() else BASE_DIR / p


settings = Settings()

# ── 向后兼容平铺导出（tools / 一次性脚本仍可 from config import DB_HOST ...）──
APP_ENV = settings.APP_ENV
HOST_MODE = settings.HOST_MODE
AUTH_PROVIDER = settings.AUTH_PROVIDER
API_BASE = settings.API_BASE
API_PREFIX = settings.API_PREFIX
DB_HOST = settings.DB_HOST
DB_PORT = settings.DB_PORT
DB_USER = settings.DB_USER
DB_PASSWORD = settings.DB_PASSWORD
DB_NAME = settings.DB_NAME
CAPITAL_DB_HOST = settings.CAPITAL_DB_HOST
CAPITAL_DB_PORT = settings.CAPITAL_DB_PORT
CAPITAL_DB_USER = settings.CAPITAL_DB_USER
CAPITAL_DB_PASSWORD = settings.CAPITAL_DB_PASSWORD
JWT_SECRET = settings.JWT_SECRET
JWT_ALGORITHM = settings.JWT_ALGORITHM
ACCESS_TOKEN_EXPIRES = settings.ACCESS_TOKEN_EXPIRES
REFRESH_TOKEN_EXPIRES_DAYS = settings.REFRESH_TOKEN_EXPIRES_DAYS
CORS_ORIGINS = settings.CORS_ORIGINS

# Mock 身份提供方的开发期固定值（非环境相关配置，不进 Settings）
MOCK_ISSUER = "local-dev"
MOCK_SUBJECT = "dev-user-001"
MOCK_DISPLAY_NAME = "本地测试用户"
MOCK_TICKET_PREFIX = "local-dev-ticket-"

# ── staging / production 启动保护 ──────────────────────────
_BANNED_IN_PRODUCTION = {
    "HOST_MODE": "local",
    "AUTH_PROVIDER": "mock",
}
_WEAK_SECRETS = {
    "change-me",
    "secret",
    "123456",
    "default-secret",
    "password",
    "tech-transfer-dev-secret-key",
}
_WEAK_DB_PASSWORDS = {"123456", "postgres123", "password", "postgres", "root", ""}


def assert_environment():
    """staging/production 启动断言：弱配置直接终止进程（sys.exit(1)）。"""
    if not settings.is_production_like:
        return
    env = settings.APP_ENV
    violations = []
    for key, banned_val in _BANNED_IN_PRODUCTION.items():
        if getattr(settings, key) == banned_val:
            violations.append(f"{key}={banned_val}")
    if settings.DEBUG:
        violations.append("DEBUG=true")
    secret = settings.JWT_SECRET.strip()
    if (not secret) or (secret.lower() in _WEAK_SECRETS) or ("change-me" in secret.lower()) or len(secret) < 16:
        violations.append("JWT_SECRET 为空/弱密钥/默认开发密钥（需 ≥16 位随机值）")
    if settings.DB_PASSWORD in _WEAK_DB_PASSWORDS:
        violations.append("DB_PASSWORD 为空/弱密码/本地开发默认值")
    if "127.0.0.1" in settings.API_BASE or "localhost" in settings.API_BASE:
        violations.append(f"API_BASE={settings.API_BASE} 指向本机回环地址")
    if not settings.CORS_ORIGINS:
        sys.stderr.write(
            f"[WARN] {env} 环境未配置 CORS_ORIGINS，跨域前端将被浏览器拦截"
            f"（同源部署可忽略）\n"
        )
    if violations:
        sys.stderr.write(
            f"[FATAL] 环境保护断言失败（{env}）：\n  - "
            + "\n  - ".join(violations)
            + f"\n以上配置不允许在 {env} 环境启动\n"
        )
        sys.exit(1)
