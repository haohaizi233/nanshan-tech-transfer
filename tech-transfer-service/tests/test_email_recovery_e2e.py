"""FastAPI TestClient 端到端测试：找回密码能力探测、邮箱 OTP/链接重置、Step-up 换绑、安全响应头与日志脱敏。"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from config import settings as _settings
from core import auth_cache
from core.exception_handlers import _DropNotFoundAccessLog
from core.jwt_utils import sign_access_token
from core.password import hash_password
from modules.security.provider import MockEmailProvider, reset_providers_for_test
from modules.security.rate_limiter import limiter
from modules.security.risk_engine import DecisionAction, RiskDecision
from modules.security.service import _fingerprint, _hmac_code_v2

client = TestClient(app, base_url="https://testserver")


@pytest.fixture(autouse=True)
def _e2e_env():
    em = MockEmailProvider()
    reset_providers_for_test(email=em)
    limiter.reset_for_test()
    auth_cache._cache.clear()
    with (
        patch.object(_settings, "REDIS_ENABLED", False),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "SMS_ENABLED", True),
    ):
        yield em
    reset_providers_for_test(None, None)
    limiter.reset_for_test()
    auth_cache._cache.clear()


def test_recovery_capabilities_and_disabled_email_gate(_e2e_env):
    resp_on = client.get("/api/tech-transfer/v1/auth/recovery/capabilities")
    assert resp_on.status_code == 200
    assert resp_on.json()["data"]["emailOtp"] is True
    assert resp_on.json()["data"]["emailLink"] is True

    with patch.object(_settings, "EMAIL_ENABLED", False):
        resp_off = client.get("/api/tech-transfer/v1/auth/recovery/capabilities")
        assert resp_off.status_code == 200
        assert resp_off.json()["data"]["emailOtp"] is False
        assert resp_off.json()["data"]["emailLink"] is False

        resp_start_off = client.post(
            "/api/tech-transfer/v1/auth/recovery/start",
            json={"account": "user@example.com", "channel": "email_otp"},
        )
        assert resp_start_off.status_code == 503
        assert resp_start_off.json()["code"] == "TT_COMMON_50301"


def test_recovery_start_anti_enumeration_and_retry_after_header(_e2e_env):
    # 1. 不存在账号与已确权账号返回结构完全一致，但不存在账号不触发发信
    cur_none = MagicMock()
    cur_none.fetchall.return_value = []
    cur_none.fetchone.return_value = None
    with (
        patch("routes.auth.email_request_gate"),
        patch("modules.security.sms_gateway.get_cursor") as mock_sms_gc,
        patch("modules.security.email_gateway.get_cursor") as mock_em_gc,
        patch("modules.security.email_gateway._engine") as em_eng,
        patch("modules.security.email_gateway.audit_record"),
    ):
        em_eng.return_value.check_request.return_value = RiskDecision(DecisionAction.ALLOW)
        em_eng.return_value.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
        mock_sms_gc.return_value.__enter__.return_value = cur_none
        mock_em_gc.return_value.__enter__.return_value = cur_none
        r_unknown = client.post(
            "/api/tech-transfer/v1/auth/recovery/start",
            json={"account": "missing@example.com", "channel": "email_otp"},
        )
    assert r_unknown.status_code == 200
    assert r_unknown.json()["data"]["sent"] is True
    assert r_unknown.json()["data"]["maskedDestination"] is None
    assert len(_e2e_env.sent_emails) == 0

    # 2. 风控限流触发 429 时必须通过 HTTP Retry-After 响应头传递给客户端
    blocked_eng = MagicMock()
    blocked_eng.check_request.return_value = RiskDecision(DecisionAction.THROTTLE, "email.cooldown", retry_after=47)
    with (
        patch("modules.security.email_gateway._engine", return_value=blocked_eng),
        patch("modules.security.email_gateway.audit_record"),
    ):
        r_429 = client.post(
            "/api/tech-transfer/v1/auth/recovery/start",
            json={"account": "user@example.com", "channel": "email_otp"},
        )
    assert r_429.status_code == 429
    assert r_429.headers.get("Retry-After") == "47"
    assert r_429.json()["details"]["retryAfter"] == 47


def test_recovery_e2e_otp_and_link_complete_and_headers(_e2e_env):
    # 1. 触发 email_otp 找回 -> 核验 -> 完成重置并吊销旧会话
    cur = MagicMock()
    cur.fetchall.return_value = [{"user_id": 301, "normalized_value": "alice@example.com"}]
    cur.fetchone.side_effect = [
        {
            "payload": {
                "account": "alice@example.com",
                "channel": "email_otp",
                "ip": "127.0.0.1",
                "device_id": None,
                "request_id": "req-e2e-1",
            }
        },
        {"id": 301},
    ]
    with (
        patch("routes.auth.email_request_gate"),
        patch("modules.security.sms_gateway.get_cursor") as mock_sms_gc,
        patch("modules.security.email_gateway.get_cursor") as mock_em_gc,
        patch("modules.security.email_gateway._engine") as em_eng,
        patch("modules.security.email_gateway.audit_record"),
        patch("modules.security.email_gateway._verify_email_worker_ownership"),
        patch("modules.security.email_gateway.claim_send_execution_right") as claim_send,
    ):
        em_eng.return_value.check_request.return_value = RiskDecision(DecisionAction.ALLOW)
        em_eng.return_value.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
        claim_send.return_value.outcome = "transitioned"
        mock_sms_gc.return_value.__enter__.return_value = cur
        mock_em_gc.return_value.__enter__.return_value = cur
        r_start = client.post(
            "/api/tech-transfer/v1/auth/recovery/start",
            json={"account": "alice@example.com", "channel": "email_otp"},
        )
    assert r_start.status_code == 200
    cid = r_start.json()["data"]["challengeId"]
    otp = _e2e_env.get_last_code("alice@example.com")
    assert otp is not None and len(otp) == 6

    code_hash = _hmac_code_v2(cid, "password_recovery", "email_otp", "alice@example.com", otp)
    with patch("modules.security.service.get_cursor") as mock_gc:
        vcur = MagicMock()
        vcur.fetchone.side_effect = [
            {"user_id": 301},
            {
                "id": cid,
                "user_id": 301,
                "purpose": "password_recovery",
                "channel": "email_otp",
                "destination_fingerprint": _fingerprint("alice@example.com"),
                "code_hash": code_hash,
                "status": "pending",
                "send_state": "accepted",
                "attempt_count": 0,
                "max_attempts": 5,
                "expires_at": time.time() + 300,
            },
            {"normalized_value": "alice@example.com"},
        ]
        mock_gc.return_value.__enter__.return_value = vcur
        r_verify = client.post("/api/tech-transfer/v1/auth/recovery/verify", json={"challengeId": cid, "code": otp})
    assert r_verify.status_code == 200
    grant = r_verify.json()["data"]["recoveryGrant"]
    assert grant

    with patch("modules.security.service.get_cursor") as mock_gc:
        ccur = MagicMock()
        ccur.fetchall.return_value = [{"id": cid, "status": "verified"}]
        ccur.fetchone.side_effect = [
            {"user_id": 301, "challenge_id": cid},
            {"user_status": "active"},
            {"cred_status": "active", "password_configured": True, "password_hash": hash_password("OldPass!9")},
            {"id": "rg-1", "user_id": 301, "challenge_id": cid, "status": "active", "expires_at": time.time() + 300},
        ]
        mock_gc.return_value.__enter__.return_value = ccur
        r_done = client.post(
            "/api/tech-transfer/v1/auth/recovery/complete",
            json={"recoveryGrant": grant, "newPassword": "NewStrongPassword!9"},
        )
    assert r_done.status_code == 200
    assert r_done.json()["data"]["ok"] is True

    # 2. SPA 重置页响应头防 Referer 与缓存泄露
    r_spa = client.get("/reset-password")
    assert r_spa.headers.get("Referrer-Policy") == "no-referrer"
    assert "no-store" in (r_spa.headers.get("Cache-Control") or "").lower()

    # 3. Uvicorn 访问日志过滤器脱敏 URL 中的 sensitive query parameters
    rec = logging.LogRecord(
        name="uvicorn.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg='%s - "%s %s HTTP/%s" %d',
        args=("127.0.0.1:1234", "GET", "/reset-password?challengeId=c1&token=SECRET_Q_TOK", "1.1", 200),
        exc_info=None,
    )
    assert _DropNotFoundAccessLog().filter(rec) is True
    assert "SECRET_Q_TOK" not in str(rec.args[2])
    assert "token=[REDACTED]" in str(rec.args[2])


def test_me_security_and_step_up_http_endpoints(_e2e_env):
    sid_405 = str(uuid.uuid4())
    token = sign_access_token(405, "U0405", ["user"], 1, sid=sid_405, auth_time=int(time.time()))
    headers = {"Authorization": f"Bearer {token}"}

    with (
        patch("core.middleware._user_is_active", return_value=True),
        patch("core.middleware._user_session_version", return_value=1),
        patch("core.middleware._session_is_active", return_value=True),
        patch("modules.security.service.get_cursor") as mock_gc,
        patch("modules.security.step_up.get_cursor") as mock_su_gc,
    ):
        cur = MagicMock()
        cur.fetchone.return_value = {"password_configured": True, "password_hash": "h", "wechat_openid": None}
        cur.fetchall.side_effect = [
            [
                {
                    "contact_type": "email",
                    "normalized_value": "old405@example.com",
                    "verified_at": datetime(2026, 11, 24, tzinfo=UTC),
                    "verification_method": "email",
                }
            ],
            [],
        ]
        mock_gc.return_value.__enter__.return_value = cur

        cur_su = MagicMock()
        cur_su.fetchone.return_value = {"password_configured": True, "has_password": True, "privileged": False}
        cur_su.fetchall.return_value = [{"contact_type": "email", "verification_method": "email"}]
        mock_su_gc.return_value.__enter__.return_value = cur_su

        r_sec = client.get("/api/tech-transfer/v1/me/security", headers=headers)
    assert r_sec.status_code == 200
    data = r_sec.json()["data"]
    assert data["capabilities"] == {"smsEnabled": True, "emailEnabled": True}
    assert data["stepUpMethods"] == ["password", "old_email_otp"]

    # Step-up verify endpoint
    pwd_hash = hash_password("MyCurrentPass!88")
    with (
        patch("core.middleware._user_is_active", return_value=True),
        patch("core.middleware._user_session_version", return_value=1),
        patch("core.middleware._session_is_active", return_value=True),
        patch("modules.security.service.get_cursor") as mock_gc,
        patch("modules.security.step_up.audit_record"),
    ):
        cur2 = MagicMock()
        cur2.fetchone.side_effect = [
            {
                "user_status": "active",
                "deleted_at": None,
                "session_version": 1,
                "cred_status": "active",
                "password_configured": True,
                "password_hash": pwd_hash,
                "privileged": False,
            },
            {
                "user_status": "active",
                "deleted_at": None,
                "session_version": 1,
                "has_any": True,
                "has_active": True,
                "has_expired": False,
            },
        ]
        mock_gc.return_value.__enter__.return_value = cur2
        r_su = client.post(
            "/api/tech-transfer/v1/me/security/step-up/verify",
            headers=headers,
            json={
                "purpose": "rebind_email",
                "method": "password",
                "currentPassword": "MyCurrentPass!88",
                "targetContact": "new405@example.com",
            },
        )
    assert r_su.status_code == 200
    assert r_su.json()["data"]["stepUpGrant"]
