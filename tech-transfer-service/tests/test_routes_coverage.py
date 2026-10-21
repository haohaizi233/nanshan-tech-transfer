"""Tests for routes — coverage boost using TestClient with DB mocked."""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from config import settings

def _token(user_id=1, roles=None):
    if roles is None:
        roles = ["user"]
    now = int(time.time())
    payload = {
        "sub": str(user_id), "userNo": f"U{user_id:03d}", "roles": roles,
        "type": "access", "iat": now, "exp": now + 3600,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _auth(user_id=1, roles=None):
    return {"Authorization": f"Bearer {_token(user_id, roles)}"}


@pytest.fixture
def client():
    from fastapi.testclient import TestClient
    with patch("db.init_pool"), patch("db.close_pool"), \
         patch("db.get_cursor") as mock_gc, patch("db.get_conn") as mock_gconn:
        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_conn = MagicMock()
        mock_gconn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_gconn.return_value.__exit__ = MagicMock(return_value=False)
        from app import app
        c = TestClient(app, raise_server_exceptions=False)
        yield c


# ── routes/ai.py ────────────────────────────────────────────

class TestAiRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("modules.ai.chat_store.append_turn")
    @patch("routes.ai._forward_to_agent")
    def test_ai_chat(self, mock_chat, mock_turn, mock_active, client):
        mock_chat.return_value = {"reply": "hello", "cards": []}
        resp = client.post("/api/tech-transfer/v1/ai/chat",
                          json={"message": "hi"}, headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.list_history")
    def test_ai_chat_history(self, mock_list, mock_active, client):
        mock_list.return_value = {"messages": [], "generation": 0}
        resp = client.get("/api/tech-transfer/v1/ai/chat/messages", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.clear_messages")
    def test_ai_chat_clear(self, mock_clear, mock_active, client):
        mock_clear.return_value = 5
        resp = client.delete("/api/tech-transfer/v1/ai/chat/messages", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.create_evaluation_task")
    def test_create_evaluation(self, mock_create, mock_active, client):
        mock_create.return_value = ({"taskId": 1, "status": "queued"}, True)
        resp = client.post("/api/tech-transfer/v1/ai/evaluation-tasks",
                          json={"achievementId": 1}, headers=_auth())
        assert resp.status_code in (200, 202)

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.get_evaluation_task")
    def test_get_evaluation(self, mock_get, mock_active, client):
        mock_get.return_value = {"taskId": 1, "status": "succeeded", "evaluation": None}
        resp = client.get("/api/tech-transfer/v1/ai/evaluation-tasks/1", headers=_auth())
        assert resp.status_code == 200

    def test_ai_unauth(self, client):
        resp = client.get("/api/tech-transfer/v1/ai/chat/messages")
        assert resp.status_code in (401, 403)


# ── routes/admin.py ─────────────────────────────────────────

class TestAdminRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._org_admin_info", return_value=([], True))
    @patch("routes.admin.list_achievements_admin")
    def test_admin_achievements(self, mock_list, mock_org, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/admin/achievements", headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._org_admin_info", return_value=([], True))
    @patch("routes.admin.list_demands_admin")
    def test_admin_demands(self, mock_list, mock_org, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/admin/demands", headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._org_admin_info", return_value=([], True))
    @patch("routes.admin_ops.list_users_admin")
    def test_admin_users(self, mock_list, mock_org, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/admin/users", headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("routes.admin.review_achievement")
    def test_admin_review_achievement(self, mock_review, mock_admin, mock_active, client):
        mock_review.return_value = {"status": "published"}
        resp = client.post("/api/tech-transfer/v1/admin/achievements/1/approve",
                          json={"version": 1}, headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("routes.admin.review_demand")
    def test_admin_review_demand(self, mock_review, mock_admin, mock_active, client):
        mock_review.return_value = {"status": "published"}
        resp = client.post("/api/tech-transfer/v1/admin/demands/1/approve",
                          json={"version": 1}, headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    def test_admin_unauth(self, client):
        resp = client.get("/api/tech-transfer/v1/admin/achievements")
        assert resp.status_code == 401


# ── routes/admin_ops.py ─────────────────────────────────────

class TestAdminOpsRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("routes.admin_ops.dashboard_summary")
    def test_admin_dashboard(self, mock_dash, mock_admin, mock_active, client):
        mock_dash.return_value = {"pendingReviews": 0}
        resp = client.get("/api/tech-transfer/v1/admin/dashboard/summary", headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("routes.admin.list_audit_logs")
    def test_admin_audit_log(self, mock_list, mock_admin, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/admin/audit-logs", headers=_auth(roles=["admin"]))
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("routes.admin_ops.list_institution_registrations")
    def test_admin_institution_registrations(self, mock_list, mock_admin, mock_active, client):
        mock_list.return_value = {"list": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/admin/institution-registrations",
                         headers=_auth(roles=["admin"]))
        assert resp.status_code == 200


# ── routes/patent.py ────────────────────────────────────────

class TestPatentRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.search_patents")
    def test_patent_search(self, mock_search, mock_active, client):
        mock_search.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/patents?q=AI", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.get_patent")
    def test_patent_detail(self, mock_detail, mock_active, client):
        mock_detail.return_value = {"id": 1, "title": "Patent"}
        resp = client.get("/api/tech-transfer/v1/patents/CN12345678A", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.list_history")
    def test_patent_history(self, mock_list, mock_active, client):
        mock_list.return_value = []
        resp = client.get("/api/tech-transfer/v1/patents/search-history", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.clear_history")
    def test_patent_clear_history(self, mock_clear, mock_active, client):
        mock_clear.return_value = 0
        resp = client.delete("/api/tech-transfer/v1/patents/search-history", headers=_auth())
        assert resp.status_code == 200


# ── routes/membership.py ────────────────────────────────────

class TestMembershipRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("modules.membership.service.list_my_memberships")
    def test_list_my_memberships(self, mock_list, mock_active, client):
        mock_list.return_value = {"list": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/me/organization-memberships", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("modules.membership.service.apply_membership")
    def test_apply_membership(self, mock_apply, mock_active, client):
        mock_apply.return_value = {"id": 1, "status": "pending"}
        resp = client.post("/api/tech-transfer/v1/me/organization-membership-applications",
                          json={"orgId": 1}, headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("modules.membership.service.cancel_membership_application")
    def test_cancel_membership(self, mock_cancel, mock_active, client):
        mock_cancel.return_value = {"status": "cancelled"}
        resp = client.post("/api/tech-transfer/v1/me/organization-membership-applications/1/cancel",
                          json={"version": 1}, headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("modules.membership.service.get_my_organization_certification")
    def test_get_certification(self, mock_cert, mock_active, client):
        mock_cert.return_value = {"status": "unverified"}
        resp = client.get("/api/tech-transfer/v1/me/organization-certification", headers=_auth())
        assert resp.status_code == 200


# ── routes/institution.py ───────────────────────────────────

class TestInstitutionRoutes:
    @patch("modules.institution.service.list_institutions")
    def test_list_institutions(self, mock_list, client):
        mock_list.return_value = {"list": [], "total": 0, "page": 1, "pageSize": 10, "totalPages": 0}
        resp = client.get("/api/tech-transfer/v1/institutions")
        assert resp.status_code == 200

    @patch("modules.institution.service.get_institution_detail")
    def test_institution_detail(self, mock_detail, client):
        mock_detail.return_value = {"id": "1", "name": "Test"}
        resp = client.get("/api/tech-transfer/v1/institutions/1")
        assert resp.status_code == 200

    @patch("modules.institution.service.get_institution_detail")
    def test_institution_not_found(self, mock_detail, client):
        mock_detail.return_value = None
        resp = client.get("/api/tech-transfer/v1/institutions/999")
        assert resp.status_code == 200


# ── routes/notification.py ──────────────────────────────────

class TestNotificationRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.summary")
    def test_notification_summary(self, mock_sum, mock_active, client):
        mock_sum.return_value = {"total": 0, "categories": {}}
        resp = client.get("/api/tech-transfer/v1/me/notifications/summary", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.list_notifications")
    def test_notification_list(self, mock_list, mock_active, client):
        mock_list.return_value = {"total": 0, "list": []}
        resp = client.get("/api/tech-transfer/v1/me/notifications", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.mark_all_read")
    def test_mark_all_read(self, mock_mark, mock_active, client):
        mock_mark.return_value = {"updated": 5}
        resp = client.post("/api/tech-transfer/v1/me/notifications/read-all", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.mark_notification_read")
    def test_mark_read(self, mock_mark, mock_active, client):
        mock_mark.return_value = {"updated": 1}
        resp = client.post("/api/tech-transfer/v1/me/notifications/1/read", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.mark_read")
    def test_mark_category_read(self, mock_mark, mock_active, client):
        mock_mark.return_value = {"updated": 3}
        resp = client.post("/api/tech-transfer/v1/me/notifications/read", json={"category": "review"}, headers=_auth())
        assert resp.status_code == 200


# ── routes/capital.py (no prefix, uses full paths) ──────────

class TestCapitalRoutes:
    @patch("modules.capital.service.list_platforms")
    def test_list_platforms(self, mock_list, client):
        mock_list.return_value = {"list": [], "total": 0, "page": 1, "pageSize": 10, "totalPages": 0}
        resp = client.get("/api/platform-base")
        assert resp.status_code == 200

    @patch("modules.capital.service.list_orgs")
    def test_list_invest_orgs(self, mock_list, client):
        mock_list.return_value = {"list": [], "total": 0, "page": 1, "pageSize": 10, "totalPages": 0}
        resp = client.get("/api/invest-orgs")
        assert resp.status_code == 200

    @patch("modules.capital.service.list_orgs")
    def test_list_service_orgs(self, mock_list, client):
        mock_list.return_value = {"list": [], "total": 0, "page": 1, "pageSize": 10, "totalPages": 0}
        resp = client.get("/api/service-orgs")
        assert resp.status_code == 200


# ── routes/file.py ──────────────────────────────────────────

class TestFileRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.file.create_uploaded_file")
    def test_file_upload(self, mock_upload, mock_active, client):
        mock_upload.return_value = {"id": 1, "name": "test.pdf"}
        resp = client.post("/api/tech-transfer/v1/files",
                          files={"file": ("test.pdf", b"%PDF-1.4", "application/pdf")},
                          headers=_auth())
        assert resp.status_code == 201

    def test_file_upload_unauth(self, client):
        resp = client.post("/api/tech-transfer/v1/files")
        assert resp.status_code == 401

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("core.middleware._org_admin_info", return_value=([], True))
    @patch("routes.file.get_uploaded_file")
    def test_file_download(self, mock_get, mock_org, mock_active, client):
        import tempfile, os
        tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
        tmp.write(b"%PDF-1.4 test content")
        tmp.close()
        try:
            mock_get.return_value = (tmp.name, "application/pdf", "test.pdf")
            resp = client.get("/api/tech-transfer/v1/files/1", headers=_auth())
            assert resp.status_code == 200
        finally:
            os.unlink(tmp.name)

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.file.delete_uploaded_file")
    def test_file_delete(self, mock_del, mock_active, client):
        mock_del.return_value = None
        resp = client.delete("/api/tech-transfer/v1/files/1", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.file.generate_file_token")
    def test_file_token(self, mock_gen, mock_active, client):
        mock_gen.return_value = "abc123"
        resp = client.post("/api/tech-transfer/v1/files/1/token", headers=_auth())
        assert resp.status_code == 200


# ── routes/institution_registration.py ──────────────────────

class TestInstitutionRegistrationRoutes:
    @patch("core.rate_limit.check_register_rate")
    @patch("routes.institution_registration.create_institution_registration")
    def test_submit_registration(self, mock_create, mock_rate, client):
        mock_create.return_value = {"applicationId": 1, "status": "pending", "version": 1, "username": "testuser"}
        resp = client.post("/api/tech-transfer/v1/institution-registrations",
                          json={
                              "kind": "enterprise",
                              "name": "Test Corp",
                              "contactName": "张三",
                              "contactPhone": "13800138000",
                              "username": "testuser",
                              "password": "Test@12345",
                          })
        assert resp.status_code == 201
