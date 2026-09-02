from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from config import (
    APP_ENV,
    AUTH_PROVIDER,
    MOCK_ISSUER,
    MOCK_SUBJECT,
    MOCK_DISPLAY_NAME,
    MOCK_TICKET_PREFIX,
    PRODUCTION_ENVS,
)
from core.errors import BizError, TT_AUTH_40103


@dataclass
class ExternalIdentity:
    issuer: str
    tenant_id: str
    external_subject: str
    display_name: Optional[str]


class IdentityProvider(ABC):
    @abstractmethod
    def verify(self, host_credential: str) -> ExternalIdentity:
        ...


class MockIdentityProvider(IdentityProvider):
    ISSUER = MOCK_ISSUER
    TENANT_ID = "default"

    def verify(self, host_credential: str) -> ExternalIdentity:
        if not host_credential or not host_credential.startswith(MOCK_TICKET_PREFIX):
            code, message, status = TT_AUTH_40103
            raise BizError(
                code, f"Mock 票据无效，需以 '{MOCK_TICKET_PREFIX}' 开头", status
            )
        subject = host_credential[len(MOCK_TICKET_PREFIX):]
        if not subject:
            subject = MOCK_SUBJECT
        return ExternalIdentity(
            issuer=self.ISSUER,
            tenant_id=self.TENANT_ID,
            external_subject=subject,
            display_name=MOCK_DISPLAY_NAME,
        )


def get_identity_provider() -> IdentityProvider:
    if AUTH_PROVIDER == "mock":
        if APP_ENV in PRODUCTION_ENVS:
            raise RuntimeError(
                f"[FATAL] MockIdentityProvider 不允许在 {APP_ENV} 环境运行"
            )
        return MockIdentityProvider()
    raise RuntimeError(f"未实现的 AUTH_PROVIDER: {AUTH_PROVIDER}")
