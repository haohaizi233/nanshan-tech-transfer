"""Real PostgreSQL migrations/locking tests in a disposable random schema.

Opt in with SMS_TEST_POSTGRES=1 (local Settings defaults), or provide
SMS_TEST_POSTGRES_DSN for a dedicated test database. Never reads business rows.
"""

import os
import uuid
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import MagicMock

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from config import Settings
from core import auth_cache
from core.errors import BizError
from modules.security import service
from modules.security import sms_gateway as gateway
from modules.security.provider import MockSmsProvider
from modules.security.sms_risk import DecisionAction, RiskDecision


@pytest.fixture
def pg(monkeypatch):
    if not os.getenv("SMS_TEST_POSTGRES") and not os.getenv("SMS_TEST_POSTGRES_DSN"):
        pytest.skip("real PostgreSQL requires explicit SMS_TEST_POSTGRES=1 or DSN")
    dsn = os.getenv("SMS_TEST_POSTGRES_DSN")
    kwargs = (
        {}
        if dsn
        else {
            k: Settings.model_fields[v].default
            for k, v in [("host", "DB_HOST"), ("port", "DB_PORT"), ("user", "DB_USER"), ("password", "DB_PASSWORD")]
        }
    )
    kwargs.update(dbname="postgres") if not dsn else None

    def connect():
        return psycopg2.connect(dsn or "", **kwargs, connect_timeout=3, cursor_factory=RealDictCursor)

    schema = "sms_test_" + uuid.uuid4().hex
    conn = connect()
    conn.autocommit = True
    with conn.cursor() as c:
        c.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        c.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        c.execute("""
        CREATE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN NEW.updated_at=NOW(); RETURN NEW; END; $$;
        CREATE TABLE app_user(id BIGINT PRIMARY KEY,status TEXT DEFAULT 'active',deleted_at TIMESTAMPTZ);
        CREATE TABLE user_credential(user_id BIGINT PRIMARY KEY,username TEXT,phone TEXT,status TEXT DEFAULT 'active',
          password_hash TEXT,password_configured BOOLEAN DEFAULT true,created_at TIMESTAMPTZ DEFAULT NOW());
        CREATE TABLE user_role(user_id BIGINT,role_code TEXT);
        CREATE TABLE organization_membership(user_id BIGINT,role TEXT,status TEXT);
        CREATE TABLE auth_session(user_id BIGINT,status TEXT,revoked_at TIMESTAMPTZ);
        CREATE TABLE audit_log(actor_user_id BIGINT,actor_user_no TEXT,action TEXT,resource_type TEXT,
          resource_id TEXT,details JSONB,ip_address TEXT,request_id TEXT,created_at TIMESTAMPTZ DEFAULT NOW());
        """)
        for name in ["033_unified_account_security.sql", "034_sms_security_gateway.sql"]:
            migration = (Path(__file__).parents[1] / "migrations" / "pg" / name).read_text(encoding="utf-8")
            c.execute(migration.replace("public.", schema + "."))
        c.execute("INSERT INTO app_user(id) VALUES (1)")
        c.execute(
            "INSERT INTO user_credential(user_id,username,phone,password_hash) VALUES(1,'user1','13800138000','old')"
        )
        c.execute(
            "INSERT INTO account_contact(user_id,contact_type,normalized_value,verified_at,verification_method) VALUES(1,'phone','13800138000',NOW(),'sms')"
        )
        c.execute("INSERT INTO auth_session VALUES(1,'active',NULL)")

    @contextmanager
    def cursor(commit=False):
        own = connect()
        try:
            with own.cursor() as c:
                c.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
                yield c
                if commit:
                    own.commit()
                else:
                    own.rollback()
        except Exception:
            own.rollback()
            raise
        finally:
            own.close()

    import db

    monkeypatch.setattr(service, "get_cursor", cursor)
    monkeypatch.setattr(gateway, "get_cursor", cursor)
    monkeypatch.setattr(db, "get_cursor", cursor)
    monkeypatch.setattr(gateway.settings, "SMS_ENABLED", True)
    auth_cache.clear()
    yield cursor
    assert schema.startswith("sms_test_") and len(schema) == 41
    with conn.cursor() as c:
        c.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
    conn.close()
    auth_cache.clear()


@pytest.fixture
def sender(monkeypatch):
    provider = MockSmsProvider()
    monkeypatch.setattr(gateway, "get_sms_provider", lambda: provider)
    engine = MagicMock()
    engine.reserve.return_value = RiskDecision(DecisionAction.ALLOW)
    return provider, engine


def start(sender):
    provider, engine = sender
    cid = str(uuid.uuid4())
    gateway.start_sms_recovery("13800138000", cid, gateway.SendContext("1.1.1.1", "device", "request"), engine)
    return cid, provider.get_last_code("13800138000")


def test_real_recovery_and_old_session_version(pg, sender):
    from core.middleware import _user_session_version

    assert _user_session_version(1) == 1
    cid, code = start(sender)
    assert code is not None
    grant = service.verify_recovery_challenge(cid, code)["recoveryGrant"]
    service.complete_password_recovery(grant, "NewPassword123!")
    assert _user_session_version(1) == 2
    with pg() as c:
        c.execute("SELECT status FROM auth_challenge WHERE id=%s", (cid,))
        assert c.fetchone()["status"] == "consumed"
        c.execute("SELECT status FROM auth_session WHERE user_id=1")
        assert c.fetchone()["status"] == "revoked"
    with pytest.raises(BizError):
        service.complete_password_recovery(grant, "AnotherPassword123!")


def test_attempts_survive_transactions_and_lock(pg, sender):
    cid, code = start(sender)
    for i in range(5):
        with pytest.raises(BizError):
            service.verify_recovery_challenge(cid, "wrong")
    with pg() as c:
        c.execute("SELECT attempt_count,status FROM auth_challenge WHERE id=%s", (cid,))
        assert dict(c.fetchone()) == {"attempt_count": 5, "status": "locked"}
    with pytest.raises(BizError):
        service.verify_recovery_challenge(cid, code)


def test_parallel_challenge_consumption_only_one_grant(pg, sender):
    cid, code = start(sender)

    def verify(i):
        try:
            return service.verify_recovery_challenge(cid, code)
        except BizError:
            return None

    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(verify, range(16)))
    assert sum(v is not None for v in results) == 1


@pytest.mark.parametrize(
    "change",
    [
        "UPDATE app_user SET status='disabled'",
        "UPDATE app_user SET deleted_at=NOW()",
        "UPDATE user_credential SET status='disabled'",
        "UPDATE user_credential SET password_configured=false",
        "UPDATE account_contact SET verified_at=NULL",
        "UPDATE account_contact SET status='revoked'",
        "UPDATE account_contact SET verification_method='legacy_unknown'",
        "INSERT INTO user_role VALUES(1,'admin')",
        "INSERT INTO organization_membership VALUES(1,'admin','active')",
    ],
)
def test_ineligible_business_account_never_calls_provider(pg, sender, change):
    with pg(commit=True) as c:
        c.execute(change)
    _cid, code = start(sender)
    assert code is None
    sender[1].reserve.assert_not_called()
    with pg() as c:
        c.execute("SELECT COUNT(*) AS n FROM auth_challenge")
        assert c.fetchone()["n"] == 0


def test_expired_challenge_and_grant_real_db(pg, sender):
    cid, code = start(sender)
    with pg(commit=True) as c:
        c.execute("UPDATE auth_challenge SET expires_at=NOW()-INTERVAL '1 second' WHERE id=%s", (cid,))
    with pytest.raises(BizError):
        service.verify_recovery_challenge(cid, code)
    with pg() as c:
        c.execute("SELECT status FROM auth_challenge WHERE id=%s", (cid,))
        assert c.fetchone()["status"] == "expired"


def test_account_revoked_after_issuance_cannot_verify(pg, sender):
    cid, code = start(sender)
    with pg(commit=True) as c:
        c.execute("UPDATE app_user SET status='disabled'")
    with pytest.raises(BizError):
        service.verify_recovery_challenge(cid, code)


def test_real_redis_postgres_concurrent_requests_send_once(pg, sender):
    url = os.getenv("SMS_TEST_REDIS_URL")
    if not url:
        pytest.skip("set SMS_TEST_REDIS_URL")
    import redis

    from modules.security.sms_risk import SmsRiskEngine

    r = redis.Redis.from_url(url, decode_responses=True, protocol=2)
    prefix = "sms:test:combined:" + uuid.uuid4().hex + ":"
    engine = SmsRiskEngine(r, secret="s" * 32, prefix=prefix)

    def send(i):
        try:
            gateway.start_sms_recovery(
                "13800138000", str(uuid.uuid4()), gateway.SendContext("1.1.1.1", str(i), "r"), engine
            )
            return True
        except BizError:
            return False

    try:
        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(send, range(24)))
        assert sum(results) == 1
        assert len(sender[0].sent_messages) == 1
        with pg() as c:
            c.execute("SELECT COUNT(*) AS n FROM auth_challenge")
            assert c.fetchone()["n"] == 1
    finally:
        keys = list(r.scan_iter(prefix + "*"))
        if keys:
            r.delete(*keys)


def test_phone_binding_uses_gateway_and_single_consumption(pg, sender):
    provider, engine = sender
    result = gateway.start_sms_binding(1, "13900139000", gateway.SendContext("ip", "dev", "r"), engine)
    cid = result["challengeId"]
    code = provider.get_last_code("13900139000")
    assert engine.reserve.call_count == 1
    assert code
    service.verify_and_bind_contact(1, cid, code, "13900139000")
    with pytest.raises(BizError):
        service.verify_and_bind_contact(1, cid, code, "13900139000")
    with pg() as c:
        c.execute("SELECT verification_method FROM account_contact WHERE status='active'")
        assert c.fetchone()["verification_method"] == "sms"


def test_durable_queue_parallel_claim_only_once(pg, sender):
    from unittest.mock import patch

    cid = str(uuid.uuid4())
    gateway.enqueue_recovery_task("unknown", "sms", cid, gateway.SendContext("ip", None, "r"))
    with patch.object(gateway, "run_recovery_task") as worker:
        with ThreadPoolExecutor(max_workers=8) as pool:
            claims = list(pool.map(lambda _: gateway.run_queued_recovery_task(cid), range(16)))
        assert sum(claims) == 1 and worker.call_count == 1
    with pg() as c:
        c.execute("SELECT state FROM security_delivery_request WHERE id=%s", (cid,))
        assert c.fetchone()["state"] == "finished"


def test_unknown_provider_result_keeps_challenge_and_quota(pg, sender):
    from modules.security.provider import ProviderError

    provider, engine = sender
    provider.send_task = MagicMock(side_effect=ProviderError("timeout", outcome_unknown=True))
    with pytest.raises(ProviderError):
        start(sender)
    engine.transition.assert_called_once()
    assert engine.transition.call_args.args[1] == "unknown"
    with pg() as c:
        c.execute("SELECT status,send_state FROM auth_challenge")
        assert dict(c.fetchone()) == {"status": "pending", "send_state": "unknown"}
