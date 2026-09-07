"""Focused assertions for the organization-membership schema and authorization."""
import json
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


class CursorConnection:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


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


def check_member_approval_cannot_demote_admin():
    class ActiveAdminCursor:
        def __init__(self):
            self._row = None

        def execute(self, sql, params):
            normalized = " ".join(sql.split())
            if normalized.startswith("SELECT id, user_id, org_id, role, status, version"):
                self._row = {
                    "id": 501,
                    "user_id": 51,
                    "org_id": 101,
                    "role": "admin",
                    "status": "active",
                    "version": 3,
                }
                return
            raise AssertionError("member activation attempted to mutate an active admin")

        def fetchone(self):
            return self._row

    try:
        membership_service._activate_membership(
            ActiveAdminCursor(), 51, 101, "member", actor_id=99,
        )
    except BizError as exc:
        check(
            "pending member approval cannot demote an active administrator",
            exc.http_status == 409,
            f"status={exc.http_status}",
        )
    except AssertionError as exc:
        check("pending member approval cannot demote an active administrator", False, str(exc))
    else:
        check("pending member approval cannot demote an active administrator", False, "no conflict")


def check_revoked_user_can_apply_for_admin():
    class AdminApplicationCursor:
        def __init__(self):
            self._row = None
            self.memberships = [
                {"user_id": 61, "org_id": 101, "role": "member", "status": "revoked"},
            ]

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, sql, params):
            normalized = " ".join(sql.split())
            if "FROM organization WHERE" in normalized:
                self._row = {"ok": 1}
            elif "FROM organization_membership" in normalized:
                matches = [
                    row for row in self.memberships
                    if row["user_id"] == params[0]
                    and row["org_id"] == params[1]
                    and row["status"] == "active"
                ]
                if "role = 'admin'" in normalized:
                    matches = [row for row in matches if row["role"] == "admin"]
                self._row = {"ok": 1} if matches else None
            elif "FROM organization_admin_application" in normalized:
                self._row = None
            elif normalized.startswith("INSERT INTO organization_admin_application"):
                self._row = {
                    "id": 601,
                    "user_id": 61,
                    "org_id": 101,
                    "status": "pending",
                    "version": 1,
                }
            else:
                raise AssertionError(f"unexpected admin-application query: {normalized}")

        def fetchone(self):
            return self._row

    original_transaction = membership_service.transaction
    cursor = AdminApplicationCursor()

    @contextmanager
    def fake_transaction():
        yield CursorConnection(cursor)

    try:
        membership_service.transaction = fake_transaction
        try:
            result = membership_service.apply_organization_admin(
                {"userId": 61}, {"orgId": 101, "reason": "负责机构认证"},
            )
        except (BizError, AssertionError) as exc:
            check("revoked user can submit organization-admin application", False, str(exc))
        else:
            check(
                "revoked user can submit organization-admin application",
                result == {
                    "id": 601,
                    "userId": 61,
                    "orgId": 101,
                    "status": "pending",
                    "version": 1,
                },
                str(result),
            )
    finally:
        membership_service.transaction = original_transaction


def check_admin_rejection_audit_has_org_id():
    class AdminRejectionCursor:
        def __init__(self):
            self._row = None
            self.audit_details = None

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def execute(self, sql, params):
            normalized = " ".join(sql.split())
            if "FROM user_role" in normalized:
                self._row = {"ok": 1}
            elif normalized.startswith("SELECT id,") and "organization_admin_application" in normalized:
                self._row = {"id": 701, "user_id": 71}
                if "org_id" in normalized.split("FROM", 1)[0]:
                    self._row["org_id"] = 101
            elif normalized.startswith("UPDATE organization_admin_application"):
                self._row = {"id": 701, "user_id": 71, "status": "rejected", "version": 2}
                if "org_id" in normalized.split("RETURNING", 1)[-1]:
                    self._row["org_id"] = 101
            elif normalized.startswith("INSERT INTO audit_log"):
                self.audit_details = json.loads(params[5])
                self._row = None
            else:
                raise AssertionError(f"unexpected admin-rejection query: {normalized}")

        def fetchone(self):
            return self._row

    original_transaction = membership_service.transaction
    cursor = AdminRejectionCursor()

    @contextmanager
    def fake_transaction():
        yield CursorConnection(cursor)

    try:
        membership_service.transaction = fake_transaction
        result = membership_service.reject_organization_admin_application(
            {"userId": 99, "userNo": "SYS-99"}, 701, 1, "材料不足",
        )
        check(
            "organization-admin rejection audit includes organization id",
            cursor.audit_details is not None
            and cursor.audit_details.get("orgId") == 101
            and result.get("orgId") == 101,
            f"result={result}, audit={cursor.audit_details}",
        )
    finally:
        membership_service.transaction = original_transaction


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
    check_member_approval_cannot_demote_admin()
    check_revoked_user_can_apply_for_admin()
    check_admin_rejection_audit_has_org_id()
    check_request_validation()

    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
