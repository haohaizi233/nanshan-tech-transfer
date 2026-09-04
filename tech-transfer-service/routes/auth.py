from fastapi import APIRouter, Depends

from core.response import success
from core.middleware import json_body
from core.errors import bootstrap_credential_invalid, BizError, TT_COMMON_40102
from modules.identity.provider import get_identity_provider
from modules.identity.service import bootstrap_session, refresh_session, logout_session

router = APIRouter(prefix="/api/tech-transfer/v1/auth", tags=["auth"])


@router.post("/bootstrap")
def bootstrap(body: dict = Depends(json_body)):
    host_credential = body.get("hostCredential")
    if not host_credential:
        raise bootstrap_credential_invalid("缺少 hostCredential")

    provider = get_identity_provider()
    ext_identity = provider.verify(host_credential)
    result = bootstrap_session(ext_identity)
    return success(result)


@router.post("/refresh")
def refresh(body: dict = Depends(json_body)):
    refresh_token = body.get("refreshToken")
    if not refresh_token:
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = refresh_session(refresh_token)
    return success(result)


@router.post("/logout")
def logout(body: dict = Depends(json_body)):
    refresh_token = body.get("refreshToken")
    if not refresh_token:
        code, message, status = TT_COMMON_40102
        raise BizError(code, "缺少 refreshToken", status)

    result = logout_session(refresh_token)
    return success(result)
