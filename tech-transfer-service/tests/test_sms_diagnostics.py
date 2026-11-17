from unittest.mock import MagicMock, patch

from modules.security import sms_diagnostics as d


def test_provider_check_never_sends():
    with patch("urllib.request.urlopen", side_effect=AssertionError("network forbidden")):
        result = d.provider_check()
    assert result["contract_ok"] and result["real_send_attempted"] is False


def test_diagnosis_distinguishes_accepted_from_delivery_failure():
    row = {
        "id": "task-id",
        "request_id": "request-id",
        "state": "completed",
        "outcome": "DELIVERY_FAILED",
        "failure_stage": "delivery",
        "failure_reason": "sendcloud_delivery_failed",
        "provider_status": 590,
        "risk_rule_id": None,
        "provider_ids": ["message$" + "138" + "00138000"],
        "outcome_unknown": False,
        "retryable": False,
        "provider_called": True,
        "send_state": "delivery_failed",
        "delivery_status_code": 590,
        "delivery_reason_code": "4121",
    }
    cur = MagicMock()
    cur.fetchall.return_value = [row]
    with patch.object(d, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        result = d.diagnose(challenge_id="task-id")
    import json

    text = json.dumps(result)
    assert "138" + "00138000" not in text
    assert result["tasks"][0]["provider_request_accepted"] is True
    assert result["tasks"][0]["final_delivery"] == "failed"
    assert result["tasks"][0]["provider_status"] == 590
    assert result["tasks"][0]["delivery_reason_code"] == "4121"


def test_config_check_sanitizes_dependency_errors():
    with (
        patch.object(d, "get_cursor", side_effect=RuntimeError("private-password")),
        patch.object(d, "redis_client", side_effect=RuntimeError("private-redis-url")),
    ):
        result = d.config_check()
    import json

    assert "private-" not in json.dumps(result)
    assert result["postgres"]["connected"] is False


def test_diagnose_requires_a_selector():
    import pytest

    with pytest.raises(ValueError):
        d.diagnose()


def test_live_test_requires_matching_explicit_authorized_phone():
    cur = MagicMock()
    cur.fetchall.return_value = [{"normalized_value": "138" + "00138000"}]
    with patch.object(d, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        assert d.authorized_live_target("test-account", "138" + "00138000")
        assert not d.authorized_live_target("test-account", "139" + "00139000")


def test_stalled_worker_is_reported_as_unknown_not_unsent():
    cur = MagicMock()
    cur.fetchall.return_value = [
        {
            "id": "task-test",
            "state": "processing",
            "stale_processing": True,
            "send_state": None,
            "provider_called": False,
        }
    ]
    with patch.object(d, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        row = d.diagnose(challenge_id="task-test")["tasks"][0]
    assert row["failure_stage"] == "worker" and row["outcome_unknown"]
    assert row["provider_called"] is None
