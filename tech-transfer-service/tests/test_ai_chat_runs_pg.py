"""Opt-in real PostgreSQL isolation tests, never use application DB settings."""

import concurrent.futures
import multiprocessing
import os
import uuid
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import psycopg2
import pytest
from psycopg2 import sql
from psycopg2.extras import RealDictCursor

TEST_DSN = os.environ.get("AI_CHAT_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not TEST_DSN, reason="AI_CHAT_TEST_DATABASE_URL is not explicitly configured")


@contextmanager
def isolated_cursor(dsn, schema, commit=False):
    connection = psycopg2.connect(dsn, cursor_factory=RealDictCursor)
    try:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
            yield cursor
        if commit:
            connection.commit()
    finally:
        connection.close()


def claim_in_process(dsn, schema):
    from modules.ai import chat_runs

    with patch.object(chat_runs, "get_cursor", lambda commit=False: isolated_cursor(dsn, schema, commit)):
        run = chat_runs.claim_one(str(uuid.uuid4()))
        return (run["user_id"], run["turn_id"]) if run else None


@pytest.fixture
def database(request):
    from modules.ai import chat_runs

    schema = "ai_chat_test_" + uuid.uuid4().hex
    connection = psycopg2.connect(TEST_DSN)
    connection.autocommit = True
    with connection.cursor() as cursor:
        cursor.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        cursor.execute(sql.SQL("SET search_path TO {}").format(sql.Identifier(schema)))
        cursor.execute(
            "CREATE TABLE app_user(id BIGINT PRIMARY KEY, status TEXT DEFAULT 'active', deleted_at TIMESTAMPTZ)"
        )
        cursor.execute("INSERT INTO app_user(id) SELECT generate_series(1, 12)")
        migration_dir = Path(__file__).resolve().parents[1] / "migrations" / "pg"
        migrations = ["023_ai_chat_history.sql", "026_ai_chat_turns.sql"]
        if getattr(request, "param", True):
            migrations.append("029_ai_chat_execution.sql")
        for name in migrations:
            cursor.execute((migration_dir / name).read_text(encoding="utf-8").replace("public.", schema + "."))

    def cursor_factory(commit=False):
        return isolated_cursor(TEST_DSN, schema, commit)

    try:
        with patch.object(chat_runs, "get_cursor", cursor_factory), patch.object(chat_runs, "require_ready"):
            yield chat_runs, cursor_factory, schema
    finally:
        with connection.cursor() as cursor:
            cursor.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        connection.close()


def test_same_key_conflict_and_queue_limit(database):
    runs, _cursor_factory, _schema = database
    from core.errors import BizError

    first = runs.submit_run(1, "turn-1", "hello")
    assert runs.submit_run(1, "turn-1", " hello ") == first
    with pytest.raises(BizError) as conflict_error:
        runs.submit_run(1, "turn-1", "changed")
    assert conflict_error.value.http_status == 409
    active = runs.claim_one("worker")
    for number in range(2, 5):
        runs.submit_run(1, f"turn-{number}", "question")
    with pytest.raises(BizError) as queue_error:
        runs.submit_run(1, "excess", "question")
    assert queue_error.value.http_status == 429
    assert active["turn_id"] == "turn-1"
    assert runs.claim_one("second-worker") is None


def test_cross_process_claims_enforce_global_slots_and_user_serialization(database):
    runs, cursor_factory, schema = database
    for user_id in range(1, 7):
        runs.submit_run(user_id, "first", "hello")
    runs.submit_run(1, "second", "later")
    with concurrent.futures.ProcessPoolExecutor(max_workers=2, mp_context=multiprocessing.get_context("spawn")) as pool:
        claims = list(pool.map(claim_in_process, [TEST_DSN] * 6, [schema] * 6))
    accepted = [claim for claim in claims if claim]
    assert len(accepted) == 4
    assert len({claim[0] for claim in accepted}) == 4
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_turn WHERE status = 'running'")
        assert cursor.fetchone()["count"] == 4


def test_clear_tombstone_and_late_worker_cannot_restore_text(database):
    runs, cursor_factory, _schema = database
    from core.errors import BizError

    runs.submit_run(1, "old", "private text")
    run = runs.claim_one("worker")
    assert runs.clear_runs(1)["generation"] == 1
    assert runs.finish_run(run, result={"success": True, "message": "late", "data": []}) is False
    assert runs.renew_run(run) is False
    with pytest.raises(BizError) as error:
        runs.submit_run(1, "old", "private text")
    assert error.value.http_status == 409
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_message")
        assert cursor.fetchone()["count"] == 0
        cursor.execute("SELECT * FROM ai_chat_tombstone")
        tombstone = cursor.fetchone()
        assert set(tombstone) == {"user_id", "turn_id", "request_hash", "expires_at"}


def test_success_pair_is_atomic_and_next_fifo_run_receives_context(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "first", "hello")
    first = runs.claim_one("worker")
    runs.submit_run(1, "second", "follow up")
    result = {
        "success": True,
        "message": "answer",
        "data": [{"id": 3, "card_type": "achievement", "title": "card"}],
        "queryPlan": {"intent": "search_achievement", "keywords": ["water"]},
    }
    assert runs.finish_run(first, result=result)
    assert not runs.finish_run(first, result=result)
    second = runs.claim_one("worker")
    assert second["turn_id"] == "second"
    assert second["context_snapshot"]["queryPlan"] == {"intent": "search_achievement", "keywords": ["water"]}
    assert second["context_snapshot"]["cards"][0]["id"] == 3
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_message")
        assert cursor.fetchone()["count"] == 2


def test_expired_lease_is_failed_and_never_replayed(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "first", "hello")
    active = runs.claim_one("worker")
    with cursor_factory(commit=True) as cursor:
        cursor.execute("UPDATE ai_chat_turn SET lease_until = clock_timestamp() - interval '1 second'")
    assert runs.reap_runs() == 1
    assert runs.get_run(1, "first")["status"] == "failed"
    assert runs.claim_one("replacement") is None
    assert not runs.finish_run(active, result={"success": True, "message": "late", "data": []})


def test_reference_is_bound_to_current_user_and_generation(database):
    runs, cursor_factory, _schema = database
    from core.errors import BizError

    with cursor_factory(commit=True) as cursor:
        cursor.execute("""INSERT INTO ai_chat_message(user_id, role, content, cards) VALUES
                          (2, 'assistant', 'other', '[{"card_type":"achievement","id":3}]') RETURNING id""")
        message_id = cursor.fetchone()["id"]
    with pytest.raises(BizError) as error:
        runs.submit_run(1, "forged", "介绍", {"messageId": message_id, "cardType": "achievement", "cardId": 3})
    assert error.value.http_status == 400


def test_lease_expiring_during_message_insert_rolls_back_success_pair(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "first", "hello")
    active = runs.claim_one("worker")
    with cursor_factory(commit=True) as cursor:
        cursor.execute("UPDATE ai_chat_turn SET lease_until = clock_timestamp() + interval '0.15 seconds'")
        cursor.execute("""CREATE FUNCTION delay_message() RETURNS trigger LANGUAGE plpgsql AS
                          $$ BEGIN PERFORM pg_sleep(0.2); RETURN NEW; END $$""")
        cursor.execute(
            "CREATE TRIGGER delay_message BEFORE INSERT ON ai_chat_message FOR EACH ROW EXECUTE FUNCTION delay_message()"
        )
    assert not runs.finish_run(active, result={"success": True, "message": "too late", "data": []})
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_message")
        assert cursor.fetchone()["count"] == 0


def test_queue_deadline_reaped_without_agent_execution(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "queued", "waiting")
    with cursor_factory(commit=True) as cursor:
        cursor.execute("UPDATE ai_chat_turn SET queue_deadline = clock_timestamp() - interval '1 second'")
    assert runs.claim_one("worker") is None
    assert runs.reap_runs() == 1
    assert runs.get_run(1, "queued")["status"] == "failed"
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_execution_slot WHERE execution_id IS NOT NULL")
        assert cursor.fetchone()["count"] == 0


def test_clear_and_finish_race_never_resurrects_history(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "old", "private question")
    active = runs.claim_one("worker")
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        finished = pool.submit(runs.finish_run, active, {"success": True, "message": "private answer", "data": []})
        cleared = pool.submit(runs.clear_runs, 1)
        finished.result()
        assert cleared.result()["generation"] == 1
    assert runs.get_run(1, "old") is None
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_message WHERE user_id = 1")
        assert cursor.fetchone()["count"] == 0


def test_disabled_account_cannot_publish_successful_result(database):
    runs, cursor_factory, _schema = database
    runs.submit_run(1, "first", "hello")
    active = runs.claim_one("worker")
    with cursor_factory(commit=True) as cursor:
        cursor.execute("UPDATE app_user SET status = 'disabled' WHERE id = 1")
    assert runs.finish_run(active, result={"success": True, "message": "restricted answer", "data": []})
    assert runs.get_run(1, "first")["status"] == "failed"
    with cursor_factory() as cursor:
        cursor.execute("SELECT content FROM ai_chat_message WHERE role = 'assistant'")
        assert cursor.fetchone()["content"] != "restricted answer"


@pytest.mark.parametrize("database", [False], indirect=True)
def test_legacy_history_and_get_work_without_execution_migration(database):
    from modules.ai import chat_store

    runs, cursor_factory, _schema = database
    with cursor_factory(commit=True) as cursor:
        cursor.execute("INSERT INTO ai_chat_message(user_id, role, content) VALUES (1, 'assistant', 'legacy')")
        cursor.execute("INSERT INTO ai_chat_turn(user_id, turn_id, user_message) VALUES (1, 'old', 'legacy question')")
    with patch.object(chat_store, "get_cursor", cursor_factory):
        history = chat_store.list_messages(1)
        turn = chat_store.get_turn(1, "old")
    assert history[0]["content"] == "legacy"
    assert history[0]["turnId"] is None
    assert history[0]["generation"] == 0
    assert turn["status"] == "running"
    assert runs.has_durable_history(1) is False


def test_reaper_removes_expired_tombstones_without_active_runs(database):
    runs, cursor_factory, _schema = database
    with cursor_factory(commit=True) as cursor:
        cursor.execute(
            "INSERT INTO ai_chat_tombstone(user_id, turn_id, expires_at) VALUES (1, 'old', clock_timestamp() - interval '1 second')"
        )
    assert runs.reap_runs() == 0
    with cursor_factory() as cursor:
        cursor.execute("SELECT count(*) AS count FROM ai_chat_tombstone")
        assert cursor.fetchone()["count"] == 0


def test_latest_query_survives_more_than_twelve_non_search_turns(database):
    from modules.ai.chat_context import load_context

    runs, cursor_factory, _schema = database
    runs.submit_run(1, "search", "water under 50")
    active = runs.claim_one("worker")
    assert runs.finish_run(
        active,
        result={
            "success": True,
            "message": "found",
            "data": [],
            "queryPlan": {"intent": "search_achievement", "keywords": ["water"], "max_price_wan": 50},
        },
    )
    with cursor_factory(commit=True) as cursor:
        cursor.execute("""INSERT INTO ai_chat_turn(user_id, turn_id, status, user_message, reply, assistant_message_id)
                          SELECT 1, 'guide-' || number, 'succeeded', 'how to publish', 'guide', 100 + number
                          FROM generate_series(1, 13) number""")
        context = load_context(cursor, 1, 0)
    assert context["queryPlan"]["max_price_wan"] == 50
    assert len(context["messages"]) == 4
