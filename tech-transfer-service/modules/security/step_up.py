"""高风险安全操作二次认证（Step-up Authentication）与 Step-up Grant 管理。

安全模型：
- 统一 `SecurityOperationPolicy` 策略矩阵，区分 `bind_email` / `rebind_email` / `bind_phone` /
  `rebind_phone` / `password_recovery` / `change_password`；
- 首次绑定与换绑安全邮箱均强制要求 Step-up Grant，且必须强绑定 `purpose`、`user_id`、
  稳定逻辑会话（`sid` + `session_version`）以及规范化后的目标邮箱指纹（禁止可选旁路）；
- `recent_auth` 严格依赖服务端在真实身份认证时签发的不可篡改 `auth_time`（Refresh Token 绝不重置），
  且禁止有密码账号与高权限账号使用 `recent_auth` 弱路径；
- 校验 Grant 时检查服务端会话撤销状态（`auth_session` / `session_version`）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import jwt
from fastapi import Request

from config import settings
from core.contact_validation import normalize_email
from core.errors import BizError, bad_request
from core.jwt_utils import decode_token
from core.password import verify_password
from db import get_cursor
from modules.audit.service import record as audit_record


@dataclass(frozen=True)
class SecurityOperationPolicy:
    purpose: str
    requires_step_up: bool
    requires_target_binding: bool
    allowed_methods: tuple[str, ...]
    max_auth_age_seconds: int


SECURITY_OPERATION_POLICIES: dict[str, SecurityOperationPolicy] = {
    "bind_email": SecurityOperationPolicy(
        purpose="bind_email",
        requires_step_up=True,
        requires_target_binding=True,
        allowed_methods=("password", "old_phone_otp", "recent_auth"),
        max_auth_age_seconds=settings.STEP_UP_RECENT_AUTH_SECONDS,
    ),
    "rebind_email": SecurityOperationPolicy(
        purpose="rebind_email",
        requires_step_up=True,
        requires_target_binding=True,
        allowed_methods=("password", "old_email_otp", "old_phone_otp", "recent_auth"),
        max_auth_age_seconds=settings.STEP_UP_RECENT_AUTH_SECONDS,
    ),
    "bind_phone": SecurityOperationPolicy(
        purpose="bind_phone",
        requires_step_up=False,
        requires_target_binding=False,
        allowed_methods=("password", "old_email_otp", "recent_auth"),
        max_auth_age_seconds=settings.STEP_UP_RECENT_AUTH_SECONDS,
    ),
    "rebind_phone": SecurityOperationPolicy(
        purpose="rebind_phone",
        requires_step_up=False,
        requires_target_binding=False,
        allowed_methods=("password", "old_email_otp", "old_phone_otp", "recent_auth"),
        max_auth_age_seconds=settings.STEP_UP_RECENT_AUTH_SECONDS,
    ),
    "password_recovery": SecurityOperationPolicy(
        purpose="password_recovery",
        requires_step_up=False,
        requires_target_binding=False,
        allowed_methods=(),
        max_auth_age_seconds=0,
    ),
    "change_password": SecurityOperationPolicy(
        purpose="change_password",
        requires_step_up=True,
        requires_target_binding=False,
        allowed_methods=("password",),
        max_auth_age_seconds=settings.STEP_UP_RECENT_AUTH_SECONDS,
    ),
}


def get_security_operation_policy(purpose: str) -> SecurityOperationPolicy:
    policy = SECURITY_OPERATION_POLICIES.get(purpose)
    if not policy:
        raise bad_request("不支持的安全操作策略")
    return policy


@dataclass(frozen=True)
class SessionAuthContext:
    user_id: int
    sid: str | None
    auth_time: int | None
    session_version: int
    token_iat: int | None
    legacy_fingerprint: str

    def fingerprint_for_purpose(self, purpose: str) -> str:
        if self.sid:
            return _stable_session_digest(self.user_id, self.sid, self.session_version, purpose)
        return self.legacy_fingerprint


def _expired(value: Any) -> bool:
    return (value.timestamp() if isinstance(value, datetime) else float(value)) <= time.time()


def _step_up_secret() -> bytes:
    raw = settings.SECURITY_OTP_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _contact_blind_secret() -> bytes:
    raw = settings.SECURITY_CONTACT_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _stable_session_digest(user_id: int, sid: str, session_version: object, purpose: str) -> str:
    payload = f"sid:{int(user_id)}:{sid}:{session_version}:{purpose}"
    return hmac.new(_step_up_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _legacy_session_digest(user_id: int, token_ver: object, token_iat: object, token_hash: str) -> str:
    payload = f"sess:{int(user_id)}:{token_ver}:{token_iat}:{token_hash}"
    return hmac.new(_step_up_secret(), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def _parse_valid_uuid(raw: Any) -> str | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return str(uuid.UUID(raw.strip()))
    except (ValueError, AttributeError):
        return None


def _parse_trusted_auth_time(raw: Any, now: int | None = None) -> int | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        ts = int(raw)
    except (TypeError, ValueError):
        return None
    cur_now = int(time.time()) if now is None else int(now)
    # 拒绝异常/伪造未来时间戳（允许 60s 时钟偏移）或非正值
    if ts <= 0 or ts > cur_now + 60:
        return None
    return ts


def session_context_from_request(request: Request | None, user_id: int | None = None) -> SessionAuthContext | None:
    """从已验证 Bearer Access Token 解析稳定会话上下文（不回退用 iat 充当 auth_time）。"""
    auth_header = request.headers.get("Authorization", "") if request else ""
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    try:
        payload = decode_token(token)
    except (jwt.ExpiredSignatureError, jwt.InvalidTokenError, Exception):
        return None
    if payload.get("type") != "access":
        return None
    sub = payload.get("sub")
    if sub is None:
        return None
    if user_id is not None and str(sub) != str(user_id):
        return None
    uid = int(sub)
    ver = int(payload["ver"]) if payload.get("ver") is not None else 1
    sid = _parse_valid_uuid(payload.get("sid"))
    auth_time = _parse_trusted_auth_time(payload.get("auth_time"))
    raw_iat = payload.get("iat")
    token_iat = int(raw_iat) if raw_iat is not None else None
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
    legacy_fp = _legacy_session_digest(uid, payload.get("ver"), raw_iat, token_hash)
    return SessionAuthContext(
        user_id=uid,
        sid=sid,
        auth_time=auth_time,
        session_version=ver,
        token_iat=token_iat,
        legacy_fingerprint=legacy_fp,
    )


def session_fingerprint_from_request(request: Request | None, user_id: int | None = None, *, purpose: str = "") -> str:
    """基于已校验 Bearer Access Token 提取会话绑定指纹（兼容传 purpose 与不传 purpose 调用）。"""
    ctx = session_context_from_request(request, user_id)
    if not ctx:
        return ""
    if ctx.sid:
        return ctx.fingerprint_for_purpose(purpose)
    return ctx.legacy_fingerprint


def trusted_auth_time_from_request(request: Request | None, user_id: int | None = None) -> int | None:
    ctx = session_context_from_request(request, user_id)
    return ctx.auth_time if ctx else None


def token_iat_from_request(request: Request | None) -> int | None:
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


def get_available_step_up_methods(
    user_id: int,
    *,
    auth_time: int | None = None,
    has_sid: bool | None = None,
) -> list[str]:
    """查询用户当前可用的二次认证方式。

    `recent_auth` 严格依赖真实登录/认证产生的 `auth_time`（且禁止高权限及已设密码账号使用）。
    """
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

    # 仅无密码、非高权限账号，在具备可信 auth_time（非未来、未过期）且未缺失会话 ID 时允许 recent_auth
    trusted_ts = _parse_trusted_auth_time(auth_time)
    if not has_password and not is_privileged and trusted_ts is not None and (has_sid is not False):
        if (time.time() - trusted_ts) <= settings.STEP_UP_RECENT_AUTH_SECONDS:
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
    return str(row["normalized_value"])


def _normalize_target_contact(purpose: str, target_contact: str | None) -> str | None:
    raw = (target_contact or "").strip()
    if not raw:
        return None
    if purpose in {"bind_email", "rebind_email"} or "@" in raw:
        return str(normalize_email(raw))
    return raw.lower()


def _target_fingerprint(target_contact: str | None, *, purpose: str = "email") -> str | None:
    norm = _normalize_target_contact(purpose, target_contact)
    if not norm:
        return None
    return hmac.new(_contact_blind_secret(), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def start_step_up_challenge(
    user_id: int,
    purpose: str,
    method: str,
    context,
    *,
    target_contact: str | None = None,
    session_ctx: SessionAuthContext | None = None,
) -> dict[str, Any]:
    """通过原已验证安全邮箱或安全手机发起二次认证 OTP（绑定用途、会话及目标联系方式）。"""
    policy = get_security_operation_policy(purpose)
    if purpose not in {"bind_email", "rebind_email", "bind_phone", "rebind_phone"}:
        raise bad_request("不支持的二次认证用途")
    if method not in {"old_email_otp", "old_phone_otp"} or method not in policy.allowed_methods:
        raise bad_request("该二次认证方式不需要发送验证码或不受当前操作策略支持")

    norm_target: str | None = None
    target_fp: str | None = None
    if policy.requires_target_binding:
        norm_target = _normalize_target_contact(purpose, target_contact)
        if not norm_target:
            raise bad_request("邮箱二次认证必须指定目标邮箱地址")
        target_fp = _target_fingerprint(norm_target, purpose=purpose)

    contact_type = "email" if method == "old_email_otp" else "phone"
    with get_cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' AND deleted_at IS NULL", (user_id,))
        if not cur.fetchone():
            raise bad_request("账号不可用")
        if purpose in {"bind_email", "rebind_email"}:
            existing_email = _get_verified_contact_for_step_up(cur, user_id, "email")
            if purpose == "rebind_email" and not existing_email:
                raise bad_request("当前账号尚未绑定安全邮箱，请先完成首次绑定")
            if purpose == "bind_email" and existing_email:
                raise bad_request("当前账号已绑定安全邮箱，请进入换绑流程")
            if existing_email and existing_email == norm_target:
                raise bad_request("新邮箱与当前已绑定安全邮箱相同")
        dest = _get_verified_contact_for_step_up(cur, user_id, contact_type)

    if not dest:
        raise bad_request("当前账号暂无可用的原安全联系方式")

    challenge_id = str(uuid.uuid4())
    sid = session_ctx.sid if session_ctx else None

    if contact_type == "email":
        from modules.security.email_gateway import _send_email
        from modules.security.service import _mask_contact

        _send_email(
            user_id,
            dest,
            "step_up_auth",
            "email_otp",
            challenge_id,
            context,
            sub_purpose=purpose,
            session_id=sid,
            target_fingerprint=target_fp,
        )
        masked = _mask_contact(dest, "email")
    else:
        from modules.security.service import _fingerprint, _hmac_code, _mask_contact
        from modules.security.sms_gateway import _engine as sms_engine_fn
        from modules.security.sms_gateway import get_sms_provider
        from modules.security.state_machine import transition_delivery_state

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
            try:
                cur.execute("SAVEPOINT sp_stepup_sms_037")
                cur.execute(
                    """INSERT INTO auth_challenge
                    (id,user_id,purpose,channel,destination_fingerprint,destination_masked,code_hash,
                     status,attempt_count,max_attempts,expires_at,send_request_id,send_state,
                     session_id,sub_purpose,target_fingerprint)
                    VALUES (%s,%s,'step_up_auth','sms',%s,%s,%s,'pending_send',0,%s,
                            NOW()+make_interval(secs=>%s),%s,'reserved',%s,%s,%s)""",
                    (
                        challenge_id,
                        user_id,
                        _fingerprint(dest),
                        masked,
                        _hmac_code(challenge_id, "step_up_auth", dest, code),
                        settings.SMS_CODE_MAX_ATTEMPTS,
                        ttl,
                        challenge_id,
                        sid,
                        purpose,
                        target_fp,
                    ),
                )
                cur.execute("RELEASE SAVEPOINT sp_stepup_sms_037")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_stepup_sms_037")
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
            with get_cursor(commit=True) as cur:
                transition_delivery_state(cur, challenge_id, ("reserved",), "sending")
            receipt = provider.send_task(dest, code, "bind_phone", ttl, send_request_id=challenge_id)
            if not receipt.accepted:
                raise BizError("TT_COMMON_50301", "短信发送失败", 503)
            with get_cursor(commit=True) as cur:
                transition_delivery_state(cur, challenge_id, ("sending", "reserved"), "accepted")
            engine.transition(challenge_id, "accepted")
        except Exception:
            engine.transition(challenge_id, "rejected")
            with get_cursor(commit=True) as cur:
                transition_delivery_state(
                    cur,
                    challenge_id,
                    ("reserved", "sending"),
                    "rejected",
                    challenge_status_on_failure="failed",
                )
            raise

    return {
        "challengeId": challenge_id,
        "method": method,
        "maskedDestination": masked,
        "message": f"二次验证验证码已发送至 {masked}",
    }


def _resolve_session_binding(
    *,
    purpose: str,
    session_ctx: SessionAuthContext | None,
    session_fingerprint: str | None,
) -> tuple[str, str | None, int | None]:
    """计算当前操作的会话绑定摘要及关联 (sid, auth_time)。"""
    if session_ctx is not None:
        return (
            session_ctx.fingerprint_for_purpose(purpose),
            session_ctx.sid,
            session_ctx.auth_time,
        )
    return (session_fingerprint or ""), None, None


def issue_step_up_grant(
    user_id: int,
    *,
    purpose: str,
    method: str,
    session_fingerprint: str = "",
    session_ctx: SessionAuthContext | None = None,
    auth_time: int | None = None,
    current_password: str | None = None,
    challenge_id: str | None = None,
    code: str | None = None,
    target_contact: str | None = None,
    request_id: str | None = None,
) -> dict[str, Any]:
    """核验二次认证凭据后签发绑定用户、会话、用途与目标联系人的短期单次 Step-up Grant。"""
    policy = get_security_operation_policy(purpose)
    if purpose not in {"bind_email", "rebind_email", "bind_phone", "rebind_phone"}:
        raise bad_request("不支持的二次认证用途")
    if (
        method not in {"password", "old_email_otp", "old_phone_otp", "recent_auth"}
        or method not in policy.allowed_methods
    ):
        raise bad_request("不支持的二次认证方式")

    effective_fp, session_id, ctx_auth_time = _resolve_session_binding(
        purpose=purpose,
        session_ctx=session_ctx,
        session_fingerprint=session_fingerprint,
    )
    if not effective_fp:
        raise BizError("TT_COMMON_40102", "当前会话无效，请重新登录", 401)

    target_fp: str | None = None
    if policy.requires_target_binding:
        norm_target = _normalize_target_contact(purpose, target_contact)
        if not norm_target:
            raise bad_request("签发邮箱敏感操作授权必须绑定目标邮箱")
        target_fp = _target_fingerprint(norm_target, purpose=purpose)
        if not target_fp:
            raise bad_request("目标邮箱格式不正确")
    elif target_contact:
        target_fp = _target_fingerprint(target_contact, purpose=purpose)

    effective_auth_time = ctx_auth_time if ctx_auth_time is not None else auth_time

    from modules.security.service import _challenge_transaction, _verify_challenge_code_match

    with _challenge_transaction() as (cur, tx_state):
        # 全局规范锁顺序：app_user -> user_credential -> auth_challenge -> account_contact -> step_up_grant
        cur.execute(
            """
            SELECT au.status AS user_status, au.deleted_at, au.session_version,
                   uc.status AS cred_status, uc.password_configured, uc.password_hash,
                   EXISTS(SELECT 1 FROM user_role ur WHERE ur.user_id=au.id
                          AND ur.role_code IN ('admin','platform_admin','org_admin')) OR
                   EXISTS(SELECT 1 FROM organization_membership om WHERE om.user_id=au.id
                          AND om.role='admin' AND om.status='active') AS privileged
            FROM app_user au
            LEFT JOIN user_credential uc ON uc.user_id = au.id
            WHERE au.id = %s FOR UPDATE OF au
            """,
            (user_id,),
        )
        account = cur.fetchone()
        if not account or account["deleted_at"] is not None or account["user_status"] != "active":
            raise bad_request("账号不可用")

        if session_ctx is not None:
            current_ver = int(account.get("session_version") or 1)
            if int(session_ctx.session_version) != current_ver:
                raise BizError("TT_COMMON_40102", "登录已失效，请重新登录", 401)
            if session_id and _session_revoked_in_db(cur, user_id, session_id):
                raise BizError("TT_COMMON_40102", "当前会话已注销，请重新登录", 401)

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
            trusted_ts = _parse_trusted_auth_time(effective_auth_time)
            if session_ctx is not None and not session_ctx.sid:
                trusted_ts = None
            if trusted_ts is None or (time.time() - trusted_ts) > policy.max_auth_age_seconds:
                raise bad_request("当前登录已超过近期安全窗口，请重新登录后再操作")
        else:
            contact_type = "email" if method == "old_email_otp" else "phone"
            c_id = (challenge_id or "").strip()
            raw_code = (code or "").strip()
            if not c_id or not raw_code:
                raise bad_request("请填写二次验证挑战 ID 与验证码")

            cur.execute(
                """
                SELECT id, user_id, purpose, channel, destination_fingerprint, code_hash,
                       status, attempt_count, max_attempts, expires_at, send_state,
                       session_id, sub_purpose, target_fingerprint
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

            if row.get("sub_purpose") is not None and row["sub_purpose"] != purpose:
                raise BizError("TT_COMMON_40301", "二次验证挑战与当前操作用途不匹配", 403)
            if row.get("session_id") is not None and session_id and str(row["session_id"]) != str(session_id):
                raise BizError("TT_COMMON_40301", "二次验证挑战与当前登录会话不匹配", 403)
            if row.get("target_fingerprint") is not None:
                if not target_fp or not hmac.compare_digest(str(row["target_fingerprint"]), target_fp):
                    raise BizError("TT_COMMON_40301", "二次验证挑战绑定的目标邮箱不一致", 403)

            dest = _get_verified_contact_for_step_up(cur, user_id, contact_type)
            if not dest:
                raise bad_request("当前账号暂无可用的原安全联系方式")
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
        try:
            cur.execute("SAVEPOINT sp_issue_stepup_037")
            cur.execute(
                """
                INSERT INTO step_up_grant (
                    id, user_id, purpose, method, session_fingerprint, session_id, target_fingerprint,
                    grant_hash, status, expires_at
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s,
                    %s, 'active', NOW() + make_interval(secs => %s)
                )
                """,
                (grant_id, user_id, purpose, method, effective_fp, session_id, target_fp, grant_hash, ttl),
            )
            cur.execute("RELEASE SAVEPOINT sp_issue_stepup_037")
        except Exception:
            cur.execute("ROLLBACK TO SAVEPOINT sp_issue_stepup_037")
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
                (grant_id, user_id, purpose, method, effective_fp, target_fp, grant_hash, ttl),
            )
        audit_record(
            "user.step_up_verified",
            "step_up_grant",
            resource_id=grant_id,
            actor_user_id=user_id,
            request_id=request_id,
            details={"purpose": purpose, "method": method, "target_bound": bool(target_fp)},
            cur=cur,
        )

    return {
        "stepUpGrant": grant_token,
        "expiresIn": ttl,
        "method": method,
        "purpose": purpose,
    }


def _session_revoked_in_db(cur, user_id: int, sid: str) -> bool:
    """检查逻辑会话 sid 在服务端是否已被注销或过期；仅放行未注销的合法会话。"""
    try:
        cur.execute("SAVEPOINT sp_check_sid_037")
        cur.execute(
            """
            SELECT
                EXISTS(SELECT 1 FROM auth_session WHERE user_id=%s AND sid=%s) AS has_any,
                EXISTS(
                    SELECT 1 FROM auth_session
                    WHERE user_id=%s AND sid=%s AND status='active'
                      AND (expires_at IS NULL OR expires_at > NOW())
                ) AS has_active
            """,
            (user_id, sid, user_id, sid),
        )
        row = cur.fetchone()
        cur.execute("RELEASE SAVEPOINT sp_check_sid_037")
        if isinstance(row, dict) and row.get("has_any") and not row.get("has_active"):
            return True
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_check_sid_037")
    return False


def validate_step_up_grant(
    cur,
    *,
    user_id: int,
    grant_token: str | None,
    purpose: str,
    session_fingerprint: str = "",
    session_ctx: SessionAuthContext | None = None,
    target_contact: str | None = None,
    consume: bool = False,
) -> dict[str, Any]:
    """严格校验证件：用户、目的、逻辑会话、目标地址均强制绑定；`consume=True` 原子核销。"""
    policy = get_security_operation_policy(purpose)
    token = (grant_token or "").strip()
    if not token:
        msg = (
            "更换已绑定安全邮箱前须先完成二次身份认证"
            if purpose == "rebind_email"
            else "绑定安全邮箱前须先完成安全身份授权"
        )
        raise BizError("TT_COMMON_40301", msg, 403)

    effective_fp, session_id, _ = _resolve_session_binding(
        purpose=purpose,
        session_ctx=session_ctx,
        session_fingerprint=session_fingerprint,
    )
    if not effective_fp:
        raise BizError("TT_COMMON_40102", "当前会话无效，请重新登录", 401)

    grant_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    try:
        cur.execute("SAVEPOINT sp_sel_grant_037")
        cur.execute(
            """
            SELECT id, user_id, purpose, method, session_fingerprint, session_id,
                   target_fingerprint, status, expires_at
            FROM step_up_grant
            WHERE grant_hash = %s FOR UPDATE
            """,
            (grant_hash,),
        )
        row = cur.fetchone()
        cur.execute("RELEASE SAVEPOINT sp_sel_grant_037")
    except Exception:
        cur.execute("ROLLBACK TO SAVEPOINT sp_sel_grant_037")
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
    if not hmac.compare_digest(str(row["session_fingerprint"]), effective_fp):
        raise BizError("TT_COMMON_40301", "二次身份认证凭证与当前登录会话不匹配", 403)

    row_sid = row.get("session_id")
    if row_sid is not None:
        if session_id is None or str(row_sid) != str(session_id):
            raise BizError("TT_COMMON_40301", "二次身份认证凭证与当前登录会话不匹配", 403)
        if _session_revoked_in_db(cur, user_id, str(row_sid)):
            cur.execute("UPDATE step_up_grant SET status='revoked' WHERE id=%s", (row["id"],))
            raise BizError("TT_COMMON_40301", "当前会话已注销，二次认证凭证已失效", 403)

    if policy.requires_target_binding:
        stored_target_fp = row.get("target_fingerprint")
        expected_fp = _target_fingerprint(target_contact, purpose=purpose)
        if not stored_target_fp or not expected_fp:
            raise BizError("TT_COMMON_40301", "二次身份认证凭证缺少目标邮箱绑定，请重新验证", 403)
        if not hmac.compare_digest(str(stored_target_fp), expected_fp):
            raise BizError("TT_COMMON_40301", "二次身份认证凭证绑定的目标邮箱不一致", 403)

    if consume:
        cur.execute(
            "UPDATE step_up_grant SET status='consumed', consumed_at=NOW() WHERE id=%s",
            (row["id"],),
        )
    return dict(row)
