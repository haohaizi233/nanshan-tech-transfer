#!/usr/bin/env python3
"""Quick smoke test for core modules."""
import sys
sys.path.insert(0, ".")

# Test auth_cache
from core.auth_cache import cached, invalidate_user, _cache, _lock
with _lock:
    _cache.clear()

call_count = 0
def fn():
    global call_count
    call_count += 1
    return "value"

r1 = cached(("user", 1), fn)
r2 = cached(("user", 1), fn)
assert r1 == "value" and r2 == "value" and call_count == 1, f"cached failed: {call_count}"

invalidate_user(1)
cached(("user", 1), fn)
assert call_count == 2, f"invalidate failed: {call_count}"
print("auth_cache: PASSED")

# Test file_token
from core.file_token import generate_file_token, verify_file_token
token = generate_file_token(user_id=42, file_id=7, ttl_seconds=300)
assert verify_file_token(token, file_id=7) == 42
assert verify_file_token(token, file_id=99) is None
assert verify_file_token("", file_id=7) is None
print("file_token: PASSED")

# Test rate_limit (use check_user_rate which takes user_id directly)
from core.rate_limit import check_user_rate, _check, _buckets, _bucket_lock
from core.errors import BizError
with _bucket_lock:
    _buckets.clear()
for _ in range(3):
    check_user_rate(999, "test", limit=3, window_s=60)
try:
    check_user_rate(999, "test", limit=3, window_s=60)
    assert False, "should have raised"
except BizError:
    pass
print("rate_limit: PASSED")

print("\nALL UNIT TESTS PASSED")