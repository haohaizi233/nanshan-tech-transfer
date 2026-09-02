from dataclasses import dataclass, field
from typing import Optional


@dataclass
class IdentityContext:
    userId: int
    issuer: str
    externalSubject: str
    tenantId: str
    displayName: Optional[str] = None
    roles: list[str] = field(default_factory=lambda: ["user"])

    def to_dict(self):
        return {
            "userId": self.userId,
            "issuer": self.issuer,
            "externalSubject": self.externalSubject,
            "tenantId": self.tenantId,
            "displayName": self.displayName,
            "roles": self.roles,
        }
