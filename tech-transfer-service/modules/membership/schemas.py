"""Validated request bodies for organization membership workflows."""

from typing import Optional

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
    realName: Optional[str] = Field(None, max_length=64)
    department: Optional[str] = Field(None, max_length=128)
    title: Optional[str] = Field(None, max_length=128)
    workEmail: Optional[str] = Field(None, max_length=128)
    proofMaterial: Optional[str] = Field(None, max_length=10_000)
    applyNote: Optional[str] = Field(None, max_length=2000)


class MembershipReviewRequest(VersionRequest):
    pass


class MembershipRejectionRequest(RejectionRequest):
    pass


class MembershipRevocationRequest(RevocationRequest):
    pass


class OrganizationAdminApplicationRequest(_Request):
    orgId: int = Field(..., ge=1)
    realName: Optional[str] = Field(None, max_length=64)
    department: Optional[str] = Field(None, max_length=128)
    title: Optional[str] = Field(None, max_length=128)
    workEmail: Optional[str] = Field(None, max_length=128)
    proofMaterial: Optional[str] = Field(None, max_length=10_000)
    reason: Optional[str] = Field(None, max_length=2000)


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
    requestedType: Optional[str] = Field(None, max_length=32)
    creditCode: Optional[str] = Field(None, max_length=64)
    website: Optional[str] = Field(None, max_length=256)
    region: Optional[str] = Field(None, max_length=64)
    address: Optional[str] = Field(None, max_length=256)
    contactName: Optional[str] = Field(None, max_length=64)
    contactPhone: Optional[str] = Field(None, max_length=32)
    contactEmail: Optional[str] = Field(None, max_length=128)
    proofMaterial: Optional[str] = Field(None, max_length=10_000)

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
