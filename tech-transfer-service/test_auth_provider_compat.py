import pytest

from config import settings
from core.errors import BizError
from modules.identity.provider import MockIdentityProvider, get_identity_provider


def test_local_mock_provider_accepts_only_local_tickets(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "local")
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "mock")

    provider = get_identity_provider()

    assert isinstance(provider, MockIdentityProvider)
    assert provider.verify("local-dev-ticket-test-user").external_subject == "test-user"
    with pytest.raises(BizError, match="Mock 票据无效"):
        provider.verify("arbitrary-token")


def test_ainanshan_provider_is_rejected_until_gateway_is_implemented(monkeypatch):
    monkeypatch.setattr(settings, "APP_ENV", "local")
    monkeypatch.setattr(settings, "AUTH_PROVIDER", "ainanshan")

    with pytest.raises(RuntimeError, match="未实现的 AUTH_PROVIDER: ainanshan"):
        get_identity_provider()
