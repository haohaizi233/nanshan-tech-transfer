"""通用 Redis Lua 原子多维风控引擎基础设施（SMS / Email 共享底座）。

特性：
1. Redis TIME（客户端缺省回退）+ UUID 全局唯一 ZSET 成员，消除并发同时间戳覆盖；
2. 统一 Hash Tag（如 `{gateway}`）兼容 Redis Cluster 单脚本多 Key 原子性；
3. 自然日配额使用 `TTL < 0` 守卫，绝不因持续访问意外跨午夜延长 TTL；
4. EVALSHA + NoScriptError 自动重载重试；
5. Key 全部采用独立密钥 HMAC-SHA256 盲索引，绝不存入明文手机号/邮箱/IP/设备号；
6. Redis 异常严格 Fail-Closed（仅非生产且未开启 REDIS_ENABLED 时允许显式本地开发模式）。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
import time as _time
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo


class DecisionAction(StrEnum):
    ALLOW = "ALLOW"
    CHALLENGE = "CHALLENGE"
    THROTTLE = "THROTTLE"
    DENY = "DENY"


@dataclass(frozen=True)
class RiskDecision:
    action: DecisionAction
    rule_id: str = "security.allow"
    retry_after: int = 0

    @property
    def risk_score(self) -> int:
        return {
            DecisionAction.ALLOW: 0,
            DecisionAction.CHALLENGE: 50,
            DecisionAction.THROTTLE: 80,
            DecisionAction.DENY: 100,
        }[self.action]

    @property
    def risk_level(self) -> str:
        return "low" if self.risk_score == 0 else "medium" if self.risk_score == 50 else "high"


@dataclass(frozen=True)
class RiskRule:
    rule_id: str
    limit: int
    window: int
    dimension: str
    decision: DecisionAction
    retry_after: int = 0


@dataclass(frozen=True)
class RiskContext:
    channel: str
    purpose: str
    account_id: str
    destination_fingerprint: str
    ip: str
    device_id: str | None
    request_id: str


def day_bucket(now: datetime, timezone: str) -> tuple[str, int]:
    local = now.astimezone(ZoneInfo(timezone))
    end = datetime.combine(local.date() + timedelta(days=1), time(), tzinfo=local.tzinfo)
    return local.date().isoformat(), max(1, math.ceil(end.timestamp() - now.timestamp()))


# 所有 Key 只含盲索引；按请求维度原子计数（被拒绝也计数但以 limit+1 封顶）；
# 日配额仅在未设置 TTL 时设定距离业务午夜的剩余秒数，避免持续访问延长 TTL。
REQUEST_LUA = """
local spec=cjson.decode(ARGV[1]); local member=ARGV[2]
local now=tonumber(ARGV[3]) or 0
if now<=0 then local t=redis.call('TIME'); now=tonumber(t[1])+tonumber(t[2])/1000000 end
local allow_rule=spec.allow_rule or 'security.allow'
local result={'ALLOW',allow_rule,'0'}
for _,r in ipairs(spec.rates) do
 local n=0
 if r.daily then
  n=tonumber(redis.call('GET',r.key) or '0')
  if n<=r.limit then
   redis.call('INCR',r.key)
   if redis.call('TTL',r.key)<0 then redis.call('EXPIRE',r.key,r.ttl) end
  end
 else
  redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
  n=redis.call('ZCARD',r.key)
  if n<=r.limit then redis.call('ZADD',r.key,now,member); redis.call('EXPIRE',r.key,r.window+1) end
 end
 if n>=r.limit and result[1]=='ALLOW' then
  local ra=r.ttl or r.window
  result={r.action,r.rule,tostring(ra)}
 end
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
local dup_rule=s.dup_rule or 'security.task.duplicate'
local pending_rule=s.pending_rule or 'security.pending_outcome'
local ok_rule=s.ok_rule or 'security.quota.reserved'
if redis.call('EXISTS',s.reservation)==1 then return {'DENY',dup_rule,'0'} end
if redis.call('EXISTS',s.uncertainty)==1 then return {'THROTTLE',pending_rule,tostring(math.max(1,redis.call('TTL',s.uncertainty)))} end
for _,r in ipairs(s.cooldowns) do
 if redis.call('EXISTS',r.key)==1 then return {'THROTTLE',r.rule,tostring(math.max(1,redis.call('TTL',r.key)))} end
end
local now=tonumber(ARGV[3]) or 0
if now<=0 then local t=redis.call('TIME'); now=tonumber(t[1])+tonumber(t[2])/1000000 end
for _,r in ipairs(s.rates) do
 redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
 if redis.call('ZCARD',r.key)>=r.limit then return {'THROTTLE',r.rule,tostring(r.window)} end
end
for _,r in ipairs(s.budgets) do
 if tonumber(redis.call('GET',r.key) or '0')>=r.limit then
  local cur_ttl=redis.call('TTL',r.key)
  return {'THROTTLE',r.rule,tostring(cur_ttl>0 and cur_ttl or r.ttl)}
 end
end
for _,r in ipairs(s.distinct) do
 redis.call('ZREMRANGEBYSCORE',r.key,'-inf',now-r.window)
 if not redis.call('ZSCORE',r.key,r.value) and redis.call('ZCARD',r.key)>=r.limit then
  return {'CHALLENGE',r.rule,tostring(r.window)}
 end
end
for _,r in ipairs(s.cooldowns) do redis.call('SET',r.key,member,'EX',r.ttl) end
for _,r in ipairs(s.rates) do redis.call('ZADD',r.key,now,member); redis.call('EXPIRE',r.key,r.window+1) end
for _,r in ipairs(s.budgets) do
 redis.call('INCR',r.key)
 if redis.call('TTL',r.key)<0 then redis.call('EXPIRE',r.key,r.ttl) end
end
for _,r in ipairs(s.distinct) do redis.call('ZADD',r.key,now,r.value); redis.call('EXPIRE',r.key,r.window+1) end
redis.call('SET',s.uncertainty,member,'EX',s.uncertainty_ttl)
redis.call('SET',s.reservation,cjson.encode({state='reserved',budgets=s.budgets,uncertainty=s.uncertainty,member=member}),'EX',172800)
return {'ALLOW',ok_rule,'0'}
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
local ttl=redis.call('TTL',KEYS[1])
redis.call('SET',KEYS[1],cjson.encode(s),'EX',math.max(1,ttl))
return 1
"""


def _is_noscript(exc: Exception) -> bool:
    name = type(exc).__name__
    return "NoScript" in name or "NOSCRIPT" in str(exc).upper()


class BaseRiskEngine:
    """SMS / Email 共用 Redis Lua 原子风控引擎基类。"""

    def __init__(self, redis_client=None, secret=None, config=None, prefix="security:{gateway}:"):
        if config is None:
            from config import settings as config
        self.config = config
        self.redis = redis_client
        raw_secret = (
            secret
            or getattr(config, "EMAIL_RISK_HMAC_SECRET", "")
            or getattr(config, "SMS_RISK_HMAC_SECRET", "")
            or config.JWT_SECRET
        )
        self.secret = raw_secret.encode("utf-8") if isinstance(raw_secret, str) else raw_secret
        self.prefix = prefix
        self._sha_cache: dict[str, str] = {}

    def _digest(self, kind: str, value: object) -> str:
        return hmac.new(self.secret, (kind + ":" + str(value)).encode("utf-8"), hashlib.sha256).hexdigest()

    def _key(self, kind: str, value: object) -> str:
        return self.prefix + kind + ":" + self._digest(kind, value)

    def _client(self):
        if self.redis is None:
            import redis

            self.redis = redis.Redis.from_url(
                self.config.REDIS_URL,
                decode_responses=True,
                protocol=2,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            self._sha_cache.clear()
        return self.redis

    def _day(self) -> tuple[str, int]:
        sec, micro = self._client().time()
        tz = getattr(self.config, "SMS_BUSINESS_TIMEZONE", "Asia/Shanghai")
        return day_bucket(datetime.fromtimestamp(int(sec) + int(micro) / 1e6, ZoneInfo("UTC")), tz)

    def _eval_script(self, script: str, numkeys: int, *args):
        client = self._client()
        if hasattr(client, "script_load") and hasattr(client, "evalsha"):
            sha = self._sha_cache.get(script)
            if not sha:
                sha = client.script_load(script)
                self._sha_cache[script] = sha
            try:
                return client.evalsha(sha, numkeys, *args)
            except Exception as exc:
                if _is_noscript(exc):
                    sha = client.script_load(script)
                    self._sha_cache[script] = sha
                    return client.evalsha(sha, numkeys, *args)
                raise
        return client.eval(script, numkeys, *args)

    def _eval(self, script: str, spec: dict) -> RiskDecision:
        now_ts = str(_time.time())
        result = self._eval_script(script, 1, self.prefix + "anchor", json.dumps(spec), uuid.uuid4().hex, now_ts)
        return RiskDecision(DecisionAction(result[0]), result[1], int(result[2]))

    def _is_dev_bypass_allowed(self) -> bool:
        return (
            self.redis is None
            and not self.config.REDIS_ENABLED
            and not self.config.is_production_like
            and self.config.APP_ENV in {"local", "development"}
        )

    def _transition_key(self, reservation_id: str, state: str) -> bool:
        if state not in {"accepted", "rejected", "unknown", "delivered"}:
            raise ValueError("invalid reservation state")
        if self._is_dev_bypass_allowed():
            return True
        try:
            res = self._eval_script(TRANSITION_LUA, 1, self._key("reservation", reservation_id), state)
            return bool(res)
        except Exception:
            return False
