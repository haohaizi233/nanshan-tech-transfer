"""鉴权查询短 TTL 缓存（M8）。

背景：每个鉴权请求原本要 2-3 次 DB 往返（app_user.status、user_role、
organization_membership……），「我的」页并发十余查询时连接池易顶满。

方案：以 30 秒短 TTL 缓存鉴权查询结果，写路径（角色授予/撤销、机构管理员
变更）主动失效对应用户的缓存，保证变更即时生效；即使漏调失效，最坏 30 秒
后自然过期，与 review 建议一致。

内存护栏：条目数硬上限 + 过期清扫，防止 key 无限增长。
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

TTL_SECONDS = 30.0
_MAX_ENTRIES = 4096

_lock = threading.Lock()
_cache: dict[tuple, tuple[float, Any]] = {}


def _sweep_locked(now: float) -> None:
    expired = [key for key, (ts, _v) in _cache.items() if now - ts > TTL_SECONDS]
    for key in expired:
        _cache.pop(key, None)
    while len(_cache) >= _MAX_ENTRIES:
        _cache.pop(next(iter(_cache)), None)


def cached(key: tuple, fn: Callable[[], Any]) -> Any:
    """返回缓存值；未命中则调用 fn() 并缓存（fn 返回 None 也缓存，防穿透）。"""
    now = time.monotonic()
    with _lock:
        entry = _cache.get(key)
        if entry is not None:
            ts, value = entry
            if now - ts <= TTL_SECONDS:
                return value
            _cache.pop(key, None)
    value = fn()
    with _lock:
        _sweep_locked(time.monotonic())
        _cache[key] = (time.monotonic(), value)
    return value


def invalidate_user(user_id: int | None) -> None:
    """写路径调用：立即丢弃该用户的全部鉴权缓存。"""
    if user_id is None:
        return
    with _lock:
        for key in [k for k in _cache if k[1] == user_id]:
            _cache.pop(key, None)


def clear() -> None:
    """测试/运维用：清空全部缓存。"""
    with _lock:
        _cache.clear()
