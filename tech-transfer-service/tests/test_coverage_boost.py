"""Comprehensive coverage boost tests with correct mock patterns.

All mocks target the correct module's get_cursor (where the function is defined),
not modules.admin.service.get_cursor.
"""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


def _ctx(cur):
    """Return a mock get_cursor context manager that yields cur."""
    mock_gc = MagicMock()
    mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)
    return mock_gc


def _trans_ctx(cur):
    """Return a mock transaction context manager with a cursor."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cur
    mock_t = MagicMock()
    mock_t.return_value = conn
    return mock_t, conn


# ══════════════════════════════════════════════════════════════
# modules/admin/service.py — Fixed mock patterns
# ══════════════════════════════════════════════════════════════

class TestAdminListAchievementsFixed:
    @patch("modules.admin.service.organization_content_scope", return_value=(None, []))
    @patch("modules.admin.service.can_claim_unassigned_content", return_value=False)
    @patch("modules.admin.service.get_cursor")
    def test_list_achievements_admin_empty(self, mock_gc, _mock_claim, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_achievements_admin
        result = list_achievements_admin({"page": "1", "pageSize": "10"}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)
        assert "list" in result
        assert result["total"] == 0

    @patch("modules.admin.service.organization_content_scope", return_value=(None, []))
    @patch("modules.admin.service.can_claim_unassigned_content", return_value=False)
    @patch("modules.admin.service.get_cursor")
    def test_list_achievements_admin_with_data(self, mock_gc, _mock_claim, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 2}
        cur.fetchall.return_value = [
            {"id": 1, "title": "成果1", "status": "published", "version": 1, "org_id": 1,
             "tech_intro": "技术简介", "source_org_name": "测试机构", "view_count": 10,
             "reject_reason": None, "published_at": datetime(2026, 1, 1),
             "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
             "owner_user_id": 1, "institution_name": "测试机构", "category_name": "技术",
             "category_code": "tech", "submitter_user_no": "U001", "submitter_name": "张三"},
            {"id": 2, "title": "成果2", "status": "draft", "version": 1, "org_id": 1,
             "tech_intro": None, "source_org_name": None, "view_count": 0,
             "reject_reason": None, "published_at": None,
             "created_at": datetime(2026, 1, 2), "updated_at": datetime(2026, 1, 2),
             "owner_user_id": 2, "institution_name": None, "category_name": None,
             "category_code": None, "submitter_user_no": "U002", "submitter_name": "李四"},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_achievements_admin
        result = list_achievements_admin({"page": "1", "pageSize": "10", "status": "published"}, {"isPlatformAdmin": True})
        assert result["total"] == 2
        assert len(result["list"]) == 2

    @patch("modules.admin.service.organization_content_scope", return_value=(None, []))
    @patch("modules.admin.service.can_claim_unassigned_content", return_value=False)
    @patch("modules.admin.service.get_cursor")
    def test_list_achievements_admin_with_keyword(self, mock_gc, _mock_claim, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "title": "AI成果", "status": "published", "version": 1, "org_id": 1,
             "tech_intro": None, "source_org_name": None, "view_count": 0,
             "reject_reason": None, "published_at": None,
             "created_at": None, "updated_at": None,
             "owner_user_id": 1, "institution_name": None, "category_name": None,
             "category_code": None, "submitter_user_no": "U001", "submitter_name": "张三"},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_achievements_admin
        result = list_achievements_admin({"keyword": "AI", "categoryCode": "tech"}, {"isPlatformAdmin": True})
        assert result["total"] == 1


class TestAdminListDemandsFixed:
    @patch("modules.admin.service.organization_content_scope", return_value=(None, []))
    @patch("modules.admin.service.get_cursor")
    def test_list_demands_admin_empty(self, mock_gc, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_demands_admin
        result = list_demands_admin({"page": "1", "pageSize": "10"}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)
        assert result["total"] == 0


class TestAdminDashboardFixed:
    @patch("modules.admin.service.get_cursor")
    def test_dashboard_summary(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "users": 10, "achievements": 5, "demands": 3, "cooperations": 1,
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
        assert result["users"] == 10
        assert result["achievements"] == 5

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_todos(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_todos
        result = dashboard_todos(10)
        assert isinstance(result, list)

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_todos_with_items(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"kind": "achievement", "id": 1, "title": "test", "created_at": datetime(2026, 1, 1)},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_todos
        result = dashboard_todos(10)
        assert isinstance(result, list)

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_trend(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = [{"dt": "2026-01-01", "count": 5}]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_trend
        result = dashboard_trend(7)
        assert isinstance(result, list)

    @patch("modules.admin.service.get_cursor")
    def test_dashboard_trend_30_days(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import dashboard_trend
        result = dashboard_trend(30)
        assert isinstance(result, list)

    @patch("modules.admin.service.dashboard_summary")
    def test_notification_summary_platform(self, mock_ds):
        mock_ds.return_value = {
            "pendingAchievements": 2, "pendingDemands": 1,
            "pendingCooperations": 0, "pendingOrganizationApplications": 0,
            "pendingOrganizationAdminApplications": 0, "pendingMembershipApplications": 1,
        }
        from modules.admin.service import notification_summary
        result = notification_summary({"isPlatformAdmin": True})
        assert result["total"] == 4
        assert "categories" in result

    @patch("modules.admin.service._coop_org_visibility_sql", return_value=("1=1", []))
    @patch("modules.admin.service._sql_in", return_value=("1=1", [1]))
    @patch("modules.admin.service.organization_content_scope", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_notification_summary_org_admin(self, mock_gc, _mock_scope, _mock_sql, _mock_coop):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "pending_achievements": 1, "pending_demands": 0,
            "pending_cooperations": 0, "pending_membership_applications": 0,
        }
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import notification_summary
        result = notification_summary({"orgIds": [1]})
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_list_audit_logs(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_audit_logs
        result = list_audit_logs({"page": "1", "pageSize": "10"})
        assert isinstance(result, dict)
        assert result["total"] == 0
        assert "list" in result

    @patch("modules.admin.service.get_cursor")
    def test_list_audit_logs_with_filters(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "actor_user_id": 1, "actor_user_no": "U001", "action": "create",
             "resource_type": "achievement", "resource_id": "1", "details": "{}",
             "request_id": "req1", "created_at": datetime(2026, 1, 1)},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_audit_logs
        result = list_audit_logs({"actorUserId": "1", "targetType": "achievement", "requestId": "req1"})
        assert result["total"] == 1
        assert len(result["list"]) == 1


class TestAdminInstitutionsFixed:
    @patch("modules.admin.service.get_cursor")
    def test_list_institutions_admin_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_institutions_admin
        result = list_institutions_admin({"page": "1", "pageSize": "10"})
        assert isinstance(result, dict)
        assert result["total"] == 0

    @patch("modules.admin.service.get_cursor")
    def test_list_institutions_admin_with_filters(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "name": "测试机构", "kind": "enterprise", "status": "active",
             "intro": None, "label": None, "support_unit": None, "region": None,
             "platform_type_key": None, "created_at": datetime(2026, 1, 1),
             "updated_at": datetime(2026, 1, 1)},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_institutions_admin
        result = list_institutions_admin({"kind": "enterprise", "status": "active", "keyword": "测试"})
        assert result["total"] == 1

    @patch("modules.admin.service.get_cursor")
    def test_get_institution_admin_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 1, "name": "测试机构", "kind": "enterprise", "status": "active",
            "intro": "简介", "label": None, "support_unit": None, "region": "深圳",
            "platform_type_key": None, "created_at": datetime(2026, 1, 1),
            "updated_at": datetime(2026, 1, 1),
        }
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_institution_admin
        result = get_institution_admin(1)
        assert isinstance(result, dict)
        assert result["id"] == 1

    @patch("modules.admin.service.get_cursor")
    def test_get_institution_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_institution_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_institution_admin(999)


class TestAdminUsersFixed:
    @patch("modules.admin.service._user_membership_scope_sql", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_list_users_admin_empty(self, mock_gc, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_users_admin
        result = list_users_admin({"page": "1", "pageSize": "10"}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)
        assert result["total"] == 0

    @patch("modules.admin.service._user_membership_scope_sql", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_list_users_admin_with_data(self, mock_gc, _mock_scope):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "user_no": "U001", "status": "active", "display_name": "张三",
             "phone": "138", "email": None, "org_name": None, "created_at": datetime(2026, 1, 1),
             "roles": ["user"]},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_users_admin
        result = list_users_admin({"keyword": "U001", "status": "active"}, {"isPlatformAdmin": True})
        assert result["total"] == 1

    @patch("modules.admin.service.get_cursor")
    def test_get_user_admin_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 1, "user_no": "U001", "status": "active", "display_name": "张三",
             "phone": "138", "email": None, "org_name": None, "created_at": datetime(2026, 1, 1),
             "roles": ["user"]},
            {"ach_count": 5, "dmd_count": 3, "coop_count": 1, "fav_count": 10},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_user_admin
        result = get_user_admin(1, {"isPlatformAdmin": True})
        assert isinstance(result, dict)
        assert result["statistics"]["achievementCount"] == 5

    @patch("modules.admin.service.get_cursor")
    def test_get_user_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_user_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_user_admin(999, {"isPlatformAdmin": True})


class TestAdminCooperationsFixed:
    @patch("modules.admin.service._coop_org_visibility_sql", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_list_cooperations_admin_empty(self, mock_gc, _mock_coop):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import list_cooperations_admin
        result = list_cooperations_admin({"page": "1", "pageSize": "10"}, {"isPlatformAdmin": True})
        assert isinstance(result, dict)
        assert result["total"] == 0

    @patch("modules.admin.service._coop_org_visibility_sql", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_get_cooperation_admin_not_found(self, mock_gc, _mock_coop):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_cooperation_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_cooperation_admin(999, {"isPlatformAdmin": True})

    @patch("modules.admin.service._coop_org_visibility_sql", return_value=("1=1", []))
    @patch("modules.admin.service.get_cursor")
    def test_get_cooperation_admin_found(self, mock_gc, _mock_coop):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 1, "status": "pending", "target_type": "achievement", "target_id": 1,
             "initiator_user_id": 1, "target_owner_user_id": 2, "message": "合作",
             "reject_reason": None, "version": 1, "created_at": datetime(2026, 1, 1),
             "updated_at": datetime(2026, 1, 1), "title": "成果", "source_org_name": "机构",
             "display_name": "张三", "user_no": "U001"},
            # events
        ]
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_cooperation_admin
        result = get_cooperation_admin(1, {"isPlatformAdmin": True})
        assert isinstance(result, dict)


class TestAdminCrudAdminFixed:
    @patch("modules.admin.service.get_cursor")
    def test_get_achievement_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_achievement_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_achievement_admin(999, {"isPlatformAdmin": True})

    @patch("modules.admin.service.get_cursor")
    def test_get_demand_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import get_demand_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            get_demand_admin(999, {"isPlatformAdmin": True})

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_achievement_admin_success(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1}
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_achievement_admin
        result = soft_delete_achievement_admin({"isPlatformAdmin": True}, 1)
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_achievement_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_achievement_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            soft_delete_achievement_admin({"isPlatformAdmin": True}, 999)

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_demand_admin_success(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1}
        cur.rowcount = 1
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_demand_admin
        result = soft_delete_demand_admin({"isPlatformAdmin": True}, 1)
        assert isinstance(result, dict)

    @patch("modules.admin.service.get_cursor")
    def test_soft_delete_demand_admin_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import soft_delete_demand_admin
        from core.errors import BizError
        with pytest.raises(BizError):
            soft_delete_demand_admin({"isPlatformAdmin": True}, 999)


# ══════════════════════════════════════════════════════════════
# modules/admin/service.py — Additional coverage for admin CRUD
# ══════════════════════════════════════════════════════════════

class TestAdminInstitutionCrud:
    @patch("modules.admin.service.get_cursor")
    def test_create_institution_validation_error(self, mock_gc):
        from modules.admin.service import create_institution
        from core.errors import BizError
        with pytest.raises(BizError):
            create_institution({"userId": 1, "userNo": "U001"}, {"name": ""})

    @patch("modules.admin.service.get_cursor")
    def test_update_institution_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import update_institution
        from core.errors import BizError
        with pytest.raises(BizError):
            update_institution({"userId": 1, "userNo": "U001"}, 999, {"name": "test", "kind": "enterprise"})

    @patch("modules.admin.service.get_cursor")
    def test_set_institution_status_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import set_institution_status
        from core.errors import BizError
        with pytest.raises(BizError):
            set_institution_status({"userId": 1, "userNo": "U001"}, 999, "enable")

    @patch("modules.admin.service.get_cursor")
    def test_delete_institution_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import delete_institution
        from core.errors import BizError
        with pytest.raises(BizError):
            delete_institution({"userId": 1, "userNo": "U001"}, 999)

    @patch("modules.admin.service.get_cursor")
    def test_validate_inst_payload(self, mock_gc):
        from modules.admin.service import _validate_inst_payload
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_inst_payload({}, require_kind=True)

    def test_to_int_or_none(self):
        from modules.admin.service import _to_int_or_none
        assert _to_int_or_none("5") == 5
        assert _to_int_or_none(None) is None
        assert _to_int_or_none("abc") is None

    def test_normalize_import_item(self):
        from modules.admin.service import _normalize_import_item
        result = _normalize_import_item({"name": "测试机构", "kind": "enterprise"})
        assert isinstance(result, dict)


class TestAdminReviewAdvanced:
    @patch("modules.admin.service.get_cursor")
    def test_review_demand_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_demand
        from core.errors import BizError
        with pytest.raises(BizError):
            review_demand({"userId": 99}, 999, {"_action": "approve", "version": 1})

    def test_review_demand_no_version(self):
        from modules.admin.service import review_demand
        from core.errors import BizError
        with pytest.raises(BizError):
            review_demand({"userId": 99}, 1, {"_action": "approve"})

    def test_review_demand_reject_no_reason(self):
        from modules.admin.service import review_demand
        from core.errors import BizError
        with pytest.raises(BizError):
            review_demand({"userId": 99}, 1, {"_action": "reject", "version": 1})

    @patch("modules.admin.service.get_cursor")
    def test_review_demand_wrong_status(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"status": "draft", "version": 1, "owner_user_id": 1}
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import review_demand
        from core.errors import BizError
        with pytest.raises(BizError):
            review_demand({"userId": 99}, 1, {"_action": "approve", "version": 1})


class TestAdminPageHelper:
    def test_page_of(self):
        from modules.admin.service import _page_of
        result = _page_of([], 1, 10, 0, lambda r: r)
        assert result["total"] == 0
        assert result["page"] == 1
        assert result["list"] == []

    def test_page_of_with_data(self):
        from modules.admin.service import _page_of
        result = _page_of([{"id": 1}, {"id": 2}], 1, 10, 2, lambda r: {"mapped": r["id"]})
        assert len(result["list"]) == 2
        assert result["totalPages"] == 1


class TestAdminContentHelpers:
    def test_ach_admin_item(self):
        from modules.admin.service import _ach_admin_item
        row = {
            "id": 1, "title": "测试", "status": "published", "version": 1,
            "org_id": 1, "tech_intro": None, "source_org_name": None,
            "view_count": 0, "reject_reason": None, "published_at": None,
            "created_at": datetime(2026, 1, 1), "updated_at": datetime(2026, 1, 1),
            "owner_user_id": 1, "institution_name": None, "category_name": None,
            "category_code": None, "submitter_user_no": None, "submitter_name": None,
        }
        result = _ach_admin_item(row)
        assert result["id"] == 1

    def test_dmd_queue_item(self):
        from modules.admin.service import _dmd_queue_item
        row = {
            "id": 1, "title": "需求", "category_name": None, "category_code": None,
            "source_org_name": None, "created_at": datetime(2026, 1, 1),
            "owner_user_id": 1, "submitter_name": "张三", "version": 1,
            "status": "pending_review",
        }
        result = _dmd_queue_item(row)
        assert result["id"] == 1

    def test_ach_queue_item(self):
        from modules.admin.service import _ach_queue_item
        row = {
            "id": 1, "title": "成果", "category_name": None, "category_code": None,
            "source_org_name": None, "created_at": datetime(2026, 1, 1),
            "owner_user_id": 1, "submitter_name": "张三", "version": 1,
            "status": "pending_review",
        }
        result = _ach_queue_item(row)
        assert result["id"] == 1


class TestAdminCoopOrgVisibility:
    def test_coop_org_visibility_platform_admin(self):
        from modules.admin.service import _coop_org_visibility_sql
        clause, params = _coop_org_visibility_sql({"isPlatformAdmin": True})
        assert clause == "TRUE"
        assert params == []

    def test_coop_org_visibility_org_admin(self):
        from modules.admin.service import _coop_org_visibility_sql
        clause, params = _coop_org_visibility_sql({"orgIds": [1, 2]})
        assert isinstance(clause, str)

    def test_user_membership_scope_sql_platform(self):
        from modules.admin.service import _user_membership_scope_sql
        clause, params = _user_membership_scope_sql({"isPlatformAdmin": True})
        assert "1=1" in clause

    def test_user_membership_scope_sql_org(self):
        from modules.admin.service import _user_membership_scope_sql
        clause, params = _user_membership_scope_sql({"orgIds": [1]})
        assert isinstance(clause, str)

    def test_append_org_row_filter(self):
        from modules.admin.service import append_org_row_filter
        where, params = [], []
        append_org_row_filter(where, params, {"isPlatformAdmin": True})
        assert len(where) == 0

    def test_append_org_row_filter_org(self):
        from modules.admin.service import append_org_row_filter
        where, params = [], []
        append_org_row_filter(where, params, {"orgId": 1})
        assert len(where) == 1

    def test_append_content_scope(self):
        from modules.admin.service import append_content_scope
        where, params = [], []
        append_content_scope(where, params, {"isPlatformAdmin": True}, "a")
        assert len(where) == 0


# ══════════════════════════════════════════════════════════════
# modules/admin/service.py — Review queues with data
# ══════════════════════════════════════════════════════════════

class TestAdminReviewQueuesWithData:
    @patch("modules.admin.service.get_cursor")
    def test_achievements_review_queue_with_data(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "title": "成果", "category_name": None, "category_code": None,
             "source_org_name": None, "created_at": datetime(2026, 1, 1),
             "owner_user_id": 1, "submitter_name": "张三", "version": 1,
             "status": "pending_review"},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import achievements_review_queue
        result = achievements_review_queue({"page": "1", "pageSize": "10"})
        assert "list" in result
        assert result["total"] == 1

    @patch("modules.admin.service.get_cursor")
    def test_demands_review_queue_with_data(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [
            {"id": 1, "title": "需求", "category_name": None, "category_code": None,
             "source_org_name": None, "created_at": datetime(2026, 1, 1),
             "owner_user_id": 1, "submitter_name": "张三", "version": 1,
             "status": "pending_review"},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.admin.service import demands_review_queue
        result = demands_review_queue({"page": "1", "pageSize": "10"})
        assert "list" in result
        assert result["total"] == 1


# ══════════════════════════════════════════════════════════════
# modules/identity/service.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestIdentityBuildUserFixed:
    def test_build_user_response_found(self):
        cur = MagicMock()
        profile = {
            "user_id": 1, "display_name": "Test", "user_type": "person",
            "phone": "138", "email": "test@test.com", "org_id": None,
            "org_title": None, "company_text": None, "version": 1,
            "subject_type": None, "business_capabilities": None, "wechat": None,
        }
        user_row = {"user_no": "U001", "status": "active"}
        cur.fetchone.side_effect = [profile, user_row]
        cur.fetchall.side_effect = [[{"role_code": "user"}], []]
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
            None,
        ]
        cur.fetchall.return_value = [{"role_code": "user"}]
        from modules.identity.service import build_user_response
        result = build_user_response(cur, 1)
        assert result is None

    def test_build_user_response_with_org(self):
        cur = MagicMock()
        profile = {
            "user_id": 1, "display_name": "Test", "user_type": "person",
            "phone": "138", "email": "e", "org_id": 1, "org_title": "工程师",
            "company_text": "公司", "version": 1, "subject_type": "enterprise",
            "business_capabilities": '["技术转让"]', "wechat": "wx123",
        }
        user_row = {"user_no": "U001", "status": "active"}
        cur.fetchone.side_effect = [profile, user_row, {"name": "测试机构"}]
        cur.fetchall.side_effect = [[{"role_code": "admin"}], [{"id": 1, "org_id": 1, "org_name": "测试机构", "role": "admin", "status": "active", "version": 1}]]
        from modules.identity.service import build_user_response
        result = build_user_response(cur, 1)
        assert result is not None
        assert result["orgName"] == "测试机构"
        assert len(result["businessCapabilities"]) == 1


class TestIdentityRegisterFixed:
    @patch("modules.identity.service.sign_refresh_token", return_value=("ref", "jti"))
    @patch("modules.identity.service.sign_access_token", return_value="tok")
    @patch("modules.identity.service.hash_password", return_value="hashed")
    @patch("modules.identity.service.validate_phone", return_value="13800138000")
    @patch("modules.identity.service.get_cursor")
    def test_register_user_success(self, mock_gc, _vp, _hp, _sat, _srt):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"m": 0},  # _generate_user_no
            None,  # phone check
            {"id": 1},  # INSERT app_user
            {"user_id": 1, "display_name": "13800138000", "user_type": None,
             "phone": "13800138000", "email": None, "org_id": None,
             "org_title": None, "company_text": None, "version": 1,
             "subject_type": None, "business_capabilities": None, "wechat": None},
            {"user_no": "U001", "status": "active"},
            None,  # org admin
            None,  # org name
            {"user_no": "U001", "status": "active"},  # _issue_session
        ]
        cur.fetchall.side_effect = [
            [{"role_code": "user"}],
            [],
            [{"role_code": "user"}],
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.service import register_user
        result = register_user("13800138000", "password123")
        assert "user" in result


class TestIdentityLoginValidation:
    def test_password_login_no_username(self):
        from modules.identity.service import password_login_session
        from core.errors import BizError
        with pytest.raises(BizError):
            password_login_session("", "password")

    def test_password_login_no_password(self):
        from modules.identity.service import password_login_session
        from core.errors import BizError
        with pytest.raises(BizError):
            password_login_session("admin", "")

    def test_login_phone_no_phone(self):
        from modules.identity.service import login_phone_session
        from core.errors import BizError
        with pytest.raises(BizError):
            login_phone_session("", "password")


class TestIdentityRefreshFixed:
    def test_refresh_session_invalid_token(self):
        from modules.identity.service import refresh_session
        from core.errors import BizError
        with patch("modules.identity.service.decode_no_verify_exp", side_effect=Exception("bad")):
            with pytest.raises(BizError):
                refresh_session("bad_token")

    def test_refresh_session_wrong_type(self):
        from modules.identity.service import refresh_session
        from core.errors import BizError
        with patch("modules.identity.service.decode_no_verify_exp", return_value={"sub": "1", "type": "access", "jti": "x"}):
            with pytest.raises(BizError):
                refresh_session("token")


class TestIdentityHelpers:
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

    def test_parse_capabilities_empty_list(self):
        from modules.identity.service import _parse_capabilities
        assert _parse_capabilities([]) == []


class TestIdentityRegisterPassword:
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


# ══════════════════════════════════════════════════════════════
# modules/membership/service.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestMembershipHelpersFixed:
    def test_map_read_row(self):
        from modules.membership.service import _map_read_row
        row = {"user_id": 1, "org_name": "Test", "created_at": "2026-01-01"}
        result = _map_read_row(row)
        assert "userId" in result
        assert "orgName" in result

    def test_resolve_content_organization_none(self):
        from modules.membership.service import resolve_content_organization
        cur = MagicMock()
        result = resolve_content_organization(cur, 1, None)
        assert result is None

    @patch("modules.membership.service.get_cursor")
    def test_list_my_memberships(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import list_my_memberships
        result = list_my_memberships({"userId": 1}, 1, 10)
        assert "list" in result
        assert "total" in result

    @patch("modules.membership.service.get_cursor")
    def test_list_my_membership_applications(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import list_my_membership_applications
        result = list_my_membership_applications({"userId": 1}, None, 1, 10)
        assert "list" in result

    @patch("modules.membership.service.get_cursor")
    def test_get_my_organization_certification(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import get_my_organization_certification
        result = get_my_organization_certification({"userId": 1})
        assert "memberships" in result
        assert result["status"] == "unverified"

    @patch("modules.membership.service.get_cursor")
    def test_active_membership_org_ids(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = [{"org_id": 1}, {"org_id": 2}]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import active_membership_org_ids
        result = active_membership_org_ids(1)
        assert result == {1, 2}

    @patch("modules.membership.service.get_cursor")
    def test_active_membership_org_ids_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.membership.service import active_membership_org_ids
        result = active_membership_org_ids(1)
        assert result == set()


class TestMembershipApplyFixed:
    @patch("modules.membership.service.audit_record")
    @patch("modules.membership.service.transaction")
    def test_apply_membership_success(self, mock_trans, mock_audit):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1},  # org exists
            None,  # existing membership
            None,  # existing application
            {"id": 1, "status": "pending", "version": 1, "org_id": 1},  # INSERT RETURNING
        ]
        from modules.membership.service import apply_membership
        result = apply_membership({"userId": 1}, {"orgId": 1})
        assert result["status"] == "pending"

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

    @patch("modules.membership.service.transaction")
    def test_apply_membership_already_member(self, mock_trans):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1},  # org exists
            {"1": 1},  # already member
        ]
        from modules.membership.service import apply_membership
        from core.errors import BizError
        with pytest.raises(BizError):
            apply_membership({"userId": 1}, {"orgId": 1})


class TestMembershipCancelFixed:
    @patch("modules.membership.service.audit_record")
    @patch("modules.membership.service.transaction")
    def test_cancel_membership_application_success(self, mock_trans, mock_audit):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1},  # existence check
            {"id": 1, "user_id": 1, "org_id": 1, "status": "cancelled", "version": 2},
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
# modules/institution_registration/service.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestInstitutionRegistrationFixed:
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

    @patch("modules.institution_registration.service.get_cursor")
    def test_list_institution_registrations(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution_registration.service import list_institution_registrations
        result = list_institution_registrations({})
        assert "list" in result
        assert "total" in result

    @patch("modules.institution_registration.service.get_cursor")
    def test_list_institution_registrations_with_status(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
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

    @patch("modules.institution_registration.service.approve_organization_application")
    @patch("modules.institution_registration.service.get_cursor")
    def test_approve_institution_registration(self, mock_gc, mock_approve):
        cur = MagicMock()
        cur.fetchone.return_value = {"version": 1, "proof_material": None}
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_approve.return_value = {"status": "approved", "orgId": 1}
        from modules.institution_registration.service import approve_institution_registration
        result = approve_institution_registration({"userId": 99}, 1)
        assert result["status"] == "approved"

    @patch("modules.institution_registration.service.reject_organization_application")
    @patch("modules.institution_registration.service.get_cursor")
    def test_reject_institution_registration(self, mock_gc, mock_reject):
        cur = MagicMock()
        cur.fetchone.return_value = {"version": 1}
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_reject.return_value = {"status": "rejected"}
        from modules.institution_registration.service import reject_institution_registration
        result = reject_institution_registration({"userId": 99}, 1, "不合规")
        assert result["status"] == "rejected"

    @patch("modules.institution_registration.service.get_cursor")
    def test_load_application_version_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution_registration.service import _load_application_version
        from core.errors import BizError
        with pytest.raises(BizError):
            _load_application_version(999)


# ══════════════════════════════════════════════════════════════
# modules/ai/worker.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestAiWorkerHelpersFixed:
    def test_clip(self):
        from modules.ai.worker import _clip
        assert len(_clip("x" * 1000)) <= 500
        assert _clip("") != ""
        assert _clip(None) != ""

    def test_desensitize_reason_empty(self):
        from modules.ai.worker import _desensitize_reason
        result = _desensitize_reason("")
        assert result

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


class TestAiWorkerFixed:
    @patch("modules.ai.worker.get_cursor")
    def test_reap_stuck(self, mock_gc):
        cur = MagicMock()
        cur.rowcount = 2
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.worker import reap_stuck
        result = reap_stuck()
        assert result == 2

    @patch("modules.ai.worker.transaction")
    def test_claim_one_at_max(self, mock_trans):
        import modules.ai.worker as w
        old = w._running_count
        w._running_count = w.MAX_RUNNING + 1
        try:
            assert w.claim_one() is None
        finally:
            w._running_count = old

    @patch("modules.ai.worker.claim_one", return_value=None)
    @patch("modules.ai.worker.reap_stuck", return_value=0)
    @patch("modules.ai.provider.configured", return_value=True)
    def test_process_one_idle(self, _conf, _reap, _claim):
        from modules.ai.worker import process_one
        assert process_one() == "idle"

    @patch("modules.ai.provider.configured", return_value=False)
    def test_process_one_unconfigured(self, _conf):
        from modules.ai.worker import process_one
        assert process_one() == "unconfigured"

    @patch("modules.ai.worker.get_cursor")
    def test_fail(self, mock_gc):
        cur = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.worker import _fail
        _fail(1, "test reason")


# ══════════════════════════════════════════════════════════════
# modules/ai/service.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestAiServiceHelpersFixed:
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
        _check_user_rate(99999)


class TestAiServiceGetTaskFixed:
    @patch("modules.ai.service.get_cursor")
    def test_get_evaluation_task_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.service import get_evaluation_task
        from core.errors import BizError
        with pytest.raises(BizError):
            get_evaluation_task(1, 999)

    @patch("modules.ai.service.get_cursor")
    def test_get_evaluation_task_wrong_user(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 1, "task_type": "evaluation", "status": "queued",
            "created_by_user_id": 2, "target_id": 1, "input_data_version": "abc",
            "model_version_id": None, "fail_reason": None,
            "created_at": None, "started_at": None, "finished_at": None,
        }
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.service import get_evaluation_task
        from core.errors import BizError
        with pytest.raises(BizError):
            get_evaluation_task(1, 1)

    @patch("modules.ai.service.get_cursor")
    def test_get_evaluation_task_success(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 1, "task_type": "evaluation", "status": "succeeded",
             "created_by_user_id": 1, "target_id": 1, "input_data_version": "abc",
             "model_version_id": None, "fail_reason": None,
             "created_at": datetime(2026, 1, 1), "started_at": datetime(2026, 1, 1),
             "finished_at": datetime(2026, 1, 1)},
            {"achievement_id": 1, "achievement_title": "成果", "score_tech": 80.0,
             "score_application": 70.0, "score_maturity": 90.0, "score_feasibility": 75.0,
             "total_score": 78.8, "summary": "Good", "suggestions": '["Fast", "Reliable"]'},
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.ai.service import get_evaluation_task
        result = get_evaluation_task(1, 1)
        assert result["status"] == "succeeded"
        assert result["evaluation"] is not None


# ══════════════════════════════════════════════════════════════
# modules/patent/history.py — Correct mock target
# ══════════════════════════════════════════════════════════════

class TestPatentHistoryFixed:
    @patch("modules.patent.history.get_cursor")
    def test_list_history(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.patent.history import list_history
        result = list_history(1, "keyword")
        assert isinstance(result, list)

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
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1, "created_at": datetime.now()}
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.patent.history import record_history
        result = record_history(1, "keyword", "AI")
        assert isinstance(result, dict)

    def test_normalize_history_input(self):
        from modules.patent.history import normalize_history_input
        mode, kw = normalize_history_input("keyword", "test")
        assert mode == "keyword"
        assert kw == "test"

    def test_normalize_history_input_defaults(self):
        from modules.patent.history import normalize_history_input
        mode, kw = normalize_history_input("", "")
        assert mode == "keyword"


# ══════════════════════════════════════════════════════════════
# modules/patent/provider.py — Test helpers (no DB)
# ══════════════════════════════════════════════════════════════

class TestPatentProviderHelpers:
    def test_configured_false(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_BASE = ""
            from modules.patent.provider import _configured
            assert _configured() is False

    def test_configured_true(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_BASE = "http://localhost:8080"
            from modules.patent.provider import _configured
            assert _configured() is True

    def test_safe_snippet_short(self):
        from modules.patent.provider import _safe_snippet
        assert _safe_snippet("hello") == "hello"

    def test_safe_snippet_empty(self):
        from modules.patent.provider import _safe_snippet
        assert _safe_snippet("") == ""

    def test_safe_snippet_long(self):
        from modules.patent.provider import _safe_snippet
        result = _safe_snippet("x" * 500)
        assert len(result) <= 300

    def test_network_reason_timeout(self):
        from modules.patent.provider import _network_reason
        assert _network_reason(TimeoutError("timed out")) == "timeout"

    def test_network_reason_connection_refused(self):
        from modules.patent.provider import _network_reason
        assert _network_reason(ConnectionRefusedError("refused")) == "connection_refused"

    def test_network_reason_other(self):
        from modules.patent.provider import _network_reason
        assert _network_reason(Exception("other")) == "unreachable"

    def test_auth_headers(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_KEY = "test-key"
            from modules.patent.provider import _auth_headers
            h = _auth_headers()
            assert isinstance(h, dict)

    def test_auth_headers_no_key(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_KEY = ""
            from modules.patent.provider import _auth_headers
            h = _auth_headers()
            assert isinstance(h, dict)

    def test_provider_key(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_KEY = "test-key"
            from modules.patent.provider import _provider_key
            assert _provider_key() == "test-key"

    def test_build_url(self):
        with patch("modules.patent.provider.settings") as mock_settings:
            mock_settings.PATENT_API_BASE = "http://localhost:8080"
            from modules.patent.provider import _build_url
            url = _build_url("/search", {"q": "AI"})
            assert "localhost" in url

    def test_raise_from_http_401(self):
        from modules.patent.provider import _raise_from_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_http("/test", 401, "unauthorized")

    def test_raise_from_http_403(self):
        from modules.patent.provider import _raise_from_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_http("/test", 403, "forbidden")

    def test_raise_from_http_429(self):
        from modules.patent.provider import _raise_from_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_http("/test", 429, "rate limited")

    def test_raise_from_http_500(self):
        from modules.patent.provider import _raise_from_http
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_http("/test", 500, "server error")

    def test_raise_from_network_timeout(self):
        from modules.patent.provider import _raise_from_network
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_network("/test", TimeoutError("timed out"))

    def test_raise_from_network_connection(self):
        from modules.patent.provider import _raise_from_network
        from core.errors import BizError
        with pytest.raises(BizError):
            _raise_from_network("/test", ConnectionRefusedError("refused"))

    def test_read_http_error_body(self):
        import urllib.error
        from modules.patent.provider import _read_http_error_body
        exc = urllib.error.HTTPError("http://test", 500, "error", {}, None)
        exc.read = MagicMock(return_value=b"error body")
        result = _read_http_error_body(exc)
        assert "error body" in result


# ══════════════════════════════════════════════════════════════
# modules/achievement/importer.py — Test helpers (no DB)
# ══════════════════════════════════════════════════════════════

class TestImporterHelpersFixed:
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

    def test_patents_from_text(self):
        from modules.achievement.importer import _patents_from_text
        result = _patents_from_text("专利号：CN12345678A 和 ZL202011223344.5")
        assert len(result) >= 1

    def test_patents_from_text_empty(self):
        from modules.achievement.importer import _patents_from_text
        result = _patents_from_text("")
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

    def test_canonical_import_label(self):
        from modules.achievement.importer import _canonical_import_label
        assert _canonical_import_label("技术") is not None
        assert _canonical_import_label(None) is None

    def test_normalize_page(self):
        from modules.achievement.importer import _normalize_page
        page = {"sourcePageOrSlide": "1", "text": "text content", "images": []}
        result = _normalize_page(page)
        assert "pageType" in result

    def test_safe_import_filename(self):
        from modules.achievement.importer import _safe_import_filename
        result = _safe_import_filename("test.pdf", ".pdf")
        assert "test" in result
        assert result.endswith(".pdf")

    def test_batch_dto(self):
        from modules.achievement.importer import _batch_dto
        row = {"id": 1, "status": "staging", "original_filename": "test.pdf",
               "item_count": 5, "created_at": datetime(2026, 1, 1)}
        result = _batch_dto(row)
        assert result["id"] == 1
        assert result["status"] == "staging"


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

    def test_is_full_slide_background(self):
        from modules.achievement.importer import _is_full_slide_background
        assert _is_full_slide_background(MagicMock(), 0, 0) is False

    def test_upload_candidate_media_no_images(self):
        from modules.achievement.importer import upload_candidate_media
        records = [{"normalized": {}, "raw": {}, "images": []}]
        result = upload_candidate_media(records, 1, MagicMock())
        assert result == []


class TestImporterStageBatch:
    @patch("modules.achievement.importer.get_cursor")
    def test_list_import_batches_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import list_import_batches
        result = list_import_batches()
        assert "list" in result

    @patch("modules.achievement.importer.get_cursor")
    def test_get_import_batch_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import get_import_batch
        result = get_import_batch(999)
        assert result is None

    @patch("modules.achievement.importer.get_cursor")
    def test_clear_import_batches_empty(self, mock_gc):
        cur = MagicMock()
        cur.rowcount = 0
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import clear_import_batches
        result = clear_import_batches({"userId": 1, "userNo": "U001"})
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# core/pagination.py — Fixed
# ══════════════════════════════════════════════════════════════

class TestCorePaginationFixed:
    def test_parse_page_args(self):
        from core.pagination import parse_page_args
        request = MagicMock()
        request.query_params = {"page": "2", "pageSize": "20", "keyword": "AI"}
        page, page_size, keyword = parse_page_args(request)
        assert page == 2
        assert page_size == 20
        assert keyword == "AI"

    def test_parse_page_args_defaults(self):
        from core.pagination import parse_page_args
        request = MagicMock()
        request.query_params = {}
        page, page_size, keyword = parse_page_args(request)
        assert page == 1
        assert page_size == 10
        assert keyword == ""

    def test_parse_page_args_invalid(self):
        from core.pagination import parse_page_args
        request = MagicMock()
        request.query_params = {"page": "abc", "pageSize": "xyz"}
        page, page_size, keyword = parse_page_args(request)
        assert page == 1
        assert page_size == 10


# ══════════════════════════════════════════════════════════════
# core/idempotency.py — Additional
# ══════════════════════════════════════════════════════════════

class TestCoreIdempotencyFixed:
    def test_idempotent_create_no_key(self):
        from core.idempotency import idempotent_create
        request = MagicMock()
        request.headers.get.return_value = ""
        result = idempotent_create(request, {"userId": 1})
        assert result is None


# ══════════════════════════════════════════════════════════════
# core/rate_limit.py — Additional
# ══════════════════════════════════════════════════════════════

class TestCoreRateLimitFixed:
    def test_check_user_rate(self):
        from core.rate_limit import check_user_rate
        check_user_rate(99999, "test_action", limit=100, window_s=60)


# ══════════════════════════════════════════════════════════════
# Additional coverage: config.py
# ══════════════════════════════════════════════════════════════

class TestConfig:
    def test_settings_import(self):
        from config import settings
        assert hasattr(settings, "DATABASE_URL")


# ══════════════════════════════════════════════════════════════
# modules/achievement/extract.py
# ══════════════════════════════════════════════════════════════

class TestAchievementExtract:
    def test_extract_patent_numbers(self):
        from modules.achievement.extract import extract_patent_numbers
        result = extract_patent_numbers("专利号：CN12345678A")
        assert len(result) >= 1

    def test_extract_patent_numbers_empty(self):
        from modules.achievement.extract import extract_patent_numbers
        result = extract_patent_numbers("")
        assert result == []


# ══════════════════════════════════════════════════════════════
# modules/achievement/content.py
# ══════════════════════════════════════════════════════════════

class TestAchievementContent:
    def test_load_content_empty(self):
        from modules.achievement.content import load_content
        cur = MagicMock()
        cur.fetchone.return_value = None
        result = load_content(cur, 1)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/achievement/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestAchievementServiceHelpers:
    def test_validate_create_fields_missing_title(self):
        from modules.achievement.service import _validate_create_fields
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_create_fields({})

    def test_validate_create_fields_valid(self):
        from modules.achievement.service import _validate_create_fields
        _validate_create_fields({"title": "测试成果"})


# ══════════════════════════════════════════════════════════════
# modules/demand/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestDemandServiceHelpers:
    def test_validate_create_fields_missing_title(self):
        from modules.demand.service import _validate_create_fields
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_create_fields({})


# ══════════════════════════════════════════════════════════════
# modules/cooperation/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCooperationServiceHelpers:
    def test_validate_intent_body_missing(self):
        from modules.cooperation.service import _validate_intent_body
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_intent_body({})


# ══════════════════════════════════════════════════════════════
# modules/favorite/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestFavoriteServiceHelpers:
    @patch("modules.favorite.service.get_cursor")
    def test_list_favorites_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.favorite.service import list_favorites
        result = list_favorites({"userId": 1}, "achievement", 1, 10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/file/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestFileServiceHelpers:
    def test_validate_file_type(self):
        from modules.file.service import _validate_file_type
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_file_type("test.exe")

    def test_validate_file_size(self):
        from modules.file.service import _validate_file_size
        from core.errors import BizError
        with pytest.raises(BizError):
            _validate_file_size(100 * 1024 * 1024)  # 100MB


# ══════════════════════════════════════════════════════════════
# modules/search/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestSearchServiceHelpers:
    @patch("modules.search.service.get_cursor")
    def test_search_all_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.search.service import search_all
        result = search_all("test", 1, 10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/notification/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestNotificationServiceHelpers:
    @patch("modules.notification.service.get_cursor")
    def test_list_notifications_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.notification.service import list_notifications
        result = list_notifications(1, 1, 10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/profile/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestProfileServiceHelpers:
    @patch("modules.profile.service.get_cursor")
    def test_get_profile_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.profile.service import get_profile
        result = get_profile(1)
        assert result is None


# ══════════════════════════════════════════════════════════════
# modules/audit/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestAuditServiceHelpers:
    @patch("modules.audit.service.get_cursor")
    def test_record(self, mock_gc):
        cur = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.audit.service import record
        record("test.action", "test_resource", 1, 1, "U001", {"key": "val"})


# ══════════════════════════════════════════════════════════════
# modules/organization/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestOrganizationServiceHelpers:
    @patch("modules.organization.service.get_cursor")
    def test_get_organization_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.organization.service import get_organization
        result = get_organization(999)
        assert result is None


# ══════════════════════════════════════════════════════════════
# modules/identity/provider.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestIdentityProviderHelpers:
    def test_external_identity(self):
        from modules.identity.provider import ExternalIdentity
        ext = ExternalIdentity(issuer="test", tenant_id="t1", external_subject="s1", display_name="Test")
        assert ext.issuer == "test"


# ══════════════════════════════════════════════════════════════
# modules/capital/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCapitalServiceHelpers:
    @patch("modules.capital.service.get_cursor")
    def test_list_capital_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.capital.service import list_capital
        result = list_capital(1, 10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/inventor/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestInventorServiceHelpers:
    @patch("modules.inventor.service.get_cursor")
    def test_list_inventors_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.inventor.service import list_inventors
        result = list_inventors(1, 10)
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# core/masking.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreMasking:
    def test_mask_phone(self):
        from core.masking import mask_phone
        result = mask_phone("13800138000")
        assert "138" in result
        assert "****" in result

    def test_mask_phone_short(self):
        from core.masking import mask_phone
        result = mask_phone("123")
        assert isinstance(result, str)

    def test_mask_email(self):
        from core.masking import mask_email
        result = mask_email("test@example.com")
        assert "@" in result

    def test_mask_name(self):
        from core.masking import mask_name
        result = mask_name("张三")
        assert isinstance(result, str)


# ══════════════════════════════════════════════════════════════
# core/password.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCorePassword:
    def test_hash_password(self):
        from core.password import hash_password, verify_password
        hashed = hash_password("test123")
        assert verify_password("test123", hashed)
        assert not verify_password("wrong", hashed)


# ══════════════════════════════════════════════════════════════
# core/contact_validation.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestContactValidation:
    def test_validate_phone_valid(self):
        from core.contact_validation import validate_phone
        result = validate_phone("13800138000")
        assert result == "13800138000"

    def test_validate_phone_invalid(self):
        from core.contact_validation import validate_phone
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_phone("abc")

    def test_validate_email_valid(self):
        from core.contact_validation import validate_email
        result = validate_email("test@example.com")
        assert result == "test@example.com"

    def test_validate_email_invalid(self):
        from core.contact_validation import validate_email
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_email("not-an-email")


# ══════════════════════════════════════════════════════════════
# core/errors.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreErrors:
    def test_biz_error(self):
        from core.errors import BizError
        err = BizError("TEST", "test message", 400)
        assert err.code == "TEST"
        assert err.message == "test message"
        assert err.status == 400

    def test_not_found(self):
        from core.errors import not_found, BizError
        with pytest.raises(BizError):
            raise not_found("not found")

    def test_bad_request(self):
        from core.errors import bad_request, BizError
        with pytest.raises(BizError):
            raise bad_request("bad")

    def test_conflict(self):
        from core.errors import conflict, BizError
        with pytest.raises(BizError):
            raise conflict("conflict")

    def test_forbidden(self):
        from core.errors import forbidden, BizError
        with pytest.raises(BizError):
            raise forbidden("forbidden")


# ══════════════════════════════════════════════════════════════
# core/response.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreResponse:
    def test_success_response(self):
        from core.response import success
        result = success({"key": "val"})
        assert isinstance(result, dict)


# ══════════════════════════════════════════════════════════════
# modules/patent/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestPatentServiceFixed:
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

    @patch("modules.patent.provider.info_raw")
    def test_get_patent_detail(self, mock_info):
        mock_info.return_value = {"title": "Patent 1", "number": "CN12345678A"}
        from modules.patent.service import get_patent_detail
        result = get_patent_detail("CN12345678A")
        assert isinstance(result, dict)

    def test_get_patent_detail_no_number(self):
        from modules.patent.service import get_patent_detail
        from core.errors import BizError
        with pytest.raises(BizError):
            get_patent_detail("")


# ══════════════════════════════════════════════════════════════
# modules/patent/normalize.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestPatentNormalize:
    def test_normalize_patent_number(self):
        from modules.patent.normalize import normalize_patent_number
        result = normalize_patent_number("CN 12345678 A")
        assert isinstance(result, str)

    def test_normalize_patent_number_empty(self):
        from modules.patent.normalize import normalize_patent_number
        result = normalize_patent_number("")
        assert result == ""


# ══════════════════════════════════════════════════════════════
# modules/institution/service.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestInstitutionServiceHelpers:
    @patch("modules.institution.service.get_cursor")
    def test_search_institutions_empty(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"total": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution.service import search_institutions
        result = search_institutions("", 1, 10)
        assert isinstance(result, dict)

    @patch("modules.institution.service.get_cursor")
    def test_get_institution_not_found(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.institution.service import get_institution
        result = get_institution(999)
        assert result is None


# ══════════════════════════════════════════════════════════════
# core/middleware.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreMiddleware:
    def test_request_context_middleware_init(self):
        from core.middleware import RequestContextMiddleware
        app = MagicMock()
        middleware = RequestContextMiddleware(app)
        assert middleware is not None


# ══════════════════════════════════════════════════════════════
# core/file_token.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreFileToken:
    def test_encode_decode(self):
        from core.file_token import encode_file_token, decode_file_token
        token = encode_file_token(1, "test.pdf")
        assert isinstance(token, str)
        result = decode_file_token(token)
        assert result is not None


# ══════════════════════════════════════════════════════════════
# core/request_schemas.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreRequestSchemas:
    def test_page_params(self):
        from core.request_schemas import PageParams
        p = PageParams(page=2, pageSize=20)
        assert p.page == 2
        assert p.pageSize == 20


# ══════════════════════════════════════════════════════════════
# modules/membership/schemas.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestMembershipSchemas:
    def test_membership_read(self):
        from modules.membership.schemas import MembershipRead
        m = MembershipRead(userId=1, orgId=1, role="member", status="active", version=1)
        assert m.userId == 1


# ══════════════════════════════════════════════════════════════
# core/exception_handlers.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreExceptionHandlers:
    def test_biz_error_handler(self):
        from core.exception_handlers import biz_error_handler
        from core.errors import BizError
        from starlette.requests import Request
        from unittest.mock import AsyncMock
        request = MagicMock(spec=Request)
        exc = BizError("TEST", "test", 400)
        # biz_error_handler is a function, test it returns proper response
        result = biz_error_handler(request, exc)
        assert result.status_code == 400


# ══════════════════════════════════════════════════════════════
# core/auth_cache.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreAuthCache:
    def test_get_cached_user_miss(self):
        from core.auth_cache import get_cached_user
        result = get_cached_user(999999)
        assert result is None


# ══════════════════════════════════════════════════════════════
# core/jwt_utils.py — Additional coverage
# ══════════════════════════════════════════════════════════════

class TestCoreJwtUtils:
    def test_sign_and_verify(self):
        from core.jwt_utils import sign_access_token, decode_no_verify_exp
        token = sign_access_token({"sub": "1", "userNo": "U001", "type": "access"})
        assert isinstance(token, str)
        payload = decode_no_verify_exp(token)
        assert payload["sub"] == "1"