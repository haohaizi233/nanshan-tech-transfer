from unittest.mock import MagicMock, patch

import pytest

from modules.security import sms_gateway as gateway


def test_phone_normalization():
    assert gateway.normalize_phone("+86 138-0013-8000") == "13800138000"
    for phone in ["12345678901", "１３８００１３８０００", "13800138000;13900139000"]:
        with pytest.raises(Exception):
            gateway.normalize_phone(phone)


def test_unknown_account_never_calls_provider_or_reserves_send_quota():
    engine = MagicMock()
    with patch.object(gateway, "get_cursor") as gc, patch.object(gateway, "get_sms_provider") as provider:
        gc.return_value.__enter__.return_value.fetchall.return_value = []
        gateway.start_sms_recovery("unknown", "test-id", gateway.SendContext("127.0.0.1", None, "r"), engine)
        provider.assert_not_called()
        engine.reserve.assert_not_called()


def test_duplicate_account_match_never_sends():
    engine = MagicMock()
    with patch.object(gateway, "get_cursor") as gc, patch.object(gateway, "get_sms_provider") as provider:
        gc.return_value.__enter__.return_value.fetchall.return_value = [{"user_id": 1}, {"user_id": 2}]
        gateway.start_sms_recovery("same", "test-id", gateway.SendContext("127.0.0.1", None, "r"), engine)
        provider.assert_not_called()


def test_public_response_does_not_include_binding_state():
    a = gateway.recovery_response("id", "sms")
    assert a["challengeId"] == "id"
    assert a["maskedDestination"] is None
    assert a["sent"] is True
    assert "如果" in a["message"]
