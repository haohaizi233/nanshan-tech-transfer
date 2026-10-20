"""Single-attempt private Agent stream transport and durable run executor."""

import json
import socket
import threading
import time
import urllib.request
from contextlib import suppress
from datetime import UTC, datetime

from config import settings
from modules.ai import chat_runs
from modules.ai.chat_context import validate_query_plan

EVENT_BYTES = 64 * 1024
RESULT_BYTES = 1024 * 1024
STREAM_BYTES = 2 * 1024 * 1024
STAGES = ("context", "routing", "retrieving", "reranking", "formatting", "succeeded", "failed")


class StreamError(Exception):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        return None


def private_opener():
    return urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())


def validate_result(result):
    if not isinstance(result, dict) or type(result.get("success")) is not bool:
        raise StreamError("invalid result")
    if result["success"] is not True:
        raise StreamError("unsuccessful result")
    if not isinstance(result.get("intent"), str) or not isinstance(result.get("message"), str):
        raise StreamError("invalid result text")
    cards = result.get("data")
    if not isinstance(cards, list) or len(cards) > 10:
        raise StreamError("invalid result cards")
    for card in cards:
        if (
            not isinstance(card, dict)
            or card.get("card_type") not in ("achievement", "demand")
            or type(card.get("id")) is not int
            or card["id"] < 1
        ):
            raise StreamError("invalid card locator")
    plan = result.get("queryPlan")
    if plan is not None:
        try:
            validate_query_plan(plan)
        except ValueError as exc:
            raise StreamError("invalid query plan") from exc
    if len(json.dumps(result, ensure_ascii=False).encode()) > RESULT_BYTES:
        raise StreamError("result limit")
    return result


def consume_stream(stream, execution_id, deadline, on_stage, clock=time.monotonic):
    total = 0
    terminal = None
    previous_sequence = 0
    while True:
        if clock() >= deadline:
            raise StreamError("execution deadline")
        raw = stream.readline(EVENT_BYTES + 1)
        if clock() >= deadline:
            raise StreamError("execution deadline")
        if not raw:
            break
        total += len(raw)
        if len(raw) > EVENT_BYTES or total > STREAM_BYTES or not raw.endswith(b"\n"):
            raise StreamError("stream limit")
        try:
            event = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise StreamError("invalid event JSON") from exc
        if not isinstance(event, dict) or event.get("executionId") != execution_id:
            raise StreamError("execution mismatch")
        if terminal is not None:
            raise StreamError("event after terminal")
        kind = event.get("type")
        if kind == "heartbeat":
            continue
        if kind == "stage":
            stage, sequence = event.get("stage"), event.get("sequence")
            if stage not in STAGES or type(sequence) is not int or sequence <= previous_sequence:
                raise StreamError("invalid stage")
            previous_sequence = sequence
            if stage in ("succeeded", "failed"):
                continue
            if on_stage(stage, sequence) is False:
                raise StreamError("execution ownership lost")
        elif kind == "result":
            terminal = validate_result(event.get("result"))
        elif kind == "error":
            raise StreamError("agent error")
        else:
            raise StreamError("invalid event type")
    if terminal is None:
        raise StreamError("stream ended without result")
    return terminal


def post_agent(url, service_key, payload, budget, on_stage):
    deadline = time.monotonic() + max(0.01, budget)
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode(),
        headers={
            "Content-Type": "application/json",
            "Accept": "application/x-ndjson",
            "X-AI-Service-Key": service_key,
            "X-AI-Timeout-Seconds": str(max(0.01, budget - 0.1)),
        },
        method="POST",
    )
    opened = private_opener().open(request, timeout=max(0.01, deadline - time.monotonic()))
    with opened as response:
        connection_socket = getattr(getattr(getattr(response, "fp", None), "raw", None), "_sock", None)

        def interrupt_read():
            if connection_socket is not None:
                with suppress(OSError):
                    connection_socket.shutdown(socket.SHUT_RDWR)

        timer = threading.Timer(max(0.01, deadline - time.monotonic()), interrupt_read)
        timer.daemon = True
        timer.start()
        try:
            return consume_stream(response, payload["executionId"], deadline, on_stage)
        finally:
            timer.cancel()


def execute_run(run):
    stop = threading.Event()
    lost = threading.Event()

    def renew():
        while not stop.wait(settings.AI_CHAT_RENEW_SECONDS):
            try:
                if not chat_runs.renew_run(run):
                    lost.set()
                    return
            except Exception:
                lost.set()
                return

    thread = threading.Thread(target=renew, daemon=True)
    thread.start()
    try:
        remaining = (run["execution_deadline"] - datetime.now(UTC)).total_seconds()
        if remaining <= 0 or lost.is_set():
            return "failed"
        payload = {
            "message": run["user_message"],
            "exclude_owner_user_id": run["user_id"],
            "executionId": run["execution_id"],
            "context": run["context_snapshot"],
        }
        result = post_agent(
            settings.AI_CHAT_STREAM_URL,
            settings.AI_INTERNAL_SERVICE_KEY,
            payload,
            remaining,
            lambda stage, sequence: not lost.is_set() and chat_runs.update_stage(run, stage, sequence),
        )
        if lost.is_set():
            return "ownership_lost"
        if not chat_runs.finish_run(run, result=result):
            return "ownership_lost"
        persisted = chat_runs.get_run(run["user_id"], run["turn_id"])
        return persisted["status"] if persisted else "ownership_lost"
    except Exception:
        chat_runs.finish_run(run, error="本轮执行已中断，结果未知，请重新发起提问")
        return "failed"
    finally:
        stop.set()
        thread.join(timeout=1)
