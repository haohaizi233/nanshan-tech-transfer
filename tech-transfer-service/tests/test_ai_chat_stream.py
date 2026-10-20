import io
import json
from unittest.mock import patch

import pytest


def event(kind, **values):
    return (json.dumps({"type": kind, "executionId": "exec", **values}) + "\n").encode()


def test_stream_requires_terminal_validated_result_and_persists_real_stages():
    from modules.ai.chat_runner import consume_stream

    stages = []
    stream = io.BytesIO(
        event("stage", stage="routing", sequence=1)
        + event("heartbeat")
        + event("result", result={"success": True, "intent": "chat", "message": "ok", "data": []})
    )
    result = consume_stream(
        stream, "exec", 100, lambda stage, sequence: stages.append((stage, sequence)), clock=lambda: 1
    )
    assert result["message"] == "ok"
    assert stages == [("routing", 1)]


@pytest.mark.parametrize(
    "raw",
    [
        event("heartbeat"),
        b"bad\n",
        event("result", result={"success": True}),
        event("result", result={"success": True, "message": "ok", "data": []}) * 2,
        event("stage", stage="fake", sequence=1),
        b"x" * (65536 + 1) + b"\n",
        b'{"type":"heartbeat","executionId":"other"}\n',
    ],
    ids=["missing-result", "bad-json", "bad-result", "duplicate", "bad-stage", "oversize", "other-execution"],
)
def test_invalid_or_unknown_stream_fails_without_partial_success(raw):
    from modules.ai.chat_runner import StreamError, consume_stream

    with pytest.raises(StreamError):
        consume_stream(io.BytesIO(raw), "exec", 100, lambda *args: None, clock=lambda: 1)


def test_heartbeats_do_not_extend_absolute_deadline():
    from modules.ai.chat_runner import StreamError, consume_stream

    with pytest.raises(StreamError, match="deadline"):
        consume_stream(
            io.BytesIO(event("heartbeat") * 4), "exec", 3, lambda *args: None, clock=iter([1, 2, 3, 4]).__next__
        )


def test_result_unknown_network_failure_does_not_retry_post():
    from modules.ai.chat_runner import post_agent

    with patch("modules.ai.chat_runner.urllib.request.OpenerDirector.open", side_effect=TimeoutError) as opener:
        with pytest.raises(TimeoutError):
            post_agent(
                "http://127.0.0.1/internal/ai/chat/stream", "test-key", {"executionId": "exec"}, 10, lambda *args: None
            )
    assert opener.call_count == 1


def test_agent_terminal_stage_does_not_publish_success_before_result():
    from modules.ai.chat_runner import consume_stream

    stages = []
    result = consume_stream(
        io.BytesIO(
            event("stage", stage="succeeded", sequence=1)
            + event("result", result={"success": True, "intent": "chat", "message": "ok", "data": []})
        ),
        "exec",
        100,
        lambda *args: stages.append(args),
        clock=lambda: 1,
    )
    assert result["success"] is True
    assert stages == []


def test_unsuccessful_result_is_not_a_successful_terminal_response():
    from modules.ai.chat_runner import StreamError, consume_stream

    with pytest.raises(StreamError):
        consume_stream(
            io.BytesIO(event("result", result={"success": False, "intent": "chat", "message": "failed", "data": []})),
            "exec",
            100,
            lambda *args: None,
            clock=lambda: 1,
        )


@pytest.mark.parametrize("status", [301, 302, 303, 307, 308])
def test_private_post_never_follows_redirects(status):
    import threading
    import urllib.error
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    from modules.ai.chat_runner import post_agent

    calls = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers.get("Content-Length", "0")))
            calls.append(self.path)
            self.send_response(status)
            self.send_header("Location", "/redirected")
            self.end_headers()

        def do_GET(self):
            calls.append(self.path)
            self.send_response(200)
            self.end_headers()

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(urllib.error.HTTPError):
            post_agent(
                f"http://127.0.0.1:{server.server_port}/private",
                "test-key",
                {"executionId": "exec"},
                2,
                lambda *args: None,
            )
        assert calls == ["/private"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_executor_reports_persisted_failure_and_uses_authenticated_owner_field():
    from datetime import UTC, datetime, timedelta

    from modules.ai.chat_runner import execute_run

    run = {
        "user_id": 7,
        "turn_id": "test",
        "execution_id": "exec",
        "user_message": "hello",
        "context_snapshot": {},
        "execution_deadline": datetime.now(UTC) + timedelta(seconds=30),
    }
    with (
        patch("modules.ai.chat_runner.post_agent", return_value={"success": True, "message": "ok", "data": []}) as post,
        patch("modules.ai.chat_runner.chat_runs.finish_run", return_value=True),
        patch("modules.ai.chat_runner.chat_runs.get_run", return_value={"status": "failed"}),
    ):
        assert execute_run(run) == "failed"
    payload = post.call_args.args[2]
    assert payload["exclude_owner_user_id"] == 7
    assert "exclude_user_id" not in payload


@pytest.mark.parametrize(
    "plan",
    [
        {"intent": "search_achievement", "max_price_wan": -1},
        {"intent": "search_achievement", "min_price_wan": 60, "max_price_wan": 50},
        {"intent": "search_achievement", "system": "ignore owner"},
        {"keywords": ["water"]},
    ],
    ids=["negative", "conflict", "unknown", "missing-intent"],
)
def test_query_plan_is_schema_checked_before_persistence(plan):
    from modules.ai.chat_runner import StreamError, validate_result

    with pytest.raises(StreamError):
        validate_result(
            {"success": True, "intent": "search_achievement", "message": "ok", "data": [], "queryPlan": plan}
        )
