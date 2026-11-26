"""Regression tests for security boundaries in the existing challenge service."""

import time
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from core.errors import BizError
from core.request_schemas import ContactChallengeRequest, RecoveryStartRequest
from modules.security import service


@pytest.mark.parametrize("phase", ["request", "reserve"])
def test_registration_rate_limit_returns_retry_after(phase, monkeypatch):
    from fastapi.testclient import TestClient

    from app import app
    from config import settings
    from modules.security import registration, sms_gateway
    from modules.security.risk_engine import DecisionAction, RiskDecision

    allow = RiskDecision(DecisionAction.ALLOW, "sms.allow")
    throttle = RiskDecision(DecisionAction.THROTTLE, "sms.phone.cooldown", 42)
    engine = MagicMock()
    engine.check_request.return_value = throttle if phase == "request" else allow
    engine.reserve.return_value = throttle
    monkeypatch.setattr(registration, "_engine", lambda: engine)
    monkeypatch.setattr(sms_gateway, "_engine", lambda: engine)
    monkeypatch.setattr(sms_gateway, "_audit", lambda *args, **kwargs: None)
    monkeypatch.setattr(sms_gateway, "get_sms_provider", lambda: None)
    monkeypatch.setattr(settings, "SMS_ENABLED", True)

    client = TestClient(app, base_url="https://testserver")
    response = client.post("/api/tech-transfer/v1/auth/register/challenge", json={"phone": "13800138000"})
    assert response.status_code == 429
    assert response.headers.get("Retry-After") == "42"
    assert response.json()["details"]["retryAfter"] == 42


def row(**values):
    return dict(
        id="1",
        user_id=11,
        purpose="password_recovery",
        channel="sms",
        destination_fingerprint=service._fingerprint("13800138000"),
        code_hash=service._hmac_code("1", "password_recovery", "13800138000", "123456"),
        status="pending",
        attempt_count=0,
        max_attempts=5,
        expires_at=time.time() + 300,
        **values,
    )


@pytest.mark.parametrize(
    "model,payload",
    [
        (RecoveryStartRequest, {"account": "test", "channel": "sms", "purpose": "login"}),
        (RecoveryStartRequest, {"account": "x" * 129, "channel": "sms"}),
        (ContactChallengeRequest, {"contactType": "phone", "contactValue": "13800138000", "admin": True}),
    ],
)
def test_security_schema_is_strict(model, payload):
    with pytest.raises(ValidationError):
        model(**payload)


def test_expired_recovery_code_is_rejected():
    r = row()
    r["expires_at"] = time.time() - 1
    cur = MagicMock()
    cur.fetchone.side_effect = [{"user_id": 11}, r, {"normalized_value": "13800138000"}]
    with patch.object(service, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        with pytest.raises(BizError):
            service.verify_recovery_challenge("1", "123456")


def test_wrong_attempt_commits_before_error_is_raised():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"user_id": 11}, row(), {"normalized_value": "13800138000"}]
    commits = []

    @contextmanager
    def cursor(commit=False):
        yield cur
        commits.append(commit)

    with patch.object(service, "get_cursor", cursor), pytest.raises(BizError):
        service.verify_recovery_challenge("1", "000000")
    assert commits == [False, True]


def test_bind_rejects_recovery_purpose():
    cur = MagicMock()
    cur.fetchone.side_effect = [{"id": 11}, row()]
    with patch.object(service, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        with pytest.raises(BizError):
            service.verify_and_bind_contact(11, "1", "123456", "13800138000")


def test_expired_recovery_grant_rejected_before_password_write():
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"user_id": 11, "challenge_id": None},
        {"user_status": "active"},
        {"cred_status": "active", "password_configured": True, "password_hash": "old"},
        {"id": "g", "user_id": 11, "status": "active", "expires_at": time.time() - 1},
    ]
    with patch.object(service, "get_cursor") as gc:
        gc.return_value.__enter__.return_value = cur
        with pytest.raises(BizError):
            service.complete_password_recovery("grant", "NewPassword123")
    assert not any("SET password_hash" in str(c.args[0]) for c in cur.execute.call_args_list)
