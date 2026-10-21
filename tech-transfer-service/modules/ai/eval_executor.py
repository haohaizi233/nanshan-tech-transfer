"""进程内 AI 评估任务异步执行器 + 容灾清理。

背景：POST /ai/evaluation-tasks 创建任务后若无 worker 认领，任务会永远停在
queued（前端"排队中"）。本模块把执行接入服务进程本身：

1. 异步执行：任务创建后 submit(task_id) 入队，后台 daemon 线程自动执行，
   状态流转 queued → running → succeeded / failed。认领走 CAS
   （UPDATE ... WHERE status='queued'），独立 worker 同时运行也不会重复执行。
2. 超时保护：单任务执行超时 EXECUTION_TIMEOUT_SECONDS（60s）——LLM 调用
   自带略短的 HTTP 超时；仍有看门狗兜底把任务标记 failed。迟到的写回由
   SQL 条件（status='running'）丢弃，不会覆盖终态。
3. 容灾清理（防止永久卡在"排队中"）：
   - queued 超过 STALE_QUEUED_SECONDS（5 分钟）→ failed（reap_stale_queued）；
   - running 超过认领时声明的 timeout_at → failed（进程崩溃/重启遗留任务）；
   - 后台清理线程定时巡检 + 任务创建/查询路径上的机会式清理双保险；
   - GET 轮询对未过期的 queued 任务补偿提交（进程重启后遗留任务可被重新唤起）。
"""
from __future__ import annotations

import logging
import queue
import threading
import time

from db import get_cursor
from modules.ai import provider, worker

logger = logging.getLogger("nanshan.ai.eval_executor")

# 单任务执行超时（秒）：含 LLM 调用；看门狗与 LLM HTTP 超时共用该预算。
EXECUTION_TIMEOUT_SECONDS = 60
# queued 超过该时长（秒）视为卡死（worker 未认领/进程重启丢失），自动清理。
STALE_QUEUED_SECONDS = 5 * 60
# 后台清理线程巡检间隔（秒）。
REAPER_INTERVAL_SECONDS = 60
# 进程内并发执行上限：避免同时打满上游 LLM 连接/线程。
MAX_WORKERS = 2
_QUEUE_MAX = 128

STALE_QUEUED_REASON = "排队超时，任务未执行，请重新发起评估"
TIMEOUT_REASON = "任务执行超时，请重新发起评估"

_queue: queue.Queue = queue.Queue(maxsize=_QUEUE_MAX)
_start_lock = threading.Lock()
_started = False


def submit(task_id: int) -> bool:
    """把任务投入进程内执行队列（非阻塞）。返回 False 表示队列已满/未启用。

    幂等安全：同一 taskId 重复入队由 claim CAS 兜底，只有一个执行者能认领。
    """
    if not isinstance(task_id, int) or task_id <= 0:
        return False
    ensure_started()
    try:
        _queue.put_nowait(task_id)
        return True
    except queue.Full:
        logger.warning("ai evaluation executor queue full, task=%s left queued", task_id)
        return False


def ensure_started() -> None:
    """惰性启动后台执行线程与清理线程（daemon，随进程退出）。"""
    global _started
    if _started:
        return
    with _start_lock:
        if _started:
            return
        for index in range(MAX_WORKERS):
            threading.Thread(
                target=_worker_loop, name=f"ai-eval-executor-{index}", daemon=True,
            ).start()
        threading.Thread(target=_reap_loop, name="ai-eval-reaper", daemon=True).start()
        _started = True


def _worker_loop() -> None:
    while True:
        task_id = _queue.get()
        try:
            _execute(task_id)
        except Exception:
            logger.exception("ai evaluation executor crashed task=%s", task_id)
        finally:
            _queue.task_done()


def _reap_loop() -> None:
    while True:
        time.sleep(REAPER_INTERVAL_SECONDS)
        try:
            reaped = reap_dead_tasks()
            if reaped:
                logger.info("ai evaluation reaper marked %s dead task(s) failed", reaped)
        except Exception:
            logger.exception("ai evaluation reaper failed")


def _claim(task_id: int) -> dict | None:
    """CAS 认领指定 queued 任务：只有把 status 从 queued 改成 running 的一方执行。"""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'running',
                started_at = NOW(),
                timeout_at = NOW() + (%s || ' seconds')::interval,
                version = version + 1
            WHERE id = %s AND task_type = 'evaluation' AND status = 'queued'
            RETURNING id, task_type, target_id, input_snapshot, version
            """,
            (str(EXECUTION_TIMEOUT_SECONDS), task_id),
        )
        row = cur.fetchone()
    return dict(row) if row else None


def _execute(task_id: int) -> None:
    """认领并执行一条评估任务：成功/失败/超时都有确定的终态，绝不留在 queued。"""
    task = _claim(task_id)
    if not task:
        # 已被独立 worker 认领 / 已终态 / 重复入队，静默跳过。
        return
    done = threading.Event()

    def _on_timeout() -> None:
        if done.is_set():
            return
        logger.warning(
            "ai evaluation task=%s timed out after %ss", task_id, EXECUTION_TIMEOUT_SECONDS,
        )
        try:
            worker._fail(task_id, TIMEOUT_REASON)
        except Exception:
            logger.exception("ai evaluation timeout mark failed task=%s", task_id)

    # 看门狗：LLM 调用卡死时把任务标记 failed；迟到写回由 SQL 条件丢弃。
    timer = threading.Timer(EXECUTION_TIMEOUT_SECONDS, _on_timeout)
    timer.daemon = True
    timer.start()
    try:
        if not provider.configured():
            worker._fail(task_id, "AI 评估服务未配置")
            return
        worker._run_evaluation(task, timeout=EXECUTION_TIMEOUT_SECONDS - 5)
        logger.info("ai evaluation task=%s succeeded", task_id)
    except provider.AiProviderError as exc:
        logger.warning("ai evaluation provider error task=%s err=%s", task_id, exc)
        worker._fail(task_id, worker._desensitize_reason(str(exc)))
    except Exception as exc:
        logger.exception("ai evaluation crashed task=%s", task_id)
        worker._fail(task_id, worker._desensitize_reason(f"{type(exc).__name__}: {exc}"))
    finally:
        done.set()
        timer.cancel()


def reap_stale_queued() -> int:
    """queued 超过 STALE_QUEUED_SECONDS 的评估任务 → failed。

    只清理 evaluation 任务：match 任务按 P0-2 约定保持 queued 等外部 worker。
    幂等且安全，可重复调用。
    """
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'failed',
                fail_reason = %s,
                finished_at = NOW(),
                version = version + 1
            WHERE task_type = 'evaluation' AND status = 'queued'
              AND created_at < NOW() - (%s || ' seconds')::interval
            """,
            (STALE_QUEUED_REASON, str(STALE_QUEUED_SECONDS)),
        )
        return int(cur.rowcount or 0)


def reap_expired_running() -> int:
    """running 任务超过认领时声明的 timeout_at → failed（进程崩溃/重启遗留）。"""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE ai_task
            SET status = 'failed',
                fail_reason = %s,
                finished_at = NOW(),
                version = version + 1
            WHERE task_type = 'evaluation' AND status = 'running'
              AND timeout_at IS NOT NULL AND timeout_at < NOW()
            """,
            (TIMEOUT_REASON,),
        )
        return int(cur.rowcount or 0)


def reap_dead_tasks() -> int:
    """一次性清理所有卡死任务（stale queued + 过期 running），返回清理条数。"""
    return reap_stale_queued() + reap_expired_running()
