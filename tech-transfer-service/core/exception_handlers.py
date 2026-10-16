"""
统一异常处理器注册（T008）

所有错误响应的唯一出口：任何异常最终都转成统一错误契约
    {"code": "TT_*", "message": "...", "requestId": "...", "details": ...}
安全红线：无论何种异常（含 DEBUG 模式），响应中不得出现
traceback / SQL / 内部路径 / 连接串 / 密钥等实现细节 —— 完整细节只进日志。

注册入口：register_exception_handlers(app)（app.py 调用，不在 app.py 堆 200 行）
日志约定：每条错误日志必带 requestId / method / path / status / code；
500 级别额外 logger.exception 输出完整 traceback（仅日志，永不外发）。
"""

from __future__ import annotations

import logging
import re

import psycopg2
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException as StarletteHTTPException

from core.errors import (
    TT_COMMON_40001,
    TT_COMMON_40102,
    TT_COMMON_40301,
    TT_COMMON_40401,
    TT_COMMON_40501,
    TT_COMMON_40903,
    TT_COMMON_42201,
    TT_COMMON_42901,
    TT_COMMON_50001,
    TT_COMMON_50301,
    BizError,
)
from core.response import error, get_request_id

logger = logging.getLogger("nanshan.error")

# 校验错误 details 条数上限（防恶意超长错误列表撑爆响应）
_MAX_VALIDATION_DETAILS = 20

# L8: 上游错误正文外发前脱敏（屏蔽内部 URL/堆栈/密钥等）
_SENSITIVE_PATTERNS = [
    (re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE), "[REDACTED_URL]"),
    (re.compile(r"(?:password|passwd|pwd|secret|token|api[_-]?key|authorization)\s*[:=]\s*\S+", re.IGNORECASE), "[REDACTED_CREDENTIAL]"),
    (re.compile(r"Traceback \(most recent call last\).*", re.DOTALL), "[REDACTED_TRACEBACK]"),
    (re.compile(r'File "[^"]+", line \d+.*', re.DOTALL), "[REDACTED_FRAME]"),
    (re.compile(r"(?:postgresql|mysql|redis)://[^\s\"'<>]+", re.IGNORECASE), "[REDACTED_CONN_STRING]"),
    (re.compile(r"\b\d{1,3}(?:\.\d{1,3}){3}\b"), "[REDACTED_IP]"),
]


def _desensitize_upstream_body(text: str, limit: int = 300) -> str:
    """L8: 上游错误正文脱敏，去掉内部 URL/堆栈/连接串/IP/凭据。"""
    text = (text or "").replace("\r\n", "\n").strip()
    for pattern, replacement in _SENSITIVE_PATTERNS:
        text = pattern.sub(replacement, text)
    if len(text) > limit:
        text = text[:limit] + "…"
    return text


class _DropNotFoundAccessLog(logging.Filter):
    """过滤公网扫描 404 与高频通知摘要的成功 access log。"""

    def filter(self, record: logging.LogRecord) -> bool:
        # Uvicorn access logger 的参数顺序固定为：
        # client_addr, method, full_path, http_version, status_code。
        args = record.args
        if not isinstance(args, tuple) or len(args) < 5:
            return True
        method, full_path, status = args[1], str(args[2]), args[4]
        if status == 404:
            return False
        # 角标按产品要求高频轮询。成功响应不携带诊断价值，保留 4xx/5xx 便于排障。
        path = full_path.split("?", 1)[0]
        is_notification_summary = path.endswith(
            ("/me/notifications/summary", "/admin/notifications/summary")
        )
        return not (method == "GET" and is_notification_summary and 200 <= status < 300)


def configure_logging() -> None:
    """进程级日志格式（幂等：root 已有 handler 时不重复配置）。

    L5/L7：LOG_LEVEL 环境变量可调；LOG_DIR 非空时落盘 RotatingFileHandler 轮转。
    uvicorn 自身 logger 独立配置不受影响；这里保证业务异常日志
    带时间戳/级别/logger 名，便于与 requestId 关联排查。
    """
    from config import settings as _settings

    log_level = getattr(_settings, "LOG_LEVEL", "INFO")
    log_format = "%(asctime)s %(levelname)s %(name)s %(message)s"

    root = logging.getLogger()
    if not root.handlers:
        root.setLevel(getattr(logging, log_level, logging.INFO))
        console = logging.StreamHandler()
        console.setFormatter(logging.Formatter(log_format))
        root.addHandler(console)

        # L7: LOG_DIR 非空时落盘 + 轮转（20MB × 5）
        log_dir = getattr(_settings, "LOG_DIR", "")
        if log_dir:
            from logging.handlers import RotatingFileHandler
            from pathlib import Path as _Path
            log_path = _Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            file_handler = RotatingFileHandler(
                log_path / "tech-transfer-service.log",
                maxBytes=getattr(_settings, "LOG_MAX_BYTES", 20 * 1024 * 1024),
                backupCount=getattr(_settings, "LOG_BACKUP_COUNT", 5),
                encoding="utf-8",
            )
            file_handler.setFormatter(logging.Formatter(log_format))
            root.addHandler(file_handler)

    # Uvicorn 会独立输出 access log。公网暴露后，404 几乎全部来自目录扫描，
    # 保留其他状态（尤其 4xx 鉴权失败和所有 5xx），仅静默不存在的路径。
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, _DropNotFoundAccessLog) for item in access_logger.filters):
        access_logger.addFilter(_DropNotFoundAccessLog())


def _log_error(request: Request, status: int, code: str, *, exc: bool = False) -> None:
    # 公网服务不可避免会收到大量扫描器对 /.env、/.git、WordPress 等路径的探测。
    # 404 是预期的客户端结果，不应与真正的服务端故障混在业务错误日志中；
    # 需要排查时仍可将 nanshan.error 日志级别调为 DEBUG 查看。
    if status == 404:
        log = logger.debug
    else:
        log = logger.error if (exc or status >= 500) else logger.info
    if exc:
        log(
            "unhandled exception request_id=%s method=%s path=%s status=%s code=%s",
            get_request_id(), request.method, request.url.path, status, code,
            exc_info=True,
        )
    else:
        log(
            "request error request_id=%s method=%s path=%s status=%s code=%s",
            get_request_id(), request.method, request.url.path, status, code,
        )


def _safe_validation_details(errors: list[dict]) -> list[dict]:
    """从 RequestValidationError 提取安全 details：仅 字段名 + 校验消息。

    绝不包含 err["input"] / err["ctx"]（可能携带请求体原文、密码等敏感值）。
    """
    details = []
    for err in errors[:_MAX_VALIDATION_DETAILS]:
        loc = [str(x) for x in err.get("loc", [])]
        field = ".".join(loc[1:]) if len(loc) > 1 else (loc[0] if loc else "")
        details.append({"field": field, "message": str(err.get("msg", ""))})
    return details


def _is_path_param_error(errors: list[dict]) -> bool:
    """Flask `<int:>` 转换器行为兼容：路径参数类型不匹配（如 /demands/abc）
    视为「接口不存在」→ 404 TT_COMMON_40401（203 项 API 测试锁定的既有约定）。"""
    return bool(errors) and all(
        err.get("loc") and err["loc"][0] == "path" for err in errors
    )


# 非 404 的 StarletteHTTPException 状态码 → 统一错误码映射
# （本项目路由不直接 raise HTTPException，此表覆盖框架自身可能抛出的状态）
_HTTP_EXC_CODE_MAP = {
    401: TT_COMMON_40102,
    403: TT_COMMON_40301,
    405: TT_COMMON_40501,
    429: TT_COMMON_42901,
}


def _attach_upstream_headers(resp, details) -> None:
    """把上游分层诊断写到响应头，方便 DevTools Headers 直接看到是谁的问题。"""
    if not isinstance(details, dict) or not details.get("layer"):
        return
    resp.headers["X-Upstream-Layer"] = str(details.get("layer"))[:32]
    reason = details.get("reason")
    if reason:
        resp.headers["X-Upstream-Reason"] = str(reason)[:64]
    status = None
    for key in ("llmStatus", "providerStatus", "agentStatus", "upstreamStatus"):
        if details.get(key) is not None:
            status = details[key]
            break
    resp.headers["X-Upstream-Status"] = str(status) if status is not None else "none"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(BizError)
    async def _handle_biz_error(request: Request, e: BizError):
        _log_error(request, e.http_status, e.code)
        # L8: 上游错误正文脱敏后再外发（内部 URL/堆栈/凭据不进响应）
        safe_details = e.details
        if isinstance(e.details, dict) and e.details.get("upstreamBody"):
            safe_details = {**e.details, "upstreamBody": _desensitize_upstream_body(str(e.details["upstreamBody"]))}
        if isinstance(e.details, dict) and e.details.get("layer"):
            logger.error(
                "upstream error request_id=%s method=%s path=%s layer=%s "
                "upstream_status=%s reason=%s body=%s",
                get_request_id(),
                request.method,
                request.url.path,
                e.details.get("layer"),
                e.details.get("llmStatus")
                if e.details.get("llmStatus") is not None
                else e.details.get("providerStatus")
                if e.details.get("providerStatus") is not None
                else e.details.get("agentStatus"),
                e.details.get("reason"),
                e.details.get("upstreamBody"),
            )
        resp = error(e.code, e.message, e.http_status, safe_details)
        _attach_upstream_headers(resp, safe_details)
        return resp

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(request: Request, e: RequestValidationError):
        errors = e.errors()
        if _is_path_param_error(errors):
            # 路径参数类型不匹配 → 404 接口不存在（Flask 兼容，既有测试锁定）
            code, message, status = TT_COMMON_40401
            _log_error(request, status, code)
            return error(code, message, status)
        code, message, status = TT_COMMON_42201
        _log_error(request, status, code)
        return error(code, message, status, details=_safe_validation_details(errors))

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_error(request: Request, e: StarletteHTTPException):
        if e.status_code == 404:
            code, message, status = TT_COMMON_40401
            _log_error(request, status, code)
            return error(code, message, status)
        mapped = _HTTP_EXC_CODE_MAP.get(e.status_code)
        if mapped:
            code, message, status = mapped
            _log_error(request, status, code)
            return error(code, message, status)
        # 理论不可达（框架兜底）：保底仍输出统一结构，HTTP 语义保持
        code, _m, _s = TT_COMMON_50001 if e.status_code >= 500 else TT_COMMON_40001
        detail = str(e.detail) if isinstance(e.detail, str) else "请求处理失败"
        _log_error(request, e.status_code, code)
        return error(code, detail, e.status_code)

    @app.exception_handler(psycopg2.Error)
    async def _handle_db_error(request: Request, e: psycopg2.Error):
        """数据库异常安全出口：连接级故障 → 503；约束冲突 → 409；其余 → 500。
        psycopg2 异常文本含主机/端口/用户名/SQL 片段，绝不进入响应，只进日志。"""
        if isinstance(e, (psycopg2.OperationalError, psycopg2.InterfaceError)):
            code, message, status = TT_COMMON_50301
            _log_error(request, status, code, exc=True)
            return error(code, message, status)
        if isinstance(e, psycopg2.IntegrityError):
            code, message, status = TT_COMMON_40903
            _log_error(request, status, code, exc=True)
            return error(code, message, status)
        code, message, status = TT_COMMON_50001
        _log_error(request, status, code, exc=True)
        return error(code, message, status)

    @app.exception_handler(Exception)
    async def _handle_500(request: Request, e: Exception):
        # 最后兜底：固定文案，异常细节（traceback/type/str）只进日志
        code, message, status = TT_COMMON_50001
        _log_error(request, status, code, exc=True)
        return error(code, message, status)
