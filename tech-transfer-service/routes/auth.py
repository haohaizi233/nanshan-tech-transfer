from fastapi import APIRouter, Request

from fastapi import Depends

from core.errors import TT_AUTH_40105, TT_COMMON_40102, BizError, bootstrap_credential_invalid
from core.middleware import identity
from core.rate_limit import check_ip_rate, check_register_rate
from core.request_schemas import (
    BootstrapRequest,
    LoginRequest,
    RefreshTokenRequest,
    RegisterRequest,
    WechatBindRequest,
    WechatLoginRequest,
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

router = APIRouter(prefix="/api/tech-transfer/v1/auth", tags=["auth"])


@router.get("/wechat/config")
def wechat_config():
    return success({"enabled": wechat_login_enabled()})


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
        code, message, status = TT_AUTH_40105
        raise BizError(code, "请输入账号和密码", status)

    # D8: IP 维度限流在认证前（防暴力破解扫描）；账号维度仅计失败
    from core.rate_limit import _check, _client_ip
    ip = _client_ip(request)
    _check(f"login:ip:{ip}", limit=20, window_s=60)

    account = phone or username
    try:
        if phone:
            # 小程序端：手机号 + 密码（user_credential.phone 校验）
            result = login_phone_session(phone, password)
        else:
            # 后台管理端：登录账号 + 密码（user_credential.username 校验）
            result = password_login_session(username, password)
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
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = refresh_session(refresh_token)
    return success(result)


@router.post("/logout")
def logout(body: RefreshTokenRequest, request: Request):
    # M5: 与 /refresh 同一限频桶，防止伪造 refreshToken 撞库
    check_ip_rate(request, "auth_refresh", limit=10, window_s=60)
    refresh_token = body.as_dict().get("refreshToken")
    if not refresh_token:
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = logout_session(refresh_token)
    return success(result)
