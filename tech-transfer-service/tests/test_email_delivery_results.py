"""统一投递回执、结构化任务结果、低基数指标与脱敏事件日志测试。"""

from __future__ import annotations

import logging

from modules.security.delivery_models import (
    DeliveryMetrics,
    DeliveryProviderError,
    DeliveryReceipt,
    DeliveryStageError,
    DeliveryTaskResult,
    ProviderCapabilities,
    ProviderError,
    risk_reason,
    safe_id,
    task_event,
)


def test_delivery_receipt_and_capabilities_contract():
    assert DeliveryProviderError is ProviderError
    caps = ProviderCapabilities(send_otp=True, send_reset_link=False, provider_message_id=True)
    assert caps.to_dict() == {
        "send_otp": True,
        "send_reset_link": False,
        "provider_message_id": True,
        "idempotency": False,
        "delivery_status_query": False,
        "delivery_webhook": False,
    }

    receipt = DeliveryReceipt(
        accepted=True,
        provider="tencent",
        channel="email_otp",
        request_id="req-123",
        provider_message_ids=("mid-1", "mid-2"),
    )
    assert receipt.provider_ids == ("mid-1", "mid-2")


def test_delivery_task_result_queue_state_and_stage_error():
    assert DeliveryTaskResult("t1", "COMPLETED", channel="email_otp").queue_state == "completed"
    assert DeliveryTaskResult("t1", "PROVIDER_REJECTED", channel="email_otp").queue_state == "failed"
    assert DeliveryTaskResult("t1", "COMPLETED", outcome_unknown=True).queue_state == "unknown"
    assert DeliveryTaskResult("t1", "RISK_BLOCKED").queue_state == "blocked"
    assert DeliveryTaskResult("t1", "INELIGIBLE").queue_state == "ineligible"

    err = DeliveryStageError(
        "risk",
        "EMAIL_COOLDOWN",
        risk_rule_id="email.cooldown",
        retry_after=60,
        provider_name="smtp",
    )
    assert err.code == "TT_COMMON_42901"
    assert err.http_status == 429
    assert err.retry_after == 60
    assert err.provider_name == "smtp"

    redis_err = DeliveryStageError("risk", "REDIS_UNAVAILABLE")
    assert redis_err.http_status == 503

    disabled_err = DeliveryStageError("config", "CHANNEL_DISABLED")
    assert disabled_err.http_status == 503


def test_delivery_metrics_low_cardinality_and_safe_log_redaction(caplog):
    m = DeliveryMetrics()
    m.inc(
        "email_request_total",
        channel="email_otp",
        purpose="password_recovery",
        provider="smtp",
        email="pii@example.com",  # 严禁作为低基数标签保留
        user_id="10086",
    )
    m.inc("email_risk_blocked_total", channel="email_otp", rule_id="owner@secret.com")
    m.observe_latency(12.5, channel="email_otp", provider="smtp")
    snap = m.snapshot()

    label_keys = {k for item in snap["counters"]["email_request_total"] for k in item["labels"]}
    assert label_keys == {"channel", "purpose", "provider"}
    assert "pii@example.com" not in str(snap)
    assert "owner@secret.com" not in str(snap)
    assert snap["email_delivery_latency"][0]["count"] == 1.0

    # safe_id 对邮箱、手机号与非法字符执行单向散列脱敏
    assert safe_id("alice@example.com").startswith("sha256:")
    assert safe_id("13800138000").startswith("sha256:")
    assert safe_id("req-abc-123") == "req-abc-123"

    assert risk_reason("email.cooldown") == "EMAIL_COOLDOWN"
    assert risk_reason("email.domain.anomaly_10m") == "EMAIL_DOMAIN_ANOMALY"
    assert risk_reason("email.redis.unavailable") == "REDIS_UNAVAILABLE"

    test_logger = logging.getLogger("nanshan.test.delivery_event")
    res = DeliveryTaskResult(
        task_id="task@pii.com",
        outcome="COMPLETED",
        provider="smtp",
        challenge_id="ch-123",
        channel="email_otp",
        purpose="password_recovery",
        elapsed_ms=15,
    )
    with caplog.at_level(logging.INFO, logger="nanshan.test.delivery_event"):
        task_event(test_logger, res, "req-1", "task_result")
    assert len(caplog.records) == 1
    rec = caplog.records[0]
    assert rec.message == "security.delivery.result"
    assert rec.outcome == "accepted"
    assert rec.task_id.startswith("sha256:")
    assert "pii.com" not in str(rec.__dict__)
