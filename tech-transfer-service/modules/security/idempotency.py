"""HTTP 请求级持久幂等（PostgreSQL `security_delivery_request`）。

区分三层幂等语义：
1. HTTP Request Idempotency（本模块）：客户端携带 `Idempotency-Key` 在超时期内重试同一发送操作，
   返回原受理结果而不重复入队或扣减真实发送额度；若同 Key 参数不同则返回 409 (`TT_COMMON_40901`)。
   - 中间占位态（`idem_pending` / `queued` / `processing`）绝不因 TTL 到期而被并发重放；
   - 外部副作用持久化阶段（`execution_stage`）作为判断能否安全释放幂等键的唯一持久化事实；
   - `unknown` 未知结果保留幂等键禁止盲目重发。
2. Application Delivery Task Idempotency：Worker 按状态行锁原子领取并执行一次。
3. Provider Delivery Idempotency：取决于服务商协议，未知结果保守记为 `unknown`，绝不假定 Exactly-Once。
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import re
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import Request

from config import settings
from core.errors import TT_COMMON_40901, BizError, bad_request
from db import get_cursor

logger = logging.getLogger("nanshan.security.idempotency")

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 300

ACTIVE_IDEMPOTENCY_STATES = ("idem_pending", "idempotent_pending", "queued", "processing")
RECOVERY_REQUIRED_IDEMPOTENCY_STATES = ("unknown", "legacy_unknown")
UNKNOWN_EXECUTION_STAGES = ("provider_unknown", "legacy_unknown")
PRE_PROVIDER_STAGES = ("pre_provider",)
TERMINAL_IDEMPOTENCY_STATES = (
    "completed",
    "failed",
    "failed_internal",
    "ineligible",
    "blocked",
    "config_error",
    "expired",
)


@dataclass(frozen=True)
class IdempotencyClaim:
    active: bool
    key: str | None = None
    scope: str | None = None
    request_hash: str | None = None
    task_id: str | None = None
    execution_owner: str | None = None
    execution_stage: str | None = None
    replay: bool = False
    cached_response: dict[str, Any] | None = None
    state: str | None = None
    challenge_id: str | None = None
    stage_provenance: str | None = None


def extract_idempotency_key(request: Request | None) -> str | None:
    if request is None:
        return None
    raw = request.headers.get("Idempotency-Key")
    if raw is None:
        return None
    val: str = raw.strip()
    if not val:
        raise bad_request("Idempotency-Key 不能为空白字符串")
    if not _IDEMPOTENCY_KEY_RE.fullmatch(val):
        raise bad_request("Idempotency-Key 格式无效（仅允许 1-128 位字母、数字、_ . : -）")
    return val


def _scope_secret() -> bytes:
    raw = settings.SECURITY_CONTACT_HMAC_SECRET or settings.JWT_SECRET
    return raw.encode("utf-8")


def build_idempotency_scope(
    endpoint: str,
    *,
    user_id: int | None = None,
    session_id: str | None = None,
    client_ip: str = "",
) -> str:
    """构造幂等隔离域：已认证绑定 endpoint + user_id(+sid)；匿名按 endpoint + IP 盲索引。"""
    if user_id is not None:
        sess = f":sid:{session_id}" if session_id else ""
        raw = f"ep:{endpoint}:u:{int(user_id)}{sess}"
    else:
        ip_norm = (client_ip or "unknown").strip()
        raw = f"ep:{endpoint}:anon:{ip_norm}"
    return hmac.new(_scope_secret(), raw.encode("utf-8"), hashlib.sha256).hexdigest()[:48]


def compute_request_fingerprint(
    *,
    channel: str,
    purpose: str,
    normalized_account: str = "",
    normalized_destination: str = "",
) -> str:
    """对规范化请求参数做单向摘要（绝不以明文邮箱/手机号/OTP 作为索引）。"""
    canonical = json.dumps(
        [channel.strip().lower(), purpose.strip().lower(), normalized_account, normalized_destination],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_expired(expires_at: Any) -> bool:
    if expires_at is None:
        return False
    ts = expires_at.timestamp() if isinstance(expires_at, datetime) else float(expires_at)
    return ts <= time.time()


def _rotatable_idempotency_where_sql() -> str:
    """统一幂等键安全释放/轮转判定谓词：

    - 活跃执行态（idem_pending/idempotent_pending/queued/processing）绝不释放；
    - 常规确定终态且未涉未知阶段：按常规请求幂等窗口 `idempotency_expires_at <= NOW()` 轮转；
    - 任何 unknown / legacy_unknown / provider_unknown / outcome_unknown=true 行：
      绝不因常规 300s `idempotency_expires_at` 到期而提前释放，必须同时满足长保留期
      `IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS` 已过。
    """
    return """(
        state <> ALL(%s)
        AND (
            (
                state = ANY(%s)
                AND outcome_unknown = false
                AND COALESCE(execution_stage, 'pre_provider') <> ALL(%s)
                AND COALESCE(stage_provenance, 'explicit') <> 'legacy_unknown'
                AND idempotency_expires_at IS NOT NULL
                AND idempotency_expires_at <= NOW()
            )
            OR (
                (
                    state = ANY(%s)
                    OR outcome_unknown = true
                    OR execution_stage = ANY(%s)
                    OR stage_provenance = 'legacy_unknown'
                )
                AND (idempotency_expires_at IS NULL OR idempotency_expires_at <= NOW())
                AND COALESCE(finished_at, idem_claimed_at, created_at) <= NOW() - make_interval(secs => %s)
            )
        )
    )"""


def _rotatable_params(unknown_retention_seconds: int) -> tuple[Any, ...]:
    return (
        list(ACTIVE_IDEMPOTENCY_STATES),
        list(TERMINAL_IDEMPOTENCY_STATES),
        list(UNKNOWN_EXECUTION_STAGES),
        list(RECOVERY_REQUIRED_IDEMPOTENCY_STATES),
        list(UNKNOWN_EXECUTION_STAGES),
        max(1, int(unknown_retention_seconds)),
    )


def read_http_idempotency_record(
    task_id: str,
    *,
    cur: Any = None,
    cursor_factory: Any = None,
) -> dict[str, Any] | None:
    """读取幂等请求记录在 PostgreSQL 中的最新权威状态。"""
    sql_text = """
        SELECT id, state, execution_owner, execution_stage, stage_provenance, challenge_id,
               idempotency_scope, idempotency_key, request_hash, idempotency_expires_at,
               response_payload, provider_called, outcome_unknown, idem_claimed_at,
               finished_at, created_at
        FROM security_delivery_request
        WHERE id = %s
    """
    if cur is not None:
        cur.execute(sql_text, (task_id,))
        row = cur.fetchone()
        return dict(row) if isinstance(row, dict) else row
    factory = cursor_factory or get_cursor
    with factory(commit=False) as own_cur:
        own_cur.execute(sql_text, (task_id,))
        row = own_cur.fetchone()
        return dict(row) if isinstance(row, dict) else row


def claim_http_idempotency(
    *,
    key: str | None,
    scope: str,
    request_hash: str,
    channel: str,
    purpose: str,
    task_id: str | None = None,
    payload: dict[str, Any] | None = None,
    request_id: str | None = None,
    initial_state: str = "queued",
    ttl_seconds: int | None = None,
    cursor_factory: Any = None,
) -> IdempotencyClaim:
    """在 PostgreSQL 原子占用 HTTP 幂等键并记录执行所有权、阶段与来源。

    - 仅当原记录已过常规 TTL **且处于确定非 unknown 终态**，或 unknown 记录同时超过长保留期
      `IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS` 时，才允许安全轮转；
    - 活跃执行中任务及处于保留期内的 unknown / legacy_unknown 任务绝不允许覆盖或重放新发；
    - 同 Key 参数不一致（request_hash 不匹配）抛 409 `TT_COMMON_40901`。
    """
    if not key:
        return IdempotencyClaim(active=False)

    rec_id = task_id or str(uuid.uuid4())
    req_id = request_id or str(uuid.uuid4())
    exec_owner = str(uuid.uuid4())
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    effective_ttl = settings.IDEMPOTENCY_REQUEST_TTL_SECONDS if ttl_seconds is None else ttl_seconds
    ttl_clamped = max(60, int(effective_ttl))
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    rotatable_sql = _rotatable_idempotency_where_sql()
    rot_params = _rotatable_params(unknown_retention)
    factory = cursor_factory or get_cursor

    with factory(commit=True) as cur:
        # 仅清理满足统一保留/过期策略的旧幂等键占用，活跃中及保留期内 unknown 任务绝不释放
        cur.execute(
            f"""
            UPDATE security_delivery_request
            SET idempotency_key = NULL, idempotency_scope = NULL
            WHERE idempotency_scope = %s AND idempotency_key = %s
              AND {rotatable_sql}
            """,
            (scope, key, *rot_params),
        )

        cur.execute(
            """
            INSERT INTO security_delivery_request (
                id, payload, state, request_id, channel, purpose,
                idempotency_scope, idempotency_key, request_hash, idempotency_expires_at,
                execution_owner, execution_stage, stage_provenance, idem_claimed_at
            ) VALUES (
                %s, %s::jsonb, %s, %s, %s, %s,
                %s, %s, %s, NOW() + make_interval(secs => %s),
                %s, 'pre_provider', 'explicit', NOW()
            )
            ON CONFLICT (idempotency_scope, idempotency_key)
            WHERE idempotency_key IS NOT NULL AND idempotency_scope IS NOT NULL
            DO NOTHING
            RETURNING id
            """,
            (
                rec_id,
                payload_json,
                initial_state,
                req_id,
                channel,
                purpose,
                scope,
                key,
                request_hash,
                ttl_clamped,
                exec_owner,
            ),
        )
        inserted = cur.fetchone()
        if inserted:
            return IdempotencyClaim(
                active=True,
                key=key,
                scope=scope,
                request_hash=request_hash,
                task_id=str(inserted["id"] if isinstance(inserted, dict) else rec_id),
                execution_owner=exec_owner,
                execution_stage="pre_provider",
                replay=False,
                state=initial_state,
                stage_provenance="explicit",
            )

        cur.execute(
            f"""
            SELECT id, state, request_hash, response_payload, idempotency_expires_at,
                   execution_owner, execution_stage, stage_provenance, challenge_id,
                   {rotatable_sql} AS can_rotate
            FROM security_delivery_request
            WHERE idempotency_scope = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (*rot_params, scope, key),
        )
        existing = cur.fetchone()
        if not existing:
            cur.execute(
                """
                INSERT INTO security_delivery_request (
                    id, payload, state, request_id, channel, purpose,
                    idempotency_scope, idempotency_key, request_hash, idempotency_expires_at,
                    execution_owner, execution_stage, stage_provenance, idem_claimed_at
                ) VALUES (
                    %s, %s::jsonb, %s, %s, %s, %s,
                    %s, %s, %s, NOW() + make_interval(secs => %s),
                    %s, 'pre_provider', 'explicit', NOW()
                )
                RETURNING id
                """,
                (
                    rec_id,
                    payload_json,
                    initial_state,
                    req_id,
                    channel,
                    purpose,
                    scope,
                    key,
                    request_hash,
                    ttl_clamped,
                    exec_owner,
                ),
            )
            return IdempotencyClaim(
                active=True,
                key=key,
                scope=scope,
                request_hash=request_hash,
                task_id=rec_id,
                execution_owner=exec_owner,
                execution_stage="pre_provider",
                replay=False,
                state=initial_state,
                stage_provenance="explicit",
            )

        if bool(existing.get("can_rotate")):
            cur.execute(
                f"""
                UPDATE security_delivery_request
                SET idempotency_key = NULL, idempotency_scope = NULL
                WHERE id = %s AND {rotatable_sql}
                """,
                (existing["id"], *rot_params),
            )
            if cur.rowcount > 0:
                cur.execute(
                    """
                    INSERT INTO security_delivery_request (
                        id, payload, state, request_id, channel, purpose,
                        idempotency_scope, idempotency_key, request_hash, idempotency_expires_at,
                        execution_owner, execution_stage, stage_provenance, idem_claimed_at
                    ) VALUES (
                        %s, %s::jsonb, %s, %s, %s, %s,
                        %s, %s, %s, NOW() + make_interval(secs => %s),
                        %s, 'pre_provider', 'explicit', NOW()
                    )
                    RETURNING id
                    """,
                    (
                        rec_id,
                        payload_json,
                        initial_state,
                        req_id,
                        channel,
                        purpose,
                        scope,
                        key,
                        request_hash,
                        ttl_clamped,
                        exec_owner,
                    ),
                )
                return IdempotencyClaim(
                    active=True,
                    key=key,
                    scope=scope,
                    request_hash=request_hash,
                    task_id=rec_id,
                    execution_owner=exec_owner,
                    execution_stage="pre_provider",
                    replay=False,
                    state=initial_state,
                    stage_provenance="explicit",
                )

        if not hmac.compare_digest(str(existing.get("request_hash") or ""), request_hash):
            raise BizError(*TT_COMMON_40901)

        cached = existing.get("response_payload")
        if not isinstance(cached, dict):
            cached = None
        return IdempotencyClaim(
            active=True,
            key=key,
            scope=scope,
            request_hash=request_hash,
            task_id=str(existing["id"]),
            execution_owner=existing.get("execution_owner"),
            execution_stage=existing.get("execution_stage"),
            replay=True,
            cached_response=cached,
            state=existing.get("state"),
            challenge_id=str(existing["challenge_id"]) if existing.get("challenge_id") else None,
            stage_provenance=existing.get("stage_provenance"),
        )


def advance_idempotency_stage(
    claim: IdempotencyClaim | None,
    expected_stages: tuple[str, ...],
    target_stage: str,
    *,
    challenge_id: str | None = None,
    provider_called: bool | None = None,
    state: str | None = None,
    failure_reason: str | None = None,
    outcome_unknown: bool | None = None,
    allowed_states: tuple[str, ...] = ACTIVE_IDEMPOTENCY_STATES,
    cur: Any = None,
    cursor_factory: Any = None,
) -> bool:
    """严格 CAS 推进幂等记录执行阶段；强绑定 owner / scope / key / 活跃态与阶段前置条件。"""
    if (
        not claim
        or not claim.active
        or not claim.task_id
        or not claim.execution_owner
        or not claim.scope
        or not claim.key
        or not expected_stages
    ):
        return False

    enforce_ownership_ttl = target_stage in ("send_claimed", "provider_called")
    ownership_seconds = max(60, int(settings.IDEMPOTENCY_EXECUTION_OWNERSHIP_SECONDS))
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    is_unknown_target = target_stage == "provider_unknown" or bool(outcome_unknown)

    sql_text = """
        UPDATE security_delivery_request
        SET execution_stage = %s,
            challenge_id = COALESCE(%s::uuid, challenge_id),
            provider_called = COALESCE(%s, provider_called),
            state = COALESCE(%s, state),
            failure_reason = COALESCE(%s, failure_reason),
            outcome_unknown = COALESCE(%s, outcome_unknown),
            idempotency_expires_at = CASE
                WHEN %s::boolean THEN GREATEST(COALESCE(idempotency_expires_at, NOW()), NOW() + make_interval(secs => %s))
                ELSE idempotency_expires_at
            END,
            finished_at = CASE
                WHEN %s IN ('unknown', 'completed', 'failed') THEN COALESCE(finished_at, NOW())
                ELSE finished_at
            END
        WHERE id = %s
          AND execution_owner = %s
          AND idempotency_scope = %s
          AND idempotency_key = %s
          AND state = ANY(%s)
          AND execution_stage = ANY(%s)
          AND (NOT %s::boolean OR idem_claimed_at IS NULL OR idem_claimed_at > NOW() - make_interval(secs => %s))
    """
    params = (
        target_stage,
        challenge_id,
        provider_called,
        state,
        failure_reason[:64] if failure_reason else None,
        outcome_unknown,
        is_unknown_target,
        unknown_retention,
        state,
        claim.task_id,
        claim.execution_owner,
        claim.scope,
        claim.key,
        list(allowed_states),
        list(expected_stages),
        enforce_ownership_ttl,
        ownership_seconds,
    )
    if cur is not None:
        cur.execute(sql_text, params)
        return bool(cur.rowcount > 0)
    factory = cursor_factory or get_cursor
    with factory(commit=True) as own_cur:
        own_cur.execute(sql_text, params)
        return bool(own_cur.rowcount > 0)


def finalize_http_idempotency(
    claim: IdempotencyClaim,
    response_payload: dict[str, Any],
    *,
    state: str | None = None,
    execution_stage: str | None = None,
    cur: Any = None,
    cursor_factory: Any = None,
) -> bool:
    """严格 CAS 写入幂等公开响应；仅在仍持有执行权、作用域、键且阶段合法时成功。"""
    if not claim.active or not claim.task_id or not claim.execution_owner or not claim.scope or not claim.key:
        return False
    target_stage = execution_stage
    if target_stage is None:
        if state == "completed":
            target_stage = "response_persisted"
        elif state == "unknown":
            target_stage = "provider_unknown"
        elif state == "failed":
            target_stage = "provider_rejected"

    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    sql_text = """
        UPDATE security_delivery_request
        SET response_payload = %s::jsonb,
            state = COALESCE(%s, state),
            execution_stage = COALESCE(%s, execution_stage),
            outcome = CASE
                WHEN %s = 'completed' THEN COALESCE(outcome, 'COMPLETED')
                WHEN %s = 'unknown' THEN 'PROVIDER_UNKNOWN'
                WHEN %s = 'failed' THEN COALESCE(outcome, 'PROVIDER_REJECTED')
                ELSE outcome
            END,
            outcome_unknown = CASE WHEN %s = 'unknown' THEN true ELSE outcome_unknown END,
            idempotency_expires_at = CASE
                WHEN %s = 'unknown'
                    THEN GREATEST(COALESCE(idempotency_expires_at, NOW()), NOW() + make_interval(secs => %s))
                ELSE idempotency_expires_at
            END,
            finished_at = CASE
                WHEN %s IN ('completed', 'failed', 'unknown') THEN COALESCE(finished_at, NOW())
                ELSE finished_at
            END,
            payload = CASE
                WHEN %s IN ('completed', 'failed', 'unknown')
                    THEN COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                ELSE payload
            END
        WHERE id = %s
          AND execution_owner = %s
          AND idempotency_scope = %s
          AND idempotency_key = %s
          AND (
              (
                  state = ANY(%s)
                  AND (
                      %s IS DISTINCT FROM 'completed'
                      OR (
                          outcome_unknown = false
                          AND COALESCE(execution_stage, 'pre_provider') NOT IN (
                              'provider_unknown', 'legacy_unknown', 'provider_rejected'
                          )
                      )
                  )
              )
              OR (%s = 'unknown' AND state = 'unknown')
          )
    """
    params = (
        json.dumps(response_payload, ensure_ascii=False),
        state,
        target_stage,
        state,
        state,
        state,
        state,
        state,
        unknown_retention,
        state,
        state,
        claim.task_id,
        claim.execution_owner,
        claim.scope,
        claim.key,
        list(ACTIVE_IDEMPOTENCY_STATES),
        state,
        state,
    )
    if cur is not None:
        cur.execute(sql_text, params)
        return bool(cur.rowcount > 0)
    factory = cursor_factory or get_cursor
    with factory(commit=True) as own_cur:
        own_cur.execute(sql_text, params)
        return bool(own_cur.rowcount > 0)


def mark_http_idempotency_unknown(
    claim: IdempotencyClaim | None,
    reason_code: str = "PROVIDER_OUTCOME_UNKNOWN",
    *,
    challenge_id: str | None = None,
    cursor_factory: Any = None,
) -> bool:
    """在外部副作用可能已发生或响应持久化失败时保守标为 unknown，锁定并延长幂等键保留期。"""
    if (
        not claim
        or not claim.active
        or not claim.task_id
        or not claim.execution_owner
        or not claim.scope
        or not claim.key
    ):
        return False
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    factory = cursor_factory or get_cursor
    try:
        with factory(commit=True) as cur:
            cur.execute(
                """
                UPDATE security_delivery_request
                SET state = 'unknown',
                    outcome = 'PROVIDER_UNKNOWN',
                    outcome_unknown = true,
                    provider_called = true,
                    challenge_id = COALESCE(%s::uuid, challenge_id),
                    execution_stage = CASE
                        WHEN execution_stage = 'response_persisted' THEN execution_stage
                        ELSE 'provider_unknown'
                    END,
                    failure_reason = COALESCE(failure_reason, %s),
                    response_payload = COALESCE(response_payload, %s::jsonb),
                    idempotency_expires_at = GREATEST(
                        COALESCE(idempotency_expires_at, NOW()),
                        NOW() + make_interval(secs => %s)
                    ),
                    finished_at = COALESCE(finished_at, NOW()),
                    payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                WHERE id = %s
                  AND execution_owner = %s
                  AND idempotency_scope = %s
                  AND idempotency_key = %s
                  AND state <> 'completed'
                """,
                (
                    challenge_id,
                    reason_code[:64],
                    json.dumps({"pendingOutcome": True, "reasonCode": reason_code[:64]}, ensure_ascii=False),
                    unknown_retention,
                    claim.task_id,
                    claim.execution_owner,
                    claim.scope,
                    claim.key,
                ),
            )
            return bool(cur.rowcount > 0)
    except Exception as exc:
        logger.warning("标记幂等任务为 unknown 失败 (task_id=%s, err=%s)", claim.task_id, type(exc).__name__)
        return False


def release_http_idempotency_on_pre_provider_failure(
    claim: IdempotencyClaim,
    failure_reason: str,
    *,
    cursor_factory: Any = None,
) -> bool:
    """仅当数据库持久化事实可证明尚未进入发送权/外部调用阶段时释放幂等键。

    要求同时满足：
    - 持有相同 execution_owner + idempotency_scope + idempotency_key；
    - execution_stage = 'pre_provider' 且 provider_called = false 且 stage_provenance = 'explicit'；
    - 关联 auth_challenge 尚未进入 sending/accepted/delivered/unknown 等外呼态。
    若已进入发送或未知阶段，绝不释放幂等键，而是收敛为 failed（若明确 rejected）或 unknown。
    """
    if not claim.active or not claim.task_id or not claim.execution_owner or not claim.scope or not claim.key:
        return False
    reason = failure_reason[:64] if failure_reason else "pre_provider_failure"
    unknown_retention = max(1, int(settings.IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS))
    factory = cursor_factory or get_cursor
    try:
        with factory(commit=True) as cur:
            cur.execute(
                """
                UPDATE security_delivery_request sdr
                SET idempotency_key = NULL,
                    idempotency_scope = NULL,
                    state = 'failed',
                    failure_reason = COALESCE(sdr.failure_reason, %s),
                    finished_at = COALESCE(sdr.finished_at, NOW()),
                    payload = COALESCE(sdr.payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                WHERE sdr.id = %s
                  AND sdr.execution_owner = %s
                  AND sdr.idempotency_scope = %s
                  AND sdr.idempotency_key = %s
                  AND sdr.state IN ('idem_pending', 'idempotent_pending', 'queued')
                  AND sdr.execution_stage = 'pre_provider'
                  AND sdr.provider_called = false
                  AND COALESCE(sdr.stage_provenance, 'explicit') = 'explicit'
                  AND NOT EXISTS (
                      SELECT 1
                      FROM auth_challenge ac
                      WHERE ac.id = COALESCE(sdr.challenge_id, sdr.id)
                        AND ac.send_state IN (
                            'sending', 'accepted', 'delivered', 'unknown', 'bounced', 'delivery_failed'
                        )
                  )
                """,
                (reason, claim.task_id, claim.execution_owner, claim.scope, claim.key),
            )
            if cur.rowcount > 0:
                return True

            cur.execute(
                """
                SELECT state, execution_stage, provider_called, execution_owner
                FROM security_delivery_request
                WHERE id = %s
                """,
                (claim.task_id,),
            )
            existing = cur.fetchone()
            if not existing:
                return False
            stage = existing.get("execution_stage")
            called = bool(existing.get("provider_called"))
            if stage == "provider_rejected":
                cur.execute(
                    """
                    UPDATE security_delivery_request
                    SET state = 'failed',
                        failure_reason = COALESCE(failure_reason, %s),
                        finished_at = COALESCE(finished_at, NOW()),
                        payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                    WHERE id = %s
                      AND execution_owner = %s
                      AND idempotency_scope = %s
                      AND idempotency_key = %s
                      AND state IN ('idem_pending', 'idempotent_pending')
                    """,
                    (reason, claim.task_id, claim.execution_owner, claim.scope, claim.key),
                )
            elif stage not in (None, "pre_provider") or called:
                cur.execute(
                    """
                    UPDATE security_delivery_request
                    SET state = 'unknown',
                        outcome = 'PROVIDER_UNKNOWN',
                        outcome_unknown = true,
                        failure_reason = COALESCE(failure_reason, %s),
                        idempotency_expires_at = GREATEST(
                            COALESCE(idempotency_expires_at, NOW()),
                            NOW() + make_interval(secs => %s)
                        ),
                        finished_at = COALESCE(finished_at, NOW()),
                        payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                    WHERE id = %s
                      AND execution_owner = %s
                      AND idempotency_scope = %s
                      AND idempotency_key = %s
                      AND state IN ('idem_pending', 'idempotent_pending', 'queued', 'processing')
                    """,
                    (
                        reason,
                        unknown_retention,
                        claim.task_id,
                        claim.execution_owner,
                        claim.scope,
                        claim.key,
                    ),
                )
            return False
    except Exception as exc:
        logger.warning("释放幂等键校验失败（保守保留占位）: task_id=%s err=%s", claim.task_id, type(exc).__name__)
        return False


def wait_for_idempotency_settlement(
    claim: IdempotencyClaim,
    *,
    timeout_seconds: float = 2.0,
    poll_interval_seconds: float = 0.025,
) -> IdempotencyClaim:
    """并发同键请求命中 `idem_pending` 时，短时轮询等待首发请求完成网关前置检查与响应落盘。"""
    if (
        not claim.active
        or not claim.replay
        or claim.cached_response is not None
        or claim.state not in ("idem_pending", "idempotent_pending")
        or not claim.task_id
    ):
        return claim

    deadline = time.monotonic() + max(0.0, float(timeout_seconds))
    interval = max(0.005, float(poll_interval_seconds))
    while time.monotonic() < deadline:
        time.sleep(interval)
        try:
            with get_cursor(commit=False) as cur:
                cur.execute(
                    """
                    SELECT state, execution_stage, stage_provenance, response_payload, idempotency_key
                    FROM security_delivery_request
                    WHERE id = %s
                    """,
                    (claim.task_id,),
                )
                row = cur.fetchone()
        except Exception:
            return claim
        if not row:
            return IdempotencyClaim(
                active=claim.active,
                key=claim.key,
                scope=claim.scope,
                request_hash=claim.request_hash,
                task_id=claim.task_id,
                execution_owner=claim.execution_owner,
                execution_stage=claim.execution_stage,
                replay=True,
                cached_response=None,
                state="released",
            )
        cur_state = str(row.get("state") or "")
        cached = row.get("response_payload")
        if not isinstance(cached, dict):
            cached = None
        if cur_state not in ("idem_pending", "idempotent_pending") or cached is not None:
            return IdempotencyClaim(
                active=claim.active,
                key=claim.key,
                scope=claim.scope,
                request_hash=claim.request_hash,
                task_id=claim.task_id,
                execution_owner=claim.execution_owner,
                execution_stage=row.get("execution_stage") or claim.execution_stage,
                replay=True,
                cached_response=cached,
                state=cur_state,
                stage_provenance=row.get("stage_provenance"),
            )
        if row.get("idempotency_key") is None:
            return IdempotencyClaim(
                active=claim.active,
                key=claim.key,
                scope=claim.scope,
                request_hash=claim.request_hash,
                task_id=claim.task_id,
                execution_owner=claim.execution_owner,
                execution_stage=row.get("execution_stage") or claim.execution_stage,
                replay=True,
                cached_response=None,
                state="released",
                stage_provenance=row.get("stage_provenance"),
            )
    return claim
