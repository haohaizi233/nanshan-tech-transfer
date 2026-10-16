"""Validated request bodies for organization membership workflows."""


from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid")


class VersionRequest(_Request):
    version: int = Field(..., ge=1, strict=True)


class RejectionRequest(VersionRequest):
    reason: str = Field(..., min_length=1, max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reason 不能为空")
        return value


class RevocationRequest(RejectionRequest):
    pass


class MembershipApplicationRequest(_Request):
    orgId: int = Field(..., ge=1)
    realName: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=128)
    workEmail: str | None = Field(None, max_length=128)
    proofMaterial: str | None = Field(None, max_length=10_000)
    applyNote: str | None = Field(None, max_length=2000)


class MembershipReviewRequest(VersionRequest):
    pass


class MembershipRejectionRequest(RejectionRequest):
    pass


class MembershipRevocationRequest(RevocationRequest):
    pass


class OrganizationAdminApplicationRequest(_Request):
    orgId: int = Field(..., ge=1)
    realName: str | None = Field(None, max_length=64)
    department: str | None = Field(None, max_length=128)
    title: str | None = Field(None, max_length=128)
    workEmail: str | None = Field(None, max_length=128)
    proofMaterial: str | None = Field(None, max_length=10_000)
    reason: str | None = Field(None, max_length=2000)


class OrganizationAdminReviewRequest(VersionRequest):
    pass


class OrganizationAdminRejectionRequest(RejectionRequest):
    pass


class OrganizationAdminGrantRequest(VersionRequest):
    pass


class OrganizationAdminRevocationRequest(RevocationRequest):
    pass


class OrganizationApplicationRequest(_Request):
    requestedName: str = Field(..., min_length=1, max_length=128)
    requestedType: str | None = Field(None, max_length=32)
    creditCode: str | None = Field(None, max_length=64)
    website: str | None = Field(None, max_length=256)
    region: str | None = Field(None, max_length=64)
    address: str | None = Field(None, max_length=256)
    contactName: str | None = Field(None, max_length=64)
    contactPhone: str | None = Field(None, max_length=32)
    contactEmail: str | None = Field(None, max_length=128)
    proofMaterial: str | None = Field(None, max_length=10_000)

    @field_validator("requestedName")
    @classmethod
    def requested_name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("requestedName 不能为空")
        return value


class OrganizationApplicationReviewRequest(VersionRequest):
    pass


class OrganizationApplicationRejectionRequest(RejectionRequest):
    pass
