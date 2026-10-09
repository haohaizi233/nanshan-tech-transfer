import json
from typing import Optional

from db import get_cursor
from config import settings
from modules.identity.context import IdentityContext
from modules.identity.provider import ExternalIdentity
from core.jwt_utils import sign_access_token, sign_refresh_token
from core.password import hash_password, verify_password
from core.contact_validation import is_valid_phone, validate_email, validate_phone
from core.errors import BizError, TT_COMMON_40903, bad_request
from modules.audit.service import record as audit_record


def _generate_user_no(cur) -> str:
    # 取存量编号数值最大值+1（COUNT 会在测试清理用户后回落，与存量编号撞唯一约束）
    cur.execute(
        "SELECT COALESCE(MAX(regexp_replace(user_no, '\\D', '', 'g')::bigint), 0) AS m "
        "FROM app_user WHERE user_no ~ '^U\\d+$'"
    )
    return f"U{cur.fetchone()['m'] + 1}"


def _get_roles(cur, user_id: int) -> list[str]:
    cur.execute("SELECT role_code FROM user_role WHERE user_id=%s ORDER BY id", (user_id,))
    rows = cur.fetchall()
    roles = [r["role_code"] for r in rows] if rows else ["user"]
    # 机构管理员角色来自 membership 实时判定（不落 user_role 表），
    # 供 Vue 后台登录门禁展示；权限判断仍以各 identity 依赖实时查库为准
    cur.execute(
        """
        SELECT 1 FROM organization_membership
        WHERE user_id=%s AND role='admin' AND status='active' LIMIT 1
        """,
        (user_id,),
    )
    if cur.fetchone() and "org_admin" not in roles:
        roles.append("org_admin")
    return roles


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
    cur.execute("SELECT name FROM institution WHERE id=%s", (org_id,))
    row = cur.fetchone()
    return row["name"] if row else None


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
            VALUES (%s, %s, 'active', NOW(), NOW() + make_interval(days => %s))
            """,
            (identity.userId, jti, settings.REFRESH_TOKEN_EXPIRES_DAYS),
        )

        user = build_user_response(cur, identity.userId)

    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": settings.ACCESS_TOKEN_EXPIRES,
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
        VALUES (%s, %s, 'active', NOW(), NOW() + make_interval(days => %s))
        """,
        (user_id, jti, settings.REFRESH_TOKEN_EXPIRES_DAYS),
    )
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": settings.ACCESS_TOKEN_EXPIRES,
    }


def register_user(phone: str, password: str, display_name: str = None) -> dict:
    """手机号注册：创建 app_user + user_profile + user_credential + user_role。

    注册成功后直接签发会话（免登录），返回与 password_login_session 相同结构。
    手机号已注册时抛 TT_AUTH_40901。
    """
    from core.errors import BizError, TT_AUTH_40901, TT_COMMON_40001
    from core.password import hash_password

    try:
        phone = validate_phone(phone, required=True)
    except BizError:
        raise BizError(*TT_COMMON_40001[:2], TT_COMMON_40001[2], "请输入11位手机号")
    if not password or len(password) < 8:
        raise BizError(*TT_COMMON_40001[:2], TT_COMMON_40001[2], "密码至少8位")

    with get_cursor(commit=True) as cur:
        # 检查手机号是否已注册（phone 唯一索引 + username 唯一约束双查，
        # 兼容迁移 012 回填前 username=手机号 的存量记录）
        cur.execute(
            "SELECT user_id FROM user_credential WHERE phone = %s OR username = %s",
            (phone, phone),
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

        # 创建 user_credential（小程序注册：username 与 phone 均写入手机号，
        # username 保留兼容旧登录链路，phone 为小程序端登录标识）
        cur.execute(
            "INSERT INTO user_credential (user_id, username, password_hash, phone, status) "
            "VALUES (%s, %s, %s, %s, 'active')",
            (user_id, phone, hash_password(password), phone),
        )

        # 签发会话
        roles = _get_roles(cur, user_id)
        result = _issue_session(cur, user_id, roles)
        result["user"] = build_user_response(cur, user_id)
        result["isNewUser"] = True
        return result


_LOGIN_CRED_SQL = """
    SELECT uc.user_id, uc.password_hash, uc.status AS cred_status,
           au.status AS user_status
    FROM user_credential uc
    JOIN app_user au ON au.id = uc.user_id
    WHERE au.deleted_at IS NULL AND {where}
"""


def _verify_login_and_issue(cur, cred: dict | None, password: str) -> dict:
    """密码校验 + 账号状态检查 + 签发会话（username/phone 两种登录共用）。

    用户不存在 / 密码错误返回同一文案（防账号枚举）；
    账号禁用（credential 或 app_user 任一 disabled）返回独立错误码。
    """
    from core.errors import TT_AUTH_40105, TT_AUTH_40106

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


def password_login_session(username: str, password: str) -> dict:
    """账号密码登录（后台管理端：按 user_credential.username 校验，无宿主票据）。"""
    from core.errors import TT_AUTH_40105

    if not username or not password:
        raise BizError(*TT_AUTH_40105)

    with get_cursor(commit=True) as cur:
        cur.execute(_LOGIN_CRED_SQL.format(where="uc.username = %s"), (username,))
        cred = cur.fetchone()
        return _verify_login_and_issue(cur, cred, password)


def login_phone_session(phone: str, password: str) -> dict:
    """手机号密码登录（小程序端：按 user_credential.phone 校验）。

    phone 未命中时回退按 username 匹配（兜底迁移 012 回填时因冲突跳过的
    phone 为 NULL 且 username=手机号 的存量账号）。
    """
    from core.errors import TT_AUTH_40105

    if not phone or not password:
        raise BizError(*TT_AUTH_40105)

    with get_cursor(commit=True) as cur:
        cur.execute(_LOGIN_CRED_SQL.format(where="uc.phone = %s"), (phone,))
        cred = cur.fetchone()
        if cred is None:
            cur.execute(
                _LOGIN_CRED_SQL.format(where="uc.phone IS NULL AND uc.username = %s"),
                (phone,),
            )
            cred = cur.fetchone()
        return _verify_login_and_issue(cur, cred, password)


def create_password_account(cur, username: str, password: str,
                            display_name=None, phone=None, email=None) -> tuple[int, str]:
    """在调用方事务游标内创建密码账号全套（app_user/profile/credential/role）。

    返回 (user_id, user_no)。供普通注册与机构注册申请（单事务创建账号+申请）复用。
    填写的 11 位手机号除 user_profile.phone 外同时写入 user_credential.phone
    （小程序端可用手机号+密码登录）；手机号已被注册时抛冲突。
    """
    cred_phone = phone if is_valid_phone(phone) else None
    if cred_phone:
        cur.execute(
            "SELECT 1 FROM user_credential WHERE phone = %s "
            "OR (phone IS NULL AND username = %s)",
            (cred_phone, cred_phone),
        )
        if cur.fetchone():
            code, message, status = TT_COMMON_40903
            raise BizError(code, "该手机号已被注册", status)

    user_no = _generate_user_no(cur)
    cur.execute(
        "INSERT INTO app_user (user_no, status) VALUES (%s, 'active') RETURNING id",
        (user_no,),
    )
    user_id = cur.fetchone()["id"]
    cur.execute(
        """
        INSERT INTO user_profile (user_id, display_name, phone, email)
        VALUES (%s, %s, %s, %s)
        """,
        (user_id, display_name, phone, email),
    )
    cur.execute(
        """
        INSERT INTO user_credential (user_id, username, password_hash, phone, status)
        VALUES (%s, %s, %s, %s, 'active')
        """,
        (user_id, username, hash_password(password), cred_phone),
    )
    cur.execute(
        "INSERT INTO user_role (user_id, role_code) VALUES (%s, 'user')",
        (user_id,),
    )
    return user_id, user_no


def register_password_user(body: dict, request_id: str | None = None) -> dict:
    """注册普通用户：账号创建后即可登录，不绑定机构，也不授予后台管理角色。"""
    import re

    username = str(body.get("username") or "").strip()
    password = body.get("password") or ""
    display_name = str(body.get("displayName") or "").strip() or None
    phone = validate_phone(body.get("phone"), required=False)
    email = validate_email(body.get("email"), required=False)

    if not re.fullmatch(r"[A-Za-z0-9_.-]{4,64}", username):
        raise bad_request("用户名须为 4-64 位字母、数字或 . _ -")
    if len(password) < 8 or len(password) > 128:
        raise bad_request("密码长度须为 8-128 位")

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT 1 FROM user_credential WHERE username=%s", (username,))
        if cur.fetchone():
            code, message, status = TT_COMMON_40903
            raise BizError(code, "该登录账号已存在", status)

        user_id, user_no = create_password_account(
            cur, username, password, display_name, phone, email,
        )
        audit_record(
            "user.registration.submit",
            "app_user",
            resource_id=user_id,
            actor_user_id=user_id,
            actor_user_no=user_no,
            details={"username": username},
            request_id=request_id,
            cur=cur,
        )
        user = build_user_response(cur, user_id)

    return {"user": user, "username": username}


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

    with get_cursor(commit=True) as cur:
        # 原子消费 refresh 令牌：仅当 status='active' 且未过期时才置 consumed。
        # 并发刷新同令牌时，第二条 UPDATE 的 WHERE status='active' 失败 → rowcount=0，
        # 杜绝令牌重放（两条有效刷新链）。过期判断下沉到 SQL，避免 Python/PG 时区分歧。
        cur.execute(
            """
            UPDATE auth_session
            SET status='consumed', consumed_at=NOW()
            WHERE refresh_jti=%s AND status='active'
              AND (expires_at IS NULL OR expires_at >= NOW())
            """,
            (jti,),
        )
        if cur.rowcount == 0:
            from core.errors import BizError, TT_COMMON_40102
            code, message, status = TT_COMMON_40102
            raise BizError(code, message, status)

        cur.execute(
            """
            SELECT au.user_no, au.status AS user_status, uc.status AS cred_status
            FROM app_user au
            LEFT JOIN user_credential uc ON uc.user_id = au.id
            WHERE au.id = %s AND au.deleted_at IS NULL
            """,
            (user_id,),
        )
        row = cur.fetchone()
        if (
            not row
            or row["user_status"] != "active"
            or (row["cred_status"] is not None and row["cred_status"] != "active")
        ):
            cur.execute(
                "UPDATE auth_session SET status='revoked', revoked_at=NOW() "
                "WHERE user_id=%s AND status='active'",
                (user_id,),
            )
            from core.errors import BizError, TT_AUTH_40106
            code, message, status = TT_AUTH_40106
            raise BizError(code, message, status)
        user_no = row["user_no"] or ""

        roles = _get_roles(cur, user_id)
        access_token = sign_access_token(user_id, user_no, roles)
        new_refresh_token, new_jti = sign_refresh_token(user_id)

        cur.execute(
            """
            INSERT INTO auth_session (user_id, refresh_jti, status, issued_at, expires_at)
            VALUES (%s, %s, 'active', NOW(), NOW() + make_interval(days => %s))
            """,
            (user_id, new_jti, settings.REFRESH_TOKEN_EXPIRES_DAYS),
        )

        user = build_user_response(cur, user_id)

    return {
        "accessToken": access_token,
        "refreshToken": new_refresh_token,
        "expiresIn": settings.ACCESS_TOKEN_EXPIRES,
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


def change_password(user_id: int, current_password: str, new_password: str) -> dict:
    """Update the signed-in account password after verifying the current one."""
    current_password = current_password or ""
    new_password = new_password or ""
    if not current_password:
        raise bad_request("请填写当前密码")
    if len(new_password) < 8 or len(new_password) > 128:
        raise bad_request("新密码长度须为 8-128 位")
    if current_password == new_password:
        raise bad_request("新密码不能与当前密码相同")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT password_hash FROM user_credential WHERE user_id=%s",
            (user_id,),
        )
        cred = cur.fetchone()
        if not cred:
            raise bad_request("当前账号不支持密码登录")
        if not verify_password(current_password, cred["password_hash"]):
            raise bad_request("当前密码不正确")
        cur.execute(
            "UPDATE user_credential SET password_hash=%s WHERE user_id=%s",
            (hash_password(new_password), user_id),
        )
        audit_record(
            "user.change_password", "user_credential", resource_id=user_id,
            actor_user_id=user_id, cur=cur,
        )
    return {"ok": True}
