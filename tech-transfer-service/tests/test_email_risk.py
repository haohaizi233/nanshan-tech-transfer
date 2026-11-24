"""EmailRiskEngine 真实 Redis Lua 多维原子风控与 SecurityRateLimiter 严格 Fail-Closed 测试。"""

from __future__ import annotations

import os
import threading
import uuid
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from core.errors import BizError
from modules.security.email_risk import PUBLIC_EMAIL_DOMAINS, DecisionAction, EmailRiskEngine
from modules.security.rate_limiter import SecurityRateLimiter

REDIS_URL = os.getenv("SMS_TEST_REDIS_URL")


def _risk_config(**overrides):
    data = {
        "APP_ENV": "production",
        "is_production_like": True,
        "REDIS_ENABLED": True,
        "REDIS_URL": REDIS_URL or "redis://127.0.0.1:6379/15",
        "JWT_SECRET": "email-risk-test-jwt-secret-key-32bytes!",
        "EMAIL_RISK_HMAC_SECRET": "email-risk-hmac-secret-32bytes!",
        "SMS_RISK_HMAC_SECRET": "sms-risk-hmac-secret-32bytes!",
        "SMS_BUSINESS_TIMEZONE": "Asia/Shanghai",
        "EMAIL_RISK_ENGINE_ENABLED": True,
        "EMAIL_REQUIRE_VERIFIED_CONTACT": True,
        "EMAIL_CODE_TTL_SECONDS": 300,
        "EMAIL_COOLDOWN_SECONDS": 60,
        "EMAIL_LIMIT_10M": 3,
        "EMAIL_LIMIT_1H": 5,
        "EMAIL_LIMIT_DAY": 10,
        "EMAIL_IP_LIMIT_1M": 10,
        "EMAIL_IP_LIMIT_1H": 30,
        "EMAIL_IP_LIMIT_DAY": 100,
        "EMAIL_ACCOUNT_LIMIT_1H": 5,
        "EMAIL_ACCOUNT_LIMIT_DAY": 10,
        "EMAIL_DEVICE_LIMIT_1H": 5,
        "EMAIL_DEVICE_LIMIT_DAY": 15,
        "EMAIL_IP_DISTINCT_LIMIT_1H": 3,
        "EMAIL_DEVICE_DISTINCT_LIMIT_10M": 3,
        "EMAIL_GLOBAL_DAILY_BUDGET": 5000,
        "EMAIL_DOMAIN_ANOMALY_LIMIT_10M": 3,
    }
    data.update(overrides)
    return SimpleNamespace(**data)


@pytest.fixture
def live_redis():
    if not REDIS_URL:
        pytest.skip("SMS_TEST_REDIS_URL not configured")
    import redis

    client = redis.Redis.from_url(REDIS_URL, decode_responses=True, protocol=2)
    client.ping()
    prefix = f"email:{{gateway}}:test:{uuid.uuid4().hex[:10]}:"
    yield client, prefix
    for k in client.scan_iter(match=prefix + "*"):
        client.delete(k)
    client.close()


def test_email_risk_pii_free_keys_and_rule_catalog(live_redis):
    client, prefix = live_redis
    engine = EmailRiskEngine(redis_client=client, config=_risk_config(), prefix=prefix)
    rules = {r.rule_id for r in engine.rule_catalog()}
    assert {
        "email.cooldown",
        "email.10m",
        "email.ip.distinct_email",
        "email.device.distinct_email",
        "email.global.day",
        "email.domain.anomaly_10m",
    }.issubset(rules)

    raw_email = "secret-alice@corp-example.cn"
    raw_ip = "203.0.113.88"
    res = engine.check_request(raw_ip, "acct_777", "dev_888", email=raw_email)
    assert res.action == DecisionAction.ALLOW
    keys = list(client.scan_iter(match=prefix + "*"))
    assert keys
    joined = "|".join(keys)
    assert raw_email not in joined
    assert raw_ip not in joined
    assert "acct_777" not in joined


def test_email_risk_cooldown_windows_distinct_and_public_domain_allowlist(live_redis):
    client, prefix = live_redis
    # 1. Cooldown + equal-timestamp multi-request windows + global daily budget
    cfg = _risk_config(EMAIL_DOMAIN_ANOMALY_LIMIT_10M=2, EMAIL_IP_DISTINCT_LIMIT_1H=2)
    engine = EmailRiskEngine(redis_client=client, config=cfg, prefix=prefix)

    r1 = engine.reserve("target@custom-corp.cn", "acct-1", "10.1.1.1", "dev-1", "res-1")
    assert r1.action == DecisionAction.ALLOW
    r_dup = engine.reserve("target@custom-corp.cn", "acct-1", "10.1.1.1", "dev-1", "res-1")
    assert r_dup.rule_id == "email.task.duplicate"

    # 未完成状态转换前（reserved/unknown），同一目标触发 email.pending_outcome 保守拦截
    r_pending = engine.reserve("target@custom-corp.cn", "acct-1", "10.1.1.1", "dev-1", "res-2")
    assert r_pending.action == DecisionAction.THROTTLE
    assert r_pending.rule_id == "email.pending_outcome"

    # 当 res-1 明确转为 accepted 清除 pending_outcome 后，下一次发送受 60s 冷却控制
    assert engine.transition("res-1", "accepted") is True
    r_cool = engine.reserve("target@custom-corp.cn", "acct-1", "10.1.1.1", "dev-1", "res-3")
    assert r_cool.action == DecisionAction.THROTTLE
    assert r_cool.rule_id == "email.cooldown"

    # 2. Public email domains (qq.com, 163.com, outlook.com, gmail.com) NEVER trigger domain anomaly limit
    assert {"qq.com", "163.com", "outlook.com", "gmail.com"}.issubset(PUBLIC_EMAIL_DOMAINS)
    for idx in range(4):
        d_pub = engine.check_request(f"198.51.100.{idx}", f"a{idx}", f"d{idx}", email=f"u{idx}@qq.com")
        assert d_pub.action == DecisionAction.ALLOW

    # 3. Non-public custom domain bursts trigger email.domain.anomaly_10m (limit=2 -> 1st/2nd allow, 3rd throttle)
    assert engine.check_request("192.0.2.1", "pa1", "pd1", email="a@custom-org.cn").action == DecisionAction.ALLOW
    assert engine.check_request("192.0.2.2", "pa2", "pd2", email="b@custom-org.cn").action == DecisionAction.ALLOW
    blocked = engine.check_request("192.0.2.3", "pa3", "pd3", email="c@custom-org.cn")
    assert blocked.action == DecisionAction.THROTTLE
    assert blocked.rule_id == "email.domain.anomaly_10m"

    # 4. IP targeting > limit distinct emails -> CHALLENGE (limit=2 -> 1st/2nd allow, 3rd challenge)
    ip_shared = "192.0.2.99"
    assert engine.check_request(ip_shared, "u1", "dev-a", email="one@qq.com").action == DecisionAction.ALLOW
    assert engine.check_request(ip_shared, "u2", "dev-b", email="two@163.com").action == DecisionAction.ALLOW
    chal = engine.check_request(ip_shared, "u3", "dev-c", email="three@gmail.com")
    assert chal.action == DecisionAction.CHALLENGE
    assert chal.rule_id == "email.ip.distinct_email"


def test_email_risk_noscript_reload_and_24_thread_concurrency(live_redis):
    client, prefix = live_redis
    engine = EmailRiskEngine(redis_client=client, config=_risk_config(), prefix=prefix)

    # Flush Redis Lua script cache to force NoScriptError reload
    client.script_flush()
    decision = engine.check_request("192.0.2.50", "acct-ns", "dev-ns", email="ns@qq.com")
    assert decision.action == DecisionAction.ALLOW

    # 24 concurrent reservations for the same email: strictly 1 ALLOW!
    results: list[DecisionAction] = []
    lock = threading.Lock()
    barrier = threading.Barrier(24)

    def _worker(i: int):
        barrier.wait(timeout=5)
        d = engine.reserve(
            "race@qq.com",
            f"race-acct-{i}",
            f"10.0.0.{i}",
            f"dev-{i}",
            f"race-res-{i}-{uuid.uuid4().hex[:6]}",
        )
        with lock:
            results.append(d.action)

    threads = [threading.Thread(target=_worker, args=(idx,)) for idx in range(24)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert results.count(DecisionAction.ALLOW) == 1
    assert len(results) == 24


def test_email_risk_and_rate_limiter_fail_closed_on_redis_failure():
    class _BrokenRedis:
        def time(self):
            raise ConnectionError("redis down")

    engine = EmailRiskEngine(redis_client=_BrokenRedis(), config=_risk_config())
    d_req = engine.check_request("1.1.1.1", "u1", "d1", email="a@b.cn")
    d_res = engine.reserve("a@b.cn", "u1", "1.1.1.1", "d1", "r1")
    assert d_req.action == DecisionAction.DENY
    assert d_req.rule_id == "email.redis.unavailable"
    assert d_res.action == DecisionAction.DENY
    assert d_res.rule_id == "email.redis.unavailable"

    # SecurityRateLimiter 在 production/staging 或 REDIS_ENABLED=True 时严禁降级进程内存
    from config import settings as _settings

    with (
        patch.object(_settings, "APP_ENV", "production"),
        patch.object(_settings, "REDIS_ENABLED", False),
    ):
        rl = SecurityRateLimiter()
        with pytest.raises(BizError) as exc_info:
            rl.check("fail_closed_prod", limit=5, window_s=60)
        assert exc_info.value.http_status == 503
        assert exc_info.value.code == "TT_COMMON_50301"

    with (
        patch.object(_settings, "APP_ENV", "local"),
        patch.object(_settings, "REDIS_ENABLED", True),
        patch.object(_settings, "REDIS_URL", "redis://127.0.0.1:1/0"),
    ):
        rl_redis = SecurityRateLimiter()
        with pytest.raises(BizError) as exc_info:
            rl_redis.check("fail_closed_redis", limit=5, window_s=60)
        assert exc_info.value.http_status == 503
