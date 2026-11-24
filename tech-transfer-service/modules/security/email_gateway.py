"""Email Security Gateway 核心编排层（共享交付、风控、资格与队列基础设施）。

职责：
1. 邮件渠道请求风控门禁 (`email_request_gate`)；
2. 邮箱密码找回 (`start_email_recovery`：统一资格检查、防枚举、结构化回执)；
3. 安全邮箱首次绑定与换绑 (`start_email_binding`：Step-up 二次认证校验、发送失败立即闭环)；
4. 行锁串行化 + 事务外投递 + 未知状态保守不重发 + 结构化诊断与低基数指标。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import secrets
import time
import uuid
from urllib.parse import quote

from config import settings, validate_frontend_reset_base_url
from core.contact_validation import normalize_email
from core.errors import TT_COMMON_40903, BizError, bad_request
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.security.delivery_models import (
    DeliveryReceipt,
    DeliveryStageError,
    DeliveryTaskResult,
    ProviderError,
    metrics,
    risk_reason,
)
from modules.security.eligibility import EMAIL_ELIGIBLE_SQL, email_eligibility_reason
from modules.security.provider import get_email_provider
from modules.security.sms_gateway import SendContext, normalize_phone, recovery_response
from modules.security.state_machine import assert_send_state_transition

logger = logging.getLogger("nanshan.security.email_gateway")


def _engine():
    from modules.security.email_risk import get_email_risk_engine

    return get_email_risk_engine()


def _allowed(decision) -> bool:
    value = getattr(decision, "action", getattr(decision, "decision", decision))
    return getattr(value, "value", value) == "ALLOW"


def _audit(rule: str, context: SendContext, challenge_id=None, **details):
    from modules.security.service import _fingerprint

    audit_record(
        "email.gateway",
        "auth_challenge",
        resource_id=challenge_id,
        request_id=context.request_id,
        details={"rule_id": rule, "ip_digest": _fingerprint("ip:" + context.ip), **details},
    )


def email_request_gate(
    context: SendContext,
    account: str,
    *,
    email: str | None = None,
    purpose: str = "password_recovery",
    engine=None,
) -> None:
    """邮件发送前统一风控门禁（IP/账号/设备/不同邮箱数/非公共域名流量）。"""
    eng = engine or _engine()
    norm_email: str | None = None
    if email:
        try:
            norm_email = normalize_email(email)
        except BizError:
            norm_email = email.strip().lower()
    decision = eng.check_request(context.ip, account, context.device_id, email=norm_email, purpose=purpose)
    rule_id = getattr(decision, "rule_id", "email.request")
    _audit(
        rule_id,
        context,
        decision=str(getattr(decision, "action", decision)),
        risk_level=getattr(decision, "risk_level", "high"),
        risk_score=getattr(decision, "risk_score", 100),
        purpose=purpose,
    )
    if not _allowed(decision):
        metrics.inc("email_risk_blocked_total", channel="email", purpose=purpose, rule_id=rule_id)
        if "redis" in rule_id:
            raise BizError("TT_COMMON_50301", "安全验证服务暂时不可用，请稍后重试", 503)
        retry_after = max(1, int(getattr(decision, "retry_after", 60) or 60))
        raise BizError(
            "TT_COMMON_42901",
            "操作过于频繁或需要额外安全验证，请稍后重试",
            429,
            details={"retryAfter": retry_after},
        )


def start_email_recovery(
    account: str,
    channel: str,
    challenge_id: str,
    context: SendContext,
    engine=None,
    *,
    return_result: bool = False,
):
    """通过安全邮件网关发起找回密码（email_otp / email_link）。"""
    eng = engine or _engine()
    ch = (channel or "").strip().lower()
    if ch not in {"email_otp", "email_link"}:
        raise bad_request("不支持的邮件找回渠道")

    lookup = (account or "").strip()
    if not lookup:
        if return_result:
            return DeliveryTaskResult(
                challenge_id,
                "INELIGIBLE",
                "eligibility",
                "invalid_account_format",
                channel=ch,
                purpose="password_recovery",
            )
        return recovery_response(challenge_id, ch)

    if "@" in lookup:
        try:
            lookup = normalize_email(lookup)
        except BizError:
            _ = hashlib.pbkdf2_hmac("sha256", lookup.encode("utf-8"), b"salt_dummy", 1000)
            if return_result:
                return DeliveryTaskResult(
                    challenge_id,
                    "INELIGIBLE",
                    "eligibility",
                    "invalid_account_format",
                    channel=ch,
                    purpose="password_recovery",
                )
            return recovery_response(challenge_id, ch)
    elif lookup.startswith("+86") or re.fullmatch(r"[0-9 -]+", lookup):
        try:
            lookup = normalize_phone(lookup)
        except BizError:
            _ = hashlib.pbkdf2_hmac("sha256", lookup.encode("utf-8"), b"salt_dummy", 1000)
            if return_result:
                return DeliveryTaskResult(
                    challenge_id,
                    "INELIGIBLE",
                    "eligibility",
                    "invalid_account_format",
                    channel=ch,
                    purpose="password_recovery",
                )
            return recovery_response(challenge_id, ch)

    try:
        with get_cursor() as cur:
            cur.execute(EMAIL_ELIGIBLE_SQL, (lookup, lookup, lookup))
            rows = cur.fetchall()
    except Exception:
        raise DeliveryStageError("eligibility", "database_unavailable") from None

    if len(rows) != 1:
        _audit("recovery.ineligible", context, challenge_id, decision="DENY", channel=ch)
        try:
            ineligible_reason = (
                "contact_conflict" if len(rows) > 1 else email_eligibility_reason(lookup, cursor_factory=get_cursor)
            )
        except Exception:
            ineligible_reason = "diagnosis_failed"
        logger.info(
            "找回密码请求未派发邮件：账号不符合确权资格 (reason=%s, channel=%s, challenge_id=%s)",
            ineligible_reason,
            ch,
            challenge_id,
        )
        _ = hashlib.pbkdf2_hmac("sha256", lookup.encode("utf-8"), b"salt_dummy", 1000)
        if return_result:
            return DeliveryTaskResult(
                challenge_id,
                "INELIGIBLE",
                "eligibility",
                ineligible_reason if ineligible_reason != "eligible" else "eligibility_changed",
                channel=ch,
                purpose="password_recovery",
            )
        return recovery_response(challenge_id, ch)

    target = rows[0]
    target_email = normalize_email(target["normalized_value"])
    receipt = _send_email(
        target["user_id"],
        target_email,
        "password_recovery",
        ch,
        challenge_id,
        context,
        eng,
    )
    if return_result:
        return DeliveryTaskResult(
            challenge_id,
            "COMPLETED",
            provider_ids=receipt.provider_message_ids,
            provider_called=True,
            challenge_id=challenge_id,
            channel=ch,
            purpose="password_recovery",
            provider=receipt.provider,
        )
    return recovery_response(challenge_id, ch)


def start_email_binding(
    user_id: int,
    email: str,
    context: SendContext,
    *,
    step_up_grant: str | None = None,
    session_fingerprint: str | None = None,
    engine=None,
) -> dict:
    """发起安全邮箱绑定或换绑挑战（已存在已确权邮箱时必须先完成二次认证）。"""
    if not settings.EMAIL_ENABLED:
        raise DeliveryStageError("config", "CHANNEL_DISABLED")
    norm_email = normalize_email(email)
    eng = engine or _engine()
    challenge_id = str(uuid.uuid4())
    is_rebind = False

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' AND deleted_at IS NULL", (user_id,))
        if not cur.fetchone():
            raise bad_request("账号不可用")

        cur.execute(
            """SELECT user_id FROM account_contact WHERE contact_type='email'
            AND normalized_value=%s AND status='active' AND verified_at IS NOT NULL AND user_id<>%s""",
            (norm_email, user_id),
        )
        if cur.fetchone():
            raise BizError(TT_COMMON_40903[0], "该邮箱已被其他账号绑定", 409)

        cur.execute(
            """SELECT normalized_value FROM account_contact WHERE user_id=%s AND contact_type='email'
            AND status='active' AND verified_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1""",
            (user_id,),
        )
        existing = cur.fetchone()
        if existing:
            is_rebind = True
            if existing["normalized_value"] == norm_email:
                raise bad_request("新邮箱与当前已绑定安全邮箱相同")
            from modules.security.step_up import validate_step_up_grant

            validate_step_up_grant(
                cur,
                user_id=user_id,
                grant_token=step_up_grant,
                purpose="rebind_email",
                session_fingerprint=session_fingerprint or "",
                target_contact=norm_email,
                consume=False,
            )

    _send_email(
        user_id,
        norm_email,
        "bind_email",
        "email_otp",
        challenge_id,
        context,
        eng,
        template_purpose="rebind_email" if is_rebind else "bind_email",
    )
    from modules.security.service import _mask_contact

    return {
        "challengeId": challenge_id,
        "maskedDestination": _mask_contact(norm_email, "email"),
        "isRebind": is_rebind,
        "message": "验证码发送请求已受理",
    }


def _send_email(
    user_id: int,
    email: str,
    purpose: str,
    channel: str,
    challenge_id: str,
    context: SendContext,
    engine=None,
    *,
    template_purpose: str | None = None,
) -> DeliveryReceipt:
    from modules.security.service import _fingerprint, _hmac_code_v2, _mask_contact

    if not settings.EMAIL_ENABLED:
        metrics.inc("email_request_total", channel=channel, purpose=purpose, reason="CHANNEL_DISABLED")
        raise DeliveryStageError("config", "CHANNEL_DISABLED")

    try:
        provider = get_email_provider()
    except ProviderError as exc:
        reason = getattr(exc, "reason_code", "CONFIG_ERROR")
        metrics.inc("email_request_total", channel=channel, purpose=purpose, reason=reason)
        raise DeliveryStageError("config", reason) from None

    eng = engine or _engine()
    ttl = settings.EMAIL_LINK_TTL_SECONDS if channel == "email_link" else settings.EMAIL_CODE_TTL_SECONDS
    decision = eng.reserve(email, str(user_id), context.ip, context.device_id, challenge_id, ttl_seconds=ttl)
    if not _allowed(decision):
        rule = getattr(decision, "rule_id", "email.risk.blocked")
        _audit(rule, context, challenge_id, decision="THROTTLE", purpose=purpose, channel=channel)
        metrics.inc("email_risk_blocked_total", channel=channel, purpose=purpose, rule_id=rule)
        raise DeliveryStageError(
            "risk",
            risk_reason(rule),
            risk_rule_id=rule,
            retry_after=getattr(decision, "retry_after", 60),
        )

    code = secrets.token_urlsafe(32) if channel == "email_link" else f"{secrets.randbelow(1_000_000):06d}"
    masked = _mask_contact(email, "email")
    fp = _fingerprint(email)
    code_hash = _hmac_code_v2(challenge_id, purpose, channel, email, code)

    try:
        with get_cursor(commit=True) as cur:
            # 行锁串行化同用户同用途挑战，确保不存在多个激活挑战；事务在调用外部 SMTP/SES 前立即结束。
            cur.execute("SELECT id FROM app_user WHERE id=%s FOR UPDATE", (user_id,))
            cur.execute(
                """UPDATE auth_challenge SET status='cancelled' WHERE user_id=%s
                AND purpose=%s AND status IN ('pending','pending_send')""",
                (user_id, purpose),
            )
            cur.execute(
                """INSERT INTO auth_challenge
                (id,user_id,purpose,channel,destination_fingerprint,destination_masked,code_hash,
                 status,attempt_count,max_attempts,expires_at,send_request_id,send_state,
                 code_hash_version,provider_name)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'pending_send',0,%s,
                        NOW()+make_interval(secs=>%s),%s,'reserved',2,%s)""",
                (
                    challenge_id,
                    user_id,
                    purpose,
                    channel,
                    fp,
                    masked,
                    code_hash,
                    settings.EMAIL_CODE_MAX_ATTEMPTS,
                    ttl,
                    challenge_id,
                    provider.provider_name,
                ),
            )
            audit_record(
                "email.reserved",
                "auth_challenge",
                resource_id=challenge_id,
                request_id=context.request_id,
                details={"decision": "ALLOW", "rule_id": "email.reserved", "channel": channel, "purpose": purpose},
                cur=cur,
            )
    except Exception:
        eng.transition(challenge_id, "rejected")
        raise DeliveryStageError("challenge_create", "CHALLENGE_CREATE_FAILED") from None

    metrics.inc("email_request_total", channel=channel, purpose=purpose, provider=provider.provider_name)
    start_ms = time.monotonic()
    try:
        if channel == "email_link":
            try:
                frontend_base = validate_frontend_reset_base_url(
                    settings.FRONTEND_URL,
                    production_like=settings.is_production_like,
                )
            except ValueError:
                raise ProviderError("重置页面域名配置无效", reason_code="CONFIG_ERROR") from None
            reset_url = f"{frontend_base}/reset-password#challengeId={quote(challenge_id, safe='')}&token={quote(code, safe='')}"
            receipt = provider.send_reset_link_task(email, reset_url, ttl, send_request_id=challenge_id)
        else:
            receipt = provider.send_code_task(
                email,
                code,
                template_purpose or purpose,
                ttl,
                send_request_id=challenge_id,
            )
        if not receipt.accepted:
            raise ProviderError("邮件服务商未接受请求", reason_code="SMTP_PERMANENT_FAILURE", request_attempted=True)
    except Exception as exc:
        elapsed_ms = (time.monotonic() - start_ms) * 1000.0
        metrics.observe_latency(elapsed_ms, channel=channel, purpose=purpose, provider=provider.provider_name)
        unknown = not isinstance(exc, ProviderError) or getattr(exc, "outcome_unknown", False)
        state = "unknown" if unknown else "rejected"
        reason = getattr(exc, "reason_code", "PROVIDER_OUTCOME_UNKNOWN" if unknown else "unexpected_provider_error")
        if unknown:
            metrics.inc(
                "email_provider_unknown_total",
                channel=channel,
                purpose=purpose,
                provider=provider.provider_name,
                reason=reason,
            )
        else:
            metrics.inc(
                "email_provider_rejected_total",
                channel=channel,
                purpose=purpose,
                provider=provider.provider_name,
                reason=reason,
            )
        eng.transition(challenge_id, state)
        try:
            _set_email_send_state(
                challenge_id,
                state,
                [],
                context,
                provider_name=provider.provider_name,
                provider_status=getattr(exc, "provider_status", None),
                failure_reason=reason,
            )
        except Exception:
            raise DeliveryStageError(
                "receipt_persist",
                "RECEIPT_PERSIST_FAILED",
                outcome_unknown=True,
                provider_called=getattr(exc, "request_attempted", True),
                provider_status=getattr(exc, "provider_status", None),
                provider_name=provider.provider_name,
            ) from None
        if isinstance(exc, ProviderError):
            raise DeliveryStageError(
                "provider",
                reason,
                outcome_unknown=unknown,
                provider_called=getattr(exc, "request_attempted", unknown),
                provider_status=getattr(exc, "provider_status", None),
                retryable=getattr(exc, "retryable", False),
                provider_name=provider.provider_name,
            ) from None
        raise DeliveryStageError(
            "provider",
            "PROVIDER_OUTCOME_UNKNOWN",
            outcome_unknown=True,
            provider_called=True,
            provider_name=provider.provider_name,
        ) from None

    elapsed_ms = (time.monotonic() - start_ms) * 1000.0
    metrics.observe_latency(elapsed_ms, channel=channel, purpose=purpose, provider=receipt.provider)
    try:
        _set_email_send_state(
            challenge_id,
            "accepted",
            list(receipt.provider_message_ids),
            context,
            provider_name=receipt.provider,
        )
    except Exception:
        raise DeliveryStageError(
            "receipt_persist",
            "RECEIPT_PERSIST_FAILED",
            provider_ids=receipt.provider_message_ids,
            provider_called=True,
            outcome_unknown=True,
            provider_name=receipt.provider,
        ) from None
    eng.transition(challenge_id, "accepted")
    metrics.inc("email_provider_accepted_total", channel=channel, purpose=purpose, provider=receipt.provider)
    return receipt


def _set_email_send_state(
    challenge_id: str,
    state: str,
    provider_ids: list[str],
    context: SendContext,
    *,
    provider_name: str | None = None,
    provider_status: int | None = None,
    failure_reason: str | None = None,
) -> None:
    assert_send_state_transition("reserved", state)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE auth_challenge SET send_state=%s, provider_message_ids=%s::jsonb,
            provider_name=COALESCE(%s, provider_name),
            delivery_status_code=COALESCE(%s, delivery_status_code),
            delivery_failure_reason=%s,
            status=CASE WHEN status='pending_send' THEN
                CASE WHEN %s IN ('accepted','unknown') THEN 'pending' ELSE 'failed' END ELSE status END
            WHERE id=%s""",
            (
                state,
                json.dumps(provider_ids),
                provider_name,
                provider_status,
                failure_reason[:64] if failure_reason else None,
                state,
                challenge_id,
            ),
        )
        audit_record(
            "email." + state,
            "auth_challenge",
            resource_id=challenge_id,
            request_id=context.request_id,
            details={"send_state": state, "provider": provider_name, "reason_code": failure_reason},
            cur=cur,
        )


def reconcile_email_delivery(challenge_id: str) -> dict | None:
    """内部运维核对邮件投递状态；不支持状态查询的 Provider（如 SMTP/Mock）显式返回 unsupported_capability。"""
    with get_cursor() as cur:
        cur.execute(
            """SELECT provider_message_ids, send_state, provider_name, created_at
            FROM auth_challenge WHERE id=%s AND channel IN ('email_otp','email_link')""",
            (challenge_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    if row["send_state"] in {"delivered", "bounced", "delivery_failed", "rejected"}:
        return {"state": row["send_state"], "provider": row.get("provider_name")}

    provider = get_email_provider()
    if not provider.capabilities.delivery_status_query:
        return {
            "state": row["send_state"],
            "provider": provider.provider_name,
            "supported": False,
            "reason_code": "unsupported_capability",
        }

    ids = row["provider_message_ids"] or []
    if not ids:
        return {"state": "unknown", "requires_manual_review": True}

    created_at = row.get("created_at")
    req_date = created_at.strftime("%Y-%m-%d") if hasattr(created_at, "strftime") else None
    result = provider.query_status(list(ids), request_date=req_date)
    records = result.get("records") or []
    if not records:
        return {"state": row["send_state"], "provider": provider.provider_name, "records": 0}

    # SES SendStatus: 0=发送成功, 1=发送中, 2=收件人拒收/退信, 3=发送失败等
    latest = records[0] if isinstance(records[0], dict) else {}
    send_status = latest.get("SendStatus")
    new_state = row["send_state"]
    if send_status == 0:
        new_state = "delivered"
    elif send_status in {2, 3, 4}:
        new_state = "bounced" if send_status == 2 else "delivery_failed"

    if new_state not in {"delivered", "bounced", "delivery_failed"}:
        return {"state": row["send_state"], "provider": provider.provider_name, "ses_send_status": send_status}

    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE auth_challenge SET send_state=%s,
            delivery_status_code=%s,
            delivery_reason_code=%s,
            status=CASE WHEN %s IN ('bounced','delivery_failed') AND status='pending' THEN 'failed' ELSE status END
            WHERE id=%s AND send_state IN ('accepted','unknown')""",
            (
                new_state,
                int(send_status) if isinstance(send_status, int) else None,
                str(latest.get("DeliverMessage") or "")[:32] or None,
                new_state,
                challenge_id,
            ),
        )
        if cur.rowcount:
            audit_record(
                "email." + new_state,
                "auth_challenge",
                resource_id=challenge_id,
                details={"ses_send_status": send_status},
                cur=cur,
            )
            cur.execute(
                """UPDATE security_delivery_request SET failure_stage=%s, failure_reason=%s,
                outcome=%s WHERE id=%s AND provider_called=true""",
                (
                    "delivery" if new_state in {"bounced", "delivery_failed"} else None,
                    f"ses_{new_state}" if new_state in {"bounced", "delivery_failed"} else None,
                    "DELIVERY_FAILED" if new_state in {"bounced", "delivery_failed"} else "COMPLETED",
                    challenge_id,
                ),
            )
    if new_state == "delivered":
        _engine().transition(challenge_id, "delivered")
    return {"state": new_state, "provider": provider.provider_name}
