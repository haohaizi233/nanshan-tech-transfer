from threading import BoundedSemaphore
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError
from routes import ai


def test_proxy_does_not_retry_after_the_shared_request_budget_has_expired():
    clock = [0.0]

    def timeout(*args, **kwargs):
        clock[0] += 2.0
        raise TimeoutError("upstream timeout")

    with (
        patch.object(ai.settings, "AI_AGENT_TIMEOUT", 2),
        patch.object(ai.time, "monotonic", side_effect=lambda: clock[0]),
        patch.object(ai.time, "sleep"),
        patch.object(ai, "_AI_CONCURRENCY", BoundedSemaphore(1)),
        patch.object(ai.urllib.request, "urlopen", side_effect=timeout) as request,
    ):
        with pytest.raises(BizError):
            ai._forward_to_agent("找机器视觉成果")
    assert request.call_count == 1


def test_proxy_forwards_the_trace_and_remaining_budget_without_changing_chat_payload():
    response = MagicMock()
    response.__enter__.return_value.read.return_value = b'{"success":true,"data":[]}'
    with (
        patch.object(ai.settings, "AI_AGENT_TIMEOUT", 2),
        patch.object(ai, "get_request_id", return_value="request-test"),
        patch.object(ai.urllib.request, "urlopen", return_value=response) as request,
    ):
        ai._forward_to_agent("query")
    headers = request.call_args.args[0]
    assert headers.get_header("X-request-id") == "request-test"
    assert 0 < float(headers.get_header("X-ai-timeout-seconds")) <= 2
