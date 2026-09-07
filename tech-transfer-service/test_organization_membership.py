"""Focused assertions for the organization-membership schema and authorization."""
import json
import sys
import uuid
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


def check_http_flows():
    """Real HTTP/auth/service/DB flows; fixtures are unique and cleaned by exact IDs."""
    from fastapi.testclient import TestClient
    from app import app
    from core.jwt_utils import sign_access_token

    suffix = uuid.uuid4().hex[:12]
    users, orgs = [], []
    names = [f"membership-{suffix}-{i}" for i in range(5)]
    try:
        with db.get_cursor(commit=True) as cur:
            for i in range(4):
                cur.execute("INSERT INTO app_user (user_no) VALUES (%s) RETURNING id", (f"M{suffix}{i}",))
                users.append(cur.fetchone()["id"])
            for i in range(4):
                cur.execute(
                    "INSERT INTO organization (org_name, status, deleted_at) VALUES (%s, %s, %s) RETURNING id",
                    (names[i], "inactive" if i == 2 else "active", "2026-01-01" if i == 3 else None),
                )
                orgs.append(cur.fetchone()["id"])
            cur.execute("INSERT INTO user_role (user_id, role_code) VALUES (%s, 'admin')", (users[3],))
            cur.execute(
                "INSERT INTO organization_membership (user_id, org_id, role) VALUES (%s, %s, 'admin') RETURNING id",
                (users[1], orgs[0]),
            )
            org_admin_membership = cur.fetchone()["id"]
        headers = [
            {"Authorization": f"Bearer {sign_access_token(uid, f'M{suffix}{i}', ['user'])}",
             "X-Request-Id": f"membership-{suffix}"}
            for i, uid in enumerate(users)
        ]
        with TestClient(app) as client:
            def call(method, path, who=0, body=None, status=200):
                response = client.request(
                    method, "/api/tech-transfer/v1" + path,
                    headers=headers[who] if who is not None else {}, json=body,
                )
                check(f"HTTP {method} {path} = {status}", response.status_code == status, response.text[:300])
                if response.status_code != status:
                    raise AssertionError(f"unexpected response: {response.status_code} {response.text[:300]}")
                payload = response.json()
                check("HTTP response carries request ID", payload.get("requestId") == response.headers.get("X-Request-Id"))
                return payload.get("data")

            def all_pages(path, who):
                separator = "&" if "?" in path else "?"
                result = call("GET", f"{path}{separator}pageSize=50", who=who)
                rows = list(result["list"])
                for page in range(2, (result["total"] + 49) // 50 + 1):
                    rows.extend(call("GET", f"{path}{separator}pageSize=50&page={page}", who=who)["list"])
                return {**result, "list": rows}

            call("GET", "/organizations/search", who=None, status=401)
            found = call("GET", f"/organizations/search?keyword={suffix}&page=1&pageSize=1")
            check("canonical search excludes inactive/deleted and paginates", found["total"] == 2 and len(found["list"]) == 1)
            check("search candidate includes canonical name", found["list"][0]["orgName"] == names[0])
            check("search never grants membership", call("GET", "/me/organization-memberships")["list"] == [])
            call("POST", "/me/organization-membership-applications", body={"orgId": orgs[2]}, status=404)
            application = call("POST", "/me/organization-membership-applications", body={"orgId": orgs[0], "realName": "申请人", "proofMaterial": "proof"})
            aid = application["id"]
            call("POST", "/me/organization-membership-applications", body={"orgId": orgs[0]}, status=409)
            call("GET", f"/org-admin/members?orgId={orgs[0]}", status=403)
            queue = all_pages(f"/org-admin/membership-applications?orgId={orgs[0]}&status=pending", who=1)
            check("review queue includes evidence", any(row["id"] == aid and row["proofMaterial"] == "proof" for row in queue["list"]))
            cross = call("POST", "/me/organization-membership-applications", who=2, body={"orgId": orgs[1]})
            call("GET", f"/org-admin/membership-applications?orgId={orgs[1]}", who=1, status=403)
            call("GET", f"/org-admin/members?orgId={orgs[1]}", who=1, status=403)
            call("POST", f"/org-admin/membership-applications/{cross['id']}/approve", who=1, body={"version": 1}, status=403)
            call("POST", f"/org-admin/membership-applications/{cross['id']}/reject", who=1, body={"version": 1, "reason": "no"}, status=403)
            call("POST", f"/org-admin/membership-applications/{aid}/approve", who=1, body={"version": 99}, status=409)
            for version in (True, "1", 1.5, 0):
                call("POST", f"/org-admin/membership-applications/{aid}/approve", who=1, body={"version": version}, status=422)
            # Audit storage is the injected failure boundary; the real transaction
            # must roll back both the application review and new membership.
            from unittest.mock import patch
            import psycopg2
            with patch.object(membership_service, "audit_record", side_effect=psycopg2.DataError("test audit failure")):
                call("POST", f"/org-admin/membership-applications/{aid}/approve", who=1, body={"version": 1}, status=500)
            with db.get_cursor() as cur:
                cur.execute("SELECT status, version FROM organization_membership_application WHERE id = %s", (aid,))
                pending = cur.fetchone()
                cur.execute("SELECT COUNT(*) AS total FROM organization_membership WHERE user_id = %s", (users[0],))
                member_count = cur.fetchone()["total"]
                cur.execute("SELECT COUNT(*) AS total FROM audit_log WHERE actor_user_id = ANY(%s)", (users,))
                audit_count = cur.fetchone()["total"]
            check("audit failure rolls back application and membership atomically", pending["status"] == "pending" and pending["version"] == 1 and member_count == 0 and audit_count == 0)
            approved = call("POST", f"/org-admin/membership-applications/{aid}/approve", who=1, body={"version": 1})
            mid = approved["membership"]["id"]
            check("approval activates membership", approved["membership"]["status"] == "active" and approved["membership"]["role"] == "member")
            mine = call("GET", "/me/organization-memberships")
            check("own membership includes canonical name", mine["list"][0]["orgName"] == names[0])
            members = call("GET", f"/org-admin/members?orgId={orgs[0]}&status=active", who=1)
            check("member list includes approved member", mid in [row["id"] for row in members["list"]])
            call("POST", f"/org-admin/membership-applications/{aid}/approve", who=1, body={"version": 1}, status=409)
            call("POST", f"/org-admin/members/{org_admin_membership}/revoke", who=1, body={"version": 1, "reason": "no"}, status=409)
            call("POST", f"/org-admin/members/{mid}/revoke", who=1, body={"version": 1, "reason": "离职"})
            reapply = call("POST", "/me/organization-membership-applications", body={"orgId": orgs[0]})
            call("POST", f"/org-admin/membership-applications/{reapply['id']}/reject", who=1, body={"version": 1, "reason": "   "}, status=422)
            call("POST", f"/org-admin/membership-applications/{reapply['id']}/reject", who=1, body={"version": 1, "reason": "材料不足"})
            reapply = call("POST", "/me/organization-membership-applications", body={"orgId": orgs[0]})
            revived = call("POST", f"/org-admin/membership-applications/{reapply['id']}/approve", who=1, body={"version": 1})["membership"]
            check("reapplication reactivates revoked membership", revived["id"] == mid and revived["version"] == 3)
            call("POST", f"/me/organization-membership-applications/{cross['id']}/cancel", body={"version": 1}, status=404)
            call("POST", f"/me/organization-membership-applications/{cross['id']}/cancel", who=2, body={"version": 99}, status=409)
            cancelled = call("POST", f"/me/organization-membership-applications/{cross['id']}/cancel", who=2, body={"version": 1})
            check("owner cancels pending application", cancelled["status"] == "cancelled")
            cross = call("POST", "/me/organization-membership-applications", who=2, body={"orgId": orgs[1]})
            cross_member = call("POST", f"/org-admin/membership-applications/{cross['id']}/approve", who=3, body={"version": 1})["membership"]
            call("POST", f"/org-admin/members/{cross_member['id']}/revoke", who=1, body={"version": 1, "reason": "no"}, status=403)
            grant_path = f"/admin/organization-memberships/{mid}/grant-admin"
            revoke_path = f"/admin/organization-memberships/{mid}/revoke-admin"
            call("POST", grant_path, who=1, body={"version": 3}, status=403)
            call("POST", grant_path, who=3, body={"version": 2}, status=409)
            granted = call("POST", grant_path, who=3, body={"version": 3})
            check("System Admin grants admin role", granted["role"] == "admin")
            call("POST", revoke_path, who=1, body={"version": 4, "reason": "no"}, status=403)
            call("POST", revoke_path, who=3, body={"version": 4, "reason": "任期结束"})
            call("GET", f"/org-admin/members?orgId={orgs[0]}", status=403)
            admin_app = call("POST", "/me/organization-admin-applications", body={"orgId": orgs[0], "proofMaterial": "admin-proof"})
            call("GET", "/admin/organization-admin-applications", who=1, status=403)
            queue = all_pages("/admin/organization-admin-applications?status=pending", who=3)
            check("admin application evidence visible to System Admin", any(row["id"] == admin_app["id"] and row["proofMaterial"] == "admin-proof" for row in queue["list"]))
            path = f"/admin/organization-admin-applications/{admin_app['id']}"
            call("POST", path + "/approve", who=1, body={"version": 1}, status=403)
            call("POST", path + "/reject", who=3, body={"version": 1, "reason": "补材料"})
            admin_app = call("POST", "/me/organization-admin-applications", body={"orgId": orgs[0]})
            call("POST", f"/admin/organization-admin-applications/{admin_app['id']}/approve", who=3, body={"version": 1})
            org_app = call("POST", "/me/organization-applications", who=2, body={"requestedName": names[4], "requestedType": "enterprise", "contactName": "申请人"})
            path = f"/admin/organization-applications/{org_app['id']}"
            call("GET", "/admin/organization-applications", who=1, status=403)
            queue = all_pages("/admin/organization-applications?status=pending", who=3)
            check("new organization queue includes requested fields", any(row["id"] == org_app["id"] and row["requestedName"] == names[4] for row in queue["list"]))
            call("POST", path + "/approve", who=1, body={"version": 1}, status=403)
            call("POST", path + "/reject", who=3, body={"version": 1, "reason": "补材料"})
            org_app = call("POST", "/me/organization-applications", who=2, body={"requestedName": names[4], "requestedType": "enterprise"})
            created = call("POST", f"/admin/organization-applications/{org_app['id']}/approve", who=3, body={"version": 1})
            orgs.append(created["orgId"])
            check("new organization grants active administrator", created["membership"]["orgId"] == created["orgId"] and created["membership"]["role"] == "admin" and created["membership"]["status"] == "active")
            found = call("GET", f"/organizations/search?keyword={names[4]}")
            check("approved organization is canonical searchable candidate", found["list"][0]["id"] == created["orgId"])
            with db.get_cursor() as cur:
                cur.execute("SELECT action, details, request_id FROM audit_log WHERE actor_user_id = ANY(%s)", (users,))
                audits = cur.fetchall()
            actions = {row["action"] for row in audits}
            check("reviews, cancellation, grants and revokes have audits", {
                "organization_membership_application.approve", "organization_membership_application.reject",
                "organization_membership_application.cancel", "organization_membership.revoke",
                "organization_admin.grant", "organization_admin.revoke",
                "organization_admin_application.approve", "organization_admin_application.reject",
                "organization_application.approve", "organization_application.reject",
            } <= actions)
            check("audit records carry HTTP request ID", all(row["request_id"] == f"membership-{suffix}" for row in audits))
    except AssertionError as exc:
        print(f"[HTTP FLOW STOPPED] {exc}")
    finally:
        # Only remove rows created by this invocation; never mutate existing fixtures.
        if users:
            with db.get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log WHERE actor_user_id = ANY(%s)", (users,))
                for table in TABLES:
                    column = "applicant_user_id" if table == "organization_application" else "user_id"
                    cur.execute(f"DELETE FROM {table} WHERE {column} = ANY(%s)", (users,))
                cur.execute("DELETE FROM user_role WHERE user_id = ANY(%s)", (users,))
                cur.execute("DELETE FROM app_user WHERE id = ANY(%s)", (users,))
                cur.execute("DELETE FROM organization WHERE org_name = ANY(%s)", (names,))


def check_profile_and_content_associations():
    """Exercise text/identity separation and content authorization against real DB rows."""
    from fastapi.testclient import TestClient
    from app import app
    from core.jwt_utils import sign_access_token

    suffix = uuid.uuid4().hex[:12]
    users, orgs = [], []
    display_name = f"display-only-{suffix}"
    try:
        with db.get_cursor(commit=True) as cur:
            for i in range(2):
                cur.execute("INSERT INTO app_user (user_no) VALUES (%s) RETURNING id", (f"T4{suffix}{i}",))
                users.append(cur.fetchone()["id"])
                cur.execute("INSERT INTO organization (org_name, intro) VALUES (%s, 'original intro') RETURNING id", (f"canonical-{suffix}-{i}",))
                orgs.append(cur.fetchone()["id"])
            cur.execute("INSERT INTO user_profile (user_id, org_id) VALUES (%s, %s)", (users[0], orgs[0]))
            cur.execute("INSERT INTO user_profile (user_id) VALUES (%s)", (users[1],))
            cur.execute("INSERT INTO organization_membership (user_id, org_id, role) VALUES (%s, %s, 'member')", (users[1], orgs[1]))
        headers = [{"Authorization": f"Bearer {sign_access_token(uid, f'T4{suffix}{i}', ['user'])}"} for i, uid in enumerate(users)]
        with TestClient(app) as client:
            def call(method, path, body=None, who=0, status=200):
                response = client.request(method, "/api/tech-transfer/v1" + path, headers=headers[who], json=body)
                check(f"association {method} {path} = {status}", response.status_code == status, response.text[:200])
                return response.json().get("data") or {}

            profile = call("GET", "/me")
            check("legacy profile orgId does not certify membership", profile.get("organizationMemberships") == [])
            updated = call("PATCH", "/me/profile", {"version": 1, "companyText": f"  {display_name}  "})
            check("company text is editable display text", updated.get("companyText") == display_name)
            check("company text does not create formal membership", updated.get("organizationMemberships") == [])
            for invalid_text in (123, {"orgId": orgs[1]}, "x" * 129):
                call("PATCH", "/me/profile", {"version": updated.get("version", 1), "companyText": invalid_text}, status=400)
            call("PATCH", "/me/profile", {"version": updated.get("version", 1), "orgId": orgs[1]}, status=400)
            with db.get_cursor() as cur:
                cur.execute("SELECT org_id FROM user_profile WHERE user_id=%s", (users[0],))
                check("direct profile orgId cannot change legacy association", cur.fetchone()["org_id"] == orgs[0])
                cur.execute("SELECT COUNT(*) AS c FROM organization_membership WHERE user_id=%s", (users[0],))
                check("profile edits create no membership rows", cur.fetchone()["c"] == 0)
                cur.execute("SELECT COUNT(*) AS c FROM organization WHERE org_name=%s", (display_name,))
                check("profile company text creates no canonical organization", cur.fetchone()["c"] == 0)
            profile = call("GET", "/me", who=1)
            memberships = profile.get("organizationMemberships", [])
            check("profile returns canonical active membership", len(memberships) == 1 and memberships[0].get("orgId") == orgs[1] and memberships[0].get("orgName") == f"canonical-{suffix}-1" and memberships[0].get("role") == "member" and memberships[0].get("status") == "active")

            for resource, table, content, text_key, column in (
                ("demands", "demand", {"description": "ordinary publishing"}, "orgName", "org_name_snapshot"),
                ("achievements", "achievement", {"maturityLevel": "02_lab", "pricingMode": "negotiable"}, "sourceOrgName", "source_org_name"),
            ):
                base = {"title": f"task4-{suffix}", **content}
                plain = call("POST", f"/{resource}", base, status=201)
                if plain.get("id"):
                    call("POST", f"/{resource}/{plain['id']}/submit", {"version": 1})
                with db.get_cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS c FROM organization WHERE org_name=%s", (display_name,))
                    organization_count = cur.fetchone()["c"]
                display = call("POST", f"/{resource}", {**base, "orgId": None, text_key: display_name}, status=201)
                check(f"{resource} preserve display snapshot", display.get(text_key) == display_name)
                with db.get_cursor() as cur:
                    cur.execute("SELECT COUNT(*) AS c FROM organization WHERE org_name=%s", (display_name,))
                    check(f"{resource} display text creates no canonical organization", cur.fetchone()["c"] == organization_count)
                    cur.execute(f"SELECT org_id, {column} FROM {table} WHERE id=%s", (display.get("id", -1),))
                    row = cur.fetchone() or {}
                    check(f"{resource} text remains unassociated", row.get("org_id") is None and row.get(column) == display_name)
                call("POST", f"/{resource}", {**base, "orgId": orgs[0]}, status=403)
                call("POST", f"/{resource}", {**base, "orgId": orgs[0], text_key: f"canonical-{suffix}-1"}, who=1, status=403)
                if display.get("id"):
                    call("PATCH", f"/{resource}/{display['id']}", {"version": 1, "orgId": orgs[1]}, status=403)
                    with db.get_cursor() as cur:
                        cur.execute(f"SELECT org_id, version FROM {table} WHERE id=%s", (display["id"],))
                        row = cur.fetchone()
                        check(f"{resource} forged update leaves row unchanged", row["org_id"] is None and row["version"] == 1)
                valid = call("POST", f"/{resource}", {**base, "orgId": orgs[1], text_key: display_name}, who=1, status=201)
                if valid.get("id"):
                    call("PATCH", f"/{resource}/{valid['id']}", {"version": 1, "orgId": orgs[1], text_key: display_name + "-edit"}, who=1)
                    with db.get_cursor() as cur:
                        cur.execute(f"SELECT org_id, {column} FROM {table} WHERE id=%s", (valid["id"],))
                        row = cur.fetchone()
                        check(f"{resource} active membership authorizes exact org without guessing from text", row["org_id"] == orgs[1] and row[column] == display_name + "-edit")
                        cur.execute("SELECT intro FROM organization WHERE id=%s", (orgs[1],))
                        check(f"{resource} does not edit canonical organization", cur.fetchone()["intro"] == "original intro")
                    with db.get_cursor(commit=True) as cur:
                        cur.execute("UPDATE organization_membership SET status='revoked' WHERE user_id=%s", (users[1],))
                    profile = call("GET", "/me", who=1)
                    check("revoked membership immediately disappears from certification", profile.get("organizationMemberships") == [])
                    call("POST", f"/{resource}", {**base, "orgId": orgs[1]}, who=1, status=403)
                    call("PATCH", f"/{resource}/{valid['id']}", {"version": 2, "orgId": orgs[1]}, who=1, status=403)
                    # An unrelated edit must not rewrite a pre-existing association.
                    call("PATCH", f"/{resource}/{valid['id']}", {"version": 2, "title": base["title"] + " edited"}, who=1)
                    with db.get_cursor(commit=True) as cur:
                        cur.execute(f"SELECT org_id FROM {table} WHERE id=%s", (valid["id"],))
                        check(f"{resource} existing association is preserved on unrelated edit", cur.fetchone()["org_id"] == orgs[1])
                        cur.execute("UPDATE organization_membership SET status='active' WHERE user_id=%s", (users[1],))
    finally:
        if users:
            with db.get_cursor(commit=True) as cur:
                cur.execute("DELETE FROM audit_log WHERE actor_user_id = ANY(%s)", (users,))
                for table in ("demand", "achievement"):
                    cur.execute(f"DELETE FROM {table} WHERE owner_user_id = ANY(%s)", (users,))
                cur.execute("DELETE FROM organization_membership WHERE user_id = ANY(%s)", (users,))
                cur.execute("DELETE FROM user_profile WHERE user_id = ANY(%s)", (users,))
                cur.execute("DELETE FROM app_user WHERE id = ANY(%s)", (users,))
                cur.execute("DELETE FROM organization WHERE id = ANY(%s) OR org_name = ANY(%s)", (orgs, [display_name, display_name + "-edit"]))


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
    check_profile_and_content_associations()
    check_http_flows()

    print(f"RESULT: {PASS} passed, {FAIL} failed")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
