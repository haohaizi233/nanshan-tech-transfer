import asyncio
import hmac
import json
import queue
import time
from threading import Event

from fastapi import HTTPException
from starlette.responses import StreamingResponse

from app.config import settings


HEARTBEAT_SECONDS = 5.0
MAX_EVENT_BYTES = 64 * 1024
MAX_RESULT_BYTES = 1024 * 1024
MAX_STREAM_BYTES = 2 * 1024 * 1024


def authorize_internal(supplied):
    configured = settings.AI_INTERNAL_SERVICE_KEY
    if not configured:
        raise HTTPException(status_code=503, detail={"reason": "internal_key_not_configured"})
    if not supplied or not hmac.compare_digest(supplied.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(status_code=401, detail={"reason": "unauthorized"})


def prepare_stream(body, request, *, slots, executor, run, timeout_seconds):
    authorize_internal(request.headers.get("X-AI-Service-Key"))
    if not slots.acquire(blocking=False):
        raise HTTPException(status_code=503, detail={"reason": "overloaded"})
    events = queue.Queue(maxsize=32)
    stopped = Event()
    execution_id = body.executionId
    deadline_at = time.monotonic() + timeout_seconds
    sequence = [0]

    def publish(event):
        if stopped.is_set():
            return
        event["executionId"] = execution_id
        try:
            events.put_nowait(event)
        except queue.Full:
            stopped.set()

    def observer(stage):
        sequence[0] += 1
        publish({"type": "stage", "stage": stage, "sequence": sequence[0]})

    def execute():
        try:
            result = run(body, execution_id, deadline_at, observer)
            if time.monotonic() >= deadline_at:
                raise TimeoutError()
            final = {"type": "result", "executionId": execution_id, "result": result.model_dump(exclude_none=True)}
            encoded = (json.dumps(final, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
            if len(encoded) > MAX_EVENT_BYTES:
                observer("failed")
                publish({"type": "error", "reason": "stream_limit"})
            else:
                observer("succeeded")
                publish(final)
        except Exception as exc:
            observer("failed")
            reason = "timeout" if isinstance(exc, TimeoutError) else "execution_failed"
            publish({"type": "error", "reason": reason})

    try:
        worker = executor.submit(execute)
    except BaseException:
        slots.release()
        raise
    worker.add_done_callback(lambda completed: slots.release())

    async def stream():
        total = 0
        last_output = time.monotonic()
        try:
            while True:
                now = time.monotonic()
                if now >= deadline_at:
                    event = {"type": "error", "executionId": execution_id, "reason": "timeout"}
                else:
                    try:
                        event = events.get_nowait()
                    except queue.Empty:
                        if stopped.is_set():
                            event = {"type": "error", "executionId": execution_id, "reason": "stream_overflow"}
                        elif now - last_output >= HEARTBEAT_SECONDS:
                            event = {"type": "heartbeat", "executionId": execution_id}
                        else:
                            await asyncio.sleep(min(0.05, max(0.001, deadline_at - now)))
                            continue
                try:
                    line = (json.dumps(event, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
                    result_size = len(json.dumps(event.get("result"), ensure_ascii=False).encode("utf-8")) if event["type"] == "result" else 0
                    if len(line) > MAX_EVENT_BYTES or result_size > MAX_RESULT_BYTES or total + len(line) > MAX_STREAM_BYTES - 256:
                        raise ValueError("stream_limit")
                except (TypeError, ValueError):
                    event = {"type": "error", "executionId": execution_id, "reason": "stream_limit"}
                    line = (json.dumps(event) + "\n").encode("utf-8")
                total += len(line)
                last_output = time.monotonic()
                yield line
                if event["type"] in ("result", "error"):
                    break
        finally:
            stopped.set()
            if not worker.running() and not worker.done():
                worker.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
