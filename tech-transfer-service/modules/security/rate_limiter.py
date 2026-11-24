"""统一安全限流器（Redis 分布式原子限流 + 严格 Fail-Closed 保护）。

覆盖安全端点：
1. 挑战验证尝试频次控制（防暴力破解与碰撞）
2. 密码找回 / 绑定请求的基础滑动窗口防护（生产环境禁止因 Redis 异常静默降级到进程内存）
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import threading
import time
import uuid
from collections import defaultdict, deque

from config import settings
from core.errors import TT_COMMON_42901, TT_COMMON_50301, BizError
from core.rate_limit import _client_ip

logger = logging.getLogger("nanshan.security.rate_limit")

_HAS_REDIS = False
try:
    import redis

    _HAS_REDIS = True
except ImportError:
    redis = None

# 内存限流滑动窗口（仅限非生产且明确未启用 Redis 的本地/单测环境）
_mem_lock = threading.Lock()
_mem_buckets: dict[str, deque] = defaultdict(deque)

# Redis Lua 原子限流脚本：使用独立 UUID 成员避免同时间戳覆盖计数
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local member = ARGV[4]
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, '-inf', clear_before)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, member)
    redis.call('EXPIRE', key, window + 1)
    return 1
else
    return 0
end
"""


def _is_noscript(exc: Exception) -> bool:
    return "NoScript" in type(exc).__name__ or "NOSCRIPT" in str(exc).upper()


def _blind_segment(kind: str, value: str) -> str:
    secret = (settings.SECURITY_CONTACT_HMAC_SECRET or settings.JWT_SECRET).encode("utf-8")
    return hmac.new(secret, f"{kind}:{value.lower().strip()}".encode(), hashlib.sha256).hexdigest()[:32]


class SecurityRateLimiter:
    def __init__(self):
        self._redis_client = None
        self._lua_sha = None
        self._init_redis()

    def _init_redis(self):
        if settings.REDIS_ENABLED and _HAS_REDIS:
            try:
                client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=True,
                )
                sha = client.script_load(LUA_SLIDING_WINDOW)
                self._redis_client = client
                self._lua_sha = sha
                logger.info("Redis 限流客户端已启用")
            except Exception as exc:
                logger.warning("Redis 限流初始化失败: %s", type(exc).__name__)
                self._redis_client = None
                self._lua_sha = None
        else:
            self._redis_client = None
            self._lua_sha = None

    def _requires_redis(self) -> bool:
        return bool(settings.is_production_like or settings.REDIS_ENABLED)

    def _eval_redis(self, key: str, now: float, window_s: int, limit: int) -> int:
        if self._redis_client is None:
            self._init_redis()
        if self._redis_client is None:
            raise ConnectionError("redis_unavailable")
        member = uuid.uuid4().hex
        redis_key = f"tt_sec:rate:{key}"
        if not self._lua_sha:
            self._lua_sha = self._redis_client.script_load(LUA_SLIDING_WINDOW)
        try:
            return int(self._redis_client.evalsha(self._lua_sha, 1, redis_key, now, window_s, limit, member))
        except Exception as exc:
            if _is_noscript(exc):
                self._lua_sha = self._redis_client.script_load(LUA_SLIDING_WINDOW)
                return int(self._redis_client.evalsha(self._lua_sha, 1, redis_key, now, window_s, limit, member))
            raise

    def check(self, key: str, limit: int, window_s: int):
        """通用限流检查。生产或启用 Redis 时严格 Fail-Closed，绝不降级内存限流。"""
        now = time.time()
        if self._requires_redis():
            try:
                allowed = self._eval_redis(key, now, window_s, limit)
            except BizError:
                raise
            except Exception as exc:
                logger.error("Redis 限流调用异常（Fail-Closed）: %s", type(exc).__name__)
                # 重置句柄以便 Redis 恢复后自动重连
                self._redis_client = None
                self._lua_sha = None
                code, _msg, status = TT_COMMON_50301
                raise BizError(code, "安全防护服务暂时不可用，请稍后重试", status) from None
            if not allowed:
                code, _msg, status = TT_COMMON_42901
                raise BizError(code, "操作过于频繁，请稍后再试", status, details={"retryAfter": window_s})
            return

        # 仅在本地/开发且明确 REDIS_ENABLED=false 时允许内存滑动窗口
        cutoff = now - window_s
        with _mem_lock:
            q = _mem_buckets[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                code, _msg, status = TT_COMMON_42901
                raise BizError(code, "操作过于频繁，请稍后再试", status, details={"retryAfter": window_s})
            q.append(now)

    def reset_for_test(self):
        """测试用清空限流状态。"""
        with _mem_lock:
            _mem_buckets.clear()
        self._redis_client = None
        self._lua_sha = None


limiter = SecurityRateLimiter()


def check_recovery_start_rate(request, account: str):
    """发起密码找回限流：IP 维度 15次/60秒，目标账号（盲索引）5次/300秒。"""
    ip = _client_ip(request)
    limiter.check(f"rec_start:ip:{_blind_segment('ip', ip)}", limit=15, window_s=60)
    if account:
        limiter.check(f"rec_start:acct:{_blind_segment('acct', account)}", limit=5, window_s=300)


def check_send_code_rate(request, destination: str):
    """验证码发送限频：IP 维度 10次/60秒，单个目标（盲索引）5次/3600秒。"""
    ip = _client_ip(request)
    limiter.check(f"otp_send:ip:{_blind_segment('ip', ip)}", limit=10, window_s=60)
    if destination:
        limiter.check(f"otp_send:dest:{_blind_segment('dest', destination)}", limit=5, window_s=3600)


def check_verify_challenge_rate(challenge_id: str):
    """挑战核验限频：单挑战 10次/60秒。"""
    limiter.check(f"chal_verify:{challenge_id}", limit=10, window_s=60)
