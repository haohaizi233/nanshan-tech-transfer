"""SmtpEmailProvider 安全传输、错误分类、DATA 未知结果保守性与本地环回测试。"""

from __future__ import annotations

import smtplib
import socket
import ssl
import threading
from unittest.mock import MagicMock, patch

import pytest

from modules.security.delivery_models import DeliveryReceipt, ProviderError
from modules.security.email_providers import SmtpEmailProvider, build_strict_ssl_context


def _make_provider(**overrides) -> SmtpEmailProvider:
    params = {
        "host": "smtp.example.com",
        "port": 465,
        "user": "auth-user@example.com",
        "password": "secret-password",
        "use_ssl": True,
        "timeout": 5,
        "from_email": "noreply@example.com",
        "max_attempts": 2,
    }
    params.update(overrides)
    return SmtpEmailProvider(**params)


def test_build_strict_ssl_context_enforces_tls12_and_cert():
    ctx = build_strict_ssl_context()
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    if hasattr(ssl, "TLSVersion"):
        assert ctx.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_smtp_config_validation_and_header_injection_protection():
    with pytest.raises(ProviderError) as exc_info:
        SmtpEmailProvider(host="smtp\r\n.example.com", user="a@b.cn", password="p")
    assert exc_info.value.reason_code == "CONFIG_ERROR"

    with pytest.raises(ProviderError):
        SmtpEmailProvider(host="smtp.example.com", port=70000, user="a@b.cn", password="p")

    with pytest.raises(ProviderError):
        SmtpEmailProvider(host="smtp.example.com", user="only-user", password="")

    provider = _make_provider()
    assert provider.from_email == "noreply@example.com"
    assert provider.user == "auth-user@example.com"
    with pytest.raises(ProviderError) as inj_exc:
        provider.send_code_task(
            "victim@example.com\r\nBcc:evil@attacker.com", "123456", "bind_email", send_request_id="r1"
        )
    assert inj_exc.value.reason_code == "invalid_parameters"

    with pytest.raises(ProviderError) as req_inj:
        provider.send_code_task("victim@example.com", "123456", "bind_email", send_request_id="bad\nheader")
    assert req_inj.value.reason_code == "invalid_parameters"


def test_smtp_ssl_success_and_query_unsupported():
    provider = _make_provider(use_ssl=True, port=465)
    mock_smtp = MagicMock()
    mock_smtp.__enter__.return_value = mock_smtp
    mock_smtp.sendmail.return_value = {}

    with patch("modules.security.email_providers.smtplib.SMTP_SSL", return_value=mock_smtp) as ssl_cls:
        receipt = provider.send_code_task(
            "User@Example.COM",
            "008812",
            "password_recovery",
            300,
            send_request_id="req-ssl-1",
        )
    assert isinstance(receipt, DeliveryReceipt)
    assert receipt.accepted is True
    assert receipt.provider == "smtp"
    assert receipt.channel == "email_otp"
    assert len(receipt.provider_message_ids) == 1
    assert receipt.provider_message_ids[0].startswith("<")
    ssl_cls.assert_called_once()
    mock_smtp.login.assert_called_once_with("auth-user@example.com", "secret-password")

    with pytest.raises(ProviderError) as q_exc:
        provider.query_status(["<id@example.com>"])
    assert q_exc.value.reason_code == "unsupported_capability"


def test_smtp_error_classifications_and_data_phase_unknown_no_retry():
    provider = _make_provider(use_ssl=False, port=587, max_attempts=3)

    # 1. TLS certificate / handshake failure
    tls_srv = MagicMock()
    tls_srv.starttls.side_effect = ssl.SSLError("certificate verify failed")
    with patch("modules.security.email_providers.smtplib.SMTP", return_value=tls_srv):
        with pytest.raises(ProviderError) as tls_exc:
            provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-tls")
        assert tls_exc.value.reason_code == "SMTP_TLS_FAILED"
        assert tls_exc.value.retryable is False

    # 2. Authentication error (535)
    auth_srv = MagicMock()
    auth_srv.__enter__.return_value = auth_srv
    auth_srv.login.side_effect = smtplib.SMTPAuthenticationError(535, b"5.7.8 Auth failed")
    with patch("modules.security.email_providers.smtplib.SMTP", return_value=auth_srv):
        with pytest.raises(ProviderError) as auth_exc:
            provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-auth")
        assert auth_exc.value.reason_code == "SMTP_AUTH_FAILED"
        assert auth_exc.value.provider_status == 535
        assert auth_exc.value.retryable is False

    # 3. 4xx Temporary failure -> retries bounded to max_attempts
    temp_srv = MagicMock()
    temp_srv.__enter__.return_value = temp_srv
    temp_srv.sendmail.side_effect = smtplib.SMTPDataError(451, b"Temporary local problem")
    with (
        patch("modules.security.email_providers.smtplib.SMTP", return_value=temp_srv) as smtp_cls,
        patch("modules.security.email_providers.time.sleep"),
    ):
        with pytest.raises(ProviderError) as temp_exc:
            provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-451")
        assert temp_exc.value.reason_code == "SMTP_TEMPORARY_FAILURE"
        assert temp_exc.value.retryable is True
        assert temp_exc.value.outcome_unknown is False
        assert smtp_cls.call_count == 3

    # 4. 5xx Recipient refused -> permanent error, no retry
    ref_srv = MagicMock()
    ref_srv.__enter__.return_value = ref_srv
    ref_srv.sendmail.side_effect = smtplib.SMTPRecipientsRefused({"u@example.com": (550, b"5.1.1 User unknown")})
    with patch("modules.security.email_providers.smtplib.SMTP", return_value=ref_srv) as smtp_cls:
        with pytest.raises(ProviderError) as ref_exc:
            provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-550")
        assert ref_exc.value.reason_code == "SMTP_RECIPIENT_REJECTED"
        assert ref_exc.value.retryable is False
        assert ref_exc.value.outcome_unknown is False
        assert smtp_cls.call_count == 1

    # 5. DATA 阶段网络断开或超时 -> PROVIDER_OUTCOME_UNKNOWN，绝对禁止自动重发！
    for exc_obj in (
        smtplib.SMTPServerDisconnected("Connection unexpectedly closed during DATA"),
        TimeoutError("timed out reading DATA response"),
    ):
        data_srv = MagicMock()
        data_srv.__enter__.return_value = data_srv
        data_srv.sendmail.side_effect = exc_obj
        with patch("modules.security.email_providers.smtplib.SMTP", return_value=data_srv) as smtp_cls:
            with pytest.raises(ProviderError) as unk_exc:
                provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-unk")
            assert unk_exc.value.reason_code == "PROVIDER_OUTCOME_UNKNOWN"
            assert unk_exc.value.outcome_unknown is True
            assert unk_exc.value.retryable is False
            assert smtp_cls.call_count == 1


def test_smtp_loopback_socket_missing_starttls_fails_safely():
    """真实本地环回 Socket SMTP 服务不宣称 STARTTLS 时，provider 必须安全失败而非明文降级。"""
    ready = threading.Event()
    port_holder: list[int] = []

    def _fake_smtp_server():
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            port_holder.append(srv.getsockname()[1])
            ready.set()
            conn, _ = srv.accept()
            with conn:
                conn.sendall(b"220 loopback.local ESMTP Fake\r\n")
                while True:
                    chunk = conn.recv(1024)
                    if not chunk:
                        break
                    line = chunk.decode("ascii", errors="ignore").upper()
                    if line.startswith("EHLO"):
                        conn.sendall(b"250-loopback.local\r\n250 SIZE 10485760\r\n")
                    elif line.startswith("QUIT"):
                        conn.sendall(b"221 Bye\r\n")
                        break
                    else:
                        conn.sendall(b"502 Command not implemented\r\n")

    t = threading.Thread(target=_fake_smtp_server, daemon=True)
    t.start()
    ready.wait(timeout=3)
    provider = _make_provider(host="127.0.0.1", port=port_holder[0], use_ssl=False, timeout=2, max_attempts=1)
    with pytest.raises(ProviderError) as exc_info:
        provider.send_code_task("u@example.com", "123456", "bind_email", send_request_id="req-loopback")
    assert exc_info.value.retryable is False
    t.join(timeout=2)
