from fastapi import APIRouter, Depends, Request

from config import settings
from core.contact_validation import normalize_email
from core.errors import BizError
from core.middleware import identity
from core.request_schemas import (
    ChangePasswordRequest,
    ContactChallengeRequest,
    ContactVerifyRequest,
    ProfileUpdateRequest,
    StepUpChallengeRequest,
    StepUpVerifyRequest,
)
from core.response import get_request_id, success
from modules.achievement.service import list_my_achievements
from modules.cooperation.service import list_my_intents
from modules.demand.service import list_my_demands
from modules.favorite.service import list_my_favorites
from modules.identity.service import change_password
from modules.profile.service import get_my_profile, update_my_profile
from modules.security.delivery_models import DeliveryStageError
from modules.security.email_gateway import email_request_gate
from modules.security.idempotency import (
    build_idempotency_scope,
    claim_http_idempotency,
    compute_request_fingerprint,
    extract_idempotency_key,
    finalize_http_idempotency,
    mark_http_idempotency_unknown,
    release_http_idempotency_on_pre_provider_failure,
)
from modules.security.rate_limiter import check_verify_challenge_rate, limiter
from modules.security.service import (
    get_security_summary,
    revoke_all_user_sessions,
    start_contact_binding_challenge,
    verify_and_bind_contact,
)
from modules.security.sms_gateway import SendContext, normalize_phone, request_gate
from modules.security.sms_request import SmsRequestContext, validate_sms_request
from modules.security.step_up import (
    issue_step_up_grant,
    session_context_from_request,
    session_fingerprint_from_request,
    start_step_up_challenge,
)

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
def get_my_security(request: Request, user: dict = Depends(identity)):
    sess_ctx = session_context_from_request(request, user["userId"])
    return success(
        get_security_summary(
            user["userId"],
            auth_time=sess_ctx.auth_time if sess_ctx else None,
            has_sid=(sess_ctx.sid is not None) if sess_ctx else False,
        )
    )


@router.post("/security/step-up/challenge", summary="发起敏感操作二次认证验证码（原安全邮箱或手机）")
def post_step_up_challenge(
    body: StepUpChallengeRequest,
    request: Request,
    user: dict = Depends(identity),
    context: SmsRequestContext = Depends(validate_sms_request),
):
    sess_ctx = session_context_from_request(request, user["userId"])
    ctx = SendContext(context.ip, context.device_id, context.request_id)
    target_norm = ""
    if body.targetContact and body.targetContact.strip():
        target_norm = (
            str(normalize_email(body.targetContact))
            if "@" in body.targetContact or body.purpose in {"bind_email", "rebind_email"}
            else body.targetContact.strip().lower()
        )
    if body.method == "old_email_otp" and not settings.EMAIL_ENABLED:
        raise BizError("TT_COMMON_50301", "邮箱安全验证功能暂未开放", 503)

    idem_key = extract_idempotency_key(request)
    if idem_key:
        limiter.check(f"step_up_ch_http:user:{user['userId']}", limit=60, window_s=60)
        ch = "email_otp" if body.method == "old_email_otp" else "sms"
        req_hash = compute_request_fingerprint(
            channel=ch,
            purpose=f"step_up:{body.purpose}:{body.method}",
            normalized_account=str(user["userId"]),
            normalized_destination=target_norm,
        )
        scope = build_idempotency_scope(
            "/me/security/step-up/challenge",
            user_id=user["userId"],
            session_id=sess_ctx.sid if sess_ctx else None,
        )
        claim = claim_http_idempotency(
            key=idem_key,
            scope=scope,
            request_hash=req_hash,
            channel=ch,
            purpose=body.purpose,
            request_id=context.request_id,
            initial_state="idem_pending",
        )
        if claim.replay:
            if claim.state == "unknown":
                raise BizError("TT_COMMON_50301", "原验证码发送结果待确认，请稍后刷新或使用新请求", 503)
            if claim.state == "failed":
                raise BizError("TT_COMMON_50301", "原请求处理失败，请更换幂等键重试", 503)
            if claim.cached_response:
                return success(claim.cached_response)
            raise BizError("TT_COMMON_40901", "同一请求正在处理中，请稍候", 409, details={"inFlight": True})
        try:
            if body.method == "old_email_otp":
                email_request_gate(ctx, str(user["userId"]), purpose="step_up_auth")
            else:
                request_gate(ctx, str(user["userId"]), purpose="bind_phone")
            res = start_step_up_challenge(
                user["userId"],
                body.purpose,
                body.method,
                ctx,
                target_contact=body.targetContact,
                session_ctx=sess_ctx,
                idempotency_claim=claim,
            )
        except Exception as exc:
            if getattr(exc, "outcome_unknown", False):
                mark_http_idempotency_unknown(claim, getattr(exc, "reason_code", "PROVIDER_OUTCOME_UNKNOWN"))
            elif getattr(exc, "request_attempted", False):
                try:
                    finalize_http_idempotency(
                        claim,
                        {"rejected": True, "reasonCode": getattr(exc, "reason_code", "PROVIDER_REJECTED")},
                        state="failed",
                        execution_stage="provider_rejected",
                    )
                except Exception:
                    mark_http_idempotency_unknown(claim, "PROVIDER_REJECTED_PERSIST_FAILED")
            else:
                release_http_idempotency_on_pre_provider_failure(claim, getattr(exc, "reason_code", type(exc).__name__))
            raise
        try:
            finalize_http_idempotency(claim, res, state="completed", execution_stage="response_persisted")
        except Exception:
            mark_http_idempotency_unknown(claim, "IDEMPOTENCY_FINALIZE_FAILED", challenge_id=res.get("challengeId"))
            raise DeliveryStageError(
                "idempotency_persist",
                "IDEMPOTENCY_FINALIZE_FAILED",
                outcome_unknown=True,
                provider_called=True,
            ) from None
        return success(res)

    if body.method == "old_email_otp":
        email_request_gate(ctx, str(user["userId"]), purpose="step_up_auth")
    else:
        request_gate(ctx, str(user["userId"]), purpose="bind_phone")
    return success(
        start_step_up_challenge(
            user["userId"],
            body.purpose,
            body.method,
            ctx,
            target_contact=body.targetContact,
            session_ctx=sess_ctx,
        )
    )


@router.post("/security/step-up/verify", summary="核验二次身份认证并签发短期 Step-up Grant")
def post_step_up_verify(
    body: StepUpVerifyRequest,
    request: Request,
    user: dict = Depends(identity),
):
    limiter.check(f"step_up_verify:user:{user['userId']}", limit=10, window_s=300)
    sess_ctx = session_context_from_request(request, user["userId"])
    return success(
        issue_step_up_grant(
            user["userId"],
            purpose=body.purpose,
            method=body.method,
            session_fingerprint=session_fingerprint_from_request(request, user["userId"], purpose=body.purpose),
            session_ctx=sess_ctx,
            auth_time=sess_ctx.auth_time if sess_ctx else None,
            current_password=body.currentPassword,
            challenge_id=body.challengeId,
            code=body.code,
            target_contact=body.targetContact,
            request_id=get_request_id(),
        )
    )


@router.post("/security/contact/challenge", summary="发起绑定/换绑安全手机号或安全邮箱挑战（发送验证码）")
def post_contact_challenge(
    body: ContactChallengeRequest,
    request: Request,
    user: dict = Depends(identity),
    context: SmsRequestContext = Depends(validate_sms_request),
):
    sess_ctx = session_context_from_request(request, user["userId"])
    ctx = SendContext(context.ip, context.device_id, context.request_id)
    if body.contactType == "phone":
        norm_dest = normalize_phone(body.contactValue)
        ch = "sms"
        purpose = "bind_phone"
    else:
        if not settings.EMAIL_ENABLED:
            raise BizError("TT_COMMON_50301", "邮箱安全验证功能暂未开放", 503)
        norm_dest = str(normalize_email(body.contactValue))
        ch = "email_otp"
        purpose = "bind_email"

    sess_fp = session_fingerprint_from_request(request, user["userId"])
    idem_key = extract_idempotency_key(request)
    if idem_key:
        limiter.check(f"contact_ch_http:user:{user['userId']}", limit=60, window_s=60)
        req_hash = compute_request_fingerprint(
            channel=ch,
            purpose=purpose,
            normalized_account=str(user["userId"]),
            normalized_destination=norm_dest,
        )
        scope = build_idempotency_scope(
            "/me/security/contact/challenge",
            user_id=user["userId"],
            session_id=sess_ctx.sid if sess_ctx else None,
        )
        claim = claim_http_idempotency(
            key=idem_key,
            scope=scope,
            request_hash=req_hash,
            channel=ch,
            purpose=purpose,
            request_id=context.request_id,
            initial_state="idem_pending",
        )
        if claim.replay:
            if claim.state == "unknown":
                raise BizError("TT_COMMON_50301", "原验证码发送结果待确认，请勿重复发送", 503)
            if claim.state == "failed":
                raise BizError("TT_COMMON_50301", "原请求处理失败，请更换幂等键重试", 503)
            if claim.cached_response:
                return success(claim.cached_response)
            raise BizError("TT_COMMON_40901", "同一请求正在处理中，请稍候", 409, details={"inFlight": True})
        try:
            if body.contactType == "phone":
                request_gate(ctx, str(user["userId"]), phone=norm_dest, purpose="bind_phone")
            else:
                email_request_gate(ctx, str(user["userId"]), email=norm_dest, purpose="bind_email")
            res = start_contact_binding_challenge(
                user["userId"],
                body.contactType,
                body.contactValue,
                context=ctx,
                step_up_grant=body.stepUpGrant,
                session_fingerprint=sess_fp,
                session_ctx=sess_ctx,
                idempotency_claim=claim,
            )
        except Exception as exc:
            if getattr(exc, "outcome_unknown", False):
                mark_http_idempotency_unknown(claim, getattr(exc, "reason_code", "PROVIDER_OUTCOME_UNKNOWN"))
            elif getattr(exc, "request_attempted", False):
                try:
                    finalize_http_idempotency(
                        claim,
                        {"rejected": True, "reasonCode": getattr(exc, "reason_code", "PROVIDER_REJECTED")},
                        state="failed",
                        execution_stage="provider_rejected",
                    )
                except Exception:
                    mark_http_idempotency_unknown(claim, "PROVIDER_REJECTED_PERSIST_FAILED")
            else:
                release_http_idempotency_on_pre_provider_failure(claim, getattr(exc, "reason_code", type(exc).__name__))
            raise
        try:
            finalize_http_idempotency(claim, res, state="completed", execution_stage="response_persisted")
        except Exception:
            mark_http_idempotency_unknown(claim, "IDEMPOTENCY_FINALIZE_FAILED", challenge_id=res.get("challengeId"))
            raise DeliveryStageError(
                "idempotency_persist",
                "IDEMPOTENCY_FINALIZE_FAILED",
                outcome_unknown=True,
                provider_called=True,
            ) from None
        return success(res)

    if body.contactType == "phone":
        request_gate(ctx, str(user["userId"]), phone=norm_dest, purpose="bind_phone")
    else:
        email_request_gate(ctx, str(user["userId"]), email=norm_dest, purpose="bind_email")
    return success(
        start_contact_binding_challenge(
            user["userId"],
            body.contactType,
            body.contactValue,
            context=ctx,
            step_up_grant=body.stepUpGrant,
            session_fingerprint=sess_fp,
            session_ctx=sess_ctx,
        )
    )


@router.post("/security/contact/verify", summary="核验验证码并确权绑定/换绑安全手机号或邮箱")
def post_contact_verify(
    body: ContactVerifyRequest,
    request: Request,
    user: dict = Depends(identity),
):
    check_verify_challenge_rate(body.challengeId)
    sess_ctx = session_context_from_request(request, user["userId"])
    return success(
        verify_and_bind_contact(
            user["userId"],
            body.challengeId,
            body.code,
            body.contactValue,
            step_up_grant=body.stepUpGrant,
            session_fingerprint=session_fingerprint_from_request(request, user["userId"]),
            session_ctx=sess_ctx,
        )
    )


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
