"""User content can bind only to a selected active organization membership."""

import modules.membership.service as membership_service


def main():
    calls = []
    original = membership_service.assert_active_membership
    membership_service.assert_active_membership = lambda cur, user_id, org_id: calls.append((user_id, org_id))
    try:
        assert membership_service.resolve_content_organization(object(), 7, None) is None
        assert membership_service.resolve_content_organization(object(), 7, 19) == 19
    finally:
        membership_service.assert_active_membership = original
    assert calls == [(7, 19)]
    print("PASS: publication organization is selected from an active membership")


if __name__ == "__main__":
    main()
