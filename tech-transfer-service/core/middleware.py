"""
FastAPI 依赖：认证（identity）与请求体解析（json_body）

- identity 等价于 Flask 版 auth_required 装饰器
- json_body 等价于 request.get_json(silent=True) or {}

鉴权查询走 core.auth_cache 的 30s 短 TTL 缓存（M8），把每请求 2-3 次
DB 往返降为偶发一次；角色/状态写路径通过 auth_cache.invalidate_user() 即时失效。
"""

import jwt
from fastapi import Request

from core import auth_cache
from core.errors import TT_COMMON_40101, TT_COMMON_40102, BizError
from core.jwt_utils import decode_token


def _payload_to_actor(payload: dict) -> dict:
    """Build the actor dict from a decoded JWT payload.

    Centralizes the mapping so identity() and identity_from_access_token()
    stay consistent. Caller must guarantee payload is a dict.
    """
    return {
        "userId": int(payload["sub"]),
        "userNo": payload.get("userNo", ""),
        "roles": payload.get("roles", ["user"]),
    }


def _user_is_active(user_id: int) -> bool:
    """Lightweight DB check: app_user.status must be 'active'.

    Closes the gap where a disabled user's existing access token remains
    valid until JWT expiry (up to ACCESS_TOKEN_EXPIRES).

    M8: 结果进 core.auth_cache 的 30s 短 TTL 缓存，重复请求不再每请求查库；
    用户状态写路径（禁用/启用）调用 auth_cache.invalidate_user() 即时失效，
    即使漏调，最坏 30s 后自然过期。False 也缓存，防缓存穿透。
    """
    from db import get_cursor

    def _query() -> bool:
        with get_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM app_user WHERE id = %s AND status = 'active'",
                (user_id,),
            )
            return cur.fetchone() is not None

    return auth_cache.cached(("user_active", user_id), _query)


def _is_admin_role(user_id: int) -> bool:
    """user_role 表实时 admin 判定（M8: 30s TTL 缓存，写路径主动失效）。"""
    from db import get_cursor

    def _query() -> bool:
        with get_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
                (user_id,),
            )
            return cur.fetchone() is not None

    return auth_cache.cached(("admin_role", user_id), _query)


def _org_admin_info(user_id: int) -> tuple[list[int], bool]:
    """(机构管理员 org_id 列表, 是否系统 admin)。M8: 30s TTL 缓存。"""
    from db import get_cursor

    def _query() -> tuple[list[int], bool]:
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT m.org_id
                FROM organization_membership m
                JOIN institution i ON i.id = m.org_id AND i.status = 'active'
                WHERE m.user_id = %s AND m.role = 'admin' AND m.status = 'active'
                ORDER BY m.org_id
                """,
                (user_id,),
            )
            org_ids = [int(row["org_id"]) for row in (cur.fetchall() or [])]
            cur.execute(
                "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
                (user_id,),
            )
            is_system_admin = bool(cur.fetchone())
        return org_ids, is_system_admin

    org_ids, is_system_admin = auth_cache.cached(("org_admin", user_id), _query)
    return list(org_ids), bool(is_system_admin)


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
    # Reject refresh tokens used as access tokens: a stolen 14-day refresh
    # token must not grant API access as a Bearer credential.
    if payload.get("type") != "access":
        code, message, status = TT_COMMON_40102
        raise BizError(code, message, status)
    actor = _payload_to_actor(payload)
    # Disabled-user gap: existing access tokens would otherwise remain valid
    # until expiry. Re-check app_user.status each request.
    if not _user_is_active(actor["userId"]):
        code, message, status = TT_COMMON_40102
        raise BizError(code, message, status)
    return actor


def identity_from_access_token(token: str):
    """Decode a bearer token without requiring the Authorization header.

    WeChat <image> cannot send headers; GET /files/:id therefore accepts
    access_token as a query parameter for the owner of unpublished media.
    Invalid tokens return None so published files still remain publicly readable.
    """
    value = (token or "").strip()
    if not value:
        return None
    try:
        payload = decode_token(value)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, KeyError, TypeError, ValueError):
        return None
    # Reject refresh tokens used as access tokens.
    if payload.get("type") != "access":
        return None
    actor = _payload_to_actor(payload)
    if not _user_is_active(actor["userId"]):
        return None
    return actor


def optional_identity(request: Request) -> dict:
    """公开详情的可选身份：无 token 是游客；有 token 仍严格校验。"""
    if not request.headers.get("Authorization", ""):
        return {"userId": None, "userNo": "", "roles": []}
    return identity(request)


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
    M8: 查库结果 30s TTL 缓存，角色授予/撤销写路径调用 auth_cache.invalidate_user()。
    """
    user = identity(request)
    if not _is_admin_role(user["userId"]):
        from core.errors import TT_ADMIN_40301
        code, message, status = TT_ADMIN_40301
        raise BizError(code, message, status)
    return user


def org_admin_identity(request: Request) -> dict:
    """Authenticate using current organization-admin rows, never JWT role snapshots.

    System Admins may enter organization-admin flows, but every resource operation
    must still call ``assert_org_admin_for`` with the resource's canonical org id.
    """
    user = identity(request)
    from core.errors import TT_ADMIN_40301

    org_ids, is_system_admin = _org_admin_info(user["userId"])
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
    from core.errors import TT_ADMIN_40301

    org_ids, is_system_admin = _org_admin_info(user["userId"])
    if is_system_admin:
        return {**user, "isPlatformAdmin": True, "orgId": None}

    if org_ids:
        return {
            **user,
            "isPlatformAdmin": False,
            "orgId": org_ids[0],
            "orgIds": org_ids,
        }

    code, message, status = TT_ADMIN_40301
    raise BizError(code, message, status)
