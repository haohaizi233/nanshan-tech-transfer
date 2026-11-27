"""AI 评估报告 SSE 流式总线（进程内 pub/sub + Redis List/PubSub 跨进程传输 + 迟到订阅回放）。

设计约定：
- 一切调用 best-effort：总线异常绝不打断评估主流程；
- 终态后增量直接丢弃，且终态不可逆；
- 若传入 execution_id，旧执行者（过期租约/版本号）产生的事件将被围栏拦截；
- 当配置了 `AI_STREAM_REDIS_URL` 或 `settings.REDIS_ENABLED=True` 且 Redis 可用时，
  通过 Redis List（`RPUSH` + `LTRIM` 有界 512 + TTL 600s）+ `PUBLISH`/`SUBSCRIBE`
  支持独立 Worker 与 API 进程实时互通（兼容 Redis 3.x ~ 7.x）；
- Redis 不可用或未启用时自动回退至进程内总线 + DB 轮询兜底。
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import queue
import threading
import time
from typing import Any

logger = logging.getLogger("nanshan.ai.eval_stream")

CHANNEL_TTL_SECONDS = 10 * 60
MAX_CHANNELS = 256
_SUB_QUEUE_MAX = 512
_REDIS_LIST_MAXLEN = 512
_TERMINAL_STATUSES = ("succeeded", "failed")


def _list_key(task_id: int) -> str:
    return f"ai:eval:events:{task_id}"


def _meta_key(task_id: int) -> str:
    return f"ai:eval:meta:{task_id}"


def _pubsub_channel(task_id: int) -> str:
    return f"ai:eval:notify:{task_id}"


def _get_redis() -> Any | None:
    """获取 Redis 客户端（未启用或不可达时返回 None，自动回退进程内/DB 模式）。"""
    url = os.getenv("AI_STREAM_REDIS_URL", "").strip()
    if not url:
        try:
            from config import settings

            if not getattr(settings, "REDIS_ENABLED", False):
                return None
            url = str(getattr(settings, "REDIS_URL", "") or "").strip()
        except Exception:
            return None
    if not url:
        return None
    try:
        import redis

        return redis.Redis.from_url(
            url, protocol=2, decode_responses=True, socket_connect_timeout=1.0, socket_timeout=2.0
        )
    except Exception:
        return None


class _Channel:
    __slots__ = ("execution_id", "subs", "terminal", "text", "updated_at")

    def __init__(self) -> None:
        self.text = ""
        self.terminal: str | None = None
        self.execution_id: str | None = None
        self.subs: list[queue.Queue] = []
        self.updated_at = time.monotonic()


class Subscription:
    """一个 SSE 订阅者：快照 + 增量队列/Redis List 游标。用完必须 close()。"""

    def __init__(
        self,
        task_id: int,
        q: queue.Queue,
        snapshot: str,
        *,
        redis_client: Any = None,
        pubsub: Any = None,
        redis_offset: int = 0,
    ) -> None:
        self._task_id = task_id
        self._q = q
        self._text = snapshot
        self._closed = False
        self._redis = redis_client
        self._pubsub = pubsub
        self._redis_offset = redis_offset

    @property
    def text(self) -> str:
        """订阅时刻的已生成全文快照（此后的增量走 get()）。"""
        return self._text

    def _drain_redis_list(self) -> None:
        if self._redis is None:
            return
        items = self._redis.lrange(_list_key(self._task_id), self._redis_offset, -1)
        if not items:
            return
        self._redis_offset += len(items)
        for raw in items:
            try:
                ev = json.loads(raw)
            except Exception:
                continue
            if isinstance(ev, dict) and ev.get("type") in ("content_delta", "terminal"):
                with contextlib.suppress(queue.Full):
                    self._q.put_nowait(ev)

    def get(self, timeout: float = 0.5) -> dict | None:
        """取下一个事件；超时返回 None。"""
        if self._closed:
            return None
        try:
            return self._q.get_nowait()
        except queue.Empty:
            pass

        if self._redis is not None:
            try:
                self._drain_redis_list()
                try:
                    return self._q.get_nowait()
                except queue.Empty:
                    pass
                if self._pubsub is not None:
                    self._pubsub.get_message(ignore_subscribe_messages=True, timeout=max(0.05, timeout))
                    self._drain_redis_list()
                    try:
                        return self._q.get_nowait()
                    except queue.Empty:
                        return None
                return None
            except Exception:
                self._redis = None

        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                self._pubsub.close()
            self._pubsub = None
        with _lock:
            ch = _channels.get(self._task_id)
            if ch is not None and self._q in ch.subs:
                ch.subs.remove(self._q)


_lock = threading.Lock()
_channels: dict[int, _Channel] = {}


def _gc_locked() -> None:
    now = time.monotonic()
    stale = [
        task_id
        for task_id, ch in _channels.items()
        if now - ch.updated_at > CHANNEL_TTL_SECONDS and (ch.terminal is not None or not ch.subs)
    ]
    for task_id in stale:
        _channels.pop(task_id, None)
    overflow = len(_channels) - MAX_CHANNELS
    if overflow > 0:
        oldest = sorted(_channels, key=lambda t: _channels[t].updated_at)[:overflow]
        for task_id in oldest:
            _channels.pop(task_id, None)


def _broadcast(ch: _Channel, event: dict) -> None:
    for q in list(ch.subs):
        try:
            q.put_nowait(event)
        except queue.Full:
            logger.warning("ai eval stream subscriber queue full, frame dropped")


def _valid(task_id) -> bool:
    return isinstance(task_id, int) and task_id > 0


def _redis_allows_execution(r: Any, task_id: int, execution_id: str | None) -> bool:
    meta = r.hgetall(_meta_key(task_id)) or {}
    if meta.get("terminal"):
        return False
    current_exec = meta.get("execution_id")
    return not (execution_id and current_exec and current_exec != execution_id)


def open(task_id: int, execution_id: str | None = None) -> bool:
    """评估开始时打开频道（幂等；终态不可重置）。"""
    if not _valid(task_id):
        return False
    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        if ch.terminal is None and execution_id:
            ch.execution_id = execution_id
        ch.updated_at = time.monotonic()
        _gc_locked()

    r = _get_redis()
    if r is not None:
        try:
            mk = _meta_key(task_id)
            meta = r.hgetall(mk) or {}
            if not meta.get("terminal") and execution_id:
                r.hset(mk, "execution_id", execution_id)
            r.expire(mk, CHANNEL_TTL_SECONDS)
            r.expire(_list_key(task_id), CHANNEL_TTL_SECONDS)
        except Exception:
            logger.debug("redis open skipped task=%s", task_id)
    return True


def push_delta(task_id: int, delta: str, execution_id: str | None = None) -> bool:
    """广播一段新增报告文字（LLM 增量）。"""
    if not _valid(task_id) or not delta:
        return False

    r = _get_redis()
    if r is not None:
        try:
            if not _redis_allows_execution(r, task_id, execution_id):
                return False
            mk = _meta_key(task_id)
            lk = _list_key(task_id)
            payload = json.dumps({"type": "content_delta", "text": delta}, ensure_ascii=False)
            pipe = r.pipeline()
            pipe.rpush(lk, payload)
            pipe.ltrim(lk, -_REDIS_LIST_MAXLEN, -1)
            pipe.expire(mk, CHANNEL_TTL_SECONDS)
            pipe.expire(lk, CHANNEL_TTL_SECONDS)
            pipe.publish(_pubsub_channel(task_id), "1")
            pipe.execute()
        except Exception:
            logger.debug("redis push_delta fallback task=%s", task_id)

    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        if ch.terminal is not None:
            return False
        if execution_id and ch.execution_id and ch.execution_id != execution_id:
            return False
        ch.text += delta
        ch.updated_at = time.monotonic()
        _broadcast(ch, {"type": "content_delta", "text": delta})
        _gc_locked()
    return True


def finish(task_id: int, status: str, execution_id: str | None = None) -> bool:
    """落终态信号（succeeded/failed）。终态不可逆。"""
    if not _valid(task_id) or status not in _TERMINAL_STATUSES:
        return False

    r = _get_redis()
    if r is not None:
        try:
            if not _redis_allows_execution(r, task_id, execution_id):
                return False
            mk = _meta_key(task_id)
            lk = _list_key(task_id)
            payload = json.dumps({"type": "terminal", "status": status}, ensure_ascii=False)
            pipe = r.pipeline()
            pipe.hset(mk, "terminal", status)
            pipe.rpush(lk, payload)
            pipe.ltrim(lk, -_REDIS_LIST_MAXLEN, -1)
            pipe.expire(mk, CHANNEL_TTL_SECONDS)
            pipe.expire(lk, CHANNEL_TTL_SECONDS)
            pipe.publish(_pubsub_channel(task_id), "1")
            pipe.execute()
        except Exception:
            logger.debug("redis finish fallback task=%s", task_id)

    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        if ch.terminal is not None:
            return False
        if execution_id and ch.execution_id and ch.execution_id != execution_id:
            return False
        ch.terminal = status
        ch.updated_at = time.monotonic()
        _broadcast(ch, {"type": "terminal", "status": status})
        _gc_locked()
    return True


def subscribe(task_id: int) -> Subscription:
    """订阅指定任务的流式事件（支持跨进程 Redis List 快照回放 + Pub/Sub 增量订阅）。"""
    if not _valid(task_id):
        raise ValueError("task_id must be a positive int")
    q: queue.Queue = queue.Queue(maxsize=_SUB_QUEUE_MAX)

    r = _get_redis()
    if r is not None:
        try:
            ps = r.pubsub(ignore_subscribe_messages=True)
            ps.subscribe(_pubsub_channel(task_id))
            entries = r.lrange(_list_key(task_id), 0, -1)
            parts: list[str] = []
            terminal: str | None = None
            for raw in entries:
                with contextlib.suppress(Exception):
                    ev = json.loads(raw)
                    if ev.get("type") == "content_delta":
                        parts.append(ev.get("text") or "")
                    elif ev.get("type") == "terminal":
                        terminal = ev.get("status")
            if terminal is not None:
                with contextlib.suppress(queue.Full):
                    q.put_nowait({"type": "terminal", "status": terminal})
            return Subscription(task_id, q, "".join(parts), redis_client=r, pubsub=ps, redis_offset=len(entries))
        except Exception:
            logger.debug("redis subscribe fallback task=%s", task_id)

    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        snapshot = ch.text
        terminal = ch.terminal
        ch.subs.append(q)
        ch.updated_at = time.monotonic()
    if terminal is not None:
        with contextlib.suppress(queue.Full):
            q.put_nowait({"type": "terminal", "status": terminal})
    return Subscription(task_id, q, snapshot)


def clear(task_id: int | None = None) -> None:
    """清空频道（仅测试/运维用途）。"""
    with _lock:
        if task_id is None:
            _channels.clear()
        else:
            _channels.pop(task_id, None)
    r = _get_redis()
    if r is not None and task_id is not None:
        with contextlib.suppress(Exception):
            r.delete(_list_key(task_id), _meta_key(task_id))
