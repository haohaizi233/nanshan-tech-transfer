"""Focused assertions for the organization-membership schema and authorization."""
import sys
from contextlib import contextmanager

import db
import core.middleware as middleware
from core.errors import BizError
import modules.membership.service as membership_service
from modules.membership.service import assert_active_membership, assert_org_admin_for
from modules.membership.schemas import (
    MembershipRejectionRequest,
    OrganizationApplicationRequest,
    VersionRequest,
)
from pydantic import ValidationError


PASS = 0
FAIL = 0

TABLES = (
    "organization_membership",
    "organization_membership_application",
    "organization_admin_application",
    "organization_application",
)
MEMBERSHIP_COLUMNS = {"org_id", "user_id", "role", "status", "version"}


class AuthorizationCursor:
    """Small database boundary fake for the authorization primitives."""

    def __init__(self, memberships=(), system_admins=()):
        self.memberships = list(memberships)
        self.system_admins = set(system_admins)
        self._row = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split())
        if "FROM organization_membership" in normalized:
            user_id, org_id = params
            matches = [
                row for row in self.memberships
                if row["user_id"] == user_id
                and row["org_id"] == org_id
                and row["status"] == "active"
            ]
            if "role = 'admin'" in normalized or "role='admin'" in normalized:
                matches = [row for row in matches if row["role"] == "admin"]
            self._row = {"ok": 1} if matches else None
            return
        if "FROM user_role" in normalized:
            self._row = {"ok": 1} if params[0] in self.system_admins else None
            return
        raise AssertionError(f"unexpected authorization query: {normalized}")

    def fetchone(self):
        return self._row


class IdentityCursor:
    def __init__(self, memberships=(), system_admins=()):
        self.memberships = list(memberships)
        self.system_admins = set(system_admins)
        self._rows = []
        self._row = None

    def execute(self, sql, params):
        normalized = " ".join(sql.split())
        if "FROM organization_membership" in normalized:
            self._rows = [
                {"org_id": row["org_id"]}
                for row in self.memberships
                if row["user_id"] == params[0]
                and row["role"] == "admin"
                and row["status"] == "active"
            ]
            return
        if "FROM user_role" in normalized:
            self._row = {"ok": 1} if params[0] in self.system_admins else None
            return
        raise AssertionError(f"unexpected identity query: {normalized}")

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._row


def expect_biz_error(name, expected_status, operation):
    try:
        operation()
    except BizError as exc:
        check(name, exc.http_status == expected_status, f"status={exc.http_status}")
        return
    check(name, False, "BizError was not raised")


def check_active_membership_rules():
    cur = AuthorizationCursor(
        memberships=(
            {"user_id": 11, "org_id": 101, "role": "member", "status": "active"},
            {"user_id": 11, "org_id": 202, "role": "member", "status": "revoked"},
        )
    )
    assert_active_membership(cur, 11, 101)
    check("active membership permits exact organization", True)
    expect_biz_error(
        "revoked membership cannot authorize organization",
        403,
        lambda: assert_active_membership(cur, 11, 202),
    )
    expect_biz_error(
        "membership cannot authorize another organization",
        403,
        lambda: assert_active_membership(cur, 11, 303),
    )


def check_org_admin_isolation():
    cur = AuthorizationCursor(
        memberships=(
            {"user_id": 21, "org_id": 101, "role": "admin", "status": "active"},
            {"user_id": 22, "org_id": 202, "role": "admin", "status": "revoked"},
        ),
        system_admins=(99,),
    )
    assert_org_admin_for(cur, {"userId": 21}, 101)
    check("organization admin can manage exact organization", True)
    expect_biz_error(
        "organization admin cannot manage another organization",
        403,
        lambda: assert_org_admin_for(cur, {"userId": 21}, 202),
    )
    expect_biz_error(
        "revoked organization admin cannot manage organization",
        403,
        lambda: assert_org_admin_for(cur, {"userId": 22}, 202),
    )
    assert_org_admin_for(cur, {"userId": 99}, 202)
    check("System Admin can manage any organization", True)


def check_realtime_identity():
    original_identity = middleware.identity
    original_get_cursor = db.get_cursor
    identity_cur = IdentityCursor(
        memberships=(
            {"user_id": 31, "org_id": 202, "role": "admin", "status": "revoked"},
            {"user_id": 31, "org_id": 101, "role": "admin", "status": "active"},
            {"user_id": 31, "org_id": 303, "role": "member", "status": "active"},
        )
    )

    @contextmanager
    def fake_get_cursor():
        yield identity_cur

    try:
        middleware.identity = lambda request: {
            "userId": 31,
            "userNo": "U31",
            "roles": ["organization-admin-from-stale-jwt"],
        }
        db.get_cursor = fake_get_cursor
        current = middleware.org_admin_identity(object())
        check(
            "organization-admin identity uses current active admin memberships",
            current["organizationAdminOrgIds"] == [101],
            str(current["organizationAdminOrgIds"]),
        )

        identity_cur.memberships = []
        expect_biz_error(
            "JWT role snapshot cannot grant organization administration",
            403,
            lambda: middleware.org_admin_identity(object()),
        )
    finally:
        middleware.identity = original_identity
        db.get_cursor = original_get_cursor


def check_active_membership_ids():
    original_get_cursor = membership_service.get_cursor

    class ActiveIdsCursor:
        def execute(self, sql, params):
            normalized = " ".join(sql.split())
            assert "status = 'active'" in normalized
            assert params == (41,)

        def fetchall(self):
            return [{"org_id": 101}, {"org_id": 202}, {"org_id": 101}]

    @contextmanager
    def fake_get_cursor():
        yield ActiveIdsCursor()

    try:
        membership_service.get_cursor = fake_get_cursor
        check(
            "active membership organization ids are returned as a set",
            membership_service.active_membership_org_ids(41) == {101, 202},
        )
    finally:
        membership_service.get_cursor = original_get_cursor


def rejects(schema, payload):
    try:
        schema.model_validate(payload)
    except ValidationError:
        return True
    return False


def check_request_validation():
    check(
        "state changes reject boolean versions",
        rejects(VersionRequest, {"version": True}),
    )
    check(
        "rejections require a non-blank reason",
        rejects(MembershipRejectionRequest, {"version": 1, "reason": "   "}),
    )
    check(
        "organization applications require a non-blank name",
        rejects(OrganizationApplicationRequest, {"requestedName": "   "}),
    )


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} — {detail}")


def main():
    with db.get_cursor() as cur:
        cur.execute(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
              AND table_name = ANY(%s)
            """,
            (list(TABLES),),
        )
        existing_tables = {row["table_name"] for row in cur.fetchall()}

        cur.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND table_name = 'organization_membership'
            """
        )
        membership_columns = {row["column_name"] for row in cur.fetchall()}

    for table_name in TABLES:
        check(f"table {table_name} exists", table_name in existing_tables)
    check(
        "organization_membership has required columns",
        MEMBERSHIP_COLUMNS <= membership_columns,
        f"missing: {sorted(MEMBERSHIP_COLUMNS - membership_columns)}",
    )
    check_active_membership_rules()
    check_org_admin_isolation()
    check_realtime_identity()
    check_active_membership_ids()
    check_request_validation()

    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
