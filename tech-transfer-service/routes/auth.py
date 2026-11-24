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
from modules.security.rate_limiter import check_verify_challenge_rate
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
    if body.channel == "sms":
        try:
            phone = normalize_phone(body.account)
        except BizError:
            phone = None
        request_gate(ctx, body.account.strip().lower(), phone=phone)
    else:
        if not settings.EMAIL_ENABLED:
            raise BizError("TT_COMMON_50301", "邮箱安全验证功能暂未开放", 503)
        norm_email = None
        if "@" in body.account:
            try:
                norm_email = normalize_email(body.account)
            except BizError:
                norm_email = None
        email_request_gate(
            ctx,
            body.account.strip().lower(),
            email=norm_email,
            purpose="password_recovery",
        )
    challenge_id = str(uuid.uuid4())
    enqueue_recovery_task(body.account.strip(), body.channel, challenge_id, ctx)
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


@router.post("/register", summary="注册（username 用户名或 phone 手机号两种模式）")
def register(body: RegisterRequest, request: Request):
    body = body.as_dict()
    username = (body.get("username") or "").strip()

    # 防批量注册：按 IP 限频
    check_register_rate(request)

    if username:
        # Vue 后台注册页：用户名 + 密码（可选 displayName/phone/email），注册后跳登录
        return success(
            register_password_user(body, request_id=get_request_id()),
            "注册成功，请登录",
        )
    # 小程序手机号注册：创建用户并直接签发会话（免登录）
    phone = (body.get("phone") or "").strip()
    password = body.get("password") or ""
    display_name = (body.get("displayName") or "").strip() or None
    result = register_user(phone, password, display_name)
    return success(result)


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
