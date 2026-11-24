"""Email Provider 注册门禁、配置校验与邮件模板安全测试。"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from config import assert_environment, validate_frontend_reset_base_url
from core.contact_validation import email_domain, normalize_email
from core.errors import BizError
from modules.security.delivery_models import ProviderError
from modules.security.email_providers import MockEmailProvider, SmtpEmailProvider, TencentSesProvider
from modules.security.email_templates import (
    render_otp_email,
    render_password_recovery_link_email,
    render_security_notification_email,
)
from modules.security.provider import get_email_provider, reset_providers_for_test


@pytest.fixture(autouse=True)
def _reset_email_provider():
    reset_providers_for_test(None, None)
    yield
    reset_providers_for_test(None, None)


def test_email_provider_registry_strict_check_order():
    from config import settings as _settings

    # 1. EMAIL_ENABLED=false 时即使注入 Mock 或已缓存实例也必须拒绝
    reset_providers_for_test(email=MockEmailProvider())
    with (
        patch.object(_settings, "APP_ENV", "local"),
        patch.object(_settings, "EMAIL_ENABLED", False),
    ):
        with pytest.raises(ProviderError) as exc_info:
            get_email_provider()
        assert exc_info.value.reason_code == "CHANNEL_DISABLED"

    # 2. production 与 staging 禁止 mock，禁止测试注入，禁止未知 provider 回退
    for env_name in ("production", "staging"):
        reset_providers_for_test(email=MockEmailProvider())
        with (
            patch.object(_settings, "APP_ENV", env_name),
            patch.object(_settings, "EMAIL_ENABLED", True),
            patch.object(_settings, "EMAIL_PROVIDER", "smtp"),
        ):
            with pytest.raises(ProviderError) as exc_info:
                get_email_provider()
            assert exc_info.value.reason_code == "CONFIG_ERROR"

        reset_providers_for_test(None, None)
        for bad_provider in ("mock", "unknown_vendor", "sendgrid", "tencent_ses"):
            with (
                patch.object(_settings, "APP_ENV", env_name),
                patch.object(_settings, "EMAIL_ENABLED", True),
                patch.object(_settings, "EMAIL_PROVIDER", bad_provider),
            ):
                with pytest.raises(ProviderError) as exc_info:
                    get_email_provider()
                assert exc_info.value.reason_code == "CONFIG_ERROR"

    # 3. SMTP / SES 配置缺失直接报错，不得静默回退 Mock
    with (
        patch.object(_settings, "APP_ENV", "production"),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_PROVIDER", "smtp"),
        patch.object(_settings, "SMTP_HOST", ""),
    ):
        with pytest.raises(ProviderError) as exc_info:
            get_email_provider()
        assert exc_info.value.reason_code == "CONFIG_ERROR"

    with (
        patch.object(_settings, "APP_ENV", "production"),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_PROVIDER", "tencent"),
        patch.object(_settings, "TENCENT_SES_SECRET_ID", ""),
    ):
        with pytest.raises(ProviderError) as exc_info:
            get_email_provider()
        assert exc_info.value.reason_code == "CONFIG_ERROR"


def test_email_provider_cache_invalidation_and_toggle():
    from config import settings as _settings

    with (
        patch.object(_settings, "APP_ENV", "production"),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_PROVIDER", "smtp"),
        patch.object(_settings, "SMTP_HOST", "smtp1.example.com"),
        patch.object(_settings, "SMTP_PORT", 465),
        patch.object(_settings, "SMTP_USER", "sender1@example.com"),
        patch.object(_settings, "SMTP_PASSWORD", "pwd-one"),
        patch.object(_settings, "SMTP_FROM_EMAIL", "sender1@example.com"),
        patch.object(_settings, "SMTP_USE_SSL", True),
    ):
        p1 = get_email_provider()
        assert isinstance(p1, SmtpEmailProvider)
        assert get_email_provider() is p1

        # 配置变更必须自动失效重建
        with patch.object(_settings, "SMTP_HOST", "smtp2.example.com"):
            p2 = get_email_provider()
            assert isinstance(p2, SmtpEmailProvider)
            assert p2 is not p1
            assert p2.host == "smtp2.example.com"

        # EMAIL_ENABLED=false 时缓存实例也不得继续返回
        with patch.object(_settings, "EMAIL_ENABLED", False):
            with pytest.raises(ProviderError) as exc_info:
                get_email_provider()
            assert exc_info.value.reason_code == "CHANNEL_DISABLED"

    with (
        patch.object(_settings, "APP_ENV", "staging"),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_PROVIDER", "tencent"),
        patch.object(_settings, "TENCENT_SES_SECRET_ID", "AKIDTEST123"),
        patch.object(_settings, "TENCENT_SES_SECRET_KEY", "SECRETKEY123"),
        patch.object(_settings, "TENCENT_SES_FROM_EMAIL", "no-reply@example.com"),
        patch.object(_settings, "TENCENT_SES_REGION", "ap-hongkong"),
    ):
        ses = get_email_provider()
        assert isinstance(ses, TencentSesProvider)


def test_mock_email_provider_never_logs_plaintext_secrets(caplog):
    provider = MockEmailProvider()
    with caplog.at_level(logging.DEBUG, logger="nanshan.security.email_provider"):
        receipt_otp = provider.send_code_task(
            "Alice+Tag@Example.COM",
            "007412",
            "password_recovery",
            300,
            send_request_id="req-secret-check-1",
        )
        receipt_link = provider.send_reset_link_task(
            "alice@example.com",
            "https://tech.example.com/reset-password#challengeId=c1&token=SUPER_SECRET_LINK_TOKEN",
            300,
            send_request_id="req-secret-check-2",
        )
    assert receipt_otp.accepted is True
    assert receipt_otp.provider == "mock"
    assert receipt_link.accepted is True
    log_text = caplog.text
    assert "007412" not in log_text
    assert "Alice" not in log_text
    assert "alice@example.com" not in log_text
    assert "SUPER_SECRET_LINK_TOKEN" not in log_text
    assert provider.get_last_code("alice+tag@example.com") == "007412"


def test_frontend_reset_url_and_assert_environment_gates():
    assert validate_frontend_reset_base_url("https://tech.nanshan.gov.cn/", production_like=True) == (
        "https://tech.nanshan.gov.cn"
    )
    for bad in (
        "http://tech.nanshan.gov.cn",
        "https://localhost:5173",
        "https://127.0.0.1:8080",
        "https://tech.nanshan.gov.cn/app?x=1",
        "https://tech.nanshan.gov.cn/#hash",
        "javascript:alert(1)",
    ):
        with pytest.raises(ValueError):
            validate_frontend_reset_base_url(bad, production_like=True)

    from config import settings as _settings

    with (
        patch.object(_settings, "APP_ENV", "production"),
        patch.object(_settings, "HOST_MODE", "cloud"),
        patch.object(_settings, "AUTH_PROVIDER", "password"),
        patch.object(_settings, "DEBUG", False),
        patch.object(_settings, "JWT_SECRET", "very-strong-production-secret-key-over-32-chars!"),
        patch.object(_settings, "DB_PASSWORD", "StrongDbPassword!9"),
        patch.object(_settings, "API_BASE", "https://api.nanshan.gov.cn"),
        patch.object(_settings, "REDIS_ENABLED", True),
        patch.object(_settings, "FRONTEND_URL", "http://localhost:5173"),
        patch.object(_settings, "EMAIL_ENABLED", True),
        patch.object(_settings, "EMAIL_PROVIDER", "smtp"),
        patch.object(_settings, "SMTP_HOST", "smtp.exmail.qq.com"),
        patch.object(_settings, "SMTP_PORT", 465),
        patch.object(_settings, "SMTP_USER", "no-reply@example.com"),
        patch.object(_settings, "SMTP_PASSWORD", "smtp-password"),
    ):
        with pytest.raises(SystemExit) as sys_exc:
            assert_environment()
        assert sys_exc.value.code == 1


def test_normalize_email_and_templates_security():
    norm = normalize_email("  Alice.Zhang+security@MAIL.XN--FIQS8S  ")
    assert norm == "alice.zhang+security@mail.xn--fiqs8s"
    assert email_domain(norm) == "mail.xn--fiqs8s"

    with pytest.raises(BizError):
        normalize_email("bad\r\nheader@example.com")
    with pytest.raises(BizError):
        normalize_email("no-tld@localhost")

    otp_mail = render_otp_email("rebind_email", "004219", 300)
    assert "004219" not in otp_mail.subject
    assert "004219" in otp_mail.html_body
    assert "004219" in otp_mail.text_body
    assert "<script" not in otp_mail.html_body.lower()
    assert "<img" not in otp_mail.html_body.lower()

    link_mail = render_password_recovery_link_email(
        'https://tech.example.com/reset-password#challengeId=1&token="bad', 300
    )
    assert "&quot;" in link_mail.html_body
    assert "http://" not in link_mail.html_body

    notice = render_security_notification_email("email_rebound", "<2026-11-24>")
    assert "&lt;2026-11-24&gt;" in notice.html_body
