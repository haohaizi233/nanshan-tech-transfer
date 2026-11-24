"""TencentSesProvider SendEmail 2020-10-02 协议、TC3 签名、状态查询与日志脱敏测试。"""

from __future__ import annotations

import base64
import io
import json
import logging
import urllib.error
from unittest.mock import MagicMock, patch

import pytest

from modules.security.delivery_models import DeliveryReceipt, ProviderError
from modules.security.email_providers import TencentSesProvider


def _make_ses(**overrides) -> TencentSesProvider:
    params = {
        "secret_id": "AKIDTESTKEY123456",
        "secret_key": "SUPER_SECRET_TC3_KEY_VALUE",
        "from_email": "no-reply@notice.example.com",
        "region": "ap-hongkong",
        "endpoint": "ses.tencentcloudapi.com",
        "timeout": 5,
    }
    params.update(overrides)
    return TencentSesProvider(**params)


def test_tencent_ses_config_validation():
    with pytest.raises(ProviderError) as exc_info:
        TencentSesProvider("", "key", "from@example.com")
    assert exc_info.value.reason_code == "CONFIG_ERROR"

    with pytest.raises(ProviderError):
        TencentSesProvider("id", "key", "from@example.com", region="invalid region!")

    with pytest.raises(ProviderError):
        TencentSesProvider("id", "key", "from@example.com", endpoint="evil.attacker.com")


def test_tencent_ses_send_email_simple_and_template_contracts(caplog):
    ses = _make_ses()

    def _ok_response(msg_id="qcloud-ses-msg-001", req_id="req-qcloud-1"):
        resp = MagicMock()
        resp.read.return_value = json.dumps({"Response": {"MessageId": msg_id, "RequestId": req_id}}).encode("utf-8")
        resp.__enter__.return_value = resp
        return resp

    with (
        patch("modules.security.email_providers.urllib.request.urlopen", return_value=_ok_response()) as mock_open,
        caplog.at_level(logging.DEBUG, logger="nanshan.security.email_provider"),
    ):
        receipt = ses.send_code_task(
            "Receiver+1@Example.COM",
            "009871",
            "password_recovery",
            300,
            send_request_id="req-ses-otp-1",
        )

    assert isinstance(receipt, DeliveryReceipt)
    assert receipt.accepted is True
    assert receipt.provider == "tencent"
    assert receipt.channel == "email_otp"
    assert receipt.provider_message_ids == ("qcloud-ses-msg-001",)
    assert receipt.request_id == "req-qcloud-1"

    req = mock_open.call_args[0][0]
    headers = {k.lower(): v for k, v in req.headers.items()}
    assert headers["x-tc-action"] == "SendEmail"
    assert headers["x-tc-version"] == "2020-10-02"
    assert headers["x-tc-region"] == "ap-hongkong"
    assert headers["authorization"].startswith("TC3-HMAC-SHA256 Credential=AKIDTESTKEY123456/")
    assert "SignedHeaders=content-type;host;x-tc-action" in headers["authorization"]

    body = json.loads(req.data.decode("utf-8"))
    assert body["FromEmailAddress"] == "no-reply@notice.example.com"
    assert body["Destination"] == ["receiver+1@example.com"]
    assert body["TriggerType"] == 1
    assert "009871" in base64.b64decode(body["Simple"]["Html"]).decode("utf-8")
    assert "009871" in base64.b64decode(body["Simple"]["Text"]).decode("utf-8")

    # 模板发送模式
    ses_tpl = _make_ses(reset_template_id=88001)
    with patch("modules.security.email_providers.urllib.request.urlopen", return_value=_ok_response("m2", "r2")) as m2:
        link_receipt = ses_tpl.send_reset_link_task(
            "user@example.com",
            "https://tech.example.com/reset-password#challengeId=c1&token=TOK",
            300,
            send_request_id="req-ses-link-1",
        )
    assert link_receipt.channel == "email_link"
    tpl_body = json.loads(m2.call_args[0][0].data.decode("utf-8"))
    assert tpl_body["Template"]["TemplateID"] == 88001
    assert json.loads(tpl_body["Template"]["TemplateData"])["resetUrl"].endswith("#challengeId=c1&token=TOK")

    # 确认日志绝无明文密钥或收件人或验证码
    assert "SUPER_SECRET_TC3_KEY_VALUE" not in caplog.text
    assert "009871" not in caplog.text
    assert "receiver+1@example.com" not in caplog.text


@pytest.mark.parametrize(
    ("ses_code", "expected_reason", "expected_unknown"),
    [
        ("AuthFailure.SignatureFailure", "SES_SIGNATURE_ERROR", False),
        ("FailedOperation.NotAuthenticatedSender", "SES_PERMISSION_ERROR", False),
        ("LimitExceeded.OutOfQuota", "SES_QUOTA_EXCEEDED", False),
        ("InternalError", "PROVIDER_OUTCOME_UNKNOWN", True),
        ("InvalidParameter.Destination", "CONFIG_ERROR", False),
    ],
)
def test_tencent_ses_business_error_mapping(ses_code, expected_reason, expected_unknown, caplog):
    ses = _make_ses()
    resp = MagicMock()
    resp.read.return_value = json.dumps(
        {
            "Response": {
                "Error": {"Code": ses_code, "Message": "SECRET_RAW_PROVIDER_BODY user@example.com"},
                "RequestId": "err-req-1",
            }
        }
    ).encode("utf-8")
    resp.__enter__.return_value = resp

    with (
        patch("modules.security.email_providers.urllib.request.urlopen", return_value=resp),
        caplog.at_level(logging.DEBUG, logger="nanshan.security.email_provider"),
    ):
        with pytest.raises(ProviderError) as exc_info:
            ses.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-err")
    assert exc_info.value.reason_code == expected_reason
    assert exc_info.value.outcome_unknown is expected_unknown
    assert exc_info.value.retryable is False
    assert "SECRET_RAW_PROVIDER_BODY" not in str(exc_info.value)
    assert "SECRET_RAW_PROVIDER_BODY" not in caplog.text


def test_tencent_ses_http_malformed_and_query_status():
    ses = _make_ses()

    # HTTP 502 -> unknown
    http_502 = urllib.error.HTTPError("https://ses.tencentcloudapi.com/", 502, "Bad Gateway", {}, io.BytesIO(b""))
    with patch("modules.security.email_providers.urllib.request.urlopen", side_effect=http_502):
        with pytest.raises(ProviderError) as e502:
            ses.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-502")
        assert e502.value.reason_code == "PROVIDER_OUTCOME_UNKNOWN"
        assert e502.value.outcome_unknown is True

    # Missing MessageId -> SES_INVALID_RESPONSE + outcome_unknown
    bad_resp = MagicMock()
    bad_resp.read.return_value = json.dumps({"Response": {"RequestId": "no-msg"}}).encode("utf-8")
    bad_resp.__enter__.return_value = bad_resp
    with patch("modules.security.email_providers.urllib.request.urlopen", return_value=bad_resp):
        with pytest.raises(ProviderError) as no_msg:
            ses.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-nomsg")
        assert no_msg.value.reason_code == "SES_INVALID_RESPONSE"
        assert no_msg.value.outcome_unknown is True

    # GetSendEmailStatus
    status_resp = MagicMock()
    status_resp.read.return_value = json.dumps(
        {
            "Response": {
                "EmailStatusList": [{"MessageId": "mid-1", "DeliverStatus": 1, "DeliverMessage": "Success"}],
                "RequestId": "q-1",
            }
        }
    ).encode("utf-8")
    status_resp.__enter__.return_value = status_resp
    with patch("modules.security.email_providers.urllib.request.urlopen", return_value=status_resp) as q_open:
        result = ses.query_status(["mid-1"], request_date="2026-11-24")
    assert result["accepted"] is True
    assert result["records"][0]["DeliverStatus"] == 1
    assert q_open.call_args[0][0].headers["X-tc-action"] == "GetSendEmailStatus"
