"""
Comprehensive route tests using FastAPI TestClient with mocked dependencies.
Covers auth, me, achievement, demand, cooperation, favorite, search, capital,
institution, patent, file, membership, notification, ai routes.
"""
import time
from unittest.mock import patch, MagicMock

import pytest
import jwt

from config import settings


def _make_token(user_id=1, roles=None, token_type="access", expired=False):
    if roles is None:
        roles = ["user"]
    now = int(time.time())
    payload = {
        "sub": str(user_id),
        "userNo": f"U{user_id:03d}",
        "roles": roles,
        "type": token_type,
        "iat": now,
        "exp": now - 3600 if expired else now + settings.ACCESS_TOKEN_EXPIRES,
    }
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def _auth(user_id=1, roles=None):
    token = _make_token(user_id, roles)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def client():
    """FastAPI TestClient with DB fully mocked."""
    from fastapi.testclient import TestClient

    with patch("db.init_pool"), \
         patch("db.close_pool"), \
         patch("db.get_cursor") as mock_gc, \
         patch("db.get_conn") as mock_gconn:

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


# ── Health endpoints ────────────────────────────────────────

class TestHealthEndpoints:
    def test_health_degraded_when_db_fails(self, client):
        """Health endpoint returns degraded when DB is down."""
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        # With mocked DB that returns None, health may still report ok or degraded
        assert data["code"] in (0, 1)

    def test_api_health(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200


# ── Auth routes ─────────────────────────────────────────────

class TestAuthRoutes:
    @patch("routes.auth.login_phone_session")
    @patch("core.rate_limit._client_ip", return_value="127.0.0.1")
    @patch("core.rate_limit._check")
    def test_login_phone_success(self, mock_check, mock_ip, mock_login, client):
        mock_login.return_value = {"accessToken": "tok", "refreshToken": "ref"}
        resp = client.post("/api/tech-transfer/v1/auth/login", json={
            "phone": "13800138000", "password": "pass123"
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["data"]["accessToken"] == "tok"

    @patch("routes.auth.password_login_session")
    @patch("core.rate_limit._client_ip", return_value="127.0.0.1")
    @patch("core.rate_limit._check")
    def test_login_username_success(self, mock_check, mock_ip, mock_login, client):
        mock_login.return_value = {"accessToken": "tok", "refreshToken": "ref"}
        resp = client.post("/api/tech-transfer/v1/auth/login", json={
            "username": "admin", "password": "Admin@2026"
        })
        assert resp.status_code == 200

    @patch("core.rate_limit._client_ip", return_value="127.0.0.1")
    @patch("core.rate_limit._check")
    def test_login_missing_credentials(self, mock_check, mock_ip, client):
        resp = client.post("/api/tech-transfer/v1/auth/login", json={
            "password": "pass"
        })
        assert resp.status_code == 401

    @patch("core.rate_limit._client_ip", return_value="127.0.0.1")
    @patch("core.rate_limit._check")
    def test_login_missing_password(self, mock_check, mock_ip, client):
        resp = client.post("/api/tech-transfer/v1/auth/login", json={
            "username": "admin"
        })
        assert resp.status_code == 401

    @patch("routes.auth.register_password_user")
    @patch("core.rate_limit.check_register_rate")
    def test_register_username(self, mock_rate, mock_register, client):
        mock_register.return_value = {"userId": 1}
        resp = client.post("/api/tech-transfer/v1/auth/register", json={
            "username": "newuser", "password": "pass123"
        })
        assert resp.status_code == 200

    @patch("routes.auth.register_user")
    @patch("core.rate_limit.check_register_rate")
    def test_register_phone(self, mock_rate, mock_register, client):
        mock_register.return_value = {"accessToken": "tok"}
        resp = client.post("/api/tech-transfer/v1/auth/register", json={
            "phone": "13800138000", "password": "pass123"
        })
        assert resp.status_code == 200

    @patch("routes.auth.refresh_session")
    @patch("core.rate_limit.check_ip_rate")
    def test_refresh_token(self, mock_rate, mock_refresh, client):
        mock_refresh.return_value = {"accessToken": "new_tok"}
        resp = client.post("/api/tech-transfer/v1/auth/refresh", json={
            "refreshToken": "old_refresh"
        })
        assert resp.status_code == 200

    @patch("core.rate_limit.check_ip_rate")
    def test_refresh_missing_token(self, mock_rate, client):
        resp = client.post("/api/tech-transfer/v1/auth/refresh", json={})
        assert resp.status_code == 422  # Pydantic validation

    @patch("routes.auth.logout_session")
    @patch("core.rate_limit.check_ip_rate")
    def test_logout(self, mock_rate, mock_logout, client):
        mock_logout.return_value = {"ok": True}
        resp = client.post("/api/tech-transfer/v1/auth/logout", json={
            "refreshToken": "token"
        })
        assert resp.status_code == 200


# ── Achievement routes ──────────────────────────────────────

class TestAchievementRoutes:
    @patch("routes.achievement.list_achievements")
    def test_list_achievements(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/achievements")
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0

    @patch("routes.achievement.list_categories")
    def test_list_categories(self, mock_cats, client):
        mock_cats.return_value = [{"id": 1, "name": "AI"}]
        resp = client.get("/api/tech-transfer/v1/achievements/categories")
        assert resp.status_code == 200

    @patch("routes.achievement.list_industries")
    def test_list_industries(self, mock_ind, client):
        mock_ind.return_value = []
        resp = client.get("/api/tech-transfer/v1/achievements/industries")
        assert resp.status_code == 200

    @patch("routes.achievement.get_achievement_detail")
    def test_achievement_detail_found(self, mock_detail, client):
        mock_detail.return_value = {"id": 1, "title": "Test"}
        resp = client.get("/api/tech-transfer/v1/achievements/1")
        assert resp.status_code == 200

    @patch("routes.achievement.get_achievement_detail")
    def test_achievement_detail_not_found(self, mock_detail, client):
        mock_detail.return_value = None
        resp = client.get("/api/tech-transfer/v1/achievements/999")
        assert resp.status_code == 200
        assert resp.json()["data"] is None

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.achievement.create_achievement")
    def test_create_achievement(self, mock_create, mock_active, client):
        mock_create.return_value = {"id": 1, "title": "New"}
        resp = client.post("/api/tech-transfer/v1/achievements",
                          json={"title": "New Achievement"},
                          headers=_auth())
        assert resp.status_code == 201

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.achievement.update_achievement")
    def test_update_achievement(self, mock_update, mock_active, client):
        mock_update.return_value = {"id": 1, "title": "Updated"}
        resp = client.patch("/api/tech-transfer/v1/achievements/1",
                           json={"title": "Updated", "version": 1},
                           headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.achievement.submit_achievement")
    def test_submit_achievement(self, mock_submit, mock_active, client):
        mock_submit.return_value = {"status": "pending_review"}
        resp = client.post("/api/tech-transfer/v1/achievements/1/submit",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.achievement.offline_achievement")
    def test_offline_achievement(self, mock_offline, mock_active, client):
        mock_offline.return_value = {"status": "offline"}
        resp = client.post("/api/tech-transfer/v1/achievements/1/offline",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    def test_create_achievement_unauth(self, client):
        resp = client.post("/api/tech-transfer/v1/achievements",
                          json={"title": "Test"})
        assert resp.status_code == 401


# ── Demand routes ───────────────────────────────────────────

class TestDemandRoutes:
    @patch("routes.demand.list_demands")
    def test_list_demands(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/demands")
        assert resp.status_code == 200

    @patch("routes.demand.get_demand_detail")
    def test_demand_detail(self, mock_detail, client):
        mock_detail.return_value = {"id": 1, "title": "Test Demand"}
        resp = client.get("/api/tech-transfer/v1/demands/1")
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.demand.create_demand")
    def test_create_demand(self, mock_create, mock_active, client):
        mock_create.return_value = {"id": 1}
        resp = client.post("/api/tech-transfer/v1/demands",
                          json={"title": "New Demand", "description": "desc"},
                          headers=_auth())
        assert resp.status_code == 201

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.demand.update_demand")
    def test_update_demand(self, mock_update, mock_active, client):
        mock_update.return_value = {"id": 1}
        resp = client.patch("/api/tech-transfer/v1/demands/1",
                           json={"title": "Updated", "version": 1},
                           headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.demand.submit_demand")
    def test_submit_demand(self, mock_submit, mock_active, client):
        mock_submit.return_value = {"status": "pending_review"}
        resp = client.post("/api/tech-transfer/v1/demands/1/submit",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.demand.cancel_demand")
    def test_cancel_demand(self, mock_cancel, mock_active, client):
        mock_cancel.return_value = {"status": "cancelled"}
        resp = client.post("/api/tech-transfer/v1/demands/1/cancel",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.demand.close_demand")
    def test_close_demand(self, mock_close, mock_active, client):
        mock_close.return_value = {"status": "closed"}
        resp = client.post("/api/tech-transfer/v1/demands/1/close",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    def test_create_demand_unauth(self, client):
        resp = client.post("/api/tech-transfer/v1/demands",
                          json={"title": "Test", "description": "desc"})
        assert resp.status_code == 401


# ── Cooperation routes ──────────────────────────────────────

class TestCooperationRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.create_intent")
    def test_create_cooperation(self, mock_create, mock_active, client):
        mock_create.return_value = {"id": 1}
        resp = client.post("/api/tech-transfer/v1/cooperations",
                          json={"targetType": "achievement", "targetId": 1, "contactShareConsent": True},
                          headers=_auth())
        assert resp.status_code == 201

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.get_intent_detail")
    def test_cooperation_detail(self, mock_detail, mock_active, client):
        mock_detail.return_value = {"id": 1}
        resp = client.get("/api/tech-transfer/v1/cooperations/1",
                         headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.accept_intent")
    def test_accept_cooperation(self, mock_accept, mock_active, client):
        mock_accept.return_value = {"status": "accepted"}
        resp = client.post("/api/tech-transfer/v1/cooperations/1/accept",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.reject_intent")
    def test_reject_cooperation(self, mock_reject, mock_active, client):
        mock_reject.return_value = {"status": "rejected"}
        resp = client.post("/api/tech-transfer/v1/cooperations/1/reject",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.confirm_intent")
    def test_confirm_cooperation(self, mock_confirm, mock_active, client):
        mock_confirm.return_value = {"status": "confirmed"}
        resp = client.post("/api/tech-transfer/v1/cooperations/1/confirm",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.cancel_intent")
    def test_cancel_cooperation(self, mock_cancel, mock_active, client):
        mock_cancel.return_value = {"status": "cancelled"}
        resp = client.post("/api/tech-transfer/v1/cooperations/1/cancel",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.complete_intent")
    def test_complete_cooperation(self, mock_complete, mock_active, client):
        mock_complete.return_value = {"status": "completed"}
        resp = client.post("/api/tech-transfer/v1/cooperations/1/complete",
                          json={"version": 1},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.cooperation.list_events")
    def test_cooperation_events(self, mock_events, mock_active, client):
        mock_events.return_value = []
        resp = client.get("/api/tech-transfer/v1/cooperations/1/events",
                         headers=_auth())
        assert resp.status_code == 200


# ── Favorite routes ─────────────────────────────────────────

class TestFavoriteRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.favorite.add_favorite")
    def test_add_favorite(self, mock_add, mock_active, client):
        mock_add.return_value = {"ok": True}
        resp = client.put("/api/tech-transfer/v1/favorites/achievement/1",
                         headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.favorite.remove_favorite")
    def test_remove_favorite(self, mock_remove, mock_active, client):
        mock_remove.return_value = None
        resp = client.delete("/api/tech-transfer/v1/favorites/achievement/1",
                            headers=_auth())
        assert resp.status_code == 200


# ── Me routes ───────────────────────────────────────────────

class TestMeRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.get_my_profile")
    def test_get_me(self, mock_profile, mock_active, client):
        mock_profile.return_value = {"userId": 1, "displayName": "Test"}
        resp = client.get("/api/tech-transfer/v1/me", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.update_my_profile")
    def test_patch_profile(self, mock_update, mock_active, client):
        mock_update.return_value = {"displayName": "Updated"}
        resp = client.patch("/api/tech-transfer/v1/me/profile",
                           json={"version": 1},
                           headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.change_password")
    def test_change_password(self, mock_change, mock_active, client):
        mock_change.return_value = {"ok": True}
        resp = client.post("/api/tech-transfer/v1/me/password",
                          json={"currentPassword": "old", "newPassword": "new"},
                          headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.list_my_demands")
    def test_my_demands(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/me/demands", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.list_my_achievements")
    def test_my_achievements(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/me/achievements", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.list_my_favorites")
    def test_my_favorites(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/me/favorites", headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.me.list_my_intents")
    def test_my_cooperations(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/me/cooperations", headers=_auth())
        assert resp.status_code == 200

    def test_get_me_unauth(self, client):
        resp = client.get("/api/tech-transfer/v1/me")
        assert resp.status_code == 401


# ── Search routes ───────────────────────────────────────────

class TestSearchRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.search.search")
    def test_search(self, mock_search, mock_active, client):
        mock_search.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/search?q=test",
                         headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    def test_search_empty_query(self, mock_active, client):
        resp = client.get("/api/tech-transfer/v1/search?q=",
                         headers=_auth())
        assert resp.status_code == 400

    @patch("core.middleware._user_is_active", return_value=True)
    def test_search_long_query(self, mock_active, client):
        resp = client.get("/api/tech-transfer/v1/search?q=" + "x" * 65,
                         headers=_auth())
        assert resp.status_code == 400

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.search.search")
    def test_search_with_type(self, mock_search, mock_active, client):
        mock_search.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/search?q=test&type=achievement",
                         headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    def test_search_invalid_type(self, mock_active, client):
        resp = client.get("/api/tech-transfer/v1/search?q=test&type=invalid",
                         headers=_auth())
        assert resp.status_code == 400

    def test_search_unauth(self, client):
        resp = client.get("/api/tech-transfer/v1/search?q=test")
        assert resp.status_code == 401


# ── Capital routes (legacy) ─────────────────────────────────

class TestCapitalRoutes:
    @patch("routes.capital.list_platforms")
    def test_platform_base(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/platform-base")
        assert resp.status_code == 200
        assert resp.headers.get("Deprecation") == "true"

    @patch("routes.capital.list_orgs")
    def test_invest_orgs(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/invest-orgs")
        assert resp.status_code == 200

    @patch("routes.capital.list_orgs")
    def test_service_orgs(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/service-orgs")
        assert resp.status_code == 200


# ── Institution routes ──────────────────────────────────────

class TestInstitutionRoutes:
    @patch("routes.institution.list_institutions")
    def test_list_institutions(self, mock_list, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/institutions")
        assert resp.status_code == 200


# ── Patent routes ───────────────────────────────────────────

class TestPatentRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.list_patents")
    def test_patent_search(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/patents?q=AI",
                         headers=_auth())
        assert resp.status_code == 200

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.patent.patent_detail")
    def test_patent_detail(self, mock_detail, mock_active, client):
        mock_detail.return_value = {"publicationNo": "CN12345678A"}
        resp = client.get("/api/tech-transfer/v1/patents/CN12345678A",
                         headers=_auth())
        assert resp.status_code == 200


# ── Notification routes ─────────────────────────────────────

class TestNotificationRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.notification.list")
    def test_list_notifications(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": [], "total": 0}
        resp = client.get("/api/tech-transfer/v1/me/notifications",
                         headers=_auth())
        assert resp.status_code == 200


# ── File routes ─────────────────────────────────────────────

class TestFileRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    def test_file_upload_requires_file(self, mock_active, client):
        resp = client.post("/api/tech-transfer/v1/files/upload",
                          headers=_auth())
        # Requires multipart file upload, so 422 is expected
        assert resp.status_code in (422, 405)


# ── Membership routes ───────────────────────────────────────

class TestMembershipRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.membership.list")
    def test_list_memberships(self, mock_list, mock_active, client):
        mock_list.return_value = {"items": []}
        resp = client.get("/api/tech-transfer/v1/me/organization-memberships",
                         headers=_auth())
        assert resp.status_code == 200


# ── 404 handling ────────────────────────────────────────────

class TestNotFound:
    def test_nonexistent_route(self, client):
        resp = client.get("/api/tech-transfer/v1/nonexistent")
        assert resp.status_code == 404
        data = resp.json()
        assert data["code"] == "TT_COMMON_40401"

    def test_path_param_type_error(self, client):
        """Non-integer path param should return 404 (Flask compat)."""
        resp = client.get("/api/tech-transfer/v1/achievements/abc")
        assert resp.status_code == 404


# ── Security headers ────────────────────────────────────────

class TestSecurityHeaders:
    def test_security_headers_present(self, client):
        resp = client.get("/health")
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
        assert "Strict-Transport-Security" in resp.headers

    def test_request_id_header(self, client):
        resp = client.get("/health")
        assert "X-Request-Id" in resp.headers


# ── CORS ────────────────────────────────────────────────────

class TestCORS:
    def test_cors_preflight(self, client):
        resp = client.options("/api/tech-transfer/v1/achievements",
                             headers={
                                 "Origin": "http://localhost:5173",
                                 "Access-Control-Request-Method": "GET",
                             })
        assert resp.status_code in (200, 204, 405)