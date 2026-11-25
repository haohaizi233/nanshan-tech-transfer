"""Internal, read-only, redacted diagnostics. Never imported by a public route."""

from __future__ import annotations

import hashlib
import hmac
import json
from unittest.mock import patch
from urllib.parse import parse_qs

from config import settings
from db import get_cursor
from modules.security.sms_delivery import safe_id


def authorized_live_target(account, phone):
    """Require an explicit operator-named test number matching a trusted binding."""
    from modules.security.sms_gateway import ELIGIBLE_SQL, normalize_phone

    phone = normalize_phone(phone)
    with get_cursor() as cur:
        cur.execute(ELIGIBLE_SQL, (account, account))
        rows = cur.fetchall()
    return len(rows) == 1 and hmac.compare_digest(normalize_phone(rows[0]["normalized_value"]), phone)


def redis_client():
    import redis
    from redis.backoff import NoBackoff
    from redis.retry import Retry

    return redis.Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        protocol=2,
        socket_connect_timeout=2,
        socket_timeout=2,
        retry=Retry(NoBackoff(), 0),
    )


def config_check():
    fields = [
        "APP_ENV",
        "SMS_ENABLED",
        "SMS_PROVIDER",
        "REDIS_ENABLED",
        "SMS_RISK_ENGINE_ENABLED",
        "SMS_REQUIRE_VERIFIED_CONTACT",
        "SENDCLOUD_SMS_MAX_ATTEMPTS",
    ]
    result = {
        "scope": "fresh_cli_process_not_running_worker",
        "settings": {k: getattr(settings, k) for k in fields},
        "configured": {
            k: bool(getattr(settings, k))
            for k in ["SENDCLOUD_SMS_USER", "SENDCLOUD_SMS_KEY", "SENDCLOUD_SMS_TEMPLATE_ID", "SMS_USER", "SMS_KEY"]
        },
        "running_process_reload": "BLOCKED_EXTERNAL",
    }
    try:
        client = redis_client()
        try:
            result["redis"] = {"ping": client.ping(), "lua": client.eval("return 1", 0) == 1}
        finally:
            client.close()
    except Exception as exc:
        result["redis"] = {"ping": False, "error_type": type(exc).__name__}
    try:
        with get_cursor() as cur:
            cur.execute("""SELECT table_name,column_name FROM information_schema.columns WHERE table_schema='public'
                AND table_name IN ('security_delivery_request','auth_challenge','account_contact')""")
            columns = {(r["table_name"], r["column_name"]) for r in cur.fetchall()}
        required = {
            ("account_contact", "verification_method"),
            ("auth_challenge", "send_state"),
            ("security_delivery_request", "outcome"),
            ("security_delivery_request", "request_id"),
            ("auth_challenge", "delivery_status_code"),
        }
        result["postgres"] = {
            "connected": True,
            "migration_033_034_035_ready": required <= columns,
            "missing_columns": sorted(".".join(x) for x in required - columns),
        }
    except Exception as exc:
        result["postgres"] = {"connected": False, "error_type": type(exc).__name__}
    return result


def queue_check():
    with get_cursor() as cur:
        cur.execute("SELECT state,COUNT(*) AS count FROM security_delivery_request GROUP BY state")
        states = {r["state"]: r["count"] for r in cur.fetchall()}
        cur.execute("""SELECT COUNT(*) AS count FROM security_delivery_request WHERE state='processing'
            AND COALESCE(claimed_at,created_at)<NOW()-INTERVAL '5 minutes'""")
        stale = cur.fetchone()["count"]
        cur.execute("""SELECT failure_stage,COUNT(*) AS count FROM security_delivery_request
            WHERE failure_stage IS NOT NULL AND created_at>NOW()-INTERVAL '1 day' GROUP BY failure_stage""")
        stages = {r["failure_stage"]: r["count"] for r in cur.fetchall()}
    return {"states": states, "stale_processing": stale, "recent_failure_stages": stages}


def _recommend(stage, reason):
    if stage == "eligibility":
        return "complete_verified_binding_or_use_audited_manual_recovery"
    if stage == "delivery":
        return "check_sendcloud_delivery_log_and_contact_vendor"
    if reason == "REDIS_UNAVAILABLE":
        return "restore_redis_connectivity_without_disabling_risk_controls"
    if stage == "risk":
        return "inspect_rule_and_ttl_do_not_bypass_limits"
    if stage == "config":
        return "verify_sms_config_and_restart_correct_worker"
    if stage in {"worker", "queue", "task", "receipt_persist", "challenge_create"}:
        return "inspect_worker_and_database_no_automatic_resend"
    if stage == "provider":
        return "check_provider_status_and_authorization_no_blind_resend"
    return "await_or_reconcile_final_receipt"


def diagnose(*, challenge_id=None, request_id=None, account=None):
    if account is not None:
        from modules.security.sms_gateway import eligibility_reason

        return {"eligibility_reason": eligibility_reason(account), "real_send_attempted": False}
    if not challenge_id and not request_id:
        raise ValueError("challenge-id or request-id is required")
    with get_cursor() as cur:
        cur.execute(
            """SELECT t.id,t.request_id,t.state,t.outcome,t.failure_stage,t.failure_reason,
            t.provider_status,t.risk_rule_id,t.provider_ids,t.outcome_unknown,t.retryable,t.provider_called,
            (t.state='processing' AND COALESCE(t.claimed_at,t.created_at)<NOW()-INTERVAL '5 minutes') AS stale_processing,
            c.send_state,c.delivery_status_code,c.delivery_reason_code
            FROM security_delivery_request t LEFT JOIN auth_challenge c ON c.id=t.id
            WHERE t.id::text=%s OR t.request_id=%s ORDER BY t.created_at DESC LIMIT 50""",
            (challenge_id, request_id),
        )
        rows = cur.fetchall()
        # Binding challenges do not need a recovery queue; support them too.
        if not rows and challenge_id:
            cur.execute(
                """SELECT id,send_state,provider_message_ids AS provider_ids,
                delivery_status_code,delivery_reason_code FROM auth_challenge WHERE id::text=%s AND channel='sms'""",
                (challenge_id,),
            )
            rows = cur.fetchall()
        if not rows and request_id:
            cur.execute(
                """SELECT action,details FROM audit_log WHERE request_id=%s
                AND action LIKE 'sms.%' ORDER BY created_at DESC LIMIT 20""",
                (request_id,),
            )
            events = [
                {
                    "event": r["action"],
                    "details": {
                        k: v
                        for k, v in (r["details"] or {}).items()
                        if k in {"rule_id", "risk_rule_id", "decision", "risk_level", "risk_score", "provider_status"}
                    },
                }
                for r in cur.fetchall()
            ]
            return {"tasks": [], "events": events, "status": "prequeue_or_no_task_record"}
    tasks = []
    for row in rows:
        state = row.get("send_state")
        stage = row.get("failure_stage")
        reason = row.get("failure_reason")
        stale = row.get("stale_processing", False)
        if stale:
            stage = "worker"
            reason = "worker_stalled_outcome_unconfirmed"
        tasks.append(
            {
                "task_id": safe_id(row["id"]),
                "challenge_id": safe_id(row["id"]) if state is not None else None,
                "provider_request_id": safe_id(row["id"]) if state is not None else None,
                "request_id": safe_id(row.get("request_id")),
                "task_state": row.get("state"),
                "outcome": row.get("outcome"),
                "failure_stage": stage,
                "failure_reason": reason,
                "risk_rule_id": row.get("risk_rule_id"),
                "provider_status": row.get("delivery_status_code") or row.get("provider_status"),
                "delivery_reason_code": row.get("delivery_reason_code"),
                "provider_request_accepted": True
                if state in {"accepted", "delivered", "delivery_failed"}
                else False
                if state == "rejected"
                else None,
                "final_delivery": "delivered"
                if state == "delivered"
                else "failed"
                if state == "delivery_failed"
                else "not_confirmed",
                "send_state": state,
                "provider_id_digests": [
                    hashlib.sha256(x.encode()).hexdigest()[:24] for x in row.get("provider_ids") or []
                ],
                "outcome_unknown": row.get("outcome_unknown", False) or stale,
                "stale_processing": stale,
                "provider_called": True
                if state in {"accepted", "delivered", "delivery_failed"}
                else None
                if row.get("state") in {"legacy_unknown", "processing"}
                else row.get("provider_called"),
                "recommended_action": _recommend(stage, reason),
            }
        )
    return {"tasks": tasks, "status": "found" if tasks else "not_found"}


def risk_snapshot(*, account=None, phone=None, ip=None, device_id=None, task_id=None):
    """Only GET/TTL operations, never check_request/reserve or counter changes."""
    from modules.security.sms_risk import SmsRiskEngine

    client = redis_client()
    engine = SmsRiskEngine(client)
    try:
        pairs: list[tuple[str, str]] = []
        if phone:
            pairs.extend(
                (label, engine._key(kind, phone))
                for label, kind in [
                    ("SMS_PHONE_COOLDOWN", "cooldown:phone"),
                    ("SMS_PENDING_OUTCOME", "pending_outcome"),
                ]
            )
        if task_id:
            pairs.append(("SMS_DUPLICATE_TASK", engine._key("reservation", task_id)))
        snapshots = []
        for reason, key in pairs:
            value = client.get(key)
            snapshots.append(
                {
                    "reason_code": reason,
                    "present": value is not None,
                    "ttl": client.ttl(key),
                    "reservation_state": json.loads(value).get("state")
                    if value and reason == "SMS_DUPLICATE_TASK"
                    else None,
                }
            )
        day, _ = engine._day()
        sec, micro = client.time()
        now = int(sec) + int(micro) / 1e6
        for kind, value, reason, daily_limit, windows in [
            (
                "phone",
                phone,
                "SMS_PHONE_DAILY_LIMIT",
                settings.SMS_PHONE_LIMIT_DAY,
                [(600, settings.SMS_PHONE_LIMIT_10M), (3600, settings.SMS_PHONE_LIMIT_1H)],
            ),
            (
                "ip",
                ip,
                "SMS_IP_RATE_LIMIT",
                settings.SMS_IP_LIMIT_DAY,
                [(60, settings.SMS_IP_LIMIT_1M), (3600, settings.SMS_IP_LIMIT_1H)],
            ),
            (
                "device",
                device_id,
                "SMS_DEVICE_RATE_LIMIT",
                settings.SMS_DEVICE_LIMIT_DAY,
                [(3600, settings.SMS_DEVICE_LIMIT_1H)],
            ),
            (
                "account",
                account,
                "SMS_ACCOUNT_RATE_LIMIT",
                settings.SMS_ACCOUNT_LIMIT_DAY,
                [(3600, settings.SMS_ACCOUNT_LIMIT_1H)],
            ),
        ]:
            if not value:
                continue
            key = engine._key("quota:" + kind + ":" + day, value)
            snapshots.append(
                {
                    "reason_code": reason,
                    "window": "day",
                    "count": int(client.get(key) or 0),
                    "limit": daily_limit,
                    "ttl": client.ttl(key),
                }
            )
            for window, limit in windows:
                for category in ["send", "request"] if kind != "phone" else ["send"]:
                    key = engine._key(category + ":" + kind + ":" + str(window), value)
                    snapshots.append(
                        {
                            "reason_code": reason,
                            "category": category,
                            "window": window,
                            "count": client.zcount(key, "(" + str(now - window), "+inf"),
                            "limit": limit,
                            "ttl": client.ttl(key),
                        }
                    )
        return {"redis_available": True, "keys": snapshots, "request_counters_mutated": False}
    except Exception as exc:
        return {"redis_available": False, "reason_code": "REDIS_UNAVAILABLE", "error_type": type(exc).__name__}
    finally:
        client.close()


def provider_check():
    """Offline HTTP contract check, explicitly patched so it cannot send."""
    from modules.security.provider import SendCloudSmsProvider, sign_sendcloud_params

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"result":true,"statusCode":200,"info":{"smsIds":["mock-id"]}}'

    with patch("urllib.request.urlopen", return_value=Response()) as request:
        provider = SendCloudSmsProvider("offline-user", "offline-only-key", "1")
        receipt = provider.send_task("138" + "00138000", "000000", "reset_password", send_request_id="offline-check")
        params = {k: v[0] for k, v in parse_qs(request.call_args.args[0].data.decode()).items()}
        signature = params.pop("signature")
        ok = (
            receipt.accepted
            and json.loads(params["vars"]) == {"%code%": "000000"}
            and signature == sign_sendcloud_params(params, "offline-only-key")
        )
    return {
        "contract_ok": ok,
        "real_send_attempted": False,
        "scope": "mock_http_not_delivery",
        "credentials_configured": bool(
            (settings.SENDCLOUD_SMS_USER or settings.SMS_USER) and (settings.SENDCLOUD_SMS_KEY or settings.SMS_KEY)
        ),
        "template_configured": bool(settings.SENDCLOUD_SMS_TEMPLATE_ID),
    }
