"""Email Security Gateway 只读诊断、脱敏故障分类与运维检查模块。

安全红线：
1. 严禁被公开 HTTP 路由导入或调用；
2. 严禁输出明文邮箱、OTP、Token、Grant、SMTP 密码、SES SecretKey 或含口令的 Redis URL；
3. `email_provider_check()` 仅执行离线合约检查，绝不触发真实邮件发送；
4. `email_risk_snapshot()` 仅执行 GET/TTL/ZCOUNT 只读查询，绝不修改任何限流计数。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import smtplib
import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from config import settings, validate_frontend_reset_base_url
from core.contact_validation import normalize_email
from core.errors import BizError
from db import get_cursor
from modules.security.delivery_models import metrics, safe_id
from modules.security.eligibility import EMAIL_ELIGIBLE_SQL, email_eligibility_reason

FAILURE_EXPLANATIONS: dict[str, dict[str, object]] = {
    "CONFIG_ERROR": {
        "category": "configuration",
        "summary": "邮件服务商或关键配置缺失/不合法（如未知 EMAIL_PROVIDER、非生产安全域名或认证参数不完整）",
        "retry_safe": False,
        "recommended_action": "check_email_provider_and_frontend_url_configuration",
    },
    "CHANNEL_DISABLED": {
        "category": "policy",
        "summary": "系统当前通过 EMAIL_ENABLED=false 关闭了安全邮件发送通道",
        "retry_safe": False,
        "recommended_action": "enable_email_channel_after_provider_and_redis_verification",
    },
    "INELIGIBLE_ACCOUNT": {
        "category": "eligibility",
        "summary": "目标账号不存在、已禁用/删除、未配置密码或属于管理员受限账号",
        "retry_safe": False,
        "recommended_action": "verify_account_status_or_use_audited_manual_recovery",
    },
    "CONTACT_NOT_VERIFIED": {
        "category": "eligibility",
        "summary": "账号未绑定通过安全确权验证的活跃邮箱（普通资料邮箱不具备找回资格）",
        "retry_safe": False,
        "recommended_action": "complete_verified_email_binding_in_security_center",
    },
    "RISK_BLOCKED": {
        "category": "risk_control",
        "summary": "触发邮箱多维风控限制（冷却期、IP/设备/账号/目标邮箱频率或不同邮箱数超限）",
        "retry_safe": False,
        "recommended_action": "inspect_risk_snapshot_and_ttl_do_not_bypass_limits",
    },
    "REDIS_UNAVAILABLE": {
        "category": "dependency",
        "summary": "Redis 不可用或 Lua 脚本执行异常，安全网关按 Fail-Closed 策略拒绝发送",
        "retry_safe": True,
        "recommended_action": "restore_redis_connectivity_and_verify_lua_support",
    },
    "CHALLENGE_CREATE_FAILED": {
        "category": "database",
        "summary": "写入 auth_challenge 事务失败，已自动释放风控预占配额",
        "retry_safe": True,
        "recommended_action": "check_postgres_connectivity_schema_and_locks",
    },
    "SMTP_CONNECTION_FAILED": {
        "category": "provider_transport",
        "summary": "连接 SMTP 服务器失败或连接握手前网络中断",
        "retry_safe": True,
        "recommended_action": "check_smtp_host_port_firewall_and_dns",
    },
    "SMTP_TLS_FAILED": {
        "category": "provider_tls",
        "summary": "SMTP SSL/STARTTLS 握手或服务端证书/主机名校验失败",
        "retry_safe": False,
        "recommended_action": "verify_smtp_certificate_chain_and_tls_port",
    },
    "SMTP_AUTH_FAILED": {
        "category": "provider_auth",
        "summary": "SMTP 发信账号或授权密码被邮件服务器拒绝（534/535）",
        "retry_safe": False,
        "recommended_action": "rotate_smtp_app_password_or_verify_sender_account",
    },
    "SMTP_RECIPIENT_REJECTED": {
        "category": "provider_recipient",
        "summary": "SMTP 明确拒绝收件地址（邮箱不存在、域拒收或策略拦截）",
        "retry_safe": False,
        "recommended_action": "verify_recipient_address_and_domain_mx_records",
    },
    "SMTP_TEMPORARY_FAILURE": {
        "category": "provider_temporary",
        "summary": "SMTP 返回 4xx 临时拒绝状态（限流或灰名单）",
        "retry_safe": True,
        "recommended_action": "respect_provider_rate_limits_and_avoid_burst_retries",
    },
    "SMTP_PERMANENT_FAILURE": {
        "category": "provider_permanent",
        "summary": "SMTP 返回 5xx 永久拒绝状态（发信权限、内容规则或发件人对齐错误）",
        "retry_safe": False,
        "recommended_action": "check_spf_dkim_sender_alignment_and_provider_policy",
    },
    "SES_SIGNATURE_ERROR": {
        "category": "provider_auth",
        "summary": "腾讯云 SES TC3 签名或密钥校验失败（检查系统时钟与 SecretId/SecretKey）",
        "retry_safe": False,
        "recommended_action": "verify_tencent_ses_credentials_and_ntp_clock_sync",
    },
    "SES_PERMISSION_ERROR": {
        "category": "provider_auth",
        "summary": "腾讯云 SES CAM 权限不足或发信域名/地址未完成认证审核",
        "retry_safe": False,
        "recommended_action": "verify_cam_policy_and_ses_sender_identity_status",
    },
    "SES_QUOTA_EXCEEDED": {
        "category": "provider_quota",
        "summary": "腾讯云 SES 配额不足、触发频率上限或命中收件限制",
        "retry_safe": False,
        "recommended_action": "inspect_ses_quota_and_blacklist_in_cloud_console",
    },
    "SES_INVALID_RESPONSE": {
        "category": "provider_protocol",
        "summary": "腾讯云 SES 返回非预期 JSON 结构或缺失 MessageId，结果按未知保守处理",
        "retry_safe": False,
        "recommended_action": "inspect_ses_request_id_and_do_not_blindly_resend",
    },
    "PROVIDER_OUTCOME_UNKNOWN": {
        "category": "provider_unknown",
        "summary": "投递请求在 DATA 提交后断连、超时或上游返回 5xx，无法确认邮件是否已入队发送，严禁盲目重发",
        "retry_safe": False,
        "recommended_action": "reconcile_provider_logs_and_let_user_use_existing_otp_or_wait_ttl",
    },
    "RECEIPT_PERSIST_FAILED": {
        "category": "database",
        "summary": "服务商调用后回写 auth_challenge 回执失败，保留未知状态以防重复派发",
        "retry_safe": False,
        "recommended_action": "inspect_postgres_health_and_reconcile_challenge_state",
    },
    "DELIVERY_TASK_EXPIRED": {
        "category": "queue",
        "summary": "持久化队列任务超过 5 分钟有效期仍未被领取，已过期终止（未触发发信）",
        "retry_safe": True,
        "recommended_action": "check_worker_schedule_and_queue_backlog",
    },
}


def _redis_client():
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


def authorized_live_email_target(account: str, email: str) -> bool:
    """要求操作员显式指定的测试目标必须与数据库已确权邮箱精确匹配。"""
    norm = normalize_email(email)
    with get_cursor() as cur:
        cur.execute(EMAIL_ELIGIBLE_SQL, (account, account, account))
        rows = cur.fetchall()
    return len(rows) == 1 and hmac.compare_digest(normalize_email(rows[0]["normalized_value"]), norm)


def email_redis_check() -> dict:
    start = time.monotonic()
    try:
        client = _redis_client()
        try:
            ping_ok = bool(client.ping())
            lua_ok = client.eval("return 1", 0) == 1
        finally:
            client.close()
        return {
            "connected": True,
            "ping": ping_ok,
            "lua": lua_ok,
            "latency_ms": round((time.monotonic() - start) * 1000.0, 2),
        }
    except Exception as exc:
        return {
            "connected": False,
            "ping": False,
            "lua": False,
            "error_type": type(exc).__name__,
            "reason_code": "REDIS_UNAVAILABLE",
        }


def email_config_check() -> dict:
    fields = [
        "APP_ENV",
        "EMAIL_ENABLED",
        "EMAIL_PROVIDER",
        "REDIS_ENABLED",
        "EMAIL_RISK_ENGINE_ENABLED",
        "EMAIL_REQUIRE_VERIFIED_CONTACT",
        "EMAIL_SECURITY_NOTIFICATION_ENABLED",
        "EMAIL_LIVE_TEST_ENABLED",
        "SMTP_PORT",
        "SMTP_USE_SSL",
        "SMTP_TIMEOUT_SECONDS",
        "SMTP_MAX_ATTEMPTS",
        "TENCENT_SES_REGION",
        "TENCENT_SES_ENDPOINT",
        "EMAIL_CODE_TTL_SECONDS",
        "EMAIL_LINK_TTL_SECONDS",
        "EMAIL_CODE_MAX_ATTEMPTS",
    ]
    frontend_valid = True
    frontend_error = None
    try:
        validate_frontend_reset_base_url(settings.FRONTEND_URL, production_like=settings.is_production_like)
    except ValueError as exc:
        frontend_valid = False
        frontend_error = str(exc)

    result: dict[str, object] = {
        "scope": "read_only_config_and_dependency_check",
        "settings": {k: getattr(settings, k) for k in fields},
        "configured": {
            "SMTP_HOST": bool(settings.SMTP_HOST),
            "SMTP_USER": bool(settings.SMTP_USER),
            "SMTP_PASSWORD": bool(settings.SMTP_PASSWORD),
            "SMTP_FROM_EMAIL": bool(settings.SMTP_FROM_EMAIL),
            "TENCENT_SES_SECRET_ID": bool(settings.TENCENT_SES_SECRET_ID),
            "TENCENT_SES_SECRET_KEY": bool(settings.TENCENT_SES_SECRET_KEY),
            "TENCENT_SES_FROM_EMAIL": bool(settings.TENCENT_SES_FROM_EMAIL),
            "SECURITY_OTP_HMAC_SECRET": bool(settings.SECURITY_OTP_HMAC_SECRET),
            "SECURITY_CONTACT_HMAC_SECRET": bool(settings.SECURITY_CONTACT_HMAC_SECRET),
            "EMAIL_RISK_HMAC_SECRET": bool(settings.EMAIL_RISK_HMAC_SECRET),
        },
        "frontend_reset_url": {
            "valid": frontend_valid,
            "scheme": urlsplit(settings.FRONTEND_URL).scheme,
            "error": frontend_error,
        },
        "redis": email_redis_check(),
    }
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT table_name, column_name FROM information_schema.columns
                WHERE table_schema='public'
                  AND table_name IN ('security_delivery_request','auth_challenge','account_contact','step_up_grant')"""
            )
            columns = {(r["table_name"], r["column_name"]) for r in cur.fetchall()}
        required = {
            ("account_contact", "verification_method"),
            ("auth_challenge", "send_state"),
            ("auth_challenge", "code_hash_version"),
            ("auth_challenge", "provider_name"),
            ("security_delivery_request", "channel"),
            ("security_delivery_request", "outcome"),
            ("step_up_grant", "grant_hash"),
        }
        result["postgres"] = {
            "connected": True,
            "migration_036_ready": required <= columns,
            "missing_columns": sorted(".".join(x) for x in required - columns),
        }
    except Exception as exc:
        result["postgres"] = {"connected": False, "error_type": type(exc).__name__}
    return result


def email_provider_check() -> dict:
    """离线邮件 Provider 协议合约自检（绝不连接真实 SMTP 或腾讯云网络）。"""
    from modules.security.email_providers import SmtpEmailProvider, TencentSesProvider

    smtp_ok = False
    with patch.object(smtplib, "SMTP_SSL") as mock_ssl:
        mock_ssl.return_value.sendmail.return_value = {}
        smtp = SmtpEmailProvider(
            host="smtp.example.com",
            port=465,
            user="noreply@example.com",
            password="offline-only-password",
            use_ssl=True,
            max_attempts=1,
        )
        smtp_receipt = smtp.send_code_task(
            "check@example.com",
            "001234",
            "password_recovery",
            300,
            send_request_id="offline-smtp-check",
        )
        smtp_ok = (
            smtp_receipt.accepted
            and smtp_receipt.provider == "smtp"
            and bool(smtp_receipt.provider_message_ids)
            and mock_ssl.called
        )

    class _SesResponse:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def read(self):
            return b'{"Response":{"MessageId":"offline-ses-msg-1","RequestId":"offline-ses-req-1"}}'

    ses_ok = False
    with patch("urllib.request.urlopen", return_value=_SesResponse()) as mock_url:
        ses = TencentSesProvider(
            secret_id="offline-id",
            secret_key="offline-key",
            from_email="noreply@example.com",
            region="ap-hongkong",
        )
        ses_receipt = ses.send_code_task(
            "check@example.com",
            "001234",
            "password_recovery",
            300,
            send_request_id="offline-ses-check",
        )
        req = mock_url.call_args.args[0]
        body = json.loads(req.data.decode("utf-8"))
        ses_ok = (
            ses_receipt.accepted
            and ses_receipt.provider == "tencent"
            and ses_receipt.provider_message_ids == ("offline-ses-msg-1",)
            and req.headers.get("X-tc-region") == "ap-hongkong"
            and req.headers.get("X-tc-version") == "2020-10-02"
            and "Html" in (body.get("Simple") or {})
            and "Text" in (body.get("Simple") or {})
        )

    provider_type = (settings.EMAIL_PROVIDER or "").strip().lower()
    return {
        "real_send_attempted": False,
        "scope": "offline_contract_check_not_live_delivery",
        "smtp_contract_ok": smtp_ok,
        "ses_contract_ok": ses_ok,
        "active_provider": provider_type,
        "email_enabled": bool(settings.EMAIL_ENABLED),
        "credentials_configured": (
            bool(settings.SMTP_HOST and settings.SMTP_USER and settings.SMTP_PASSWORD)
            if provider_type == "smtp"
            else bool(
                settings.TENCENT_SES_SECRET_ID
                and settings.TENCENT_SES_SECRET_KEY
                and settings.TENCENT_SES_FROM_EMAIL
                and settings.TENCENT_SES_REGION
            )
            if provider_type == "tencent"
            else False
        ),
    }


def email_explain_failure(code: str) -> dict:
    key = (code or "").strip().upper()
    if key in FAILURE_EXPLANATIONS:
        return {"reason_code": key, "known": True, **FAILURE_EXPLANATIONS[key]}
    # 兼容小写或等价编码
    alias = {
        "QUEUED_REQUEST_EXPIRED": "DELIVERY_TASK_EXPIRED",
        "WORKER_INTERRUPTED": "PROVIDER_OUTCOME_UNKNOWN",
        "DATABASE_WRITE_FAILED": "RECEIPT_PERSIST_FAILED",
        "EMAIL_RISK_BLOCKED": "RISK_BLOCKED",
        "EMAIL_COOLDOWN": "RISK_BLOCKED",
        "EMAIL_DAILY_LIMIT": "RISK_BLOCKED",
        "EMAIL_IP_RATE_LIMIT": "RISK_BLOCKED",
        "EMAIL_DEVICE_RATE_LIMIT": "RISK_BLOCKED",
        "EMAIL_ACCOUNT_RATE_LIMIT": "RISK_BLOCKED",
        "EMAIL_GLOBAL_BUDGET": "RISK_BLOCKED",
        "EMAIL_DOMAIN_ANOMALY": "RISK_BLOCKED",
        "EMAIL_PENDING_OUTCOME": "PROVIDER_OUTCOME_UNKNOWN",
    }.get(key)
    if alias and alias in FAILURE_EXPLANATIONS:
        return {"reason_code": key, "mapped_to": alias, "known": True, **FAILURE_EXPLANATIONS[alias]}
    return {
        "reason_code": key,
        "known": False,
        "category": "unknown",
        "summary": "未收录的诊断错误码，请结合服务端结构化日志与审计事件排查",
        "retry_safe": False,
        "recommended_action": "inspect_server_logs_and_audit_events",
    }


def email_inspect_delivery(*, challenge_id: str | None = None, request_id: str | None = None) -> dict:
    if not challenge_id and not request_id:
        raise ValueError("challenge-id or request-id is required")
    with get_cursor() as cur:
        cur.execute(
            """SELECT t.id, t.request_id, t.state, t.outcome, t.failure_stage, t.failure_reason,
               t.provider_status, t.risk_rule_id, t.provider_ids, t.outcome_unknown, t.retryable,
               t.provider_called, t.elapsed_ms,
               (t.state='processing' AND COALESCE(t.claimed_at,t.created_at)<NOW()-INTERVAL '5 minutes') AS stale_processing,
               c.channel, c.purpose, c.status AS challenge_status, c.send_state,
               c.delivery_status_code, c.delivery_reason_code
            FROM security_delivery_request t
            LEFT JOIN auth_challenge c ON c.id = t.id
            WHERE t.id::text = %s OR t.request_id = %s
            ORDER BY t.created_at DESC LIMIT 50""",
            (challenge_id, request_id),
        )
        rows = cur.fetchall()
        if not rows and challenge_id:
            cur.execute(
                """SELECT id, channel, purpose, status AS challenge_status, send_state,
                   provider_message_ids AS provider_ids, delivery_status_code, delivery_reason_code
                FROM auth_challenge
                WHERE id::text = %s AND channel IN ('email_otp','email_link')""",
                (challenge_id,),
            )
            rows = cur.fetchall()
        if not rows and request_id:
            cur.execute(
                """SELECT action, details FROM audit_log WHERE request_id=%s
                AND (action LIKE 'email.%' OR action LIKE 'recovery.%')
                ORDER BY created_at DESC LIMIT 20""",
                (request_id,),
            )
            events = [
                {
                    "event": r["action"],
                    "details": {
                        k: v
                        for k, v in (r["details"] or {}).items()
                        if k
                        in {
                            "rule_id",
                            "risk_rule_id",
                            "decision",
                            "risk_level",
                            "risk_score",
                            "provider_status",
                            "reason_code",
                        }
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
        stale = bool(row.get("stale_processing", False))
        if stale:
            stage = "worker"
            reason = "PROVIDER_OUTCOME_UNKNOWN"
        explain = email_explain_failure(str(reason or "")) if reason else None
        tasks.append(
            {
                "task_id": safe_id(row["id"]),
                "challenge_id": safe_id(row["id"]) if row.get("challenge_status") is not None else None,
                "request_id": safe_id(row.get("request_id")),
                "channel": row.get("channel"),
                "purpose": row.get("purpose"),
                "task_state": row.get("state"),
                "challenge_status": row.get("challenge_status"),
                "send_state": state,
                "outcome": row.get("outcome"),
                "failure_stage": stage,
                "failure_reason": reason,
                "risk_rule_id": row.get("risk_rule_id"),
                "provider_status": row.get("delivery_status_code") or row.get("provider_status"),
                "delivery_reason_code": row.get("delivery_reason_code"),
                "provider_id_digests": [
                    hashlib.sha256(str(x).encode("utf-8")).hexdigest()[:24] for x in (row.get("provider_ids") or [])
                ],
                "provider_request_accepted": True
                if state in {"accepted", "delivered", "bounced", "delivery_failed"}
                else False
                if state == "rejected"
                else None,
                "final_delivery": "delivered"
                if state == "delivered"
                else "failed"
                if state in {"bounced", "delivery_failed"}
                else "not_confirmed",
                "outcome_unknown": bool(row.get("outcome_unknown", False)) or stale,
                "stale_processing": stale,
                "recommended_action": explain["recommended_action"] if explain else "await_or_reconcile_final_receipt",
            }
        )
    return {"tasks": tasks, "status": "found" if tasks else "not_found"}


def email_inspect_challenge(*, challenge_id: str | None = None, account: str | None = None) -> dict:
    if account is not None:
        return {"eligibility_reason": email_eligibility_reason(account), "real_send_attempted": False}
    if not challenge_id:
        raise ValueError("challenge-id or account is required")
    with get_cursor() as cur:
        cur.execute(
            """SELECT id, purpose, channel, status, send_state, attempt_count, max_attempts,
               expires_at, consumed_at, delivery_status_code, delivery_reason_code, created_at
            FROM auth_challenge WHERE id::text = %s""",
            (challenge_id,),
        )
        row = cur.fetchone()
    if not row:
        return {"status": "not_found", "challenge": None}
    return {
        "status": "found",
        "challenge": {
            "challenge_id": safe_id(row["id"]),
            "purpose": row["purpose"],
            "channel": row["channel"],
            "status": row["status"],
            "send_state": row.get("send_state"),
            "attempt_count": row["attempt_count"],
            "max_attempts": row["max_attempts"],
            "expired": row["expires_at"].isoformat()
            if hasattr(row["expires_at"], "isoformat")
            else str(row["expires_at"]),
            "consumed": row["consumed_at"] is not None,
            "delivery_status_code": row.get("delivery_status_code"),
            "delivery_reason_code": row.get("delivery_reason_code"),
        },
    }


def email_risk_snapshot(
    *,
    account: str | None = None,
    email: str | None = None,
    ip: str | None = None,
    device_id: str | None = None,
    task_id: str | None = None,
) -> dict:
    """只读查询邮箱风控状态与剩余 TTL，绝不写入或消耗任何额度。"""
    from modules.security.email_risk import EmailRiskEngine

    client = _redis_client()
    engine = EmailRiskEngine(client)
    norm_email: str | None = None
    if email:
        try:
            norm_email = normalize_email(email)
        except BizError:
            norm_email = email.strip().lower()
    try:
        pairs = []
        if norm_email:
            pairs.extend(
                [
                    ("EMAIL_COOLDOWN", engine._key("cooldown:email", norm_email)),
                    ("EMAIL_PENDING_OUTCOME", engine._key("pending_outcome", norm_email)),
                ]
            )
        if task_id:
            pairs.append(("EMAIL_DUPLICATE_TASK", engine._key("reservation", task_id)))

        snapshots = []
        for reason, key in pairs:
            value = client.get(key)
            snapshots.append(
                {
                    "reason_code": reason,
                    "present": value is not None,
                    "ttl": client.ttl(key),
                    "reservation_state": json.loads(value).get("state")
                    if value and reason == "EMAIL_DUPLICATE_TASK"
                    else None,
                }
            )

        day, _ = engine._day()
        sec, micro = client.time()
        now = int(sec) + int(micro) / 1e6
        for kind, value, reason, daily_limit, windows in [
            (
                "email",
                norm_email,
                "EMAIL_DAILY_LIMIT",
                settings.EMAIL_LIMIT_DAY,
                [(600, settings.EMAIL_LIMIT_10M), (3600, settings.EMAIL_LIMIT_1H)],
            ),
            (
                "ip",
                ip,
                "EMAIL_IP_RATE_LIMIT",
                settings.EMAIL_IP_LIMIT_DAY,
                [(60, settings.EMAIL_IP_LIMIT_1M), (3600, settings.EMAIL_IP_LIMIT_1H)],
            ),
            (
                "device",
                device_id,
                "EMAIL_DEVICE_RATE_LIMIT",
                settings.EMAIL_DEVICE_LIMIT_DAY,
                [(3600, settings.EMAIL_DEVICE_LIMIT_1H)],
            ),
            (
                "account",
                account,
                "EMAIL_ACCOUNT_RATE_LIMIT",
                settings.EMAIL_ACCOUNT_LIMIT_DAY,
                [(3600, settings.EMAIL_ACCOUNT_LIMIT_1H)],
            ),
        ]:
            if not value:
                continue
            key = engine._key(f"quota:{kind}:{day}", value)
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
                for category in ["send", "request"] if kind != "email" else ["send"]:
                    wkey = engine._key(f"{category}:{kind}:{window}", value)
                    snapshots.append(
                        {
                            "reason_code": reason,
                            "category": category,
                            "window": window,
                            "count": client.zcount(wkey, "(" + str(now - window), "+inf"),
                            "limit": limit,
                            "ttl": client.ttl(wkey),
                        }
                    )

        global_key = engine._key(f"quota:global:{day}", "all")
        snapshots.append(
            {
                "reason_code": "EMAIL_GLOBAL_BUDGET",
                "window": "day",
                "count": int(client.get(global_key) or 0),
                "limit": settings.EMAIL_GLOBAL_DAILY_BUDGET,
                "ttl": client.ttl(global_key),
            }
        )
        return {"redis_available": True, "keys": snapshots, "request_counters_mutated": False}
    except Exception as exc:
        return {"redis_available": False, "reason_code": "REDIS_UNAVAILABLE", "error_type": type(exc).__name__}
    finally:
        client.close()


def email_queue_check() -> dict:
    with get_cursor() as cur:
        cur.execute(
            """SELECT state, COUNT(*) AS count FROM security_delivery_request
            WHERE COALESCE(channel, payload->>'channel') IN ('email_otp','email_link')
            GROUP BY state"""
        )
        states = {r["state"]: r["count"] for r in cur.fetchall()}
        cur.execute(
            """SELECT COUNT(*) AS count FROM security_delivery_request
            WHERE state='processing'
              AND COALESCE(channel, payload->>'channel') IN ('email_otp','email_link')
              AND COALESCE(claimed_at, created_at) < NOW() - INTERVAL '5 minutes'"""
        )
        stale = cur.fetchone()["count"]
        cur.execute(
            """SELECT failure_stage, COUNT(*) AS count FROM security_delivery_request
            WHERE failure_stage IS NOT NULL
              AND COALESCE(channel, payload->>'channel') IN ('email_otp','email_link')
              AND created_at > NOW() - INTERVAL '1 day'
            GROUP BY failure_stage"""
        )
        stages = {r["failure_stage"]: r["count"] for r in cur.fetchall()}
    return {
        "states": states,
        "email_queue_pending": int(states.get("queued", 0)),
        "email_queue_failed": int(states.get("failed", 0)) + int(states.get("failed_internal", 0)),
        "stale_processing": stale,
        "recent_failure_stages": stages,
        "metrics": metrics.snapshot(),
    }


def email_cleanup_expired(*, dry_run: bool = True) -> dict:
    """查看或清理过期挑战、授权与投递队列记录；默认只读 dry_run=True。"""
    if dry_run:
        with get_cursor() as cur:
            cur.execute(
                """SELECT COUNT(*) AS count FROM auth_challenge
                WHERE status IN ('pending_send','pending') AND expires_at <= NOW()"""
            )
            expired_challenges = cur.fetchone()["count"]
            cur.execute("SELECT COUNT(*) AS count FROM recovery_grant WHERE status='active' AND expires_at <= NOW()")
            expired_recovery = cur.fetchone()["count"]
            cur.execute(
                """SELECT COUNT(*) AS count FROM security_delivery_request
                WHERE created_at < NOW() - INTERVAL '7 days'"""
            )
            old_tasks = cur.fetchone()["count"]
            expired_stepup = 0
            try:
                cur.execute("SELECT COUNT(*) AS count FROM step_up_grant WHERE status='active' AND expires_at <= NOW()")
                expired_stepup = cur.fetchone()["count"]
            except Exception:
                pass
        return {
            "dry_run": True,
            "expired_challenges": expired_challenges,
            "expired_recovery_grants": expired_recovery,
            "expired_step_up_grants": expired_stepup,
            "expired_queue_rows_7d": old_tasks,
        }

    from modules.security.sms_gateway import cleanup_delivery_tasks

    cleanup_delivery_tasks()
    return {"dry_run": False, "cleaned": True}


def format_parse_qs(query: str) -> dict[str, list[str]]:
    return parse_qs(query)
