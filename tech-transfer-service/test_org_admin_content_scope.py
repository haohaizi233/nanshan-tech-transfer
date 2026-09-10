"""Regression checks for organization-admin access to legacy personal content."""

from contextlib import contextmanager

import modules.admin.service as admin_service
from modules.admin.service import can_claim_unassigned_content, organization_content_scope


def main():
    single, single_params = organization_content_scope(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8}, "a"
    )
    assert "a.org_id IN (%s)" in single
    assert "organization_membership" in single
    assert single_params == [17, 17]

    predicate, params = organization_content_scope(
        {"isPlatformAdmin": False, "orgIds": [17, 19], "userId": 8}, "a"
    )
    assert "a.org_id IN (%s,%s)" in predicate
    assert params == [17, 19, 17, 19]

    assert can_claim_unassigned_content(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8},
        {"org_id": None, "owner_user_id": 8},
    )
    assert can_claim_unassigned_content(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8},
        {"org_id": None, "owner_user_id": 9, "owner_in_org": True},
    )
    assert not can_claim_unassigned_content(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8},
        {"org_id": None, "owner_user_id": 9},
    )
    assert not can_claim_unassigned_content(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8},
        {"org_id": 21, "owner_user_id": 8, "owner_in_org": True},
    )

    class ClaimCursor:
        def __init__(self):
            self.row = None
            self.sqls = []

        def execute(self, sql, params):
            self.sqls.append(sql)
            text = sql.strip()
            if "FROM organization_membership" in text:
                self.row = {"ok": 1}
            elif "FROM institution" in text:
                self.row = {"name": "恒程创新"}
            elif text.startswith("SELECT"):
                self.row = {"id": 41, "org_id": None, "owner_user_id": 8, "version": 3}
            elif text.startswith("UPDATE"):
                assert params == (17, "恒程创新", 41, 3)
                self.row = {"id": 41, "org_id": 17, "version": 4}
            else:
                raise AssertionError(sql)

        def fetchone(self):
            return self.row

    cursor = ClaimCursor()

    @contextmanager
    def fake_cursor(**_kwargs):
        yield cursor

    original_cursor = admin_service.get_cursor
    original_audit = admin_service.audit_record
    admin_service.get_cursor = fake_cursor
    admin_service.audit_record = lambda *_args, **_kwargs: None
    try:
        claimed = admin_service.claim_unassigned_content(
            {"isPlatformAdmin": False, "orgId": 17, "userId": 8, "userNo": "U8"},
            "achievement", 41, 3,
        )
    finally:
        admin_service.get_cursor = original_cursor
        admin_service.audit_record = original_audit
    assert claimed == {"id": 41, "orgId": 17, "version": 4}
    print("PASS: organization admin can see and claim member unassigned legacy content")


if __name__ == "__main__":
    main()
