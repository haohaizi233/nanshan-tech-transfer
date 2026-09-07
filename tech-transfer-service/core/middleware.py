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


def org_admin_identity(request: Request) -> dict:
    """Authenticate using current organization-admin rows, never JWT role snapshots.

    System Admins may enter organization-admin flows, but every resource operation
    must still call ``assert_org_admin_for`` with the resource's canonical org id.
    """
    user = identity(request)
    from db import get_cursor
    from core.errors import TT_ADMIN_40301

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT org_id
            FROM organization_membership
            WHERE user_id = %s AND role = 'admin' AND status = 'active'
            ORDER BY org_id
            """,
            (user["userId"],),
        )
        org_ids = [int(row["org_id"]) for row in (cur.fetchall() or [])]
        cur.execute(
            "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
            (user["userId"],),
        )
        is_system_admin = bool(cur.fetchone())

    if not org_ids and not is_system_admin:
        code, message, status = TT_ADMIN_40301
        raise BizError(code, "非机构管理员", status)

    return {
        **user,
        "organizationAdminOrgIds": org_ids,
        "isSystemAdmin": is_system_admin,
    }


def backend_identity(request: Request) -> dict:
    """后台内容管理访问身份（admin 路由 scope 契约）。

    - 平台管理员（user_role.role_code='admin'）：isPlatformAdmin=True，全平台范围；
    - 机构管理员：isPlatformAdmin=False，orgId 限本机构（内容 scope 过滤）。

    机构管理员身份来自 organization_membership(role='admin', status='active')
    实时查库——不使用 user_role 表达机构权限（与 org_admin_identity 同源）。
    """
    user = identity(request)
    from db import get_cursor
    from core.errors import TT_ADMIN_40301

    with get_cursor() as cur:
        cur.execute(
            "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
            (user["userId"],),
        )
        if cur.fetchone():
            return {**user, "isPlatformAdmin": True, "orgId": None}

        cur.execute(
            """
            SELECT m.org_id
            FROM organization_membership m
            JOIN institution i ON i.id = m.org_id AND i.status = 'active'
            WHERE m.user_id = %s AND m.role = 'admin' AND m.status = 'active'
            ORDER BY m.org_id
            LIMIT 1
            """,
            (user["userId"],),
        )
        row = cur.fetchone()

    if row:
        return {**user, "isPlatformAdmin": False, "orgId": int(row["org_id"])}

    code, message, status = TT_ADMIN_40301
    raise BizError(code, message, status)
