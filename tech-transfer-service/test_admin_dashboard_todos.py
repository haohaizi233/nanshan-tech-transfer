import sys
from contextlib import contextmanager

import modules.admin.service as admin_service


class TodoCursor:
    def execute(self, sql, params=None):
        normalized = " ".join(sql.split())
        assert "organization_application" in normalized
        assert "organization_membership_application" in normalized
        assert "organization_admin_application" in normalized
        assert "cooperation_intent" in normalized
        assert "submitted_at" not in normalized

    def fetchall(self):
        return [
            {"kind": "achievement", "id": 1, "title": "成果 A", "created_at": "2026-09-09T09:00:00"},
            {"kind": "organization_application", "id": 2, "title": "机构 B", "created_at": "2026-09-09T08:00:00"},
            {"kind": "membership_application", "id": 3, "title": "用户 U 申请加入机构 C", "created_at": "2026-09-09T07:00:00"},
            {"kind": "cooperation", "id": 4, "title": "对接 D", "created_at": "2026-09-09T06:00:00"},
        ]


def main():
    original_get_cursor = admin_service.get_cursor

    @contextmanager
    def fake_get_cursor():
        yield TodoCursor()

    try:
        admin_service.get_cursor = fake_get_cursor
        result = admin_service.dashboard_todos(5)
    finally:
        admin_service.get_cursor = original_get_cursor

    assert result["total"] == 4
    assert [item["kind"] for item in result["list"]] == [
        "achievement", "organization_application", "membership_application", "cooperation"
    ]
    assert result["list"][1]["route"] == "/admin/membership-review?tab=organization"
    assert result["list"][2]["route"] == "/admin/membership-review?tab=member"
    assert result["list"][3]["route"] == "/admin/cooperation"
    print("PASS: dashboard todo list includes each review source once")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
