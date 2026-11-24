"""邮箱渠道 Redis Lua 多维原子风控引擎。

规则覆盖：
- 单邮箱冷却时间（60s）+ 10m / 1h / 自然日额度
- 单 IP 1m / 1h / 自然日额度 + IP 不同目标邮箱数限制
- 单账号 1h / 自然日额度
- 单设备 1h / 自然日额度 + 设备不同目标邮箱数限制
- 全系统每日发送总预算
- 非大型公共邮箱域名的短期异常流量信号（永不误伤 QQ/163/Outlook/Gmail 等大型公共邮箱）
"""

from __future__ import annotations

from functools import lru_cache

from core.contact_validation import email_domain
from modules.security.risk_engine import (
    REQUEST_LUA,
    RESERVE_LUA,
    BaseRiskEngine,
    DecisionAction,
    RiskContext,
    RiskDecision,
    RiskRule,
)

# 公共大型邮箱域名白名单：不得针对公共邮箱域名实施默认域名级封禁或误杀限额。
PUBLIC_EMAIL_DOMAINS = frozenset(
    {
        "qq.com",
        "foxmail.com",
        "163.com",
        "126.com",
        "yeah.net",
        "sina.com",
        "sina.cn",
        "sohu.com",
        "aliyun.com",
        "139.com",
        "189.cn",
        "outlook.com",
        "hotmail.com",
        "live.com",
        "msn.com",
        "gmail.com",
        "googlemail.com",
        "icloud.com",
        "me.com",
        "yahoo.com",
    }
)

_ALLOWED_EMAIL_RISK_PURPOSES = frozenset(
    {
        "password_recovery",
        "reset_password",
        "bind_email",
        "rebind_email",
        "step_up_auth",
    }
)


class EmailRiskEngine(BaseRiskEngine):
    def __init__(self, redis_client=None, secret=None, config=None, prefix="email:{gateway}:"):
        if config is None:
            from config import settings as config
        effective_secret = (
            secret
            or getattr(config, "EMAIL_RISK_HMAC_SECRET", "")
            or getattr(config, "SMS_RISK_HMAC_SECRET", "")
            or config.JWT_SECRET
        )
        super().__init__(redis_client=redis_client, secret=effective_secret, config=config, prefix=prefix)

    def rule_catalog(self) -> list[RiskRule]:
        """导出当前生效的邮箱风控规则目录（rule_id/limit/window/dimension/decision）。"""
        c = self.config
        return [
            RiskRule(
                "email.cooldown",
                c.EMAIL_COOLDOWN_SECONDS,
                c.EMAIL_COOLDOWN_SECONDS,
                "email",
                DecisionAction.THROTTLE,
                c.EMAIL_COOLDOWN_SECONDS,
            ),
            RiskRule("email.10m", c.EMAIL_LIMIT_10M, 600, "email", DecisionAction.THROTTLE, 600),
            RiskRule("email.1h", c.EMAIL_LIMIT_1H, 3600, "email", DecisionAction.THROTTLE, 3600),
            RiskRule("email.day", c.EMAIL_LIMIT_DAY, 86400, "email", DecisionAction.THROTTLE, 86400),
            RiskRule("email.ip.1m", c.EMAIL_IP_LIMIT_1M, 60, "ip", DecisionAction.THROTTLE, 60),
            RiskRule("email.ip.1h", c.EMAIL_IP_LIMIT_1H, 3600, "ip", DecisionAction.THROTTLE, 3600),
            RiskRule("email.ip.day", c.EMAIL_IP_LIMIT_DAY, 86400, "ip", DecisionAction.THROTTLE, 86400),
            RiskRule("email.account.1h", c.EMAIL_ACCOUNT_LIMIT_1H, 3600, "account", DecisionAction.THROTTLE, 3600),
            RiskRule("email.account.day", c.EMAIL_ACCOUNT_LIMIT_DAY, 86400, "account", DecisionAction.THROTTLE, 86400),
            RiskRule("email.device.1h", c.EMAIL_DEVICE_LIMIT_1H, 3600, "device", DecisionAction.THROTTLE, 3600),
            RiskRule("email.device.day", c.EMAIL_DEVICE_LIMIT_DAY, 86400, "device", DecisionAction.THROTTLE, 86400),
            RiskRule(
                "email.ip.distinct_email",
                c.EMAIL_IP_DISTINCT_LIMIT_1H,
                3600,
                "ip_distinct",
                DecisionAction.CHALLENGE,
                3600,
            ),
            RiskRule(
                "email.device.distinct_email",
                c.EMAIL_DEVICE_DISTINCT_LIMIT_10M,
                600,
                "device_distinct",
                DecisionAction.CHALLENGE,
                600,
            ),
            RiskRule("email.global.day", c.EMAIL_GLOBAL_DAILY_BUDGET, 86400, "global", DecisionAction.THROTTLE, 86400),
            RiskRule(
                "email.domain.anomaly_10m",
                c.EMAIL_DOMAIN_ANOMALY_LIMIT_10M,
                600,
                "domain",
                DecisionAction.THROTTLE,
                600,
            ),
        ]

    def _distinct(self, ip: str, device_id: str | None, target_email: str) -> list[dict]:
        c = self.config
        out = [
            {
                "key": self._key("distinct:ip:email", ip),
                "value": self._digest("email", target_email),
                "window": 3600,
                "limit": c.EMAIL_IP_DISTINCT_LIMIT_1H,
                "rule": "email.ip.distinct_email",
            }
        ]
        if device_id:
            out.append(
                {
                    "key": self._key("distinct:device:email", device_id),
                    "value": self._digest("email", target_email),
                    "window": 600,
                    "limit": c.EMAIL_DEVICE_DISTINCT_LIMIT_10M,
                    "rule": "email.device.distinct_email",
                }
            )
        return out

    def build_context(
        self,
        *,
        purpose: str,
        account_id: str,
        email: str | None,
        ip: str,
        device_id: str | None,
        request_id: str,
    ) -> RiskContext:
        fp = self._digest("email", email) if email else ""
        return RiskContext(
            channel="email",
            purpose=purpose,
            account_id=str(account_id),
            destination_fingerprint=fp,
            ip=ip,
            device_id=device_id,
            request_id=request_id,
        )

    def check_request(
        self,
        ip: str,
        account: str,
        device_id: str | None,
        email: str | None = None,
        purpose: str = "password_recovery",
    ) -> RiskDecision:
        if not self.config.EMAIL_RISK_ENGINE_ENABLED:
            return RiskDecision(DecisionAction.DENY, "email.risk.disabled")
        if purpose not in _ALLOWED_EMAIL_RISK_PURPOSES:
            return RiskDecision(DecisionAction.DENY, "email.purpose.disabled")
        if self._is_dev_bypass_allowed():
            return RiskDecision(DecisionAction.ALLOW, "email.allow.dev_mode")
        try:
            day, ttl = self._day()
            c = self.config
            rates: list[dict] = []
            distinct: list[dict] = []

            def rate(kind: str, value: str, window: int, limit: int, rule_name: str):
                rates.append(
                    {
                        "key": self._key(f"request:{kind}:{window}", value),
                        "window": window,
                        "limit": limit,
                        "rule": rule_name,
                        "action": "THROTTLE",
                    }
                )

            def daily(kind: str, value: str, limit: int, rule_name: str):
                rates.append(
                    {
                        "key": self._key(f"request:{kind}:day:{day}", value),
                        "daily": True,
                        "ttl": ttl,
                        "limit": limit,
                        "rule": rule_name,
                        "action": "THROTTLE",
                    }
                )

            rate("ip", ip, 60, c.EMAIL_IP_LIMIT_1M, "email.ip.1m")
            rate("ip", ip, 3600, c.EMAIL_IP_LIMIT_1H, "email.ip.1h")
            daily("ip", ip, c.EMAIL_IP_LIMIT_DAY, "email.ip.day")
            rate("account", account, 3600, c.EMAIL_ACCOUNT_LIMIT_1H, "email.account.1h")
            daily("account", account, c.EMAIL_ACCOUNT_LIMIT_DAY, "email.account.day")
            if device_id:
                rate("device", device_id, 3600, c.EMAIL_DEVICE_LIMIT_1H, "email.device.1h")
                daily("device", device_id, c.EMAIL_DEVICE_LIMIT_DAY, "email.device.day")
            if email:
                distinct = self._distinct(ip, device_id, email)
                dom = email_domain(email)
                if dom and dom not in PUBLIC_EMAIL_DOMAINS:
                    rate("domain", dom, 600, c.EMAIL_DOMAIN_ANOMALY_LIMIT_10M, "email.domain.anomaly_10m")

            return self._eval(REQUEST_LUA, {"allow_rule": "email.allow", "rates": rates, "distinct": distinct})
        except Exception:
            return RiskDecision(DecisionAction.DENY, "email.redis.unavailable")

    def reserve(
        self,
        email: str,
        account: str,
        ip: str,
        device_id: str | None,
        reservation_id: str,
        *,
        ttl_seconds: int | None = None,
    ) -> RiskDecision:
        if not self.config.EMAIL_RISK_ENGINE_ENABLED or not self.config.EMAIL_REQUIRE_VERIFIED_CONTACT:
            return RiskDecision(DecisionAction.DENY, "email.policy.disabled")
        if self._is_dev_bypass_allowed():
            return RiskDecision(DecisionAction.ALLOW, "email.quota.dev_mode")
        try:
            day, ttl = self._day()
            c = self.config
            cooldowns = [
                {
                    "key": self._key("cooldown:email", email),
                    "ttl": c.EMAIL_COOLDOWN_SECONDS,
                    "rule": "email.cooldown",
                },
                {
                    "key": self._key("cooldown:pair", f"{ip}:{email}"),
                    "ttl": c.EMAIL_COOLDOWN_SECONDS,
                    "rule": "email.pair.cooldown",
                },
            ]
            rates: list[dict] = []
            for kind, value, window, limit, rule_name in [
                ("email", email, 600, c.EMAIL_LIMIT_10M, "email.10m"),
                ("email", email, 3600, c.EMAIL_LIMIT_1H, "email.1h"),
                ("account", account, 3600, c.EMAIL_ACCOUNT_LIMIT_1H, "email.account.1h"),
                ("ip", ip, 60, c.EMAIL_IP_LIMIT_1M, "email.ip.1m"),
                ("ip", ip, 3600, c.EMAIL_IP_LIMIT_1H, "email.ip.1h"),
                *([("device", device_id, 3600, c.EMAIL_DEVICE_LIMIT_1H, "email.device.1h")] if device_id else []),
            ]:
                rates.append(
                    {
                        "key": self._key(f"send:{kind}:{window}", value),
                        "window": window,
                        "limit": limit,
                        "rule": rule_name,
                    }
                )
            dom = email_domain(email)
            if dom and dom not in PUBLIC_EMAIL_DOMAINS:
                rates.append(
                    {
                        "key": self._key("send:domain:600", dom),
                        "window": 600,
                        "limit": c.EMAIL_DOMAIN_ANOMALY_LIMIT_10M,
                        "rule": "email.domain.anomaly_10m",
                    }
                )

            budgets = [
                {
                    "key": self._key("quota:email:" + day, email),
                    "limit": c.EMAIL_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "email.day",
                },
                {
                    "key": self._key("quota:account:" + day, account),
                    "limit": c.EMAIL_ACCOUNT_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "email.account.day",
                },
                {
                    "key": self._key("quota:ip:" + day, ip),
                    "limit": c.EMAIL_IP_LIMIT_DAY,
                    "ttl": ttl,
                    "rule": "email.ip.day",
                },
                {
                    "key": self._key("quota:global:" + day, "all"),
                    "limit": c.EMAIL_GLOBAL_DAILY_BUDGET,
                    "ttl": ttl,
                    "rule": "email.global.day",
                },
            ]
            if device_id:
                budgets.append(
                    {
                        "key": self._key("quota:device:" + day, device_id),
                        "limit": c.EMAIL_DEVICE_LIMIT_DAY,
                        "ttl": ttl,
                        "rule": "email.device.day",
                    }
                )

            return self._eval(
                RESERVE_LUA,
                {
                    "dup_rule": "email.task.duplicate",
                    "pending_rule": "email.pending_outcome",
                    "ok_rule": "email.quota.reserved",
                    "reservation": self._key("reservation", reservation_id),
                    "uncertainty": self._key("pending_outcome", email),
                    "uncertainty_ttl": int(ttl_seconds or c.EMAIL_CODE_TTL_SECONDS),
                    "rates": rates,
                    "cooldowns": cooldowns,
                    "budgets": budgets,
                    "distinct": self._distinct(ip, device_id, email),
                },
            )
        except Exception:
            return RiskDecision(DecisionAction.DENY, "email.redis.unavailable")

    def transition(self, reservation_id: str, state: str) -> bool:
        return self._transition_key(reservation_id, state)


@lru_cache(maxsize=1)
def get_email_risk_engine() -> EmailRiskEngine:
    return EmailRiskEngine()
