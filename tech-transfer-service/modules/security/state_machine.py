"""Challenge 认证状态机与投递状态机显式转换校验。

原则：
1. 认证状态（status）与投递状态（send_state）严格分离；
2. 禁止任意逆向/跨态跳转（如 consumed -> pending、expired -> verified、cancelled -> pending）；
3. `send_state == 'unknown'`（如 SMTP DATA 后断连或 SES 超时）时：
   - 严禁自动重新生成新 OTP 或盲目重发（防止双码并发或投递风暴）；
   - Challenge 仍保持在单次 TTL/最大错误次数约束下（status='pending'），
     若真实邮件已送达用户邮箱，用户可凭原 OTP/Token 在有效期内完成一次性核验；
     若邮件未送达，Challenge 在 TTL 后自然过期，不会产生额外投递风险。
"""

from __future__ import annotations

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
