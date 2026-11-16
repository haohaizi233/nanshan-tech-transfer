"""统一安全限流器（Redis 分布式原子限流 + 本地内存滑动窗口兜底）。

覆盖安全端点：
1. 短信/邮件验证码发送频次控制（按 IP、按目标联系方式）
2. 密码找回发起频次控制（防账号扫描与枚举）
3. 挑战验证尝试频次控制（防暴力破解与碰撞）
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from config import settings
from core.errors import TT_COMMON_42901, BizError
from core.rate_limit import _client_ip

logger = logging.getLogger("nanshan.security.rate_limit")

_HAS_REDIS = False
try:
    import redis

    _HAS_REDIS = True
except ImportError:
    redis = None

# 内存限流滑动窗口备选
_mem_lock = threading.Lock()
_mem_buckets: dict[str, deque] = defaultdict(deque)

# Redis Lua 原子限流脚本
LUA_SLIDING_WINDOW = """
local key = KEYS[1]
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
local limit = tonumber(ARGV[3])
local clear_before = now - window

redis.call('ZREMRANGEBYSCORE', key, 0, clear_before)
local count = redis.call('ZCARD', key)
if count < limit then
    redis.call('ZADD', key, now, now)
    redis.call('EXPIRE', key, window)
    return 1
else
    return 0
end
"""


class SecurityRateLimiter:
    def __init__(self):
        self._redis_client = None
        self._lua_sha = None
        self._init_redis()

    def _init_redis(self):
        if settings.REDIS_ENABLED and _HAS_REDIS:
            try:
                self._redis_client = redis.Redis.from_url(
                    settings.REDIS_URL,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                    decode_responses=True,
                )
                self._lua_sha = self._redis_client.script_load(LUA_SLIDING_WINDOW)
                logger.info("Redis 限流客户端已启用: %s", settings.REDIS_URL)
            except Exception as e:
                logger.warning("Redis 初始化连接失败: %s", e)
                self._redis_client = None

    def check(self, key: str, limit: int, window_s: int):
        """通用限流检查。超出限制抛出 TT_COMMON_42901。"""
        now = time.time()
        # 1. 尝试 Redis 分布式限流
        if settings.REDIS_ENABLED and self._redis_client is not None:
            try:
                allowed = self._redis_client.evalsha(self._lua_sha, 1, f"tt_sec:rate:{key}", now, window_s, limit)
                if not allowed:
                    code, _msg, status = TT_COMMON_42901
                    raise BizError(code, "操作过于频繁，请稍后再试", status)
                return
            except BizError:
                raise
            except Exception as e:
                logger.error("Redis 限流调用异常: %s", e)
                # 生产环境若配置了 Redis 但宕机，公开发送接口严格 fail-closed
                if settings.is_production_like:
                    code, _msg, status = TT_COMMON_42901
                    raise BizError(code, "安全防护服务暂时不可用，请稍后重试", status) from None

        # 2. 内存滑动窗口限流（单机开发或备选）
        cutoff = now - window_s
        with _mem_lock:
            q = _mem_buckets[key]
            while q and q[0] < cutoff:
                q.popleft()
            if len(q) >= limit:
                code, _msg, status = TT_COMMON_42901
                raise BizError(code, "操作过于频繁，请稍后再试", status)
            q.append(now)

    def reset_for_test(self):
        """测试用清空限流状态。"""
        with _mem_lock:
            _mem_buckets.clear()


limiter = SecurityRateLimiter()


def check_recovery_start_rate(request, account: str):
    """发起密码找回限流：IP 维度 15次/60秒，目标账号 5次/300秒。"""
    ip = _client_ip(request)
    limiter.check(f"rec_start:ip:{ip}", limit=15, window_s=60)
    if account:
        limiter.check(f"rec_start:acct:{account.lower().strip()}", limit=5, window_s=300)


def check_send_code_rate(request, destination: str):
    """验证码发送限频：IP 维度 10次/60秒，单个目标 5次/3600秒（防短信轰炸及成本激增）。"""
    ip = _client_ip(request)
    limiter.check(f"otp_send:ip:{ip}", limit=10, window_s=60)
    if destination:
        limiter.check(f"otp_send:dest:{destination.lower().strip()}", limit=5, window_s=3600)


def check_verify_challenge_rate(challenge_id: str):
    """挑战核验限频：单挑战 10次/60秒。"""
    limiter.check(f"chal_verify:{challenge_id}", limit=10, window_s=60)
