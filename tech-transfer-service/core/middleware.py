from functools import wraps
from flask import request, g
from core.errors import BizError, TT_COMMON_40101, TT_COMMON_40102
from core.jwt_utils import decode_token
import jwt


def auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            code, message, status = TT_COMMON_40101
            raise BizError(code, message, status)
        token = auth_header[7:]
        try:
            payload = decode_token(token)
        except jwt.ExpiredSignatureError:
            code, message, status = TT_COMMON_40102
            raise BizError(code, message, status)
        except jwt.InvalidTokenError:
            code, message, status = TT_COMMON_40102
            raise BizError(code, message, status)
        g.identity = {
            "userId": int(payload["sub"]),
            "userNo": payload.get("userNo", ""),
            "roles": payload.get("roles", ["user"]),
        }
        return f(*args, **kwargs)
    return wrapper
