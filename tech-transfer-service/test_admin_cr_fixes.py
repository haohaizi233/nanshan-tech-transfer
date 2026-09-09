"""Unit checks for CR fixes: org forge, self-accept, membership owner, offline submit."""

from modules.admin.service import (
    _can_review_cooperation,
    _restrict_org_admin_fields,
    organization_content_scope,
    scope_org_ids,
)
from modules.achievement.service import EDITABLE_STATUSES, TRANSITIONS
from modules.demand.service import _resolve_name_refs


def main():
    assert scope_org_ids({"isPlatformAdmin": True, "orgId": 1}) == []
    assert scope_org_ids({"orgIds": [4, 9], "orgId": 4}) == [4, 9]
    assert scope_org_ids({"orgId": 4}) == [4]

    predicate, params = organization_content_scope(
        {"isPlatformAdmin": False, "orgId": 17, "userId": 8}, "a"
    )
    assert "a.org_id IN (%s)" in predicate or "a.org_id = %s" in predicate
    assert 17 in params and 8 in params

    row = {"status": "pending", "initiator_user_id": 8, "target_org_id": 17}
    assert not _can_review_cooperation({"userId": 8, "orgIds": [17]}, row)
    assert _can_review_cooperation({"userId": 9, "orgIds": [17]}, row)
    assert _can_review_cooperation(
        {"userId": 1, "isPlatformAdmin": True},
        {"status": "pending", "initiator_user_id": 2, "target_org_id": 99},
    )
    assert not _can_review_cooperation(
        {"userId": 1, "isPlatformAdmin": True},
        {"status": "pending", "initiator_user_id": 1, "target_org_id": 99},
    )

    fields = {"org_id": 17, "org_name_snapshot": "伪造机构", "org_intro": "x"}
    _restrict_org_admin_fields(
        {"isPlatformAdmin": False, "orgIds": [17]}, fields, is_create=True, kind="demand"
    )
    assert fields["org_id"] == 17
    assert "org_name_snapshot" not in fields

    fields = {"org_id": 99, "org_name_snapshot": "伪造机构"}
    _restrict_org_admin_fields(
        {"isPlatformAdmin": False, "orgIds": [17]}, fields, is_create=True, kind="demand"
    )
    assert "org_id" not in fields

    class Cur:
        def execute(self, *_args, **_kwargs):
            return None

        def fetchone(self):
            return {"id": 88}

    kept = {"org_id": 17, "org_name_snapshot": "伪造机构"}
    _resolve_name_refs(Cur(), kept, allow_org_mutate=False)
    assert kept["org_id"] == 17
    assert "org_name_snapshot" not in kept

    overwritten = {"org_id": 17, "org_name_snapshot": "伪造机构"}
    _resolve_name_refs(Cur(), overwritten, allow_org_mutate=True)
    assert overwritten["org_id"] == 88

    assert "offline" in EDITABLE_STATUSES
    assert "offline" in TRANSITIONS["submit"]["from"]
    print("PASS: admin CR fixes for org scope, self-accept, and demand name forge")


if __name__ == "__main__":
    main()
