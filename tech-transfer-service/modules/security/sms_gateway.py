"""SMS orchestration over existing Auth tables; no parallel OTP system.

No public status endpoint. Redis is required for all real send paths.
Send ownership requires a committed CAS transition (`reserved -> sending`) before calling
the external provider. Ambiguous outcomes are retained safely without regenerating OTPs.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass, replace
from typing import Any

from config import settings
from core.errors import BizError, bad_request
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.security.delivery_models import (
    DeliveryStageError,
    DeliveryTaskResult,
    metrics,
    risk_reason,
    task_event,
    transition_risk_checked,
)
from modules.security.eligibility import SMS_ELIGIBLE_SQL as ELIGIBLE_SQL
from modules.security.eligibility import sms_eligibility_reason as _shared_sms_eligibility_reason
from modules.security.idempotency import (
    ACTIVE_IDEMPOTENCY_STATES,
    RECOVERY_REQUIRED_IDEMPOTENCY_STATES,
    TERMINAL_IDEMPOTENCY_STATES,
    UNKNOWN_EXECUTION_STAGES,
    IdempotencyClaim,
    advance_idempotency_stage,
    mark_http_idempotency_unknown,
)
from modules.security.provider import ProviderError, get_sms_provider
from modules.security.state_machine import (
    DeliveryTransitionResult,
    claim_send_execution_right,
    transition_delivery_state,
)

logger = logging.getLogger(__name__)

ACTIVE_TASK_STATES = ACTIVE_IDEMPOTENCY_STATES
TERMINAL_TASK_STATES = TERMINAL_IDEMPOTENCY_STATES
RECOVERY_REQUIRED_STATES = RECOVERY_REQUIRED_IDEMPOTENCY_STATES


def eligibility_reason(account: str) -> str:
    return _shared_sms_eligibility_reason(account, cursor_factory=get_cursor)


@dataclass(frozen=True)
class SendContext:
    ip: str
    device_id: str | None
    request_id: str


def normalize_phone(value: str) -> str:
    value = re.sub(r"[ -]", "", value.strip())
    if value.startswith("+86"):
        value = value[3:]
    if not re.fullmatch(r"1[3-9][0-9]{9}", value):
        raise bad_request("手机号格式不正确")
    return value


def recovery_response(challenge_id: str, channel: str) -> dict[str, Any]:
    return {
        "challengeId": challenge_id,
        "channel": channel,
        "maskedDestination": None,
        "sent": True,
        "message": "如果该账号存在且已绑定有效联系方式，验证信息将发送至对应地址。",
    }


def _engine():
    from modules.security.sms_risk import get_sms_risk_engine

    return get_sms_risk_engine()


def _allowed(decision: Any) -> bool:
    value = getattr(decision, "action", getattr(decision, "decision", decision))
    return str(getattr(value, "value", value)) == "ALLOW"


def _audit(rule: str, context: SendContext, challenge_id: str | None = None, **details: Any) -> None:
    from modules.security.service import _fingerprint

    audit_record(
        "sms.gateway",
        "auth_challenge",
        resource_id=challenge_id,
        request_id=context.request_id,
        details={"rule_id": rule, "ip_digest": _fingerprint("ip:" + context.ip), **details},
    )


def request_gate(context: SendContext, account: str, phone: str | None = None, purpose: str = "reset_password") -> None:
    decision = _engine().check_request(context.ip, account, context.device_id, phone=phone, purpose=purpose)
    _audit(
        getattr(decision, "rule_id", "request"),
        context,
        decision=str(getattr(decision, "action", decision)),
        risk_level=getattr(decision, "risk_level", "high"),
        risk_score=getattr(decision, "risk_score", 100),
    )
    if not _allowed(decision):
        # Same response independent of eligibility; no bypass from human verification.
        if "redis" in getattr(decision, "rule_id", ""):
            raise BizError("TT_COMMON_50301", "安全验证服务暂时不可用，请稍后重试", 503)
        retry_after = getattr(decision, "retry_after", 0)
        details = {"retryAfter": retry_after} if retry_after > 0 else None
        raise BizError("TT_COMMON_42901", "操作过于频繁或需要额外安全验证，请稍后重试", 429, details=details)


def start_sms_recovery(
    account: str,
    challenge_id: str,
    context: SendContext,
    engine: Any = None,
    *,
    return_result: bool = False,
) -> Any:
    engine = engine or _engine()
    account = account.strip()
    if account.startswith("+86") or re.fullmatch(r"[0-9 -]+", account):
        try:
            account = normalize_phone(account)
        except BizError:
            if return_result:
                return DeliveryTaskResult(challenge_id, "INELIGIBLE", "eligibility", "invalid_account_format")
            return recovery_response(challenge_id, "sms")
    try:
        with get_cursor() as cur:
            cur.execute(ELIGIBLE_SQL, (account, account))
            rows = cur.fetchall()
    except Exception:
        raise DeliveryStageError("eligibility", "database_unavailable") from None
    if len(rows) != 1:
        _audit("recovery.ineligible", context, challenge_id, decision="DENY")
        try:
            ineligible_reason = "contact_conflict" if len(rows) > 1 else eligibility_reason(account)
        except Exception:
            ineligible_reason = "diagnosis_failed"
        logger.info(
            "找回密码请求未派发短信：账号不符合确权资格 (reason=%s, challenge_id=%s)；"
            "接口按防枚举规范返回统一提示，未向供应商发信",
            ineligible_reason,
            challenge_id,
        )
        if return_result:
            return DeliveryTaskResult(
                challenge_id,
                "INELIGIBLE",
                "eligibility",
                ineligible_reason if ineligible_reason != "eligible" else "eligibility_changed",
            )
        return recovery_response(challenge_id, "sms")
    target = rows[0]
    phone = normalize_phone(target["normalized_value"])
    receipt = _send(target["user_id"], phone, "password_recovery", challenge_id, context, engine)
    if return_result:
        return DeliveryTaskResult(
            challenge_id,
            "COMPLETED",
            provider_ids=receipt.provider_ids,
            provider_called=True,
            challenge_id=challenge_id,
        )
    return recovery_response(challenge_id, "sms")


def start_sms_binding(
    user_id: int,
    phone: str,
    context: SendContext,
    engine: Any = None,
    *,
    idempotency_claim: IdempotencyClaim | None = None,
) -> dict[str, Any]:
    phone = normalize_phone(phone)
    engine = engine or _engine()
    challenge_id = str(uuid.uuid4())
    with get_cursor() as cur:
        cur.execute("SELECT id FROM app_user WHERE id=%s AND status='active' AND deleted_at IS NULL", (user_id,))
        if not cur.fetchone():
            raise bad_request("账号不可用")
        cur.execute(
            """SELECT user_id FROM account_contact WHERE contact_type='phone'
            AND normalized_value=%s AND status='active' AND verified_at IS NOT NULL AND user_id<>%s""",
            (phone, user_id),
        )
        if cur.fetchone():
            raise bad_request("无法绑定此联系方式")
    _send(user_id, phone, "bind_phone", challenge_id, context, engine, idempotency_claim=idempotency_claim)
    return {
        "challengeId": challenge_id,
        "maskedDestination": phone[:3] + "****" + phone[-4:],
        "message": "验证码发送请求已受理",
    }


def _send(
    user_id: int | None,
    phone: str,
    purpose: str,
    challenge_id: str,
    context: SendContext,
    engine: Any,
    *,
    idempotency_claim: IdempotencyClaim | None = None,
) -> Any:
    from modules.security.service import _fingerprint, _hmac_code

    if not settings.SMS_ENABLED:
        raise DeliveryStageError("config", "sms_disabled")
    try:
        provider = get_sms_provider()
    except ProviderError as exc:
        raise DeliveryStageError("config", getattr(exc, "reason_code", "provider_config_invalid")) from None
    account = str(user_id) if user_id is not None else "register:" + phone
    decision = engine.reserve(phone, account, context.ip, context.device_id, challenge_id)
    if not _allowed(decision):
        _audit(getattr(decision, "rule_id", "send.limit"), context, challenge_id, decision="THROTTLE")
        rule = getattr(decision, "rule_id", "sms.risk.blocked")
        raise DeliveryStageError(
            "risk", risk_reason(rule), risk_rule_id=rule, retry_after=getattr(decision, "retry_after", 0)
        )
    code = f"{secrets.randbelow(1_000_000):06d}"
    ttl = settings.SMS_CODE_TTL_SECONDS
    try:
        with get_cursor(commit=True) as cur:
            if user_id is None:
                fingerprint = _fingerprint(phone)
                cur.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", ("register:" + fingerprint,))
                cur.execute(
                    """UPDATE auth_challenge SET status='cancelled'
                    WHERE user_id IS NULL AND purpose='register' AND destination_fingerprint=%s
                    AND status IN ('pending','pending_send')""",
                    (fingerprint,),
                )
            else:
                # Serialize per user and purpose. Same task UUID can never be sent twice.
                cur.execute("SELECT id FROM app_user WHERE id=%s FOR UPDATE", (user_id,))
                cur.execute(
                    """UPDATE auth_challenge SET status='cancelled' WHERE user_id=%s
                    AND purpose=%s AND status IN ('pending','pending_send')""",
                    (user_id, purpose),
                )
            cur.execute(
                """INSERT INTO auth_challenge
                (id,user_id,purpose,channel,destination_fingerprint,destination_masked,code_hash,
                 status,attempt_count,max_attempts,expires_at,send_request_id,send_state,provider_name)
                VALUES (%s,%s,%s,'sms',%s,%s,%s,'pending_send',0,%s,
                        NOW()+make_interval(secs=>%s),%s,'reserved','sms')""",
                (
                    challenge_id,
                    user_id,
                    purpose,
                    _fingerprint(phone),
                    phone[:3] + "****" + phone[-4:],
                    _hmac_code(challenge_id, purpose, phone, code),
                    settings.SMS_CODE_MAX_ATTEMPTS,
                    ttl,
                    challenge_id,
                ),
            )
            audit_record(
                "sms.reserved",
                "auth_challenge",
                resource_id=challenge_id,
                request_id=context.request_id,
                details={"decision": "ALLOW", "rule_id": "send.reserved"},
                cur=cur,
            )
    except Exception:
        transition_risk_checked(
            engine,
            challenge_id,
            "rejected",
            channel="sms",
            purpose=purpose,
            request_id=context.request_id,
            cursor_factory=get_cursor,
        )
        raise DeliveryStageError("challenge_create", "database_write_failed") from None

    send_owner = f"req:{context.request_id}:{uuid.uuid4().hex[:12]}"
    try:
        claim_res = claim_send_execution_right(
            challenge_id,
            send_owner=send_owner,
            expected_states=("reserved",),
            provider_name="sms",
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
                engine,
                challenge_id,
                "rejected",
                channel="sms",
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
            )

    try:
        receipt = provider.send_task(
            phone,
            code,
            "reset_password" if purpose == "password_recovery" else purpose,
            ttl,
            send_request_id=challenge_id,
        )
        if not receipt.accepted:
            raise ProviderError("短信服务未接受请求", request_attempted=True)
    except Exception as exc:
        unknown = not isinstance(exc, ProviderError) or getattr(exc, "outcome_unknown", False)
        state = "unknown" if unknown else "rejected"
        # Ambiguous delivery is not retried by creating a fresh OTP.
        try:
            _set_send_state(challenge_id, state, [], context, expected_owner=send_owner)
        except Exception:
            transition_risk_checked(
                engine,
                challenge_id,
                state,
                channel="sms",
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
                "database_write_failed",
                outcome_unknown=True,
                provider_called=getattr(exc, "request_attempted", True),
                provider_status=getattr(exc, "provider_status", None),
            ) from None
        transition_risk_checked(
            engine,
            challenge_id,
            state,
            channel="sms",
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
                    failure_reason=getattr(exc, "reason_code", state),
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
                ) from None
        if isinstance(exc, ProviderError):
            raise DeliveryStageError(
                "provider",
                getattr(exc, "reason_code", "provider_rejected"),
                outcome_unknown=unknown,
                provider_called=getattr(exc, "request_attempted", unknown),
                provider_status=getattr(exc, "provider_status", None),
                retryable=getattr(exc, "retryable", False),
            ) from None
        raise DeliveryStageError(
            "provider", "unexpected_provider_error", outcome_unknown=True, provider_called=True
        ) from None

    try:
        res = _set_send_state(
            challenge_id,
            "accepted",
            list(receipt.provider_ids),
            context,
            expected_owner=send_owner,
        )
        if not res.updated and res.outcome != "already_target":
            raise DeliveryStageError(
                "receipt_persist",
                "RECEIPT_STATE_CONFLICT",
                provider_ids=receipt.provider_ids,
                provider_called=True,
                outcome_unknown=True,
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
            "database_write_failed",
            provider_ids=receipt.provider_ids,
            provider_called=True,
            outcome_unknown=True,
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
                provider_ids=receipt.provider_ids,
                provider_called=True,
                outcome_unknown=True,
            )
    transition_risk_checked(
        engine,
        challenge_id,
        "accepted",
        channel="sms",
        purpose=purpose,
        request_id=context.request_id,
        cursor_factory=get_cursor,
    )
    return receipt


def _set_send_state(
    challenge_id: str,
    state: str,
    provider_ids: list[str],
    context: SendContext,
    *,
    expected_owner: str | None = None,
) -> DeliveryTransitionResult:
    with get_cursor(commit=True) as cur:
        res = transition_delivery_state(
            cur,
            challenge_id,
            ("reserved", "sending"),
            state,
            provider_ids=provider_ids,
            challenge_status_on_failure="failed",
            expected_owner=expected_owner,
        )
        if res.updated:
            audit_record(
                "sms." + state,
                "auth_challenge",
                resource_id=challenge_id,
                request_id=context.request_id,
                details={"send_state": state},
                cur=cur,
            )
        elif res.outcome != "already_target":
            metrics.inc(
                "delivery_cas_conflict_total",
                channel="sms",
                purpose=state,
                reason=res.outcome,
            )
            logger.warning(
                "SMS delivery state CAS conflict (challenge=%s target=%s outcome=%s current=%s)",
                challenge_id,
                state,
                res.outcome,
                res.current_send_state,
            )
    return res


def run_recovery_task(account: str, channel: str, challenge_id: str, context: SendContext) -> DeliveryTaskResult:
    """Run after uniform HTTP response. Never expose business/provider outcome."""
    start = time.monotonic()
    exception_type = None
    try:
        if channel == "sms":
            result = start_sms_recovery(account, challenge_id, context, return_result=True)
        elif channel in {"email_otp", "email_link"}:
            from modules.security.email_gateway import start_email_recovery

            result = start_email_recovery(account, channel, challenge_id, context, return_result=True)
        else:
            from modules.security.service import start_password_recovery

            value = start_password_recovery(account, channel, challenge_id=challenge_id)
            result = DeliveryTaskResult(
                challenge_id,
                "COMPLETED" if value.get("challengeId") else "INELIGIBLE",
                challenge_id=value.get("challengeId"),
                channel=channel,
                purpose="password_recovery",
            )
        if not isinstance(result, DeliveryTaskResult):
            raise TypeError("delivery_result_missing")
    except ProviderError as exc:
        exception_type = type(exc).__name__
        stage = getattr(exc, "stage", "provider")
        unknown = exc.outcome_unknown
        outcome = (
            "RISK_BLOCKED"
            if stage == "risk"
            else "CONFIG_ERROR"
            if stage == "config"
            else "INTERNAL_ERROR"
            if stage in {"eligibility", "challenge_create", "receipt_persist", "send_claim"}
            else "PROVIDER_UNKNOWN"
            if unknown
            else "PROVIDER_REJECTED"
        )
        result = DeliveryTaskResult(
            challenge_id,
            outcome,
            stage,
            getattr(exc, "reason_code", "provider_error"),
            provider_status=getattr(exc, "provider_status", None),
            provider_ids=getattr(exc, "provider_ids", ()),
            retryable=getattr(exc, "retryable", False),
            outcome_unknown=unknown,
            risk_rule_id=getattr(exc, "risk_rule_id", None),
            provider_called=getattr(exc, "request_attempted", False),
            challenge_id=challenge_id if stage not in {"risk", "config", "eligibility"} else None,
            channel=channel,
            purpose="password_recovery",
            provider=getattr(exc, "provider_name", None),
        )
    except Exception as exc:
        exception_type = type(exc).__name__
        result = DeliveryTaskResult(
            challenge_id,
            "INTERNAL_ERROR",
            "task",
            "unexpected_exception",
            channel=channel,
            purpose="password_recovery",
        )
    result = replace(result, elapsed_ms=max(0, int((time.monotonic() - start) * 1000)))
    task_event(logger, result, context.request_id, "task_result", exception_type)
    return result


def enqueue_recovery_task(account: str, channel: str, challenge_id: str, context: SendContext) -> None:
    """Same insert for real/unknown accounts, before any eligibility lookup."""
    payload = {
        "account": account,
        "channel": channel,
        "ip": context.ip,
        "device_id": context.device_id,
        "request_id": context.request_id,
    }
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "INSERT INTO security_delivery_request(id,payload,request_id,channel,purpose,execution_stage) "
                "VALUES(%s,%s::jsonb,%s,%s,'password_recovery','pre_provider')",
                (challenge_id, json.dumps(payload), context.request_id, channel[:16]),
            )
    except Exception as exc:
        task_event(
            logger,
            DeliveryTaskResult(challenge_id, "INTERNAL_ERROR", "queue_enqueue", "database_unavailable"),
            context.request_id,
            "queue_enqueue_failed",
            type(exc).__name__,
        )
        raise BizError("TT_COMMON_50301", "验证服务暂时不可用，请稍后重试", 503) from None


def run_queued_recovery_task(challenge_id: str) -> bool:
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """UPDATE security_delivery_request SET state='processing',claimed_at=NOW()
                WHERE id=%s AND state='queued' AND created_at>NOW()-INTERVAL '5 minutes'
                RETURNING payload""",
                (challenge_id,),
            )
            row = cur.fetchone()
    except Exception as exc:
        task_event(
            logger,
            DeliveryTaskResult(challenge_id, "INTERNAL_ERROR", "queue_claim", "database_unavailable", retryable=True),
            None,
            "queue_claim_failed",
            type(exc).__name__,
        )
        return False
    if not row:
        return False
    data = row["payload"] if isinstance(row["payload"], dict) else {}
    # Never regenerate a code for processing/unknown tasks after a worker crash.
    try:
        result = run_recovery_task(
            data["account"],
            data["channel"],
            challenge_id,
            SendContext(data["ip"], data["device_id"], data["request_id"]),
        )
        if not isinstance(result, DeliveryTaskResult):
            raise TypeError("delivery_result_missing")
    except Exception as exc:
        result = DeliveryTaskResult(challenge_id, "INTERNAL_ERROR", "task", "unexpected_worker_exception")
        task_event(logger, result, data.get("request_id"), "worker_error", type(exc).__name__)
    try:
        return _persist_task_result(challenge_id, result, data.get("request_id"))
    except Exception as exc:
        failed = replace(
            result,
            outcome="INTERNAL_ERROR",
            failure_stage="queue_persist",
            failure_reason="database_write_failed",
            outcome_unknown=result.provider_called or result.outcome_unknown,
        )
        task_event(logger, failed, data.get("request_id"), "queue_persist_failed", type(exc).__name__)
        return False


def _persist_task_result(challenge_id: str, result: DeliveryTaskResult, request_id: str | None) -> bool:
    exec_stage = (
        "provider_unknown"
        if result.outcome_unknown or result.outcome == "PROVIDER_UNKNOWN"
        else "provider_accepted"
        if result.outcome == "COMPLETED" and result.provider_called
        else "provider_rejected"
        if result.outcome == "PROVIDER_REJECTED" and result.provider_called
        else "pre_provider"
    )
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    is_unknown = bool(result.outcome_unknown or result.queue_state == "unknown")
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE security_delivery_request SET state=%s,outcome=%s,failure_stage=%s,failure_reason=%s,
              provider_status=%s,risk_rule_id=%s,provider_ids=%s::jsonb,outcome_unknown=%s,retryable=%s,
              elapsed_ms=%s,provider_called=%s,channel=%s,purpose=%s,provider=%s,
              execution_stage=%s,stage_provenance='explicit',challenge_id=COALESCE(%s::uuid, challenge_id),
              idempotency_expires_at = CASE
                  WHEN idempotency_key IS NOT NULL AND %s::boolean
                      THEN GREATEST(COALESCE(idempotency_expires_at, NOW()), NOW() + make_interval(secs => %s))
                  ELSE idempotency_expires_at
              END,
              finished_at=NOW(),
              payload=COALESCE(payload,'{}'::jsonb)-'account'-'ip'-'device_id'-'destination'
              WHERE id=%s AND state='processing'""",
            (
                result.queue_state,
                result.outcome,
                result.failure_stage,
                result.failure_reason,
                result.provider_status,
                result.risk_rule_id,
                json.dumps(result.provider_ids),
                result.outcome_unknown,
                result.retryable,
                result.elapsed_ms,
                result.provider_called,
                result.channel,
                result.purpose,
                result.provider,
                exec_stage,
                result.challenge_id,
                is_unknown,
                unknown_retention,
                challenge_id,
            ),
        )
        audit_record(
            "sms.task_result" if result.channel == "sms" else "email.task_result",
            "security_delivery_request",
            resource_id=challenge_id,
            request_id=request_id,
            details={
                "channel": result.channel,
                "purpose": result.purpose,
                "provider": result.provider,
                "outcome": result.outcome,
                "stage": result.failure_stage,
                "reason_code": result.failure_reason,
                "risk_rule_id": result.risk_rule_id,
                "provider_status": result.provider_status,
                "outcome_unknown": result.outcome_unknown,
                "provider_called": result.provider_called,
                "elapsed_ms": result.elapsed_ms,
            },
            cur=cur,
        )
    return True


def process_pending_recovery_tasks(limit: int = 50) -> int:
    """Worker hook. Safe for multiple workers; each claim is an atomic CAS."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM security_delivery_request WHERE state='queued' ORDER BY created_at LIMIT %s",
            (max(1, min(100, int(limit))),),
        )
        ids = [str(row["id"]) for row in cur.fetchall()]
    return sum(1 for cid in ids if run_queued_recovery_task(cid))


def cleanup_delivery_tasks() -> None:
    """清理过期队列任务、收敛 Worker/幂等占位崩溃残留、仅在终态/未知恢复态清除明文 PII。

    - 绝不误伤正在合法执行中的 `idem_pending` / `queued` / `processing` 任务；
    - 仅当明确停留在 `pre_provider` + `provider_called=false` + `stage_provenance='explicit'` 且关联挑战
      未进入 sending+ 时才允许释放超时崩溃占位键；
    - `unknown` / `legacy_unknown` / `provider_unknown` 与 `claim_http_idempotency` 采用统一长保留期
      `IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS`，绝不因常规 300s `idempotency_expires_at` 到期而提前释放。
    """
    ownership_seconds = max(60, int(settings.IDEMPOTENCY_EXECUTION_OWNERSHIP_SECONDS))
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    delete_retention = max(7 * 86400, unknown_retention)
    with get_cursor(commit=True) as cur:
        # 1. 超时 idem_pending：仅明确未入外呼阶段且来源显式时安全过期释放；否则保守收敛为 unknown 并锁定键长保留期
        cur.execute(
            """UPDATE security_delivery_request sdr
            SET idempotency_key = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN NULL
                    ELSE sdr.idempotency_key
                END,
                idempotency_scope = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN NULL
                    ELSE sdr.idempotency_scope
                END,
                state = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN 'expired'
                    ELSE 'unknown'
                END,
                outcome = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN COALESCE(sdr.outcome, 'INTERNAL_ERROR')
                    ELSE 'PROVIDER_UNKNOWN'
                END,
                failure_stage = COALESCE(sdr.failure_stage, 'idempotency'),
                failure_reason = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN COALESCE(sdr.failure_reason, 'idem_pending_expired')
                    ELSE COALESCE(sdr.failure_reason, 'idem_pending_interrupted')
                END,
                outcome_unknown = CASE
                    WHEN sdr.execution_stage = 'pre_provider'
                         AND sdr.provider_called = false
                         AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                         AND NOT EXISTS (
                             SELECT 1 FROM auth_challenge ac
                             WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                               AND ac.send_state IN (
                                   'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                               )
                         )
                        THEN sdr.outcome_unknown
                    ELSE true
                END,
                idempotency_expires_at = CASE
                    WHEN NOT (
                        sdr.execution_stage = 'pre_provider'
                        AND sdr.provider_called = false
                        AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                        AND NOT EXISTS (
                            SELECT 1 FROM auth_challenge ac
                            WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                              AND ac.send_state IN (
                                  'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                              )
                        )
                    ) AND sdr.idempotency_key IS NOT NULL
                        THEN GREATEST(
                            COALESCE(sdr.idempotency_expires_at, NOW()),
                            NOW() + make_interval(secs => %s)
                        )
                    ELSE sdr.idempotency_expires_at
                END,
                retryable = false,
                finished_at = COALESCE(sdr.finished_at, NOW()),
                payload = COALESCE(sdr.payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
            WHERE sdr.state IN ('idem_pending', 'idempotent_pending')
              AND COALESCE(sdr.idem_claimed_at, sdr.created_at) < NOW() - make_interval(secs => %s)""",
            (unknown_retention, ownership_seconds),
        )
        # 2. queued 超时（未曾调用外部发送）：终止为 expired 并清除明文 PII
        cur.execute(
            """UPDATE security_delivery_request
            SET state='expired', outcome='INTERNAL_ERROR',
                failure_stage='queue', failure_reason='queued_request_expired',
                finished_at=NOW(),
                payload=COALESCE(payload,'{}'::jsonb)-'account'-'ip'-'device_id'-'destination'
            WHERE state='queued'
              AND execution_stage='pre_provider'
              AND provider_called=false
              AND created_at<NOW()-make_interval(secs => %s)""",
            (ownership_seconds,),
        )
        # 3. processing 超时（Worker 崩溃，真实发送结果未知）：收敛为 unknown、保留幂等键并清除明文 PII
        cur.execute(
            """UPDATE security_delivery_request
            SET state='unknown', outcome='PROVIDER_UNKNOWN',
                failure_stage='worker', failure_reason='worker_interrupted',
                outcome_unknown=true, retryable=false, finished_at=NOW(),
                execution_stage=CASE
                    WHEN execution_stage='pre_provider' THEN 'provider_unknown'
                    ELSE execution_stage
                END,
                idempotency_expires_at=CASE
                    WHEN idempotency_key IS NOT NULL
                        THEN GREATEST(COALESCE(idempotency_expires_at, NOW()), NOW() + make_interval(secs => %s))
                    ELSE idempotency_expires_at
                END,
                payload=COALESCE(payload,'{}'::jsonb)-'account'-'ip'-'device_id'-'destination'
            WHERE state='processing' AND COALESCE(claimed_at,created_at)<NOW()-make_interval(secs => %s)""",
            (unknown_retention, ownership_seconds),
        )
        # 4. 仅针对显式终态与需核对未知态剥离残留明文 PII（严禁触碰活跃中的 idem_pending/queued/processing）
        cur.execute(
            """UPDATE security_delivery_request
            SET payload=COALESCE(payload,'{}'::jsonb)-'account'-'ip'-'device_id'-'destination'
            WHERE state = ANY(%s)
              AND (payload ? 'account' OR payload ? 'ip' OR payload ? 'device_id' OR payload ? 'destination')""",
            (list(TERMINAL_TASK_STATES + RECOVERY_REQUIRED_STATES),),
        )
        # 5a. 清理非活跃且确定终态（未涉 unknown）且幂等窗口已过期的幂等键
        cur.execute(
            """UPDATE security_delivery_request
            SET idempotency_key=NULL, idempotency_scope=NULL
            WHERE state = ANY(%s)
              AND outcome_unknown = false
              AND COALESCE(execution_stage, 'pre_provider') <> ALL(%s)
              AND COALESCE(stage_provenance, 'explicit') <> 'legacy_unknown'
              AND idempotency_key IS NOT NULL
              AND idempotency_expires_at IS NOT NULL
              AND idempotency_expires_at <= NOW()""",
            (list(TERMINAL_TASK_STATES), list(UNKNOWN_EXECUTION_STAGES)),
        )
        # 5b. unknown / legacy_unknown / provider_unknown：仅在同时超过长保留期 IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS 时释放
        cur.execute(
            """UPDATE security_delivery_request
            SET idempotency_key=NULL, idempotency_scope=NULL
            WHERE state <> ALL(%s)
              AND (
                  state = ANY(%s)
                  OR outcome_unknown = true
                  OR execution_stage = ANY(%s)
                  OR stage_provenance = 'legacy_unknown'
              )
              AND idempotency_key IS NOT NULL
              AND (idempotency_expires_at IS NULL OR idempotency_expires_at <= NOW())
              AND COALESCE(finished_at, idem_claimed_at, created_at) <= NOW() - make_interval(secs => %s)""",
            (
                list(ACTIVE_TASK_STATES),
                list(RECOVERY_REQUIRED_STATES),
                list(UNKNOWN_EXECUTION_STAGES),
                unknown_retention,
            ),
        )
        # 6. 仅清理超过保留期（>=7 天且超过 unknown 长保留期）的非活跃任务
        cur.execute(
            """DELETE FROM security_delivery_request
            WHERE state <> ALL(%s)
              AND (
                  (state = ANY(%s) AND outcome_unknown = false AND created_at < NOW() - INTERVAL '7 days')
                  OR (
                      (state = ANY(%s) OR outcome_unknown = true)
                      AND COALESCE(finished_at, idem_claimed_at, created_at) < NOW() - make_interval(secs => %s)
                  )
              )""",
            (
                list(ACTIVE_TASK_STATES),
                list(TERMINAL_TASK_STATES),
                list(RECOVERY_REQUIRED_STATES),
                delete_retention,
            ),
        )
        cur.execute(
            """UPDATE auth_challenge SET status='expired'
            WHERE status IN ('pending_send','pending') AND expires_at<=NOW()"""
        )
        cur.execute(
            """UPDATE recovery_grant SET status='expired'
            WHERE status='active' AND expires_at<=NOW()"""
        )
        cur.execute(
            """UPDATE step_up_grant SET status='expired'
            WHERE status='active' AND expires_at<=NOW()"""
        )


def reconcile_sms_delivery(challenge_id: str) -> dict[str, Any] | None:
    """Internal scheduled/operations hook; no public account-status oracle.

    Acceptance consumes a send allowance even if final delivery fails. SendCloud
    status query may cache results for ten minutes; re-run after that window.
    Unknown tasks without a provider ID require operator reconciliation.
    """
    with get_cursor() as cur:
        cur.execute(
            "SELECT provider_message_ids,send_state FROM auth_challenge WHERE id=%s AND channel='sms'", (challenge_id,)
        )
        row = cur.fetchone()
    if not row:
        return None
    if row["send_state"] in {"delivered", "delivery_failed", "rejected"}:
        return {"state": row["send_state"]}
    ids = row["provider_message_ids"]
    if not ids:
        return {"state": "unknown", "requires_manual_review": True}
    provider = get_sms_provider()
    if not hasattr(provider, "query_status"):
        raise ProviderError("服务商不支持状态查询")
    result = provider.query_status(ids)
    records = [r for r in result["records"] if r.get("smsId") in ids]
    if not records:
        return {"state": row["send_state"]}
    codes = [int(r["statusCode"]) for r in records]
    reason_code = next(
        (
            str(r.get("sendLog"))
            for r in records
            if re.fullmatch(r"[A-Za-z0-9_-]{1,32}", str(r.get("sendLog", "")))
            and not re.search(r"1[3-9][0-9]{9}", str(r.get("sendLog", "")))
        ),
        None,
    )
    state = (
        "delivered"
        if len(records) == len(ids) and all(c == 200 for c in codes)
        else "delivery_failed"
        if any(400 <= c < 600 for c in codes)
        else row["send_state"]
    )
    if state not in {"delivered", "delivery_failed"}:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE auth_challenge SET delivery_status_code=%s WHERE id=%s AND send_state IN ('accepted','unknown')",
                (codes[-1], challenge_id),
            )
        return {"state": state}
    target_status_code = 200 if state == "delivered" else next(c for c in codes if 400 <= c < 600)
    with get_cursor(commit=True) as cur:
        res = transition_delivery_state(
            cur,
            challenge_id,
            ("accepted", "unknown"),
            state,
            provider_status=target_status_code,
            delivery_reason_code=reason_code,
            challenge_status_on_failure="failed",
        )
        if res.updated:
            audit_record(
                "sms." + state,
                "auth_challenge",
                resource_id=challenge_id,
                details={"status_codes": codes, "reason_code": reason_code},
                cur=cur,
            )
            cur.execute(
                """UPDATE security_delivery_request
                SET failure_stage=%s,
                    failure_reason=%s,
                    provider_status=%s,
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
                    "delivery" if state == "delivery_failed" else None,
                    "sendcloud_delivery_failed" if state == "delivery_failed" else None,
                    target_status_code,
                    "DELIVERY_FAILED" if state == "delivery_failed" else "COMPLETED",
                    "failed" if state == "delivery_failed" else "completed",
                    challenge_id,
                    challenge_id,
                ),
            )
    if state == "delivered" and res.updated:
        transition_risk_checked(
            _engine(),
            challenge_id,
            "delivered",
            channel="sms",
            purpose="reconcile",
            cursor_factory=get_cursor,
        )
    return {
        "state": res.current_send_state or row["send_state"],
        "outcome": res.outcome,
        "updated": res.updated,
    }
