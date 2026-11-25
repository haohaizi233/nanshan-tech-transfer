"""Email Security Gateway 核心编排层（共享交付、风控、资格与队列基础设施）。

职责：
1. 邮件渠道请求风控门禁 (`email_request_gate`)；
2. 邮箱密码找回 (`start_email_recovery`：统一资格检查、防枚举、结构化回执)；
3. 安全邮箱首次绑定与换绑 (`start_email_binding`：强制 Step-up 二次认证校验、发送失败立即闭环)；
4. 统一锁顺序 + 事务提交发送执行权门禁 (`claim_send_execution_right`) + 事务外投递 + CAS 回执核对（严格校验历史 Provider 身份）。
"""

from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
import uuid
from typing import Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

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
    transition_risk_checked,
)
from modules.security.eligibility import EMAIL_ELIGIBLE_SQL, email_eligibility_reason
from modules.security.idempotency import (
    IdempotencyClaim,
    advance_idempotency_stage,
    mark_http_idempotency_unknown,
)
from modules.security.provider import get_email_provider
from modules.security.sms_gateway import SendContext, normalize_phone, recovery_response
from modules.security.state_machine import (
    DeliveryTransitionResult,
    claim_send_execution_right,
    transition_delivery_state,
)
from modules.security.step_up import SessionAuthContext, validate_step_up_grant

logger = logging.getLogger("nanshan.security.email_gateway")
_SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _engine():
    from modules.security.email_risk import get_email_risk_engine

    return get_email_risk_engine()


def _allowed(decision: Any) -> bool:
    value = getattr(decision, "action", getattr(decision, "decision", decision))
    return str(getattr(value, "value", value)) == "ALLOW"


def _audit(rule: str, context: SendContext, challenge_id: str | None = None, **details: Any) -> None:
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
    engine: Any = None,
) -> None:
    """邮件发送前统一风控门禁（IP/账号/设备/不同邮箱数/非公共域名流量）。"""
    eng = engine or _engine()
    norm_email: str | None = None
    if email:
        try:
            norm_email = str(normalize_email(email))
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
    engine: Any = None,
    *,
    return_result: bool = False,
) -> Any:
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
            lookup = str(normalize_email(lookup))
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
    target_email = str(normalize_email(target["normalized_value"]))
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
    session_ctx: SessionAuthContext | None = None,
    engine: Any = None,
    idempotency_claim: IdempotencyClaim | None = None,
) -> dict[str, Any]:
    """发起安全邮箱绑定或换绑挑战（首次绑定与换绑均强制要求强绑定 Step-up Grant）。"""
    if not settings.EMAIL_ENABLED:
        raise DeliveryStageError("config", "CHANNEL_DISABLED")
    norm_email = str(normalize_email(email))
    eng = engine or _engine()
    challenge_id = str(uuid.uuid4())
    is_rebind = False

    with get_cursor(commit=True) as cur:
        # 锁顺序：app_user -> account_contact -> step_up_grant
        cur.execute(
            "SELECT id FROM app_user WHERE id=%s AND status='active' AND deleted_at IS NULL FOR UPDATE", (user_id,)
        )
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
            AND status='active' AND verified_at IS NOT NULL ORDER BY updated_at DESC LIMIT 1 FOR UPDATE""",
            (user_id,),
        )
        existing = cur.fetchone()
        if existing:
            is_rebind = True
            if existing["normalized_value"] == norm_email:
                raise bad_request("新邮箱与当前已绑定安全邮箱相同")

        actual_purpose = "rebind_email" if is_rebind else "bind_email"
        validate_step_up_grant(
            cur,
            user_id=user_id,
            grant_token=step_up_grant,
            purpose=actual_purpose,
            session_fingerprint=session_fingerprint or "",
            session_ctx=session_ctx,
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
        idempotency_claim=idempotency_claim,
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
    engine: Any = None,
    *,
    template_purpose: str | None = None,
    sub_purpose: str | None = None,
    session_id: str | None = None,
    session_version: int | None = None,
    target_fingerprint: str | None = None,
    source_contact_fingerprint: str | None = None,
    idempotency_claim: IdempotencyClaim | None = None,
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

    provider_config_id = getattr(provider, "provider_config_id", f"{provider.provider_name}:default")
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
            # 行锁串行化同用户同用途挑战；外部 SMTP/SES 呼叫在事务提交并取得发送执行权后执行。
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
                 code_hash_version,provider_name,provider_config_id,session_id,session_version,
                 sub_purpose,target_fingerprint,source_contact_fingerprint)
                VALUES (%s,%s,%s,%s,%s,%s,%s,'pending_send',0,%s,
                        NOW()+make_interval(secs=>%s),%s,'reserved',2,%s,%s,%s,%s,%s,%s,%s)""",
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
                    provider_config_id,
                    session_id,
                    session_version,
                    sub_purpose,
                    target_fingerprint,
                    source_contact_fingerprint,
                ),
            )
            audit_record(
                "email.reserved",
                "auth_challenge",
                resource_id=challenge_id,
                request_id=context.request_id,
                details={
                    "decision": "ALLOW",
                    "rule_id": "email.reserved",
                    "channel": channel,
                    "purpose": purpose,
                },
                cur=cur,
            )
    except Exception:
        transition_risk_checked(
            eng,
            challenge_id,
            "rejected",
            channel=channel,
            purpose=purpose,
            request_id=context.request_id,
            cursor_factory=get_cursor,
        )
        raise DeliveryStageError("challenge_create", "CHALLENGE_CREATE_FAILED") from None

    # 双重执行权门禁：必须在单事务提交中同时 CAS 推进幂等阶段与 Challenge 发送权，方允许调用外部 Provider
    send_owner = f"req:{context.request_id}:{uuid.uuid4().hex[:12]}"
    try:
        claim_res = claim_send_execution_right(
            challenge_id,
            send_owner=send_owner,
            expected_states=("reserved",),
            provider_name=provider.provider_name,
            provider_config_id=provider_config_id,
            cursor_factory=get_cursor,
            idempotency_claim=idempotency_claim,
        )
    except Exception:
        if idempotency_claim is not None:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "SEND_CLAIM_DB_ERROR",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
        raise DeliveryStageError(
            "send_claim",
            "SEND_CLAIM_DATABASE_ERROR",
            outcome_unknown=True,
            provider_called=False,
            provider_name=provider.provider_name,
        ) from None

    if claim_res.outcome != "transitioned":
        ambiguous = (
            claim_res.outcome
            in {
                "already_target",
                "owner_mismatch",
                "idempotency_owner_mismatch",
                "idempotency_conflict",
            }
            or (
                claim_res.outcome == "idempotency_stage_conflict"
                and claim_res.current_send_state not in (None, "pre_provider")
            )
            or claim_res.current_send_state
            in {
                "sending",
                "accepted",
                "delivered",
                "unknown",
                "send_claimed",
                "provider_called",
                "provider_accepted",
                "provider_unknown",
            }
        )
        if not ambiguous and claim_res.outcome in {"not_found", "expired", "conflict_or_disallowed"}:
            transition_risk_checked(
                eng,
                challenge_id,
                "rejected",
                channel=channel,
                purpose=purpose,
                request_id=context.request_id,
                cursor_factory=get_cursor,
            )
        if ambiguous and idempotency_claim is not None:
            mark_http_idempotency_unknown(
                idempotency_claim,
                f"SEND_CLAIM_{claim_res.outcome.upper()}",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
        raise DeliveryStageError(
            "send_claim",
            f"SEND_CLAIM_{claim_res.outcome.upper()}",
            outcome_unknown=ambiguous,
            provider_called=False,
            provider_name=provider.provider_name,
        )

    if idempotency_claim is not None and idempotency_claim.active:
        try:
            stage_ok = advance_idempotency_stage(
                idempotency_claim,
                ("send_claimed",),
                "provider_called",
                challenge_id=challenge_id,
                provider_called=True,
                cursor_factory=get_cursor,
            )
        except Exception:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "IDEMPOTENCY_STAGE_DB_ERROR",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
            raise DeliveryStageError(
                "send_claim",
                "IDEMPOTENCY_STAGE_DB_ERROR",
                outcome_unknown=True,
                provider_called=False,
                provider_name=provider.provider_name,
            ) from None
        if not stage_ok:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "IDEMPOTENCY_STAGE_CONFLICT",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
            raise DeliveryStageError(
                "send_claim",
                "IDEMPOTENCY_STAGE_CONFLICT",
                outcome_unknown=True,
                provider_called=False,
                provider_name=provider.provider_name,
            )

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
        try:
            _set_email_send_state(
                challenge_id,
                state,
                [],
                context,
                provider_name=provider.provider_name,
                provider_config_id=provider_config_id,
                provider_status=getattr(exc, "provider_status", None),
                failure_reason=reason,
                expected_owner=send_owner,
            )
        except Exception:
            transition_risk_checked(
                eng,
                challenge_id,
                state,
                channel=channel,
                purpose=purpose,
                request_id=context.request_id,
                cursor_factory=get_cursor,
            )
            if idempotency_claim is not None:
                mark_http_idempotency_unknown(
                    idempotency_claim,
                    "RECEIPT_PERSIST_FAILED",
                    challenge_id=challenge_id,
                    cursor_factory=get_cursor,
                )
            raise DeliveryStageError(
                "receipt_persist",
                "RECEIPT_PERSIST_FAILED",
                outcome_unknown=True,
                provider_called=getattr(exc, "request_attempted", True),
                provider_status=getattr(exc, "provider_status", None),
                provider_name=provider.provider_name,
            ) from None

        transition_risk_checked(
            eng,
            challenge_id,
            state,
            channel=channel,
            purpose=purpose,
            request_id=context.request_id,
            cursor_factory=get_cursor,
        )

        if idempotency_claim is not None and idempotency_claim.active:
            try:
                stage_ok = advance_idempotency_stage(
                    idempotency_claim,
                    ("provider_called", "send_claimed"),
                    "provider_unknown" if unknown else "provider_rejected",
                    challenge_id=challenge_id,
                    provider_called=True,
                    failure_reason=reason,
                    outcome_unknown=unknown,
                    cursor_factory=get_cursor,
                )
            except Exception:
                stage_ok = False
            if not stage_ok:
                mark_http_idempotency_unknown(
                    idempotency_claim,
                    "IDEMPOTENCY_RECEIPT_STAGE_CONFLICT",
                    challenge_id=challenge_id,
                    cursor_factory=get_cursor,
                )
                raise DeliveryStageError(
                    "receipt_persist",
                    "IDEMPOTENCY_RECEIPT_STAGE_CONFLICT",
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
    receipt_cfg_id = getattr(provider, "provider_config_id", provider_config_id)
    try:
        res = _set_email_send_state(
            challenge_id,
            "accepted",
            list(receipt.provider_message_ids),
            context,
            provider_name=receipt.provider,
            provider_config_id=receipt_cfg_id,
            expected_owner=send_owner,
        )
        if not res.updated and res.outcome != "already_target":
            raise DeliveryStageError(
                "receipt_persist",
                "RECEIPT_STATE_CONFLICT",
                provider_ids=receipt.provider_message_ids,
                provider_called=True,
                outcome_unknown=True,
                provider_name=receipt.provider,
            )
    except DeliveryStageError:
        if idempotency_claim is not None:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "RECEIPT_STATE_CONFLICT",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
        raise
    except Exception:
        if idempotency_claim is not None:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "RECEIPT_PERSIST_FAILED",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
        raise DeliveryStageError(
            "receipt_persist",
            "RECEIPT_PERSIST_FAILED",
            provider_ids=receipt.provider_message_ids,
            provider_called=True,
            outcome_unknown=True,
            provider_name=receipt.provider,
        ) from None

    if idempotency_claim is not None and idempotency_claim.active:
        try:
            stage_ok = advance_idempotency_stage(
                idempotency_claim,
                ("provider_called", "send_claimed"),
                "provider_accepted",
                challenge_id=challenge_id,
                provider_called=True,
                cursor_factory=get_cursor,
            )
        except Exception:
            stage_ok = False
        if not stage_ok:
            mark_http_idempotency_unknown(
                idempotency_claim,
                "IDEMPOTENCY_ACCEPTED_STAGE_CONFLICT",
                challenge_id=challenge_id,
                cursor_factory=get_cursor,
            )
            raise DeliveryStageError(
                "receipt_persist",
                "IDEMPOTENCY_ACCEPTED_STAGE_CONFLICT",
                provider_ids=receipt.provider_message_ids,
                provider_called=True,
                outcome_unknown=True,
                provider_name=receipt.provider,
            )
    transition_risk_checked(
        eng,
        challenge_id,
        "accepted",
        channel=channel,
        purpose=purpose,
        request_id=context.request_id,
        cursor_factory=get_cursor,
    )
    metrics.inc("email_provider_accepted_total", channel=channel, purpose=purpose, provider=receipt.provider)
    return receipt


def _set_email_send_state(
    challenge_id: str,
    state: str,
    provider_ids: list[str],
    context: SendContext,
    *,
    provider_name: str | None = None,
    provider_config_id: str | None = None,
    provider_status: int | None = None,
    failure_reason: str | None = None,
    expected_owner: str | None = None,
) -> DeliveryTransitionResult:
    with get_cursor(commit=True) as cur:
        res = transition_delivery_state(
            cur,
            challenge_id,
            ("reserved", "sending"),
            state,
            provider_ids=provider_ids,
            provider_name=provider_name,
            provider_config_id=provider_config_id,
            provider_status=provider_status,
            failure_reason=failure_reason,
            challenge_status_on_failure="failed",
            expected_owner=expected_owner,
        )
        if res.updated:
            audit_record(
                "email." + state,
                "auth_challenge",
                resource_id=challenge_id,
                request_id=context.request_id,
                details={"send_state": state, "provider": provider_name, "reason_code": failure_reason},
                cur=cur,
            )
        elif res.outcome != "already_target":
            metrics.inc(
                "delivery_cas_conflict_total",
                channel="email",
                purpose=state,
                reason=res.outcome,
            )
            logger.warning(
                "Email delivery state CAS conflict (challenge=%s target=%s outcome=%s current=%s)",
                challenge_id,
                state,
                res.outcome,
                res.current_send_state,
            )
    return res


def _match_ses_record(records: list[Any], target_ids: set[str]) -> dict[str, Any] | None:
    matched = [r for r in records if isinstance(r, dict) and str(r.get("MessageId") or "").strip() in target_ids]
    if not matched:
        return None
    if len(matched) == 1:
        return matched[0]
    return max(
        matched,
        key=lambda r: int(r["DeliverTime"]) if str(r.get("DeliverTime") or "").isdigit() else 0,
    )


def _map_ses_deliver_status(deliver_status: object) -> tuple[str | None, str]:
    """依腾讯云 SES GetSendEmailStatus (2020-10-02) 官方 DeliverStatus 枚举精确映射：
    0=请求成功进入发送队列, 1=递送成功, 2=被丢弃, 3=ESP 拒信退信, 8=延迟递送。
    绝不持久化原始 DeliverMessage 文本（防止邮箱/响应泄露）。
    """
    if deliver_status == 1:
        return "delivered", "ses_delivered"
    if deliver_status == 2:
        return "delivery_failed", "ses_dropped"
    if deliver_status == 3:
        return "bounced", "ses_esp_rejected"
    if deliver_status == 0:
        return None, "ses_in_queue"
    if deliver_status == 8:
        return None, "ses_delayed"
    return None, "unknown_provider_status"


def reconcile_email_delivery(challenge_id: str) -> dict[str, Any] | None:
    """内部运维核对邮件投递状态（严格校验历史 Provider 身份 + 官方 DeliverStatus + CAS 更新 + 脱敏）。"""
    with get_cursor() as cur:
        cur.execute(
            """SELECT provider_message_ids, send_state, provider_name, provider_config_id, created_at
            FROM auth_challenge WHERE id=%s AND channel IN ('email_otp','email_link')""",
            (challenge_id,),
        )
        row = cur.fetchone()
    if not row:
        return None
    if row["send_state"] in {"delivered", "bounced", "delivery_failed", "rejected"}:
        return {"state": row["send_state"], "provider": row.get("provider_name")}

    hist_provider = row.get("provider_name")
    hist_cfg_id = row.get("provider_config_id") if isinstance(row, dict) else None
    if not hist_provider:
        return {
            "state": row["send_state"],
            "supported": False,
            "reason_code": "provider_configuration_changed",
            "requires_manual_review": True,
        }

    try:
        provider = get_email_provider()
    except ProviderError:
        return {
            "state": row["send_state"],
            "historicalProvider": hist_provider,
            "supported": False,
            "reason_code": "provider_unavailable",
            "requires_manual_review": True,
        }

    if provider.provider_name != hist_provider:
        return {
            "state": row["send_state"],
            "historicalProvider": hist_provider,
            "activeProvider": provider.provider_name,
            "supported": False,
            "reason_code": "provider_configuration_changed",
            "requires_manual_review": True,
        }
    active_cfg_id = getattr(provider, "provider_config_id", None)
    if hist_cfg_id and active_cfg_id and active_cfg_id != hist_cfg_id:
        return {
            "state": row["send_state"],
            "historicalProvider": hist_provider,
            "supported": False,
            "reason_code": "provider_configuration_changed",
            "requires_manual_review": True,
        }

    if not provider.capabilities.delivery_status_query:
        return {
            "state": row["send_state"],
            "provider": provider.provider_name,
            "supported": False,
            "reason_code": "unsupported_capability",
        }

    ids = [str(x).strip() for x in (row["provider_message_ids"] or []) if str(x).strip()]
    if not ids:
        return {"state": "unknown", "requires_manual_review": True}

    created_at = row.get("created_at")
    if hasattr(created_at, "astimezone"):
        req_date = created_at.astimezone(_SHANGHAI_TZ).strftime("%Y-%m-%d")
    elif hasattr(created_at, "strftime"):
        req_date = created_at.strftime("%Y-%m-%d")
    else:
        req_date = None

    result = provider.query_status(ids, request_date=req_date)
    records = result.get("records") or []
    if not records:
        return {"state": row["send_state"], "provider": provider.provider_name, "records": 0}

    latest = _match_ses_record(records, set(ids))
    if latest is None:
        return {
            "state": row["send_state"],
            "provider": provider.provider_name,
            "matched": 0,
            "reason_code": "provider_message_mismatch",
            "requires_manual_review": True,
        }

    deliver_status = latest.get("DeliverStatus")
    new_state, reason_code = _map_ses_deliver_status(deliver_status)
    if new_state is None:
        out: dict[str, Any] = {
            "state": row["send_state"],
            "provider": provider.provider_name,
            "ses_deliver_status": deliver_status,
            "reason_code": reason_code,
        }
        if reason_code == "unknown_provider_status":
            out["requires_manual_review"] = True
        return out

    with get_cursor(commit=True) as cur:
        res = transition_delivery_state(
            cur,
            challenge_id,
            ("accepted", "unknown"),
            new_state,
            provider_status=int(deliver_status) if isinstance(deliver_status, int) else None,
            delivery_reason_code=reason_code,
            failure_reason=reason_code if new_state in {"bounced", "delivery_failed"} else None,
            challenge_status_on_failure="failed",
        )
        if res.updated:
            audit_record(
                "email." + new_state,
                "auth_challenge",
                resource_id=challenge_id,
                details={"ses_deliver_status": deliver_status, "reason_code": reason_code},
                cur=cur,
            )
            cur.execute(
                """UPDATE security_delivery_request
                SET failure_stage=%s,
                    failure_reason=%s,
                    outcome=%s,
                    outcome_unknown=false,
                    state=CASE
                        WHEN state IN ('unknown', 'legacy_unknown') THEN %s
                        ELSE state
                    END,
                    execution_stage=CASE
                        WHEN execution_stage IN ('provider_unknown', 'provider_called', 'send_claimed')
                            THEN 'provider_accepted'
                        ELSE execution_stage
                    END
                WHERE (id=%s OR challenge_id=%s::uuid) AND provider_called=true""",
                (
                    "delivery" if new_state in {"bounced", "delivery_failed"} else None,
                    reason_code if new_state in {"bounced", "delivery_failed"} else None,
                    "DELIVERY_FAILED" if new_state in {"bounced", "delivery_failed"} else "COMPLETED",
                    "failed" if new_state in {"bounced", "delivery_failed"} else "completed",
                    challenge_id,
                    challenge_id,
                ),
            )
    if new_state == "delivered" and res.updated:
        transition_risk_checked(
            _engine(),
            challenge_id,
            "delivered",
            channel="email",
            purpose="reconcile",
            cursor_factory=get_cursor,
        )
    out_res: dict[str, Any] = {
        "state": res.current_send_state or row["send_state"],
        "provider": provider.provider_name,
        "outcome": res.outcome,
        "reason_code": reason_code,
        "updated": res.updated,
    }
    if not res.updated and res.outcome != "already_target":
        out_res["requires_manual_review"] = True
    return out_res
