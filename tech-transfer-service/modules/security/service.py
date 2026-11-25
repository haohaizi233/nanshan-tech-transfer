"""统一账号安全与密码找回核心服务。

实现：
1. 账号找回挑战发起（start_password_recovery：统一路由至 sms_gateway / email_gateway）
2. 挑战验证与 Recovery Grant 签发（verify_recovery_challenge：统一公开错误语义防枚举、全局锁顺序、HMAC v1/v2 兼容）
3. 密码重置单事务执行与会话即时失效（complete_password_recovery：锁外哈希 + 全局锁顺序 + 死锁有界重试）
4. 安全中心资料、能力探测与已确权联系方式绑定/换绑（get_security_summary, start_contact_binding_challenge, verify_and_bind_contact）
5. 退出全部其他设备会话（revoke_all_user_sessions）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg2

from config import settings
from core import auth_cache
from core.contact_validation import normalize_email, validate_phone
from core.errors import (
    TT_AUTH_40106,
    TT_AUTH_RECOVERY_INVALID,
    TT_COMMON_40903,
    BizError,
    bad_request,
)
from core.password import hash_password
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.security.delivery_models import metrics
from modules.security.provider import get_email_provider
from modules.security.state_machine import can_verify_challenge
from modules.security.step_up import SessionAuthContext, get_available_step_up_methods

logger = logging.getLogger("nanshan.security.service")

RECOVERY_GRANT_EXPIRES_SECONDS = 300
CHALLENGE_EXPIRES_SECONDS = 300
MAX_CHALLENGE_ATTEMPTS = 5


def _expired(value: Any) -> bool:
    return (value.timestamp() if isinstance(value, datetime) else float(value)) <= time.time()


def _is_retryable_db_concurrency_error(exc: BaseException) -> bool:
    pgcode = getattr(exc, "pgcode", None)
    if pgcode in {"40P01", "40001"}:
        return True
    err_mod = getattr(psycopg2, "errors", None)
    if err_mod is not None:
        for name in ("DeadlockDetected", "SerializationFailure"):
            cls = getattr(err_mod, name, None)
            if cls is not None and isinstance(exc, cls):
                return True
    return False


def _run_with_deadlock_retry(fn, *, max_attempts: int = 3):
    """对纯数据库安全事务在发生 40P01/40001 并发冲突时执行有界重试（事务已完整回滚）。"""
    attempts = max(1, int(max_attempts))
    for attempt in range(attempts):
        try:
            return fn()
        except psycopg2.Error as exc:
            if not _is_retryable_db_concurrency_error(exc) or attempt + 1 >= attempts:
                raise
            time.sleep(0.01 * (attempt + 1))
    return None


@contextmanager
def _challenge_transaction():
    """仅在尚未发生业务写操作时允许提交失败次数/过期/锁定状态后再抛 BizError；
    一旦进入业务写阶段，任何异常（含 BizError）均立即触发完整事务回滚。
    """
    tx_state = {"business_writes_started": False}
    failure = None
    with get_cursor(commit=True) as cur:
        try:
            yield cur, tx_state
        except BizError as exc:
            if tx_state["business_writes_started"]:
                raise
            failure = exc
    if failure is not None:
        raise failure


def _otp_secret() -> bytes:
    raw = settings.SECURITY_OTP_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _contact_secret() -> bytes:
    raw = settings.SECURITY_CONTACT_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def _legacy_fingerprint(contact: str) -> str:
    norm = contact.strip().lower()
    return hmac.new(settings.JWT_SECRET.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def _fingerprint(contact: str) -> str:
    """生成联系方式的不可逆检索盲索引（HMAC-SHA256，支持独立密钥隔离）。"""
    norm = contact.strip().lower()
    return hmac.new(_contact_secret(), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def _hmac_code(challenge_id: str, purpose: str, destination: str, code: str) -> str:
    """v1 验证码安全摘要（保留向后兼容存量未过期挑战）。"""
    raw = f"{challenge_id}:{purpose}:{destination.strip().lower()}:{code.strip()}"
    return hmac.new(_otp_secret(), raw.encode("utf-8"), hashlib.sha256).hexdigest()


def _hmac_code_v2(challenge_id: str, purpose: str, channel: str, destination: str, code: str) -> str:
    """v2 无歧义规范化上下文绑定 HMAC-SHA256 摘要。"""
    canonical = json.dumps(
        [
            "v2",
            str(challenge_id),
            str(purpose),
            str(channel),
            destination.strip().lower(),
            code.strip(),
        ],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return "v2$" + hmac.new(_otp_secret(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()


def _verify_destination_fingerprint(row: dict, destination: str) -> bool:
    stored = str(row.get("destination_fingerprint") or "")
    if hmac.compare_digest(_fingerprint(destination), stored):
        return True
    # 密钥轮换兼容窗口：允许未过期存量记录匹配旧 JWT_SECRET 盲索引
    return hmac.compare_digest(_legacy_fingerprint(destination), stored)


def _verify_challenge_code_match(row: dict, destination: str, raw_code: str) -> bool:
    stored = str(row.get("code_hash") or "")
    c_id = str(row["id"])
    purpose = str(row["purpose"])
    channel = str(row.get("channel") or "")
    if stored.startswith("v2$"):
        expected_v2 = _hmac_code_v2(c_id, purpose, channel, destination, raw_code)
        return hmac.compare_digest(expected_v2, stored)
    expected_v1 = _hmac_code(c_id, purpose, destination, raw_code)
    if hmac.compare_digest(expected_v1, stored):
        return True
    if settings.SECURITY_OTP_HMAC_SECRET:
        legacy_raw = f"{c_id}:{purpose}:{destination.strip().lower()}:{raw_code.strip()}"
        legacy_v1 = hmac.new(
            settings.JWT_SECRET.encode("utf-8"), legacy_raw.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(legacy_v1, stored)
    return False


def _mask_contact(value: str, contact_type: str) -> str:
    """联系方式脱敏显示。"""
    v = value.strip()
    if contact_type == "phone":
        if len(v) == 11:
            return f"{v[:3]}****{v[7:]}"
        return f"{v[:2]}****{v[-2:]}" if len(v) > 4 else "****"
    if contact_type == "email":
        parts = v.split("@")
        if len(parts) == 2:
            name, domain = parts
            masked_name = name[0] + "***" if len(name) > 1 else name + "***"
            return f"{masked_name}@{domain}"
    return "****"


def get_recovery_capabilities() -> dict[str, Any]:
    """公开查询当前系统启用的密码找回通道能力（仅布尔开关与倒计时配置，无敏感凭证）。"""
    return {
        "sms": bool(settings.SMS_ENABLED),
        "emailOtp": bool(settings.EMAIL_ENABLED),
        "emailLink": bool(settings.EMAIL_ENABLED),
        "codeTtlSeconds": settings.EMAIL_CODE_TTL_SECONDS,
        "cooldownSeconds": settings.EMAIL_COOLDOWN_SECONDS,
    }


def start_password_recovery(
    account: str, channel: str, *, challenge_id: str | None = None, context=None
) -> dict[str, Any]:
    """发起找回密码流程（统一委托给 sms_gateway 与 email_gateway）。"""
    account_norm = (account or "").strip()
    if not account_norm:
        raise bad_request("请输入用户名、手机号或邮箱")

    ch = channel.lower().strip()
    if ch not in {"sms", "email_otp", "email_link"}:
        raise bad_request("不支持的找回渠道，仅支持 sms / email_otp / email_link")

    from modules.security.sms_gateway import SendContext

    ctx = context or SendContext("internal", None, str(uuid.uuid4()))
    cid = challenge_id or str(uuid.uuid4())
    if ch == "sms":
        from modules.security.sms_gateway import start_sms_recovery

        return dict(start_sms_recovery(account_norm, cid, ctx))

    from modules.security.email_gateway import start_email_recovery

    return dict(start_email_recovery(account_norm, ch, cid, ctx))


def _record_recovery_verify_failure(reason: str, challenge_id: str) -> None:
    logger.info(
        "匿名找回核验未通过 (internal_reason=%s, challenge_digest=%s)",
        reason,
        _fingerprint("cid:" + challenge_id)[:16],
    )
    metrics.inc("recovery_verify_failed_total", reason=reason)


def _fail_recovery_verify(reason: str, challenge_id: str, raw_code: str = "", *, dummy_compute: bool = False) -> None:
    if dummy_compute:
        # 温和等价计算以缓解是否存在 Challenge 的轻度时序偏差（严禁无界耗时防 DoS）
        _ = _hmac_code_v2(challenge_id, "password_recovery", "email_otp", "dummy@invalid.local", raw_code or "000000")
    _record_recovery_verify_failure(reason, challenge_id)
    raise BizError(*TT_AUTH_RECOVERY_INVALID)


def _lookup_challenge_owner_non_locking(challenge_id: str) -> tuple[bool, int | None]:
    """非锁定前置查找 challenge 所属 user_id（不作为最终授权依据）。"""
    try:
        with get_cursor() as cur:
            cur.execute("SELECT user_id FROM auth_challenge WHERE id = %s", (challenge_id,))
            row = cur.fetchone()
    except Exception as exc:
        err_name = type(exc).__name__
        if err_name in {"DataError", "InvalidTextRepresentation"}:
            return False, None
        raise
    if not row:
        return False, None
    uid = row.get("user_id") if isinstance(row, dict) else None
    return True, (int(uid) if uid is not None else None)


def verify_recovery_challenge(challenge_id: str, code: str) -> dict[str, Any]:
    """原子核验找回挑战凭据，签发短期单次 Recovery Grant（防枚举统一响应 + 全局锁顺序）。"""
    c_id = (challenge_id or "").strip()
    raw_code = (code or "").strip()
    if not c_id or not raw_code:
        _fail_recovery_verify("INVALID_PARAMS", c_id or "empty", raw_code)

    def _attempt() -> dict[str, Any]:
        exists, owner_user_id = _lookup_challenge_owner_non_locking(c_id)
        if not exists:
            _fail_recovery_verify("CHALLENGE_NOT_FOUND", c_id, raw_code, dummy_compute=True)

        verified_channel = ""
        with _challenge_transaction() as (cur, tx):
            # 统一锁顺序：app_user -> auth_challenge -> account_contact -> recovery_grant
            if owner_user_id is not None:
                cur.execute(
                    "SELECT id FROM app_user WHERE id = %s FOR UPDATE",
                    (owner_user_id,),
                )
            cur.execute(
                """
                SELECT id, user_id, purpose, channel, destination_fingerprint, code_hash,
                       status, attempt_count, max_attempts, expires_at, send_state
                FROM auth_challenge
                WHERE id = %s FOR UPDATE
                """,
                (c_id,),
            )
            row = cur.fetchone()
            if not row:
                _fail_recovery_verify("CHALLENGE_NOT_FOUND", c_id, raw_code, dummy_compute=True)

            if row["purpose"] != "password_recovery":
                _fail_recovery_verify("PURPOSE_MISMATCH", c_id, raw_code, dummy_compute=True)

            cur_status = str(row["status"])
            cur_send_state = row.get("send_state")
            if cur_status == "expired":
                _fail_recovery_verify("CHALLENGE_EXPIRED", c_id, raw_code, dummy_compute=True)
            if cur_status == "locked":
                _fail_recovery_verify("CHALLENGE_LOCKED", c_id, raw_code, dummy_compute=True)
            if cur_status == "consumed":
                _fail_recovery_verify("CHALLENGE_CONSUMED", c_id, raw_code, dummy_compute=True)
            if cur_status == "cancelled":
                _fail_recovery_verify("CHALLENGE_CANCELLED", c_id, raw_code, dummy_compute=True)
            if cur_status == "failed" or cur_send_state in {"rejected", "delivery_failed", "bounced"}:
                _fail_recovery_verify("DELIVERY_REJECTED", c_id, raw_code, dummy_compute=True)
            if not can_verify_challenge(cur_status, cur_send_state):
                _fail_recovery_verify("CHALLENGE_UNVERIFIABLE", c_id, raw_code, dummy_compute=True)

            if _expired(row["expires_at"]):
                cur.execute("UPDATE auth_challenge SET status = 'expired' WHERE id = %s", (c_id,))
                _fail_recovery_verify("CHALLENGE_EXPIRED", c_id, raw_code, dummy_compute=True)

            if row["attempt_count"] >= row["max_attempts"]:
                cur.execute("UPDATE auth_challenge SET status = 'locked' WHERE id = %s", (c_id,))
                _fail_recovery_verify("CHALLENGE_LOCKED", c_id, raw_code, dummy_compute=True)

            user_id = row["user_id"]
            contact_type = "phone" if row["channel"] == "sms" else "email"
            cur.execute(
                """
                SELECT normalized_value FROM account_contact
                WHERE user_id = %s AND contact_type = %s AND status = 'active'
                  AND verified_at IS NOT NULL
                  AND (contact_type <> 'phone' OR verification_method IN ('sms','wechat','manual'))
                  AND (contact_type <> 'email' OR verification_method IN ('email','manual'))
                  AND EXISTS (SELECT 1 FROM app_user au JOIN user_credential uc ON uc.user_id=au.id
                      WHERE au.id=account_contact.user_id AND au.status='active' AND au.deleted_at IS NULL
                      AND uc.status='active' AND uc.password_configured=true AND uc.password_hash IS NOT NULL)
                  AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id=account_contact.user_id
                      AND ur.role_code IN ('admin','platform_admin','org_admin'))
                  AND NOT EXISTS (SELECT 1 FROM organization_membership om
                      WHERE om.user_id=account_contact.user_id AND om.role='admin' AND om.status='active')
                LIMIT 1
                """,
                (user_id, contact_type),
            )
            contact_row = cur.fetchone()
            if not contact_row:
                cur.execute("UPDATE auth_challenge SET status = 'failed' WHERE id = %s", (c_id,))
                _fail_recovery_verify("ACCOUNT_INELIGIBLE", c_id, raw_code, dummy_compute=True)

            destination = contact_row["normalized_value"]
            if not _verify_destination_fingerprint(row, destination):
                _fail_recovery_verify("CONTACT_CHANGED", c_id, raw_code, dummy_compute=True)

            if not _verify_challenge_code_match(row, destination, raw_code):
                cur.execute(
                    """UPDATE auth_challenge SET attempt_count = attempt_count + 1,
                       status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE status END
                       WHERE id = %s""",
                    (c_id,),
                )
                _fail_recovery_verify("CODE_MISMATCH", c_id, raw_code)

            # 验证通过后进入业务写入阶段：后续任何异常均应完整回滚
            tx["business_writes_started"] = True
            verified_channel = str(row["channel"])

            cur.execute("UPDATE auth_challenge SET status = 'verified' WHERE id = %s", (c_id,))

            grant_token = secrets.token_urlsafe(32)
            grant_hash = hashlib.sha256(grant_token.encode("utf-8")).hexdigest()
            grant_id = str(uuid.uuid4())

            cur.execute(
                """
                UPDATE recovery_grant SET status = 'revoked'
                WHERE user_id = %s AND status = 'active'
                """,
                (user_id,),
            )
            cur.execute(
                """
                INSERT INTO recovery_grant (
                    id, user_id, challenge_id, grant_hash, status, expires_at
                ) VALUES (
                    %s, %s, %s, %s, 'active', NOW() + make_interval(secs => %s)
                )
                """,
                (grant_id, user_id, c_id, grant_hash, RECOVERY_GRANT_EXPIRES_SECONDS),
            )

        if verified_channel in {"email_otp", "email_link"}:
            metrics.inc("email_challenge_verified_total", channel=verified_channel, purpose="password_recovery")

        return {
            "recoveryGrant": grant_token,
            "expiresIn": RECOVERY_GRANT_EXPIRES_SECONDS,
        }

    return dict(_run_with_deadlock_retry(_attempt))


def _send_security_notification_best_effort(email: str, event_type: str) -> None:
    if not settings.EMAIL_SECURITY_NOTIFICATION_ENABLED or not settings.EMAIL_ENABLED:
        return
    try:
        provider = get_email_provider()
        occurred_at = datetime.now(UTC).astimezone().strftime("%Y-%m-%d %H:%M:%S %z")
        provider.send_notification_task(
            email,
            event_type,
            occurred_at,
            send_request_id=f"notify-{uuid.uuid4().hex}",
        )
    except Exception as exc:
        logger.warning("发送安全变更通知邮件失败（已忽略，不影响主业务）: %s", type(exc).__name__)


def _lookup_recovery_grant_owner_non_locking(grant_hash: str) -> tuple[int, str | None] | None:
    with get_cursor() as cur:
        cur.execute(
            "SELECT user_id, challenge_id FROM recovery_grant WHERE grant_hash = %s",
            (grant_hash,),
        )
        row = cur.fetchone()
    if not row:
        return None
    cid = row.get("challenge_id") if isinstance(row, dict) else None
    return int(row["user_id"]), (str(cid) if cid is not None else None)


def complete_password_recovery(grant_token: str, new_password: str) -> dict[str, Any]:
    """完成密码重置（锁外哈希 + 全局锁顺序 app_user->user_credential->auth_challenge->recovery_grant->step_up_grant->auth_session）。"""
    token = (grant_token or "").strip()
    pwd = new_password or ""
    if not token:
        raise bad_request("缺少重置授权凭证")
    if len(pwd) < 8 or len(pwd) > 128:
        raise bad_request("新密码长度须为 8-128 位")

    grant_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    # 耗时密码哈希移出数据库行锁事务临界区，事务内再重新验证凭证状态与 Grant
    precomputed_hash = hash_password(pwd)

    def _attempt() -> tuple[int, str | None]:
        owner = _lookup_recovery_grant_owner_non_locking(grant_hash)
        if owner is None:
            raise bad_request("重置授权凭证无效或已被使用")
        user_id, challenge_id = owner
        notify_email: str | None = None

        with get_cursor(commit=True) as cur:
            # 1. 全局锁顺序第一环：锁定 app_user 并检查账号资格
            cur.execute(
                """
                SELECT au.status AS user_status
                FROM app_user au
                WHERE au.id = %s AND au.deleted_at IS NULL
                  AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id=au.id
                      AND ur.role_code IN ('admin','platform_admin','org_admin'))
                  AND NOT EXISTS (SELECT 1 FROM organization_membership om
                      WHERE om.user_id=au.id AND om.role='admin' AND om.status='active')
                FOR UPDATE OF au
                """,
                (user_id,),
            )
            au_row = cur.fetchone()
            if not au_row or au_row["user_status"] != "active":
                raise BizError(*TT_AUTH_40106)

            # 2. 锁定 user_credential
            cur.execute(
                """
                SELECT status AS cred_status, password_configured, password_hash
                FROM user_credential
                WHERE user_id = %s AND password_configured = true AND password_hash IS NOT NULL
                FOR UPDATE
                """,
                (user_id,),
            )
            cred_row = cur.fetchone()
            if not cred_row or cred_row["cred_status"] != "active":
                raise BizError(*TT_AUTH_40106)

            # 3. 锁定关联 auth_challenge
            if challenge_id:
                cur.execute(
                    "SELECT id, status FROM auth_challenge WHERE id = %s AND user_id = %s FOR UPDATE",
                    (challenge_id, user_id),
                )
                cur.fetchone()

            # 4. 锁后重新验证 recovery_grant（防 TOCTOU 与并发重放）
            cur.execute(
                """
                SELECT id, user_id, challenge_id, status, expires_at
                FROM recovery_grant
                WHERE grant_hash = %s FOR UPDATE
                """,
                (grant_hash,),
            )
            grant = cur.fetchone()
            if (
                not grant
                or int(grant["user_id"]) != user_id
                or grant["status"] != "active"
                or _expired(grant["expires_at"])
            ):
                raise bad_request("重置授权凭证无效或已被使用")

            # 5. 更新密码哈希并消费 Grant 与关联 Challenge
            cur.execute(
                """
                UPDATE user_credential
                SET password_hash = %s, password_configured = true
                WHERE user_id = %s
                """,
                (precomputed_hash, user_id),
            )
            if grant.get("challenge_id"):
                cur.execute(
                    "UPDATE auth_challenge SET status = 'consumed', consumed_at = NOW() WHERE id = %s",
                    (grant["challenge_id"],),
                )
            cur.execute(
                """
                UPDATE recovery_grant
                SET status = 'consumed', consumed_at = NOW()
                WHERE id = %s
                """,
                (grant["id"],),
            )

            # 6. 吊销活跃 Step-up Grant 与活跃会话，并递增 session_version
            try:
                cur.execute("SAVEPOINT sp_revoke_stepup_on_reset")
                cur.execute(
                    "UPDATE step_up_grant SET status = 'revoked' WHERE user_id = %s AND status = 'active'",
                    (user_id,),
                )
                cur.execute("RELEASE SAVEPOINT sp_revoke_stepup_on_reset")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_revoke_stepup_on_reset")

            cur.execute(
                """
                UPDATE auth_session
                SET status = 'revoked', revoked_at = NOW()
                WHERE user_id = %s AND status = 'active'
                """,
                (user_id,),
            )
            cur.execute(
                """
                UPDATE app_user
                SET session_version = session_version + 1
                WHERE id = %s
                """,
                (user_id,),
            )

            if settings.EMAIL_SECURITY_NOTIFICATION_ENABLED and settings.EMAIL_ENABLED:
                cur.execute(
                    """SELECT normalized_value FROM account_contact
                    WHERE user_id=%s AND contact_type='email' AND status='active'
                    AND verified_at IS NOT NULL AND verification_method IN ('email','manual')
                    LIMIT 1""",
                    (user_id,),
                )
                email_row = cur.fetchone()
                if email_row:
                    notify_email = email_row["normalized_value"]

            audit_record(
                "user.password_recovery",
                "user_credential",
                resource_id=user_id,
                actor_user_id=user_id,
                cur=cur,
            )

        return user_id, notify_email

    user_id, notify_email = _run_with_deadlock_retry(_attempt)
    auth_cache.invalidate_user(user_id)
    if notify_email:
        _send_security_notification_best_effort(notify_email, "password_reset")
    return {"ok": True, "message": "密码重置成功，请重新登录"}


# ── 安全中心与联系方式确权 ──────────────────────────────────────


def get_security_summary(
    user_id: int,
    *,
    auth_time: int | None = None,
    has_sid: bool | None = None,
    token_iat: int | None = None,
) -> dict[str, Any]:
    """获取当前登录用户的安全配置概览（stepUpMethods 仅依据可信 auth_time 与角色/密码策略判定）。"""
    del token_iat  # 严禁用 Refresh 可推进的 token iat 充当可信 auth_time
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT uc.username, uc.password_configured,
                   EXISTS(SELECT 1 FROM external_identity ei WHERE ei.user_id = %s
                          AND ei.issuer = 'wechat-mini' AND ei.unlinked_at IS NULL) AS wechat_bound
            FROM user_credential uc
            WHERE uc.user_id = %s
            """,
            (user_id, user_id),
        )
        cred = cur.fetchone() or {}

        cur.execute(
            """
            SELECT contact_type, normalized_value, verified_at, updated_at
            FROM account_contact
            WHERE user_id = %s AND status = 'active'
            ORDER BY contact_type
            """,
            (user_id,),
        )
        contacts = cur.fetchall()

        phone_info = None
        email_info = None
        for c in contacts:
            masked = _mask_contact(c["normalized_value"], c["contact_type"])
            is_verified = c["verified_at"] is not None
            if c["contact_type"] == "phone":
                phone_info = {
                    "value": masked,
                    "verified": is_verified,
                    "verifiedAt": c["verified_at"].isoformat() if c["verified_at"] else None,
                }
            elif c["contact_type"] == "email":
                email_info = {
                    "value": masked,
                    "verified": is_verified,
                    "verifiedAt": c["verified_at"].isoformat() if c["verified_at"] else None,
                }

        cur.execute(
            """
            SELECT action, resource_type, created_at
            FROM audit_log
            WHERE actor_user_id = %s
            ORDER BY id DESC LIMIT 5
            """,
            (user_id,),
        )
        logs = [
            {
                "action": row["action"],
                "resourceType": row["resource_type"],
                "createdAt": row["created_at"].isoformat() if row["created_at"] else None,
            }
            for row in (cur.fetchall() or [])
        ]

    password_configured = cred.get("password_configured", True)
    step_up_methods = get_available_step_up_methods(
        user_id,
        auth_time=auth_time,
        has_sid=has_sid,
    )

    return {
        "passwordConfigured": password_configured,
        "wechatBound": cred.get("wechat_bound", False),
        "phone": phone_info,
        "email": email_info,
        "recentLogs": logs,
        "capabilities": {
            "smsEnabled": bool(settings.SMS_ENABLED),
            "emailEnabled": bool(settings.EMAIL_ENABLED),
        },
        "stepUpMethods": step_up_methods,
    }


def start_contact_binding_challenge(
    user_id: int,
    contact_type: str,
    contact_value: str,
    *,
    context=None,
    step_up_grant: str | None = None,
    session_fingerprint: str | None = None,
    session_ctx: SessionAuthContext | None = None,
) -> dict[str, Any]:
    """发起安全手机号/邮箱绑定挑战（委托给 sms_gateway / email_gateway，消除孤儿 pending 挑战）。"""
    ct = contact_type.lower().strip()
    if ct not in {"phone", "email"}:
        raise bad_request("联系方式类型仅支持 phone 或 email")

    from modules.security.sms_gateway import SendContext

    ctx = context or SendContext("internal", None, str(uuid.uuid4()))
    if ct == "phone":
        from modules.security.sms_gateway import start_sms_binding

        return dict(start_sms_binding(user_id, contact_value, ctx))

    from modules.security.email_gateway import start_email_binding

    return dict(
        start_email_binding(
            user_id,
            contact_value,
            ctx,
            step_up_grant=step_up_grant,
            session_fingerprint=session_fingerprint,
            session_ctx=session_ctx,
        )
    )


def verify_and_bind_contact(
    user_id: int,
    challenge_id: str,
    code: str,
    contact_value: str,
    *,
    step_up_grant: str | None = None,
    session_fingerprint: str | None = None,
    session_ctx: SessionAuthContext | None = None,
) -> dict[str, Any]:
    """验证挑战并原子绑定/换绑安全联系方式（首次绑定与换绑安全邮箱均强制核销强绑定 Step-up Grant）。"""
    c_id = (challenge_id or "").strip()
    raw_code = (code or "").strip()
    val = (contact_value or "").strip()
    if not c_id or not raw_code or not val:
        raise bad_request("参数不完整")

    def _attempt() -> tuple[str | None, bool, str]:
        old_email_to_notify: str | None = None
        is_rebind = False
        contact_type = "email"

        with _challenge_transaction() as (cur, tx):
            # 全局规范锁顺序：app_user -> auth_challenge -> account_contact -> recovery_grant -> step_up_grant
            cur.execute(
                "SELECT id FROM app_user WHERE id = %s AND status = 'active' AND deleted_at IS NULL FOR UPDATE",
                (user_id,),
            )
            if not cur.fetchone():
                raise bad_request("账号不可用")

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
            if not row or not can_verify_challenge(row["status"], row.get("send_state")):
                raise bad_request("挑战不存在或已失效")

            contact_type = "phone" if row["channel"] == "sms" else "email"
            if row["purpose"] != f"bind_{contact_type}":
                raise bad_request("挑战类型不匹配")
            if _expired(row["expires_at"]):
                cur.execute("UPDATE auth_challenge SET status = 'expired' WHERE id = %s", (c_id,))
                raise bad_request("验证码已过期")
            if row["attempt_count"] >= row["max_attempts"]:
                cur.execute("UPDATE auth_challenge SET status = 'locked' WHERE id = %s", (c_id,))
                raise bad_request("验证错误次数超限")

            normalized_val = str(
                validate_phone(val, required=True) if contact_type == "phone" else normalize_email(val)
            )

            if not _verify_destination_fingerprint(row, normalized_val):
                raise bad_request("联系方式与挑战不匹配")
            if not _verify_challenge_code_match(row, normalized_val, raw_code):
                cur.execute(
                    """UPDATE auth_challenge SET attempt_count = attempt_count + 1,
                    status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE status END
                    WHERE id = %s""",
                    (c_id,),
                )
                raise bad_request("验证码不正确")

            # 验证通过后进入业务写入阶段：后续任何异常均应完整回滚
            tx["business_writes_started"] = True

            cur.execute("UPDATE auth_challenge SET status = 'consumed', consumed_at = NOW() WHERE id = %s", (c_id,))
            if contact_type == "email":
                cur.execute(
                    """UPDATE auth_challenge SET status = 'cancelled'
                    WHERE user_id = %s AND purpose = 'password_recovery'
                      AND channel IN ('email_otp', 'email_link')
                      AND status IN ('pending_send', 'pending', 'verified')""",
                    (user_id,),
                )

            existing_email = None
            if contact_type == "email":
                cur.execute(
                    """
                    SELECT id, normalized_value FROM account_contact
                    WHERE user_id = %s AND contact_type = 'email' AND status = 'active'
                      AND verified_at IS NOT NULL
                    FOR UPDATE
                    """,
                    (user_id,),
                )
                existing_email = cur.fetchone()
                if existing_email:
                    is_rebind = True
                    old_email_to_notify = existing_email["normalized_value"]
                    if old_email_to_notify == normalized_val:
                        raise bad_request("新邮箱与当前已绑定安全邮箱相同")

            # 检查唯一性冲突（防并发抢绑同一联系方式）
            cur.execute(
                """
                SELECT user_id FROM account_contact
                WHERE contact_type = %s AND normalized_value = %s
                  AND status = 'active' AND verified_at IS NOT NULL AND user_id <> %s
                FOR UPDATE
                """,
                (contact_type, normalized_val, user_id),
            )
            if cur.fetchone():
                raise BizError(
                    TT_COMMON_40903[0],
                    f"该{'手机号' if contact_type == 'phone' else '邮箱'}已被其他账号绑定",
                    409,
                )

            if contact_type == "email":
                cur.execute(
                    "UPDATE recovery_grant SET status = 'revoked' WHERE user_id = %s AND status = 'active'",
                    (user_id,),
                )
                from modules.security.step_up import validate_step_up_grant

                actual_purpose = "rebind_email" if is_rebind else "bind_email"
                validate_step_up_grant(
                    cur,
                    user_id=user_id,
                    grant_token=step_up_grant,
                    purpose=actual_purpose,
                    session_fingerprint=session_fingerprint or "",
                    session_ctx=session_ctx,
                    target_contact=normalized_val,
                    consume=True,
                )

            cur.execute(
                """
                UPDATE account_contact
                SET status = 'revoked', revoked_at = NOW()
                WHERE user_id = %s AND contact_type = %s AND status = 'active'
                """,
                (user_id, contact_type),
            )

            try:
                cur.execute(
                    """
                    INSERT INTO account_contact (user_id, contact_type, normalized_value, verified_at, status, verification_method)
                    VALUES (%s, %s, %s, NOW(), 'active', %s)
                    """,
                    (user_id, contact_type, normalized_val, "sms" if contact_type == "phone" else "email"),
                )
            except psycopg2.IntegrityError:
                raise BizError(
                    TT_COMMON_40903[0],
                    f"该{'手机号' if contact_type == 'phone' else '邮箱'}已被其他账号绑定，请勿重复提交",
                    409,
                ) from None

            if contact_type == "phone":
                cur.execute(
                    "UPDATE user_credential SET phone = %s WHERE user_id = %s",
                    (normalized_val, user_id),
                )
            else:
                metrics.inc("email_challenge_verified_total", channel="email_otp", purpose="bind_email")

            audit_action = (
                "user.rebind_email" if (contact_type == "email" and is_rebind) else f"user.bind_{contact_type}"
            )
            audit_record(
                audit_action,
                "account_contact",
                resource_id=user_id,
                actor_user_id=user_id,
                details={"contact_type": contact_type, "rebind": is_rebind},
                cur=cur,
            )

        return old_email_to_notify, is_rebind, contact_type

    old_email_to_notify, is_rebind, contact_type = _run_with_deadlock_retry(_attempt)
    if old_email_to_notify and is_rebind:
        _send_security_notification_best_effort(old_email_to_notify, "email_rebound")

    return {"ok": True, "message": f"安全{'手机号' if contact_type == 'phone' else '邮箱'}绑定成功"}


def revoke_all_user_sessions(user_id: int) -> dict[str, Any]:
    """强制退出全部其他设备会话（锁 app_user -> step_up_grant -> auth_session，递增 session_version）。"""

    def _attempt() -> None:
        with get_cursor(commit=True) as cur:
            cur.execute("SELECT id FROM app_user WHERE id = %s FOR UPDATE", (user_id,))
            cur.execute("UPDATE app_user SET session_version = session_version + 1 WHERE id = %s", (user_id,))
            try:
                cur.execute("SAVEPOINT sp_revoke_stepup_all")
                cur.execute(
                    "UPDATE step_up_grant SET status = 'revoked' WHERE user_id = %s AND status = 'active'",
                    (user_id,),
                )
                cur.execute("RELEASE SAVEPOINT sp_revoke_stepup_all")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_revoke_stepup_all")
            cur.execute(
                "UPDATE auth_session SET status = 'revoked', revoked_at = NOW() WHERE user_id = %s AND status = 'active'",
                (user_id,),
            )
            auth_cache.invalidate_user(user_id)
            audit_record("user.revoke_all_sessions", "app_user", resource_id=user_id, actor_user_id=user_id, cur=cur)

    _run_with_deadlock_retry(_attempt)
    return {"ok": True, "message": "已成功强制登出全部会话，请重新登录"}
