"""Regression: admin notification badges stay platform-wide for admins and org-scoped for org admins."""

import sys
from contextlib import contextmanager

import modules.admin.service as admin_service


class SummaryCursor:
    def __init__(self):
        self.sqls = []

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(sql.split()))
        self.params = params

    def fetchone(self):
        return {
            "users": 1, "achievements": 2, "demands": 3, "cooperations": 4,
            "pending_achievements": 2, "pending_demands": 3,
            "pending_organization_applications": 1,
            "pending_organization_admin_applications": 4,
            "pending_membership_applications": 5,
            "pending_cooperations": 6,
            "institutions": 7,
        }

    def fetchall(self):
        return []


class OrgCursor:
    def __init__(self):
        self.sqls = []
        self.params = None

    def execute(self, sql, params=None):
        self.sqls.append(" ".join(sql.split()))
        self.params = list(params or [])

    def fetchone(self):
        return {
            "pending_achievements": 1,
            "pending_demands": 2,
            "pending_cooperations": 3,
            "pending_membership_applications": 4,
        }


def main():
    original_get_cursor = admin_service.get_cursor
    platform_cursor = SummaryCursor()
    org_cursor = OrgCursor()

    @contextmanager
    def fake_get_cursor(**_kwargs):
        current = fake_get_cursor.current
        yield current

    try:
        fake_get_cursor.current = platform_cursor
        admin_service.get_cursor = fake_get_cursor
        platform = admin_service.notification_summary({"isPlatformAdmin": True})
        fake_get_cursor.current = org_cursor
        org = admin_service.notification_summary(
            {"isPlatformAdmin": False, "orgId": 17, "orgIds": [17], "userId": 8}
        )
        empty = admin_service.notification_summary(
            {"isPlatformAdmin": False, "orgId": None, "orgIds": [], "userId": 8}
        )
    finally:
        admin_service.get_cursor = original_get_cursor

    assert platform["categories"]["review"] == 5
    assert platform["categories"]["cooperation"] == 6
    assert platform["categories"]["organization"] == 1
    assert platform["categories"]["membership"] == 9
    assert platform["total"] == 21

    sql = org_cursor.sqls[0]
    assert "achievement a" in sql
    assert "demand d" in sql
    assert "cooperation_intent ci" in sql
    assert "organization_membership_application" in sql
    assert "organization_application" not in sql
    assert "organization_admin_application" not in sql
    assert org_cursor.params[:2] == [17, 17]
    assert org["categories"] == {
        "review": 3,
        "cooperation": 3,
        "organization": 0,
        "membership": 4,
    }
    assert org["total"] == 10
    assert empty == {
        "total": 0,
        "categories": {
            "review": 0,
            "cooperation": 0,
            "organization": 0,
            "membership": 0,
        },
    }
    print("PASS: notification summary is platform-wide for admins and org-scoped for org admins")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
