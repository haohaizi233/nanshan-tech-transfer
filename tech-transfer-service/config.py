import os
import sys

APP_ENV = os.environ.get("APP_ENV", "local")
HOST_MODE = os.environ.get("HOST_MODE", "local")
AUTH_PROVIDER = os.environ.get("AUTH_PROVIDER", "mock")
API_BASE = os.environ.get("API_BASE", "http://127.0.0.1:8787")
API_PREFIX = "/api/tech-transfer/v1"

DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "5432"))
DB_USER = os.environ.get("DB_USER", "postgres")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "postgres123")
DB_NAME = os.environ.get("DB_NAME", "tech_transfer")

# 存量资本库（MySQL，仅 legacy capital 接口过渡期使用，P0-1 后由 institution 表接管）
CAPITAL_DB_HOST = os.environ.get("CAPITAL_DB_HOST", "127.0.0.1")
CAPITAL_DB_PORT = int(os.environ.get("CAPITAL_DB_PORT", "3306"))
CAPITAL_DB_USER = os.environ.get("CAPITAL_DB_USER", "root")
CAPITAL_DB_PASSWORD = os.environ.get("CAPITAL_DB_PASSWORD", "123456")

JWT_SECRET = os.environ.get("JWT_SECRET", "tech-transfer-dev-secret-key")
ACCESS_TOKEN_EXPIRES = 7200
REFRESH_TOKEN_EXPIRES_DAYS = 14

MOCK_ISSUER = "local-dev"
MOCK_SUBJECT = "dev-user-001"
MOCK_DISPLAY_NAME = "本地测试用户"
MOCK_TICKET_PREFIX = "local-dev-ticket-"

BANNED_IN_PRODUCTION = {
    "HOST_MODE": "local",
    "AUTH_PROVIDER": "mock",
}
PRODUCTION_ENVS = {"staging", "production"}


def assert_environment():
    if APP_ENV not in PRODUCTION_ENVS:
        return
    violations = []
    for key, banned_val in BANNED_IN_PRODUCTION.items():
        current = os.environ.get(key, "")
        if current == banned_val:
            violations.append(f"{key}={banned_val}")
    if violations:
        sys.stderr.write(
            f"[FATAL] 环境保护断言失败：{', '.join(violations)} "
            f"不允许在 {APP_ENV} 环境启动\n"
        )
        sys.exit(1)
