"""统一 Fail-Closed 服务端会话校验模型与状态机（Phase R-Final）。

不变量：
- INV-01：不存在或已撤销的新版 SID 绝不得通过身份认证；
- INV-02：数据库不可用、缺表、缺字段、超时等任何异常均必须 Fail-Closed（503），
  严禁返回 True/ACTIVE 或降级为历史无 SID 模式；
- INV-06：高风险敏感操作强制现代 SID，禁止缺失 SID 的历史 Token 绕过；
- 非法 SID 格式在查询数据库之前即拒绝（INVALID -> 401）。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from core.errors import TT_COMMON_40102, BizError

logger = logging.getLogger("nanshan.security.session_guard")


class SessionValidationState(StrEnum):
    ACTIVE = "active"
    REVOKED = "revoked"
    EXPIRED = "expired"
    NOT_FOUND = "not_found"
    INVALID = "invalid"
    LEGACY = "legacy"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class SessionValidationResult:
    state: SessionValidationState
    user_id: int
    sid: str | None = None
    session_version: int | None = None
    user_active: bool = False
    reason: str = ""

    @property
    def is_usable_normal(self) -> bool:
        return self.state in {SessionValidationState.ACTIVE, SessionValidationState.LEGACY}

    @property
    def is_usable_modern(self) -> bool:
        return self.state == SessionValidationState.ACTIVE


def parse_strict_sid(raw_sid: Any) -> tuple[bool, str | None]:
    """严格校验 sid 字段：None 代表历史无 sid Token；非 None 必须是合法 UUID 字符串。"""
    if raw_sid is None:
        return True, None
    if not isinstance(raw_sid, str):
        return False, None
    cleaned = raw_sid.strip()
    if not cleaned:
        return False, None
    try:
        return True, str(uuid.UUID(cleaned))
    except (ValueError, AttributeError):
        return False, None


def validate_session_state(
    user_id: int,
    sid: Any = None,
    token_ver: Any = None,
    *,
    cur: Any = None,
    require_modern: bool = False,
) -> SessionValidationResult:
    """统一服务端会话校验入口（单次 SQL 查询核对 app_user + auth_session，严格 Fail-Closed）。"""
    try:
        uid = int(user_id)
    except (TypeError, ValueError):
        return SessionValidationResult(
            state=SessionValidationState.INVALID,
            user_id=0,
            reason="invalid_user_id",
        )

    valid_fmt, parsed_sid = parse_strict_sid(sid)
    if not valid_fmt:
        return SessionValidationResult(
            state=SessionValidationState.INVALID,
            user_id=uid,
            reason="invalid_sid_format",
        )

    expected_ver: int | None = None
    if token_ver is not None:
        if isinstance(token_ver, bool):
            return SessionValidationResult(
                state=SessionValidationState.INVALID,
                user_id=uid,
                sid=parsed_sid,
                reason="invalid_token_version",
            )
        try:
            expected_ver = int(token_ver)
        except (TypeError, ValueError):
            return SessionValidationResult(
                state=SessionValidationState.INVALID,
                user_id=uid,
                sid=parsed_sid,
                reason="invalid_token_version",
            )

    def _run_query(db_cur: Any) -> dict[str, Any] | None:
        if parsed_sid is not None:
            db_cur.execute(
                """
                SELECT
                    au.status AS user_status,
                    au.deleted_at,
                    au.session_version,
                    EXISTS(
                        SELECT 1 FROM auth_session s
                        WHERE s.user_id = au.id AND s.sid = %s
                    ) AS has_any,
                    EXISTS(
                        SELECT 1 FROM auth_session s
                        WHERE s.user_id = au.id AND s.sid = %s
                          AND s.status = 'active'
                          AND (s.expires_at IS NULL OR s.expires_at > NOW())
                    ) AS has_active,
                    EXISTS(
                        SELECT 1 FROM auth_session s
                        WHERE s.user_id = au.id AND s.sid = %s
                          AND (
                              s.status = 'expired'
                              OR (s.expires_at IS NOT NULL AND s.expires_at <= NOW())
                          )
                    ) AS has_expired
                FROM app_user au
                WHERE au.id = %s
                """,
                (parsed_sid, parsed_sid, parsed_sid, uid),
            )
        else:
            db_cur.execute(
                """
                SELECT
                    au.status AS user_status,
                    au.deleted_at,
                    au.session_version
                FROM app_user au
                WHERE au.id = %s
                """,
                (uid,),
            )
        fetched = db_cur.fetchone()
        return fetched if isinstance(fetched, dict) else None

    try:
        if cur is not None:
            row = _run_query(cur)
        else:
            from db import get_cursor

            with get_cursor() as db_cur:
                row = _run_query(db_cur)
    except Exception as exc:
        logger.warning(
            "会话状态数据库校验失败（Fail-Closed）: err=%s user_id=%s has_sid=%s",
            type(exc).__name__,
            uid,
            parsed_sid is not None,
        )
        return SessionValidationResult(
            state=SessionValidationState.UNAVAILABLE,
            user_id=uid,
            sid=parsed_sid,
            reason=f"db_error:{type(exc).__name__}",
        )

    if row is None:
        return SessionValidationResult(
            state=SessionValidationState.NOT_FOUND,
            user_id=uid,
            sid=parsed_sid,
            user_active=False,
            reason="user_not_found",
        )

    if row.get("deleted_at") is not None or row.get("user_status") != "active":
        return SessionValidationResult(
            state=SessionValidationState.REVOKED,
            user_id=uid,
            sid=parsed_sid,
            user_active=False,
            reason="user_inactive",
        )

    raw_ver = row.get("session_version")
    if raw_ver is None:
        return SessionValidationResult(
            state=SessionValidationState.UNAVAILABLE,
            user_id=uid,
            sid=parsed_sid,
            user_active=True,
            reason="missing_session_version",
        )
    current_ver = int(raw_ver)

    if expected_ver is not None:
        if expected_ver != current_ver:
            return SessionValidationResult(
                state=SessionValidationState.REVOKED,
                user_id=uid,
                sid=parsed_sid,
                session_version=current_ver,
                user_active=True,
                reason="session_version_mismatch",
            )
    elif current_ver > 1:
        return SessionValidationResult(
            state=SessionValidationState.REVOKED,
            user_id=uid,
            sid=parsed_sid,
            session_version=current_ver,
            user_active=True,
            reason="legacy_ver_invalidated",
        )

    if parsed_sid is None:
        if require_modern:
            return SessionValidationResult(
                state=SessionValidationState.INVALID,
                user_id=uid,
                sid=None,
                session_version=current_ver,
                user_active=True,
                reason="modern_session_required",
            )
        return SessionValidationResult(
            state=SessionValidationState.LEGACY,
            user_id=uid,
            sid=None,
            session_version=current_ver,
            user_active=True,
            reason="legacy_token",
        )

    has_any = bool(row.get("has_any"))
    has_active = bool(row.get("has_active"))
    has_expired = bool(row.get("has_expired"))

    if not has_any:
        return SessionValidationResult(
            state=SessionValidationState.NOT_FOUND,
            user_id=uid,
            sid=parsed_sid,
            session_version=current_ver,
            user_active=True,
            reason="sid_not_found",
        )
    if has_active:
        return SessionValidationResult(
            state=SessionValidationState.ACTIVE,
            user_id=uid,
            sid=parsed_sid,
            session_version=current_ver,
            user_active=True,
            reason="ok",
        )
    if has_expired:
        return SessionValidationResult(
            state=SessionValidationState.EXPIRED,
            user_id=uid,
            sid=parsed_sid,
            session_version=current_ver,
            user_active=True,
            reason="sid_expired",
        )
    return SessionValidationResult(
        state=SessionValidationState.REVOKED,
        user_id=uid,
        sid=parsed_sid,
        session_version=current_ver,
        user_active=True,
        reason="sid_revoked",
    )


def raise_for_session_state(
    result: SessionValidationResult, *, require_modern: bool = False
) -> SessionValidationResult:
    """将 SessionValidationResult 转换为确定性 HTTP 安全响应（503 / 401）。"""
    if result.state == SessionValidationState.UNAVAILABLE:
        raise BizError("TT_COMMON_50301", "认证服务暂时不可用", 503)
    usable = result.is_usable_modern if require_modern else result.is_usable_normal
    if usable:
        return result
    if result.state in {SessionValidationState.REVOKED, SessionValidationState.EXPIRED}:
        raise BizError(TT_COMMON_40102[0], "登录已失效，请重新登录", 401)
    if result.state == SessionValidationState.INVALID and result.reason == "modern_session_required":
        raise BizError(TT_COMMON_40102[0], "当前登录会话版本过旧，请重新登录后操作", 401)
    code, message, status = TT_COMMON_40102
    raise BizError(code, message, status)
