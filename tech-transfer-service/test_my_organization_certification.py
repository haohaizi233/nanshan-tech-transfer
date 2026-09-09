import sys
from contextlib import contextmanager

import modules.membership.service as membership_service


class CertificationCursor:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params):
        normalized = " ".join(sql.split())
        assert params == (71,)
        if "FROM organization_membership m" in normalized:
            self.rows = [{
                "id": 101,
                "org_id": 7,
                "org_name": "南山产业集团",
                "role": "admin",
                "status": "active",
                "version": 3,
            }]
        elif "FROM organization_membership_application a" in normalized:
            self.rows = []
        elif "FROM organization_application a" in normalized:
            self.rows = []
        else:
            raise AssertionError(f"unexpected query: {normalized}")

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


def main():
    original_get_cursor = membership_service.get_cursor
    cursor = CertificationCursor()

    @contextmanager
    def fake_get_cursor():
        yield cursor

    try:
        membership_service.get_cursor = fake_get_cursor
        result = membership_service.get_my_organization_certification({"userId": 71})
    finally:
        membership_service.get_cursor = original_get_cursor

    assert result["status"] == "certified_admin"
    assert result["memberships"] == [{
        "id": 101,
        "orgId": 7,
        "orgName": "南山产业集团",
        "role": "admin",
        "status": "active",
        "version": 3,
    }]
    assert result["membershipApplication"] is None
    assert result["organizationApplication"] is None
    print("PASS: organization administrator certification state is returned")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"FAIL: {exc}")
        sys.exit(1)
