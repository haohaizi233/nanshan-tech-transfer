"""轻量幂等键存储（进程内，TTL 10 分钟）。

X-Idempotency-Key 在 CORS 中已声明但未强制；这里提供一个简单的进程内
去重层：以 user_id + idempotency_key 为复合键缓存首条响应，TTL 内重复请求
直接回放缓存，不再执行业务逻辑。

约束：
- 进程内实现，多 worker 部署下每进程独立缓存（保守，不会漏放，只会更严）；
- 仅缓存成功响应（HTTP 2xx）；失败响应不缓存，允许客户端重试；
- 不持久化，进程重启即失效（与限流器同生命周期）。
"""
import time
from typing import Any

from fastapi import Request
from fastapi.responses import JSONResponse

_TTL_SECONDS = 10 * 60
_store: dict[tuple[int, str], tuple[float, Any]] = {}
_lock_clean_counter = 0


def _evict_expired() -> None:
    """惰性清理过期项，避免缓存无限增长。"""
    now = time.time()
    expired = [key for key, (ts, _payload) in _store.items() if now - ts > _TTL_SECONDS]
    for key in expired:
        _store.pop(key, None)


def get_cached(user_id: int, idempotency_key: str):
    """返回缓存的 (status_code, body) 或 None。"""
    if not idempotency_key:
        return None
    _evict_expired()
    entry = _store.get((user_id, idempotency_key))
    if not entry:
        return None
    ts, payload = entry
    if time.time() - ts > _TTL_SECONDS:
        _store.pop((user_id, idempotency_key), None)
        return None
    return payload


def cache_response(user_id: int, idempotency_key: str, status_code: int, body: Any) -> None:
    """仅缓存成功响应（2xx）。失败响应不缓存，允许客户端重试。"""
    if not idempotency_key:
        return
    if not (200 <= status_code < 300):
        return
    _evict_expired()
    _store[(user_id, idempotency_key)] = (time.time(), (status_code, body))


def idempotent_create(request: Request, user: dict):
    """FastAPI 依赖：若 X-Idempotency-Key 命中缓存，直接返回缓存的 JSONResponse。

    用法：在 POST 创建端点上以 Depends 注入；返回 None 表示未命中，需继续执行；
    返回 JSONResponse 表示命中，路由应直接 return 该响应。
    """
    key = (request.headers.get("X-Idempotency-Key") or "").strip()
    if not key:
        return None
    user_id = user.get("userId")
    if user_id is None:
        return None
    cached = get_cached(int(user_id), key)
    if cached is None:
        return None
    status_code, body = cached
    resp = JSONResponse(status_code=status_code, content=body)
    resp.headers["Idempotent-Replay"] = "true"
    return resp


def current_key(request: Request) -> str:
    return (request.headers.get("X-Idempotency-Key") or "").strip()
