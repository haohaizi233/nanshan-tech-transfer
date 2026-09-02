from flask import Blueprint, request
from core.response import success, error
from core.errors import BizError, bootstrap_credential_invalid, TT_AUTH_40103
from modules.identity.provider import get_identity_provider
from modules.identity.service import bootstrap_session, refresh_session, logout_session

bp = Blueprint("auth", __name__, url_prefix="/api/tech-transfer/v1/auth")


@bp.post("/bootstrap")
def bootstrap():
    body = request.get_json(silent=True) or {}
    host_credential = body.get("hostCredential")
    if not host_credential:
        raise bootstrap_credential_invalid("缺少 hostCredential")

    provider = get_identity_provider()
    ext_identity = provider.verify(host_credential)
    result = bootstrap_session(ext_identity)
    return success(result)


@bp.post("/refresh")
def refresh():
    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refreshToken")
    if not refresh_token:
        from core.errors import BizError, TT_COMMON_40102
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = refresh_session(refresh_token)
    return success(result)


@bp.post("/logout")
def logout():
    body = request.get_json(silent=True) or {}
    refresh_token = body.get("refreshToken")
    if not refresh_token:
        from core.errors import BizError, TT_COMMON_40102
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = logout_session(refresh_token)
    return success(result)
