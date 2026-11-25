"""安全邮箱绑定与换绑（Step-up 二次身份认证、冲突处理、授权吊销与通知）测试。"""

from __future__ import annotations

import time
import uuid
from unittest.mock import MagicMock, patch

import psycopg2
import pytest

from core.errors import BizError
from core.jwt_utils import sign_access_token
from core.password import hash_password
from modules.security.provider import MockEmailProvider, reset_providers_for_test
from modules.security.service import _fingerprint, _hmac_code_v2, verify_and_bind_contact
from modules.security.step_up import (
    _target_fingerprint,
    get_available_step_up_methods,
    issue_step_up_grant,
    session_context_from_request,
    session_fingerprint_from_request,
    validate_step_up_grant,
)


@pytest.fixture(autouse=True)
def _reset():
    reset_providers_for_test(None, None)
    yield
    reset_providers_for_test(None, None)


def _make_request_with_jwt(user_id: int, *, sid: str | None = None, version: int = 1):
    sid_val = sid or str(uuid.uuid4())
    token = sign_access_token(user_id, "U001", ["user"], version, sid=sid_val, auth_time=int(time.time()))
    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {token}"}
    return req, session_fingerprint_from_request(req, user_id)


def test_available_step_up_methods_by_account_type():
    from config import settings as _settings

    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "SMS_ENABLED", True),
        patch("modules.security.step_up.get_cursor") as mock_gc,
    ):
        cur = MagicMock()
        cur.fetchone.return_value = {"password_configured": True, "has_password": True, "privileged": False}
        cur.fetchall.return_value = [{"contact_type": "email", "verification_method": "email"}]
        mock_gc.return_value.__enter__.return_value = cur
        methods = get_available_step_up_methods(10, auth_time=int(time.time()), has_sid=True)
    assert methods == ["password", "old_email_otp"]

    # 无密码（仅微信）账号近期可信登录（含 auth_time + sid）可使用 recent_auth
    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "SMS_ENABLED", False),
        patch("modules.security.step_up.get_cursor") as mock_gc,
    ):
        cur2 = MagicMock()
        cur2.fetchone.return_value = {"password_configured": False, "has_password": False, "privileged": False}
        cur2.fetchall.return_value = []
        mock_gc.return_value.__enter__.return_value = cur2
        methods_wc = get_available_step_up_methods(11, auth_time=int(time.time()) - 10, has_sid=True)
    assert "recent_auth" in methods_wc


def test_step_up_grant_issuance_and_validation_guards():
    sid1 = str(uuid.uuid4())
    sid2 = str(uuid.uuid4())
    req1, sess1 = _make_request_with_jwt(50, sid=sid1, version=1)
    req2, sess2 = _make_request_with_jwt(50, sid=sid2, version=2)
    sctx1 = session_context_from_request(req1, 50)
    sctx2 = session_context_from_request(req2, 50)
    assert sess1 != sess2
    pwd_hash = hash_password("CurrentStrongPass!9")

    cur = MagicMock()
    cur.fetchone.side_effect = [
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
    with (
        patch("modules.security.service.get_cursor") as mock_gc,
        patch("modules.security.step_up.audit_record"),
    ):
        mock_gc.return_value.__enter__.return_value = cur
        issued = issue_step_up_grant(
            50,
            purpose="rebind_email",
            method="password",
            session_fingerprint=sess1,
            session_ctx=sctx1,
            current_password="CurrentStrongPass!9",
            target_contact="new@example.com",
        )
    token = issued["stepUpGrant"]
    assert token

    valid_row = {
        "id": "sg-1",
        "user_id": 50,
        "purpose": "rebind_email",
        "method": "password",
        "session_fingerprint": sess1,
        "session_id": sid1,
        "target_fingerprint": _target_fingerprint("new@example.com", purpose="rebind_email"),
        "status": "active",
        "expires_at": time.time() + 180,
    }
    # Wrong session rejected
    vcur = MagicMock()
    vcur.fetchone.return_value = valid_row
    with pytest.raises(BizError) as exc_sess:
        validate_step_up_grant(
            vcur,
            user_id=50,
            grant_token=token,
            purpose="rebind_email",
            session_fingerprint=sess2,
            session_ctx=sctx2,
            target_contact="new@example.com",
        )
    assert exc_sess.value.http_status == 403

    # Wrong user rejected
    vcur.fetchone.return_value = {**valid_row, "user_id": 999}
    with pytest.raises(BizError) as exc_user:
        validate_step_up_grant(
            vcur,
            user_id=50,
            grant_token=token,
            purpose="rebind_email",
            session_fingerprint=sess1,
            session_ctx=sctx1,
            target_contact="new@example.com",
        )
    assert exc_user.value.http_status == 403

    # Consumed replay rejected
    vcur.fetchone.return_value = {**valid_row, "status": "consumed"}
    with pytest.raises(BizError):
        validate_step_up_grant(
            vcur,
            user_id=50,
            grant_token=token,
            purpose="rebind_email",
            session_fingerprint=sess1,
            session_ctx=sctx1,
            target_contact="new@example.com",
        )

    # Expired grant rejected and marked expired
    vcur.fetchone.return_value = {**valid_row, "expires_at": time.time() - 5}
    with pytest.raises(BizError):
        validate_step_up_grant(
            vcur,
            user_id=50,
            grant_token=token,
            purpose="rebind_email",
            session_fingerprint=sess1,
            session_ctx=sctx1,
            target_contact="new@example.com",
        )


def test_rebind_email_requires_step_up_revokes_grants_handles_conflict_and_notifies():
    from config import settings as _settings
    from modules.security.step_up import _target_fingerprint

    sid77 = str(uuid.uuid4())
    req77, sess_fp = _make_request_with_jwt(77, sid=sid77, version=1)
    sctx77 = session_context_from_request(req77, 77)
    cid = "ch-rebind-77"
    code = "005599"
    new_email = "new77@example.com"
    code_hash = _hmac_code_v2(cid, "bind_email", "email_otp", new_email, code)

    # 1. Rebind WITHOUT step_up_grant MUST fail 403
    cur_no_grant = MagicMock()
    cur_no_grant.fetchone.side_effect = [
        {"id": 77},
        {
            "id": cid,
            "user_id": 77,
            "purpose": "bind_email",
            "channel": "email_otp",
            "destination_fingerprint": _fingerprint(new_email),
            "code_hash": code_hash,
            "status": "pending",
            "send_state": "accepted",
            "attempt_count": 0,
            "max_attempts": 5,
            "expires_at": time.time() + 300,
        },
        {"id": 10, "normalized_value": "old77@example.com"},
        None,  # conflict query
    ]
    with patch("modules.security.service.get_cursor") as mock_gc:
        mock_gc.return_value.__enter__.return_value = cur_no_grant
        with pytest.raises(BizError) as no_su_exc:
            verify_and_bind_contact(77, cid, code, new_email, step_up_grant=None, session_fingerprint=sess_fp)
        assert no_su_exc.value.http_status == 403

    # 2. Valid step_up_grant -> consumes grant, binds new email, revokes old recovery_grants + email challenges, sends notice
    em = MockEmailProvider()
    reset_providers_for_test(email=em)
    grant_token = "step-up-grant-secret-77"
    grant_row = {
        "id": "sg-77",
        "user_id": 77,
        "purpose": "rebind_email",
        "method": "password",
        "session_fingerprint": sctx77.fingerprint_for_purpose("rebind_email"),
        "session_id": sid77,
        "target_fingerprint": _target_fingerprint(new_email, purpose="rebind_email"),
        "status": "active",
        "expires_at": time.time() + 180,
    }
    cur_ok = MagicMock()
    cur_ok.fetchone.side_effect = [
        {"id": 77},
        {
            "id": cid,
            "user_id": 77,
            "purpose": "bind_email",
            "channel": "email_otp",
            "destination_fingerprint": _fingerprint(new_email),
            "code_hash": code_hash,
            "status": "pending",
            "send_state": "accepted",
            "attempt_count": 0,
            "max_attempts": 5,
            "expires_at": time.time() + 300,
        },
        {"id": 10, "normalized_value": "old77@example.com"},
        None,  # conflict query -> no other account
        grant_row,
        {
            "user_status": "active",
            "deleted_at": None,
            "session_version": 1,
            "has_any": True,
            "has_active": True,
            "has_expired": False,
        },
    ]
    with (
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_SECURITY_NOTIFICATION_ENABLED", True),
        patch("modules.security.service.get_cursor") as mock_gc,
        patch("modules.security.service.audit_record"),
    ):
        mock_gc.return_value.__enter__.return_value = cur_ok
        res = verify_and_bind_contact(
            77,
            cid,
            code,
            new_email,
            step_up_grant=grant_token,
            session_fingerprint=sess_fp,
            session_ctx=sctx77,
        )
    assert res["ok"] is True
    sqls = [str(c.args[0]) for c in cur_ok.execute.call_args_list]
    assert any("UPDATE step_up_grant SET status='consumed'" in s for s in sqls)
    assert any("UPDATE recovery_grant SET status = 'revoked'" in s for s in sqls)
    assert any("UPDATE auth_challenge SET status = 'cancelled'" in s for s in sqls)
    assert len(em.sent_emails) == 1
    assert em.sent_emails[0]["type"] == "notification"
    assert em.sent_emails[0]["email"] == "old77@example.com"

    # 3. DB UNIQUE conflict (IntegrityError) translates to 409
    cur_dup = MagicMock()
    cur_dup.fetchone.side_effect = [
        {"id": 77},
        {
            "id": cid,
            "user_id": 77,
            "purpose": "bind_email",
            "channel": "email_otp",
            "destination_fingerprint": _fingerprint(new_email),
            "code_hash": code_hash,
            "status": "pending",
            "send_state": "accepted",
            "attempt_count": 0,
            "max_attempts": 5,
            "expires_at": time.time() + 300,
        },
        None,  # first-time bind
        None,  # FOR UPDATE didn't see uncommitted row
        {
            "id": "sg-bind-dup",
            "user_id": 77,
            "purpose": "bind_email",
            "method": "password",
            "session_fingerprint": sctx77.fingerprint_for_purpose("bind_email"),
            "session_id": sid77,
            "target_fingerprint": _target_fingerprint(new_email, purpose="bind_email"),
            "status": "active",
            "expires_at": time.time() + 180,
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

    def _side_effect(sql, params=None):
        if "INSERT INTO account_contact" in str(sql):
            raise psycopg2.IntegrityError("duplicate key")

    cur_dup.execute.side_effect = _side_effect
    with patch("modules.security.service.get_cursor") as mock_gc:
        mock_gc.return_value.__enter__.return_value = cur_dup
        with pytest.raises(BizError) as dup_exc:
            verify_and_bind_contact(
                77,
                cid,
                code,
                new_email,
                step_up_grant="step-up-bind-dup-77",
                session_fingerprint=sess_fp,
                session_ctx=sctx77,
            )
        assert dup_exc.value.http_status == 409
