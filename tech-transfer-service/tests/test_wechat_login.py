from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError


@pytest.fixture
def runtime():
    from modules.identity import wechat

    cursor = MagicMock()

    @contextmanager
    def transaction(**kwargs):
        yield cursor

    with (
        patch.object(wechat.settings, "WECHAT_LOGIN_ENABLED", True),
        patch.object(wechat.settings, "WECHAT_APPID", "app-id"),
        patch.object(wechat.settings, "WECHAT_APP_SECRET", "server-only-secret"),
        patch.object(wechat, "get_cursor", transaction),
        patch.object(wechat, "exchange_login_code", return_value="trusted-openid"),
        patch.object(wechat, "exchange_phone_code", return_value="13900000000") as phone,
        patch.object(wechat, "_get_roles", return_value=["user"]),
        patch.object(wechat, "_issue_session", return_value={"accessToken": "session"}) as issue,
        patch.object(wechat, "build_user_response", return_value={"userId": 7}),
        patch.object(wechat, "audit_record"),
    ):
        yield wechat, cursor, phone, issue


def test_linked_wechat_login_reuses_account_without_phone_authorization(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.return_value = {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": "13900000000", "unlinked_at": None}
    result = wechat.wechat_login_session("one-time-login-code")
    assert result["user"]["userId"] == 7
    phone.assert_not_called()
    issue.assert_called_once()


def test_unlinked_wechat_login_requires_verified_phone_and_issues_no_session(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.return_value = None
    with pytest.raises(BizError) as error:
        wechat.wechat_login_session("login-code")
    assert error.value.code == "TT_AUTH_40902"
    issue.assert_not_called()


def test_existing_phone_account_is_not_merged_without_original_account_login(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.side_effect = [None, {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": "13900000000"}]
    with pytest.raises(BizError) as error:
        wechat.wechat_login_session("login-code", "phone-code")
    assert error.value.code == "TT_AUTH_40903"
    issue.assert_not_called()
    assert not any("INSERT INTO external_identity" in call.args[0] for call in cursor.execute.call_args_list)


def test_signed_in_phone_owner_can_bind_wechat(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.side_effect = [None, {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": "13900000000"}]
    result = wechat.wechat_login_session("login-code", "phone-code", bind_user_id=7)
    assert result["user"]["userId"] == 7
    phone.assert_called_once_with("phone-code", "trusted-openid")
    assert any("INSERT INTO external_identity" in call.args[0] for call in cursor.execute.call_args_list)


def test_binding_a_legacy_phone_username_backfills_the_verified_login_phone(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.side_effect = [None, {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": None}]
    wechat.wechat_login_session("login-code", "phone-code", bind_user_id=7)
    assert any("UPDATE user_credential SET phone=%s" in call.args[0] and call.args[1] == ("13900000000", 7)
               for call in cursor.execute.call_args_list)


def test_cannot_bind_another_accounts_verified_phone(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.side_effect = [None, {"user_id": 8, "user_status": "active", "cred_status": "active", "phone": "13900000000"}]
    with pytest.raises(BizError):
        wechat.wechat_login_session("login-code", "phone-code", bind_user_id=7)
    issue.assert_not_called()


def test_disabled_or_unlinked_wechat_identity_cannot_login(runtime):
    wechat, cursor, phone, issue = runtime
    for override in [{"user_status": "disabled"}, {"cred_status": "disabled"}, {"unlinked_at": "deleted"}]:
        cursor.fetchone.side_effect = None
        cursor.fetchone.return_value = {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": "13900000000", "unlinked_at": None, **override}
        with pytest.raises(BizError):
            wechat.wechat_login_session("login-code")
    issue.assert_not_called()


def test_new_verified_phone_creates_one_regular_user_not_a_mock_identity(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.side_effect = [None, None]
    with patch.object(wechat, "create_password_account", return_value=(9, "U9")) as create:
        result = wechat.wechat_login_session("login-code", "phone-code")
    assert result["isNewUser"] is True
    assert create.call_args.kwargs["phone"] == "13900000000"
    assert len(create.call_args.args[2]) >= 32
    assert any("password_configured=false" in call.args[0] for call in cursor.execute.call_args_list)


def test_wechat_disabled_fails_closed_without_network(runtime):
    wechat, cursor, phone, issue = runtime
    with patch.object(wechat.settings, "WECHAT_LOGIN_ENABLED", False):
        with pytest.raises(BizError):
            wechat.wechat_login_session("anything", "anything")
    assert cursor.execute.call_count == 0
    issue.assert_not_called()


def test_phone_code_checks_app_watermark_and_does_not_accept_a_client_phone():
    from modules.identity import wechat

    info = {"purePhoneNumber": "13900000000", "countryCode": "86", "watermark": {"appid": "correct-app"}}
    with patch.object(wechat.settings, "WECHAT_APPID", "correct-app"), patch.object(wechat, "_access_token", return_value="server-token"):
        with patch.object(wechat, "_wechat_json", return_value={"phone_info": info}) as upstream:
            assert wechat.exchange_phone_code("phone-code", "openid-from-wechat") == "13900000000"
            assert upstream.call_args.kwargs["body"] == {"code": "phone-code", "openid": "openid-from-wechat"}
        for bad in [{**info, "watermark": {"appid": "other-app"}}, {**info, "countryCode": "1"}, {}]:
            with patch.object(wechat, "_wechat_json", return_value={"phone_info": bad}), pytest.raises(BizError):
                wechat.exchange_phone_code("code", "openid")


def test_wechat_errors_never_expose_upstream_secrets_or_session_keys():
    import json
    from modules.identity import wechat

    response = MagicMock()
    response.__enter__.return_value.read.return_value = json.dumps({"errcode": 40029, "errmsg": "sensitive upstream payload"}).encode()
    with patch.object(wechat.urllib.request, "urlopen", return_value=response), pytest.raises(BizError) as error:
        wechat._wechat_json("sns/jscode2session")
    assert "sensitive" not in str(error.value)


def test_session_response_excludes_wechat_identifiers_and_is_a_regular_session(runtime):
    wechat, cursor, phone, issue = runtime
    cursor.fetchone.return_value = {"user_id": 7, "user_status": "active", "cred_status": "active", "phone": "13900000000", "unlinked_at": None}
    result = wechat.wechat_login_session("code")
    assert set(result) == {"accessToken", "user", "isNewUser"}


def test_wechat_binding_requires_an_authenticated_user():
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from routes import auth

    app = FastAPI()
    app.include_router(auth.router)
    with TestClient(app, raise_server_exceptions=False) as client, patch.object(auth, "wechat_login_session") as login:
        response = client.post("/api/tech-transfer/v1/auth/wechat/bind", json={"loginCode": "login", "phoneCode": "phone"})
    assert response.status_code != 200
    login.assert_not_called()


def test_wechat_new_user_can_initialize_password_but_existing_password_is_required():
    from modules.identity import service

    cursor = MagicMock()
    context = MagicMock()
    context.__enter__.return_value = cursor
    with patch.object(service, "get_cursor", return_value=context), patch.object(service, "hash_password", return_value="hash"), patch.object(service, "audit_record"):
        cursor.fetchone.return_value = {"password_hash": "random", "password_configured": False, "status": "active"}
        assert service.change_password(7, "", "NewPassword123")["ok"] is True
        assert "password_configured=true" in cursor.execute.call_args.args[0]
        cursor.fetchone.return_value = {"password_hash": "existing", "password_configured": True, "status": "active"}
        with pytest.raises(BizError):
            service.change_password(7, "", "NewPassword123")
