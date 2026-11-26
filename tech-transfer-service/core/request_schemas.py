"""OpenAPI 请求体声明。

业务校验仍在 service 层；这里只把 camelCase 字段暴露给 /docs，
extra=allow 保证未列出的字段仍会原样传给现有 json_body 逻辑。
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class RequestBody(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    def as_dict(self) -> dict:
        return self.model_dump(exclude_unset=True)


class VersionBody(RequestBody):
    version: int = Field(..., ge=1, description="乐观锁版本")


class ReasonVersionBody(VersionBody):
    reason: str | None = Field(None, description="原因说明")
    reasonCode: str | None = None
    reasonNote: str | None = None


# ── auth ────────────────────────────────────────────────────


class LoginRequest(RequestBody):
    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {"username": "admin", "password": "Admin@2026"},
        },
    )
    username: str | None = Field(None, description="后台登录账号")
    phone: str | None = Field(None, description="小程序手机号")
    password: str | None = Field(None, description="密码")


class RegistrationChallengeRequest(RequestBody):
    phone: str = Field(..., min_length=11, max_length=20)


class RegistrationProofRequest(RequestBody):
    challengeId: str = Field(..., pattern=r"^[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}$")
    code: str = Field(..., strict=True, pattern=r"^[0-9]{6}$")


class RegisterRequest(RegistrationProofRequest):
    username: str | None = Field(None, description="后台用户名注册")
    phone: str = Field(..., description="待确权的手机号")
    password: str = Field(..., min_length=1, description="密码")
    displayName: str | None = None
    email: str | None = None


class BootstrapRequest(RequestBody):
    hostCredential: str = Field(..., description="宿主身份凭证")


class RefreshTokenRequest(RequestBody):
    refreshToken: str = Field(..., description="refreshToken")


class WechatLoginRequest(RequestBody):
    loginCode: str = Field(..., min_length=1, max_length=512)
    phoneCode: str | None = Field(None, min_length=1, max_length=512)


class WechatBindRequest(WechatLoginRequest):
    phoneCode: str = Field(..., min_length=1, max_length=512)


class RecoveryStartRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    account: str = Field(..., min_length=1, max_length=128, description="用户名、手机号或邮箱")
    channel: Literal["sms", "email_otp", "email_link"] = "sms"


class RecoveryVerifyRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    challengeId: str = Field(..., description="挑战 UUID")
    code: str = Field(..., min_length=1, max_length=128, description="验证码或重置Token")


class RecoveryCompleteRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    recoveryGrant: str = Field(..., min_length=1, description="恢复授权凭证")
    newPassword: str = Field(..., min_length=8, max_length=128, description="新密码（8-128位）")


class WechatWebCallbackRequest(RequestBody):
    code: str = Field(..., min_length=1, description="微信开放平台授权码")
    state: str = Field(..., min_length=1, description="OAuth state 校验值")


class WechatWebBindRequest(RequestBody):
    bindingTicket: str = Field(..., min_length=1, description="绑定临时票据")


class ContactChallengeRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    contactType: Literal["phone", "email"]
    contactValue: str = Field(..., min_length=1, max_length=128, description="联系方式号码或邮箱")
    stepUpGrant: str | None = Field(None, min_length=1, max_length=256, description="换绑安全邮箱二次认证凭证")


class ContactVerifyRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    challengeId: str = Field(..., description="挑战 UUID")
    code: str = Field(..., min_length=1, max_length=128, description="收到的验证码")
    contactValue: str = Field(..., min_length=1, description="联系方式号码或邮箱")
    stepUpGrant: str | None = Field(None, min_length=1, max_length=256, description="换绑安全邮箱二次认证凭证")


class StepUpChallengeRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    purpose: Literal["bind_email", "rebind_email", "bind_phone", "rebind_phone"] = "rebind_email"
    method: Literal["old_email_otp", "old_phone_otp"]
    targetContact: str | None = Field(None, max_length=128)


class StepUpVerifyRequest(RequestBody):
    model_config = ConfigDict(extra="forbid", strict=True)
    purpose: Literal["bind_email", "rebind_email", "bind_phone", "rebind_phone"] = "rebind_email"
    method: Literal["password", "old_email_otp", "old_phone_otp", "recent_auth"]
    currentPassword: str | None = Field(None, max_length=128)
    challengeId: str | None = Field(None, max_length=64)
    code: str | None = Field(None, max_length=128)
    targetContact: str | None = Field(None, max_length=128)


# ── me ──────────────────────────────────────────────────────


class ProfileUpdateRequest(RequestBody):
    version: int = Field(..., ge=1)
    avatarFileId: int | None = Field(None, ge=1, strict=True)
    displayName: str | None = None
    userType: str | None = Field(None, description="enterprise_staff/researcher/investor/service_org/other")
    subjectType: str | None = None
    phone: str | None = None
    email: str | None = None
    wechat: str | None = None
    companyText: str | None = None
    orgTitle: str | None = None
    businessCapabilities: list[str] | None = None


class ChangePasswordRequest(RequestBody):
    currentPassword: str = Field("", description="当前密码；微信新账号首次设置时留空")
    newPassword: str = Field(..., description="新密码")


# ── achievement / demand 内容 ───────────────────────────────


class InventorRef(RequestBody):
    name: str
    orgName: str | None = None
    personType: str | None = None
    sortOrder: int | None = None
    department: str | None = None
    title: str | None = None
    bio: str | None = None
    phone: str | None = None
    email: str | None = None
    homepageUrl: str | None = None
    avatarFileId: int | None = None


class MediaItem(RequestBody):
    fileId: int
    role: str | None = None
    caption: str | None = None
    sortOrder: int | None = None


class AchievementWriteRequest(RequestBody):
    title: str | None = None
    titleEn: str | None = None
    version: int | None = Field(None, ge=1)
    maturityLevel: str | None = Field(None, description="01_idea ~ 06_mass_done")
    pricingMode: str | None = None
    techIntro: str | None = None
    techRoute: str | None = None
    maturityDesc: str | None = None
    sourceOrgName: str | None = None
    achievementKind: str | None = None
    applicationFields: list[str] | None = None
    innovationPoints: list[str] | None = None
    priceMinWan: float | None = None
    priceMaxWan: float | None = None
    categoryId: int | None = None
    orgId: int | None = None
    ownerUserId: int | None = None
    saveAction: str | None = Field(None, description="draft/submit/publish")
    contactName: str | None = None
    contactTitle: str | None = None
    contactPhone: str | None = None
    contactEmail: str | None = None
    contactWechat: str | None = None
    inventorRefs: list[InventorRef] | None = None
    sections: list[dict[str, Any]] | None = None
    patents: list[dict[str, Any]] | None = None
    links: list[dict[str, Any]] | None = None
    media: list[MediaItem] | None = None
    industryIds: list[int] | None = None


class AchievementCreateRequest(AchievementWriteRequest):
    title: str = Field(..., min_length=1, max_length=200)


class AchievementUpdateRequest(AchievementWriteRequest):
    version: int = Field(..., ge=1)


class AchievementOfflineRequest(VersionBody):
    reason: str | None = None
    reasonCode: str | None = None


class DemandWriteRequest(RequestBody):
    title: str | None = None
    description: str | None = None
    version: int | None = Field(None, ge=1)
    region: str | None = None
    deadlineDesc: str | None = None
    contactName: str | None = None
    contactTitle: str | None = None
    contactPhone: str | None = None
    contactEmail: str | None = None
    contactWechat: str | None = None
    coopMode: list[str] | None = None
    budgetMinWan: float | None = None
    budgetMaxWan: float | None = None
    budgetNegotiable: bool | None = None
    expectDeadline: str | None = Field(None, description="YYYY-MM-DD")
    categoryId: int | None = None
    categoryName: str | None = None
    orgId: int | None = None
    orgName: str | None = None
    orgIntro: str | None = None
    ownerUserId: int | None = None
    saveAction: str | None = None
    tags: list[str] | None = None
    attachments: list[MediaItem] | None = None


class DemandCreateRequest(DemandWriteRequest):
    title: str = Field(..., min_length=1, max_length=200)
    description: str = Field(..., min_length=1)


class DemandUpdateRequest(DemandWriteRequest):
    version: int = Field(..., ge=1)


# ── cooperation ─────────────────────────────────────────────


class CooperationCreateRequest(RequestBody):
    targetType: str = Field(..., description="achievement 或 demand")
    targetId: int = Field(..., ge=1)
    intentType: str | None = None
    message: str | None = None
    contactShareConsent: bool = Field(..., description="必须为 true")


class CooperationCompleteRequest(VersionBody):
    remark: str | None = None
    outcome: str | None = None


# ── institution registration ────────────────────────────────


class InstitutionRegistrationRequest(RegistrationProofRequest):
    kind: str = Field(..., description="university/institute/enterprise/invest/service/other")
    name: str = Field(..., min_length=1, max_length=128)
    contactName: str = Field(..., min_length=1, max_length=64)
    contactPhone: str
    username: str
    password: str
    region: str | None = None
    creditCode: str | None = None
    email: str | None = None
    intro: str | None = None


# ── notification / ai / patent ──────────────────────────────


class NotificationReadRequest(RequestBody):
    category: str | None = Field(None, description="按分类标记已读，如 cooperation")


class EvaluationTaskRequest(RequestBody):
    achievementId: int = Field(..., ge=1)


class AiChatReference(BaseModel):
    model_config = ConfigDict(extra="forbid")
    messageId: int = Field(..., ge=1, strict=True)
    cardType: Literal["achievement", "demand"]
    cardId: int = Field(..., ge=1, strict=True)


class AiChatRequest(RequestBody):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(..., min_length=1)
    reference: AiChatReference | None = None
    turnId: str | None = Field(
        None,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$",
        description="客户端生成的幂等问答轮次 ID",
    )


class AiMatchRequest(RequestBody):
    demandId: int = Field(..., ge=1)


class AiCardTarget(RequestBody):
    card_type: Literal["achievement", "demand"]
    id: int = Field(..., ge=1, strict=True)


class AiCardViewCountsRequest(RequestBody):
    cards: list[AiCardTarget] = Field(..., max_length=50)


class PatentSearchHistoryRequest(RequestBody):
    mode: str = Field(..., description="keyword 或 assignee")
    keyword: str = Field(..., min_length=1, max_length=128)


# ── admin ───────────────────────────────────────────────────


class ReviewRejectRequest(VersionBody):
    reason: str = Field(..., min_length=1, description="驳回原因")


class InstitutionRejectRequest(RequestBody):
    reason: str | None = None


class InstitutionImportRequest(RequestBody):
    items: list[dict[str, Any]] = Field(..., min_length=1, description="机构导入条目")


class AssistStatusRequest(RequestBody):
    assistStatus: str = Field(
        ..., description="queued/contacting/waiting_reply/target_agreed/target_rejected/unreachable"
    )
    note: str | None = None
    nextFollowupAt: str | None = None


class AssistTransitionRequest(VersionBody):
    action: str = Field(..., description="accept/reject/confirm/cancel/complete")
    reason: str | None = None
    confirmationNote: str | None = None
    remark: str | None = None
    outcome: str | None = None
