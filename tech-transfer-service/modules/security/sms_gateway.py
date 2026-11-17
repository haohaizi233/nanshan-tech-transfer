"""SMS orchestration over existing Auth tables; no parallel OTP system.

No public status endpoint. Redis is required for all real send paths. A send
reservation is retained on ambiguous outcomes; no new OTP is generated on retry.
"""

from __future__ import annotations

import json
import logging
import re
import secrets
import time
import uuid
from dataclasses import dataclass, replace

from config import settings
from core.errors import BizError, bad_request
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.security.provider import ProviderError, get_sms_provider
from modules.security.sms_delivery import DeliveryStageError, DeliveryTaskResult, risk_reason, task_event

logger = logging.getLogger(__name__)


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


def recovery_response(challenge_id: str, channel: str) -> dict:
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


def _allowed(decision) -> bool:
    value = getattr(decision, "action", getattr(decision, "decision", decision))
    return getattr(value, "value", value) == "ALLOW"


def _audit(rule: str, context: SendContext, challenge_id=None, **details):
    from modules.security.service import _fingerprint

    audit_record(
        "sms.gateway",
        "auth_challenge",
        resource_id=challenge_id,
        request_id=context.request_id,
        details={"rule_id": rule, "ip_digest": _fingerprint("ip:" + context.ip), **details},
    )


def request_gate(context: SendContext, account: str, phone=None, purpose="reset_password"):
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
        raise BizError("TT_COMMON_42901", "操作过于频繁或需要额外安全验证，请稍后重试", 429)


ELIGIBLE_SQL = """
SELECT au.id AS user_id, ac.normalized_value
FROM app_user au
JOIN user_credential uc ON uc.user_id = au.id AND uc.status = 'active'
JOIN account_contact ac ON ac.user_id = au.id AND ac.contact_type = 'phone'
    AND ac.status = 'active' AND ac.verified_at IS NOT NULL
    AND ac.verification_method IN ('sms','wechat','manual')
WHERE au.deleted_at IS NULL AND au.status = 'active'
  AND uc.password_configured = true AND uc.password_hash IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id = au.id
                  AND ur.role_code IN ('admin','platform_admin','org_admin'))
  AND NOT EXISTS (SELECT 1 FROM organization_membership om WHERE om.user_id = au.id
                  AND om.role = 'admin' AND om.status = 'active')
  AND NOT EXISTS (SELECT 1 FROM account_contact other WHERE other.contact_type = 'phone'
                  AND other.status = 'active' AND other.verified_at IS NOT NULL
                  AND other.normalized_value = ac.normalized_value AND other.user_id <> au.id)
  AND (uc.username = %s OR ac.normalized_value = %s)
LIMIT 2
"""


def start_sms_recovery(account: str, challenge_id: str, context: SendContext, engine=None, *, return_result=False):
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
        if return_result:
            return DeliveryTaskResult(
                challenge_id,
                "INELIGIBLE",
                "eligibility",
                "contact_conflict" if len(rows) > 1 else "no_eligible_account",
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


def start_sms_binding(user_id: int, phone: str, context: SendContext, engine=None):
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
    _send(user_id, phone, "bind_phone", challenge_id, context, engine)
    return {
        "challengeId": challenge_id,
        "maskedDestination": phone[:3] + "****" + phone[-4:],
        "message": "验证码发送请求已受理",
    }


def _send(user_id, phone, purpose, challenge_id, context, engine):
    from modules.security.service import _fingerprint, _hmac_code

    if not settings.SMS_ENABLED:
        raise DeliveryStageError("config", "sms_disabled")
    try:
        provider = get_sms_provider()
    except ProviderError as exc:
        raise DeliveryStageError("config", getattr(exc, "reason_code", "provider_config_invalid")) from None
    decision = engine.reserve(phone, str(user_id), context.ip, context.device_id, challenge_id)
    if not _allowed(decision):
        _audit(getattr(decision, "rule_id", "send.limit"), context, challenge_id, decision="THROTTLE")
        rule = getattr(decision, "rule_id", "sms.risk.blocked")
        raise DeliveryStageError("risk", risk_reason(rule), risk_rule_id=rule)
    code = f"{secrets.randbelow(1_000_000):06d}"
    ttl = settings.SMS_CODE_TTL_SECONDS
    try:
        with get_cursor(commit=True) as cur:
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
                 status,attempt_count,max_attempts,expires_at,send_request_id,send_state)
                VALUES (%s,%s,%s,'sms',%s,%s,%s,'pending_send',0,%s,
                        NOW()+make_interval(secs=>%s),%s,'reserved')""",
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
        engine.transition(challenge_id, "rejected")
        raise DeliveryStageError("challenge_create", "database_write_failed") from None
    try:
        receipt = provider.send_task(
            phone,
            code,
            "reset_password" if purpose == "password_recovery" else purpose,
            ttl,
            send_request_id=challenge_id,
        )
        if not receipt.accepted:
            raise ProviderError("短信服务未接受请求")
    except Exception as exc:
        unknown = not isinstance(exc, ProviderError) or getattr(exc, "outcome_unknown", False)
        state = "unknown" if unknown else "rejected"
        # Ambiguous delivery is not retried by creating a fresh OTP.
        engine.transition(challenge_id, state)
        try:
            _set_send_state(challenge_id, state, [], context)
        except Exception:
            raise DeliveryStageError(
                "receipt_persist",
                "database_write_failed",
                outcome_unknown=unknown,
                provider_called=getattr(exc, "request_attempted", unknown),
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
        _set_send_state(challenge_id, "accepted", list(receipt.provider_ids), context)
    except Exception:
        raise DeliveryStageError(
            "receipt_persist",
            "database_write_failed",
            provider_ids=receipt.provider_ids,
            provider_called=True,
            outcome_unknown=True,
        ) from None
    engine.transition(challenge_id, "accepted")
    return receipt


def _set_send_state(challenge_id, state, provider_ids, context):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE auth_challenge SET send_state=%s, provider_message_ids=%s::jsonb,
            status=CASE WHEN status='pending_send' THEN
                CASE WHEN %s IN ('accepted','unknown') THEN 'pending' ELSE 'failed' END ELSE status END
            WHERE id=%s""",
            (state, json.dumps(provider_ids), state, challenge_id),
        )
        audit_record(
            "sms." + state,
            "auth_challenge",
            resource_id=challenge_id,
            request_id=context.request_id,
            details={"send_state": state},
            cur=cur,
        )


def run_recovery_task(account, channel, challenge_id, context):
    """Run after uniform HTTP response. Never expose business/provider outcome."""
    start = time.monotonic()
    exception_type = None
    try:
        if channel == "sms":
            result = start_sms_recovery(account, challenge_id, context, return_result=True)
        else:
            from modules.security.service import start_password_recovery

            value = start_password_recovery(account, channel, challenge_id=challenge_id)
            result = DeliveryTaskResult(
                challenge_id,
                "COMPLETED" if value.get("challengeId") else "INELIGIBLE",
                challenge_id=value.get("challengeId"),
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
            if stage in {"eligibility", "challenge_create", "receipt_persist"}
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
        )
    except Exception as exc:
        exception_type = type(exc).__name__
        result = DeliveryTaskResult(challenge_id, "INTERNAL_ERROR", "task", "unexpected_exception")
    result = replace(result, elapsed_ms=max(0, int((time.monotonic() - start) * 1000)))
    task_event(logger, result, context.request_id, "task_result", exception_type)
    return result


def enqueue_recovery_task(account, channel, challenge_id, context):
    """Same insert for real/unknown accounts, before any eligibility lookup."""
    payload = {
        "account": account,
        "channel": channel,
        "ip": context.ip,
        "device_id": context.device_id,
        "request_id": context.request_id,
    }
    with get_cursor(commit=True) as cur:
        cur.execute(
            "INSERT INTO security_delivery_request(id,payload,request_id) VALUES(%s,%s::jsonb,%s)",
            (challenge_id, json.dumps(payload), context.request_id),
        )


def run_queued_recovery_task(challenge_id):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE security_delivery_request SET state='processing',claimed_at=NOW()
            WHERE id=%s AND state='queued' AND created_at>NOW()-INTERVAL '5 minutes'
            RETURNING payload""",
            (challenge_id,),
        )
        row = cur.fetchone()
    if not row:
        return False
    data = row["payload"]
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
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE security_delivery_request SET state=%s,outcome=%s,failure_stage=%s,failure_reason=%s,
              provider_status=%s,risk_rule_id=%s,provider_ids=%s::jsonb,outcome_unknown=%s,retryable=%s,
              elapsed_ms=%s,provider_called=%s,finished_at=NOW() WHERE id=%s AND state='processing'""",
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
                challenge_id,
            ),
        )
        audit_record(
            "sms.task_result",
            "security_delivery_request",
            resource_id=challenge_id,
            request_id=data.get("request_id"),
            details={
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


def process_pending_recovery_tasks(limit=50):
    """Worker hook. Safe for multiple workers; each claim is an atomic CAS."""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id FROM security_delivery_request WHERE state='queued' ORDER BY created_at LIMIT %s",
            (max(1, min(100, int(limit))),),
        )
        ids = [str(row["id"]) for row in cur.fetchall()]
    return sum(run_queued_recovery_task(cid) for cid in ids)


def cleanup_delivery_tasks():
    with get_cursor(commit=True) as cur:
        cur.execute("""UPDATE security_delivery_request SET state='expired',finished_at=NOW()
            WHERE state IN ('queued','processing') AND created_at<NOW()-INTERVAL '5 minutes'""")
        cur.execute("DELETE FROM security_delivery_request WHERE created_at<NOW()-INTERVAL '7 days'")


def reconcile_sms_delivery(challenge_id: str):
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
    if not row or row["send_state"] in {"delivered", "delivery_failed", "rejected"}:
        return None
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
    state = (
        "delivered"
        if len(records) == len(ids) and all(c == 200 for c in codes)
        else "delivery_failed"
        if any(400 <= c < 600 for c in codes)
        else row["send_state"]
    )
    if state not in {"delivered", "delivery_failed"}:
        return {"state": state}
    with get_cursor(commit=True) as cur:
        cur.execute(
            """UPDATE auth_challenge SET send_state=%s,
            status=CASE WHEN %s='delivery_failed' AND status='pending' THEN 'failed' ELSE status END
            WHERE id=%s AND send_state IN ('accepted','unknown')""",
            (state, state, challenge_id),
        )
        if cur.rowcount:
            audit_record(
                "sms." + state, "auth_challenge", resource_id=challenge_id, details={"status_codes": codes}, cur=cur
            )
    if state == "delivered":
        _engine().transition(challenge_id, "delivered")
    return {"state": state}
