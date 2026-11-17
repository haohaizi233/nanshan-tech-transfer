"""Internal delivery results. Public recovery responses never expose these."""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass

from modules.security.provider import ProviderError


@dataclass(frozen=True)
class DeliveryTaskResult:
    task_id: str
    outcome: str
    failure_stage: str | None = None
    failure_reason: str | None = None
    provider_status: int | None = None
    provider_ids: tuple[str, ...] = ()
    retryable: bool = False
    outcome_unknown: bool = False
    risk_rule_id: str | None = None
    provider_called: bool = False
    challenge_id: str | None = None
    elapsed_ms: int = 0

    @property
    def queue_state(self):
        if self.outcome_unknown:
            return "unknown"
        return {
            "COMPLETED": "completed",
            "INELIGIBLE": "ineligible",
            "RISK_BLOCKED": "blocked",
            "CONFIG_ERROR": "config_error",
            "PROVIDER_REJECTED": "failed",
            "PROVIDER_UNKNOWN": "unknown",
            "DELIVERY_FAILED": "failed",
            "INTERNAL_ERROR": "failed_internal",
        }[self.outcome]


class DeliveryStageError(ProviderError):
    def __init__(
        self,
        stage,
        reason,
        *,
        risk_rule_id=None,
        provider_status=None,
        provider_ids=(),
        outcome_unknown=False,
        provider_called=False,
        retryable=False,
    ):
        super().__init__("验证服务暂时不可用，请稍后重试", outcome_unknown=outcome_unknown)
        self.stage = stage
        self.reason_code = reason
        self.risk_rule_id = risk_rule_id
        self.provider_status = provider_status
        self.provider_ids = tuple(provider_ids)
        self.request_attempted = provider_called
        self.retryable = retryable
        if stage == "risk":
            self.code = "TT_COMMON_42901"
            self.http_status = 503 if reason == "REDIS_UNAVAILABLE" else 429


def risk_reason(rule):
    if "redis" in rule:
        return "REDIS_UNAVAILABLE"
    if "pending_outcome" in rule:
        return "SMS_PENDING_OUTCOME"
    if "duplicate" in rule:
        return "SMS_DUPLICATE_TASK"
    if "cooldown" in rule:
        return "SMS_PHONE_COOLDOWN"
    if rule == "sms.phone.day":
        return "SMS_PHONE_DAILY_LIMIT"
    if "device" in rule:
        return "SMS_DEVICE_RATE_LIMIT"
    if ".ip." in rule:
        return "SMS_IP_RATE_LIMIT"
    return "SMS_RISK_BLOCKED"


def safe_id(value):
    value = str(value or "")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,96}", value) or re.search(r"1[3-9][0-9]{9}", value):
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()[:24]
    return value


def task_event(logger: logging.Logger, result: DeliveryTaskResult, request_id, event, exception_type=None):
    fields = {
        "request_id": safe_id(request_id),
        "task_id": safe_id(result.task_id),
        "challenge_id": safe_id(result.challenge_id) if result.challenge_id else None,
        "stage": result.failure_stage or "provider_accepted",
        "event": event,
        "reason_code": result.failure_reason,
        "provider_status": result.provider_status,
        "risk_rule_id": result.risk_rule_id,
        "elapsed_ms": result.elapsed_ms,
        "outcome": result.outcome,
        "outcome_unknown": result.outcome_unknown,
        "provider_called": result.provider_called,
        "exception_type": exception_type,
    }
    logger.log(
        logging.INFO if result.outcome == "COMPLETED" else logging.WARNING, "SMS delivery task event", extra=fields
    )
