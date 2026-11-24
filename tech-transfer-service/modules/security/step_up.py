"""高风险安全操作二次认证（Step-up Authentication）与 Step-up Grant 管理。

安全模型：
- 更换已绑定安全邮箱时，仅验证新邮箱 OTP 绝不足以授权覆盖旧安全邮箱；
- 根据账号类型提供可用二次认证方式：
  - 已配置密码账号 / 管理员账号：当前密码重新验证、原安全邮箱验证码、原安全手机验证码；
  - 无密码（微信快捷）账号：原安全邮箱验证码、原安全手机验证码、可信近期认证（JWT iat 窗口内）；
- Step-up Grant 在服务端表 `step_up_grant` 持久化 SHA-256 摘要，严格绑定：
  `user_id`、`purpose`、`session_fingerprint`、可选 `target_fingerprint`、短有效期与单次消费。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from datetime import datetime

import jwt
from fastapi import Request

from config import settings
from core.contact_validation import normalize_email
from core.errors import BizError, bad_request
from core.jwt_utils import decode_token
from core.password import verify_password
from db import get_cursor
from modules.audit.service import record as audit_record


def _expired(value) -> bool:
    return (value.timestamp() if isinstance(value, datetime) else float(value)) <= time.time()


def _step_up_secret() -> bytes:
    raw = settings.SECURITY_OTP_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _contact_blind_secret() -> bytes:
    raw = settings.SECURITY_CONTACT_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _session_digest(user_id: int, token_ver: object, token_iat: object, token_hash: str) -> str:
    payload = f"sess:{int(user_id)}:{token_ver}:{token_iat}:{token_hash}"
    return hmac.new(_step_up_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def session_fingerprint_from_request(request: Request, user_id: int | None = None) -> str:
    """基于已校验 Bearer Access Token 提取会话绑定指纹（不修改 JWT payload 或 actor 契约）。"""
    auth_header = request.headers.get("Authorization", "") if request else ""
    if not auth_header.startswith("Bearer "):
        return ""
    token = auth_header[7:].strip()
    if not token:
        return ""
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
        return ""
    sub = payload.get("sub")
    if user_id is not None and str(sub) != str(user_id):
        return ""
    uid = int(sub) if sub is not None else int(user_id or 0)
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    return _session_digest(uid, payload.get("ver"), payload.get("iat"), token_hash)


def token_iat_from_request(request: Request) -> int | None:
    auth_header = request.headers.get("Authorization", "") if request else ""
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
        iat = payload.get("iat")
        return int(iat) if iat is not None else None
    except Exception:
        return None


def get_available_step_up_methods(user_id: int, *, token_iat: int | None = None) -> list[str]:
    """查询用户当前可用的二次认证方式。"""
    methods: list[str] = []
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT uc.password_configured, uc.password_hash IS NOT NULL AS has_password,
                   EXISTS(SELECT 1 FROM user_role ur WHERE ur.user_id=uc.user_id
                          AND ur.role_code IN ('admin','platform_admin','org_admin')) OR
                   EXISTS(SELECT 1 FROM organization_membership om WHERE om.user_id=uc.user_id
                          AND om.role='admin' AND om.status='active') AS privileged
            FROM user_credential uc
            WHERE uc.user_id = %s AND uc.status = 'active'
            """,
            (user_id,),
        )
        cred = cur.fetchone()
        cur.execute(
            """
            SELECT contact_type, verification_method
            FROM account_contact
            WHERE user_id = %s AND status = 'active' AND verified_at IS NOT NULL
            """,
            (user_id,),
        )
        contacts = cur.fetchall()

    has_password = bool(cred and cred.get("password_configured") and cred.get("has_password"))
    is_privileged = bool(cred and cred.get("privileged"))
    if has_password:
        methods.append("password")

    for c in contacts:
        if (
            c["contact_type"] == "email"
            and c.get("verification_method") in {"email", "manual"}
            and settings.EMAIL_ENABLED
        ):
            if "old_email_otp" not in methods:
                methods.append("old_email_otp")
        elif (
            c["contact_type"] == "phone"
            and c.get("verification_method") in {"sms", "wechat", "manual"}
            and settings.SMS_ENABLED
        ):
            if "old_phone_otp" not in methods:
                methods.append("old_phone_otp")

    # 仅无密码且非高权限的微信等账号，允许在刚登录窗口内使用可信近期认证
    if not has_password and not is_privileged and token_iat is not None:
        if (time.time() - int(token_iat)) <= settings.STEP_UP_RECENT_AUTH_SECONDS:
            methods.append("recent_auth")
    return methods


def _get_verified_contact_for_step_up(cur, user_id: int, contact_type: str) -> str | None:
    allowed = ("email", "manual") if contact_type == "email" else ("sms", "wechat", "manual")
    cur.execute(
        """
        SELECT normalized_value, verification_method
        FROM account_contact
        WHERE user_id = %s AND contact_type = %s AND status = 'active' AND verified_at IS NOT NULL
        ORDER BY updated_at DESC LIMIT 1
        """,
        (user_id, contact_type),
    )
    row = cur.fetchone()
    if not row or row.get("verification_method") not in allowed:
        return None
    return row["normalized_value"]


def start_step_up_challenge(user_id: int, purpose: str, method: str, context) -> dict:
    """通过原已验证安全邮箱或安全手机发起二次认证 OTP。"""
    if purpose not in {"rebind_email", "rebind_phone"}:
        raise bad_request("不支持的二次认证用途")
    if method not in {"old_email_otp", "old_phone_otp"}:
        raise bad_request("该二次认证方式不需要发送验证码")

    contact_type = "email" if method == "old_email_otp" else "phone"
    with get_cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' AND deleted_at IS NULL", (user_id,))
        if not cur.fetchone():
            raise bad_request("账号不可用")
        dest = _get_verified_contact_for_step_up(cur, user_id, contact_type)

    if not dest:
        raise bad_request("当前账号暂无可用的原安全联系方式")

    challenge_id = str(uuid.uuid4())
    if contact_type == "email":
        from modules.security.email_gateway import _send_email
        from modules.security.service import _mask_contact

        _send_email(user_id, dest, "step_up_auth", "email_otp", challenge_id, context)
        masked = _mask_contact(dest, "email")
    else:
        from modules.security.service import _fingerprint, _hmac_code, _mask_contact
        from modules.security.sms_gateway import _engine as sms_engine_fn
        from modules.security.sms_gateway import get_sms_provider

        if not settings.SMS_ENABLED:
            raise BizError("TT_COMMON_50301", "短信验证服务暂未开放", 503)
        engine = sms_engine_fn()
        decision = engine.reserve(dest, str(user_id), context.ip, context.device_id, challenge_id)
        action = getattr(decision, "action", decision)
        if getattr(action, "value", action) != "ALLOW":
            raise BizError("TT_COMMON_42901", "操作过于频繁，请稍后重试", 429)
        code = f"{secrets.randbelow(1_000_000):06d}"
        ttl = settings.SMS_CODE_TTL_SECONDS
        masked = _mask_contact(dest, "phone")
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM app_user WHERE id=%s FOR UPDATE", (user_id,))
            cur.execute(
                """UPDATE auth_challenge SET status='cancelled' WHERE user_id=%s
                AND purpose='step_up_auth' AND channel='sms' AND status IN ('pending','pending_send')""",
                (user_id,),
            )
            cur.execute(
                """INSERT INTO auth_challenge
                (id,user_id,purpose,channel,destination_fingerprint,destination_masked,code_hash,
                 status,attempt_count,max_attempts,expires_at,send_request_id,send_state)
                VALUES (%s,%s,'step_up_auth','sms',%s,%s,%s,'pending_send',0,%s,
                        NOW()+make_interval(secs=>%s),%s,'reserved')""",
                (
                    challenge_id,
                    user_id,
                    _fingerprint(dest),
                    masked,
                    _hmac_code(challenge_id, "step_up_auth", dest, code),
                    settings.SMS_CODE_MAX_ATTEMPTS,
                    ttl,
                    challenge_id,
                ),
            )
        provider = get_sms_provider()
        try:
            receipt = provider.send_task(dest, code, "bind_phone", ttl, send_request_id=challenge_id)
            if not receipt.accepted:
                raise BizError("TT_COMMON_50301", "短信发送失败", 503)
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE auth_challenge SET send_state='accepted', status='pending' WHERE id=%s",
                    (challenge_id,),
                )
            engine.transition(challenge_id, "accepted")
        except Exception:
            engine.transition(challenge_id, "rejected")
            with get_cursor(commit=True) as cur:
                cur.execute(
                    "UPDATE auth_challenge SET send_state='rejected', status='failed' WHERE id=%s",
                    (challenge_id,),
                )
            raise

    return {
        "challengeId": challenge_id,
        "method": method,
        "maskedDestination": masked,
        "message": f"二次验证验证码已发送至 {masked}",
    }


def _target_fingerprint(target_contact: str | None) -> str | None:
    if not target_contact:
        return None
    norm = normalize_email(target_contact) if "@" in target_contact else target_contact.strip().lower()
    return hmac.new(_contact_blind_secret(), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_step_up_grant(
    user_id: int,
    *,
    purpose: str,
    method: str,
    session_fingerprint: str,
    token_iat: int | None = None,
    current_password: str | None = None,
    challenge_id: str | None = None,
    code: str | None = None,
    target_contact: str | None = None,
    request_id: str | None = None,
) -> dict:
    """核验二次认证凭据后签发绑定会话与用户的短期单次 Step-up Grant。"""
    if purpose not in {"rebind_email", "rebind_phone"}:
        raise bad_request("不支持的二次认证用途")
    if method not in {"password", "old_email_otp", "old_phone_otp", "recent_auth"}:
        raise bad_request("不支持的二次认证方式")
    if not session_fingerprint:
        raise BizError("TT_COMMON_40102", "当前会话无效，请重新登录", 401)

    target_fp = _target_fingerprint(target_contact)

    from modules.security.service import _challenge_transaction, _verify_challenge_code_match

    with _challenge_transaction() as (cur, tx_state):
        cur.execute(
            """
            SELECT au.status AS user_status, au.deleted_at,
                   uc.status AS cred_status, uc.password_configured, uc.password_hash,
                   EXISTS(SELECT 1 FROM user_role ur WHERE ur.user_id=au.id
                          AND ur.role_code IN ('admin','platform_admin','org_admin')) OR
                   EXISTS(SELECT 1 FROM organization_membership om WHERE om.user_id=au.id
                          AND om.role='admin' AND om.status='active') AS privileged
            FROM app_user au
            LEFT JOIN user_credential uc ON uc.user_id = au.id
            WHERE au.id = %s FOR UPDATE
            """,
            (user_id,),
        )
        account = cur.fetchone()
        if not account or account["deleted_at"] is not None or account["user_status"] != "active":
            raise bad_request("账号不可用")

        has_password = bool(
            account.get("cred_status") == "active"
            and account.get("password_configured")
            and account.get("password_hash")
        )
        is_privileged = bool(account.get("privileged"))

        if method == "password":
            if not has_password:
                raise bad_request("当前账号未设置登录密码，请选择其他二次验证方式")
            if not current_password or not verify_password(current_password, account["password_hash"]):
                raise bad_request("当前登录密码不正确")
        elif method == "recent_auth":
            if has_password or is_privileged:
                raise bad_request("当前账号不支持免凭据二次认证，请验证密码或原安全联系方式")
            if token_iat is None or (time.time() - int(token_iat)) > settings.STEP_UP_RECENT_AUTH_SECONDS:
                raise bad_request("当前登录已超过近期安全窗口，请重新登录后再操作")
        else:
            contact_type = "email" if method == "old_email_otp" else "phone"
            c_id = (challenge_id or "").strip()
            raw_code = (code or "").strip()
            if not c_id or not raw_code:
                raise bad_request("请填写二次验证挑战 ID 与验证码")
            dest = _get_verified_contact_for_step_up(cur, user_id, contact_type)
            if not dest:
                raise bad_request("当前账号暂无可用的原安全联系方式")
            cur.execute(
                """
                SELECT id, user_id, purpose, channel, destination_fingerprint, code_hash,
                       status, attempt_count, max_attempts, expires_at, send_state
                FROM auth_challenge
                WHERE id = %s AND user_id = %s FOR UPDATE
                """,
                (c_id, user_id),
            )
            row = cur.fetchone()
            if not row or row["purpose"] != "step_up_auth" or row["status"] != "pending":
                raise bad_request("二次验证挑战不存在或已失效")
            if _expired(row["expires_at"]):
                cur.execute("UPDATE auth_challenge SET status='expired' WHERE id=%s", (c_id,))
                raise bad_request("二次验证验证码已过期")
            if row["attempt_count"] >= row["max_attempts"]:
                cur.execute("UPDATE auth_challenge SET status='locked' WHERE id=%s", (c_id,))
                raise bad_request("二次验证错误次数超限")
            if not _verify_challenge_code_match(row, dest, raw_code):
                cur.execute(
                    """UPDATE auth_challenge SET attempt_count = attempt_count + 1,
                    status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE status END
                    WHERE id = %s""",
                    (c_id,),
                )
                remaining = max(0, row["max_attempts"] - (row["attempt_count"] + 1))
                raise bad_request(f"验证码不正确，还可尝试 {remaining} 次")
            cur.execute("UPDATE auth_challenge SET status='consumed', consumed_at=NOW() WHERE id=%s", (c_id,))

        tx_state["business_writes_started"] = True
        grant_token = secrets.token_urlsafe(32)
        grant_hash = hashlib.sha256(grant_token.encode("utf-8")).hexdigest()
        grant_id = str(uuid.uuid4())
        ttl = settings.STEP_UP_GRANT_TTL_SECONDS

        cur.execute(
            "UPDATE step_up_grant SET status='revoked' WHERE user_id=%s AND purpose=%s AND status='active'",
            (user_id, purpose),
        )
        cur.execute(
            """
            INSERT INTO step_up_grant (
                id, user_id, purpose, method, session_fingerprint, target_fingerprint,
                grant_hash, status, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 'active', NOW() + make_interval(secs => %s)
            )
            """,
            (grant_id, user_id, purpose, method, session_fingerprint, target_fp, grant_hash, ttl),
        )
        audit_record(
            "user.step_up_verified",
            "step_up_grant",
            resource_id=grant_id,
            actor_user_id=user_id,
            request_id=request_id,
            details={"purpose": purpose, "method": method},
            cur=cur,
        )

    return {
        "stepUpGrant": grant_token,
        "expiresIn": ttl,
        "method": method,
    }


def validate_step_up_grant(
    cur,
    *,
    user_id: int,
    grant_token: str | None,
    purpose: str,
    session_fingerprint: str,
    target_contact: str | None = None,
    consume: bool = False,
) -> dict:
    """校验证件是否有效；在最终换绑事务中 `consume=True` 原子核销。"""
    token = (grant_token or "").strip()
    if not token:
        raise BizError("TT_COMMON_40301", "更换已绑定安全邮箱前须先完成二次身份认证", 403)
    if not session_fingerprint:
        raise BizError("TT_COMMON_40102", "当前会话无效，请重新登录", 401)

    grant_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    cur.execute(
        """
        SELECT id, user_id, purpose, method, session_fingerprint, target_fingerprint, status, expires_at
        FROM step_up_grant
        WHERE grant_hash = %s FOR UPDATE
        """,
        (grant_hash,),
    )
    row = cur.fetchone()
    if not row:
        raise BizError("TT_COMMON_40301", "二次身份认证凭证无效或已失效", 403)
    if int(row["user_id"]) != int(user_id) or row["purpose"] != purpose:
        raise BizError("TT_COMMON_40301", "二次身份认证凭证与当前操作不匹配", 403)
    if row["status"] != "active":
        raise BizError("TT_COMMON_40301", "二次身份认证凭证已被使用或已失效", 403)
    if _expired(row["expires_at"]):
        cur.execute("UPDATE step_up_grant SET status='expired' WHERE id=%s", (row["id"],))
        raise BizError("TT_COMMON_40301", "二次身份认证已过期，请重新验证", 403)
    if not hmac.compare_digest(str(row["session_fingerprint"]), session_fingerprint):
        raise BizError("TT_COMMON_40301", "二次身份认证凭证与当前登录会话不匹配", 403)

    if row.get("target_fingerprint") and target_contact:
        expected_fp = _target_fingerprint(target_contact)
        if not expected_fp or not hmac.compare_digest(str(row["target_fingerprint"]), expected_fp):
            raise BizError("TT_COMMON_40301", "二次身份认证凭证绑定的目标邮箱不一致", 403)

    if consume:
        cur.execute(
            "UPDATE step_up_grant SET status='consumed', consumed_at=NOW() WHERE id=%s",
            (row["id"],),
        )
    return row
