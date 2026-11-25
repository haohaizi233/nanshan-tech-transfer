import time
import uuid
from typing import Any

import jwt

from config import settings


def _now() -> int:
    return int(time.time())


def sign_access_token(
    user_id: int,
    user_no: str,
    roles: list[str],
    session_version: int = 1,
    *,
    sid: str | None = None,
    auth_time: int | None = None,
) -> str:
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "userNo": user_no,
        "roles": roles,
        "ver": int(session_version),
        "type": "access",
        "iat": now,
        "exp": now + settings.ACCESS_TOKEN_EXPIRES,
    }
    if sid is not None:
        payload["sid"] = str(sid)
    if auth_time is not None:
        payload["auth_time"] = int(auth_time)
    token: str = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token


def sign_refresh_token(user_id: int, *, sid: str | None = None) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    expires_in = settings.REFRESH_TOKEN_EXPIRES_DAYS * 86400
    now = _now()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": now,
        "exp": now + expires_in,
    }
    if sid is not None:
        payload["sid"] = str(sid)
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])
    return claims


def decode_no_verify_exp(token: str) -> dict[str, Any]:
    claims: dict[str, Any] = jwt.decode(
        token,
        settings.JWT_SECRET,
        algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
    return claims
