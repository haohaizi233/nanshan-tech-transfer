"""生产安全数据库 Schema 版本启动门禁（Phase R-Final）。

确保生产/预发环境在启动安全服务前已完成 038 及前置关键迁移，
严禁因缺失字段或约束而自动降级到弱化认证或弱化幂等路径。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("nanshan.security.schema_gate")

REQUIRED_SECURITY_SCHEMA_VERSION = "040"
REQUIRED_APPLICATION_SCHEMA_VERSION = "042"

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
        "risk_sync_state",
        "risk_sync_target",
        "risk_sync_attempts",
        "risk_sync_next_retry_at",
        "risk_sync_last_error_code",
        "risk_sync_claimed_at",
        "risk_sync_updated_at",
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
        "stage_provenance",
    ),
}

REQUIRED_SECURITY_CONSTRAINTS: dict[str, tuple[str, ...]] = {
    "step_up_grant": ("chk_step_up_grant_email_target",),
    "auth_challenge": (
        "chk_auth_challenge_status",
        "chk_auth_challenge_send_state",
        "chk_auth_challenge_stepup_context",
        "chk_auth_challenge_risk_sync_state",
        "chk_auth_challenge_risk_sync_target",
        "ck_auth_challenge_registration_owner",
    ),
    "security_delivery_request": (
        "chk_sdr_execution_stage",
        "chk_sdr_stage_provenance",
    ),
}


REQUIRED_SECURITY_INDEXES: dict[str, tuple[str, ...]] = {
    "auth_challenge": ("uk_auth_challenge_active_registration_phone",),
}

REQUIRED_SECURITY_NULLABLE: dict[str, tuple[str, ...]] = {
    "auth_challenge": ("user_id",),
}

REQUIRED_APPLICATION_COLUMNS: dict[str, tuple[str, ...]] = {
    "capital_module_icon": ("module_key", "png"),
    "capital_institution_icon": ("institution_id", "png"),
    "ai_chat_turn": ("turn_id", "status"),
    "ai_task": ("id", "task_type", "status"),
}


def check_required_security_schema(cur: Any = None) -> dict[str, Any]:
    """核验当前 PostgreSQL schema 是否具备 Phase R/P3-A (040) 所需列、约束、可空性与索引。"""
    from db import get_cursor

    def _inspect(db_cur: Any) -> dict[str, Any]:
        tables = sorted(
            set(REQUIRED_SECURITY_COLUMNS)
            | set(REQUIRED_SECURITY_CONSTRAINTS)
            | set(REQUIRED_SECURITY_INDEXES)
            | set(REQUIRED_SECURITY_NULLABLE)
        )
        db_cur.execute(
            """
            SELECT table_name, column_name, is_nullable
            FROM information_schema.columns
            WHERE table_schema = current_schema()
              AND table_name = ANY(%s)
            """,
            (tables,),
        )
        present_cols: dict[str, set[str]] = {t: set() for t in tables}
        nullable_cols: dict[str, dict[str, bool]] = {t: {} for t in tables}
        for row in db_cur.fetchall() or []:
            if isinstance(row, dict):
                tname = str(row.get("table_name") or "")
                cname = str(row.get("column_name") or "")
                is_null = str(row.get("is_nullable") or "").upper() == "YES"
            else:
                tname, cname = str(row[0]), str(row[1])
                is_null = len(row) > 2 and str(row[2] or "").upper() == "YES"
            if tname in present_cols:
                present_cols[tname].add(cname)
                nullable_cols[tname][cname] = is_null

        missing_columns: list[str] = []
        for table, cols in REQUIRED_SECURITY_COLUMNS.items():
            existing = present_cols.get(table, set())
            for col in cols:
                if col not in existing:
                    missing_columns.append(f"{table}.{col}")

        for table, cols in REQUIRED_SECURITY_NULLABLE.items():
            for col in cols:
                if col in present_cols.get(table, set()) and not nullable_cols.get(table, {}).get(col, False):
                    missing_columns.append(f"{table}.{col}(NOT NULL)")

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

        db_cur.execute(
            """
            SELECT tablename AS table_name, indexname AS index_name
            FROM pg_indexes
            WHERE schemaname = current_schema()
              AND tablename = ANY(%s)
            """,
            (sorted(REQUIRED_SECURITY_INDEXES),),
        )
        present_idxs: dict[str, set[str]] = {t: set() for t in REQUIRED_SECURITY_INDEXES}
        for row in db_cur.fetchall() or []:
            if isinstance(row, dict):
                tname = str(row.get("table_name") or "")
                iname = str(row.get("index_name") or "")
            else:
                tname, iname = str(row[0]), str(row[1])
            if tname in present_idxs:
                present_idxs[tname].add(iname)

        missing_indexes: list[str] = []
        for table, idxs in REQUIRED_SECURITY_INDEXES.items():
            existing_idxs = present_idxs.get(table, set())
            for idx in idxs:
                if idx not in existing_idxs:
                    missing_indexes.append(f"{table}.{idx}")

        ok = not missing_columns and not missing_constraints and not missing_indexes
        return {
            "ok": ok,
            "required_version": REQUIRED_SECURITY_SCHEMA_VERSION,
            "missing_columns": missing_columns,
            "missing_constraints": missing_constraints,
            "missing_indexes": missing_indexes,
        }

    if cur is not None:
        return _inspect(cur)
    with get_cursor() as db_cur:
        return _inspect(db_cur)


def check_required_application_schema(cur: Any = None) -> dict[str, Any]:
    """核验当前 PostgreSQL schema 是否具备应用层关键迁移 (042) 所需表与列。"""
    from db import get_cursor

    def _inspect(db_cur: Any) -> dict[str, Any]:
        tables = sorted(REQUIRED_APPLICATION_COLUMNS)
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
        for table, cols in REQUIRED_APPLICATION_COLUMNS.items():
            existing = present_cols.get(table, set())
            for col in cols:
                if col not in existing:
                    missing_columns.append(f"{table}.{col}")

        return {
            "ok": not missing_columns,
            "required_version": REQUIRED_APPLICATION_SCHEMA_VERSION,
            "missing_columns": missing_columns,
        }

    if cur is not None:
        return _inspect(cur)
    with get_cursor() as db_cur:
        return _inspect(db_cur)


def assert_required_application_schema(cur: Any = None) -> dict[str, Any]:
    try:
        result = check_required_application_schema(cur=cur)
    except Exception as exc:
        raise RuntimeError(
            f"Application schema gate failed (required={REQUIRED_APPLICATION_SCHEMA_VERSION}): {type(exc).__name__}"
        ) from exc
    if not result["ok"]:
        raise RuntimeError(
            f"Application schema version below required {REQUIRED_APPLICATION_SCHEMA_VERSION}: "
            f"missing_columns={result['missing_columns']}"
        )
    return result


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
