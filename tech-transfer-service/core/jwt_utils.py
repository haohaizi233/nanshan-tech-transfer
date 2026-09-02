import jwt
import time
import uuid
from config import JWT_SECRET, ACCESS_TOKEN_EXPIRES, REFRESH_TOKEN_EXPIRES_DAYS

_ALGO = "HS256"


def _now():
    return int(time.time())


def sign_access_token(user_id: int, user_no: str, roles: list[str]) -> str:
    payload = {
        "sub": str(user_id),
        "userNo": user_no,
        "roles": roles,
        "type": "access",
        "iat": _now(),
        "exp": _now() + ACCESS_TOKEN_EXPIRES,
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=_ALGO)


def sign_refresh_token(user_id: int) -> tuple[str, str]:
    jti = uuid.uuid4().hex
    expires_in = REFRESH_TOKEN_EXPIRES_DAYS * 86400
    payload = {
        "sub": str(user_id),
        "jti": jti,
        "type": "refresh",
        "iat": _now(),
        "exp": _now() + expires_in,
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=_ALGO)
    return token, jti


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[_ALGO])


def decode_no_verify_exp(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[_ALGO], options={"verify_exp": False})
