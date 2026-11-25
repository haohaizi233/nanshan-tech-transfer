"""Email Challenge 生命周期、v1/v2 HMAC 绑定、状态机约束、DATA 未知保守性与事务回滚测试。"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError
from modules.security.delivery_models import DeliveryStageError, ProviderError
from modules.security.email_gateway import _send_email, start_email_binding
from modules.security.provider import MockEmailProvider, reset_providers_for_test
from modules.security.risk_engine import DecisionAction, RiskDecision
from modules.security.service import (
    _challenge_transaction,
    _fingerprint,
    _hmac_code,
    _hmac_code_v2,
    _verify_challenge_code_match,
    _verify_destination_fingerprint,
    verify_recovery_challenge,
)
from modules.security.sms_gateway import SendContext
from modules.security.state_machine import (
    assert_challenge_transition,
    assert_send_state_transition,
    can_verify_challenge,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_providers_for_test(None, None)
    yield
    reset_providers_for_test(None, None)


def test_challenge_state_machine_and_unknown_verification_policy():
    assert can_verify_challenge("pending", "accepted") is True
    assert can_verify_challenge("pending", "delivered") is True
    assert can_verify_challenge("pending", "unknown") is True
    assert can_verify_challenge("pending", None) is True

    assert can_verify_challenge("pending", "rejected") is False
    assert can_verify_challenge("pending", "delivery_failed") is False
    assert can_verify_challenge("pending", "bounced") is False
    assert can_verify_challenge("consumed", "accepted") is False

    with pytest.raises(BizError):
        assert_challenge_transition("consumed", "pending")
    with pytest.raises(BizError):
        assert_challenge_transition("expired", "verified")
    with pytest.raises(ValueError):
        assert_send_state_transition("rejected", "accepted")


def test_hmac_v2_v1_key_rotation_and_leading_zero_preservation():
    from config import settings as _settings

    cid = "ch-hmac-1"
    # v2 上下文绑定摘要保留前导零且绑定 purpose / channel / contact
    with patch.object(_settings, "SECURITY_OTP_HMAC_SECRET", "otp-secret-v2"):
        digest_v2 = _hmac_code_v2(cid, "password_recovery", "email_otp", "Alice@Example.com", "000419")
        assert digest_v2.startswith("v2$")
        row_v2 = {"id": cid, "purpose": "password_recovery", "channel": "email_otp", "code_hash": digest_v2}
        assert _verify_challenge_code_match(row_v2, "alice@example.com", "000419") is True
        assert _verify_challenge_code_match(row_v2, "alice@example.com", "419") is False
        # 跨用途或跨渠道防复用
        assert _verify_challenge_code_match({**row_v2, "purpose": "bind_email"}, "alice@example.com", "000419") is False
        assert _verify_challenge_code_match({**row_v2, "channel": "email_link"}, "alice@example.com", "000419") is False
        assert _verify_challenge_code_match(row_v2, "other@example.com", "000419") is False

        # v1 旧密钥（JWT_SECRET）签发的未过期存量挑战仍可在轮换窗口内兼容核验
        legacy_raw = f"{cid}:password_recovery:alice@example.com:009876"
        legacy_v1 = hmac.new(
            _settings.JWT_SECRET.encode("utf-8"), legacy_raw.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        assert (
            _verify_challenge_code_match(
                {"id": cid, "purpose": "password_recovery", "channel": "email_otp", "code_hash": legacy_v1},
                "alice@example.com",
                "009876",
            )
            is True
        )
        # 新签发默认摘要则严格绑定 SECURITY_OTP_HMAC_SECRET
        digest_v1_new = _hmac_code(cid, "password_recovery", "alice@example.com", "009876")
        assert digest_v1_new != legacy_v1

    with patch.object(_settings, "SECURITY_CONTACT_HMAC_SECRET", "contact-blind-secret"):
        legacy_fp = hmac.new(_settings.JWT_SECRET.encode("utf-8"), b"alice@example.com", hashlib.sha256).hexdigest()
        assert _verify_destination_fingerprint({"destination_fingerprint": legacy_fp}, "alice@example.com") is True
        assert (
            _verify_destination_fingerprint(
                {"destination_fingerprint": _fingerprint("alice@example.com")}, "alice@example.com"
            )
            is True
        )


def test_email_binding_provider_failure_closes_challenge_without_dangling_pending():
    from config import settings as _settings
    from core.jwt_utils import sign_access_token
    from modules.security.step_up import _target_fingerprint, session_fingerprint_from_request

    em = MockEmailProvider()
    em.should_fail = True
    reset_providers_for_test(email=em)

    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {sign_access_token(42, 'U042', ['user'], 1)}"}
    sess_fp = session_fingerprint_from_request(req, 42)
    target_fp = _target_fingerprint("newuser@example.com", purpose="bind_email")

    eng = MagicMock()
    eng.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
    cur = MagicMock()
    cur.fetchone.side_effect = [
        {"id": 42},  # active user check
        None,  # duplicate verified email check
        None,  # existing verified email check (first bind)
        {
            "id": "sg-bind-42",
            "user_id": 42,
            "purpose": "bind_email",
            "method": "password",
            "session_fingerprint": sess_fp,
            "session_id": None,
            "target_fingerprint": target_fp,
            "status": "active",
            "expires_at": time.time() + 180,
        },  # bind_email step_up_grant validation
        {"id": 42},  # FOR UPDATE app_user in _send_email
        {"status": "pending_send", "send_state": "sending"},  # RETURNING in reserved->sending CAS
        {"status": "failed", "send_state": "rejected"},  # RETURNING in sending->rejected CAS
    ]

    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch("modules.security.email_gateway.get_cursor") as mock_gc,
        patch("modules.security.email_gateway.audit_record"),
    ):
        mock_gc.return_value.__enter__.return_value = cur
        with pytest.raises(DeliveryStageError) as exc_info:
            start_email_binding(
                42,
                "newuser@example.com",
                SendContext("10.0.0.1", "dev-1", "req-bind-fail"),
                step_up_grant="su-bind-42",
                session_fingerprint=sess_fp,
                engine=eng,
            )
        assert exc_info.value.stage == "provider"
        assert exc_info.value.reason_code == "provider_rejected"

    # 验证最终 CAS UPDATE 将 sending 转为 rejected / failed（绝不残留 pending）
    update_calls = [
        c.args
        for c in cur.execute.call_args_list
        if "UPDATE auth_challenge" in str(c.args[0]) and "SET send_state" in str(c.args[0])
    ]
    assert len(update_calls) == 2
    assert update_calls[0][1][0] == "sending"
    sql_params = update_calls[-1][1]
    assert sql_params[0] == "rejected"
    assert sql_params[5] == "rejected"
    eng.transition.assert_called_once()
    assert eng.transition.call_args.args[1] == "rejected"


def test_email_unknown_outcome_keeps_single_otp_verifiable_and_avoids_resend():
    from config import settings as _settings

    em = MockEmailProvider()
    em.failure_error = ProviderError(
        "邮件发送结果待核对",
        reason_code="PROVIDER_OUTCOME_UNKNOWN",
        outcome_unknown=True,
        retryable=False,
        request_attempted=True,
    )
    reset_providers_for_test(email=em)

    eng = MagicMock()
    eng.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 88, "status": "pending", "send_state": "unknown"}

    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch("modules.security.email_gateway.get_cursor") as mock_gc,
        patch("modules.security.email_gateway.audit_record"),
        patch("modules.security.email_gateway.secrets.randbelow", return_value=412),
    ):
        mock_gc.return_value.__enter__.return_value = cur
        with pytest.raises(DeliveryStageError) as exc_info:
            _send_email(
                88,
                "u88@example.com",
                "password_recovery",
                "email_otp",
                "ch-unk-88",
                SendContext("10.0.0.1", "dev-1", "req-unk"),
                engine=eng,
            )
        assert exc_info.value.outcome_unknown is True
        assert exc_info.value.reason_code == "PROVIDER_OUTCOME_UNKNOWN"

    update_calls = [
        c.args
        for c in cur.execute.call_args_list
        if "UPDATE auth_challenge" in str(c.args[0]) and "SET send_state" in str(c.args[0])
    ]
    assert len(update_calls) == 2
    assert update_calls[0][1][0] == "sending"
    assert update_calls[-1][1][0] == "unknown"
    assert (
        update_calls[-1][1][5] == "unknown"
    )  # CASE turns pending_send -> pending when send_state in (accepted, unknown)
    eng.transition.assert_called_once_with("ch-unk-88", "unknown")

    # 若邮件实际送达，原 OTP 000412 仍可在 send_state='unknown' 下完成一次性核验
    code_hash = _hmac_code_v2("ch-unk-88", "password_recovery", "email_otp", "u88@example.com", "000412")
    with patch("modules.security.service.get_cursor") as mock_gc:
        v_cur = MagicMock()
        v_cur.fetchone.side_effect = [
            {"user_id": 88},
            {
                "id": "ch-unk-88",
                "user_id": 88,
                "purpose": "password_recovery",
                "channel": "email_otp",
                "destination_fingerprint": _fingerprint("u88@example.com"),
                "code_hash": code_hash,
                "status": "pending",
                "send_state": "unknown",
                "attempt_count": 0,
                "max_attempts": 5,
                "expires_at": time.time() + 300,
            },
            {"normalized_value": "u88@example.com"},
        ]
        mock_gc.return_value.__enter__.return_value = v_cur
        grant_res = verify_recovery_challenge("ch-unk-88", "000412")
        assert grant_res["recoveryGrant"]


def test_challenge_transaction_commits_attempt_error_but_rolls_back_business_writes():
    events: list[str] = []

    class _FakeCtxMgr:
        def __init__(self, cur):
            self._cur = cur

        def __enter__(self):
            events.append("enter")
            return self._cur

        def __exit__(self, exc_type, exc, tb):
            events.append("rollback" if exc_type is not None else "commit")
            return False

    fake_cur = MagicMock()

    with patch("modules.security.service.get_cursor", return_value=_FakeCtxMgr(fake_cur)):
        with pytest.raises(BizError):
            with _challenge_transaction() as (_cur, _tx):
                raise BizError("TT_COMMON_40001", "验证码错误", 400)
        assert events == ["enter", "commit"]

        events.clear()
        with pytest.raises(BizError):
            with _challenge_transaction() as (_cur, tx):
                tx["business_writes_started"] = True
                raise BizError("TT_COMMON_40903", "冲突回滚", 409)
        assert events == ["enter", "rollback"]


def test_email_link_token_is_256_bit_and_uses_hash_fragment():
    from config import settings as _settings

    em = MockEmailProvider()
    reset_providers_for_test(email=em)
    eng = MagicMock()
    eng.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
    cur = MagicMock()
    cur.fetchone.return_value = {"id": 91}

    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch("modules.security.email_gateway.get_cursor") as mock_gc,
        patch("modules.security.email_gateway.audit_record"),
    ):
        mock_gc.return_value.__enter__.return_value = cur
        _send_email(
            91,
            "linkuser@example.com",
            "password_recovery",
            "email_link",
            "ch-link-91",
            SendContext("10.0.0.1", "dev-1", "req-link"),
            engine=eng,
        )

    assert len(em.sent_emails) == 1
    reset_url = em.sent_emails[0]["reset_url"]
    assert "#challengeId=ch-link-91&token=" in reset_url
    assert "?challengeId=" not in reset_url
    token = reset_url.split("&token=")[1]
    assert len(token) >= 43  # >=256-bit urlsafe token

    # 验证入库摘要为 JSON 规范化的 v2 HMAC，绝非明文 token
    insert_args = next(c.args for c in cur.execute.call_args_list if "INSERT INTO auth_challenge" in str(c.args[0]))[1]
    assert token not in json.dumps(insert_args, default=str)
    assert str(insert_args[6]).startswith("v2$")
