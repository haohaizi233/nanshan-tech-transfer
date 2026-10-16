import time
import uuid

import jwt

from config import settings


def _now():
    return int(time.time())


def sign_access_token(user_id: int, user_no: str, roles: list[str]) -> str:
    payload = {
        "sub": str(user_id),
        "userNo": user_no,
        "roles": roles,
        "type": "access",
        "iat": _now(),
        "exp": _now() + settings.ACCESS_TOKEN_EXPIRES,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def sign_refresh_token(user_id: int) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    expires_in = settings.REFRESH_TOKEN_EXPIRES_DAYS * 86400
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + expires_in,
    }
    token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return token, jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM])


def decode_no_verify_exp(token: str) -> dict:
    return jwt.decode(
        token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM],
        options={"verify_exp": False},
    )
