"""P3-2 & P3-3 实库并发与 Schema Gate 验收测试。"""

from __future__ import annotations

import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest
from fastapi.testclient import TestClient
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

from modules.security.delivery_models import (
    DeliveryStageError,
    DeliveryTaskResult,
    _persist_risk_sync_outcome,
)
from modules.security.maintenance import get_security_maintenance_status, run_security_maintenance_tick
from modules.security.schema_gate import (
    REQUIRED_APPLICATION_SCHEMA_VERSION,
    REQUIRED_SECURITY_SCHEMA_VERSION,
    assert_required_application_schema,
    check_required_application_schema,
)
from modules.security.sms_gateway import (
    SendContext,
    _persist_task_result,
)
from modules.security.sms_gateway import _send as _send_sms
from tests.test_security_provider_execution_right import _BASE_TABLES_SQL

PG_DSN = os.getenv("SMS_TEST_POSTGRES_DSN") or (
    "postgresql://mac:test@127.0.0.1:5432/tech_transfer_test" if os.getenv("SMS_TEST_POSTGRES") == "1" else None
)
MIGRATION_DIR = Path(__file__).resolve().parents[1] / "migrations" / "pg"


def _apply_sql(cur, schema: str, sql_text: str) -> None:
    cleaned = (
        sql_text.replace("BEGIN;", "")
        .replace("COMMIT;", "")
        .replace("'public.auth_challenge'", "'auth_challenge'")
        .replace("public.set_updated_at()", "set_updated_at()")
        .replace("public.", "")
    )
    cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
    cur.execute(cleaned)


@contextmanager
def _pg_schema_cursor(conn, schema: str):
    @contextmanager
    def _factory(commit: bool = False):
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()

    yield _factory


def _setup_security_schema(conn, schema: str) -> None:
    with conn.cursor() as cur:
        cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        _apply_sql(cur, schema, _BASE_TABLES_SQL)
        for fname in (
            "033_unified_account_security.sql",
            "034_sms_security_gateway.sql",
            "035_sms_delivery_diagnostics.sql",
            "036_email_security_gateway.sql",
            "037_phase_r_security_hardening.sql",
            "038_phase_r_final_security.sql",
            "039_phase_r_hotfix.sql",
            "040_registration_sms.sql",
        ):
            _apply_sql(cur, schema, (MIGRATION_DIR / fname).read_text(encoding="utf-8"))
    conn.commit()


@pytest.mark.skipif(not PG_DSN, reason="需要 SMS_TEST_POSTGRES=1 实库环境")
def test_p3_2_stale_worker_cannot_send_or_overwrite_after_ownership_lost():
    """P3-A06/P3-A07: Worker A 领取后失去执行权，恢复执行时无法创建 challenge 或调用 Provider。"""
    schema = f"p3w_{uuid.uuid4().hex[:10]}"
    conn = psycopg2.connect(PG_DSN)
    try:
        _setup_security_schema(conn, schema)
        cid = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("INSERT INTO app_user (user_no) VALUES ('U1') RETURNING id")
            uid = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO account_contact (user_id, contact_type, normalized_value, status, verified_at)
                   VALUES (%s, 'phone', '13800138000', 'active', NOW())""",
                (uid,),
            )
            cur.execute(
                """INSERT INTO security_delivery_request
                   (id, state, channel, purpose, execution_owner, execution_stage, stage_provenance, payload)
                   VALUES (%s, 'processing', 'sms', 'password_recovery', 'worker:A', 'pre_provider', 'explicit', '{}'::jsonb)""",
                (cid,),
            )
        conn.commit()

        # 模拟清理程序或新 Worker 接管，使 worker:A 失去执行权
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute(
                "UPDATE security_delivery_request SET state='expired', execution_owner='reaper' WHERE id=%s",
                (cid,),
            )
        conn.commit()

        provider_calls = 0

        class _SpyProvider:
            provider_name = "mock"

            def send_otp(self, *_args, **_kwargs):
                nonlocal provider_calls
                provider_calls += 1
                raise AssertionError("stale worker must never call provider")

        with _pg_schema_cursor(conn, schema) as factory:
            with (
                patch("modules.security.sms_gateway.get_cursor", factory),
                patch("modules.security.sms_gateway.get_sms_provider", return_value=_SpyProvider()),
                patch("modules.security.sms_gateway.settings.SMS_ENABLED", True),
            ):
                with pytest.raises(DeliveryStageError) as exc_info:
                    _send_sms(
                        uid,
                        "13800138000",
                        "password_recovery",
                        cid,
                        SendContext("127.0.0.1", "dev1", "req1"),
                        engine=None,
                        worker_owner="worker:A",
                    )
                assert exc_info.value.reason_code == "WORKER_OWNERSHIP_LOST"
                assert exc_info.value.request_attempted is False
                assert provider_calls == 0

                # 旧 worker 试图落盘任务结果也必须被 execution_owner 条件拒绝
                stale_res = DeliveryTaskResult(cid, "INTERNAL_ERROR", "send_claim", "WORKER_OWNERSHIP_LOST")
                persisted = _persist_task_result(cid, stale_res, "req1", worker_owner="worker:A")
                assert persisted is False
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


@pytest.mark.skipif(not PG_DSN, reason="需要 SMS_TEST_POSTGRES=1 实库环境")
def test_p3_2_late_risk_sync_outcome_cannot_overwrite_newer_synced_target():
    """P3-A09/P3-A10: 迟到或旧目标的风险协调失败结果不得覆盖已 synced 的新目标，且维护 tick 零发信。"""
    schema = f"p3r_{uuid.uuid4().hex[:10]}"
    conn = psycopg2.connect(PG_DSN)
    try:
        _setup_security_schema(conn, schema)
        cid = str(uuid.uuid4())
        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("INSERT INTO app_user (user_no) VALUES ('U2') RETURNING id")
            uid = cur.fetchone()[0]
            cur.execute(
                """INSERT INTO auth_challenge
                   (id, user_id, purpose, channel, destination_fingerprint, destination_masked, code_hash,
                    status, attempt_count, max_attempts, expires_at, send_state,
                    risk_sync_state, risk_sync_target, risk_sync_claimed_at)
                   VALUES (%s, %s, 'password_recovery', 'sms', 'fp1', '138****8000', 'hash',
                           'pending', 0, 5, NOW() + INTERVAL '5 minutes', 'accepted',
                           'sync_pending', 'accepted', NULL)""",
                (cid, uid),
            )
        conn.commit()

        class _FakeEngine:
            def transition(self, _cid, _target):
                return True

        with _pg_schema_cursor(conn, schema) as factory:
            with patch("modules.security.sms_gateway.cleanup_delivery_tasks"):
                tick = run_security_maintenance_tick(limit=10, sms_engine=_FakeEngine(), cursor_factory=factory)
                assert tick["ok"] is True
                assert tick["summary"]["synced"] == 1
                assert tick["pendingRiskSyncCount"] == 0
                status = get_security_maintenance_status()
                assert status["lastSuccessAt"] is not None
                assert status["pendingRiskSyncCount"] == 0

            # 迟到的旧目标失败写回，不得覆盖 synced
            late_state = _persist_risk_sync_outcome(
                cid,
                "rejected",
                sync_state="retryable_failure",
                error_code="late_timeout",
                cursor_factory=factory,
            )
            assert late_state == "synced"

            with factory() as cur:
                cur.execute("SELECT risk_sync_state, risk_sync_target FROM auth_challenge WHERE id=%s", (cid,))
                row = cur.fetchone()
                assert row["risk_sync_state"] == "synced"
                assert row["risk_sync_target"] == "accepted"
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()


@pytest.mark.skipif(not PG_DSN, reason="需要 SMS_TEST_POSTGRES=1 实库环境")
def test_p3_3_application_schema_gate_and_health_version_endpoint():
    """P3-A11/P3-A12: 应用 Schema Gate 042 校验与脱敏版本端点验证。"""
    assert REQUIRED_SECURITY_SCHEMA_VERSION == "040"
    assert REQUIRED_APPLICATION_SCHEMA_VERSION == "042"

    schema = f"p3s_{uuid.uuid4().hex[:10]}"
    conn = psycopg2.connect(PG_DSN)
    try:
        with conn.cursor() as cur:
            cur.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.commit()

        with _pg_schema_cursor(conn, schema) as factory:
            with factory() as cur:
                res_empty = check_required_application_schema(cur)
                assert res_empty["ok"] is False
                assert "capital_institution_icon.institution_id" in res_empty["missing_columns"]
                with pytest.raises(RuntimeError):
                    assert_required_application_schema(cur)

        with conn.cursor() as cur:
            cur.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
            cur.execute("CREATE TABLE institution (id BIGINT PRIMARY KEY)")
            cur.execute("CREATE TABLE ai_chat_turn (turn_id TEXT, status TEXT)")
            cur.execute("CREATE TABLE ai_task (id BIGINT, task_type TEXT, status TEXT)")
            _apply_sql(cur, schema, (MIGRATION_DIR / "041_capital_module_icons.sql").read_text(encoding="utf-8"))
            cur.execute(
                """CREATE TABLE capital_institution_icon (
                       institution_id BIGINT PRIMARY KEY REFERENCES institution(id) ON DELETE CASCADE,
                       png BYTEA NOT NULL
                   )"""
            )
        conn.commit()

        with _pg_schema_cursor(conn, schema) as factory:
            with factory() as cur:
                assert assert_required_application_schema(cur)["ok"] is True
    finally:
        conn.rollback()
        with conn.cursor() as cur:
            cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(schema)))
        conn.commit()
        conn.close()

    from app import app

    client = TestClient(app)
    resp = client.get("/health/version")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == 0
    assert set(body["data"].keys()) == {"applicationVersion", "gitCommit", "schemaVersion", "buildTime"}
    assert body["data"]["schemaVersion"] == "042"
