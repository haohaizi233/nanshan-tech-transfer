"""Confirmed/offline targets leave public lists; docking parties must still favorite them."""

from modules.cooperation.service import can_access_target, is_accepted_dock_party


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.params = None

    def execute(self, _sql, params):
        self.params = params

    def fetchone(self):
        return self.row


def main():
    assert can_access_target(9, owner_user_id=1, status="published")
    assert can_access_target(1, owner_user_id=1, status="matched")
    assert can_access_target(
        9, owner_user_id=1, status="matched", is_dock_party=True
    )
    assert can_access_target(
        9, owner_user_id=1, status="offline", is_dock_party=True
    )
    assert not can_access_target(9, owner_user_id=1, status="matched")
    assert not can_access_target(9, owner_user_id=1, status="offline")
    assert not can_access_target(9, owner_user_id=1, status="draft")
    assert can_access_target(1, owner_user_id=1, status="draft")
    assert not can_access_target(None, owner_user_id=1, status="matched", is_dock_party=True)

    hit = FakeCursor({"ok": 1})
    assert is_accepted_dock_party(hit, "demand", 12, 9)
    assert hit.params == ("demand", 12, 9, 9)

    miss = FakeCursor(None)
    assert not is_accepted_dock_party(miss, "achievement", 4, 8)
    assert not is_accepted_dock_party(FakeCursor({"ok": 1}), "demand", 12, None)

    print("PASS: docking parties can still access matched/offline targets for favorite")


if __name__ == "__main__":
    main()
