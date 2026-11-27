"""P3-5 AI 评估 SSE 跨进程双进程集成测试（Process A Worker + Process B SSE 订阅端）。"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest

from modules.ai import eval_stream

REDIS_URL = os.getenv("AI_STREAM_REDIS_URL") or os.getenv("SMS_TEST_REDIS_URL") or "redis://127.0.0.1:6379/15"


def _redis_reachable(url: str) -> bool:
    try:
        import redis

        client = redis.Redis.from_url(url, decode_responses=True, socket_connect_timeout=1.0)
        return bool(client.ping())
    except Exception:
        return False


@pytest.mark.skipif(not _redis_reachable(REDIS_URL), reason="需要本地 Redis 运行")
def test_cross_process_sse_delivery_reconnect_and_execution_fencing(monkeypatch):
    """P3-A21/A22/A23: 真实子进程生产者 -> Redis Streams -> 主进程订阅者实时增量、断线重连与终态围栏。"""
    monkeypatch.setenv("AI_STREAM_REDIS_URL", REDIS_URL)
    task_id = 990042
    eval_stream.clear(task_id)

    # 先由订阅端建立订阅，再启动独立子进程（模拟独立 AI Worker 进程）推送增量与终态
    sub = eval_stream.subscribe(task_id)
    assert sub.text == ""

    producer_code = (
        "import time\n"
        "from modules.ai import eval_stream\n"
        f"tid = {task_id}\n"
        "eval_stream.open(tid, execution_id='exec-2')\n"
        "time.sleep(0.05)\n"
        "assert eval_stream.push_delta(tid, '第一段', execution_id='exec-2') is True\n"
        "assert eval_stream.push_delta(tid, '第二段', execution_id='exec-2') is True\n"
        "# 旧执行者 exec-1 迟到增量必须被拦截\n"
        "assert eval_stream.push_delta(tid, '脏数据', execution_id='exec-1') is False\n"
        "assert eval_stream.finish(tid, 'succeeded', execution_id='exec-2') is True\n"
        "# 终态不可逆，后续增量与重复终态均丢弃\n"
        "assert eval_stream.push_delta(tid, '终态后', execution_id='exec-2') is False\n"
        "assert eval_stream.finish(tid, 'failed', execution_id='exec-1') is False\n"
    )
    env = dict(os.environ)
    env["AI_STREAM_REDIS_URL"] = REDIS_URL
    proc = subprocess.Popen([sys.executable, "-c", producer_code], env=env)

    received: list[dict] = []
    deadline = time.monotonic() + 5.0
    try:
        while time.monotonic() < deadline:
            ev = sub.get(timeout=0.5)
            if ev is None:
                continue
            received.append(ev)
            if ev.get("type") == "terminal":
                break
    finally:
        sub.close()
        rc = proc.wait(timeout=5)
    assert rc == 0

    deltas = [e["text"] for e in received if e["type"] == "content_delta"]
    assert "".join(deltas) == "第一段第二段"
    assert received[-1] == {"type": "terminal", "status": "succeeded"}

    # P3-A22: 模拟前端断线重连 / 页面刷新后重新订阅，应拿到完整 snapshot 与 terminal
    sub2 = eval_stream.subscribe(task_id)
    try:
        assert sub2.text == "第一段第二段"
        term = sub2.get(timeout=0.5)
        assert term == {"type": "terminal", "status": "succeeded"}
    finally:
        sub2.close()
        eval_stream.clear(task_id)


def test_eval_stream_falls_back_gracefully_when_redis_unavailable(monkeypatch):
    """Redis 不可达时自动降级到进程内总线且不抛异常。"""
    monkeypatch.setenv("AI_STREAM_REDIS_URL", "redis://127.0.0.1:6399/0")
    task_id = 990043
    eval_stream.clear(task_id)
    assert eval_stream.open(task_id, execution_id="exec-1") is True
    sub = eval_stream.subscribe(task_id)
    try:
        assert eval_stream.push_delta(task_id, "离线降级片段", execution_id="exec-1") is True
        assert eval_stream.finish(task_id, "succeeded", execution_id="exec-1") is True
        ev1 = sub.get(timeout=0.5)
        ev2 = sub.get(timeout=0.5)
        assert ev1 == {"type": "content_delta", "text": "离线降级片段"}
        assert ev2 == {"type": "terminal", "status": "succeeded"}
    finally:
        sub.close()
        eval_stream.clear(task_id)
