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

from pydantic import field_validator, model_validator
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
    WECHAT_LOGIN_ENABLED: bool = False
    WECHAT_APPID: str = ""
    WECHAT_APP_SECRET: str = ""

    # ── 对外 API 地址（staging/production 必须为真实域名）───
    API_BASE: str = "http://127.0.0.1:8787"
    API_PREFIX: str = "/api/tech-transfer/v1"

    # ── 业务库（PostgreSQL / psycopg2）──────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres123"  # 本地开发默认值；staging/production 必须由环境提供
    DB_NAME: str = "tech_transfer"

    # ── DB 连接池（T007：psycopg2 ThreadedConnectionPool，进程内）──
    # 规模约束：uvicorn worker 数 × DB_POOL_MAX ≤ PostgreSQL max_connections；
    # 本地默认单 worker；「我的」页会并发打出十余个 /me/* 查询，max=20 留余量
    DB_POOL_MIN: int = 2
    DB_POOL_MAX: int = 20
    DB_CONNECT_TIMEOUT: int = 5  # 秒；防止 DB 不可用时 connect 长时间挂起
    DB_POOL_ACQUIRE_TIMEOUT: float = 3.0  # 秒；池满时等待归还，0=立即失败

    # ── 存量资本库（MySQL，仅 tools/etl_institutions.py 过渡期使用）──
    CAPITAL_DB_HOST: str = "127.0.0.1"
    CAPITAL_DB_PORT: int = 3306
    CAPITAL_DB_USER: str = "root"
    CAPITAL_DB_PASSWORD: str = "123456"  # 本地开发默认值

    # ── JWT（staging/production 必须提供强密钥）─────────────
    JWT_SECRET: str = "tech-transfer-dev-secret-key"  # 本地开发默认值；生产由 assert_environment 拦截
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRES: int = 7200  # 秒
    REFRESH_TOKEN_EXPIRES_DAYS: int = 14

    # ── uvicorn workers（生产多进程；需与 DB 连接池 × workers ≤ PG max_connections）──
    UVICORN_WORKERS: int = 2

    # ── CORS（staging/production 需显式白名单）──────────────
    # NoDecode：跳过 pydantic-settings 的 JSON 预解码，交给下方 validator
    # 同时支持逗号分隔与 JSON 数组两种环境变量写法
    CORS_ORIGINS: Annotated[list[str], NoDecode] = []

    # ── 文件代理（第三方源站 + 本地缓存目录）────────────────
    SZTE_FILE_URL: str = (
        "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"
    )
    FILE_CACHE_DIR: str = "cache/logos"  # 相对 BASE_DIR，也可配绝对路径

    # ── 用户上传媒体（与第三方 Logo 代理缓存完全隔离）────────
    # 默认落到用户数据目录，避免把运行时文件写进后端源码或小程序包。
    # 生产环境必须通过 MEDIA_ROOT 挂载持久化卷，并配置 MEDIA_BASE_URL。
    MEDIA_ROOT: str = ""
    MEDIA_BASE_URL: str = "/api/tech-transfer/v1/files"
    MAX_UPLOAD_BYTES: int = 20 * 1024 * 1024
    MAX_IMPORT_BYTES: int = 80 * 1024 * 1024

    # ── 日志（L5/L7：LOG_LEVEL 可配 + RotatingFileHandler 落盘轮转）──
    LOG_LEVEL: str = "INFO"
    LOG_DIR: str = ""  # 空=仅控制台；非空=落盘到该目录（RotatingFileHandler 20MB×5）
    LOG_MAX_BYTES: int = 20 * 1024 * 1024
    LOG_BACKUP_COUNT: int = 5

    # ── 请求超时上限（M1：sync 路由保护）────────────────────
    MAX_REQUEST_SECONDS: float = 60.0

    # ── 专利检索 Provider（密钥只在服务端，禁止下发前端）──
    PATENT_PROVIDER_BASE: str = ""
    PATENT_PROVIDER_KEY: str = ""
    PATENT_PROVIDER_TIMEOUT: int = 30
    PATENT_PDF_TIMEOUT: int = 45

    # ── AI 能力开关（与前端 feature-flags.js 对齐）──────────
    AI_FEATURE_ENABLED: bool = True

    # ── nanshan-ai-agent demo（自然语言查询成果/需求）──────
    # 独立 FastAPI 服务，本服务通过 HTTP 转发 /ai/chat；为空则禁用聊天代理。
    # ai-agent 与本服务同机部署（默认 127.0.0.1:8001，见 nanshan-ai-agent/run_local.bat
    # 与 start_dev.py 的 AI_AGENT_PORT）；.env 必须显式配置，禁止依赖隐式默认值。
    AI_AGENT_URL: str = "http://127.0.0.1:8001/api/ai/chat"
    AI_AGENT_TIMEOUT: int = 30  # 秒；主服务转发 ai-agent 的单次超时（M1：防止 sync 路由长阻塞耗尽线程池）
    # 同步阻塞 LLM 转发并发上限（routes/ai.py 的信号量）；运维可通过 .env 调参。
    AI_MAX_CONCURRENT: int = 4

    # ── 爱马仕 Hermes / OpenAI 兼容 Provider（密钥只在服务端）──
    # 企业微信 Bot 长连接由爱马仕 gateway 持有（服务器在别处），本服务只走 HTTP。
    AI_PROVIDER_BASE: str = ""
    AI_PROVIDER_KEY: str = ""
    AI_PROVIDER_MODEL: str = "hermes-agent"
    AI_PROVIDER_TIMEOUT: int = 120
    WECOM_BOT_ID: str = ""
    WECOM_SECRET: str = ""
    WECOM_WEBSOCKET_URL: str = "wss://openws.work.weixin.qq.com"

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

    @field_validator("DB_POOL_MIN", "DB_POOL_MAX", "DB_CONNECT_TIMEOUT")
    @classmethod
    def _validate_pool_sizes(cls, v: int) -> int:
        if v < 1:
            raise ValueError("DB 连接池参数必须 >= 1")
        return v

    @field_validator("DB_POOL_ACQUIRE_TIMEOUT")
    @classmethod
    def _validate_acquire_timeout(cls, v: float) -> float:
        if v < 0:
            raise ValueError("DB_POOL_ACQUIRE_TIMEOUT 必须 >= 0")
        return v

    @field_validator("AI_MAX_CONCURRENT", "AI_AGENT_TIMEOUT")
    @classmethod
    def _validate_ai_limits(cls, v: int) -> int:
        if v < 1:
            raise ValueError("AI_MAX_CONCURRENT / AI_AGENT_TIMEOUT 必须 >= 1")
        return v

    @field_validator("LOG_LEVEL")
    @classmethod
    def _validate_log_level(cls, v: str) -> str:
        level = v.strip().upper()
        if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise ValueError(f"LOG_LEVEL 必须是 DEBUG/INFO/WARNING/ERROR/CRITICAL 之一，当前: {v}")
        return level

    @field_validator("MAX_REQUEST_SECONDS")
    @classmethod
    def _validate_max_request_seconds(cls, v: float) -> float:
        if v < 1 or v > 300:
            raise ValueError("MAX_REQUEST_SECONDS 必须在 1-300 秒之间")
        return v

    @field_validator("MAX_UPLOAD_BYTES", "MAX_IMPORT_BYTES")
    @classmethod
    def _validate_upload_limits(cls, v: int) -> int:
        if v < 1024:
            raise ValueError("MAX_UPLOAD_BYTES / MAX_IMPORT_BYTES 必须 >= 1KB")
        return v

    @model_validator(mode="after")
    def _validate_pool_order(self):
        if self.DB_POOL_MIN > self.DB_POOL_MAX:
            raise ValueError(
                f"DB_POOL_MIN({self.DB_POOL_MIN}) 不能大于 DB_POOL_MAX({self.DB_POOL_MAX})"
            )
        # L8: 连接池总量约束 — DB_POOL_MAX × UVICORN_WORKERS 不应超过保守上限（100）
        total_conns = self.DB_POOL_MAX * max(1, self.UVICORN_WORKERS)
        if total_conns > 100:
            import warnings
            warnings.warn(
                f"DB_POOL_MAX({self.DB_POOL_MAX}) × UVICORN_WORKERS({self.UVICORN_WORKERS}) = {total_conns}，"
                f"可能超过 PostgreSQL max_connections，请确认 PG 配置",
                stacklevel=2,
            )
        return self

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
        staging/production：放行 Postman/Swagger/Apifox 等API测试工具。"""
        if self.is_local:
            return r"^https?://(localhost|127\.0\.0\.1|\d{1,3}(\.\d{1,3}){3}):(5173|8077)$"
        # 放行常见API测试工具的Origin（简化regex）
        return r"^https?://.*\.(postman|swagger|apifox|hoppscotch)\.(com|io|app)(:\d+)?$"

    @property
    def file_cache_path(self) -> Path:
        p = Path(self.FILE_CACHE_DIR)
        return p if p.is_absolute() else BASE_DIR / p

    @property
    def media_root_path(self) -> Path:
        if self.MEDIA_ROOT.strip():
            return Path(self.MEDIA_ROOT).expanduser()
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            return Path(local_app_data) / "NanshanTechTransfer" / "media"
        return BASE_DIR.parent / ".runtime-media"


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
    if (not secret) or (secret.lower() in _WEAK_SECRETS) or ("change-me" in secret.lower()) or len(secret) < 32:
        violations.append("JWT_SECRET 为空/弱密钥/默认开发密钥（需 ≥32 位随机值，openssl rand -hex 32）")
    password = settings.DB_PASSWORD.strip()
    if password in _WEAK_DB_PASSWORDS or len(password) < 12:
        violations.append("DB_PASSWORD 为空/弱密码/本地开发默认值（需 ≥12 位强密码）")
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
