"""
FastAPI 依赖：认证（identity）与请求体解析（json_body）

- identity 等价于 Flask 版 auth_required 装饰器
- json_body 等价于 request.get_json(silent=True) or {}
"""

import jwt
from fastapi import Depends, Request

from core.errors import BizError, TT_COMMON_40101, TT_COMMON_40102
from core.jwt_utils import decode_token


def identity(request: Request) -> dict:
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        code, message, status = TT_COMMON_40101
        raise BizError(code, message, status)
    token = auth_header[7:]
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError):
        code, message, status = TT_COMMON_40102
        raise BizError(code, message, status)
    return {
        "userId": int(payload["sub"]),
        "userNo": payload.get("userNo", ""),
        "roles": payload.get("roles", ["user"]),
    }


async def json_body(request: Request) -> dict:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else {}
