"""Real Redis scripts, isolated namespaces, no business data."""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime

import pytest

from config import settings
from modules.security.sms_risk import DecisionAction, SmsRiskEngine, day_bucket


@pytest.fixture
def engine():
    url = os.getenv("SMS_TEST_REDIS_URL")
    if not url:
        pytest.skip("set SMS_TEST_REDIS_URL to an isolated real Redis")
    import redis

    client = redis.Redis.from_url(url, decode_responses=True, socket_timeout=2, protocol=2)
    client.ping()
    namespace = "sms:test:" + uuid.uuid4().hex + ":"
    e = SmsRiskEngine(client, secret="s" * 32, config=settings, prefix=namespace)
    yield e
    keys = list(client.scan_iter(namespace + "*"))
    if keys:
        client.delete(*keys)


def test_midnight_ttl():
    day, ttl = day_bucket(datetime(2026, 11, 17, 15, 59, 59, tzinfo=UTC), "Asia/Shanghai")
    assert day == "2026-11-17" and ttl == 1
    assert day_bucket(datetime(2026, 11, 17, 16, 0, 0, tzinfo=UTC), "Asia/Shanghai")[1] == 86400


def test_concurrent_phone_only_one_send(engine):
    def reserve(i):
        return engine.reserve("13800138000", str(i), "1.1.1.1", str(i), str(i)).action

    with ThreadPoolExecutor(max_workers=12) as pool:
        result = list(pool.map(reserve, range(30)))
    assert result.count(DecisionAction.ALLOW) == 1


def test_quota_release_idempotent_and_unknown_retained(engine):
    assert engine.reserve("13800138000", "a", "1.1.1.1", None, "r1").action == DecisionAction.ALLOW
    assert engine.transition("r1", "unknown")
    assert not engine.transition("r1", "rejected")
    assert engine.transition("r1", "accepted")
    assert engine.transition("r1", "delivered")
    assert not engine.transition("r1", "rejected")
    assert engine.reserve("13800138000", "a", "1.1.1.1", None, "r1").action != DecisionAction.ALLOW


def test_known_reject_releases_daily_budget_once(engine):
    engine.reserve("13800138000", "a", "1.1.1.1", None, "r1")
    assert engine.transition("r1", "rejected")
    assert engine.transition("r1", "rejected")
    budgets = list(engine.redis.scan_iter(engine.prefix + "quota:*"))
    assert budgets and all(int(engine.redis.get(k)) == 0 for k in budgets)


def test_ip_minute_limit_missing_device_still_limited(engine):
    results = [engine.check_request("1.1.1.1", str(i), None) for i in range(11)]
    assert all(r.action == DecisionAction.ALLOW for r in results[:10])
    assert results[-1].action == DecisionAction.THROTTLE


def test_keys_never_contain_raw_pii(engine):
    engine.check_request("1.1.1.1", "13800138000", "my-device", phone="13800138000")
    keys = " ".join(engine.redis.scan_iter(engine.prefix + "*"))
    assert all(v not in keys for v in ["1.1.1.1", "13800138000", "my-device"])


def test_redis_failure_denies():
    class Broken:
        def eval(self, *a):
            raise ConnectionError()

    assert SmsRiskEngine(Broken(), secret="s" * 32).check_request("ip", "account", None).action == DecisionAction.DENY


def _clear_cooldowns(engine):
    keys = list(engine.redis.scan_iter(engine.prefix + "cooldown:*"))
    if keys:
        engine.redis.delete(*keys)


@pytest.mark.parametrize("window,limit", [(600, 3), (3600, 5)])
def test_phone_sliding_window(engine, window, limit):
    engine.config = engine.config.model_copy(
        update={
            "SMS_PHONE_LIMIT_10M": limit if window == 600 else 100,
            "SMS_PHONE_LIMIT_1H": limit if window == 3600 else 100,
            "SMS_ACCOUNT_LIMIT_1H": 100,
        }
    )
    for i in range(limit):
        assert engine.reserve("13800138000", str(i), "ip", None, str(i)).action == DecisionAction.ALLOW
        engine.transition(str(i), "accepted")
        _clear_cooldowns(engine)
    assert engine.reserve("13800138000", "next", "ip", None, "next").action == DecisionAction.THROTTLE


def test_daily_phone_limit_ttl(engine):
    engine.config = engine.config.model_copy(
        update={"SMS_PHONE_LIMIT_10M": 100, "SMS_PHONE_LIMIT_1H": 100, "SMS_IP_LIMIT_1M": 100}
    )
    for i in range(10):
        assert engine.reserve("13800138000", str(i), "ip", None, str(i)).action == DecisionAction.ALLOW
        engine.transition(str(i), "accepted")
        _clear_cooldowns(engine)
    decision = engine.reserve("13800138000", "next", "ip", None, "next")
    assert decision.rule_id == "sms.phone.day"
    keys = list(engine.redis.scan_iter(engine.prefix + "quota:phone:*"))
    assert all(0 < engine.redis.ttl(k) <= 86400 for k in keys)


def test_device_limit_and_soft_nat_diversity(engine):
    engine.config = engine.config.model_copy(update={"SMS_IP_LIMIT_1M": 100})
    for i in range(10):
        assert engine.check_request("ip", str(i), "device").action == DecisionAction.ALLOW
    assert engine.check_request("ip", "next", "device").rule_id.startswith("sms.request.device")
    # Another device behind same NAT remains available.
    assert engine.check_request("ip", "fresh", "fresh-device").action == DecisionAction.ALLOW
    for i in range(10):
        assert engine.check_request("other-ip", str(i), str(i), phone=str(i)).action == DecisionAction.ALLOW
    assert engine.check_request("other-ip", "new", "new", phone="new").action == DecisionAction.CHALLENGE
