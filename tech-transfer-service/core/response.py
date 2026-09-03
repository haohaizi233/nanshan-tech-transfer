"""
统一响应封装（FastAPI 版）

路由返回 dict（success），由 FastAPI 序列化为 JSON；
error 供异常处理器构造 JSONResponse。
requestId 通过 contextvar 传递：中间件写入 → 线程池中的同步端点可读
（anyio.to_thread 会复制当前上下文到工作线程）。
"""

from contextvars import ContextVar
import uuid

from fastapi.responses import JSONResponse

_request_id_var: ContextVar[str] = ContextVar("request_id", default="")


def set_request_id(request_id: str):
    _request_id_var.set(request_id)


def get_request_id() -> str:
    return _request_id_var.get() or str(uuid.uuid4())


def success(data=None, message: str = "ok") -> dict:
    return {
        "code": 0,
        "message": message,
        "data": data,
        "requestId": get_request_id(),
    }


def error(code: str, message: str, http_status: int = 400, details=None) -> JSONResponse:
    body = {
        "code": code,
        "message": message,
        "requestId": get_request_id(),
    }
    if details is not None:
        body["details"] = details
    return JSONResponse(status_code=http_status, content=body)
