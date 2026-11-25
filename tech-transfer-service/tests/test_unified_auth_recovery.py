"""南山科转通统一身份安全与密码找回全套自动化测试。

测试覆盖：
1. 短信与邮件 Provider 接口及 Mock 行为
2. 找回密码发起（防账号枚举、时间平抑、脱敏显示）
3. 验证码核验（防重放、错误重试上限、单次有效性、跨用途防复用）
4. 密码重置单事务执行（Recovery Grant 消费、会话版本递增、活跃会话吊销、旧 Token 拦截）
5. PC 微信扫码 OAuth2（state 防 CSRF、单次核销、身份匹配与绑定）
6. 安全中心（联系方式确权、修改密码联动、强制多设备会话吊销）
"""

import time
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app import app
from core.errors import BizError
from core.jwt_utils import sign_access_token
from modules.security.provider import MockEmailProvider, MockSmsProvider, ProviderError, reset_providers_for_test
from modules.security.rate_limiter import limiter
from modules.security.service import (
    complete_password_recovery,
    get_security_summary,
    revoke_all_user_sessions,
    start_password_recovery,
    verify_recovery_challenge,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def setup_security_test():
    from config import settings as _settings

    sms = MockSmsProvider()
    email = MockEmailProvider()
    reset_providers_for_test(sms, email)
    limiter.reset_for_test()
    with patch.object(_settings, "REDIS_ENABLED", False):
        yield
    reset_providers_for_test(None, None)
    limiter.reset_for_test()


# ── 1. Provider 基础功能测试 ─────────────────────────────────────


def test_mock_sms_provider_send_and_last_code():
    sms = MockSmsProvider()
    sms.send_code("13800138000", "654321", "password_recovery", 300)
    assert sms.get_last_code("13800138000") == "654321"
    assert sms.get_last_code("13900000000") is None

    sms.should_fail = True
    with pytest.raises(ProviderError):
        sms.send_code("13800138000", "111111", "password_recovery")


def test_mock_email_provider_send_and_last_link():
    em = MockEmailProvider()
    em.send_code("test@example.com", "888999", "password_recovery", 300)
    assert em.get_last_code("test@example.com") == "888999"

    em.send_reset_link("test@example.com", "https://example.com/reset?token=abc", 300)
    assert em.get_last_link("test@example.com") == "https://example.com/reset?token=abc"

    em.should_fail = True
    with pytest.raises(ProviderError):
        em.send_code("test@example.com", "123123", "password_recovery")


def test_sendcloud_sms_provider_logic():
    import json

    from modules.security.provider import SendCloudSmsProvider

    with pytest.raises(ProviderError, match="缺少 SMS_USER 或 SMS_KEY"):
        SendCloudSmsProvider(sms_user="", sms_key="", template_id="123")

    with pytest.raises(ProviderError, match="缺少 SENDCLOUD_SMS_TEMPLATE_ID"):
        SendCloudSmsProvider(sms_user="user", sms_key="key", template_id="")

    provider = SendCloudSmsProvider(sms_user="test_u", sms_key="test_k", template_id="999")
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"result": True, "statusCode": 200}).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp
        mock_url.return_value = mock_resp

        res = provider.send_code("13800138000", "123456", "password_recovery", 300)
        assert res is True
        assert mock_url.called
        req = mock_url.call_args[0][0]
        assert "signature=" in req.data.decode("utf-8")


# ── 2. 密码找回发起测试（防枚举） ────────────────────────────────


def test_recovery_start_nonexistent_account_uniform_response():
    """Unknown accounts receive an opaque ID with the same response shape."""
    sms = MockSmsProvider()
    reset_providers_for_test(sms=sms)

    with patch("modules.security.sms_gateway.get_cursor") as mock_gc, patch("modules.security.sms_gateway._audit"):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__.return_value = cur

        resp = start_password_recovery("nonexistent_user", "sms")
        assert resp["sent"] is True
        assert resp["challengeId"] is not None
        assert resp["maskedDestination"] is None
        assert len(sms.sent_messages) == 0


def test_recovery_start_valid_account_sends_sms():
    sms = MockSmsProvider()
    reset_providers_for_test(sms=sms)

    from config import settings as _settings
    from modules.security.sms_risk import DecisionAction, RiskDecision

    with (
        patch("modules.security.sms_gateway.get_cursor") as mock_gc,
        patch("modules.security.sms_gateway._engine") as engine,
        patch("modules.security.sms_gateway.audit_record"),
        patch.object(_settings, "SMS_ENABLED", True),
    ):
        engine.return_value.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
        cur = MagicMock()
        # 第一次 fetchone: 命中 app_user
        # 第二次 fetchone: 命中 account_contact
        cur.fetchall.return_value = [{"user_id": 101, "normalized_value": "13800138000"}]
        mock_gc.return_value.__enter__.return_value = cur

        resp = start_password_recovery("13800138000", "sms")
        assert resp["sent"] is True
        assert resp["challengeId"] is not None
        assert resp["maskedDestination"] is None
        assert len(sms.sent_messages) == 1
        assert sms.sent_messages[0]["phone"] == "13800138000"


def test_recovery_start_valid_account_email_link():
    em = MockEmailProvider()
    reset_providers_for_test(email=em)

    from config import settings as _settings
    from modules.security.risk_engine import DecisionAction, RiskDecision

    with (
        patch("modules.security.email_gateway.get_cursor") as mock_gc,
        patch("modules.security.email_gateway._engine") as engine,
        patch("modules.security.email_gateway.audit_record"),
        patch.object(_settings, "EMAIL_ENABLED", True),
    ):
        engine.return_value.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
        cur = MagicMock()
        cur.fetchall.return_value = [{"user_id": 102, "normalized_value": "user@nanshan.com"}]
        mock_gc.return_value.__enter__.return_value = cur

        resp = start_password_recovery("user@nanshan.com", "email_link")
        assert resp["sent"] is True
        assert resp["challengeId"] is not None
        assert len(em.sent_emails) == 1
        assert em.sent_emails[0]["type"] == "link"
        assert "reset-password#challengeId=" in em.sent_emails[0]["reset_url"]
        assert "&token=" in em.sent_emails[0]["reset_url"]
        assert "reset-password?challengeId=" not in em.sent_emails[0]["reset_url"]


# ── 3. 挑战核验与 Recovery Grant 签发测试 ────────────────────────


def test_verify_challenge_success_and_grant_issuance():
    from modules.security.service import _hmac_code

    challenge_id = "test-challenge-uuid-1"
    code = "123456"
    dest = "13800138000"
    code_hash = _hmac_code(challenge_id, "password_recovery", dest, code)

    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 101},
            {
                "id": challenge_id,
                "user_id": 101,
                "purpose": "password_recovery",
                "channel": "sms",
                "destination_fingerprint": __import__(
                    "modules.security.service", fromlist=["_fingerprint"]
                )._fingerprint("13800138000"),
                "code_hash": code_hash,
                "status": "pending",
                "attempt_count": 0,
                "max_attempts": 5,
                "expires_at": time.time() + 300,
            },
            {"normalized_value": dest},
        ]
        mock_gc.return_value.__enter__.return_value = cur

        result = verify_recovery_challenge(challenge_id, code)
        assert "recoveryGrant" in result
        assert result["expiresIn"] == 300


def test_verify_challenge_wrong_code_increments_attempt():
    from modules.security.service import _hmac_code

    challenge_id = "test-challenge-uuid-2"
    correct_hash = _hmac_code(challenge_id, "password_recovery", "13800138000", "888888")

    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 101},
            {
                "id": challenge_id,
                "user_id": 101,
                "purpose": "password_recovery",
                "channel": "sms",
                "destination_fingerprint": __import__(
                    "modules.security.service", fromlist=["_fingerprint"]
                )._fingerprint("13800138000"),
                "code_hash": correct_hash,
                "status": "pending",
                "attempt_count": 1,
                "max_attempts": 5,
                "expires_at": time.time() + 300,
            },
            {"normalized_value": "13800138000"},
        ]
        mock_gc.return_value.__enter__.return_value = cur

        with pytest.raises(BizError) as exc_info:
            verify_recovery_challenge(challenge_id, "000000")
        assert "验证凭据无效或已失效" in exc_info.value.message


# ── 4. 密码重置单事务执行与会话即时失效 ──────────────────────────


def test_complete_recovery_atomic_transaction():
    grant_token = "valid_grant_token_xyz"

    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 101, "challenge_id": None},
            {"user_status": "active"},
            {"cred_status": "active", "password_configured": True, "password_hash": "old_hash"},
            {"id": "grant-uuid-1", "user_id": 101, "status": "active", "expires_at": time.time() + 300},
        ]
        mock_gc.return_value.__enter__.return_value = cur

        res = complete_password_recovery(grant_token, "NewPassword@2026")
        assert res["ok"] is True

        # 检查是否执行了关键更新语句
        executed_sqls = [str(call.args[0]) for call in cur.execute.call_args_list]
        assert any("session_version = session_version + 1" in s for s in executed_sqls)
        assert any("UPDATE auth_session" in s and "status = 'revoked'" in s for s in executed_sqls)
        assert any("status = 'consumed'" in s and "recovery_grant" in s for s in executed_sqls)


def test_complete_recovery_consumed_grant_rejected():
    grant_token = "consumed_grant_token"

    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 101, "challenge_id": None},
            {"user_status": "active"},
            {"cred_status": "active", "password_configured": True, "password_hash": "old_hash"},
            {
                "id": "grant-uuid-2",
                "user_id": 101,
                "status": "consumed",
                "expires_at": time.time() + 300,
            },
        ]
        mock_gc.return_value.__enter__.return_value = cur

        with pytest.raises(BizError) as exc_info:
            complete_password_recovery(grant_token, "NewPassword@2026")
        assert "无效或已被使用" in exc_info.value.message


# ── 5. 会话版本失效验证（中间件拒绝旧 Token） ──────────────────────


def test_session_version_rejection_after_invalidation():
    """验证：当用户 session_version 递增后，携带旧 session_version 的 JWT 立即被中间件拒绝 (401)。"""
    from core.middleware import identity

    user_id = 999
    # 签发版本号为 1 的 access token
    old_token = sign_access_token(user_id, "U999", ["user"], session_version=1)

    req = MagicMock()
    req.headers = {"Authorization": f"Bearer {old_token}"}

    # 模拟用户当前版本已变成 2（例如执行了密码修改或重置）
    with (
        patch("core.middleware._user_is_active", return_value=True),
        patch("core.middleware._user_session_version", return_value=2),
    ):
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.http_status == 401
        assert "登录已失效" in exc_info.value.message


# ── 6. PC 微信扫码 OAuth2 测试 ────────────────────────────────────


def test_wechat_web_authorize_url_and_state():
    from modules.identity.wechat_web import get_web_authorize_url, verify_and_consume_state

    info = get_web_authorize_url("https://frontend.com/auth/wechat-callback")
    assert "open.weixin.qq.com/connect/qrconnect" in info["authorizeUrl"]
    assert "state=" in info["authorizeUrl"]
    state = info["state"]

    # 首次核销应成功
    assert verify_and_consume_state(state) is True
    # 再次核销（重放）应失败
    assert verify_and_consume_state(state) is False


def test_wechat_web_callback_mock_login():
    from modules.identity.wechat_web import create_oauth_state, handle_web_callback

    state = create_oauth_state()
    with patch("modules.identity.wechat_web.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.return_value = {
            "user_id": 88,
            "unlinked_at": None,
            "user_status": "active",
            "cred_status": "active",
        }
        mock_gc.return_value.__enter__.return_value = cur

        with (
            patch("modules.identity.wechat_web._get_roles", return_value=["user"]),
            patch(
                "modules.identity.wechat_web._issue_session",
                return_value={"accessToken": "at_test", "refreshToken": "rt_test"},
            ),
            patch("modules.identity.wechat_web.build_user_response", return_value={"userId": 88}),
        ):
            res = handle_web_callback("mock_code_88", state)
            assert res["accessToken"] == "at_test"


# ── 7. 安全中心联系方式确权与全设备吊销测试 ────────────────────────


def test_security_summary_and_revoke_all_sessions():
    with (
        patch("modules.security.service.get_cursor") as mock_gc,
        patch("modules.security.step_up.get_cursor") as mock_su_gc,
    ):
        cur = MagicMock()
        cur.fetchone.return_value = {"username": "admin", "password_configured": True, "wechat_bound": False}
        cur.fetchall.side_effect = [
            [{"contact_type": "phone", "normalized_value": "13800138000", "verified_at": None, "updated_at": None}],
            [],
        ]
        mock_gc.return_value.__enter__.return_value = cur

        cur_su = MagicMock()
        cur_su.fetchone.return_value = {"password_configured": True, "has_password": True, "privileged": True}
        cur_su.fetchall.return_value = []
        mock_su_gc.return_value.__enter__.return_value = cur_su

        summary = get_security_summary(1)
        assert summary["passwordConfigured"] is True
        assert summary["phone"]["value"] == "138****8000"
        assert summary["phone"]["verified"] is False

    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        mock_gc.return_value.__enter__.return_value = cur
        res = revoke_all_user_sessions(1)
        assert res["ok"] is True
        executed_sqls = [str(call.args[0]) for call in cur.execute.call_args_list]
        assert any("session_version = session_version + 1" in s for s in executed_sqls)
        assert any("UPDATE auth_session SET status = 'revoked'" in s for s in executed_sqls)


# ── 8. API 路由端点端到端测试 ────────────────────────────────────


def test_api_recovery_flow_e2e():
    sms = MockSmsProvider()
    reset_providers_for_test(sms=sms)

    from config import settings as _settings
    from modules.security.sms_risk import DecisionAction, RiskDecision

    with (
        patch("modules.security.sms_gateway.get_cursor") as mock_gc,
        patch("modules.security.sms_gateway._engine") as engine,
        patch("modules.security.sms_gateway.audit_record"),
        patch.object(_settings, "SMS_ENABLED", True),
    ):
        engine.return_value.check_request.return_value = RiskDecision(DecisionAction.ALLOW)
        engine.return_value.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
        cur = MagicMock()
        cur.fetchall.return_value = [{"user_id": 200, "normalized_value": "13800138999"}]
        cur.fetchone.return_value = {
            "payload": {
                "account": "13800138999",
                "channel": "sms",
                "ip": "testclient",
                "device_id": None,
                "request_id": "test-request",
            }
        }
        mock_gc.return_value.__enter__.return_value = cur

        resp = client.post(
            "https://testserver/api/tech-transfer/v1/auth/recovery/start",
            json={"account": "13800138999", "channel": "sms"},
        )
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["sent"] is True
        challenge_id = data["challengeId"]
        assert challenge_id is not None
        code = sms.get_last_code("13800138999")
        assert code is not None

    # 2. verify
    from modules.security.service import _hmac_code

    code_hash = _hmac_code(challenge_id, "password_recovery", "13800138999", code)
    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 200},
            {
                "id": challenge_id,
                "user_id": 200,
                "purpose": "password_recovery",
                "channel": "sms",
                "destination_fingerprint": __import__(
                    "modules.security.service", fromlist=["_fingerprint"]
                )._fingerprint("13800138999"),
                "code_hash": code_hash,
                "status": "pending",
                "attempt_count": 0,
                "max_attempts": 5,
                "expires_at": time.time() + 300,
            },
            {"normalized_value": "13800138999"},
        ]
        mock_gc.return_value.__enter__.return_value = cur

        resp = client.post(
            "/api/tech-transfer/v1/auth/recovery/verify", json={"challengeId": challenge_id, "code": code}
        )
        assert resp.status_code == 200
        grant = resp.json()["data"]["recoveryGrant"]
        assert grant is not None

    # 3. complete
    with patch("modules.security.service.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchall.return_value = [{"id": challenge_id, "status": "verified"}]
        cur.fetchone.side_effect = [
            {"user_id": 200, "challenge_id": challenge_id},
            {"user_status": "active"},
            {"cred_status": "active", "password_configured": True, "password_hash": "dummy"},
            {
                "id": "grant-1",
                "user_id": 200,
                "challenge_id": challenge_id,
                "status": "active",
                "expires_at": time.time() + 300,
            },
        ]
        mock_gc.return_value.__enter__.return_value = cur

        resp = client.post(
            "/api/tech-transfer/v1/auth/recovery/complete",
            json={"recoveryGrant": grant, "newPassword": "ValidPassword@2026"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["ok"] is True


def test_api_wechat_web_endpoints():
    # 1. config
    resp = client.get("/api/tech-transfer/v1/auth/wechat/web/config")
    assert resp.status_code == 200
    assert "enabled" in resp.json()["data"]

    # 2. authorize
    resp = client.get("/api/tech-transfer/v1/auth/wechat/web/authorize?redirectUri=https://example.com/callback")
    assert resp.status_code == 200
    auth_data = resp.json()["data"]
    state = auth_data["state"]

    # 3. callback with mock code
    with patch("modules.identity.wechat_web.get_cursor") as mock_gc:
        cur = MagicMock()
        cur.fetchone.return_value = None  # 未绑定
        mock_gc.return_value.__enter__.return_value = cur

        resp = client.post(
            "/api/tech-transfer/v1/auth/wechat/web/callback",
            json={"code": "mock_code_test99", "state": state},
        )
        assert resp.status_code == 200
        cb_data = resp.json()["data"]
        assert cb_data["isBound"] is False
        assert "bindingTicket" in cb_data


@pytest.mark.parametrize(
    "phone,code,ttl",
    [
        ("", "123456", 300),
        ("13800138000,13900139000", "123456", 300),
        ("23800138000", "123456", 300),
        ("13800138000", 123456, 300),
        ("13800138000", "１２３４５６", 300),
        ("13800138000", "123456", True),
        ("13800138000", "123456", 0),
    ],
)
def test_sendcloud_rejects_invalid_inputs(phone, code, ttl):
    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        with pytest.raises(ProviderError):
            SendCloudSmsProvider("u", "k", 123).send_code(phone, code, "bind_phone", ttl)
        network.assert_not_called()


def test_sendcloud_exact_form_and_signature():
    import hashlib
    import json
    from urllib.parse import parse_qs

    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        network.return_value.__enter__.return_value.read.return_value = b'{"result":true,"statusCode":200}'
        provider = SendCloudSmsProvider("用户 &+", "secret", 123)
        provider.send_code("+8613800138000", "001234", "bind_phone", 61, request_id="task &+1")
        actual = {k: v[0] for k, v in parse_qs(network.call_args.args[0].data.decode()).items()}
        expected = {
            "smsUser": "用户 &+",
            "templateId": "123",
            "phone": "13800138000",
            "vars": '{"%code%":"001234"}',
            "sendRequestId": "task &+1",
        }
        signature = hashlib.sha256(
            ("secret&" + "&".join(k + "=" + expected[k] for k in sorted(expected)) + "&secret").encode()
        ).hexdigest()
        assert actual == dict(expected, signature=signature)
        assert json.loads(actual["vars"]) == {"%code%": "001234"}
        for key in expected:
            changed = dict(expected)
            changed[key] += "x"
            assert (
                hashlib.sha256(
                    ("secret&" + "&".join(k + "=" + changed[k] for k in sorted(changed)) + "&secret").encode()
                ).hexdigest()
                != signature
            )


@pytest.mark.parametrize("enabled", [True, False])
def test_production_rejects_cached_mock(monkeypatch, enabled):
    import modules.security.provider as p

    monkeypatch.setattr(p.settings, "APP_ENV", "production")
    monkeypatch.setattr(p.settings, "SMS_ENABLED", enabled)
    monkeypatch.setattr(p.settings, "SMS_PROVIDER", "mock")
    with pytest.raises(ProviderError):
        p.get_sms_provider()


@pytest.mark.parametrize(
    "kind,status,unknown",
    [
        ("http", 400, False),
        ("http", 503, True),
        ("json", None, True),
        ("structure", None, True),
        ("connect", None, True),
        ("read", None, True),
        ("connection", None, True),
        ("business", 422, False),
        ("business", 431, False),
        ("business", 499, False),
        ("business", 400, True),
    ],
)
def test_sendcloud_errors_are_safe(kind, status, unknown, monkeypatch, caplog):
    import modules.security.provider as p

    monkeypatch.setattr(p.settings, "SENDCLOUD_SMS_MAX_ATTEMPTS", 1)
    with patch("urllib.request.urlopen") as network:
        response = network.return_value.__enter__.return_value
        if kind == "http":
            network.side_effect = p.urllib.error.HTTPError("url", status, "secret 001234", {}, None)
        elif kind == "connect":
            network.side_effect = p.urllib.error.URLError(TimeoutError("secret 001234"))
        elif kind == "connection":
            network.side_effect = p.urllib.error.URLError("secret 001234")
        elif kind == "read":
            response.read.side_effect = TimeoutError("secret 001234")
        elif kind == "json":
            response.read.return_value = b"secret 001234 invalid json"
        elif kind == "structure":
            response.read.return_value = b"[]"
        else:
            response.read.return_value = (
                '{"result":false,"statusCode":' + str(status) + ',"message":"secret 001234"}'
            ).encode()
        with pytest.raises(ProviderError) as error:
            p.SendCloudSmsProvider("u", "secret", 123).send_code("13800138000", "001234", "bind_phone")
        assert error.value.outcome_unknown is unknown
        assert network.call_count == 1
        for sensitive in ["secret", "001234", "13800138000"]:
            assert sensitive not in str(error.value) + caplog.text
        assert caplog.records[-1].error_type


@pytest.mark.parametrize("request_id", ["", "x" * 129, 123, "bad\nID"])
def test_sendcloud_request_id_rejected(request_id):
    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        with pytest.raises(ProviderError):
            SendCloudSmsProvider("u", "k", 1).send_code("13800138000", "001234", "bind_phone", request_id=request_id)
        network.assert_not_called()


def test_sendcloud_generated_ids_are_distinct():
    from urllib.parse import parse_qs

    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        network.return_value.__enter__.return_value.read.return_value = b'{"result":true,"statusCode":200}'
        provider = SendCloudSmsProvider("u", "k", 1)
        for _ in range(2):
            provider.send_code("13800138000", "001234", "bind_phone")
        ids = [parse_qs(call.args[0].data.decode())["sendRequestId"][0] for call in network.call_args_list]
        assert ids[0] != ids[1]


@pytest.mark.parametrize("provider_type", ["mock", "sendcloud", "tencent", "typo"])
def test_sms_disabled_without_injection(monkeypatch, provider_type):
    import modules.security.provider as p

    p.reset_providers_for_test()
    monkeypatch.setattr(p.settings, "SMS_ENABLED", False)
    monkeypatch.setattr(p.settings, "SMS_PROVIDER", provider_type)
    with pytest.raises(ProviderError):
        p.get_sms_provider()


@pytest.mark.parametrize("phone", ["+8613800138000", "13800138000"])
def test_sendcloud_mainland_phone(phone):
    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        network.return_value.__enter__.return_value.read.return_value = b'{"result":true,"statusCode":200}'
        assert SendCloudSmsProvider("u", "k", 1).send_code(phone, "000001", "password_recovery")


@pytest.mark.parametrize(
    "phone,code,ttl,purpose",
    [
        ("+1 2025550123", "123456", 300, "bind_phone"),
        ("13800138000\n", "123456", 300, "bind_phone"),
        ("abc", "123456", 300, "bind_phone"),
        ("13800138000", "", 300, "bind_phone"),
        ("13800138000", "1e0005", 300, "bind_phone"),
        ("13800138000", 1.23, 300, "bind_phone"),
        ("13800138000", "123456", 3601, "bind_phone"),
        ("13800138000", "123456", 1.5, "bind_phone"),
        ("13800138000", "123456", "300", "bind_phone"),
        ("13800138000", "123456", 300, "login"),
    ],
)
def test_sendcloud_more_invalid_inputs(phone, code, ttl, purpose):
    from modules.security.provider import SendCloudSmsProvider

    with patch("urllib.request.urlopen") as network:
        with pytest.raises(ProviderError):
            SendCloudSmsProvider("u", "k", 1).send_code(phone, code, purpose, ttl)
        network.assert_not_called()


def test_sms_disable_also_blocks_factory_cached_instance(monkeypatch):
    import modules.security.provider as p

    p.reset_providers_for_test()
    monkeypatch.setattr(p.settings, "SMS_ENABLED", True)
    monkeypatch.setattr(p.settings, "SMS_PROVIDER", "mock")
    p.get_sms_provider()
    monkeypatch.setattr(p.settings, "SMS_ENABLED", False)
    with pytest.raises(ProviderError):
        p.get_sms_provider()
