"""E10: 核心模块 pytest 单元测试（不需要 DB/网络）。

覆盖模块：
- core.auth_cache（缓存读写 + TTL 过期 + invalidate + 条目上限）
- core.file_token（HMAC 签名生成 + 校验 + 过期 + file_id 匹配）
- core.rate_limit（滑动窗口限流 + 超限抛异常）
"""
import time
from unittest.mock import patch

import pytest


# ── auth_cache ──────────────────────────────────────────────


class TestAuthCache:
    """auth_cache 纯内存缓存测试。"""

    def setup_method(self):
        """每个测试前清空缓存。"""
        from core import auth_cache
        with auth_cache._lock:
            auth_cache._cache.clear()

    def test_cached_hit(self):
        """首次调用 fn 并缓存结果。"""
        from core.auth_cache import cached
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return "value1"

        result1 = cached(("user", 1), fn)
        result2 = cached(("user", 1), fn)
        assert result1 == "value1"
        assert result2 == "value1"
        assert call_count == 1  # fn 只调用一次

    def test_cached_different_keys(self):
        """不同 key 独立缓存。"""
        from core.auth_cache import cached
        result1 = cached(("user", 1), lambda: "a")
        result2 = cached(("user", 2), lambda: "b")
        assert result1 == "a"
        assert result2 == "b"

    def test_cached_none_value(self):
        """fn 返回 None 也缓存（防穿透）。"""
        from core.auth_cache import cached
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return None

        cached(("user", 1), fn)
        cached(("user", 1), fn)
        assert call_count == 1

    def test_invalidate_user(self):
        """invalidate_user 清除该用户所有缓存。"""
        from core.auth_cache import cached, invalidate_user
        call_count = 0

        def fn():
            nonlocal call_count
            call_count += 1
            return "v"

        cached(("auth", 42), fn)
        cached(("role", 42), fn)
        cached(("auth", 99), fn)
        assert call_count == 3

        invalidate_user(42)
        cached(("auth", 42), fn)  # 应重新调用
        cached(("role", 42), fn)  # 应重新调用
        cached(("auth", 99), fn)  # 不应重新调用
        assert call_count == 5

    def test_max_entries_eviction(self):
        """超过 _MAX_ENTRIES 时淘汰旧条目。"""
        from core.auth_cache import cached, _MAX_ENTRIES, _cache, _lock
        for i in range(_MAX_ENTRIES + 100):
            cached(("overflow", i), lambda i=i: i)
        with _lock:
            assert len(_cache) <= _MAX_ENTRIES


# ── file_token ──────────────────────────────────────────────


class TestFileToken:
    """file_token HMAC 签名测试。"""

    def test_generate_and_verify(self):
        """生成并校验 token，返回正确 user_id。"""
        from core.file_token import generate_file_token, verify_file_token
        token = generate_file_token(user_id=42, file_id=7, ttl_seconds=300)
        assert verify_file_token(token, file_id=7) == 42

    def test_wrong_file_id(self):
        """file_id 不匹配返回 None。"""
        from core.file_token import generate_file_token, verify_file_token
        token = generate_file_token(user_id=42, file_id=7, ttl_seconds=300)
        assert verify_file_token(token, file_id=99) is None

    def test_expired_token(self):
        """过期 token 返回 None。"""
        from core.file_token import generate_file_token, verify_file_token
        token = generate_file_token(user_id=42, file_id=7, ttl_seconds=0)
        time.sleep(0.01)
        assert verify_file_token(token, file_id=7) is None

    def test_tampered_token(self):
        """篡改的 token 返回 None。"""
        from core.file_token import generate_file_token, verify_file_token
        token = generate_file_token(user_id=42, file_id=7, ttl_seconds=300)
        tampered = token[:-5] + "xxxxx"
        assert verify_file_token(tampered, file_id=7) is None

    def test_empty_token(self):
        """空 token 返回 None。"""
        from core.file_token import verify_file_token
        assert verify_file_token("", file_id=7) is None
        assert verify_file_token("   ", file_id=7) is None

    def test_malformed_token(self):
        """格式错误的 token 返回 None。"""
        from core.file_token import verify_file_token
        assert verify_file_token("not-a-token", file_id=7) is None
        assert verify_file_token("a:b:c", file_id=7) is None  # 只有 3 段


# ── rate_limit ──────────────────────────────────────────────


class TestRateLimit:
    """rate_limit 滑动窗口限流测试。"""

    def setup_method(self):
        """每个测试前清空桶。"""
        from core import rate_limit
        with rate_limit._bucket_lock:
            rate_limit._buckets.clear()

    def test_under_limit_passes(self):
        """限流阈值内不抛异常。"""
        from core.rate_limit import check_user_rate
        for _ in range(5):
            check_user_rate(1001, "login", limit=10, window_s=60)

    def test_over_limit_raises(self):
        """超过限流阈值抛 BizError。"""
        from core.rate_limit import check_user_rate
        from core.errors import BizError
        for _ in range(3):
            check_user_rate(1002, "test", limit=3, window_s=60)
        with pytest.raises(BizError):
            check_user_rate(1002, "test", limit=3, window_s=60)

    def test_different_keys_independent(self):
        """不同 key 独立计数。"""
        from core.rate_limit import check_user_rate
        for _ in range(3):
            check_user_rate(1003, "test", limit=3, window_s=60)
        # 不同用户不受影响
        check_user_rate(1004, "test", limit=3, window_s=60)