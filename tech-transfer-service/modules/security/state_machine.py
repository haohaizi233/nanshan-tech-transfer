"""Challenge 认证状态机与投递状态机显式转换、执行权门禁与数据库 CAS 原子更新。

原则：
1. 认证状态（status）与投递状态（send_state）严格分离，并满足联合状态约束；
2. 禁止任意逆向/跨态跳转（如 consumed -> pending、expired -> verified、cancelled -> pending）；
3. 获取外部发送执行权（`-> sending`）必须满足联合 CAS：
   `status = 'pending_send' AND expires_at > NOW() AND send_state = ANY(expected_states)`，
   且必须在数据库事务**提交成功**后方可执行真实外部发送；
4. 绝不通过 `SAVEPOINT` 回退忽略扩展列写入错误；
5. `send_state == 'unknown'` 时严禁重新生成新 OTP 或盲目重发。
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from core.errors import bad_request

CHALLENGE_TERMINAL_STATES = frozenset({"consumed", "expired", "locked", "failed", "cancelled"})

ALLOWED_CHALLENGE_TRANSITIONS: dict[str, frozenset[str]] = {
    "pending_send": frozenset({"pending", "failed", "cancelled", "expired"}),
    "pending": frozenset({"verified", "consumed", "expired", "locked", "failed", "cancelled"}),
    "verified": frozenset({"consumed", "expired", "cancelled"}),
    "consumed": frozenset(),
    "expired": frozenset(),
    "locked": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

ALLOWED_SEND_STATE_TRANSITIONS: dict[str, frozenset[str]] = {
    "reserved": frozenset({"sending", "accepted", "rejected", "unknown"}),
    "sending": frozenset({"accepted", "rejected", "unknown"}),
    "unknown": frozenset({"accepted", "rejected", "delivered", "bounced", "delivery_failed"}),
    "accepted": frozenset({"delivered", "bounced", "delivery_failed"}),
    "rejected": frozenset(),
    "delivered": frozenset(),
    "bounced": frozenset(),
    "delivery_failed": frozenset(),
}


@dataclass(frozen=True)
class DeliveryTransitionResult:
    outcome: str  # "transitioned" | "already_target" | "conflict_or_disallowed" | "not_found" | "expired" | "owner_mismatch" | "database_error"
    current_status: str | None = None
    current_send_state: str | None = None
    updated: bool = False
    send_owner: str | None = None


def can_transition_challenge_status(current: str, target: str) -> bool:
    if current == target:
        return True
    allowed = ALLOWED_CHALLENGE_TRANSITIONS.get(current)
    return allowed is not None and target in allowed


def assert_challenge_transition(current: str, target: str) -> None:
    if not can_transition_challenge_status(current, target):
        raise bad_request("验证码状态不允许此操作")


def can_transition_send_state(current: str | None, target: str) -> bool:
    if current is None:
        return target in {"reserved", "sending", "accepted", "rejected", "unknown"}
    if current == target:
        return True
    allowed = ALLOWED_SEND_STATE_TRANSITIONS.get(current)
    return allowed is not None and target in allowed


def assert_send_state_transition(current: str | None, target: str) -> None:
    if not can_transition_send_state(current, target):
        raise ValueError(f"非法投递状态跳转: {current} -> {target}")


def can_verify_challenge(status: str, send_state: str | None = None) -> bool:
    """判定 Challenge 是否处于允许核验状态。

    `status` 必须为 `pending`，且当存在 `send_state` 时：
    - `accepted` / `delivered` / `unknown` / `None`（兼容存量无 send_state 记录）允许核验；
    - `rejected` / `delivery_failed` / `bounced` / `reserved` / `sending` 不允许核验。
    """
    if status != "pending":
        return False
    if send_state is None:
        return True
    return send_state in {"accepted", "delivered", "unknown"}


def _is_expired(value: Any) -> bool:
    if value is None:
        return False
    ts = value.timestamp() if isinstance(value, datetime) else float(value)
    return ts <= time.time()


def transition_delivery_state(
    cur: Any,
    challenge_id: str,
    expected_states: tuple[str, ...],
    target_state: str,
    *,
    provider_ids: list[str] | tuple[str, ...] | None = None,
    provider_name: str | None = None,
    provider_config_id: str | None = None,
    provider_status: int | None = None,
    failure_reason: str | None = None,
    delivery_reason_code: str | None = None,
    challenge_status_on_failure: str | None = "failed",
    send_owner: str | None = None,
    expected_owner: str | None = None,
    require_pending_send: bool | None = None,
    require_not_expired: bool | None = None,
) -> DeliveryTransitionResult:
    """基于数据库真实当前状态的联合 CAS 原子投递状态转换。

    关键不变量：
    - 校验所有 `expected_states -> target_state` 均满足 `ALLOWED_SEND_STATE_TRANSITIONS`；
    - 当 `target_state == 'sending'` 时强制联合检查 `status = 'pending_send' AND expires_at > NOW()`；
    - 当提供 `expected_owner` 时严格校对 `send_owner`，防止迟到或无执行权 Worker 篡改状态；
    - 绝不将 `consumed` / `expired` / `locked` / `failed` / `cancelled` 等终态恢复为 `pending`；
    - 精准区分 `not_found`、`expired`、`owner_mismatch`、`already_target` 与 `conflict_or_disallowed`。
    """
    if not expected_states:
        raise ValueError("expected_states 不能为空")
    for src in expected_states:
        assert_send_state_transition(src, target_state)

    must_pending_send = (target_state == "sending") if require_pending_send is None else bool(require_pending_send)
    must_not_expired = (target_state == "sending") if require_not_expired is None else bool(require_not_expired)

    has_provider_ids = provider_ids is not None
    pids_json = json.dumps(list(provider_ids or ()))
    fail_target = challenge_status_on_failure if target_state in {"rejected", "bounced", "delivery_failed"} else None
    reason_val = failure_reason[:64] if failure_reason else None
    deliv_code = delivery_reason_code[:32] if delivery_reason_code else None
    is_claim_sending = target_state == "sending"

    where_clauses = ["id = %s", "send_state = ANY(%s)"]
    params: list[Any] = [
        target_state,
        has_provider_ids,
        pids_json,
        provider_status,
        deliv_code,
        target_state,
        fail_target,
        fail_target,
        target_state,
        fail_target,
        fail_target,
        provider_name,
        provider_config_id,
        reason_val,
        send_owner,
        is_claim_sending,
        challenge_id,
        list(expected_states),
    ]
    if must_pending_send:
        where_clauses.append("status = 'pending_send'")
    if must_not_expired:
        where_clauses.append("expires_at > NOW()")
    if expected_owner is not None:
        where_clauses.append("(send_owner IS NULL OR send_owner = %s)")
        params.append(expected_owner)

    cur.execute(
        f"""
        UPDATE auth_challenge
        SET send_state = %s,
            provider_message_ids = CASE WHEN %s::boolean THEN %s::jsonb ELSE provider_message_ids END,
            delivery_status_code = COALESCE(%s, delivery_status_code),
            delivery_reason_code = COALESCE(%s, delivery_reason_code),
            status = CASE
                WHEN status = 'pending_send' AND %s IN ('accepted', 'unknown') THEN 'pending'
                WHEN status = 'pending_send' AND %s IS NOT NULL THEN %s
                WHEN status = 'pending' AND %s IN ('bounced', 'delivery_failed', 'rejected') AND %s IS NOT NULL THEN %s
                ELSE status
            END,
            provider_name = COALESCE(%s, provider_name),
            provider_config_id = COALESCE(%s, provider_config_id),
            delivery_failure_reason = COALESCE(%s, delivery_failure_reason),
            send_owner = COALESCE(%s, send_owner),
            send_claimed_at = CASE WHEN %s::boolean THEN COALESCE(send_claimed_at, NOW()) ELSE send_claimed_at END
        WHERE {" AND ".join(where_clauses)}
        RETURNING status, send_state, send_owner
        """,
        tuple(params),
    )
    if cur.rowcount:
        updated_row = cur.fetchone()
        st = updated_row.get("status") if isinstance(updated_row, dict) else None
        ss = updated_row.get("send_state") if isinstance(updated_row, dict) else target_state
        owner_out = updated_row.get("send_owner") if isinstance(updated_row, dict) else send_owner
        return DeliveryTransitionResult(
            outcome="transitioned",
            current_status=st,
            current_send_state=ss or target_state,
            updated=True,
            send_owner=owner_out,
        )

    cur.execute(
        "SELECT status, send_state, expires_at, send_owner FROM auth_challenge WHERE id = %s",
        (challenge_id,),
    )
    existing = cur.fetchone()
    if not existing:
        return DeliveryTransitionResult(outcome="not_found", updated=False)
    cur_status = existing.get("status") if isinstance(existing, dict) else None
    cur_send = existing.get("send_state") if isinstance(existing, dict) else None
    cur_owner = existing.get("send_owner") if isinstance(existing, dict) else None
    cur_expires = existing.get("expires_at") if isinstance(existing, dict) else None

    if expected_owner is not None and cur_owner is not None and cur_owner != expected_owner:
        return DeliveryTransitionResult(
            outcome="owner_mismatch",
            current_status=cur_status,
            current_send_state=cur_send,
            updated=False,
            send_owner=cur_owner,
        )
    if is_claim_sending and send_owner is not None and cur_send == "sending" and cur_owner not in (None, send_owner):
        return DeliveryTransitionResult(
            outcome="owner_mismatch",
            current_status=cur_status,
            current_send_state=cur_send,
            updated=False,
            send_owner=cur_owner,
        )
    if must_not_expired and _is_expired(cur_expires):
        return DeliveryTransitionResult(
            outcome="expired",
            current_status=cur_status,
            current_send_state=cur_send,
            updated=False,
            send_owner=cur_owner,
        )
    if cur_send == target_state:
        return DeliveryTransitionResult(
            outcome="already_target",
            current_status=cur_status,
            current_send_state=cur_send,
            updated=False,
            send_owner=cur_owner,
        )
    return DeliveryTransitionResult(
        outcome="conflict_or_disallowed",
        current_status=cur_status,
        current_send_state=cur_send,
        updated=False,
        send_owner=cur_owner,
    )


def claim_send_execution_right(
    challenge_id: str,
    *,
    send_owner: str,
    expected_states: tuple[str, ...] = ("reserved",),
    provider_name: str | None = None,
    provider_config_id: str | None = None,
    cursor_factory: Any = None,
) -> DeliveryTransitionResult:
    """在独立事务提交中原子取得外部发送执行权（reserved -> sending）。

    仅当联合 CAS 更新成功且数据库事务**实际提交**完成后才返回 outcome='transitioned'。
    任何状态冲突、过期、取消、不存在、或数据库/提交异常均视为未取得发送执行权。
    """
    from db import get_cursor

    factory = cursor_factory or get_cursor
    with factory(commit=True) as cur:
        res = transition_delivery_state(
            cur,
            challenge_id,
            expected_states,
            "sending",
            provider_name=provider_name,
            provider_config_id=provider_config_id,
            send_owner=send_owner,
            require_pending_send=True,
            require_not_expired=True,
        )
    return res
