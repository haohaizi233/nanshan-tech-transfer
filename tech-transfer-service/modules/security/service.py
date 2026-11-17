"""统一账号安全与密码找回核心服务。

实现：
1. 账号找回挑战发起（start_password_recovery）
2. 挑战验证与 Recovery Grant 签发（verify_recovery_challenge）
3. 密码重置单事务执行与会话即时失效（complete_password_recovery）
4. 安全中心资料与已确权联系方式管理（get_security_summary, bind_contact）
5. 退出全部其他设备会话（revoke_all_user_sessions）
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
import uuid
from contextlib import contextmanager
from datetime import datetime

from config import settings
from core import auth_cache
from core.contact_validation import validate_email, validate_phone
from core.errors import (
    TT_AUTH_40106,
    TT_COMMON_40903,
    BizError,
    bad_request,
)
from core.password import hash_password
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.security.provider import get_email_provider, get_sms_provider

logger = logging.getLogger("nanshan.security.service")

RECOVERY_GRANT_EXPIRES_SECONDS = 300
CHALLENGE_EXPIRES_SECONDS = 300
MAX_CHALLENGE_ATTEMPTS = 5


def _expired(value) -> bool:
    return (value.timestamp() if isinstance(value, datetime) else float(value)) <= time.time()


@contextmanager
def _challenge_transaction():
    """Persist failed attempt/expiry transitions before reporting a business error."""
    failure = None
    with get_cursor(commit=True) as cur:
        try:
            yield cur
        except BizError as exc:
            failure = exc
    if failure is not None:
        raise failure


def _fingerprint(contact: str) -> str:
    """生成联系方式的不可逆检索盲索引（HMAC-SHA256）。"""
    norm = contact.strip().lower()
    return hmac.new(settings.JWT_SECRET.encode("utf-8"), norm.encode("utf-8"), hashlib.sha256).hexdigest()


def _hmac_code(challenge_id: str, purpose: str, destination: str, code: str) -> str:
    """服务端密钥参与的验证码安全哈希，防离线暴力枚举与跨用途跨目标复用。"""
    raw = f"{challenge_id}:{purpose}:{destination.strip().lower()}:{code.strip()}"
    return hmac.new(settings.JWT_SECRET.encode("utf-8"), raw.encode("utf-8"), hashlib.sha256).hexdigest()


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


def start_password_recovery(account: str, channel: str, *, challenge_id: str | None = None, context=None) -> dict:
    """发起找回密码流程。

    防账号枚举设计：
    无论账号是否存在或是否有已确权联系方式，统一对外返回成功响应。
    当且仅当命中真实用户且具备已确权有效联系方式时，才真正派发验证码/邮件。
    """
    account_norm = (account or "").strip()
    if not account_norm:
        raise bad_request("请输入用户名、手机号或邮箱")

    channel = channel.lower().strip()
    if channel not in {"sms", "email_otp", "email_link"}:
        raise bad_request("不支持的找回渠道，仅支持 sms / email_otp / email_link")

    if channel == "sms":
        from modules.security.sms_gateway import SendContext, start_sms_recovery

        return start_sms_recovery(
            account_norm, challenge_id or str(uuid.uuid4()), context or SendContext("internal", None, str(uuid.uuid4()))
        )

    contact_type = "phone" if channel == "sms" else "email"

    target_user_id = None
    target_contact = None

    with get_cursor() as cur:
        # 1. 解析目标账号：支持按 username / phone / account_contact 查用户
        cur.execute(
            """
            SELECT au.id AS user_id, au.status AS user_status
            FROM app_user au
            LEFT JOIN user_credential uc ON uc.user_id = au.id
            WHERE au.deleted_at IS NULL AND (
                uc.username = %s OR uc.phone = %s OR EXISTS (
                    SELECT 1 FROM account_contact ac
                    WHERE ac.user_id = au.id AND ac.normalized_value = %s
                      AND ac.status = 'active' AND ac.verified_at IS NOT NULL
                )
            )
            LIMIT 1
            """,
            (account_norm, account_norm, account_norm.lower()),
        )
        row = cur.fetchone()
        if row and row.get("user_status") == "active":
            target_user_id = row["user_id"]

        # 2. 查询该用户对应渠道已确权联系方式
        if target_user_id:
            cur.execute(
                """
                SELECT normalized_value
                FROM account_contact
                WHERE user_id = %s AND contact_type = %s AND status = 'active'
                  AND verified_at IS NOT NULL
                ORDER BY updated_at DESC LIMIT 1
                """,
                (target_user_id, contact_type),
            )
            c_row = cur.fetchone()
            if c_row:
                target_contact = c_row["normalized_value"]

    # 3. 目标不存在或无确权联系方式时的防护处理（时间平抑 + 虚假响应）
    if not target_user_id or not target_contact:
        # 模拟哈希耗时，阻断时间侧信道分析
        _ = hashlib.pbkdf2_hmac("sha256", account_norm.encode(), b"salt_dummy", 1000)
        return {
            "challengeId": None,
            "channel": channel,
            "maskedDestination": None,
            "sent": True,
            "message": "若该账号已绑定有效联系方式，验证信息已发送",
        }

    # 4. 生成挑战凭证
    challenge_id = challenge_id or str(uuid.uuid4())
    masked = _mask_contact(target_contact, contact_type)
    fp = _fingerprint(target_contact)

    if channel in ("sms", "email_otp"):
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash = _hmac_code(challenge_id, "password_recovery", target_contact, code)
    else:
        # email_link: 256 位高熵随机 token
        code = secrets.token_urlsafe(32)
        code_hash = _hmac_code(challenge_id, "password_recovery", target_contact, code)

    # 5. 落库 auth_challenge
    with get_cursor(commit=True) as cur:
        # 失效该用户之前同用途未消费的旧挑战，防止多个有效验证码并存
        cur.execute(
            """
            UPDATE auth_challenge SET status = 'expired'
            WHERE user_id = %s AND purpose = 'password_recovery' AND status = 'pending'
            """,
            (target_user_id,),
        )
        cur.execute(
            """
            INSERT INTO auth_challenge (
                id, user_id, purpose, channel, destination_fingerprint, destination_masked,
                code_hash, status, attempt_count, max_attempts, expires_at
            ) VALUES (
                %s, %s, 'password_recovery', %s, %s, %s,
                %s, 'pending', 0, %s, NOW() + make_interval(secs => %s)
            )
            """,
            (
                challenge_id,
                target_user_id,
                channel,
                fp,
                masked,
                code_hash,
                MAX_CHALLENGE_ATTEMPTS,
                CHALLENGE_EXPIRES_SECONDS,
            ),
        )

    # 6. 调用 Provider 派发
    try:
        if channel == "sms":
            provider = get_sms_provider()
            provider.send_code(target_contact, code, "password_recovery", CHALLENGE_EXPIRES_SECONDS)
        elif channel == "email_otp":
            email_provider = get_email_provider()
            email_provider.send_code(target_contact, code, "password_recovery", CHALLENGE_EXPIRES_SECONDS)
        else:
            email_provider = get_email_provider()
            frontend_base = settings.FRONTEND_URL.rstrip("/")
            reset_url = f"{frontend_base}/reset-password?challengeId={challenge_id}&token={code}"
            email_provider.send_reset_link(target_contact, reset_url, CHALLENGE_EXPIRES_SECONDS)
    except Exception as e:
        logger.error("Provider 消息投递失败: %s", e)
        # 投递失败时立即将挑战置为 failed，防止产生无发送但可猜解的悬空挑战
        with get_cursor(commit=True) as cur:
            cur.execute("UPDATE auth_challenge SET status = 'failed' WHERE id = %s", (challenge_id,))
        raise

    return {
        "challengeId": challenge_id,
        "channel": channel,
        "maskedDestination": masked,
        "sent": True,
        "message": f"验证信息已发送至 {masked}",
    }


def verify_recovery_challenge(challenge_id: str, code: str) -> dict:
    """原子核验找回挑战凭据，签发短期单次 Recovery Grant。"""
    c_id = (challenge_id or "").strip()
    raw_code = (code or "").strip()
    if not c_id or not raw_code:
        raise bad_request("缺少 challengeId 或验证凭据")

    with _challenge_transaction() as cur:
        cur.execute(
            """
            SELECT id, user_id, purpose, channel, destination_fingerprint, code_hash,
                   status, attempt_count, max_attempts, expires_at
            FROM auth_challenge
            WHERE id = %s FOR UPDATE
            """,
            (c_id,),
        )
        row = cur.fetchone()
        if not row:
            raise bad_request("验证挑战不存在或已失效")

        if row["purpose"] != "password_recovery":
            raise bad_request("挑战类型不匹配")

        if row["status"] != "pending":
            raise bad_request("验证码已使用或已失效，请重新获取")

        if _expired(row["expires_at"]):
            cur.execute("UPDATE auth_challenge SET status = 'expired' WHERE id = %s", (c_id,))
            raise bad_request("验证码已过期，请重新获取")

        if row["attempt_count"] >= row["max_attempts"]:
            cur.execute("UPDATE auth_challenge SET status = 'failed' WHERE id = %s", (c_id,))
            raise bad_request("验证错误次数超限，请重新获取验证码")

        # 从 account_contact 查出目标联系方式重新计算 HMAC 比对
        user_id = row["user_id"]
        contact_type = "phone" if row["channel"] == "sms" else "email"
        cur.execute(
            """
            SELECT normalized_value FROM account_contact
            WHERE user_id = %s AND contact_type = %s AND status = 'active'
              AND verified_at IS NOT NULL
              AND (contact_type <> 'phone' OR verification_method IN ('sms','wechat','manual'))
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
            raise bad_request("安全联系方式已失效")

        destination = contact_row["normalized_value"]
        if not hmac.compare_digest(_fingerprint(destination), row["destination_fingerprint"]):
            raise bad_request("安全联系方式已变更")
        expected_hash = _hmac_code(c_id, "password_recovery", destination, raw_code)

        if not hmac.compare_digest(expected_hash, row["code_hash"]):
            cur.execute(
                """UPDATE auth_challenge SET attempt_count = attempt_count + 1,
                   status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE status END
                   WHERE id = %s""",
                (c_id,),
            )
            remaining = row["max_attempts"] - (row["attempt_count"] + 1)
            raise bad_request(f"验证码不正确，还可尝试 {max(0, remaining)} 次")

        # 验证通过：更新 challenge 状态
        cur.execute("UPDATE auth_challenge SET status = 'verified' WHERE id = %s", (c_id,))

        # 签发 Recovery Grant
        grant_token = secrets.token_urlsafe(32)
        grant_hash = hashlib.sha256(grant_token.encode("utf-8")).hexdigest()
        grant_id = str(uuid.uuid4())

        # 废弃该用户之前有效但未消费的 grant
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

    return {
        "recoveryGrant": grant_token,
        "expiresIn": RECOVERY_GRANT_EXPIRES_SECONDS,
    }


def complete_password_recovery(grant_token: str, new_password: str) -> dict:
    """完成密码重置（单个原子事务）：核销 Grant、更新密码、递增 session_version、吊销旧会话。"""
    token = (grant_token or "").strip()
    pwd = new_password or ""
    if not token:
        raise bad_request("缺少重置授权凭证")
    if len(pwd) < 8 or len(pwd) > 128:
        raise bad_request("新密码长度须为 8-128 位")

    grant_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()

    with get_cursor(commit=True) as cur:
        # 1. 原子锁定并消费 recovery_grant
        cur.execute(
            """
            SELECT id, user_id, status, expires_at
            FROM recovery_grant
            WHERE grant_hash = %s FOR UPDATE
            """,
            (grant_hash,),
        )
        grant = cur.fetchone()
        if not grant or grant["status"] != "active" or _expired(grant["expires_at"]):
            raise bad_request("重置授权凭证无效或已被使用")

        user_id = grant["user_id"]

        # 2. 检查用户与凭证状态
        cur.execute(
            """
            SELECT au.status AS user_status, uc.status AS cred_status, uc.password_hash
            FROM app_user au
            JOIN user_credential uc ON uc.user_id = au.id
            WHERE au.id = %s AND au.deleted_at IS NULL
              AND uc.password_configured=true AND uc.password_hash IS NOT NULL
              AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id=au.id
                  AND ur.role_code IN ('admin','platform_admin','org_admin'))
              AND NOT EXISTS (SELECT 1 FROM organization_membership om
                  WHERE om.user_id=au.id AND om.role='admin' AND om.status='active')
            FOR UPDATE
            """,
            (user_id,),
        )
        account = cur.fetchone()
        if not account or account["user_status"] != "active" or account["cred_status"] != "active":
            raise BizError(*TT_AUTH_40106)

        # 3. 更新密码哈希
        new_hash = hash_password(pwd)
        cur.execute(
            """
            UPDATE user_credential
            SET password_hash = %s, password_configured = true
            WHERE user_id = %s
            """,
            (new_hash, user_id),
        )

        # 4. 消费 Grant
        cur.execute(
            """
            UPDATE recovery_grant
            SET status = 'consumed', consumed_at = NOW()
            WHERE id = %s
            """,
            (grant["id"],),
        )
        cur.execute(
            "UPDATE auth_challenge SET status = 'consumed', consumed_at = NOW() "
            "WHERE id = (SELECT challenge_id FROM recovery_grant WHERE id = %s)",
            (grant["id"],),
        )

        # 5. 递增用户全局 session_version，使已有全部 Access Token 即刻失效
        cur.execute(
            """
            UPDATE app_user
            SET session_version = session_version + 1
            WHERE id = %s
            """,
            (user_id,),
        )

        # 6. 吊销所有活跃 Refresh Token 记录
        cur.execute(
            """
            UPDATE auth_session
            SET status = 'revoked', revoked_at = NOW()
            WHERE user_id = %s AND status = 'active'
            """,
            (user_id,),
        )

        # 7. 立即清理缓存

        # 8. 审计记录
        audit_record(
            "user.password_recovery",
            "user_credential",
            resource_id=user_id,
            actor_user_id=user_id,
            cur=cur,
        )

    auth_cache.invalidate_user(user_id)
    return {"ok": True, "message": "密码重置成功，请重新登录"}


# ── 安全中心与联系方式确权 ──────────────────────────────────────


def get_security_summary(user_id: int) -> dict:
    """获取当前登录用户的安全配置概览。"""
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

        # 确权联系方式
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

        # 最近安全审计日志
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

    return {
        "passwordConfigured": cred.get("password_configured", True),
        "wechatBound": cred.get("wechat_bound", False),
        "phone": phone_info,
        "email": email_info,
        "recentLogs": logs,
    }


def start_contact_binding_challenge(user_id: int, contact_type: str, contact_value: str, *, context=None) -> dict:
    """发起安全手机号/邮箱绑定挑战（发送验证码）。"""
    contact_type = contact_type.lower().strip()
    if contact_type not in {"phone", "email"}:
        raise bad_request("联系方式类型仅支持 phone 或 email")

    if contact_type == "phone":
        from modules.security.sms_gateway import SendContext, start_sms_binding

        return start_sms_binding(user_id, contact_value, context or SendContext("internal", None, str(uuid.uuid4())))

    if contact_type == "phone":
        valid_val = validate_phone(contact_value, required=True)
    else:
        valid_val = validate_email(contact_value, required=True).lower()

    # 查重：有效联系方式不能同时归属其他有效用户
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT user_id FROM account_contact
            WHERE contact_type = %s AND normalized_value = %s
              AND status = 'active' AND verified_at IS NOT NULL
              AND user_id <> %s
            """,
            (contact_type, valid_val, user_id),
        )
        if cur.fetchone():
            raise BizError(
                TT_COMMON_40903[0], f"该{'手机号' if contact_type == 'phone' else '邮箱'}已被其他账号绑定", 409
            )

    challenge_id = str(uuid.uuid4())
    masked = _mask_contact(valid_val, contact_type)
    fp = _fingerprint(valid_val)
    purpose = f"bind_{contact_type}"
    channel = "sms" if contact_type == "phone" else "email_otp"
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = _hmac_code(challenge_id, purpose, valid_val, code)

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO auth_challenge (
                id, user_id, purpose, channel, destination_fingerprint, destination_masked,
                code_hash, status, attempt_count, max_attempts, expires_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s,
                %s, 'pending', 0, %s, NOW() + make_interval(secs => %s)
            )
            """,
            (challenge_id, user_id, purpose, channel, fp, masked, code_hash, 5, 300),
        )

    # 派发验证码
    if contact_type == "phone":
        get_sms_provider().send_code(valid_val, code, purpose, 300)
    else:
        get_email_provider().send_code(valid_val, code, purpose, 300)

    return {
        "challengeId": challenge_id,
        "maskedDestination": masked,
        "message": f"验证码已发送至 {masked}",
    }


def verify_and_bind_contact(user_id: int, challenge_id: str, code: str, contact_value: str) -> dict:
    """验证挑战并原子绑定安全联系方式。"""
    c_id = (challenge_id or "").strip()
    raw_code = (code or "").strip()
    val = (contact_value or "").strip()
    if not c_id or not raw_code or not val:
        raise bad_request("参数不完整")

    with _challenge_transaction() as cur:
        cur.execute(
            """
            SELECT id, user_id, purpose, channel, destination_fingerprint, code_hash,
                   status, attempt_count, max_attempts, expires_at
            FROM auth_challenge
            WHERE id = %s AND user_id = %s FOR UPDATE
            """,
            (c_id, user_id),
        )
        row = cur.fetchone()
        if not row or row["status"] != "pending":
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
        normalized_val = (
            validate_phone(val, required=True)
            if contact_type == "phone"
            else validate_email(val, required=True).lower()
        )

        expected_hash = _hmac_code(c_id, row["purpose"], normalized_val, raw_code)
        if not hmac.compare_digest(_fingerprint(normalized_val), row["destination_fingerprint"]):
            raise bad_request("联系方式与挑战不匹配")
        if not hmac.compare_digest(expected_hash, row["code_hash"]):
            cur.execute(
                """UPDATE auth_challenge SET attempt_count = attempt_count + 1,
                status = CASE WHEN attempt_count + 1 >= max_attempts THEN 'locked' ELSE status END
                WHERE id = %s""",
                (c_id,),
            )
            raise bad_request("验证码不正确")

        # 挑战置为 verified
        cur.execute("UPDATE auth_challenge SET status = 'consumed', consumed_at = NOW() WHERE id = %s", (c_id,))

        # 绑定联系方式：先撤销旧同类型联系方式
        cur.execute(
            """
            UPDATE account_contact
            SET status = 'revoked', revoked_at = NOW()
            WHERE user_id = %s AND contact_type = %s AND status = 'active'
            """,
            (user_id, contact_type),
        )

        cur.execute(
            """
            INSERT INTO account_contact (user_id, contact_type, normalized_value, verified_at, status, verification_method)
            VALUES (%s, %s, %s, NOW(), 'active', %s)
            """,
            (user_id, contact_type, normalized_val, "sms" if contact_type == "phone" else "email"),
        )

        # 同步更新 user_credential.phone（若为手机号）以支持小程序直接手机号登录
        if contact_type == "phone":
            cur.execute(
                "UPDATE user_credential SET phone = %s WHERE user_id = %s",
                (normalized_val, user_id),
            )

        audit_record(
            f"user.bind_{contact_type}",
            "account_contact",
            resource_id=user_id,
            actor_user_id=user_id,
            cur=cur,
        )

    return {"ok": True, "message": f"安全{'手机号' if contact_type == 'phone' else '邮箱'}绑定成功"}


def revoke_all_user_sessions(user_id: int) -> dict:
    """强制退出全部其他设备会话（递增 session_version + 吊销所有活跃 refresh token）。"""
    with get_cursor(commit=True) as cur:
        cur.execute("UPDATE app_user SET session_version = session_version + 1 WHERE id = %s", (user_id,))
        cur.execute(
            "UPDATE auth_session SET status = 'revoked', revoked_at = NOW() WHERE user_id = %s AND status = 'active'",
            (user_id,),
        )
        auth_cache.invalidate_user(user_id)
        audit_record("user.revoke_all_sessions", "app_user", resource_id=user_id, actor_user_id=user_id, cur=cur)

    return {"ok": True, "message": "已成功强制登出全部会话，请重新登录"}
