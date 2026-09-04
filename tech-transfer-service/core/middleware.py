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


def admin_identity(request: Request) -> dict:
    """管理端依赖：登录 + user_role 表实时校验 admin 角色。

    不信任 JWT 内 roles 快照（角色变更后旧 token 立即失效），
    每次请求查库判定 —— 06 §授权：RBAC（user_role）+ TT_ADMIN_40301。
    """
    user = identity(request)
    from db import get_cursor
    from core.errors import TT_ADMIN_40301
    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
            (user["userId"],),
        )
        if not cur.fetchone():
            code, message, status = TT_ADMIN_40301
            raise BizError(code, message, status)
    return user
