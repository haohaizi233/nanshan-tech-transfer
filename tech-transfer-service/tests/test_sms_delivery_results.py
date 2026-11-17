"""Task processing results are distinct from HTTP acceptance and delivery."""

from unittest.mock import MagicMock, patch

import pytest

from modules.security import sms_gateway as g
from modules.security.provider import ProviderError

CTX = g.SendContext("internal-test", None, "request-test")


@pytest.mark.parametrize(
    "reason,unknown,outcome",
    [
        ("insufficient_balance", False, "PROVIDER_REJECTED"),
        ("network_timeout", True, "PROVIDER_UNKNOWN"),
    ],
)
def test_provider_failure_propagates_in_internal_result(reason, unknown, outcome):
    error = ProviderError("safe", outcome_unknown=unknown)
    error.reason_code = reason
    error.provider_status = 499 if not unknown else None
    error.request_attempted = True
    with patch.object(g, "start_sms_recovery", side_effect=error):
        result = g.run_recovery_task("unused", "sms", "task-test", CTX)
    assert result.outcome == outcome
    assert result.failure_reason == reason
    assert result.outcome_unknown is unknown


def test_unexpected_error_does_not_log_sensitive_exception(caplog):
    with patch.object(g, "start_sms_recovery", side_effect=RuntimeError("secretOTP=123456 private-key")):
        result = g.run_recovery_task("unused", "sms", "task-test", CTX)
    assert result.outcome == "INTERNAL_ERROR"
    assert "private-key" not in caplog.text and "123456" not in caplog.text
    assert caplog.records[-1].exception_type == "RuntimeError"


def test_ineligible_task_is_not_marked_completed():
    expected = g.DeliveryTaskResult(
        task_id="task-test", outcome="INELIGIBLE", failure_stage="eligibility", failure_reason="account_not_found"
    )
    with patch.object(g, "start_sms_recovery", return_value=expected):
        assert g.run_recovery_task("unused", "sms", "task-test", CTX).outcome == "INELIGIBLE"


def test_queue_uses_execution_result_not_unconditional_finished():
    cur = MagicMock()
    cur.fetchone.return_value = {
        "payload": {"account": "unused", "channel": "sms", "ip": "ip", "device_id": None, "request_id": "request-test"}
    }
    result = g.DeliveryTaskResult(
        task_id="task-test",
        outcome="PROVIDER_UNKNOWN",
        failure_stage="provider",
        failure_reason="network_timeout",
        outcome_unknown=True,
        provider_called=True,
    )
    with patch.object(g, "get_cursor") as gc, patch.object(g, "run_recovery_task", return_value=result):
        gc.return_value.__enter__.return_value = cur
        assert g.run_queued_recovery_task("task-test")
    updates = [c for c in cur.execute.call_args_list if "outcome=" in c.args[0]]
    assert updates
    assert updates[0].args[1][0] == "unknown"


def test_request_unavailable_distinguished_from_rate_limit():
    from core.errors import BizError
    from modules.security.sms_risk import DecisionAction, RiskDecision

    with patch.object(g, "_engine") as e, patch.object(g, "_audit"):
        e.return_value.check_request.return_value = RiskDecision(DecisionAction.DENY, "sms.redis.unavailable")
        with pytest.raises(BizError) as error:
            g.request_gate(CTX, "unused")
    assert error.value.http_status == 503
