import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Request

from config import settings
from core.contact_validation import normalize_email
from core.errors import TT_AUTH_40105, TT_COMMON_40102, BizError, bootstrap_credential_invalid
from core.middleware import identity
from core.rate_limit import check_ip_rate, check_register_rate
from core.request_schemas import (
    BootstrapRequest,
    LoginRequest,
    RecoveryCompleteRequest,
    RecoveryStartRequest,
    RecoveryVerifyRequest,
    RefreshTokenRequest,
    RegisterRequest,
    RegistrationChallengeRequest,
    WechatBindRequest,
    WechatLoginRequest,
    WechatWebBindRequest,
    WechatWebCallbackRequest,
)
from core.response import get_request_id, success
from modules.identity.provider import get_identity_provider
from modules.identity.service import (
    bootstrap_session,
    login_phone_session,
    logout_session,
    password_login_session,
    refresh_session,
    register_password_user,
    register_user,
)
from modules.identity.wechat import wechat_login_enabled, wechat_login_session
from modules.identity.wechat_web import (
    bind_web_wechat,
    get_web_authorize_url,
    handle_web_callback,
    wechat_web_enabled,
)
from modules.security.email_gateway import email_request_gate
from modules.security.idempotency import (
    build_idempotency_scope,
    claim_http_idempotency,
    compute_request_fingerprint,
    extract_idempotency_key,
    finalize_http_idempotency,
    read_http_idempotency_record,
    release_http_idempotency_on_pre_provider_failure,
    wait_for_idempotency_settlement,
)
from modules.security.rate_limiter import check_verify_challenge_rate
from modules.security.registration import start_registration_challenge, verified_registration
from modules.security.service import (
    complete_password_recovery,
    get_recovery_capabilities,
    verify_recovery_challenge,
)
from modules.security.sms_gateway import (
    SendContext,
    enqueue_recovery_task,
    normalize_phone,
    recovery_response,
    request_gate,
    run_queued_recovery_task,
)
from modules.security.sms_request import SmsRequestContext, validate_sms_request

router = APIRouter(prefix="/api/tech-transfer/v1/auth", tags=["auth"])


@router.get("/wechat/config")
def wechat_config():
    return success({"enabled": wechat_login_enabled()})


@router.get("/wechat/web/config", summary="PC 微信扫码配置")
def wechat_web_config():
    from config import settings

    return success({"enabled": wechat_web_enabled(), "appid": settings.WECHAT_OPEN_APPID})


@router.get("/wechat/web/authorize", summary="获取 PC 微信扫码授权 URL")
def wechat_web_authorize(redirectUri: str):
    return success(get_web_authorize_url(redirectUri))


@router.post("/wechat/web/callback", summary="处理 PC 微信扫码回调")
def wechat_web_callback(body: WechatWebCallbackRequest, request: Request):
    check_ip_rate(request, "wechat_web_callback", limit=20, window_s=60)
    return success(handle_web_callback(body.code, body.state))


@router.post("/wechat/web/bind", summary="当前账号绑定 PC 微信扫码身份")
def wechat_web_bind(body: WechatWebBindRequest, user: dict = Depends(identity)):
    return success(bind_web_wechat(user["userId"], body.bindingTicket))


@router.get("/recovery/capabilities", summary="查询密码找回可用验证渠道能力")
def recovery_capabilities():
    return success(get_recovery_capabilities())


@router.post("/recovery/start", summary="发起密码找回（发送短信/邮件验证码或重置链接）")
def recovery_start(
    body: RecoveryStartRequest,
    request: Request,
    background: BackgroundTasks,
    context: SmsRequestContext = Depends(validate_sms_request),
):
    ctx = SendContext(context.ip, context.device_id, context.request_id)
    acct_raw = body.account.strip()
    acct_norm = acct_raw.lower()
    phone: str | None = None
    norm_email: str | None = None

    if body.channel == "sms":
        try:
            phone = normalize_phone(acct_raw)
            acct_norm = phone
        except BizError:
            phone = None
    else:
        if not settings.EMAIL_ENABLED:
            raise BizError("TT_COMMON_50301", "邮箱安全验证功能暂未开放", 503)
        if "@" in acct_raw:
            try:
                norm_email = str(normalize_email(acct_raw))
                acct_norm = norm_email
            except BizError:
                norm_email = None

    idem_key = extract_idempotency_key(request)
    if idem_key:
        # 幂等重放仍受请求级防洪水保护，绝不在基础安全门禁之前无条件放行
        check_ip_rate(request, "recovery_start_http", limit=60, window_s=60)
        req_hash = compute_request_fingerprint(
            channel=body.channel,
            purpose="password_recovery",
            normalized_account=acct_norm,
        )
        scope = build_idempotency_scope("/auth/recovery/start", client_ip=context.ip)
        challenge_id = str(uuid.uuid4())
        payload = {
            "account": acct_raw,
            "channel": body.channel,
            "ip": context.ip,
            "device_id": context.device_id,
            "request_id": context.request_id,
        }
        claim = claim_http_idempotency(
            key=idem_key,
            scope=scope,
            request_hash=req_hash,
            channel=body.channel,
            purpose="password_recovery",
            task_id=challenge_id,
            payload=payload,
            request_id=context.request_id,
            initial_state="idem_pending",
        )
        if claim.replay:
            if claim.state in ("idem_pending", "idempotent_pending") and not claim.cached_response:
                claim = wait_for_idempotency_settlement(claim, timeout_seconds=2.5)
            if claim.state in ("unknown", "legacy_unknown") or claim.execution_stage in (
                "provider_unknown",
                "legacy_unknown",
            ):
                raise BizError("TT_COMMON_50301", "原请求发送结果待确认，请稍后刷新或使用新请求", 503)
            if claim.state in ("failed", "failed_internal", "expired", "released") and not claim.cached_response:
                raise BizError("TT_COMMON_50301", "原请求处理失败，请更换幂等键重试", 503)
            if claim.state in ("idem_pending", "idempotent_pending") and not claim.cached_response:
                raise BizError("TT_COMMON_40901", "同一请求正在处理中，请稍候", 409, details={"inFlight": True})
            resp_data = claim.cached_response or recovery_response(claim.task_id or challenge_id, body.channel)
            return success(resp_data)

        try:
            if body.channel == "sms":
                request_gate(ctx, acct_raw.lower(), phone=phone)
            else:
                email_request_gate(
                    ctx,
                    acct_raw.lower(),
                    email=norm_email,
                    purpose="password_recovery",
                )
            resp_data = recovery_response(claim.task_id or challenge_id, body.channel)
            finalized = finalize_http_idempotency(claim, resp_data, state="queued", execution_stage="pre_provider")
            if not finalized:
                rec = read_http_idempotency_record(claim.task_id or challenge_id) if claim.task_id else None
                if rec and rec.get("state") in ("unknown", "legacy_unknown"):
                    raise BizError("TT_COMMON_50301", "原请求发送结果待确认，请稍后刷新或使用新请求", 503)
                if rec and isinstance(rec.get("response_payload"), dict):
                    return success(rec["response_payload"])
                raise BizError("TT_COMMON_50301", "请求幂等状态已失效，请更换幂等键重试", 503)
        except Exception as exc:
            release_http_idempotency_on_pre_provider_failure(
                claim,
                getattr(exc, "code", type(exc).__name__),
            )
            raise
        background.add_task(run_queued_recovery_task, claim.task_id or challenge_id)
        return success(resp_data)

    if body.channel == "sms":
        request_gate(ctx, acct_raw.lower(), phone=phone)
    else:
        email_request_gate(
            ctx,
            acct_raw.lower(),
            email=norm_email,
            purpose="password_recovery",
        )
    challenge_id = str(uuid.uuid4())
    enqueue_recovery_task(acct_raw, body.channel, challenge_id, ctx)
    background.add_task(run_queued_recovery_task, challenge_id)
    return success(recovery_response(challenge_id, body.channel))


@router.post("/recovery/verify", summary="核验找回挑战凭证，获取短期重置授权凭证")
def recovery_verify(body: RecoveryVerifyRequest, request: Request):
    check_verify_challenge_rate(body.challengeId)
    return success(verify_recovery_challenge(body.challengeId, body.code))


@router.post("/recovery/complete", summary="完成密码重置（单事务提交并失效全部旧会话）")
def recovery_complete(body: RecoveryCompleteRequest):
    return success(complete_password_recovery(body.recoveryGrant, body.newPassword))


@router.post("/wechat/login")
def wechat_login(body: WechatLoginRequest, request: Request):
    check_ip_rate(request, "wechat_login", limit=10, window_s=60)
    return success(wechat_login_session(body.loginCode, body.phoneCode))


@router.post("/wechat/bind")
def wechat_bind(body: WechatBindRequest, request: Request, user: dict = Depends(identity)):
    check_ip_rate(request, "wechat_bind", limit=5, window_s=60)
    return success(wechat_login_session(body.loginCode, body.phoneCode, bind_user_id=user["userId"]))


@router.post("/login", summary="登录（小程序传 phone 手机号 / 后台传 username 账号）")
def login(body: LoginRequest, request: Request):
    body = body.as_dict()
    phone = (body.get("phone") or "").strip()
    username = (body.get("username") or "").strip()
    password = body.get("password") or ""
    if not (phone or username) or not password:
        code, _message, status = TT_AUTH_40105
        raise BizError(code, "请输入账号和密码", status)

    # D8: IP 维度限流在认证前（防暴力破解扫描）；账号维度仅计失败
    from core.rate_limit import _check, _client_ip

    ip = _client_ip(request)
    _check(f"login:ip:{ip}", limit=20, window_s=60)

    account = phone or username
    try:
        # 小程序端：手机号+密码（user_credential.phone 校验）；后台管理端：登录账号+密码（user_credential.username 校验）
        result = login_phone_session(phone, password) if phone else password_login_session(username, password)
    except Exception:
        # D8: 认证失败时才计入账号限流桶（成功登录不计数）
        if account:
            _check(f"login:acct:{account}", limit=5, window_s=300)
        raise

    # D8: 登录成功后不计入账号限流桶（只计失败次数）
    return success(result)


@router.post("/register/challenge", summary="发送注册手机号验证码")
def register_challenge(body: RegistrationChallengeRequest, context: SmsRequestContext = Depends(validate_sms_request)):
    send_context = SendContext(context.ip, context.device_id, context.request_id)
    return success(start_registration_challenge(body.phone, send_context))


@router.post("/register", summary="核验手机号并注册")
def register(body: RegisterRequest, request: Request):
    check_register_rate(request)
    with verified_registration(body.phone, body.challengeId, body.code) as registration:
        if body.username and body.username.strip():
            profile = body.model_dump(exclude={"challengeId", "code"})
            profile["phone"] = registration.phone
            result = register_password_user(profile, request_id=get_request_id(), registration=registration)
            return success(result, "注册成功，请登录")
        return success(register_user(registration.phone, body.password, body.displayName, registration=registration))


@router.post("/bootstrap")
def bootstrap(body: BootstrapRequest):
    host_credential = body.as_dict().get("hostCredential")
    if not host_credential:
        raise bootstrap_credential_invalid("缺少 hostCredential")

    provider = get_identity_provider()
    ext_identity = provider.verify(host_credential)
    result = bootstrap_session(ext_identity)
    return success(result)


@router.post("/refresh")
def refresh(body: RefreshTokenRequest, request: Request):
    # M5: refresh token 防重放/枚举：按 IP 限频（10 次/60s），超限 429
    check_ip_rate(request, "auth_refresh", limit=10, window_s=60)
    refresh_token = body.as_dict().get("refreshToken")
    if not refresh_token:
        code, _message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = refresh_session(refresh_token)
    return success(result)


@router.post("/logout")
def logout(body: RefreshTokenRequest, request: Request):
    # M5: 与 /refresh 同一限频桶，防止伪造 refreshToken 撞库
    check_ip_rate(request, "auth_refresh", limit=10, window_s=60)
    refresh_token = body.as_dict().get("refreshToken")
    if not refresh_token:
        code, _message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = logout_session(refresh_token)
    return success(result)
