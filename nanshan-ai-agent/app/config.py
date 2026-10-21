"""
L5: ai-agent 配置校验 — 启动时检查必填项，缺失时 fail-fast。
"""
import math
import os
import sys
from dotenv import load_dotenv

load_dotenv()


class Settings:
    # LLM
    LLM_API_URL = os.getenv("LLM_API_URL")
    LLM_API_KEY = os.getenv("LLM_API_KEY")
    LLM_MODEL = os.getenv("LLM_MODEL")

    # 备用 LLM Provider（主 Provider 不可用时自动切换）
    LLM_FALLBACK_URL = os.getenv("LLM_FALLBACK_URL")
    LLM_FALLBACK_KEY = os.getenv("LLM_FALLBACK_KEY")
    LLM_FALLBACK_MODEL = os.getenv("LLM_FALLBACK_MODEL")

    # M4: TLS 证书校验开关。默认开启；仅内网自签证书等特殊场景可显式关闭。
    LLM_VERIFY_SSL = os.getenv("LLM_VERIFY_SSL", "true").strip().lower() not in (
        "0", "false", "no", "off",
    )
    # N5: 主 + 备 Provider 共享的墙钟总超时预算（秒）。<=0 表示自动（2×单次 timeout，上限 120s）。
    LLM_FALLBACK_BUDGET_SECONDS = float(os.getenv("LLM_FALLBACK_BUDGET_SECONDS", "0"))

    # PostgreSQL —— 建议为 AI 服务单独建只读角色（最小权限原则），
    # 设置 AI_DB_USER/AI_DB_PASSWORD 后将使用该只读账号，未设置则回退主账号。
    DB_HOST = os.getenv("DB_HOST")
    DB_PORT = int(os.getenv("DB_PORT", "5432"))
    DB_NAME = os.getenv("DB_NAME")
    DB_USER = os.getenv("AI_DB_USER") or os.getenv("DB_USER")
    DB_PASSWORD = os.getenv("AI_DB_PASSWORD") or os.getenv("DB_PASSWORD")
    # 连接池上限：AI 服务并发低，限制连接数避免与主服务争抢 PG max_connections
    DB_MAX_CONN = int(os.getenv("AI_DB_MAX_CONN", "3"))
    DB_POOL_WAIT_SECONDS = float(os.getenv("AI_DB_POOL_WAIT_SECONDS", "1.5"))
    DB_STATEMENT_TIMEOUT_MS = int(os.getenv("AI_DB_STATEMENT_TIMEOUT_MS", "5000"))
    AI_CHAT_TIMEOUT_SECONDS = float(os.getenv("AI_CHAT_TIMEOUT_SECONDS", "90"))
    AI_CHAT_MAX_CONCURRENCY = int(os.getenv("AI_CHAT_MAX_CONCURRENCY", "4"))
    AI_RERANK_MAX_CHARS = int(os.getenv("AI_RERANK_MAX_CHARS", "24000"))
    AI_INTERNAL_SERVICE_KEY = os.getenv("AI_INTERNAL_SERVICE_KEY", "")
    # 零结果诊断：额外跑一次聚合查询，把库里客观事实带进"没找到"的说明里。
    # 离线评测 / 压测场景可关闭，避免额外 DB 往返。
    AI_EMPTY_DIAGNOSTICS = os.getenv("AI_EMPTY_DIAGNOSTICS", "1").strip().lower() not in (
        "0", "false", "no", "off",
    )

    # L5: 日志级别可配
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

    def validate(self) -> None:
        """启动自检：必填配置缺失时终止进程，避免「启动假成功，首请求才失败」。"""
        violations = []

        if not self.LLM_API_URL:
            violations.append("LLM_API_URL 未配置")
        if not self.LLM_API_KEY:
            violations.append("LLM_API_KEY 未配置")
        if not self.LLM_MODEL:
            violations.append("LLM_MODEL 未配置")
        if not self.DB_HOST:
            violations.append("DB_HOST 未配置")
        if not self.DB_NAME:
            violations.append("DB_NAME 未配置")
        if not self.DB_USER:
            violations.append("DB_USER / AI_DB_USER 未配置")
        if not self.DB_PASSWORD:
            violations.append("DB_PASSWORD / AI_DB_PASSWORD 未配置")
        if self.AI_CHAT_MAX_CONCURRENCY < 1:
            violations.append(f"AI_CHAT_MAX_CONCURRENCY 必须 >= 1，当前: {self.AI_CHAT_MAX_CONCURRENCY}")
        if self.DB_MAX_CONN < 1:
            violations.append(f"AI_DB_MAX_CONN 必须 >= 1，当前: {self.DB_MAX_CONN}")
        if not 4000 <= self.AI_RERANK_MAX_CHARS <= 64000:
            violations.append("AI_RERANK_MAX_CHARS 必须在 4000-64000 之间")
        if not math.isfinite(self.AI_CHAT_TIMEOUT_SECONDS) or self.AI_CHAT_TIMEOUT_SECONDS <= 0:
            violations.append("AI_CHAT_TIMEOUT_SECONDS 必须为有限正数")
        if not math.isfinite(self.LLM_FALLBACK_BUDGET_SECONDS):
            violations.append("LLM_FALLBACK_BUDGET_SECONDS 必须为有限数值")
        if self.LOG_LEVEL not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            violations.append(f"LOG_LEVEL 非法: {self.LOG_LEVEL}")

        if violations:
            sys.stderr.write(
                "[FATAL] ai-agent 配置校验失败：\n  - "
                + "\n  - ".join(violations)
                + "\n请检查 .env 或环境变量后重新启动\n"
            )
            sys.exit(1)


settings = Settings()
