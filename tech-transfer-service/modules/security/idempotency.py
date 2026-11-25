"""HTTP 请求级持久幂等（PostgreSQL `security_delivery_request`）。

区分三层幂等语义：
1. HTTP Request Idempotency（本模块）：客户端携带 `Idempotency-Key` 在超时期内重试同一发送操作，
   返回原受理结果而不重复入队或扣减真实发送额度；若同 Key 参数不同则返回 409 (`TT_COMMON_40901`)。
   未提供 `Idempotency-Key` 的旧客户端保持完全兼容（由风控与任务级幂等兜底）。
2. Application Delivery Task Idempotency：Worker 按状态行锁原子领取并执行一次。
3. Provider Delivery Idempotency：取决于服务商协议，未知结果保守记为 `unknown`，绝不假定 Exactly-Once。
"""

from __future__ import annotations

import hashlib
import hmac
import json
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

_IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
DEFAULT_IDEMPOTENCY_TTL_SECONDS = 300


@dataclass(frozen=True)
class IdempotencyClaim:
    active: bool
    key: str | None = None
    scope: str | None = None
    request_hash: str | None = None
    task_id: str | None = None
    replay: bool = False
    cached_response: dict[str, Any] | None = None
    state: str | None = None


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
    ttl_seconds: int = DEFAULT_IDEMPOTENCY_TTL_SECONDS,
) -> IdempotencyClaim:
    """在 PostgreSQL 原子占用 HTTP 幂等键并可选同时入队任务。

    - 若首次出现（或原记录已过期轮转），插入记录并返回 `replay=False`；
    - 若在 TTL 内重复出现且 `request_hash` 一致，返回 `replay=True` 及持久化公开响应；
    - 若在 TTL 内重复出现但 `request_hash` 不一致，抛出 409 `TT_COMMON_40901`。
    """
    if not key:
        return IdempotencyClaim(active=False)

    rec_id = task_id or str(uuid.uuid4())
    req_id = request_id or str(uuid.uuid4())
    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    with get_cursor(commit=True) as cur:
        # 清理同作用域同 Key 且已过期的旧幂等键占用，允许安全轮转
        cur.execute(
            """
            UPDATE security_delivery_request
            SET idempotency_key = NULL, idempotency_scope = NULL
            WHERE idempotency_scope = %s AND idempotency_key = %s
              AND idempotency_expires_at IS NOT NULL AND idempotency_expires_at <= NOW()
            """,
            (scope, key),
        )

        cur.execute(
            """
            INSERT INTO security_delivery_request (
                id, payload, state, request_id, channel, purpose,
                idempotency_scope, idempotency_key, request_hash, idempotency_expires_at
            ) VALUES (
                %s, %s::jsonb, %s, %s, %s, %s,
                %s, %s, %s, NOW() + make_interval(secs => %s)
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
                max(60, int(ttl_seconds)),
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
                replay=False,
                state=initial_state,
            )

        cur.execute(
            """
            SELECT id, state, request_hash, response_payload, idempotency_expires_at
            FROM security_delivery_request
            WHERE idempotency_scope = %s AND idempotency_key = %s
            FOR UPDATE
            """,
            (scope, key),
        )
        existing = cur.fetchone()
        if not existing:
            # 极罕见竞态下旧行刚刚被轮转清理，重试一次插入
            cur.execute(
                """
                INSERT INTO security_delivery_request (
                    id, payload, state, request_id, channel, purpose,
                    idempotency_scope, idempotency_key, request_hash, idempotency_expires_at
                ) VALUES (
                    %s, %s::jsonb, %s, %s, %s, %s,
                    %s, %s, %s, NOW() + make_interval(secs => %s)
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
                    max(60, int(ttl_seconds)),
                ),
            )
            return IdempotencyClaim(
                active=True,
                key=key,
                scope=scope,
                request_hash=request_hash,
                task_id=rec_id,
                replay=False,
                state=initial_state,
            )

        if _is_expired(existing.get("idempotency_expires_at")):
            cur.execute(
                """
                UPDATE security_delivery_request SET idempotency_key = NULL, idempotency_scope = NULL
                WHERE id = %s
                """,
                (existing["id"],),
            )
            cur.execute(
                """
                INSERT INTO security_delivery_request (
                    id, payload, state, request_id, channel, purpose,
                    idempotency_scope, idempotency_key, request_hash, idempotency_expires_at
                ) VALUES (
                    %s, %s::jsonb, %s, %s, %s, %s,
                    %s, %s, %s, NOW() + make_interval(secs => %s)
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
                    max(60, int(ttl_seconds)),
                ),
            )
            return IdempotencyClaim(
                active=True,
                key=key,
                scope=scope,
                request_hash=request_hash,
                task_id=rec_id,
                replay=False,
                state=initial_state,
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
            replay=True,
            cached_response=cached,
            state=existing.get("state"),
        )


def finalize_http_idempotency(
    claim: IdempotencyClaim,
    response_payload: dict[str, Any],
    *,
    state: str | None = None,
) -> None:
    if not claim.active or not claim.task_id:
        return
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE security_delivery_request
            SET response_payload = %s::jsonb,
                state = COALESCE(%s, state)
            WHERE id = %s
            """,
            (json.dumps(response_payload, ensure_ascii=False), state, claim.task_id),
        )


def release_http_idempotency_on_pre_provider_failure(claim: IdempotencyClaim, failure_reason: str) -> None:
    """若任务在真正调用外部服务商之前因校验/配置/风控失败，释放幂等锁并脱敏保留审计痕迹，防止合法重试被永久卡死。"""
    if not claim.active or not claim.task_id:
        return
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                UPDATE security_delivery_request
                SET idempotency_key = NULL,
                    idempotency_scope = NULL,
                    state = CASE WHEN state IN ('queued', 'idem_pending', 'idempotent_pending') THEN 'failed' ELSE state END,
                    failure_reason = COALESCE(failure_reason, %s),
                    finished_at = COALESCE(finished_at, NOW()),
                    payload = COALESCE(payload, '{}'::jsonb) - 'account' - 'ip' - 'device_id' - 'destination'
                WHERE id = %s AND provider_called = false
                """,
                (failure_reason[:64], claim.task_id),
            )
    except Exception:
        pass
