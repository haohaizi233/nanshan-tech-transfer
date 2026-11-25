import hmac
import json
import time
import uuid

from config import settings
from core import auth_cache
from core.contact_validation import is_valid_phone, validate_email, validate_phone
from core.errors import TT_COMMON_40903, BizError, bad_request
from core.jwt_utils import sign_access_token, sign_refresh_token
from core.password import hash_password, verify_password
from db import get_cursor, run_with_deadlock_retry
from modules.audit.service import record as audit_record
from modules.identity.context import IdentityContext
from modules.identity.provider import ExternalIdentity


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
               up.subject_type, up.business_capabilities, up.wechat, up.avatar_file_id,
               EXISTS(SELECT 1 FROM user_credential uc WHERE uc.user_id=up.user_id
                      AND uc.password_configured) AS password_configured,
               EXISTS(SELECT 1 FROM external_identity ei WHERE ei.user_id=up.user_id
                      AND ei.issuer='wechat-mini' AND ei.unlinked_at IS NULL) AS wechat_bound
        FROM user_profile up
        WHERE up.user_id = %s
        """,
        (user_id,),
    )
    return cur.fetchone()


def _get_org_name(cur, org_id: int | None) -> str | None:
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
    cur.execute("SELECT user_no, status FROM app_user WHERE id=%s", (user_id,))
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
        {
            "id": row["id"],
            "orgId": row["org_id"],
            "orgName": row["org_name"],
            "role": row["role"],
            "status": row["status"],
            "version": row["version"],
        }
        for row in cur.fetchall()
    ]
    return {
        "userId": user_id,
        "userNo": user["user_no"],
        "avatarFileId": profile.get("avatar_file_id") if profile else None,
        "avatar": (
            f"{settings.MEDIA_BASE_URL.rstrip('/')}/{profile['avatar_file_id']}"
            if profile and profile.get("avatar_file_id")
            else None
        ),
        "passwordLoginEnabled": profile.get("password_configured", True) if profile else True,
        "wechatBound": profile.get("wechat_bound", False) if profile else False,
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


def _ts_to_epoch(value) -> int | None:
    if value is None:
        return None
    if hasattr(value, "timestamp"):
        return int(value.timestamp())
    try:
        ts = int(value)
        return ts if ts > 0 else None
    except (TypeError, ValueError):
        return None


def _insert_auth_session(cur, user_id: int, refresh_jti: str, sid: str | None, auth_time: int | None) -> None:
    cur.execute(
        """
        INSERT INTO auth_session (user_id, refresh_jti, status, issued_at, expires_at, sid, auth_time)
        VALUES (
            %s, %s, 'active', NOW(), NOW() + make_interval(days => %s), %s,
            CASE WHEN %s IS NOT NULL THEN to_timestamp(%s) ELSE NULL END
        )
        """,
        (user_id, refresh_jti, settings.REFRESH_TOKEN_EXPIRES_DAYS, sid, auth_time, auth_time),
    )


def bootstrap_session(ext: ExternalIdentity) -> dict:
    from core.errors import TT_AUTH_40106

    identity, is_new = find_or_create_user(ext)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT user_no, status, deleted_at, session_version FROM app_user WHERE id=%s FOR UPDATE",
            (identity.userId,),
        )
        row = cur.fetchone()
        if not row or row.get("deleted_at") is not None or row.get("status", "active") != "active":
            raise BizError(*TT_AUTH_40106)
        user_no = row.get("user_no") or ""
        session_version = int(row.get("session_version") or 1)
        sid = str(uuid.uuid4())
        auth_time = int(time.time())

        access_token = sign_access_token(
            identity.userId,
            user_no,
            identity.roles,
            session_version=session_version,
            sid=sid,
            auth_time=auth_time,
        )
        refresh_token, jti = sign_refresh_token(identity.userId, sid=sid)
        _insert_auth_session(cur, identity.userId, jti, sid, auth_time)

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
    cur.execute("SELECT user_no, status, session_version FROM app_user WHERE id=%s FOR UPDATE", (user_id,))
    row = cur.fetchone()
    user_no = (row and row.get("user_no")) or ""
    session_version = int((row and row.get("session_version")) or 1)
    sid = str(uuid.uuid4())
    auth_time = int(time.time())

    access_token = sign_access_token(
        user_id,
        user_no,
        roles,
        session_version=session_version,
        sid=sid,
        auth_time=auth_time,
    )
    refresh_token, jti = sign_refresh_token(user_id, sid=sid)
    _insert_auth_session(cur, user_id, jti, sid, auth_time)
    return {
        "accessToken": access_token,
        "refreshToken": refresh_token,
        "expiresIn": settings.ACCESS_TOKEN_EXPIRES,
    }


def register_user(phone: str, password: str, display_name: str | None = None) -> dict:
    """手机号注册：创建 app_user + user_profile + user_credential + user_role。

    注册成功后直接签发会话（免登录），返回与 password_login_session 相同结构。
    手机号已注册时抛 TT_AUTH_40901。
    """
    from core.errors import TT_AUTH_40901, BizError, bad_request
    from core.password import hash_password

    try:
        phone = validate_phone(phone, required=True)
    except BizError:
        raise bad_request("请输入11位手机号", details="请输入11位手机号")
    if not password:
        raise bad_request("请输入密码", details="请输入密码")
    if len(password) < 8:
        raise bad_request("密码至少8位", details="密码至少8位")
    if len(password) > 128:
        raise bad_request("密码长度不能超过128位", details="密码长度不能超过128位")

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
    SELECT uc.user_id, uc.password_hash, uc.password_configured, uc.status AS cred_status,
           au.status AS user_status
    FROM user_credential uc
    JOIN app_user au ON au.id = uc.user_id
    WHERE au.deleted_at IS NULL AND {where}
"""


def _verify_login_and_issue(cred: dict | None, password: str) -> dict:
    """密码校验（锁外）+ 锁内凭证/状态二次核验 + 签发会话。

    防止在慢密码哈希校验窗口内发生并发改密/重置后仍以旧密码签发新版有效会话；
    用户不存在 / 密码错误返回同一文案（防账号枚举）。
    """
    from core.errors import TT_AUTH_40105, TT_AUTH_40106

    if (
        cred is None
        or not cred.get("password_configured", True)
        or not verify_password(password, cred["password_hash"])
    ):
        code, message, status = TT_AUTH_40105
        raise BizError(code, message, status)

    if cred["cred_status"] != "active" or cred["user_status"] != "active":
        code, message, status = TT_AUTH_40106
        raise BizError(code, message, status)

    user_id = int(cred["user_id"])
    expected_hash = str(cred["password_hash"])

    def _attempt() -> dict:
        with get_cursor(commit=True) as cur:
            # 全局规范锁顺序：app_user -> user_credential -> ... -> auth_session
            cur.execute(
                "SELECT id, status, deleted_at FROM app_user WHERE id=%s FOR UPDATE",
                (user_id,),
            )
            au = cur.fetchone()
            if not au or au.get("deleted_at") is not None or au.get("status") != "active":
                raise BizError(*TT_AUTH_40106)

            cur.execute(
                "SELECT password_hash, password_configured, status FROM user_credential WHERE user_id=%s FOR UPDATE",
                (user_id,),
            )
            fresh_cred = cur.fetchone()
            if not fresh_cred or fresh_cred.get("status") != "active":
                raise BizError(*TT_AUTH_40106)
            if not fresh_cred.get("password_configured", True) or not hmac.compare_digest(
                str(fresh_cred.get("password_hash") or ""),
                expected_hash,
            ):
                raise BizError(*TT_AUTH_40105)

            roles = _get_roles(cur, user_id)
            result = _issue_session(cur, user_id, roles)
            result["user"] = build_user_response(cur, user_id)
            result["isNewUser"] = False
            return result

    return run_with_deadlock_retry(_attempt)


def password_login_session(username: str, password: str) -> dict:
    """账号密码登录（后台管理端：按 user_credential.username 校验，无宿主票据）。"""
    from core.errors import TT_AUTH_40105

    if not username or not password:
        raise BizError(*TT_AUTH_40105)

    with get_cursor() as cur:
        cur.execute(_LOGIN_CRED_SQL.format(where="uc.username = %s"), (username,))
        cred = cur.fetchone()
    return _verify_login_and_issue(cred, password)


def login_phone_session(phone: str, password: str) -> dict:
    """手机号密码登录（小程序端：按 user_credential.phone 校验）。

    phone 未命中时回退按 username 匹配（兜底迁移 012 回填时因冲突跳过的
    phone 为 NULL 且 username=手机号 的存量账号）。
    """
    from core.errors import TT_AUTH_40105

    if not phone or not password:
        raise BizError(*TT_AUTH_40105)

    with get_cursor() as cur:
        cur.execute(_LOGIN_CRED_SQL.format(where="uc.phone = %s"), (phone,))
        cred = cur.fetchone()
        if cred is None:
            cur.execute(
                _LOGIN_CRED_SQL.format(where="uc.phone IS NULL AND uc.username = %s"),
                (phone,),
            )
            cred = cur.fetchone()
    return _verify_login_and_issue(cred, password)


def create_password_account(
    cur, username: str, password: str, display_name=None, phone=None, email=None
) -> tuple[int, str]:
    """在调用方事务游标内创建密码账号全套（app_user/profile/credential/role）。

    返回 (user_id, user_no)。供普通注册与机构注册申请（单事务创建账号+申请）复用。
    填写的 11 位手机号除 user_profile.phone 外同时写入 user_credential.phone
    （小程序端可用手机号+密码登录）；手机号已被注册时抛冲突。
    """
    cred_phone = phone if is_valid_phone(phone) else None
    if cred_phone:
        cur.execute(
            "SELECT 1 FROM user_credential WHERE phone = %s OR (phone IS NULL AND username = %s)",
            (cred_phone, cred_phone),
        )
        if cur.fetchone():
            code, _message, status = TT_COMMON_40903
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
            code, _message, status = TT_COMMON_40903
            raise BizError(code, "该登录账号已存在", status)

        user_id, user_no = create_password_account(
            cur,
            username,
            password,
            display_name,
            phone,
            email,
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
    import jwt as _jwt

    from core.errors import TT_AUTH_40106, TT_COMMON_40102
    from core.jwt_utils import decode_no_verify_exp

    try:
        payload = decode_no_verify_exp(refresh_token)
    except _jwt.InvalidTokenError:
        raise BizError(*TT_COMMON_40102) from None

    if payload.get("type") != "refresh":
        raise BizError(*TT_COMMON_40102)

    jti = payload.get("jti")
    if not jti:
        raise BizError(*TT_COMMON_40102)
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError):
        raise BizError(*TT_COMMON_40102) from None

    def _attempt() -> tuple[dict | None, bool]:
        with get_cursor() as read_cur:
            read_cur.execute(
                "SELECT user_id, sid, status FROM auth_session WHERE refresh_jti=%s",
                (jti,),
            )
            sess_row = read_cur.fetchone()
        if not sess_row or int(sess_row.get("user_id") or 0) != user_id:
            raise BizError(*TT_COMMON_40102)

        with get_cursor(commit=True) as cur:
            # 全局规范锁顺序：app_user -> user_credential -> ... -> step_up_grant -> auth_session
            cur.execute(
                """
                SELECT au.user_no, au.status AS user_status, au.deleted_at, au.session_version
                FROM app_user au
                WHERE au.id = %s
                FOR UPDATE OF au
                """,
                (user_id,),
            )
            au_row = cur.fetchone()
            cur.execute(
                "SELECT status AS cred_status FROM user_credential WHERE user_id = %s FOR UPDATE",
                (user_id,),
            )
            cred_row = cur.fetchone()
            cred_status = cred_row.get("cred_status") if isinstance(cred_row, dict) else None
            if (
                not au_row
                or au_row.get("deleted_at") is not None
                or au_row.get("user_status") != "active"
                or (cred_status is not None and cred_status != "active")
            ):
                cur.execute(
                    "UPDATE step_up_grant SET status='revoked' WHERE user_id=%s AND status='active'",
                    (user_id,),
                )
                cur.execute(
                    "UPDATE auth_session SET status='revoked', revoked_at=NOW() WHERE user_id=%s AND status='active'",
                    (user_id,),
                )
                return None, True

            cur.execute(
                """
                UPDATE auth_session
                SET status='consumed', consumed_at=NOW()
                WHERE refresh_jti=%s AND user_id=%s AND status='active'
                  AND (expires_at IS NULL OR expires_at >= NOW())
                RETURNING sid, auth_time
                """,
                (jti, user_id),
            )
            if cur.rowcount == 0:
                raise BizError(*TT_COMMON_40102)
            consumed_row = cur.fetchone()

            raw_sid = consumed_row.get("sid") if isinstance(consumed_row, dict) else None
            sid = str(raw_sid) if raw_sid else None
            auth_time = _ts_to_epoch(consumed_row.get("auth_time")) if isinstance(consumed_row, dict) else None

            user_no = au_row["user_no"] or ""
            session_version = int(au_row.get("session_version") or 1)

            roles = _get_roles(cur, user_id)
            access_token = sign_access_token(
                user_id,
                user_no,
                roles,
                session_version=session_version,
                sid=sid,
                auth_time=auth_time,
            )
            new_refresh_token, new_jti = sign_refresh_token(user_id, sid=sid)
            _insert_auth_session(cur, user_id, new_jti, sid, auth_time)
            user = build_user_response(cur, user_id)
            return {
                "accessToken": access_token,
                "refreshToken": new_refresh_token,
                "expiresIn": settings.ACCESS_TOKEN_EXPIRES,
                "user": user,
                "isNewUser": False,
            }, False

    result, disabled_revoked = run_with_deadlock_retry(_attempt)
    if disabled_revoked:
        auth_cache.invalidate_user(user_id)
        raise BizError(*TT_AUTH_40106)
    assert result is not None
    return result


def logout_session(refresh_token: str) -> dict:
    import jwt as _jwt

    from core.jwt_utils import decode_no_verify_exp

    try:
        payload = decode_no_verify_exp(refresh_token)
    except _jwt.InvalidTokenError:
        return {"revoked": False}

    if payload.get("type") not in (None, "refresh"):
        return {"revoked": False}

    jti = payload.get("jti")
    if not jti:
        return {"revoked": False}

    def _attempt() -> tuple[bool, int | None]:
        with get_cursor() as read_cur:
            read_cur.execute(
                "SELECT user_id, sid, status FROM auth_session WHERE refresh_jti=%s",
                (jti,),
            )
            sess_row = read_cur.fetchone()

        raw_uid = (sess_row.get("user_id") if isinstance(sess_row, dict) else None) or payload.get("sub")
        uid: int | None = int(raw_uid) if raw_uid is not None else None
        raw_sid = (sess_row.get("sid") if isinstance(sess_row, dict) else None) or payload.get("sid")
        sid: str | None = str(raw_sid) if raw_sid else None
        if sess_row is None and uid is None:
            return False, None

        revoked_local = False
        with get_cursor(commit=True) as cur:
            # 全局规范锁顺序：app_user -> ... -> step_up_grant -> auth_session
            if uid is not None:
                cur.execute("SELECT id FROM app_user WHERE id=%s FOR UPDATE", (uid,))
            if sid and uid is not None:
                cur.execute(
                    "UPDATE step_up_grant SET status='revoked' WHERE user_id=%s AND session_id=%s AND status='active'",
                    (uid, sid),
                )
                cur.execute(
                    "UPDATE auth_session SET status='revoked', revoked_at=NOW() "
                    "WHERE user_id=%s AND sid=%s AND status='active'",
                    (uid, sid),
                )
                revoked_local = cur.rowcount > 0
            else:
                cur.execute(
                    "UPDATE auth_session SET status='revoked', revoked_at=NOW() "
                    "WHERE refresh_jti=%s AND status='active'",
                    (jti,),
                )
                revoked_local = cur.rowcount > 0
        return revoked_local, uid

    revoked, uid = run_with_deadlock_retry(_attempt)
    if revoked and uid is not None:
        auth_cache.invalidate_user(uid)
    return {"revoked": revoked}


def change_password(user_id: int, current_password: str, new_password: str) -> dict:
    """Set a first password or update an existing password after verification."""
    current_password = current_password or ""
    new_password = new_password or ""
    if len(new_password) < 8 or len(new_password) > 128:
        raise bad_request("新密码长度须为 8-128 位")
    if current_password == new_password:
        raise bad_request("新密码不能与当前密码相同")

    with get_cursor() as cur:
        cur.execute(
            "SELECT password_hash, password_configured, status FROM user_credential WHERE user_id=%s",
            (user_id,),
        )
        pre_cred = cur.fetchone()
    if not pre_cred:
        raise bad_request("当前账号不支持密码登录")
    if pre_cred.get("status", "active") != "active":
        raise bad_request("当前账号不可修改密码")
    if pre_cred.get("password_configured", True) and not current_password:
        raise bad_request("请填写当前密码")
    if pre_cred.get("password_configured", True) and not verify_password(current_password, pre_cred["password_hash"]):
        raise bad_request("当前密码不正确")

    new_hash = hash_password(new_password)

    def _attempt() -> None:
        with get_cursor(commit=True) as cur:
            # 全局统一锁顺序：app_user -> user_credential -> auth_challenge -> recovery_grant -> step_up_grant -> auth_session
            cur.execute(
                "SELECT id, status, deleted_at FROM app_user WHERE id=%s FOR UPDATE",
                (user_id,),
            )
            user_row = cur.fetchone()
            if not user_row or user_row.get("deleted_at") is not None or user_row.get("status", "active") != "active":
                raise bad_request("当前账号不可修改密码")
            cur.execute(
                "SELECT password_hash, password_configured, status FROM user_credential WHERE user_id=%s FOR UPDATE",
                (user_id,),
            )
            cred = cur.fetchone()
            if not cred:
                raise bad_request("当前账号不支持密码登录")
            if cred.get("status", "active") != "active":
                raise bad_request("当前账号不可修改密码")
            if cred.get("password_configured", True) and not current_password:
                raise bad_request("请填写当前密码")
            if cred.get("password_configured", True) and not verify_password(current_password, cred["password_hash"]):
                raise bad_request("当前密码不正确")

            cur.execute(
                "UPDATE user_credential SET password_hash=%s, password_configured=true WHERE user_id=%s",
                (new_hash, user_id),
            )
            cur.execute(
                """
                UPDATE auth_challenge
                SET status='cancelled'
                WHERE user_id=%s
                  AND purpose IN ('password_recovery', 'step_up_auth')
                  AND status IN ('pending_send', 'pending', 'verified')
                """,
                (user_id,),
            )
            cur.execute(
                "UPDATE recovery_grant SET status='revoked' WHERE user_id=%s AND status='active'",
                (user_id,),
            )
            cur.execute(
                "UPDATE step_up_grant SET status='revoked' WHERE user_id=%s AND status='active'",
                (user_id,),
            )
            cur.execute(
                "UPDATE auth_session SET status='revoked', revoked_at=NOW() WHERE user_id=%s AND status='active'",
                (user_id,),
            )
            cur.execute(
                "UPDATE app_user SET session_version = session_version + 1 WHERE id = %s",
                (user_id,),
            )
            audit_record(
                "user.change_password",
                "user_credential",
                resource_id=user_id,
                actor_user_id=user_id,
                cur=cur,
            )

    run_with_deadlock_retry(_attempt)
    auth_cache.invalidate_user(user_id)
    return {"ok": True}
