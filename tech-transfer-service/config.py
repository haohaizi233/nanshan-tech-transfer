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

    # ── 微信开放平台（PC 网站扫码登录 OAuth2）────────────────
    WECHAT_OPEN_ENABLED: bool = False
    WECHAT_OPEN_APPID: str = ""
    WECHAT_OPEN_APP_SECRET: str = ""

    # ── Redis 缓存与分布式原子限流 ──────────────────────────
    REDIS_ENABLED: bool = False
    REDIS_URL: str = "redis://127.0.0.1:6379/0"

    # ── 短信服务（SmsProvider：mock / tencent / sendcloud）──────
    SMS_ENABLED: bool = False
    SMS_PROVIDER: str = "mock"
    SMS_USER: str = ""
    SMS_KEY: str = ""
    SENDCLOUD_SMS_USER: str = ""
    SENDCLOUD_SMS_KEY: str = ""
    SENDCLOUD_SMS_TEMPLATE_ID: str = ""
    TENCENT_SMS_SECRET_ID: str = ""
    TENCENT_SMS_SECRET_KEY: str = ""
    TENCENT_SMS_SDK_APP_ID: str = ""
    TENCENT_SMS_SIGN_NAME: str = "南山科转通"
    TENCENT_SMS_TEMPLATE_ID: str = ""

    # SMS risk policy
    SMS_RISK_ENGINE_ENABLED: bool = True
    SMS_RISK_HMAC_SECRET: str = ""
    SMS_CODE_TTL_SECONDS: int = 300
    SMS_CODE_MAX_ATTEMPTS: int = 5
    SMS_PHONE_COOLDOWN_SECONDS: int = 60
    SMS_PHONE_LIMIT_10M: int = 3
    SMS_PHONE_LIMIT_1H: int = 5
    SMS_PHONE_LIMIT_DAY: int = 10
    SMS_IP_LIMIT_1M: int = 10
    SMS_IP_LIMIT_1H: int = 60
    SMS_IP_LIMIT_DAY: int = 200
    SMS_IP_DISTINCT_PHONE_LIMIT_1H: int = 10
    SMS_DEVICE_LIMIT_1H: int = 10
    SMS_DEVICE_LIMIT_DAY: int = 20
    SMS_REQUIRE_VERIFIED_CONTACT: bool = True
    SMS_SERVICE_CLIENTS: dict[str, str] = {}
    SMS_REQUEST_MAX_BYTES: int = 4096
    SMS_SERVICE_TIMESTAMP_WINDOW_SECONDS: int = 300
    SMS_LIVE_TEST_ENABLED: bool = False
    SMS_BUSINESS_TIMEZONE: str = "Asia/Shanghai"
    SMS_ACCOUNT_LIMIT_1H: int = 5
    SMS_ACCOUNT_LIMIT_DAY: int = 10
    SMS_DEVICE_DISTINCT_PHONE_LIMIT_10M: int = 5
    SENDCLOUD_SMS_MAX_ATTEMPTS: int = 3

    # ── 邮件服务（EmailProvider：mock / tencent / smtp）─────
    EMAIL_ENABLED: bool = False
    EMAIL_PROVIDER: str = "mock"
    TENCENT_SES_SECRET_ID: str = ""
    TENCENT_SES_SECRET_KEY: str = ""
    TENCENT_SES_FROM_EMAIL: str = ""
    TENCENT_SES_REGION: str = "ap-hongkong"
    TENCENT_SES_ENDPOINT: str = "ses.tencentcloudapi.com"
    TENCENT_SES_TIMEOUT_SECONDS: int = 10
    TENCENT_SES_TEMPLATE_ID_OTP: int = 0
    TENCENT_SES_TEMPLATE_ID_RESET: int = 0
    SMTP_HOST: str = ""
    SMTP_PORT: int = 465
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = ""
    SMTP_FROM_NAME: str = "南山科转通"
    SMTP_USE_SSL: bool = True
    SMTP_TIMEOUT_SECONDS: int = 10
    SMTP_MAX_ATTEMPTS: int = 2

    # ── 安全密钥隔离（OTP / 联系方式盲索引 / Step-up）──────────
    SECURITY_OTP_HMAC_SECRET: str = ""
    SECURITY_CONTACT_HMAC_SECRET: str = ""
    STEP_UP_GRANT_TTL_SECONDS: int = 300
    STEP_UP_RECENT_AUTH_SECONDS: int = 300
    IDEMPOTENCY_REQUEST_TTL_SECONDS: int = 300
    IDEMPOTENCY_EXECUTION_OWNERSHIP_SECONDS: int = 300
    IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS: int = 86400
    RISK_SYNC_MAX_ATTEMPTS: int = 5
    RISK_SYNC_RETRY_BASE_SECONDS: int = 5
    RISK_SYNC_RETRY_MAX_SECONDS: int = 300

    # ── Email Gateway 策略与多维风控 ───────────────────────────
    EMAIL_CODE_TTL_SECONDS: int = 300
    EMAIL_LINK_TTL_SECONDS: int = 300
    EMAIL_CODE_MAX_ATTEMPTS: int = 5
    EMAIL_RISK_ENGINE_ENABLED: bool = True
    EMAIL_RISK_HMAC_SECRET: str = ""
    EMAIL_REQUIRE_VERIFIED_CONTACT: bool = True
    EMAIL_SECURITY_NOTIFICATION_ENABLED: bool = False
    EMAIL_LIVE_TEST_ENABLED: bool = False
    EMAIL_COOLDOWN_SECONDS: int = 60
    EMAIL_LIMIT_10M: int = 3
    EMAIL_LIMIT_1H: int = 5
    EMAIL_LIMIT_DAY: int = 15
    EMAIL_IP_LIMIT_1M: int = 10
    EMAIL_IP_LIMIT_1H: int = 50
    EMAIL_IP_LIMIT_DAY: int = 200
    EMAIL_ACCOUNT_LIMIT_1H: int = 5
    EMAIL_ACCOUNT_LIMIT_DAY: int = 15
    EMAIL_DEVICE_LIMIT_1H: int = 20
    EMAIL_DEVICE_LIMIT_DAY: int = 50
    EMAIL_IP_DISTINCT_LIMIT_1H: int = 10
    EMAIL_DEVICE_DISTINCT_LIMIT_10M: int = 5
    EMAIL_GLOBAL_DAILY_BUDGET: int = 5000
    EMAIL_DOMAIN_ANOMALY_LIMIT_10M: int = 50

    # ── 前端页面地址（用于生成密码重置链接与扫码回调）──────
    FRONTEND_URL: str = "http://localhost:5173"

    # ── 对外 API 地址（staging/production 必须为真实域名）───
    API_BASE: str = "http://127.0.0.1:8787"
    API_PREFIX: str = "/api/tech-transfer/v1"

    # ── 业务库（PostgreSQL / psycopg2）──────────────────────
    DB_HOST: str = "127.0.0.1"
    DB_PORT: int = 5432
    DB_USER: str = "postgres"
    DB_PASSWORD: str = "postgres123"  # 本地开发默认值；staging/production 必须由环境提供
    DB_NAME: str = "tech_transfer"

    @field_validator("DB_PASSWORD", mode="before")
    @classmethod
    def _fallback_db_password(cls, v):
        if not v or v == "postgres123":
            alt = os.environ.get("DB_PWD") or os.environ.get("DB_PWD_READONLY")
            if alt:
                return alt
        return v

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
    SZTE_FILE_URL: str = "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"
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
    # 公开号补位枚举的整轮时间预算（秒）。上游被限流时单次请求会退化到十几秒，
    # 同步接口不能被拖死：超预算后放弃剩余候选，用已拿到的结果返回。
    PATENT_ENUM_TIMEOUT: float = 8.0

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
    AI_CHAT_RUNS_ENABLED: bool = False
    AI_INTERNAL_SERVICE_KEY: str = ""
    # 同步对话通道（主服务 → ai-agent /api/ai/chat）的服务间密钥。
    # 留空时复用 AI_INTERNAL_SERVICE_KEY；两者都为空时 ai-agent 仅接受本机回环调用。
    AI_PUBLIC_API_KEY: str = ""
    AI_CHAT_STREAM_URL: str = "http://127.0.0.1:8001/internal/ai/chat/stream"
    AI_CHAT_GLOBAL_SLOTS: int = 4
    AI_CHAT_QUEUE_SECONDS: int = 30
    AI_CHAT_EXECUTION_SECONDS: int = 55
    AI_CHAT_LEASE_SECONDS: int = 20
    AI_CHAT_RENEW_SECONDS: int = 5
    AI_CHAT_REAP_SECONDS: int = 5

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
            raise ValueError(f"APP_ENV 必须是 {' / '.join(sorted(_ALLOWED_ENVS))} 之一，当前: {v}")
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

    @field_validator(
        "AI_MAX_CONCURRENT",
        "AI_AGENT_TIMEOUT",
        "AI_CHAT_GLOBAL_SLOTS",
        "AI_CHAT_QUEUE_SECONDS",
        "AI_CHAT_EXECUTION_SECONDS",
        "AI_CHAT_LEASE_SECONDS",
        "AI_CHAT_RENEW_SECONDS",
        "AI_CHAT_REAP_SECONDS",
    )
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

    @field_validator(
        "SMS_CODE_TTL_SECONDS",
        "SMS_CODE_MAX_ATTEMPTS",
        "SMS_PHONE_COOLDOWN_SECONDS",
        "SMS_PHONE_LIMIT_10M",
        "SMS_PHONE_LIMIT_1H",
        "SMS_PHONE_LIMIT_DAY",
        "SMS_IP_LIMIT_1M",
        "SMS_IP_LIMIT_1H",
        "SMS_IP_LIMIT_DAY",
        "SMS_IP_DISTINCT_PHONE_LIMIT_1H",
        "SMS_DEVICE_LIMIT_1H",
        "SMS_DEVICE_LIMIT_DAY",
        "SMS_ACCOUNT_LIMIT_1H",
        "SMS_ACCOUNT_LIMIT_DAY",
        "SMS_DEVICE_DISTINCT_PHONE_LIMIT_10M",
        "SMS_REQUEST_MAX_BYTES",
        "SMS_SERVICE_TIMESTAMP_WINDOW_SECONDS",
        "SENDCLOUD_SMS_MAX_ATTEMPTS",
    )
    @classmethod
    def _validate_sms_positive(cls, value):
        if value < 1:
            raise ValueError("SMS limits must be positive")
        return value

    @field_validator("SMS_BUSINESS_TIMEZONE")
    @classmethod
    def _validate_sms_timezone(cls, value):
        from zoneinfo import ZoneInfo

        ZoneInfo(value)
        return value

    @field_validator(
        "SMTP_TIMEOUT_SECONDS",
        "SMTP_MAX_ATTEMPTS",
        "TENCENT_SES_TIMEOUT_SECONDS",
        "STEP_UP_GRANT_TTL_SECONDS",
        "STEP_UP_RECENT_AUTH_SECONDS",
        "EMAIL_CODE_TTL_SECONDS",
        "EMAIL_LINK_TTL_SECONDS",
        "EMAIL_CODE_MAX_ATTEMPTS",
        "EMAIL_COOLDOWN_SECONDS",
        "EMAIL_LIMIT_10M",
        "EMAIL_LIMIT_1H",
        "EMAIL_LIMIT_DAY",
        "EMAIL_IP_LIMIT_1M",
        "EMAIL_IP_LIMIT_1H",
        "EMAIL_IP_LIMIT_DAY",
        "EMAIL_ACCOUNT_LIMIT_1H",
        "EMAIL_ACCOUNT_LIMIT_DAY",
        "EMAIL_DEVICE_LIMIT_1H",
        "EMAIL_DEVICE_LIMIT_DAY",
        "EMAIL_IP_DISTINCT_LIMIT_1H",
        "EMAIL_DEVICE_DISTINCT_LIMIT_10M",
        "EMAIL_GLOBAL_DAILY_BUDGET",
        "EMAIL_DOMAIN_ANOMALY_LIMIT_10M",
        "RISK_SYNC_MAX_ATTEMPTS",
        "RISK_SYNC_RETRY_BASE_SECONDS",
        "RISK_SYNC_RETRY_MAX_SECONDS",
    )
    @classmethod
    def _validate_email_positive(cls, value):
        if value < 1:
            raise ValueError("Email limits and timeouts must be positive")
        return value

    @field_validator("IDEMPOTENCY_REQUEST_TTL_SECONDS", "IDEMPOTENCY_EXECUTION_OWNERSHIP_SECONDS")
    @classmethod
    def _validate_idempotency_ttl(cls, value: int) -> int:
        if value < 60:
            raise ValueError("IDEMPOTENCY TTL 必须 >= 60 秒")
        return value

    @field_validator("IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS")
    @classmethod
    def _validate_unknown_retention(cls, value: int) -> int:
        if value < 300:
            raise ValueError("IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS 必须 >= 300 秒")
        return value

    @field_validator("SMTP_PORT")
    @classmethod
    def _validate_smtp_port(cls, value: int) -> int:
        if not 1 <= value <= 65535:
            raise ValueError("SMTP_PORT 必须在 1-65535 之间")
        return value

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
        if self.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS < self.IDEMPOTENCY_REQUEST_TTL_SECONDS:
            raise ValueError(
                f"IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS({self.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS}) "
                f"不能小于 IDEMPOTENCY_REQUEST_TTL_SECONDS({self.IDEMPOTENCY_REQUEST_TTL_SECONDS})"
            )
        if self.RISK_SYNC_RETRY_MAX_SECONDS < self.RISK_SYNC_RETRY_BASE_SECONDS:
            raise ValueError(
                f"RISK_SYNC_RETRY_MAX_SECONDS({self.RISK_SYNC_RETRY_MAX_SECONDS}) "
                f"不能小于 RISK_SYNC_RETRY_BASE_SECONDS({self.RISK_SYNC_RETRY_BASE_SECONDS})"
            )
        if self.DB_POOL_MIN > self.DB_POOL_MAX:
            raise ValueError(f"DB_POOL_MIN({self.DB_POOL_MIN}) 不能大于 DB_POOL_MAX({self.DB_POOL_MAX})")
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
        return f"postgresql://{self.DB_USER}:{self.DB_PASSWORD}@{self.DB_HOST}:{self.DB_PORT}/{self.DB_NAME}"

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


def validate_frontend_reset_base_url(raw_url: str, *, production_like: bool = False) -> str:
    """校验用于拼接密码重置链接的受信任前端基地址。

    禁止用户控制域名、内嵌凭证、query/fragment 或开放重定向；
    staging/production 必须使用非回环 HTTPS 地址。
    """
    from urllib.parse import urlsplit

    text = (raw_url or "").strip()
    if not text or any(ord(c) < 32 or ord(c) == 127 or c.isspace() for c in text):
        raise ValueError("FRONTEND_URL 不能为空或包含空白/控制字符")
    parsed = urlsplit(text)
    scheme = (parsed.scheme or "").lower()
    if scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise ValueError("FRONTEND_URL 必须是合法的 http/https 地址")
    if parsed.username or parsed.password:
        raise ValueError("FRONTEND_URL 不允许包含账号密码信息")
    if parsed.query or parsed.fragment:
        raise ValueError("FRONTEND_URL 不允许包含查询参数或片段")
    host = parsed.hostname.lower()
    if production_like:
        if scheme != "https":
            raise ValueError("staging/production 环境 FRONTEND_URL 必须使用 https")
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"} or host.endswith(".local"):
            raise ValueError(f"staging/production 环境 FRONTEND_URL 不允许指向本地地址 ({host})")
    path = parsed.path.rstrip("/")
    return f"{scheme}://{parsed.netloc}{path}"


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
        sys.stderr.write(f"[WARN] {env} 环境未配置 CORS_ORIGINS，跨域前端将被浏览器拦截（同源部署可忽略）\n")
    if settings.SMS_ENABLED and settings.SMS_PROVIDER == "mock":
        violations.append("生产环境启用了 SMS_ENABLED 但 SMS_PROVIDER 仍为 mock")
    if settings.SMS_ENABLED and not settings.REDIS_ENABLED:
        violations.append("生产短信安全网关必须显式配置 REDIS_ENABLED=true")
    if settings.EMAIL_ENABLED:
        email_provider = (settings.EMAIL_PROVIDER or "").strip().lower()
        if email_provider == "mock":
            violations.append("生产环境启用了 EMAIL_ENABLED 但 EMAIL_PROVIDER 仍为 mock")
        elif email_provider not in {"smtp", "tencent"}:
            violations.append(f"生产环境 EMAIL_PROVIDER 无效或不支持: {settings.EMAIL_PROVIDER}")
        if not settings.REDIS_ENABLED:
            violations.append("生产邮件安全网关必须显式配置 REDIS_ENABLED=true")
        if not settings.EMAIL_RISK_ENGINE_ENABLED:
            violations.append("生产邮件安全网关必须启用 EMAIL_RISK_ENGINE_ENABLED=true")
        if not settings.EMAIL_REQUIRE_VERIFIED_CONTACT:
            violations.append("生产邮件安全网关必须启用 EMAIL_REQUIRE_VERIFIED_CONTACT=true")
        if email_provider == "smtp":
            if not settings.SMTP_HOST.strip():
                violations.append("启用 SMTP 时必须配置 SMTP_HOST")
            if not settings.SMTP_USER.strip() or not settings.SMTP_PASSWORD.strip():
                violations.append("启用 SMTP 时必须配置 SMTP_USER 与 SMTP_PASSWORD")
        elif email_provider == "tencent":
            if (
                not settings.TENCENT_SES_SECRET_ID.strip()
                or not settings.TENCENT_SES_SECRET_KEY.strip()
                or not settings.TENCENT_SES_FROM_EMAIL.strip()
                or not settings.TENCENT_SES_REGION.strip()
            ):
                violations.append(
                    "启用腾讯云 SES 时必须配置 TENCENT_SES_SECRET_ID / TENCENT_SES_SECRET_KEY / "
                    "TENCENT_SES_FROM_EMAIL / TENCENT_SES_REGION"
                )
        try:
            validate_frontend_reset_base_url(settings.FRONTEND_URL, production_like=True)
        except ValueError as exc:
            violations.append(str(exc))
    if violations:
        sys.stderr.write(
            f"[FATAL] 环境保护断言失败（{env}）：\n  - "
            + "\n  - ".join(violations)
            + f"\n以上配置不允许在 {env} 环境启动\n"
        )
        sys.exit(1)
