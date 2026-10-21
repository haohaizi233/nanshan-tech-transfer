"""Massive unit tests for low-coverage service modules.
Uses mocked DB cursors to test service functions without real database.
"""
import json
import time
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Helper to create a mock cursor with configurable return values ──

def _mock_cursor(fetchone_val=None, fetchall_val=None, rowcount_val=0):
    """Create a MagicMock cursor with configurable query results."""
    cur = MagicMock()
    cur.fetchone.return_value = fetchone_val
    cur.fetchall.return_value = fetchall_val if fetchall_val is not None else []
    cur.rowcount = rowcount_val
    return cur


def _mock_get_cursor(mock_cursor):
    """Patch db.get_cursor to return mock cursor context manager."""
    mock_gc = MagicMock()
    mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)
    return mock_gc


# ══════════════════════════════════════════════════════════════
# modules/admin/service.py
# ══════════════════════════════════════════════════════════════

class TestAdminServicePageArgs:
    def test_page_args_defaults(self):
        from modules.admin.service import _page_args
        page, page_size = _page_args({})
        assert page == 1
        assert page_size == 10

    def test_page_args_custom(self):
        from modules.admin.service import _page_args
        page, page_size = _page_args({"page": "3", "pageSize": "25"})
        assert page == 3
        assert page_size == 25

    def test_page_args_invalid(self):
        from modules.admin.service import _page_args
        page, page_size = _page_args({"page": "abc", "pageSize": "xyz"})
        assert page == 1
        assert page_size == 10

    def test_page_args_clamp(self):
        from modules.admin.service import _page_args
        _, page_size = _page_args({"pageSize": "999"})
        assert page_size == 50


class TestAdminServiceScope:
    def test_scope_org_ids_platform_admin(self):
        from modules.admin.service import scope_org_ids
        assert scope_org_ids({"isPlatformAdmin": True}) == []

    def test_scope_org_ids_with_org_ids(self):
        from modules.admin.service import scope_org_ids
        assert scope_org_ids({"orgIds": [1, 2, 3]}) == [1, 2, 3]

    def test_scope_org_ids_with_single_org_id(self):
        from modules.admin.service import scope_org_ids
        assert scope_org_ids({"orgId": 5}) == [5]

    def test_scope_org_ids_empty(self):
        from modules.admin.service import scope_org_ids
        assert scope_org_ids({}) == []


class TestAdminServiceHelpers:
    def test_sql_in(self):
        from modules.admin.service import _sql_in
        clause, params = _sql_in("id", [1, 2, 3])
        assert "IN" in clause
        assert params == [1, 2, 3]

    def test_restrict_org_admin_fields_platform_admin(self):
        from modules.admin.service import _restrict_org_admin_fields
        fields = {"org_name": "test", "source_org_name": "src", "org_id": 1}
        _restrict_org_admin_fields({"isPlatformAdmin": True}, fields, is_create=True, kind="achievement")
        assert fields["org_name"] == "test"

    def test_restrict_org_admin_fields_org_admin(self):
        from modules.admin.service import _restrict_org_admin_fields
        fields = {"org_name": "test", "source_org_name": "src", "org_id": 1}
        _restrict_org_admin_fields({"orgIds": [1]}, fields, is_create=True, kind="achievement")
        assert "org_name" not in fields
        assert "source_org_name" not in fields

    def test_restrict_org_admin_fields_not_create(self):
        from modules.admin.service import _restrict_org_admin_fields
        fields = {"org_id": 1, "title": "test"}
        _restrict_org_admin_fields({"orgIds": [1]}, fields, is_create=False, kind="achievement")
        assert "org_id" not in fields


class TestAdminServiceListFunctions:
    @patch("modules.admin.service.get_cursor")
    def test_list_demand_categories_admin(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[
            {"id": 1, "code": "tech", "name": "技术"},
            {"id": 2, "code": "product", "name": "产品"},
        ])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_demand_categories_admin
        result = list_demand_categories_admin()
        assert isinstance(result, list)

    @patch("modules.admin.service.get_cursor")
    def test_list_content_organizations_admin_platform(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[
            {"id": 1, "name": "Test Org", "kind": "university"},
        ])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_content_organizations_admin
        result = list_content_organizations_admin({"isPlatformAdmin": True})
        assert isinstance(result, list)

    @patch("modules.admin.service.get_cursor")
    def test_list_content_organizations_admin_org(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[
            {"id": 1, "name": "My Org", "kind": "enterprise"},
        ])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_content_organizations_admin
        result = list_content_organizations_admin({"orgId": 1})
        assert isinstance(result, list)


class TestAdminServiceReviewQueues:
    @patch("modules.admin.service.get_cursor")
    def test_achievements_review_queue(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import achievements_review_queue
        result = achievements_review_queue({})
        assert ("list" in result or "items" in result)
        assert "total" in result

    @patch("modules.admin.service.get_cursor")
    def test_demands_review_queue(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import demands_review_queue
        result = demands_review_queue({})
        assert ("list" in result or "items" in result)
        assert "total" in result

    @patch("modules.admin.service.get_cursor")
    def test_achievements_review_queue_with_category(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import achievements_review_queue
        result = achievements_review_queue({"categoryCode": "tech"})
        assert ("list" in result or "items" in result)


class TestAdminServiceReview:
    @patch("modules.admin.service.get_cursor")
    def test_review_achievement_approve(self, mock_gc):
        cur = _mock_cursor(
            fetchone_val={"status": "pending_review", "version": 1, "owner_user_id": 1},
        )
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_achievement
        result = review_achievement(
            {"userId": 99, "userNo": "U099"}, 1,
            {"_action": "approve", "version": 1},
        )
        assert result["status"] == "published"

    @patch("modules.admin.service.get_cursor")
    def test_review_achievement_reject(self, mock_gc):
        cur = _mock_cursor(
            fetchone_val={"status": "pending_review", "version": 1, "owner_user_id": 1},
        )
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_achievement
        result = review_achievement(
            {"userId": 99, "userNo": "U099"}, 1,
            {"_action": "reject", "version": 1, "reason": "不合规"},
        )
        assert result["status"] == "rejected"

    def test_review_achievement_no_version(self):
        from modules.admin.service import review_achievement
        from core.errors import BizError
        with pytest.raises(BizError):
            review_achievement({"userId": 99}, 1, {"_action": "approve"})

    def test_review_achievement_reject_no_reason(self):
        from modules.admin.service import review_achievement
        from core.errors import BizError
        with pytest.raises(BizError):
            review_achievement({"userId": 99}, 1, {"_action": "reject", "version": 1})

    @patch("modules.admin.service.get_cursor")
    def test_review_achievement_not_found(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_achievement
        from core.errors import BizError
        with pytest.raises(BizError):
            review_achievement({"userId": 99}, 999, {"_action": "approve", "version": 1})

    @patch("modules.admin.service.get_cursor")
    def test_review_achievement_wrong_status(self, mock_gc):
        cur = _mock_cursor(
            fetchone_val={"status": "draft", "version": 1, "owner_user_id": 1},
        )
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_achievement
        from core.errors import BizError
        with pytest.raises(BizError):
            review_achievement({"userId": 99}, 1, {"_action": "approve", "version": 1})

    @patch("modules.admin.service.get_cursor")
    def test_review_demand_approve(self, mock_gc):
        cur = _mock_cursor(
            fetchone_val={"status": "pending_review", "version": 1, "owner_user_id": 1},
        )
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_demand
        result = review_demand(
            {"userId": 99, "userNo": "U099"}, 1,
            {"_action": "approve", "version": 1},
        )
        assert result["status"] == "published"

    @patch("modules.admin.service.get_cursor")
    def test_review_demand_reject(self, mock_gc):
        cur = _mock_cursor(
            fetchone_val={"status": "pending_review", "version": 1, "owner_user_id": 1},
        )
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_demand
        result = review_demand(
            {"userId": 99, "userNo": "U099"}, 1,
            {"_action": "reject", "version": 1, "reason": "内容不完整"},
        )
        assert result["status"] == "rejected"


class TestAdminServiceListAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_list_achievements_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_achievements_admin
        result = list_achievements_admin({}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_list_demands_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_demands_admin
        result = list_demands_admin({}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)


class TestAdminServiceDashboard:
    @patch("modules.admin.service.get_cursor")
    def test_dashboard_summary(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "users": 10, "achievements": 5, "demands": 3, "cooperations": 0,
            "pending_achievements": 0, "pending_demands": 0,
            "pending_organization_applications": 0, "pending_organization_admin_applications": 0,
            "pending_membership_applications": 0, "pending_cooperations": 0, "institutions": 2,
        }
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_summary
        result = dashboard_summary()
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_todos(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_todos
        result = dashboard_todos(10)
        assert isinstance(result, dict)
        assert "list" in result

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_trend(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[
            {"dt": "2026-01-01", "count": 5},
        ])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_trend
        result = dashboard_trend(7)
        assert isinstance(result, dict)
        assert "list" in result

    @patch("modules.admin.service.dashboard_summary")
    def test_notification_summary(self, mock_ds):
        mock_ds.return_value = {
            "pendingAchievements": 0, "pendingDemands": 0,
            "pendingCooperations": 0, "pendingOrganizationApplications": 0,
            "pendingOrganizationAdminApplications": 0, "pendingMembershipApplications": 0,
        }
        from modules.admin.service import notification_summary
        result = notification_summary({"isPlatformAdmin": True})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_list_audit_logs(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_audit_logs
        result = list_audit_logs({"page": "1", "pageSize": "10"})
        assert isinstance(result, dict)


class TestAdminServiceInstitutions:
    @patch("modules.admin.service.get_cursor")
    def test_list_institutions_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_institutions_admin
        result = list_institutions_admin({"page": "1", "pageSize": "10"})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_get_institution_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_institution_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_institution_admin(1)


class TestAdminServiceUsers:
    @patch("modules.admin.service.get_cursor")
    def test_list_users_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_users_admin
        result = list_users_admin({}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_get_user_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_user_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_user_admin(1, {"isPlatformAdmin": True})


class TestAdminServiceCooperations:
    @patch("modules.admin.service.get_cursor")
    def test_list_cooperations_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"c": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_cooperations_admin
        result = list_cooperations_admin({}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_get_cooperation_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_cooperation_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_cooperation_admin(1, {"isPlatformAdmin": True})


class TestAdminServiceCrudAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_get_achievement_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_achievement_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_achievement_admin(1, {"isPlatformAdmin": True})

    @patch("modules.admin.service.get_cursor")
    def test_get_demand_admin(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_demand_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_demand_admin(1, {"isPlatformAdmin": True})

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_achievement_admin(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.side_effect = [{"id": 1}, {"id": 1}]
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_achievement_admin
        result = soft_delete_achievement_admin({"isPlatformAdmin": True}, 1)
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_achievement_admin_not_found(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_achievement_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            soft_delete_achievement_admin({"isPlatformAdmin": True}, 999)

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_demand_admin(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.side_effect = [{"id": 1}, {"id": 1}]
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_demand_admin
        result = soft_delete_demand_admin({"isPlatformAdmin": True}, 1)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/identity/service.py
# ══════════════════════════════════════════════════════════════

class TestIdentityServiceHelpers:
    def test_parse_capabilities_none(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities(None) == []

    def test_parse_capabilities_string(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities('["a", "b"]') == ["a", "b"]

    def test_parse_capabilities_invalid_json(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities("not json") == []

    def test_parse_capabilities_list(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities(["a", 1]) == ["a", "1"]

    def test_parse_capabilities_dict(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities({"key": "val"}) == []


class TestIdentityServiceBuildUser:
    @patch("modules.identity.service.get_cursor")
    def test_build_user_response_found(self, mock_gc):
        cur = MagicMock()
        # First fetchone: profile
        profile = {
            "user_id": 1, "display_name": "Test", "user_type": "person",
            "phone": "138", "email": "test@test.com", "org_id": None,
            "org_title": None, "company_text": None, "version": 1,
            "subject_type": None, "business_capabilities": None, "wechat": None,
        }
        # Second fetchone: user row
        user_row = {"user_no": "U001", "status": "active"}
        # Third fetchall: memberships
        # Fourth fetchone: org admin check
        cur.fetchone.side_effect = [profile, None, user_row]
        cur.fetchall.side_effect = [
            [{"role_code": "user"}],  # roles
            [],  # memberships
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.service import build_user_response
        result = build_user_response(cur, 1)
        assert result is not None
        assert result["userId"] == 1
        assert result["userNo"] == "U001"

    def test_build_user_response_not_found(self):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"user_id": 1, "display_name": "Test", "user_type": "person",
             "phone": "138", "email": "e", "org_id": None, "org_title": None,
             "company_text": None, "version": 1, "subject_type": None,
             "business_capabilities": None, "wechat": None},
            None,  # org_admin check
            None,  # user row
        ]
        cur.fetchall.return_value = [{"role_code": "user"}]
        from modules.identity.service import build_user_response
        result = build_user_response(cur, 1)
        assert result is None


class TestIdentityServiceRegister:
    @patch("modules.identity.service.validate_phone", return_value="13800138000")
    @patch("modules.identity.service.hash_password", return_value="hashed")
    @patch("modules.identity.service.get_cursor")
    def test_register_user_success(self, mock_gc, mock_hash, mock_phone):
        cur = MagicMock()
        # _generate_user_no: fetchone → {"m": 0}
        # check phone exists → None
        # INSERT app_user RETURNING id → {"id": 1}
        # INSERT user_profile
        # INSERT user_role
        # INSERT user_credential
        # _get_roles: fetchall → [{"role_code": "user"}], fetchone → None
        # _get_profile: fetchone → profile
        # _get_org_name: fetchone → None
        # build_user_response internals
        cur.fetchone.side_effect = [
            {"m": 0},  # _generate_user_no
            None,  # phone check
            {"id": 1},  # INSERT app_user
            # build_user_response → _get_profile
            {"user_id": 1, "display_name": "13800138000", "user_type": None,
             "phone": "13800138000", "email": None, "org_id": None,
             "org_title": None, "company_text": None, "version": 1,
             "subject_type": None, "business_capabilities": None, "wechat": None},
            # _get_roles → org_admin check
            None,
            # app_user row
            {"user_no": "U001", "status": "active"},
            # _get_org_name
            None,
            # sign_access_token / sign_refresh_token: _issue_session
            {"user_no": "U001", "status": "active"},
            # auth_session insert
        ]
        cur.fetchall.side_effect = [
            [{"role_code": "user"}],  # _get_roles
            [],  # memberships in build_user_response
            [],  # _get_roles for _issue_session
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.service import register_user
        with patch("modules.identity.service.sign_access_token", return_value="tok"), \
             patch("modules.identity.service.sign_refresh_token", return_value=("ref", "jti")):
            result = register_user("13800138000", "password123")
        assert "user" in result

    def test_register_user_invalid_phone(self):
        from modules.identity.service import register_user
        from core.errors import BizError
        with patch("modules.identity.service.validate_phone", side_effect=BizError("X", "bad", 400)):
            with pytest.raises(BizError):
                register_user("bad", "password123")

    def test_register_user_short_password(self):
        from modules.identity.service import register_user
        from core.errors import BizError
        with patch("modules.identity.service.validate_phone", return_value="13800138000"):
            with pytest.raises(BizError):
                register_user("13800138000", "short")


class TestIdentityServiceLogin:
    @patch("modules.identity.service.get_cursor")
    def test_password_login_session_no_username(self, mock_gc):
        from modules.identity.service import password_login_session
        from core.errors import BizError
        with pytest.raises(BizError):
            password_login_session("", "password")

    @patch("modules.identity.service.get_cursor")
    def test_password_login_session_no_password(self, mock_gc):
        from modules.identity.service import password_login_session
        from core.errors import BizError
        with pytest.raises(BizError):
            password_login_session("admin", "")

    @patch("modules.identity.service.get_cursor")
    def test_login_phone_session_no_phone(self, mock_gc):
        from modules.identity.service import login_phone_session
        from core.errors import BizError
        with pytest.raises(BizError):
            login_phone_session("", "password")


class TestIdentityServiceRegisterPassword:
    def test_register_password_user_bad_username(self):
        from modules.identity.service import register_password_user
        from core.errors import BizError
        with pytest.raises(BizError):
            register_password_user({"username": "a", "password": "password123"})

    def test_register_password_user_short_password(self):
        from modules.identity.service import register_password_user
        from core.errors import BizError
        with pytest.raises(BizError):
            register_password_user({"username": "testuser", "password": "short"})


class TestIdentityServiceRefresh:
    @patch("core.jwt_utils.decode_no_verify_exp")
    def test_refresh_session_invalid_token(self, mock_decode):
        import jwt as _jwt
        mock_decode.side_effect = _jwt.InvalidTokenError("bad")
        from modules.identity.service import refresh_session
        from core.errors import BizError
        with pytest.raises(BizError):
            refresh_session("bad_token")

    @patch("core.jwt_utils.decode_no_verify_exp")
    def test_refresh_session_wrong_type(self, mock_decode):
        mock_decode.return_value = {"sub": "1", "type": "access", "jti": "x"}
        from modules.identity.service import refresh_session
        from core.errors import BizError
        with pytest.raises(BizError):
            refresh_session("token")


# ══════════════════════════════════════════════════════════════
# modules/membership/service.py
# ══════════════════════════════════════════════════════════════

class TestMembershipServiceHelpers:
    def test_map_read_row(self):
        from modules.membership.service import _map_read_row
        row = {"user_id": 1, "org_name": "Test", "created_at": "2026-01-01"}
        result = _map_read_row(row)
        assert "userId" in result
        assert "orgName" in result

    @patch("modules.admin.service.get_cursor")
    def test_resolve_content_organization_none(self, mock_gc):
        from modules.membership.service import resolve_content_organization
        cur = MagicMock()
        result = resolve_content_organization(cur, 1, None)
        assert result is None

    @patch("modules.membership.service.get_cursor")
    def test_list_my_memberships(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"total": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import list_my_memberships
        result = list_my_memberships({"userId": 1}, 1, 10)
        assert "list" in result
        assert "total" in result

    @patch("modules.membership.service.get_cursor")
    def test_list_my_membership_applications(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"total": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import list_my_membership_applications
        result = list_my_membership_applications({"userId": 1}, None, 1, 10)
        assert "list" in result

    @patch("modules.membership.service.get_cursor")
    def test_get_my_organization_certification(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        # First fetchall for memberships
        # Second fetchone for pending application
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import get_my_organization_certification
        result = get_my_organization_certification({"userId": 1})
        assert "memberships" in result


class TestMembershipServiceApply:
    @patch("modules.membership.service.transaction")
    def test_apply_membership_success(self, mock_trans):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1, "status": "active"},  # org check
            None,  # existing membership check
            None,  # existing application check
            {"id": 1, "status": "pending", "version": 1},  # INSERT RETURNING
        ]
        from modules.membership.service import apply_membership
        result = apply_membership({"userId": 1}, {"orgId": 1})
        assert isinstance(result, dict)

    @patch("modules.membership.service.transaction")
    def test_apply_membership_org_not_found(self, mock_trans):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.return_value = None
        from modules.membership.service import apply_membership
        from core.errors import BizError
        with pytest.raises(BizError):
            apply_membership({"userId": 1}, {"orgId": 999})


class TestMembershipServiceCancel:
    @patch("modules.membership.service.transaction")
    def test_cancel_membership_application_success(self, mock_trans):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1},  # check exists
            {"id": 1, "user_id": 1, "org_id": 1, "status": "cancelled", "version": 2},  # RETURNING
        ]
        from modules.membership.service import cancel_membership_application
        result = cancel_membership_application({"userId": 1}, 1, 1)
        assert isinstance(result, dict)

    @patch("modules.membership.service.transaction")
    def test_cancel_membership_not_found(self, mock_trans):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.return_value = None
        from modules.membership.service import cancel_membership_application
        from core.errors import BizError
        with pytest.raises(BizError):
            cancel_membership_application({"userId": 1}, 999, 1)


# ══════════════════════════════════════════════════════════════
# modules/institution_registration/service.py
# ══════════════════════════════════════════════════════════════

class TestInstitutionRegistrationService:
    def test_create_registration_not_dict(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration("not a dict")

    def test_create_registration_bad_kind(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "invalid", "name": "Test", "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "Test@12345"})

    def test_create_registration_no_name(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "", "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "Test@12345"})

    def test_create_registration_no_contact(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "Test", "contactName": "",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "Test@12345"})

    def test_create_registration_bad_username(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "Test", "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "ab", "password": "Test@12345"})

    def test_create_registration_short_password(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "Test", "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "short"})

    def test_create_registration_name_too_long(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "x" * 200, "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "Test@12345"})

    def test_create_registration_region_too_long(self):
        from modules.institution_registration.service import create_institution_registration
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution_registration({"kind": "enterprise", "name": "Test", "contactName": "张三",
                                              "contactPhone": "13800138000", "username": "testuser", "password": "Test@12345",
                                              "region": "x" * 100})


class TestInstitutionRegistrationList:
    @patch("modules.institution_registration.service.get_cursor")
    def test_list_institution_registrations(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"total": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution_registration.service import list_institution_registrations
        result = list_institution_registrations({})
        assert "list" in result
        assert "total" in result

    @patch("modules.institution_registration.service.get_cursor")
    def test_list_institution_registrations_with_status(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"total": 0}, fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution_registration.service import list_institution_registrations
        result = list_institution_registrations({"registrationStatus": "pending"})
        assert "list" in result

    def test_list_institution_registrations_bad_status(self):
        from modules.institution_registration.service import list_institution_registrations
        from core.errors import BizError
        with pytest.raises(BizError):
            list_institution_registrations({"registrationStatus": "invalid"})


class TestInstitutionRegistrationApproveReject:
    @patch("modules.institution_registration.service.approve_organization_application")
    @patch("modules.institution_registration.service.get_cursor")
    def test_approve_institution_registration(self, mock_gc, mock_approve):
        cur = _mock_cursor(fetchone_val={"version": 1, "proof_material": None})
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_approve.return_value = {"status": "approved", "orgId": 1}
        from modules.institution_registration.service import approve_institution_registration
        result = approve_institution_registration({"userId": 99}, 1)
        assert result["status"] == "approved"

    @patch("modules.institution_registration.service.reject_organization_application")
    @patch("modules.institution_registration.service.get_cursor")
    def test_reject_institution_registration(self, mock_gc, mock_reject):
        cur = _mock_cursor(fetchone_val={"version": 1})
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_reject.return_value = {"status": "rejected"}
        from modules.institution_registration.service import reject_institution_registration
        result = reject_institution_registration({"userId": 99}, 1, "不合规")
        assert result["status"] == "rejected"

    @patch("modules.institution_registration.service.get_cursor")
    def test_load_application_version_not_found(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution_registration.service import _load_application_version
        from core.errors import BizError
        with pytest.raises(BizError):
            _load_application_version(999)


# ══════════════════════════════════════════════════════════════
# modules/ai/provider.py
# ══════════════════════════════════════════════════════════════

class TestAiProviderConfig:
    def test_configured_true(self):
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            from modules.ai.provider import configured
            assert configured() is True

    def test_configured_false(self):
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = ""
            from modules.ai.provider import configured
            assert configured() is False


class TestAiProviderParseJson:
    def test_parse_json_content_valid(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_content_with_fence(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_content_empty(self):
        from modules.ai.provider import parse_json_content, AiProviderError
        with pytest.raises(AiProviderError):
            parse_json_content("")

    def test_parse_json_content_embedded_json(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('Here is the result: {"key": "value"} end')
        assert result == {"key": "value"}

    def test_parse_json_content_invalid(self):
        from modules.ai.provider import parse_json_content, AiProviderError
        with pytest.raises(AiProviderError):
            parse_json_content("not json at all")

    def test_parse_json_content_embedded_invalid(self):
        from modules.ai.provider import parse_json_content, AiProviderError
        with pytest.raises(AiProviderError):
            parse_json_content('result: {broken json} here')


class TestAiProviderChat:
    def test_chat_not_configured(self):
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = ""
            from modules.ai.provider import _chat, AiProviderError
            with pytest.raises(AiProviderError, match="not set"):
                _chat([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_chat_success(self, mock_opener):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({
            "choices": [{"message": {"content": "hello"}}]
        }).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener.open.return_value = mock_resp
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            mock_settings.AI_PROVIDER_MODEL = "test-model"
            mock_settings.AI_PROVIDER_KEY = ""
            mock_settings.AI_PROVIDER_TIMEOUT = 30
            from modules.ai.provider import _chat
            result = _chat([{"role": "user", "content": "hi"}])
            assert result == "hello"

    @patch("modules.ai.provider._OPENER")
    def test_chat_http_error(self, mock_opener):
        import urllib.error
        mock_opener.open.side_effect = urllib.error.HTTPError(
            "http://test", 500, "error", {}, None
        )
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            mock_settings.AI_PROVIDER_MODEL = "test"
            mock_settings.AI_PROVIDER_KEY = ""
            mock_settings.AI_PROVIDER_TIMEOUT = 30
            from modules.ai.provider import _chat, AiProviderError
            with pytest.raises(AiProviderError):
                _chat([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_chat_empty_choices(self, mock_opener):
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps({"choices": []}).encode()
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener.open.return_value = mock_resp
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            mock_settings.AI_PROVIDER_MODEL = "test"
            mock_settings.AI_PROVIDER_KEY = ""
            mock_settings.AI_PROVIDER_TIMEOUT = 30
            from modules.ai.provider import _chat, AiProviderError
            with pytest.raises(AiProviderError):
                _chat([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_chat_non_object(self, mock_opener):
        mock_resp = MagicMock()
        mock_resp.read.return_value = b'"just a string"'
        mock_resp.__enter__ = MagicMock(return_value=mock_resp)
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_opener.open.return_value = mock_resp
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            mock_settings.AI_PROVIDER_MODEL = "test"
            mock_settings.AI_PROVIDER_KEY = ""
            mock_settings.AI_PROVIDER_TIMEOUT = 30
            from modules.ai.provider import _chat, AiProviderError
            with pytest.raises(AiProviderError):
                _chat([{"role": "user", "content": "hi"}])


class TestAiProviderEvaluate:
    def test_evaluate_achievement_success(self):
        from modules.ai.provider import evaluate_achievement
        mock_result = {
            "dimensions": {
                "innovation": {"score": 80, "comment": "创新明确"},
                "techMaturity": {"score": 90, "comment": "成熟度高"},
                "marketProspect": {"score": 70, "comment": "市场可期"},
                "teamStrength": {"score": 65, "comment": "团队完整"},
                "cooperation": {"score": 75, "comment": "合作灵活"},
                "riskAssessment": {"score": 80, "comment": "风险可控"},
            },
            "conclusion": "Good",
            "highlights": ["Fast", "Reliable"],
            "report": [{"heading": "总体评价", "content": "详细分析"}],
        }
        with patch("modules.ai.provider.complete_json", return_value=mock_result):
            result = evaluate_achievement({"id": 1, "title": "Test"})
        assert len(result["dimensions"]) == 6
        assert result["legacyScores"]["techFeature"] == 80.0
        assert result["totalScore"] == pytest.approx(77.35, abs=0.2)
        assert result["conclusion"] == "Good"
        assert result["report"] == [{"heading": "总体评价", "content": "详细分析"}]

    def test_evaluate_achievement_missing_score(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        mock_result = {
            "dimensions": {"innovation": 80},  # 其余维度缺失
        }
        with patch("modules.ai.provider.complete_json", return_value=mock_result):
            with pytest.raises(AiProviderError):
                evaluate_achievement({"id": 1})

    def test_evaluate_achievement_not_dict(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        with patch("modules.ai.provider.complete_json", return_value="not a dict"):
            with pytest.raises(AiProviderError):
                evaluate_achievement({"id": 1})

    def test_evaluate_achievement_fallback_total(self):
        from modules.ai.provider import evaluate_achievement
        mock_result = {
            # LLM 不回 totalScore：由权重换算
            "dimensions": {
                "innovation": 80, "techMaturity": 90, "marketProspect": 70,
                "teamStrength": 65, "cooperation": 75, "riskAssessment": 80,
            },
            "conclusion": "ok",
        }
        with patch("modules.ai.provider.complete_json", return_value=mock_result):
            result = evaluate_achievement({"id": 1})
        assert result["totalScore"] == pytest.approx(77.35, abs=0.2)
        assert result["starScore"] == pytest.approx(3.9, abs=0.2)

    def test_evaluate_achievement_string_highlights(self):
        from modules.ai.provider import evaluate_achievement
        mock_result = {
            "dimensions": {
                "innovation": 80, "techMaturity": 90, "marketProspect": 70,
                "teamStrength": 65, "cooperation": 75, "riskAssessment": 80,
            },
            "conclusion": "ok",
            "highlights": "single highlight",
        }
        with patch("modules.ai.provider.complete_json", return_value=mock_result):
            result = evaluate_achievement({"id": 1})
        assert isinstance(result["highlights"], list)

    def test_evaluate_achievement_alt_score_keys(self):
        from modules.ai.provider import evaluate_achievement
        mock_result = {
            # 列表形态（与 dict 形态等价，normalize 两者都接受）
            "dimensions": [
                {"key": "innovation", "score": 80},
                {"key": "techMaturity", "score": 90},
                {"key": "marketProspect", "score": 70},
                {"key": "teamStrength", "score": 65},
                {"key": "cooperation", "score": 75},
                {"key": "riskAssessment", "score": 80},
            ],
            "summary": "ok",
        }
        with patch("modules.ai.provider.complete_json", return_value=mock_result):
            result = evaluate_achievement({"id": 1})
        assert len(result["dimensions"]) == 6
        assert result["conclusion"] == "ok"


# ══════════════════════════════════════════════════════════════
# modules/ai/worker.py
# ══════════════════════════════════════════════════════════════

class TestAiWorkerHelpers:
    def test_clip(self):
        from modules.ai.worker import _clip
        assert len(_clip("x" * 1000)) <= 500
        assert _clip("") != ""
        assert _clip(None) != ""

    def test_desensitize_reason_empty(self):
        from modules.ai.worker import _desensitize_reason
        result = _desensitize_reason("")
        assert result  # non-empty fallback

    def test_desensitize_reason_with_hint(self):
        from modules.ai.worker import _desensitize_reason
        result = _desensitize_reason("connection to openai failed")
        assert "openai" not in result.lower()

    def test_desensitize_reason_clean(self):
        from modules.ai.worker import _desensitize_reason
        result = _desensitize_reason("任务超时")
        assert "任务超时" in result

    def test_snapshot_dict(self):
        from modules.ai.worker import _snapshot
        assert _snapshot({"key": "val"}) == {"key": "val"}

    def test_snapshot_string(self):
        from modules.ai.worker import _snapshot
        assert _snapshot('{"key": "val"}') == {"key": "val"}

    def test_snapshot_invalid_string(self):
        from modules.ai.worker import _snapshot
        assert _snapshot("not json") == {}

    def test_snapshot_none(self):
        from modules.ai.worker import _snapshot
        assert _snapshot(None) == {}

    def test_snapshot_empty_string(self):
        from modules.ai.worker import _snapshot
        assert _snapshot("") == {}


class TestAiWorkerReapStuck:
    @patch("modules.ai.worker.get_cursor")
    def test_reap_stuck(self, mock_gc):
        cur = MagicMock()
        cur.rowcount = 2
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.worker import reap_stuck
        result = reap_stuck()
        assert result == 2


class TestAiWorkerClaimOne:
    @patch("modules.ai.worker.transaction")
    def test_claim_one_at_max(self, mock_trans):
        import modules.ai.worker as w
        old = w._running_count
        w._running_count = w.MAX_RUNNING + 1
        try:
            assert w.claim_one() is None
        finally:
            w._running_count = old


class TestAiWorkerProcessOne:
    @patch("modules.ai.worker.claim_one", return_value=None)
    @patch("modules.ai.worker.reap_stuck", return_value=0)
    @patch("modules.ai.provider.configured", return_value=True)
    def test_process_one_idle(self, mock_conf, mock_reap, mock_claim):
        from modules.ai.worker import process_one
        assert process_one() == "idle"

    @patch("modules.ai.provider.configured", return_value=False)
    def test_process_one_unconfigured(self, mock_conf):
        from modules.ai.worker import process_one
        assert process_one() == "unconfigured"


class TestAiWorkerFail:
    @patch("modules.ai.worker.get_cursor")
    def test_fail(self, mock_gc):
        cur = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.worker import _fail
        _fail(1, "test reason")


# ══════════════════════════════════════════════════════════════
# modules/ai/service.py
# ══════════════════════════════════════════════════════════════

class TestAiServiceHelpers:
    def test_parse_reasons_none(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons(None) == []

    def test_parse_reasons_list(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons(["a", "b"]) == ["a", "b"]

    def test_parse_reasons_json_string(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons('["a", "b"]') == ["a", "b"]

    def test_parse_reasons_invalid_json(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons("not json") == []

    def test_parse_reasons_non_list_json(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons('"just string"') == []

    def test_desensitize_fail_reason_none(self):
        from modules.ai.service import _desensitize_fail_reason
        assert _desensitize_fail_reason(None) is None

    def test_desensitize_fail_reason_clean(self):
        from modules.ai.service import _desensitize_fail_reason
        assert _desensitize_fail_reason("custom error") == "custom error"

    def test_desensitize_fail_reason_hint(self):
        from modules.ai.service import _desensitize_fail_reason
        result = _desensitize_fail_reason("openai timeout")
        assert "openai" not in result

    def test_iso_with_dt(self):
        from modules.ai.service import _iso
        dt = datetime(2026, 1, 1, 12, 0, 0)
        assert _iso(dt) == "2026-01-01T12:00:00"

    def test_iso_with_none(self):
        from modules.ai.service import _iso
        assert _iso(None) is None

    def test_check_user_rate(self):
        from modules.ai.service import _check_user_rate
        # Should not raise for first call
        _check_user_rate(99999)


class TestAiServiceGetTask:
    @patch("modules.ai.service.get_cursor")
    def test_get_evaluation_task_not_found(self, mock_gc):
        cur = _mock_cursor(fetchone_val=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.service import get_evaluation_task
        from core.errors import BizError
        with pytest.raises(BizError):
            get_evaluation_task(1, 999)

    @patch("modules.ai.service.get_cursor")
    def test_get_evaluation_task_wrong_user(self, mock_gc):
        cur = _mock_cursor(fetchone_val={
            "id": 1, "task_type": "evaluation", "status": "queued",
            "created_by_user_id": 2, "target_id": 1,
            "input_data_version": "abc", "model_version_id": None,
            "fail_reason": None, "created_at": None, "started_at": None,
            "finished_at": None,
        })
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.service import get_evaluation_task
        from core.errors import BizError
        with pytest.raises(BizError):
            get_evaluation_task(1, 1)  # user 1, but task belongs to user 2


# ══════════════════════════════════════════════════════════════
# modules/achievement/importer.py
# ══════════════════════════════════════════════════════════════

class TestImporterHelpers:
    def test_media_payload_from_uploads(self):
        from modules.achievement.importer import _media_payload_from_uploads
        result = _media_payload_from_uploads([
            {"id": 1, "name": "img1.jpg"},
            {"id": 2, "name": "img2.jpg"},
        ])
        assert len(result) == 2
        assert result[0]["role"] == "cover"
        assert result[1]["role"] == "gallery"

    def test_classify_page_empty(self):
        from modules.achievement.importer import _classify_page
        result = _classify_page({"text": "", "images": []})
        assert result == "empty"

    def test_classify_page_template(self):
        from modules.achievement.importer import _classify_page
        result = _classify_page({"text": "单击此处添加标题"})
        assert result == "template"

    def test_classify_page_project(self):
        from modules.achievement.importer import _classify_page
        result = _classify_page({"text": "新型材料技术\n这是一种新型的技术方案\n应用领域广泛"})
        assert result in ("project", "patent", "contributor")

    def test_classify_page_contributor(self):
        from modules.achievement.importer import _classify_page
        result = _classify_page({
            "text": "成果完成人\n张三\n联系电话：13800138000\n博士，高级工程师"
        })
        assert result in ("contributor", "project")

    def test_patents_from_text(self):
        from modules.achievement.importer import _patents_from_text
        result = _patents_from_text("专利号：CN12345678A 和 ZL202011223344.5")
        assert len(result) >= 1
        assert result[0]["patentNo"] is not None

    def test_patents_from_text_empty(self):
        from modules.achievement.importer import _patents_from_text
        result = _patents_from_text("")
        assert result == []

    def test_patents_from_text_no_patents(self):
        from modules.achievement.importer import _patents_from_text
        result = _patents_from_text("没有专利号的文字")
        assert result == []

    def test_clean_label(self):
        from modules.achievement.importer import _clean_label
        assert _clean_label("技术 （创新）点") == "技术创新点"

    def test_is_template_content_hint_true(self):
        from modules.achievement.importer import _is_template_content_hint
        assert _is_template_content_hint("成果简介（包括但不限于") is True

    def test_is_template_content_hint_false(self):
        from modules.achievement.importer import _is_template_content_hint
        assert _is_template_content_hint("正常文本") is False

    def test_select_fallback_title(self):
        from modules.achievement.importer import _select_fallback_title
        title, idx = _select_fallback_title(["新型材料技术", "简介内容"])
        assert title is not None

    def test_select_fallback_title_empty(self):
        from modules.achievement.importer import _select_fallback_title
        title, idx = _select_fallback_title([])
        assert title == ""


class TestImporterExtractDocument:
    def test_extract_unsupported_format(self):
        from modules.achievement.importer import extract_document_records
        from core.errors import BizError
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
        tmp.write(b"test")
        tmp.close()
        try:
            with pytest.raises(BizError):
                extract_document_records(tmp.name)
        finally:
            os.unlink(tmp.name)

    def test_is_full_slide_background(self):
        from modules.achievement.importer import _is_full_slide_background
        # No width/height → False
        assert _is_full_slide_background(MagicMock(), 0, 0) is False

    def test_normalize_contributor_page(self):
        from modules.achievement.importer import _normalize_contributor_page
        page = {
            "sourcePageOrSlide": "slide-2",
            "text": "张三\n联系电话：13800138000\n高级工程师，博士生导师",
            "images": [],
        }
        result = _normalize_contributor_page(page)
        assert "inventor" in result
        assert result["pageType"] == "contributor"


class TestImporterUploadCandidateMedia:
    def test_upload_candidate_media_no_images(self):
        from modules.achievement.importer import upload_candidate_media
        records = [{"normalized": {}, "raw": {}, "images": []}]
        result = upload_candidate_media(records, 1, MagicMock())
        assert result == []


class TestImporterListBatches:
    @patch("modules.achievement.importer.get_cursor")
    def test_list_import_batches(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import list_import_batches
        result = list_import_batches()
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# routes/ai.py helper functions
# ══════════════════════════════════════════════════════════════

class TestAiRoutesHelpers:
    def test_safe_snippet_short(self):
        from routes.ai import _safe_snippet
        assert _safe_snippet("hello") == "hello"

    def test_safe_snippet_long(self):
        from routes.ai import _safe_snippet
        result = _safe_snippet("x" * 500)
        assert len(result) <= 305

    def test_safe_snippet_empty(self):
        from routes.ai import _safe_snippet
        assert _safe_snippet("") == ""

    def test_safe_snippet_none(self):
        from routes.ai import _safe_snippet
        assert _safe_snippet(None) == ""

    def test_network_reason_timeout(self):
        from routes.ai import _network_reason
        exc = TimeoutError("timed out")
        assert _network_reason(exc) == "timeout"

    def test_network_reason_connection_refused(self):
        from routes.ai import _network_reason
        exc = ConnectionRefusedError("refused")
        assert _network_reason(exc) == "connection_refused"

    def test_network_reason_unreachable(self):
        from routes.ai import _network_reason
        exc = Exception("some other error")
        assert _network_reason(exc) == "unreachable"

    def test_read_http_error_body(self):
        import urllib.error
        from routes.ai import _read_http_error_body
        exc = urllib.error.HTTPError("http://test", 500, "error", {}, None)
        exc.read = MagicMock(return_value=b"error body")
        result = _read_http_error_body(exc)
        assert "error body" in result

    def test_parse_agent_error_details_dict(self):
        from routes.ai import _parse_agent_error_details
        body = json.dumps({"detail": {"layer": "llm", "llmStatus": 429, "llmReason": "rate limit"}})
        result = _parse_agent_error_details(502, body)
        assert result["layer"] == "llm"
        assert result["llmStatus"] == 429

    def test_parse_agent_error_details_string_detail(self):
        from routes.ai import _parse_agent_error_details
        body = json.dumps({"detail": "some error message"})
        result = _parse_agent_error_details(500, body)
        assert "upstreamBody" in result

    def test_parse_agent_error_details_empty(self):
        from routes.ai import _parse_agent_error_details
        result = _parse_agent_error_details(500, "")
        assert result["agentStatus"] == 500

    def test_parse_agent_error_details_malformed_json(self):
        from routes.ai import _parse_agent_error_details
        result = _parse_agent_error_details(500, "not json")
        assert "upstreamBody" in result

    def test_extract_demand_keywords(self):
        from routes.ai import _extract_demand_keywords
        result = _extract_demand_keywords("寻找新型材料技术", "需要一种耐高温的复合材料")
        assert isinstance(result, list)
        assert len(result) <= 6

    def test_extract_demand_keywords_empty(self):
        from routes.ai import _extract_demand_keywords
        result = _extract_demand_keywords("", "")
        assert result == []

    def test_build_match_reasons(self):
        from routes.ai import _build_match_reasons
        card = {"title": "新型材料技术", "description": "耐高温复合材料", "application_fields": ["航天"]}
        keywords = ["材料", "复合材料", "航天"]
        result = _build_match_reasons(card, keywords)
        assert isinstance(result, list)
        assert len(result) <= 4

    def test_build_match_reasons_empty(self):
        from routes.ai import _build_match_reasons
        result = _build_match_reasons({}, [])
        assert result == []

    def test_raise_from_agent_http_429(self):
        from routes.ai import _raise_from_agent_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_agent_http(429, "")

    def test_raise_from_agent_http_500_llm(self):
        from routes.ai import _raise_from_agent_http
        from core.errors import BizError
        body = json.dumps({"detail": {"layer": "llm"}})
        with pytest.raises(BizError):
            _raise_from_agent_http(500, body)

    def test_raise_from_agent_http_503(self):
        from routes.ai import _raise_from_agent_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_agent_http(503, "")

    def test_raise_from_agent_network(self):
        from routes.ai import _raise_from_agent_network
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_agent_network(ConnectionRefusedError("refused"))

    def test_persist_failed_turn(self):
        from routes.ai import _persist_failed_turn
        # Should not raise even if append_turn fails
        with patch("routes.ai.append_turn", side_effect=Exception("db error")):
            _persist_failed_turn(1, "question", "answer")


# ══════════════════════════════════════════════════════════════
# modules/patent/service.py
# ══════════════════════════════════════════════════════════════

class TestPatentService:
    @patch("modules.patent.provider.search_raw")
    def test_search_patents_empty(self, mock_search):
        mock_search.return_value = {"results": [], "total": 0}
        from modules.patent.service import search_patents
        result = search_patents("AI", "", 1, 10)
        assert ("list" in result or "items" in result)
        assert "total" in result

    @patch("modules.patent.provider.search_raw")
    def test_search_patents_with_results(self, mock_search):
        mock_search.return_value = {
            "results": [{"title": "Patent 1", "number": "CN12345678A"}],
            "total": 1,
        }
        from modules.patent.service import search_patents
        result = search_patents("AI", "", 1, 10)
        assert result["total"] >= 0

    def test_search_patents_no_keyword_raises(self):
        from modules.patent.service import search_patents
        from core.errors import BizError
        with pytest.raises(BizError):
            search_patents("", "", 1, 10)


# ══════════════════════════════════════════════════════════════
# modules/patent/history.py
# ══════════════════════════════════════════════════════════════

class TestPatentHistory:
    @patch("modules.patent.history.get_cursor")
    def test_list_history(self, mock_gc):
        cur = _mock_cursor(fetchall_val=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.patent.history import list_history
        result = list_history(1, "keyword")
        assert isinstance(result, (list, dict))

    @patch("modules.patent.history.get_cursor")
    def test_clear_history(self, mock_gc):
        cur = MagicMock()
        cur.rowcount = 3
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.patent.history import clear_history
        result = clear_history(1, "keyword")
        assert result == 3

    @patch("modules.patent.history.get_cursor")
    def test_record_history(self, mock_gc):
        cur = _mock_cursor(fetchone_val={"id": 1, "created_at": datetime(2026, 1, 1)}  )
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.patent.history import record_history
        result = record_history(1, "keyword", "AI")
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/patent/provider.py
# ══════════════════════════════════════════════════════════════

class TestPatentProvider:
    def test_patent_provider_import(self):
        from modules.patent import provider
        assert provider is not None


# ══════════════════════════════════════════════════════════════
# Additional routes coverage
# ══════════════════════════════════════════════════════════════

class TestCoreIdempotency:
    def test_idempotent_create_no_key(self):
        from core.idempotency import idempotent_create
        request = MagicMock()
        request.headers.get.return_value = ""
        result = idempotent_create(request, {"userId": 1})
        assert result is None


class TestCoreRateLimit:
    def test_check_user_rate(self):
        from core.rate_limit import check_user_rate
        # First call should not raise
        check_user_rate(99999, "test_action", limit=100, window_s=60)


class TestCorePagination:
    def test_parse_page_args(self):
        from core.pagination import parse_page_args  # noqa
        request = MagicMock()
        request.query_params = {"page": "2", "pageSize": "20", "keyword": "AI"}
        page, page_size, keyword = parse_page_args(request)
        assert page == 2
        assert page_size == 20
        assert keyword == "AI"

    def test_parse_page_args_defaults(self):
        from core.pagination import parse_page_args  # noqa
        request = MagicMock()
        request.query_params = {}
        page, page_size, keyword = parse_page_args(request)
        assert page == 1
        assert page_size == 10
        assert keyword == ""