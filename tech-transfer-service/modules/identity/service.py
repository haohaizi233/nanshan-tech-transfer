import json
from datetime import datetime, timezone
from typing import Optional

from db import get_cursor
from modules.identity.context import IdentityContext
from modules.identity.provider import ExternalIdentity
from core.jwt_utils import sign_access_token, sign_refresh_token
from core.password import verify_password


def _generate_user_no(cur) -> str:
    # 取存量编号数值最大值+1（COUNT 会在测试清理用户后回落，与存量编号撞唯一约束）
    cur.execute(
        "SELECT COALESCE(MAX(regexp_replace(user_no, '\\D', '', 'g')::bigint), 0) AS m "
        "FROM app_user WHERE user_no ~ '^U\\d+$'"
    )
    return f"U{cur.fetchone()['m'] + 1}"


def _get_roles(cur, user_id: int) -> list[str]:
    cur.execute(
        "SELECT role_code FROM user_role WHERE user_id=%s ORDER BY id", (user_id,)
    )
    rows = cur.fetchall()
    return [r["role_code"] for r in rows] if rows else ["user"]


def _get_profile(cur, user_id: int) -> dict:
    cur.execute(
        """
        SELECT up.user_id, up.display_name, up.user_type, up.phone, up.email,
               up.org_id, up.org_title, up.company_text, up.version,
               up.subject_type, up.business_capabilities, up.wechat
        FROM user_profile up
        WHERE up.user_id = %s
        """,
        (user_id,),
    )
    return cur.fetchone()


def _get_org_name(cur, org_id: Optional[int]) -> Optional[str]:
    if not org_id:
        return None
    return None


def _parse_capabilities(raw) -> list:
    """business_capabilities JSONB → list[str]；异常值一律归为空（画像字段不参与权限，宽松处理）"""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    if not isinstance(raw, list):
        return []
    return [str(x) for x in raw if isinstance(x, (str, int))]


def build_user_response(cur, user_id: int) -> dict:
    profile = _get_profile(cur, user_id)
    roles = _get_roles(cur, user_id)
    cur.execute(
        "SELECT user_no, status FROM app_user WHERE id=%s", (user_id,)
    )
    user = cur.fetchone()
    if not user:
        return None
    org_name = _get_org_name(cur, profile.get("org_id") if profile else None)
    cur.execute(
        """
        SELECT m.id, m.org_id, o.name AS org_name, m.role, m.status, m.version
        FROM organization_membership m
        JOIN institution o ON o.id = m.org_id
        WHERE m.user_id = %s AND m.status = 'active'
        ORDER BY m.id
        """,
        (user_id,),
    )
    memberships = [
        {"id": row["id"], "orgId": row["org_id"], "orgName": row["org_name"],
         "role": row["role"], "status": row["status"], "version": row["version"]}
        for row in cur.fetchall()
    ]
    return {
        "userId": user_id,
        "userNo": user["user_no"],
        "displayName": profile["display_name"] if profile else None,
        "userType": profile["user_type"] if profile else None,
        "subjectType": profile["subject_type"] if profile else None,
        "businessCapabilities": _parse_capabilities(profile.get("business_capabilities")) if profile else [],
        "phone": profile["phone"] if profile else None,
        "email": profile["email"] if profile else None,
        "wechat": profile["wechat"] if profile else None,
        "companyText": profile["company_text"] if profile else None,
        "organizationMemberships": memberships,
        # Compatibility only: legacy profile fields never establish certification.
        "orgId": profile["org_id"] if profile else None,
        "orgName": org_name,
        "orgTitle": profile["org_title"] if profile else None,
        "version": profile["version"] if profile else None,
        "roles": roles,
    }


def find_or_create_user(ext: ExternalIdentity) -> tuple[IdentityContext, bool]:
    """返回 (IdentityContext, is_new_user)"""
    is_new = False
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT ei.user_id, ei.display_name_snapshot
            FROM external_identity ei
            WHERE ei.issuer=%s AND ei.tenant_id=%s AND ei.external_subject=%s
              AND ei.unlinked_at IS NULL
            """,
            (ext.issuer, ext.tenant_id, ext.external_subject),
        )
        existing = cur.fetchone()

        if existing:
            user_id = existing["user_id"]
        else:
            is_new = True
            user_no = _generate_user_no(cur)
            cur.execute(
                "INSERT INTO app_user (user_no, status) VALUES (%s, 'active') RETURNING id",
                (user_no,),
            )
            user_id = cur.fetchone()["id"]

            cur.execute(
                """
                INSERT INTO external_identity
                    (user_id, issuer, tenant_id, external_subject, display_name_snapshot)
                VALUES (%s, %s, %s, %s, %s)
                """,
                (user_id, ext.issuer, ext.tenant_id, ext.external_subject, ext.display_name),
            )

            cur.execute(
                "INSERT INTO user_profile (user_id) VALUES (%s)",
                (user_id,),
            )

            cur.execute(
                "INSERT INTO user_role (user_id, role_code) VALUES (%s, 'user')",
                (user_id,),
            )

        roles = _get_roles(cur, user_id)
        identity = IdentityContext(
            userId=user_id,
            issuer=ext.issuer,
            externalSubject=ext.external_subject,
            tenantId=ext.tenant_id,
            displayName=ext.display_name,
            roles=roles,
        )
    return identity, is_new


def bootstrap_session(ext: ExternalIdentity) -> dict:
    identity, is_new = find_or_create_user(ext)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT user_no FROM app_user WHERE id=%s", (identity.userId,)
        )
        row = cur.fetchone()
        user_no = row["user_no"] if row else ""

        access_token = sign_access_token(identity.userId, user_no, identity.roles)
        refresh_token, jti = sign_refresh_token(identity.userId)

        cur.execute(
            """
            INSERT INTO auth_session (user_id, refresh_jti, status, issued_at, expires_at)
            VALUES (%s, %s, 'active', NOW(), NOW() + INTERVAL '14 days')
            """,
            (identity.userId, jti),
        )

        user = build_user_response(cur, identity.userId)

    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": 7200,
        "user": user,
        "isNewUser": is_new,
    }


def _issue_session(cur, user_id: int, roles: list[str]) -> dict:
    """签发 access/refresh token 并落 auth_session，返回响应 dict（无 user 字段）。"""
    cur.execute("SELECT user_no, status FROM app_user WHERE id=%s", (user_id,))
    row = cur.fetchone()
    user_no = row["user_no"] if row else ""

    access_token = sign_access_token(user_id, user_no, roles)
    refresh_token, jti = sign_refresh_token(user_id)

    cur.execute(
        """
        INSERT INTO auth_session (user_id, refresh_jti, status, issued_at, expires_at)
        VALUES (%s, %s, 'active', NOW(), NOW() + INTERVAL '14 days')
        """,
        (user_id, jti),
    )
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": 7200,
    }


def register_user(phone: str, password: str, display_name: str = None) -> dict:
    """手机号注册：创建 app_user + user_profile + user_credential + user_role。

    注册成功后直接签发会话（免登录），返回与 password_login_session 相同结构。
    手机号已注册时抛 TT_AUTH_40901。
    """
    from core.errors import BizError, TT_AUTH_40901, TT_COMMON_40001
    from core.password import hash_password
    import re

    if not phone or not re.match(r"^\d{11}$", phone):
        raise BizError(*TT_COMMON_40001[:2], TT_COMMON_40001[2], "请输入11位手机号")
    if not password or len(password) < 6:
        raise BizError(*TT_COMMON_40001[:2], TT_COMMON_40001[2], "密码至少6位")

    with get_cursor(commit=True) as cur:
        # 检查手机号是否已注册（通过 user_credential.username 唯一）
        cur.execute(
            "SELECT user_id FROM user_credential WHERE username = %s",
            (phone,),
        )
        if cur.fetchone():
            code, message, status = TT_AUTH_40901
            raise BizError(code, message, status)

        # 创建 app_user
        user_no = _generate_user_no(cur)
        cur.execute(
            "INSERT INTO app_user (user_no, status) VALUES (%s, 'active') RETURNING id",
            (user_no,),
        )
        user_id = cur.fetchone()["id"]

        # 创建 user_profile
        cur.execute(
            """
            INSERT INTO user_profile (user_id, display_name, phone)
            VALUES (%s, %s, %s)
            """,
            (user_id, display_name or phone, phone),
        )

        # 创建 user_role
        cur.execute(
            "INSERT INTO user_role (user_id, role_code) VALUES (%s, 'user')",
            (user_id,),
        )

        # 创建 user_credential（username = 手机号）
        cur.execute(
            "INSERT INTO user_credential (user_id, username, password_hash, status) "
            "VALUES (%s, %s, %s, 'active')",
            (user_id, phone, hash_password(password)),
        )

        # 签发会话
        roles = _get_roles(cur, user_id)
        result = _issue_session(cur, user_id, roles)
        result["user"] = build_user_response(cur, user_id)
        result["isNewUser"] = True
        return result


def password_login_session(username: str, password: str) -> dict:
    """账号密码登录（user_credential 表真实校验，无宿主票据）。

    用户不存在 / 密码错误返回同一文案（防账号枚举）；
    账号禁用（credential 或 app_user 任一 disabled）返回独立错误码。
    """
    from core.errors import BizError, TT_AUTH_40105, TT_AUTH_40106

    if not username or not password:
        raise BizError(*TT_AUTH_40105[:2], TT_AUTH_40105[2])

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT uc.user_id, uc.password_hash, uc.status AS cred_status,
                   au.status AS user_status
            FROM user_credential uc
            JOIN app_user au ON au.id = uc.user_id
            WHERE uc.username = %s AND au.deleted_at IS NULL
            """,
            (username,),
        )
        cred = cur.fetchone()

        if cred is None or not verify_password(password, cred["password_hash"]):
            code, message, status = TT_AUTH_40105
            raise BizError(code, message, status)

        if cred["cred_status"] != "active" or cred["user_status"] != "active":
            code, message, status = TT_AUTH_40106
            raise BizError(code, message, status)

        user_id = cred["user_id"]
        roles = _get_roles(cur, user_id)
        result = _issue_session(cur, user_id, roles)
        result["user"] = build_user_response(cur, user_id)
        result["isNewUser"] = False
        return result


def refresh_session(refresh_token: str) -> dict:
    from core.jwt_utils import decode_no_verify_exp
    import jwt as _jwt

    try:
        payload = decode_no_verify_exp(refresh_token)
    except _jwt.InvalidTokenError:
        from core.errors import BizError, TT_COMMON_40102
        code, message, status = TT_COMMON_40102
        raise BizError(code, message, status)

    if payload.get("type") != "refresh":
        from core.errors import BizError, TT_COMMON_40102
        code, message, status = TT_COMMON_40102
        raise BizError(code, message, status)

    jti = payload.get("jti")
    user_id = int(payload["sub"])
    # PG TIMESTAMPTZ 读取为带时区 datetime，比较也须用带时区当前时间
    now = datetime.now(timezone.utc)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status, expires_at FROM auth_session WHERE refresh_jti=%s",
            (jti,),
        )
        session = cur.fetchone()
        if not session or session["status"] != "active":
            from core.errors import BizError, TT_COMMON_40102
            code, message, status = TT_COMMON_40102
            raise BizError(code, message, status)

        if session["expires_at"] and session["expires_at"] < now:
            from core.errors import BizError, TT_COMMON_40102
            code, message, status = TT_COMMON_40102
            raise BizError(code, message, status)

        cur.execute(
            "UPDATE auth_session SET status='consumed' WHERE refresh_jti=%s",
            (jti,),
        )

        cur.execute("SELECT user_no FROM app_user WHERE id=%s", (user_id,))
        row = cur.fetchone()
        user_no = row["user_no"] if row else ""

        roles = _get_roles(cur, user_id)
        access_token = sign_access_token(user_id, user_no, roles)
        new_refresh_token, new_jti = sign_refresh_token(user_id)

        cur.execute(
            """
            INSERT INTO auth_session (user_id, refresh_jti, status, issued_at, expires_at)
            VALUES (%s, %s, 'active', NOW(), NOW() + INTERVAL '14 days')
            """,
            (user_id, new_jti),
        )

        user = build_user_response(cur, user_id)

    return {
        "accessToken": access_token,
        "refreshToken": new_refresh_token,
        "expiresIn": 7200,
        "user": user,
        "isNewUser": False,
    }


def logout_session(refresh_token: str) -> dict:
    from core.jwt_utils import decode_no_verify_exp
    import jwt as _jwt

    revoked = False
    try:
        payload = decode_no_verify_exp(refresh_token)
        jti = payload.get("jti")
        if jti:
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE auth_session SET status='revoked', revoked_at=NOW() "
                    "WHERE refresh_jti=%s AND status='active'",
                    (jti,),
                )
                revoked = cur.rowcount > 0
    except _jwt.InvalidTokenError:
        pass

    return {"revoked": revoked}
