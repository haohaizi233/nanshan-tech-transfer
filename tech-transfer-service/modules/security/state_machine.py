"""Challenge 认证状态机与投递状态机显式转换与数据库 CAS 原子更新。

原则：
1. 认证状态（status）与投递状态（send_state）严格分离，并满足联合状态约束；
2. 禁止任意逆向/跨态跳转（如 consumed -> pending、expired -> verified、cancelled -> pending）；
3. 投递状态更新必须基于数据库实际当前状态的 CAS 条件更新（WHERE send_state = ANY(%s)），
   防止覆盖更新后的终态（consumed/expired/locked/failed/cancelled 绝不复活为 pending）；
4. `send_state == 'unknown'`（如 SMTP DATA 后断连或 SES 超时）时：
   - 严禁自动重新生成新 OTP 或盲目重发（防止双码并发或投递风暴）；
   - Challenge 仍保持在单次 TTL/最大错误次数约束下（status='pending'），
     若真实邮件已送达用户邮箱，用户可凭原 OTP/Token 在有效期内完成一次性核验；
     若邮件未送达，Challenge 在 TTL 后自然过期，不会产生额外投递风险。
"""

from __future__ import annotations

import json
from dataclasses import dataclass

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
    outcome: str  # "transitioned" | "already_target" | "conflict_or_disallowed" | "not_found"
    current_status: str | None = None
    current_send_state: str | None = None
    updated: bool = False


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


def transition_delivery_state(
    cur,
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
) -> DeliveryTransitionResult:
    """基于数据库真实当前状态的 CAS 原子投递状态转换。

    关键不变量：
    - 校验所有 `expected_states -> target_state` 均满足 `ALLOWED_SEND_STATE_TRANSITIONS`；
    - 参数化 `WHERE id = %s AND send_state = ANY(%s)` 执行条件更新；
    - 绝不将 `consumed` / `expired` / `locked` / `failed` / `cancelled` 等终态恢复为 `pending`；
    - `rowcount == 0` 时区分 `not_found`、`already_target` 与 `conflict_or_disallowed`。
    """
    if not expected_states:
        raise ValueError("expected_states 不能为空")
    for src in expected_states:
        assert_send_state_transition(src, target_state)

    has_provider_ids = provider_ids is not None
    pids_json = json.dumps(list(provider_ids or ()))
    fail_target = challenge_status_on_failure if target_state in {"rejected", "bounced", "delivery_failed"} else None

    cur.execute(
        """
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
            END
        WHERE id = %s
          AND send_state = ANY(%s)
        RETURNING status, send_state
        """,
        (
            target_state,
            has_provider_ids,
            pids_json,
            provider_status,
            delivery_reason_code[:32] if delivery_reason_code else None,
            target_state,
            fail_target,
            fail_target,
            target_state,
            fail_target,
            fail_target,
            challenge_id,
            list(expected_states),
        ),
    )
    if cur.rowcount:
        updated_row = cur.fetchone()
        st = updated_row.get("status") if isinstance(updated_row, dict) else None
        ss = updated_row.get("send_state") if isinstance(updated_row, dict) else target_state
        if provider_name is not None or provider_config_id is not None or failure_reason is not None:
            reason_val = failure_reason[:64] if failure_reason else None
            try:
                cur.execute("SAVEPOINT sp_transition_ext_037")
                cur.execute(
                    """
                    UPDATE auth_challenge
                    SET provider_name = COALESCE(%s, provider_name),
                        provider_config_id = COALESCE(%s, provider_config_id),
                        delivery_failure_reason = COALESCE(%s, delivery_failure_reason)
                    WHERE id = %s
                    """,
                    (provider_name, provider_config_id, reason_val, challenge_id),
                )
                cur.execute("RELEASE SAVEPOINT sp_transition_ext_037")
            except Exception:
                cur.execute("ROLLBACK TO SAVEPOINT sp_transition_ext_037")
        return DeliveryTransitionResult(
            outcome="transitioned",
            current_status=st,
            current_send_state=ss or target_state,
            updated=True,
        )

    cur.execute("SELECT status, send_state FROM auth_challenge WHERE id = %s", (challenge_id,))
    existing = cur.fetchone()
    if not existing:
        return DeliveryTransitionResult(outcome="not_found", updated=False)
    cur_status = existing.get("status") if isinstance(existing, dict) else None
    cur_send = existing.get("send_state") if isinstance(existing, dict) else None
    if cur_send == target_state:
        return DeliveryTransitionResult(
            outcome="already_target",
            current_status=cur_status,
            current_send_state=cur_send,
            updated=False,
        )
    return DeliveryTransitionResult(
        outcome="conflict_or_disallowed",
        current_status=cur_status,
        current_send_state=cur_send,
        updated=False,
    )
