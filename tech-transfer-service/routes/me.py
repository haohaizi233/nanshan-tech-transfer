from fastapi import APIRouter, Depends, Request

from core.middleware import identity
from core.request_schemas import (
    ChangePasswordRequest,
    ContactChallengeRequest,
    ContactVerifyRequest,
    ProfileUpdateRequest,
)
from core.response import success
from modules.achievement.service import list_my_achievements
from modules.cooperation.service import list_my_intents
from modules.demand.service import list_my_demands
from modules.favorite.service import list_my_favorites
from modules.identity.service import change_password
from modules.profile.service import get_my_profile, update_my_profile
from modules.security.rate_limiter import (
    check_send_code_rate,
    check_verify_challenge_rate,
)
from modules.security.service import (
    get_security_summary,
    revoke_all_user_sessions,
    start_contact_binding_challenge,
    verify_and_bind_contact,
)
from modules.security.sms_gateway import SendContext, normalize_phone, request_gate
from modules.security.sms_request import SmsRequestContext, validate_sms_request

router = APIRouter(prefix="/api/tech-transfer/v1/me", tags=["me"])


@router.get("")
def get_me(user: dict = Depends(identity)):
    profile = get_my_profile(user["userId"])
    return success(profile)


@router.patch("/profile")
def patch_my_profile(body: ProfileUpdateRequest, user: dict = Depends(identity)):
    profile = update_my_profile(user["userId"], body.as_dict())
    return success(profile)


@router.post("/password")
def post_my_password(body: ChangePasswordRequest, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = change_password(
        user["userId"],
        payload.get("currentPassword") or "",
        payload.get("newPassword") or "",
    )
    return success(result, "密码已更新")


@router.get("/security", summary="获取当前用户账号安全中心数据")
def get_my_security(user: dict = Depends(identity)):
    return success(get_security_summary(user["userId"]))


@router.post("/security/contact/challenge", summary="发起绑定安全手机号或安全邮箱挑战（发送验证码）")
def post_contact_challenge(
    body: ContactChallengeRequest,
    request: Request,
    user: dict = Depends(identity),
    context: SmsRequestContext = Depends(validate_sms_request),
):
    ctx = SendContext(context.ip, context.device_id, context.request_id)
    if body.contactType == "phone":
        phone = normalize_phone(body.contactValue)
        request_gate(ctx, str(user["userId"]), phone=phone, purpose="bind_phone")
    else:
        check_send_code_rate(request, body.contactValue)
    return success(start_contact_binding_challenge(user["userId"], body.contactType, body.contactValue, context=ctx))


@router.post("/security/contact/verify", summary="核验验证码并确权绑定安全手机号或邮箱")
def post_contact_verify(body: ContactVerifyRequest, user: dict = Depends(identity)):
    check_verify_challenge_rate(body.challengeId)
    return success(verify_and_bind_contact(user["userId"], body.challengeId, body.code, body.contactValue))


@router.post("/security/revoke-sessions", summary="退出全部其他设备会话（即时失效旧 Token）")
def post_revoke_all_sessions(user: dict = Depends(identity)):
    return success(revoke_all_user_sessions(user["userId"]))


@router.get("/demands")
def get_my_demands(request: Request, user: dict = Depends(identity)):
    return success(list_my_demands(user["userId"], request.query_params))


@router.get("/achievements")
def get_my_achievements(request: Request, user: dict = Depends(identity)):
    return success(list_my_achievements(user["userId"], request.query_params))


@router.get("/favorites")
def get_my_favorites(request: Request, user: dict = Depends(identity)):
    return success(list_my_favorites(user["userId"], request.query_params))


@router.get("/cooperations")
def get_my_cooperations(request: Request, user: dict = Depends(identity)):
    return success(list_my_intents(user["userId"], request.query_params))
