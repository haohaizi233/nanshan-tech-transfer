"""AI 评估报告 SSE 流式总线（进程内 pub/sub + 迟到订阅回放）。

背景：评估由后台线程执行（eval_executor / worker），前端经 SSE 端点
（GET /ai/evaluation-tasks/{id}/stream）要像 ChatGPT 一样实时看到报告文字
逐字生成。总线解耦生产者（LLM 执行线程）与消费者（SSE 请求线程）：

1. 实时增量：provider 每收到一个 LLM token 就 push_delta，广播给所有订阅者，
   SSE 端点转成 content_delta 帧推给前端（打字机效果）。
2. 迟到订阅回放：前端可能在生成到一半才打开 SSE，订阅时先拿到 snapshot
   （截至当前已生成全文），之后才是增量 —— 不丢字、不重字。
   快照与订阅在同一次锁内完成，快照与增量之间无空窗。
3. 终态收尾：finish(succeeded/failed) 广播 terminal 事件，SSE 端点据此
   查库组装最终结构化结果（done 帧）后关闭连接。

设计约定：
- 一切调用 best-effort：总线异常绝不打断评估主流程（调用方仍包 try/except）；
- 终态后增量直接丢弃（与 progress.set_stage 的 running 守卫语义一致）；
- 频道带 TTL 与数量上限，任务终态/无订阅超过 TTL 自动回收，不泄漏内存；
- 仅进程内有效：独立 worker 进程执行时总线无事件，SSE 端点靠 DB 巡检
  （progress_stage / 终态）收敛，前端再降级轮询 —— 三层兜底。

事件形状（SSE data 帧的 payload）：
- {"type": "content_delta", "text": "<增量>"}
- {"type": "terminal", "status": "succeeded" | "failed"}   # 结果体由端点查库组装
"""
from __future__ import annotations

import logging
import queue
import threading
import time

logger = logging.getLogger("nanshan.ai.eval_stream")

# 频道保留时长（秒）：终态/无订阅超过该时长自动回收（断线重连窗口 10 分钟）。
CHANNEL_TTL_SECONDS = 10 * 60
# 频道数量上限：防异常调用把内存打爆；超限按最旧淘汰。
MAX_CHANNELS = 256
# 单订阅事件队列上限：消费者卡死时丢弃新事件（best-effort），不阻塞生产者。
_SUB_QUEUE_MAX = 512

_TERMINAL_STATUSES = ("succeeded", "failed")


class _Channel:
    __slots__ = ("text", "terminal", "subs", "updated_at")

    def __init__(self) -> None:
        self.text = ""            # 已生成全文（供迟到订阅快照回放）
        self.terminal: str | None = None  # "succeeded" | "failed" | None
        self.subs: list[queue.Queue] = []
        self.updated_at = time.monotonic()


class Subscription:
    """一个 SSE 订阅者：快照 + 增量队列。用完必须 close()。"""

    def __init__(self, task_id: int, q: queue.Queue, snapshot: str) -> None:
        self._task_id = task_id
        self._q = q
        self._text = snapshot
        self._closed = False

    @property
    def text(self) -> str:
        """订阅时刻的已生成全文快照（此后的增量走 get()）。"""
        return self._text

    def get(self, timeout: float = 0.5) -> dict | None:
        """取下一个事件；超时返回 None。"""
        if self._closed:
            return None
        try:
            return self._q.get(timeout=timeout)
        except queue.Empty:
            return None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        with _lock:
            ch = _channels.get(self._task_id)
            if ch is not None and self._q in ch.subs:
                ch.subs.remove(self._q)


_lock = threading.Lock()
_channels: dict[int, _Channel] = {}


def _gc_locked() -> None:
    """回收过期频道（调用方需持锁）。"""
    now = time.monotonic()
    stale = [
        task_id for task_id, ch in _channels.items()
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
            # 消费者跟不上：丢帧不阻塞生产者（前端靠快照/轮询补齐）
            logger.warning("ai eval stream subscriber queue full, frame dropped")


def _valid(task_id) -> bool:
    return isinstance(task_id, int) and task_id > 0


def open(task_id: int) -> bool:
    """评估开始时打开频道（幂等；同一 taskId 重复 open 不重置已有内容）。"""
    if not _valid(task_id):
        return False
    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        ch.updated_at = time.monotonic()
        _gc_locked()
    return True


def push_delta(task_id: int, delta: str) -> bool:
    """广播一段新增报告文字（LLM 增量）。返回是否有订阅者收到。

    best-effort：参数非法/频道已终态直接丢弃返回 False，绝不抛异常。
    """
    if not _valid(task_id) or not delta:
        return False
    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        if ch.terminal is not None:
            return False  # 终态后的迟到增量丢弃，不污染回放
        ch.text += delta
        ch.updated_at = time.monotonic()
        event = {"type": "content_delta", "text": delta}
        _broadcast(ch, event)
        _gc_locked()
    return True


def finish(task_id: int, status: str) -> bool:
    """落终态信号（succeeded/failed）。结果体由 SSE 端点查库组装。"""
    if not _valid(task_id) or status not in _TERMINAL_STATUSES:
        return False
    with _lock:
        ch = _channels.get(task_id)
        if ch is None:
            ch = _Channel()
            _channels[task_id] = ch
        if ch.terminal is not None:
            return False  # 终态幂等：重复收尾不重发
        ch.terminal = status
        ch.updated_at = time.monotonic()
        _broadcast(ch, {"type": "terminal", "status": status})
        _gc_locked()
    return True


def subscribe(task_id: int) -> Subscription:
    """订阅指定任务的流式事件。

    订阅瞬间在锁内拍快照并挂入订阅列表：快照文本经 Subscription.text 返回，
    此后增量/终态经队列按序到达 —— 快照与增量之间无空窗。
    频道已终态时（迟到订阅）队列里直接预置 terminal 事件。
    """
    if not _valid(task_id):
        raise ValueError("task_id must be a positive int")
    q: queue.Queue = queue.Queue(maxsize=_SUB_QUEUE_MAX)
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
        try:
            q.put_nowait({"type": "terminal", "status": terminal})
        except queue.Full:
            pass
    return Subscription(task_id, q, snapshot)


def clear(task_id: int | None = None) -> None:
    """清空频道（仅测试/运维用途）。"""
    with _lock:
        if task_id is None:
            _channels.clear()
        else:
            _channels.pop(task_id, None)
