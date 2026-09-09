import sys
from contextlib import contextmanager

import modules.membership.service as membership_service


class QueueCursor:
    def __init__(self):
        self.calls = 0

    def execute(self, sql, params):
        self.calls += 1
        normalized = " ".join(sql.split())
        assert "organization_membership_application" in normalized
        assert "a.org_id" in normalized

    def fetchone(self):
        return {"total": 1}

    def fetchall(self):
        return [{
            "id": 88, "user_id": 9, "org_id": 7, "status": "pending", "version": 1,
            "user_no": "U9", "org_name": "南山实验室", "real_name": "李四",
        }]


def main():
    original_get_cursor = membership_service.get_cursor
    original_assert = membership_service._assert_system_admin

    @contextmanager
    def fake_get_cursor():
        yield QueueCursor()

    try:
        membership_service.get_cursor = fake_get_cursor
        membership_service._assert_system_admin = lambda cur, admin: None
        result = membership_service.list_organization_membership_applications({"userId": 99}, "pending", 1, 10)
    finally:
        membership_service.get_cursor = original_get_cursor
        membership_service._assert_system_admin = original_assert

    assert result["total"] == 1
    assert result["list"][0]["orgName"] == "南山实验室"
    assert result["list"][0]["userNo"] == "U9"
    print("PASS: system admin can load pending member certification applications")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
