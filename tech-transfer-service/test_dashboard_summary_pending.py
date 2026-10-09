import sys
from contextlib import contextmanager

import modules.admin.service as admin_service


class SummaryCursor:
    def __init__(self):
        self.call = 0

    def execute(self, sql, params=None):
        self.call += 1

    def fetchone(self):
        return {
            "users": 1, "achievements": 2, "demands": 3, "cooperations": 4,
            "pending_achievements": 1, "pending_demands": 1,
            "pending_organization_applications": 1,
            "pending_organization_admin_applications": 1,
            "pending_membership_applications": 1,
            "pending_cooperations": 1,
            "institutions": 5,
        }

    def fetchall(self):
        return []


def main():
    original_get_cursor = admin_service.get_cursor

    @contextmanager
    def fake_get_cursor():
        yield SummaryCursor()

    try:
        admin_service.get_cursor = fake_get_cursor
        result = admin_service.dashboard_summary()
    finally:
        admin_service.get_cursor = original_get_cursor

    assert result["pendingTotal"] == 6
    assert result["pendingMembershipApplications"] == 1
    assert result["pendingOrganizationApplications"] == 1
    print("PASS: dashboard summary counts every pending review source")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
