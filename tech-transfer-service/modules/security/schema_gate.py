"""生产安全数据库 Schema 版本启动门禁（Phase R-Final）。

确保生产/预发环境在启动安全服务前已完成 038 及前置关键迁移，
严禁因缺失字段或约束而自动降级到弱化认证或弱化幂等路径。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nanshan.security.schema_gate")

REQUIRED_SECURITY_SCHEMA_VERSION = "038"

REQUIRED_SECURITY_COLUMNS: dict[str, tuple[str, ...]] = {
    "app_user": ("session_version",),
    "auth_session": ("sid", "auth_time"),
    "step_up_grant": ("session_id", "target_fingerprint"),
    "auth_challenge": (
        "send_state",
        "provider_name",
        "provider_config_id",
        "session_id",
        "session_version",
        "sub_purpose",
        "target_fingerprint",
        "source_contact_fingerprint",
        "send_owner",
        "send_claimed_at",
    ),
    "security_delivery_request": (
        "channel",
        "purpose",
        "provider",
        "idempotency_scope",
        "idempotency_key",
        "request_hash",
        "idempotency_expires_at",
        "response_payload",
        "execution_owner",
        "execution_stage",
        "challenge_id",
        "idem_claimed_at",
    ),
}

REQUIRED_SECURITY_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "step_up_grant": ("chk_step_up_grant_email_target",),
    "auth_challenge": (
        "chk_auth_challenge_status",
        "chk_auth_challenge_send_state",
        "chk_auth_challenge_stepup_context",
    ),
    "security_delivery_request": ("chk_sdr_execution_stage",),
}


def check_required_security_schema(cur: Any = None) -> dict[str, Any]:
    """核验当前 PostgreSQL schema 是否具备 Phase R-Final (038) 所需列与约束。"""
    from db import get_cursor

    def _inspect(db_cur: Any) -> dict[str, Any]:
        tables = sorted(set(REQUIRED_SECURITY_COLUMNS) | set(REQUIRED_SECURITY_CONSTRAINTS))
        db_cur.execute(
            """
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
            """,
            (tables,),
        )
        present_cols: dict[str, set[str]] = {t: set() for t in tables}
        for row in db_cur.fetchall() or []:
            if isinstance(row, dict):
                tname = str(row.get("table_name") or "")
                cname = str(row.get("column_name") or "")
            else:
                tname, cname = str(row[0]), str(row[1])
            if tname in present_cols:
                present_cols[tname].add(cname)

        missing_columns: list[str] = []
        for table, cols in REQUIRED_SECURITY_COLUMNS.items():
            existing = present_cols.get(table, set())
            for col in cols:
                if col not in existing:
                    missing_columns.append(f"{table}.{col}")

        db_cur.execute(
            """
            SELECT c.relname AS table_name, con.conname AS constraint_name
            FROM pg_constraint con
            JOIN pg_class c ON c.oid = con.conrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = current_schema()
              AND c.relname = ANY(%s)
            """,
            (tables,),
        )
        present_cons: dict[str, set[str]] = {t: set() for t in tables}
        for row in db_cur.fetchall() or []:
            if isinstance(row, dict):
                tname = str(row.get("table_name") or "")
                conname = str(row.get("constraint_name") or "")
            else:
                tname, conname = str(row[0]), str(row[1])
            if tname in present_cons:
                present_cons[tname].add(conname)

        missing_constraints: list[str] = []
        for table, cons in REQUIRED_SECURITY_CONSTRAINTS.items():
            existing_cons = present_cons.get(table, set())
            for con in cons:
                if con not in existing_cons:
                    missing_constraints.append(f"{table}.{con}")

        ok = not missing_columns and not missing_constraints
        return {
            "ok": ok,
            "required_version": REQUIRED_SECURITY_SCHEMA_VERSION,
            "missing_columns": missing_columns,
            "missing_constraints": missing_constraints,
        }

    if cur is not None:
        return _inspect(cur)
    with get_cursor() as db_cur:
        return _inspect(db_cur)


def assert_required_security_schema(cur: Any = None) -> dict[str, Any]:
    """生产级启动门禁：数据库未完成 038 迁移或不可用时拒绝提供服务。"""
    try:
        result = check_required_security_schema(cur=cur)
    except Exception as exc:
        logger.error("安全 Schema 版本检查失败（数据库不可用）: %s", type(exc).__name__)
        raise RuntimeError(
            f"Security schema gate failed (required={REQUIRED_SECURITY_SCHEMA_VERSION}): {type(exc).__name__}"
        ) from exc

    if not result["ok"]:
        logger.error(
            "安全 Schema 版本不满足要求 (required=%s, missing_columns=%s, missing_constraints=%s)",
            REQUIRED_SECURITY_SCHEMA_VERSION,
            result["missing_columns"],
            result["missing_constraints"],
        )
        raise RuntimeError(
            f"Security schema version below required {REQUIRED_SECURITY_SCHEMA_VERSION}: "
            f"missing_columns={result['missing_columns']}, missing_constraints={result['missing_constraints']}"
        )
    return result
