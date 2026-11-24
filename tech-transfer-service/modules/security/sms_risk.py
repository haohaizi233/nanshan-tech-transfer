"""Atomic SMS request frequency and cost reservations. Redis failure closes sends.

Builds on shared `modules.security.risk_engine.BaseRiskEngine` while preserving
100% of existing SMS rule IDs, Redis keys, and SmsRiskEngine signatures.
"""

from __future__ import annotations

from functools import lru_cache

from modules.security.risk_engine import (
    REQUEST_LUA,
    RESERVE_LUA,
    TRANSITION_LUA,
    BaseRiskEngine,
    DecisionAction,
    RiskDecision,
    day_bucket,
)


class SmsRiskEngine(BaseRiskEngine):
    def __init__(self, redis_client=None, secret=None, config=None, prefix="sms:{gateway}:"):
        if config is None:
            from config import settings as config
        effective_secret = secret or config.SMS_RISK_HMAC_SECRET or config.JWT_SECRET
        super().__init__(redis_client=redis_client, secret=effective_secret, config=config, prefix=prefix)

    def check_request(self, ip, account, device_id, phone=None, purpose="reset_password"):
        if not self.config.SMS_RISK_ENGINE_ENABLED:
            return RiskDecision(DecisionAction.DENY, "sms.risk.disabled")
        if purpose not in {"reset_password", "bind_phone"}:
            return RiskDecision(DecisionAction.DENY, "sms.purpose.disabled")
        if self._is_dev_bypass_allowed():
            return RiskDecision(DecisionAction.ALLOW, "sms.allow.dev_mode")
        try:
            day, ttl = self._day()
            rates = []
            distinct = []
            c = self.config

            def rate(kind, value, window, limit):
                rates.append(
                    {
                        "key": self._key("request:" + kind + ":" + str(window), value),
                        "window": window,
                        "limit": limit,
                        "rule": "sms.request." + kind + "." + str(window),
                        "action": "THROTTLE",
                    }
                )

            def daily(kind, value, limit):
                rates.append(
                    {
                        "key": self._key("request:" + kind + ":day:" + day, value),
                        "daily": True,
                        "ttl": ttl,
                        "limit": limit,
                        "rule": "sms.request." + kind + ".day",
                        "action": "THROTTLE",
                    }
                )

            rate("ip", ip, 60, c.SMS_IP_LIMIT_1M)
            rate("ip", ip, 3600, c.SMS_IP_LIMIT_1H)
            daily("ip", ip, c.SMS_IP_LIMIT_DAY)
            rate("account", account, 3600, c.SMS_ACCOUNT_LIMIT_1H)
            daily("account", account, c.SMS_ACCOUNT_LIMIT_DAY)
            if device_id:
                rate("device", device_id, 3600, c.SMS_DEVICE_LIMIT_1H)
                daily("device", device_id, c.SMS_DEVICE_LIMIT_DAY)
            if phone:
                distinct = self._distinct(ip, device_id, phone)
            return self._eval(REQUEST_LUA, {"allow_rule": "sms.allow", "rates": rates, "distinct": distinct})
        except Exception:
            return RiskDecision(DecisionAction.DENY, "sms.redis.unavailable")

    def _distinct(self, ip, device_id, phone):
        c = self.config
        out = [
            {
                "key": self._key("distinct:ip:phone", ip),
                "value": self._digest("phone", phone),
                "window": 3600,
                "limit": c.SMS_IP_DISTINCT_PHONE_LIMIT_1H,
                "rule": "sms.ip.distinct_phone",
            }
        ]
        if device_id:
            out.append(
                {
                    "key": self._key("distinct:device:phone", device_id),
                    "value": self._digest("phone", phone),
                    "window": 600,
                    "limit": c.SMS_DEVICE_DISTINCT_PHONE_LIMIT_10M,
                    "rule": "sms.device.distinct_phone",
                }
            )
        return out

    def reserve(self, phone, account, ip, device_id, reservation_id):
        if not self.config.SMS_RISK_ENGINE_ENABLED or not self.config.SMS_REQUIRE_VERIFIED_CONTACT:
            return RiskDecision(DecisionAction.DENY, "sms.policy.disabled")
        if self._is_dev_bypass_allowed():
            return RiskDecision(DecisionAction.ALLOW, "sms.quota.dev_mode")
        try:
            day, ttl = self._day()
            c = self.config
            cooldowns = [
                {
                    "key": self._key("cooldown:phone", phone),
                    "ttl": c.SMS_PHONE_COOLDOWN_SECONDS,
                    "rule": "sms.phone.cooldown",
                },
                {
                    "key": self._key("cooldown:pair", ip + ":" + phone),
                    "ttl": c.SMS_PHONE_COOLDOWN_SECONDS,
                    "rule": "sms.pair.cooldown",
                },
            ]
            rates = []
            for kind, value, window, limit in [
                ("phone", phone, 600, c.SMS_PHONE_LIMIT_10M),
                ("phone", phone, 3600, c.SMS_PHONE_LIMIT_1H),
                ("account", account, 3600, c.SMS_ACCOUNT_LIMIT_1H),
                ("ip", ip, 60, c.SMS_IP_LIMIT_1M),
                ("ip", ip, 3600, c.SMS_IP_LIMIT_1H),
                *([("device", device_id, 3600, c.SMS_DEVICE_LIMIT_1H)] if device_id else []),
            ]:
                rates.append(
                    {
                        "key": self._key("send:" + kind + ":" + str(window), value),
                        "window": window,
                        "limit": limit,
                        "rule": "sms.send." + kind + "." + str(window),
                    }
                )
            budgets = [
                {
                    "key": self._key("quota:phone:" + day, phone),
                    "limit": c.SMS_PHONE_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "sms.phone.day",
                },
                {
                    "key": self._key("quota:account:" + day, account),
                    "limit": c.SMS_ACCOUNT_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "sms.account.day",
                },
                {
                    "key": self._key("quota:ip:" + day, ip),
                    "limit": c.SMS_IP_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "sms.ip.day",
                },
            ]
            if device_id:
                budgets.append(
                    {
                        "key": self._key("quota:device:" + day, device_id),
                        "limit": c.SMS_DEVICE_LIMIT_DAY,
                        "ttl": ttl,
                        "rule": "sms.device.day",
                    }
                )
            return self._eval(
                RESERVE_LUA,
                {
                    "dup_rule": "sms.task.duplicate",
                    "pending_rule": "sms.phone.pending_outcome",
                    "ok_rule": "sms.quota.reserved",
                    "reservation": self._key("reservation", reservation_id),
                    "uncertainty": self._key("pending_outcome", phone),
                    "uncertainty_ttl": c.SMS_CODE_TTL_SECONDS,
                    "rates": rates,
                    "cooldowns": cooldowns,
                    "budgets": budgets,
                    "distinct": self._distinct(ip, device_id, phone),
                },
            )
        except Exception:
            return RiskDecision(DecisionAction.DENY, "sms.redis.unavailable")

    def transition(self, reservation_id, state):
        return self._transition_key(reservation_id, state)


@lru_cache(maxsize=1)
def get_sms_risk_engine():
    return SmsRiskEngine()


__all__ = [
    "REQUEST_LUA",
    "RESERVE_LUA",
    "TRANSITION_LUA",
    "DecisionAction",
    "RiskDecision",
    "SmsRiskEngine",
    "day_bucket",
    "get_sms_risk_engine",
]
