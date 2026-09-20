from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from config import (
    settings,
    MOCK_ISSUER,
    MOCK_SUBJECT,
    MOCK_DISPLAY_NAME,
    MOCK_TICKET_PREFIX,
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
    if settings.AUTH_PROVIDER == "mock":
        if settings.is_production_like:
            raise RuntimeError(
                f"[FATAL] MockIdentityProvider 不允许在 {settings.APP_ENV} 环境运行"
            )
        return MockIdentityProvider()
    if settings.AUTH_PROVIDER == "wechat":
        # 微信 code2session 登录尚未接入：需 AppID/AppSecret + 小程序 code 换 openid。
        # 当前生产正式登录方式为手机号 + 密码（routes/auth.py 的 login/register）。
        # 接入微信登录时在此返回 WeChatIdentityProvider()，并补 .env 配置。
        raise RuntimeError(
            "微信登录尚未实现；当前正式登录方式为手机号 + 密码（AUTH_PROVIDER=mock 仅限本地）"
        )
    raise RuntimeError(f"未实现的 AUTH_PROVIDER: {settings.AUTH_PROVIDER}")
