"""Phone ownership for account creation before a user ID exists."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any

from psycopg2 import IntegrityError

from config import settings
from core.errors import BizError, bad_request, conflict
from modules.security.delivery_models import DeliveryStageError
from modules.security.rate_limiter import check_verify_challenge_rate
from modules.security.service import (
    _challenge_transaction,
    _expired,
    _verify_challenge_code_match,
    _verify_destination_fingerprint,
)
from modules.security.sms_gateway import SendContext, _engine, _send, normalize_phone, request_gate
from modules.security.state_machine import can_verify_challenge


def start_registration_challenge(phone: str, context: SendContext) -> dict[str, Any]:
    phone = normalize_phone(phone)
    request_gate(context, "register:" + phone, phone=phone, purpose="register")
    challenge_id = str(uuid.uuid4())
    try:
        _send(None, phone, "register", challenge_id, context, _engine())
    except DeliveryStageError as exc:
        if exc.http_status == 429:
            raise BizError("TT_COMMON_42901", "请求过于频繁，请稍后重试", 429) from None
        if not exc.outcome_unknown or not exc.request_attempted:
            raise BizError("TT_COMMON_50301", "短信验证暂时不可用，请稍后重试", 503) from None
        # A provider timeout can still deliver this code. Its persisted Challenge
        # determines whether verification can proceed.
    return {"challengeId": challenge_id, "cooldownSeconds": settings.SMS_PHONE_COOLDOWN_SECONDS}


@dataclass(frozen=True)
class VerifiedRegistration:
    cursor: Any
    challenge_id: str
    phone: str

    def bind_phone(self, user_id: int) -> None:
        self.cursor.execute(
            """
            INSERT INTO account_contact
                (user_id, contact_type, normalized_value, verified_at, status, verification_method)
            VALUES (%s, 'phone', %s, NOW(), 'active', 'sms')
            """,
            (user_id, self.phone),
        )
        self.cursor.execute(
            """
            UPDATE auth_challenge
            SET user_id=%s, status='consumed', consumed_at=NOW()
            WHERE id=%s AND user_id IS NULL AND purpose='register' AND status='pending'
            """,
            (user_id, self.challenge_id),
        )
        if self.cursor.rowcount != 1:
            raise bad_request("短信验证码无效或已过期，请重新获取")


@contextmanager
def verified_registration(phone: str, challenge_id: str, code: str) -> Iterator[VerifiedRegistration]:
    phone = normalize_phone(phone)
    challenge_id = str(uuid.UUID(challenge_id))
    check_verify_challenge_rate(challenge_id)
    try:
        with _challenge_transaction() as (cur, tx):
            cur.execute(
                """
                SELECT id, purpose, channel, status, send_state, destination_fingerprint, code_hash,
                       attempt_count, max_attempts, expires_at
                FROM auth_challenge
                WHERE id=%s AND purpose='register' AND channel='sms' AND user_id IS NULL
                FOR UPDATE
                """,
                (challenge_id,),
            )
            row = cur.fetchone()
            invalid = bad_request("短信验证码无效或已过期，请重新获取")
            if not row or not row["send_state"] or not can_verify_challenge(row["status"], row["send_state"]):
                raise invalid
            if _expired(row["expires_at"]):
                cur.execute("UPDATE auth_challenge SET status='expired' WHERE id=%s", (challenge_id,))
                raise invalid
            if row["attempt_count"] >= row["max_attempts"]:
                cur.execute("UPDATE auth_challenge SET status='locked' WHERE id=%s", (challenge_id,))
                raise invalid
            if not _verify_destination_fingerprint(row, phone):
                raise invalid
            if not _verify_challenge_code_match(row, phone, code):
                cur.execute(
                    """
                    UPDATE auth_challenge SET attempt_count=attempt_count+1,
                        status=CASE WHEN attempt_count+1 >= max_attempts THEN 'locked' ELSE status END
                    WHERE id=%s
                    """,
                    (challenge_id,),
                )
                raise invalid
            tx["business_writes_started"] = True
            yield VerifiedRegistration(cur, challenge_id, phone)
    except IntegrityError as exc:
        if exc.pgcode == "23505":
            raise conflict("该手机号或账号已使用") from None
        raise
