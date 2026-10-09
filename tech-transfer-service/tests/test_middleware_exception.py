"""
Comprehensive tests for core.middleware (identity, admin_identity, etc.)
and core.exception_handlers and core.idempotency.
"""
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest

from config import settings

# ── core.jwt_utils ──────────────────────────────────────────

class TestJwtUtils:
    def test_sign_and_decode_access_token(self):
        from core.jwt_utils import decode_token, sign_access_token
        token = sign_access_token(42, "U042", ["user", "admin"])
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["userNo"] == "U042"
        assert payload["roles"] == ["user", "admin"]
        assert payload["type"] == "access"

    def test_sign_and_decode_refresh_token(self):
        from core.jwt_utils import decode_token, sign_refresh_token
        token, jti = sign_refresh_token(42)
        assert len(jti) == 32  # uuid hex
        payload = decode_token(token)
        assert payload["sub"] == "42"
        assert payload["type"] == "refresh"
        assert payload["jti"] == jti

    def test_decode_expired_token(self):
        from core.jwt_utils import decode_no_verify_exp
        now = int(time.time())
        payload = {
            "sub": "1", "userNo": "U001", "roles": ["user"],
            "type": "access", "iat": now - 7200, "exp": now - 3600,
        }
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        # decode_no_verify_exp should succeed even though expired
        decoded = decode_no_verify_exp(token)
        assert decoded["sub"] == "1"

    def test_decode_invalid_token(self):
        from core.jwt_utils import decode_token
        with pytest.raises(jwt.InvalidTokenError):
            decode_token("invalid.token.here")

    def test_decode_wrong_secret(self):
        from core.jwt_utils import decode_token
        now = int(time.time())
        payload = {
            "sub": "1", "userNo": "U001", "roles": ["user"],
            "type": "access", "iat": now, "exp": now + 3600,
        }
        token = jwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(jwt.InvalidTokenError):
            decode_token(token)


# ── core.idempotency ────────────────────────────────────────

class TestIdempotency:
    def setup_method(self):
        from core import idempotency
        idempotency._store.clear()

    def test_cache_and_get(self):
        from core.idempotency import cache_response, get_cached
        cache_response(1, "key1", 201, {"id": 1})
        result = get_cached(1, "key1")
        assert result == (201, {"id": 1})

    def test_get_nonexistent(self):
        from core.idempotency import get_cached
        assert get_cached(1, "nokey") is None

    def test_empty_key(self):
        from core.idempotency import cache_response, get_cached
        assert get_cached(1, "") is None
        cache_response(1, "", 201, {})  # Should be no-op
        assert get_cached(1, "") is None

    def test_only_cache_success(self):
        from core.idempotency import cache_response, get_cached
        cache_response(1, "fail_key", 400, {"error": "bad"})
        assert get_cached(1, "fail_key") is None  # 4xx not cached

    def test_different_users_independent(self):
        from core.idempotency import cache_response, get_cached
        cache_response(1, "key1", 201, {"user": 1})
        cache_response(2, "key1", 201, {"user": 2})
        assert get_cached(1, "key1") == (201, {"user": 1})
        assert get_cached(2, "key1") == (201, {"user": 2})

    def test_max_entries_eviction(self):
        from core.idempotency import _MAX_ENTRIES, cache_response
        for i in range(_MAX_ENTRIES + 10):
            cache_response(1, f"key{i}", 201, {"i": i})
        from core.idempotency import _store
        assert len(_store) <= _MAX_ENTRIES

    def test_idempotent_create_no_key(self):
        from core.idempotency import idempotent_create
        mock_request = MagicMock()
        mock_request.headers = {}
        result = idempotent_create(mock_request, {"userId": 1})
        assert result is None

    def test_idempotent_create_no_user(self):
        from core.idempotency import idempotent_create
        mock_request = MagicMock()
        mock_request.headers = {"X-Idempotency-Key": "key1"}
        result = idempotent_create(mock_request, {})
        assert result is None

    def test_idempotent_create_cache_hit(self):
        from core.idempotency import cache_response, idempotent_create
        cache_response(1, "key1", 201, {"id": 1})
        mock_request = MagicMock()
        mock_request.headers = {"X-Idempotency-Key": "key1"}
        result = idempotent_create(mock_request, {"userId": 1})
        assert result is not None
        assert result.headers.get("Idempotent-Replay") == "true"

    def test_idempotent_create_cache_miss(self):
        from core.idempotency import idempotent_create
        mock_request = MagicMock()
        mock_request.headers = {"X-Idempotency-Key": "newkey"}
        result = idempotent_create(mock_request, {"userId": 1})
        assert result is None

    def test_current_key(self):
        from core.idempotency import current_key
        mock_request = MagicMock()
        mock_request.headers = {"X-Idempotency-Key": "test-key"}
        assert current_key(mock_request) == "test-key"

    def test_current_key_missing(self):
        from core.idempotency import current_key
        mock_request = MagicMock()
        mock_request.headers = {}
        assert current_key(mock_request) == ""


# ── core.middleware (identity flow) ─────────────────────────

class TestMiddlewareIdentity:
    def _make_request(self, auth_header=None):
        from starlette.requests import Request
        headers = []
        if auth_header:
            headers.append((b"authorization", auth_header.encode()))
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": b"",
            "headers": headers,
        }
        return Request(scope)

    def _make_token(self, user_id=1, roles=None, token_type="access", expired=False):
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

    def test_identity_no_header(self):
        from core.errors import BizError
        from core.middleware import identity
        req = self._make_request()
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.code == "TT_COMMON_40101"

    def test_identity_invalid_token(self):
        from core.errors import BizError
        from core.middleware import identity
        req = self._make_request("Bearer invalid.token.here")
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.code == "TT_COMMON_40102"

    def test_identity_expired_token(self):
        from core.errors import BizError
        from core.middleware import identity
        token = self._make_token(expired=True)
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.code == "TT_COMMON_40102"

    def test_identity_refresh_token_rejected(self):
        from core.errors import BizError
        from core.middleware import identity
        token = self._make_token(token_type="refresh")
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.code == "TT_COMMON_40102"

    @patch("core.middleware._user_is_active", return_value=True)
    def test_identity_valid_token(self, mock_active):
        from core.middleware import identity
        token = self._make_token(user_id=42, roles=["admin"])
        req = self._make_request(f"Bearer {token}")
        actor = identity(req)
        assert actor["userId"] == 42
        assert actor["userNo"] == "U042"
        assert actor["roles"] == ["admin"]

    @patch("core.middleware._user_is_active", return_value=False)
    def test_identity_inactive_user(self, mock_active):
        from core.errors import BizError
        from core.middleware import identity
        token = self._make_token()
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError) as exc_info:
            identity(req)
        assert exc_info.value.code == "TT_COMMON_40102"

    def test_optional_identity_no_header(self):
        from core.middleware import optional_identity
        req = self._make_request()
        actor = optional_identity(req)
        assert actor["userId"] is None
        assert actor["roles"] == []

    @patch("core.middleware._user_is_active", return_value=True)
    def test_optional_identity_with_valid_token(self, mock_active):
        from core.middleware import optional_identity
        token = self._make_token(user_id=5)
        req = self._make_request(f"Bearer {token}")
        actor = optional_identity(req)
        assert actor["userId"] == 5

    def test_identity_from_access_token_empty(self):
        from core.middleware import identity_from_access_token
        assert identity_from_access_token("") is None
        assert identity_from_access_token(None) is None
        assert identity_from_access_token("  ") is None

    def test_identity_from_access_token_invalid(self):
        from core.middleware import identity_from_access_token
        assert identity_from_access_token("invalid") is None

    def test_identity_from_access_token_refresh_type(self):
        from core.middleware import identity_from_access_token
        token = self._make_token(token_type="refresh")
        assert identity_from_access_token(token) is None

    @patch("core.middleware._user_is_active", return_value=True)
    def test_identity_from_access_token_valid(self, mock_active):
        from core.middleware import identity_from_access_token
        token = self._make_token(user_id=7)
        actor = identity_from_access_token(token)
        assert actor is not None
        assert actor["userId"] == 7

    @patch("core.middleware._user_is_active", return_value=False)
    def test_identity_from_access_token_inactive(self, mock_active):
        from core.middleware import identity_from_access_token
        token = self._make_token()
        assert identity_from_access_token(token) is None

    @patch("core.middleware._is_admin_role", return_value=True)
    @patch("core.middleware._user_is_active", return_value=True)
    def test_admin_identity_valid_admin(self, mock_active, mock_admin):
        from core.middleware import admin_identity
        token = self._make_token(user_id=99)
        req = self._make_request(f"Bearer {token}")
        actor = admin_identity(req)
        assert actor["userId"] == 99

    @patch("core.middleware._is_admin_role", return_value=False)
    @patch("core.middleware._user_is_active", return_value=True)
    def test_admin_identity_not_admin(self, mock_active, mock_admin):
        from core.errors import BizError
        from core.middleware import admin_identity
        token = self._make_token()
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError) as exc_info:
            admin_identity(req)
        assert exc_info.value.code == "TT_ADMIN_40301"

    @patch("core.middleware._org_admin_info", return_value=([1, 2], False))
    @patch("core.middleware._user_is_active", return_value=True)
    def test_org_admin_identity_valid(self, mock_active, mock_org):
        from core.middleware import org_admin_identity
        token = self._make_token(user_id=10)
        req = self._make_request(f"Bearer {token}")
        actor = org_admin_identity(req)
        assert actor["organizationAdminOrgIds"] == [1, 2]
        assert actor["isSystemAdmin"] is False

    @patch("core.middleware._org_admin_info", return_value=([], False))
    @patch("core.middleware._user_is_active", return_value=True)
    def test_org_admin_identity_not_org_admin(self, mock_active, mock_org):
        from core.errors import BizError
        from core.middleware import org_admin_identity
        token = self._make_token()
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError):
            org_admin_identity(req)

    @patch("core.middleware._org_admin_info", return_value=([], True))
    @patch("core.middleware._user_is_active", return_value=True)
    def test_backend_identity_system_admin(self, mock_active, mock_org):
        from core.middleware import backend_identity
        token = self._make_token(user_id=99)
        req = self._make_request(f"Bearer {token}")
        actor = backend_identity(req)
        assert actor["isPlatformAdmin"] is True
        assert actor["orgId"] is None

    @patch("core.middleware._org_admin_info", return_value=([5, 6], False))
    @patch("core.middleware._user_is_active", return_value=True)
    def test_backend_identity_org_admin(self, mock_active, mock_org):
        from core.middleware import backend_identity
        token = self._make_token(user_id=10)
        req = self._make_request(f"Bearer {token}")
        actor = backend_identity(req)
        assert actor["isPlatformAdmin"] is False
        assert actor["orgId"] == 5
        assert actor["orgIds"] == [5, 6]

    @patch("core.middleware._org_admin_info", return_value=([], False))
    @patch("core.middleware._user_is_active", return_value=True)
    def test_backend_identity_regular_user(self, mock_active, mock_org):
        from core.errors import BizError
        from core.middleware import backend_identity
        token = self._make_token()
        req = self._make_request(f"Bearer {token}")
        with pytest.raises(BizError):
            backend_identity(req)

    def test_payload_to_actor(self):
        from core.middleware import _payload_to_actor
        payload = {"sub": "42", "userNo": "U042", "roles": ["admin"]}
        actor = _payload_to_actor(payload)
        assert actor == {"userId": 42, "userNo": "U042", "roles": ["admin"]}

    def test_payload_to_actor_default_roles(self):
        from core.middleware import _payload_to_actor
        payload = {"sub": "1"}
        actor = _payload_to_actor(payload)
        assert actor["roles"] == ["user"]

    @pytest.mark.asyncio
    async def test_json_body_valid(self):
        import json

        from starlette.requests import Request

        from core.middleware import json_body

        body_bytes = json.dumps({"key": "value"}).encode()
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
        async def receive():
            return {"type": "http.request", "body": body_bytes, "more_body": False}
        req = Request(scope, receive=receive)
        result = await json_body(req)
        assert result == {"key": "value"}

    @pytest.mark.asyncio
    async def test_json_body_invalid(self):
        from starlette.requests import Request

        from core.middleware import json_body

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/",
            "query_string": b"",
            "headers": [(b"content-type", b"application/json")],
        }
        async def receive():
            return {"type": "http.request", "body": b"not-json", "more_body": False}
        req = Request(scope, receive=receive)
        result = await json_body(req)
        assert result == {}


# ── core.exception_handlers ─────────────────────────────────

class TestExceptionHandlers:
    def test_desensitize_upstream_body(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("Error at https://internal.corp/api")
        assert "https://internal.corp/api" not in result
        assert "[REDACTED_URL]" in result

    def test_desensitize_credentials(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("password=secret123 and api_key=sk-abc")
        assert "secret123" not in result
        assert "sk-abc" not in result

    def test_desensitize_traceback(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("Traceback (most recent call last): File test.py line 1")
        assert "Traceback" not in result
        assert "[REDACTED_TRACEBACK]" in result

    def test_desensitize_ip(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("Connected to 192.168.1.100")
        assert "192.168.1.100" not in result

    def test_desensitize_long_text(self):
        from core.exception_handlers import _desensitize_upstream_body
        long_text = "x" * 500
        result = _desensitize_upstream_body(long_text, limit=100)
        assert len(result) <= 110  # 100 + "…"

    def test_desensitize_empty(self):
        from core.exception_handlers import _desensitize_upstream_body
        assert _desensitize_upstream_body("") == ""
        assert _desensitize_upstream_body(None) == ""

    def test_safe_validation_details(self):
        from core.exception_handlers import _safe_validation_details
        errors = [
            {"loc": ["body", "username"], "msg": "field required", "input": "secret"},
            {"loc": ["body", "password"], "msg": "too short"},
        ]
        details = _safe_validation_details(errors)
        assert len(details) == 2
        # field is loc[1:] joined by ".", so ["body","username"] -> "body.username"
        assert "username" in details[0]["field"]
        assert details[0]["message"] == "field required"
        # Should NOT contain "input"
        assert "input" not in details[0]

    def test_is_path_param_error(self):
        from core.exception_handlers import _is_path_param_error
        errors = [{"loc": ["path", "id"], "msg": "not a valid int"}]
        assert _is_path_param_error(errors) is True

    def test_is_path_param_error_false(self):
        from core.exception_handlers import _is_path_param_error
        errors = [{"loc": ["body", "name"], "msg": "required"}]
        assert _is_path_param_error(errors) is False

    def test_is_path_param_error_empty(self):
        from core.exception_handlers import _is_path_param_error
        assert _is_path_param_error([]) is False

    def test_max_validation_details(self):
        from core.exception_handlers import _MAX_VALIDATION_DETAILS, _safe_validation_details
        errors = [{"loc": ["body", f"field{i}"], "msg": "err"} for i in range(30)]
        details = _safe_validation_details(errors)
        assert len(details) == _MAX_VALIDATION_DETAILS

    def test_drop_not_found_access_log_filter(self):
        from core.exception_handlers import _DropNotFoundAccessLog
        f = _DropNotFoundAccessLog()

        # 404 should be filtered
        record = MagicMock()
        record.args = ("127.0.0.1", "GET", "/nonexistent", "1.1", 404)
        assert f.filter(record) is False

        # 200 on normal path should pass
        record2 = MagicMock()
        record2.args = ("127.0.0.1", "GET", "/api/data", "1.1", 200)
        assert f.filter(record2) is True

        # Notification summary 200 should be filtered
        record3 = MagicMock()
        record3.args = ("127.0.0.1", "GET", "/me/notifications/summary", "1.1", 200)
        assert f.filter(record3) is False

        # Non-tuple args should pass
        record4 = MagicMock()
        record4.args = "simple string"
        assert f.filter(record4) is True


# ── core.rate_limit (additional tests) ──────────────────────

class TestRateLimitAdditional:
    def setup_method(self):
        from core import rate_limit
        with rate_limit._bucket_lock:
            rate_limit._buckets.clear()

    def test_check_ip_rate(self):
        from core.rate_limit import check_ip_rate
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        # Should not raise under limit
        check_ip_rate(mock_request, "test_action", limit=5, window_s=60)

    def test_check_login_rate(self):
        from core.rate_limit import check_login_rate
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        check_login_rate(mock_request)

    def test_check_register_rate(self):
        from core.rate_limit import check_register_rate
        mock_request = MagicMock()
        mock_request.client.host = "127.0.0.1"
        mock_request.headers = {}
        check_register_rate(mock_request)


# ── config module ───────────────────────────────────────────

class TestConfig:
    def test_settings_loaded(self):
        from config import settings
        assert settings.APP_ENV in ("local", "development", "staging", "production")
        assert settings.PORT > 0

    def test_is_local(self):
        from config import settings
        if settings.APP_ENV in ("local", "development"):
            assert settings.is_local is True

    def test_database_url(self):
        from config import settings
        url = settings.database_url
        assert url.startswith("postgresql://")
        assert str(settings.DB_PORT) in url

    def test_cors_origin_regex(self):
        from config import settings
        if settings.is_local:
            assert settings.cors_origin_regex is not None

    def test_file_cache_path(self):
        from config import settings
        path = settings.file_cache_path
        assert path is not None

    def test_media_root_path(self):
        from config import settings
        path = settings.media_root_path
        assert path is not None

    def test_compat_exports(self):
        import config
        assert hasattr(config, "DB_HOST")
        assert hasattr(config, "JWT_SECRET")
        assert hasattr(config, "API_PREFIX")
        assert config.API_PREFIX == "/api/tech-transfer/v1"
