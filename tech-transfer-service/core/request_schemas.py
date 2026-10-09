"""OpenAPI 请求体声明。

业务校验仍在 service 层；这里只把 camelCase 字段暴露给 /docs，
extra=allow 保证未列出的字段仍会原样传给现有 json_body 逻辑。
"""

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def as_dict(self) -> dict:
        return self.model_dump(exclude_unset=True)


class VersionBody(RequestBody):
    version: int = Field(..., ge=1, description="乐观锁版本")


class ReasonVersionBody(VersionBody):
    reason: Optional[str] = Field(None, description="原因说明")
    reasonCode: Optional[str] = None
    reasonNote: Optional[str] = None


# ── auth ────────────────────────────────────────────────────

class LoginRequest(RequestBody):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {"username": "admin", "password": "Admin@2026"},
        },
    )
    username: Optional[str] = Field(None, description="后台登录账号")
    phone: Optional[str] = Field(None, description="小程序手机号")
    password: Optional[str] = Field(None, description="密码")


class RegisterRequest(RequestBody):
    username: Optional[str] = Field(None, description="后台用户名注册")
    phone: Optional[str] = Field(None, description="小程序手机号注册")
    password: str = Field(..., min_length=1, description="密码")
    displayName: Optional[str] = None
    email: Optional[str] = None


class BootstrapRequest(RequestBody):
    hostCredential: str = Field(..., description="宿主身份凭证")


class RefreshTokenRequest(RequestBody):
    refreshToken: str = Field(..., description="refreshToken")


# ── me ──────────────────────────────────────────────────────

class ProfileUpdateRequest(RequestBody):
    version: int = Field(..., ge=1)
    displayName: Optional[str] = None
    userType: Optional[str] = Field(None, description="enterprise_staff/researcher/investor/service_org/other")
    subjectType: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    wechat: Optional[str] = None
    companyText: Optional[str] = None
    orgTitle: Optional[str] = None
    businessCapabilities: Optional[list[str]] = None


class ChangePasswordRequest(RequestBody):
    currentPassword: str = Field(..., description="当前密码")
    newPassword: str = Field(..., description="新密码")


# ── achievement / demand 内容 ───────────────────────────────

class InventorRef(RequestBody):
    name: str
    orgName: Optional[str] = None
    personType: Optional[str] = None
    sortOrder: Optional[int] = None
    department: Optional[str] = None
    title: Optional[str] = None
    bio: Optional[str] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    homepageUrl: Optional[str] = None
    avatarFileId: Optional[int] = None


class MediaItem(RequestBody):
    fileId: int
    role: Optional[str] = None
    caption: Optional[str] = None
    sortOrder: Optional[int] = None


class AchievementWriteRequest(RequestBody):
    title: Optional[str] = None
    titleEn: Optional[str] = None
    version: Optional[int] = Field(None, ge=1)
    maturityLevel: Optional[str] = Field(None, description="01_idea ~ 06_mass_done")
    pricingMode: Optional[str] = None
    techIntro: Optional[str] = None
    techRoute: Optional[str] = None
    maturityDesc: Optional[str] = None
    sourceOrgName: Optional[str] = None
    achievementKind: Optional[str] = None
    applicationFields: Optional[list[str]] = None
    innovationPoints: Optional[list[str]] = None
    priceMinWan: Optional[float] = None
    priceMaxWan: Optional[float] = None
    categoryId: Optional[int] = None
    orgId: Optional[int] = None
    ownerUserId: Optional[int] = None
    saveAction: Optional[str] = Field(None, description="draft/submit/publish")
    contactName: Optional[str] = None
    contactTitle: Optional[str] = None
    contactPhone: Optional[str] = None
    contactEmail: Optional[str] = None
    contactWechat: Optional[str] = None
    inventorRefs: Optional[list[InventorRef]] = None
    sections: Optional[list[dict[str, Any]]] = None
    patents: Optional[list[dict[str, Any]]] = None
    links: Optional[list[dict[str, Any]]] = None
    media: Optional[list[MediaItem]] = None
    industryIds: Optional[list[int]] = None


class AchievementCreateRequest(AchievementWriteRequest):
    title: str = Field(..., min_length=1, max_length=200)


class AchievementUpdateRequest(AchievementWriteRequest):
    version: int = Field(..., ge=1)


class AchievementOfflineRequest(VersionBody):
    reason: Optional[str] = None
    reasonCode: Optional[str] = None


class DemandWriteRequest(RequestBody):
    title: Optional[str] = None
    description: Optional[str] = None
    version: Optional[int] = Field(None, ge=1)
    region: Optional[str] = None
    deadlineDesc: Optional[str] = None
    contactName: Optional[str] = None
    contactTitle: Optional[str] = None
    contactPhone: Optional[str] = None
    contactEmail: Optional[str] = None
    contactWechat: Optional[str] = None
    coopMode: Optional[list[str]] = None
    budgetMinWan: Optional[float] = None
    budgetMaxWan: Optional[float] = None
    budgetNegotiable: Optional[bool] = None
    expectDeadline: Optional[str] = Field(None, description="YYYY-MM-DD")
    categoryId: Optional[int] = None
    categoryName: Optional[str] = None
    orgId: Optional[int] = None
    orgName: Optional[str] = None
    orgIntro: Optional[str] = None
    ownerUserId: Optional[int] = None
    saveAction: Optional[str] = None
    tags: Optional[list[str]] = None
    attachments: Optional[list[MediaItem]] = None


class DemandCreateRequest(DemandWriteRequest):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)


class DemandUpdateRequest(DemandWriteRequest):
    version: int = Field(..., ge=1)


# ── cooperation ─────────────────────────────────────────────

class CooperationCreateRequest(RequestBody):
    targetType: str = Field(..., description="achievement 或 demand")
    targetId: int = Field(..., ge=1)
    intentType: Optional[str] = None
    message: Optional[str] = None
    contactShareConsent: bool = Field(..., description="必须为 true")


class CooperationCompleteRequest(VersionBody):
    remark: Optional[str] = None
    outcome: Optional[str] = None


# ── institution registration ────────────────────────────────

class InstitutionRegistrationRequest(RequestBody):
    kind: str = Field(..., description="university/institute/enterprise/invest/service/other")
    name: str = Field(..., min_length=1, max_length=128)
    contactName: str = Field(..., min_length=1, max_length=64)
    contactPhone: str
    username: str
    password: str
    region: Optional[str] = None
    creditCode: Optional[str] = None
    email: Optional[str] = None
    intro: Optional[str] = None


# ── notification / ai / patent ──────────────────────────────

class NotificationReadRequest(RequestBody):
    category: Optional[str] = Field(None, description="按分类标记已读，如 cooperation")


class EvaluationTaskRequest(RequestBody):
    achievementId: int = Field(..., ge=1)


class AiChatRequest(RequestBody):
    message: str = Field(..., min_length=1)


class AiMatchRequest(RequestBody):
    demandId: int = Field(..., ge=1)


class PatentSearchHistoryRequest(RequestBody):
    mode: str = Field(..., description="keyword 或 assignee")
    keyword: str = Field(..., min_length=1, max_length=128)


# ── admin ───────────────────────────────────────────────────

class ReviewRejectRequest(VersionBody):
    reason: str = Field(..., min_length=1, description="驳回原因")


class InstitutionRejectRequest(RequestBody):
    reason: Optional[str] = None


class InstitutionImportRequest(RequestBody):
    items: list[dict[str, Any]] = Field(..., min_length=1, description="机构导入条目")


class AssistStatusRequest(RequestBody):
    assistStatus: str = Field(..., description="queued/contacting/waiting_reply/target_agreed/target_rejected/unreachable")
    note: Optional[str] = None
    nextFollowupAt: Optional[str] = None


class AssistTransitionRequest(VersionBody):
    action: str = Field(..., description="accept/reject/confirm/cancel/complete")
    reason: Optional[str] = None
    confirmationNote: Optional[str] = None
    remark: Optional[str] = None
    outcome: Optional[str] = None
