"""PostgreSQL-owned chat execution, generation isolation and lease CAS."""

import hashlib
import ipaddress
import json
import uuid
from urllib.parse import urlparse

from psycopg2.extras import Json

from config import settings
from core.errors import BizError, ai_unavailable, conflict
from db import get_cursor
from modules.ai.chat_context import load_context, validate_reference


class _OwnershipLost(Exception):
    pass


_OWNER_PREDICATE = """ AND user_id = %s AND generation = %s AND execution_id = %s AND status = 'running'
    AND lease_until > clock_timestamp() AND execution_deadline > clock_timestamp()
    AND EXISTS (SELECT 1 FROM ai_chat_execution_slot slot WHERE slot.execution_id = ai_chat_turn.execution_id
                AND slot.lease_until > clock_timestamp())"""


def _owner_parameters(run):
    return (run["user_id"], run["generation"], run["execution_id"])


def request_hash(message, reference=None):
    value = {"message": message.strip(), "reference": reference or None}
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()


def run_view(row):
    if not row:
        return None
    result = {
        "turnId": row["turn_id"],
        "status": "running" if row["status"] == "queued" else row["status"],
        "generation": row.get("generation", 0),
        "stage": row.get("stage") or row["status"],
        "stageSeq": row.get("stage_seq", 0),
        "pollAfterMs": 2000,
        "reply": row.get("reply"),
        "cards": row.get("cards"),
        "errorMessage": row.get("error_message"),
        "errorCode": row.get("error_code"),
        "errorStatus": row.get("error_status"),
        "messageId": row.get("assistant_message_id"),
    }
    result["referenceSupported"] = settings.AI_CHAT_RUNS_ENABLED
    for source, target in (("created_at", "createdAt"), ("updated_at", "updatedAt")):
        value = row.get(source)
        result[target] = value.isoformat() if value else None
    return result


def configuration_ready():
    if not settings.AI_INTERNAL_SERVICE_KEY or not settings.AI_CHAT_STREAM_URL:
        return False
    parsed = urlparse(settings.AI_CHAT_STREAM_URL)
    if parsed.scheme not in ("http", "https") or parsed.username or parsed.password or parsed.query or parsed.fragment:
        return False
    if parsed.path != "/internal/ai/chat/stream":
        return False
    host = parsed.hostname or ""
    try:
        address = ipaddress.ip_address(host)
        return address.is_private or address.is_loopback
    except ValueError:
        return host == "localhost" or host.endswith((".internal", ".local"))


def _lock_session(cur, user_id):
    cur.execute("INSERT INTO ai_chat_session(user_id) VALUES (%s) ON CONFLICT DO NOTHING", (user_id,))
    cur.execute("SELECT generation FROM ai_chat_session WHERE user_id = %s FOR UPDATE", (user_id,))
    return cur.fetchone()["generation"]


def health_status():
    status = {"configured": configuration_ready(), "database": False, "worker": False, "agent": False}
    try:
        with get_cursor() as cur:
            cur.execute(
                """SELECT count(*) FILTER (WHERE heartbeat_at > clock_timestamp() - interval '15 seconds') AS workers,
                           count(*) FILTER (WHERE heartbeat_at > clock_timestamp() - interval '15 seconds'
                                            AND agent_reachable AND capacity = %s) AS ready
                           FROM ai_chat_worker""",
                (settings.AI_CHAT_GLOBAL_SLOTS,),
            )
            row = cur.fetchone()
            status.update(database=True, worker=bool(row["workers"]), agent=bool(row["ready"]))
    except Exception:
        pass
    return status


def require_ready():
    if not all(health_status().values()):
        raise ai_unavailable("AI 聊天执行服务尚未就绪")


def submit_run(user_id, turn_id, message, reference=None):
    fingerprint = request_hash(message, reference)
    with get_cursor(commit=True) as cur:
        generation = _lock_session(cur, user_id)
        cur.execute("DELETE FROM ai_chat_tombstone WHERE user_id = %s AND expires_at <= clock_timestamp()", (user_id,))
        cur.execute("SELECT 1 FROM ai_chat_tombstone WHERE user_id = %s AND turn_id = %s", (user_id, turn_id))
        if cur.fetchone():
            raise conflict("该轮次已清空，请重新发起提问", {"reason": "chat_history_cleared"})
        cur.execute("SELECT * FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s", (user_id, turn_id))
        existing = cur.fetchone()
        if existing:
            existing_hash = existing.get("request_hash") or request_hash(existing["user_message"])
            if existing_hash != fingerprint:
                raise conflict("相同 turnId 的请求内容不一致", {"reason": "turn_request_conflict"})
            return run_view(existing)
        require_ready()
        validate_reference(cur, user_id, generation, reference)
        cur.execute(
            """SELECT count(*) FILTER (WHERE status = 'queued') AS queued,
                       count(*) FILTER (WHERE status = 'running') AS running FROM ai_chat_turn
                       WHERE user_id = %s AND status IN ('queued', 'running')""",
            (user_id,),
        )
        counts = cur.fetchone()
        if counts["queued"] >= 3:
            raise BizError("TT_AI_42901", "已有三个问题排队，请稍后再试", 429)
        cur.execute(
            """INSERT INTO ai_chat_turn(user_id, turn_id, status, user_message, execution_mode,
                       request_hash, generation, reference, stage, queue_deadline)
                       VALUES (%s, %s, 'queued', %s, 'durable', %s, %s, %s, 'queued',
                               clock_timestamp() + %s * interval '1 second') RETURNING *""",
            (
                user_id,
                turn_id,
                message.strip(),
                fingerprint,
                generation,
                Json(reference) if reference else None,
                settings.AI_CHAT_QUEUE_SECONDS,
            ),
        )
        return run_view(cur.fetchone())


def get_run(user_id, turn_id):
    with get_cursor() as cur:
        cur.execute(
            """SELECT t.* FROM ai_chat_turn t LEFT JOIN ai_chat_session s ON s.user_id = t.user_id
                       WHERE t.user_id = %s AND t.turn_id = %s AND t.generation = COALESCE(s.generation, 0)""",
            (user_id, turn_id),
        )
        return run_view(cur.fetchone())


def has_durable_history(user_id):
    with get_cursor() as cur:
        cur.execute("SELECT to_regclass('ai_chat_session') AS relation")
        row = cur.fetchone()
        if not row or not row["relation"]:
            return False
        cur.execute("SELECT 1 FROM ai_chat_session WHERE user_id = %s", (user_id,))
        return cur.fetchone() is not None


def clear_runs(user_id):
    with get_cursor(commit=True) as cur:
        generation = _lock_session(cur, user_id) + 1
        cur.execute(
            "UPDATE ai_chat_session SET generation = %s, updated_at = clock_timestamp() WHERE user_id = %s",
            (generation, user_id),
        )
        cur.execute(
            """INSERT INTO ai_chat_tombstone(user_id, turn_id, request_hash)
                       SELECT user_id, turn_id, request_hash FROM ai_chat_turn WHERE user_id = %s
                       ON CONFLICT (user_id, turn_id) DO UPDATE SET expires_at = clock_timestamp() + interval '7 days'""",
            (user_id,),
        )
        cur.execute(
            """UPDATE ai_chat_execution_slot SET execution_id = NULL, lease_until = NULL
                       WHERE execution_id IN (SELECT execution_id FROM ai_chat_turn WHERE user_id = %s)""",
            (user_id,),
        )
        cur.execute("DELETE FROM ai_chat_turn WHERE user_id = %s", (user_id,))
        cur.execute("DELETE FROM ai_chat_message WHERE user_id = %s", (user_id,))
        return {"deleted": cur.rowcount, "generation": generation}


def heartbeat_worker(worker_id, agent_reachable):
    with get_cursor(commit=True) as cur:
        cur.execute(
            """INSERT INTO ai_chat_worker(worker_id, agent_reachable, capacity) VALUES (%s, %s, %s)
                       ON CONFLICT (worker_id) DO UPDATE SET heartbeat_at = clock_timestamp(),
                       agent_reachable = EXCLUDED.agent_reachable, capacity = EXCLUDED.capacity""",
            (worker_id, agent_reachable, settings.AI_CHAT_GLOBAL_SLOTS),
        )


def claim_one(worker_id):
    with get_cursor(commit=True) as cur:
        cur.execute("""SELECT s.user_id, s.generation FROM ai_chat_session s
                       WHERE EXISTS (SELECT 1 FROM ai_chat_turn t WHERE t.user_id = s.user_id
                                     AND t.generation = s.generation AND t.execution_mode = 'durable'
                                     AND t.status = 'queued' AND t.queue_deadline > clock_timestamp())
                       AND NOT EXISTS (SELECT 1 FROM ai_chat_turn t WHERE t.user_id = s.user_id AND t.status = 'running')
                       ORDER BY (SELECT min(t.id) FROM ai_chat_turn t WHERE t.user_id = s.user_id AND t.status = 'queued')
                       FOR UPDATE OF s SKIP LOCKED LIMIT 1""")
        session = cur.fetchone()
        if not session:
            return None
        cur.execute(
            """SELECT slot_id FROM ai_chat_execution_slot WHERE slot_id <= %s AND execution_id IS NULL
                       ORDER BY slot_id FOR UPDATE SKIP LOCKED LIMIT 1""",
            (settings.AI_CHAT_GLOBAL_SLOTS,),
        )
        slot = cur.fetchone()
        if not slot:
            return None
        cur.execute(
            """SELECT * FROM ai_chat_turn WHERE user_id = %s AND generation = %s
                       AND execution_mode = 'durable' AND status = 'queued' ORDER BY id LIMIT 1 FOR UPDATE""",
            (session["user_id"], session["generation"]),
        )
        run = cur.fetchone()
        if not run:
            return None
        try:
            context = load_context(cur, run["user_id"], run["generation"], run.get("reference"))
        except BizError:
            _fail_locked(cur, run, "引用消息已不可用，请重新选择卡片", "reference_invalid")
            return None
        execution_id = str(uuid.uuid4())
        cur.execute(
            """UPDATE ai_chat_execution_slot SET execution_id = %s,
                       lease_until = clock_timestamp() + %s * interval '1 second' WHERE slot_id = %s""",
            (execution_id, settings.AI_CHAT_LEASE_SECONDS, slot["slot_id"]),
        )
        cur.execute(
            """UPDATE ai_chat_turn SET status = 'running', execution_id = %s, worker_id = %s,
                       stage = 'context', stage_seq = 1, context_snapshot = %s,
                       execution_deadline = clock_timestamp() + %s * interval '1 second',
                       lease_until = clock_timestamp() + %s * interval '1 second', updated_at = clock_timestamp()
                       WHERE id = %s AND queue_deadline > clock_timestamp() RETURNING *""",
            (
                execution_id,
                worker_id,
                Json(context),
                min(55, settings.AI_CHAT_EXECUTION_SECONDS),
                settings.AI_CHAT_LEASE_SECONDS,
                run["id"],
            ),
        )
        claimed = cur.fetchone()
        if not claimed:
            cur.execute(
                "UPDATE ai_chat_execution_slot SET execution_id = NULL, lease_until = NULL WHERE execution_id = %s",
                (execution_id,),
            )
        return claimed


def _owned_run(cur, run):
    generation = _lock_session(cur, run["user_id"])
    if generation != run["generation"]:
        return None
    cur.execute(
        """SELECT * FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s AND generation = %s
                   AND execution_id = %s AND status = 'running' AND lease_until > clock_timestamp()
                   AND execution_deadline > clock_timestamp() FOR UPDATE""",
        (run["user_id"], run["turn_id"], run["generation"], run["execution_id"]),
    )
    return cur.fetchone()


def renew_run(run):
    with get_cursor(commit=True) as cur:
        if not _owned_run(cur, run):
            return False
        cur.execute(
            """UPDATE ai_chat_execution_slot SET lease_until = clock_timestamp() + %s * interval '1 second'
                       WHERE execution_id = %s AND lease_until > clock_timestamp() RETURNING slot_id""",
            (settings.AI_CHAT_LEASE_SECONDS, run["execution_id"]),
        )
        if not cur.fetchone():
            return False
        cur.execute(
            """UPDATE ai_chat_turn SET lease_until = clock_timestamp() + %s * interval '1 second'
                       WHERE id = %s""",
            (settings.AI_CHAT_LEASE_SECONDS, run["id"]),
        )
        return True


def update_stage(run, stage, sequence):
    with get_cursor(commit=True) as cur:
        if not _owned_run(cur, run):
            return False
        cur.execute(
            """UPDATE ai_chat_turn SET stage = %s, stage_seq = %s, updated_at = clock_timestamp()
                       WHERE id = %s AND stage_seq < %s""",
            (stage, sequence + 1, run["id"], sequence + 1),
        )
        return True


def _messages(cur, run, reply, cards=None):
    identifiers = []
    for role, text, payload in (("user", run["user_message"], None), ("assistant", reply, cards)):
        cur.execute(
            """INSERT INTO ai_chat_message(user_id, role, content, cards, turn_id, generation)
                       VALUES (%s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                run["user_id"],
                role,
                text,
                Json(payload) if payload is not None else None,
                run["turn_id"],
                run["generation"],
            ),
        )
        identifiers.append(cur.fetchone()["id"])
    return identifiers


def _release_slot(cur, run):
    cur.execute(
        "UPDATE ai_chat_execution_slot SET execution_id = NULL, lease_until = NULL WHERE execution_id = %s",
        (run.get("execution_id"),),
    )


def _fail_locked(cur, run, message, reason, require_owner=False):
    identifiers = _messages(cur, run, message)
    statement = """UPDATE ai_chat_turn SET status = 'failed', stage = 'failed', stage_seq = stage_seq + 1,
                   reply = %s, error_message = %s, error_code = 'TT_AI_50301', error_status = 503,
                   user_message_id = %s, assistant_message_id = %s, lease_until = NULL,
                   completed_at = clock_timestamp(), updated_at = clock_timestamp() WHERE id = %s"""
    parameters = (message, message, *identifiers, run["id"])
    if require_owner:
        statement += _OWNER_PREDICATE
        parameters += _owner_parameters(run)
    cur.execute(statement + " RETURNING id", parameters)
    if not cur.fetchone():
        raise _OwnershipLost()
    _release_slot(cur, run)


def finish_run(run, result=None, error=None):
    try:
        return _finish_run(run, result, error)
    except _OwnershipLost:
        return False


def _finish_run(run, result=None, error=None):
    with get_cursor(commit=True) as cur:
        owned = _owned_run(cur, run)
        if not owned:
            return False
        cur.execute(
            "SELECT 1 FROM ai_chat_execution_slot WHERE execution_id = %s AND lease_until > clock_timestamp() FOR UPDATE",
            (run["execution_id"],),
        )
        if not cur.fetchone():
            return False
        cur.execute(
            "SELECT 1 FROM app_user WHERE id = %s AND status = 'active' AND deleted_at IS NULL", (run["user_id"],)
        )
        if not cur.fetchone():
            error = "账号状态已变化，本轮回答未保存"
        if error or not result or not result.get("success"):
            _fail_locked(cur, owned, error or "本轮回答未完成，请重新提问", "execution_failed", require_owner=True)
            return True
        reply, cards = result["message"], result.get("data") or []
        identifiers = _messages(cur, owned, reply, cards)
        cur.execute(
            """UPDATE ai_chat_turn SET status = 'succeeded', stage = 'succeeded', stage_seq = stage_seq + 1,
                       reply = %s, cards = %s, query_plan = %s, user_message_id = %s, assistant_message_id = %s,
                       lease_until = NULL, updated_at = clock_timestamp(), completed_at = clock_timestamp()
                       WHERE id = %s"""
            + _OWNER_PREDICATE
            + " RETURNING id",
            (reply, Json(cards), Json(result.get("queryPlan") or {}), *identifiers, run["id"], *_owner_parameters(run)),
        )
        if not cur.fetchone():
            raise _OwnershipLost()
        _release_slot(cur, run)
        return True


def reap_runs():
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM ai_chat_tombstone WHERE expires_at <= clock_timestamp()")
        cur.execute(
            """SELECT DISTINCT user_id FROM ai_chat_turn WHERE
                       (execution_mode = 'durable' AND ((status = 'queued' AND queue_deadline <= clock_timestamp())
                        OR (status = 'running' AND (lease_until <= clock_timestamp() OR execution_deadline <= clock_timestamp()))))
                       OR (execution_mode = 'sync' AND status = 'running'
                           AND created_at < clock_timestamp() - %s * interval '1 second')""",
            (max(settings.MAX_REQUEST_SECONDS, settings.AI_AGENT_TIMEOUT) + 30,),
        )
        users = cur.fetchall() or []
    count = 0
    for user in users:
        with get_cursor(commit=True) as cur:
            _lock_session(cur, user["user_id"])
            cur.execute(
                """SELECT * FROM ai_chat_turn WHERE user_id = %s AND (
                           (execution_mode = 'durable' AND ((status = 'queued' AND queue_deadline <= clock_timestamp())
                            OR (status = 'running' AND (lease_until <= clock_timestamp() OR execution_deadline <= clock_timestamp()))))
                           OR (execution_mode = 'sync' AND status = 'running'
                               AND created_at < clock_timestamp() - %s * interval '1 second')) FOR UPDATE""",
                (user["user_id"], max(settings.MAX_REQUEST_SECONDS, settings.AI_AGENT_TIMEOUT) + 30),
            )
            for run in cur.fetchall() or []:
                _fail_locked(cur, run, "本轮已中断或等待超时，请重新发起提问", "expired")
                count += 1
    return count
