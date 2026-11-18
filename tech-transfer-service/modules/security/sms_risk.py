"""Atomic SMS request frequency and cost reservations. Redis failure closes sends.

Redis TIME is authoritative. All keys use one cluster hash slot. Random ZSET
members prevent simultaneous requests collapsing into one timestamp entry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from functools import lru_cache
from zoneinfo import ZoneInfo


class DecisionAction(StrEnum):
    ALLOW = "ALLOW"
    CHALLENGE = "CHALLENGE"
    THROTTLE = "THROTTLE"
    DENY = "DENY"


@dataclass(frozen=True)
class RiskDecision:
    action: DecisionAction
    rule_id: str = "sms.allow"
    retry_after: int = 0

    @property
    def risk_score(self):
        return {
            DecisionAction.ALLOW: 0,
            DecisionAction.CHALLENGE: 50,
            DecisionAction.THROTTLE: 80,
            DecisionAction.DENY: 100,
        }[self.action]

    @property
    def risk_level(self):
        return "low" if self.risk_score == 0 else "medium" if self.risk_score == 50 else "high"


def day_bucket(now: datetime, timezone: str) -> tuple[str, int]:
    local = now.astimezone(ZoneInfo(timezone))
    end = datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=local.tzinfo)
    return local.date().isoformat(), max(1, math.ceil(end.timestamp() - now.timestamp()))


# Specs carry only digests. Count all request dimensions atomically, including
# denied attempts, bounded at limit+1. Daily keys expire at business midnight.
REQUEST_LUA = """
local spec=cjson.decode(ARGV[1]); local member=ARGV[2]
local t=redis.call('TIME'); local now=tonumber(t[1])+tonumber(t[2])/1000000
local result={'ALLOW','sms.allow','0'}
for _,r in ipairs(spec.rates) do
 local n=0
 if r.daily then
  n=tonumber(redis.call('GET',r.key) or '0')
  if n<=r.limit then redis.call('INCR',r.key); redis.call('EXPIRE',r.key,r.ttl) end
 else
  redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
  n=redis.call('ZCARD',r.key)
  if n<=r.limit then redis.call('ZADD',r.key,now,member); redis.call('EXPIRE',r.key,r.window+1) end
 end
 if n>=r.limit and result[1]=='ALLOW' then result={r.action,r.rule,tostring(r.ttl or r.window)} end
end
for _,r in ipairs(spec.distinct) do
 redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
 local present=redis.call('ZSCORE',r.key,r.value)
 local n=redis.call('ZCARD',r.key)
 if present or n<=r.limit then redis.call('ZADD',r.key,now,r.value); redis.call('EXPIRE',r.key,r.window+1) end
 if not present and n>=r.limit and result[1]=='ALLOW' then result={'CHALLENGE',r.rule,tostring(r.window)} end
end
return result
"""

RESERVE_LUA = """
local s=cjson.decode(ARGV[1]); local member=ARGV[2]
if redis.call('EXISTS',s.reservation)==1 then return {'DENY','sms.task.duplicate','0'} end
if redis.call('EXISTS',s.uncertainty)==1 then return {'THROTTLE','sms.phone.pending_outcome',tostring(redis.call('TTL',s.uncertainty))} end
for _,r in ipairs(s.cooldowns) do
 if redis.call('EXISTS',r.key)==1 then return {'THROTTLE',r.rule,tostring(redis.call('TTL',r.key))} end
end
local t=redis.call('TIME'); local now=tonumber(t[1])+tonumber(t[2])/1000000
for _,r in ipairs(s.rates) do
 redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
 if redis.call('ZCARD',r.key)>=r.limit then return {'THROTTLE',r.rule,tostring(r.window)} end
end
for _,r in ipairs(s.budgets) do
 if tonumber(redis.call('GET',r.key) or '0')>=r.limit then return {'THROTTLE',r.rule,tostring(r.ttl)} end
end
for _,r in ipairs(s.distinct) do
 redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
 if not redis.call('ZSCORE',r.key,r.value) and redis.call('ZCARD',r.key)>=r.limit then
  return {'CHALLENGE',r.rule,tostring(r.window)}
 end
end
for _,r in ipairs(s.cooldowns) do redis.call('SET',r.key,member,'EX',r.ttl) end
for _,r in ipairs(s.rates) do redis.call('ZADD',r.key,now,member); redis.call('EXPIRE',r.key,r.window+1) end
for _,r in ipairs(s.budgets) do redis.call('INCR',r.key); redis.call('EXPIRE',r.key,r.ttl) end
for _,r in ipairs(s.distinct) do redis.call('ZADD',r.key,now,r.value); redis.call('EXPIRE',r.key,r.window+1) end
redis.call('SET',s.uncertainty,member,'EX',s.uncertainty_ttl)
redis.call('SET',s.reservation,cjson.encode({state='reserved',budgets=s.budgets,uncertainty=s.uncertainty,member=member}),'EX',172800)
return {'ALLOW','sms.quota.reserved','0'}
"""

TRANSITION_LUA = """
local raw=redis.call('GET',KEYS[1]); if not raw then return 0 end
local s=cjson.decode(raw); local target=ARGV[1]
if s.state==target then return 1 end
local ok=(s.state=='reserved' and (target=='accepted' or target=='unknown' or target=='rejected'))
 or (s.state=='unknown' and (target=='accepted' or target=='delivered'))
 or (s.state=='accepted' and target=='delivered')
if not ok then return 0 end
if target~='unknown' and redis.call('GET',s.uncertainty)==s.member then redis.call('DEL',s.uncertainty) end
if target=='rejected' then
 for _,r in ipairs(s.budgets) do
  if tonumber(redis.call('GET',r.key) or '0')>0 then redis.call('DECR',r.key) end
 end
end
s.state=target
redis.call('SET',KEYS[1],cjson.encode(s),'KEEPTTL')
return 1
""".replace(
    "redis.call('SET',KEYS[1],cjson.encode(s),'KEEPTTL')",
    "local ttl=redis.call('TTL',KEYS[1]); redis.call('SET',KEYS[1],cjson.encode(s),'EX',math.max(1,ttl))",
)


class SmsRiskEngine:
    def __init__(self, redis_client=None, secret=None, config=None, prefix="sms:{gateway}:"):
        if config is None:
            from config import settings as config
        self.config = config
        self.redis = redis_client
        self.secret = (secret or config.SMS_RISK_HMAC_SECRET or config.JWT_SECRET).encode()
        self.prefix = prefix

    def _digest(self, kind, value):
        return hmac.new(self.secret, (kind + ":" + str(value)).encode(), hashlib.sha256).hexdigest()

    def _key(self, kind, value):
        return self.prefix + kind + ":" + self._digest(kind, value)

    def _client(self):
        if self.redis is None:
            import redis

            self.redis = redis.Redis.from_url(
                self.config.REDIS_URL, decode_responses=True, protocol=2, socket_connect_timeout=2, socket_timeout=2
            )
        return self.redis

    def _day(self):
        # Same day computation on all instances using Redis server clock.
        sec, micro = self._client().time()
        return day_bucket(
            datetime.fromtimestamp(int(sec) + int(micro) / 1e6, ZoneInfo("UTC")), self.config.SMS_BUSINESS_TIMEZONE
        )

    def _eval(self, script, spec):
        result = self._client().eval(script, 1, self.prefix + "anchor", json.dumps(spec), uuid.uuid4().hex)
        return RiskDecision(DecisionAction(result[0]), result[1], int(result[2]))

    def check_request(self, ip, account, device_id, phone=None, purpose="reset_password"):
        if not self.config.SMS_RISK_ENGINE_ENABLED:
            return RiskDecision(DecisionAction.DENY, "sms.risk.disabled")
        if purpose not in {"reset_password", "bind_phone"}:
            return RiskDecision(DecisionAction.DENY, "sms.purpose.disabled")
        if self.redis is None and not self.config.REDIS_ENABLED and self.config.APP_ENV in {"local", "development"}:
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
            return self._eval(REQUEST_LUA, {"rates": rates, "distinct": distinct})
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
        if self.redis is None and not self.config.REDIS_ENABLED and self.config.APP_ENV in {"local", "development"}:
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
        if state not in {"accepted", "rejected", "unknown", "delivered"}:
            raise ValueError("invalid reservation state")
        if self.redis is None and not self.config.REDIS_ENABLED and self.config.APP_ENV in {"local", "development"}:
            return True
        try:
            return bool(self._client().eval(TRANSITION_LUA, 1, self._key("reservation", reservation_id), state))
        except Exception:
            return False


@lru_cache(maxsize=1)
def get_sms_risk_engine():
    return SmsRiskEngine()
