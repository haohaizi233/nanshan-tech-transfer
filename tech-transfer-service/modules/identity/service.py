from datetime import datetime, timezone
from typing import Optional

from db import get_cursor
from modules.identity.context import IdentityContext
from modules.identity.provider import ExternalIdentity
from core.jwt_utils import sign_access_token, sign_refresh_token


def _generate_user_no(cur) -> str:
    cur.execute("SELECT COUNT(*) AS c FROM app_user")
    count = cur.fetchone()["c"]
    return f"U{datetime.now().strftime('%Y')}{count + 1:05d}"


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
               up.org_id, up.org_title, up.version
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
    return {
        "userId": user_id,
        "userNo": user["user_no"],
        "displayName": profile["display_name"] if profile else None,
        "userType": profile["user_type"] if profile else None,
        "phone": profile["phone"] if profile else None,
        "email": profile["email"] if profile else None,
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
                "INSERT INTO app_user (user_no, status) VALUES (%s, 'active')",
                (user_no,),
            )
            user_id = cur.lastrowid

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
            VALUES (%s, %s, 'active', NOW(), DATE_ADD(NOW(), INTERVAL 14 DAY))
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
    now = datetime.now()

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
            VALUES (%s, %s, 'active', NOW(), DATE_ADD(NOW(), INTERVAL 14 DAY))
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
