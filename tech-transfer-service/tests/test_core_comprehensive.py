"""
Comprehensive tests for core modules:
- core.errors (BizError, all error codes, convenience constructors)
- core.response (success, error, request_id)
- core.password (hash_password, verify_password)
- core.masking (mask_name, mask_phone, mask_email, mask_wechat, mask_contact)
- core.contact_validation (all validators)
- core.pagination (parse_page_args)
- core.request_schemas (all Pydantic models)
"""

import pytest

# ── core.errors ─────────────────────────────────────────────

class TestBizError:
    def test_init(self):
        from core.errors import BizError
        e = BizError("CODE_1", "message", 400, {"detail": "x"})
        assert e.code == "CODE_1"
        assert e.message == "message"
        assert e.http_status == 400
        assert e.details == {"detail": "x"}

    def test_str(self):
        from core.errors import BizError
        e = BizError("CODE_1", "hello")
        assert str(e) == "[CODE_1] hello"

    def test_defaults(self):
        from core.errors import BizError
        e = BizError("C", "m")
        assert e.http_status == 400
        assert e.details is None


class TestErrorCodes:
    """All error code tuples exist and have 3 elements."""

    def test_common_codes(self):
        from core.errors import (
            TT_COMMON_40001,
            TT_COMMON_40101,
            TT_COMMON_40102,
            TT_COMMON_40301,
            TT_COMMON_40401,
            TT_COMMON_40402,
            TT_COMMON_40501,
            TT_COMMON_40901,
            TT_COMMON_40902,
            TT_COMMON_40903,
            TT_COMMON_42201,
            TT_COMMON_42901,
            TT_COMMON_50001,
            TT_COMMON_50301,
        )
        for code in [TT_COMMON_40001, TT_COMMON_40101, TT_COMMON_40102,
                     TT_COMMON_40301, TT_COMMON_40401, TT_COMMON_40402,
                     TT_COMMON_40901, TT_COMMON_40902, TT_COMMON_42901,
                     TT_COMMON_50001, TT_COMMON_40501, TT_COMMON_42201,
                     TT_COMMON_40903, TT_COMMON_50301]:
            assert len(code) == 3
            assert code[0].startswith("TT_")

    def test_auth_codes(self):
        from core.errors import TT_AUTH_40103, TT_AUTH_40104, TT_AUTH_40105, TT_AUTH_40106, TT_AUTH_40901
        for code in [TT_AUTH_40103, TT_AUTH_40104, TT_AUTH_40105, TT_AUTH_40106, TT_AUTH_40901]:
            assert len(code) == 3

    def test_domain_codes(self):
        from core.errors import (
            TT_ACH_40301,
            TT_ACH_40401,
            TT_ACH_40901,
            TT_ADMIN_40001,
            TT_ADMIN_40301,
            TT_AI_40301,
            TT_AI_40401,
            TT_AI_42901,
            TT_AI_50201,
            TT_AI_50301,
            TT_COOP_40001,
            TT_COOP_40301,
            TT_COOP_40401,
            TT_COOP_40901,
            TT_COOP_40902,
            TT_DMD_40301,
            TT_DMD_40401,
            TT_DMD_40901,
            TT_FAV_40401,
            TT_FILE_40001,
            TT_FILE_40401,
            TT_FILE_50201,
            TT_INST_40001,
            TT_INST_40401,
            TT_INST_40901,
            TT_INST_REG_40001,
            TT_INST_REG_40401,
            TT_INST_REG_40901,
            TT_INST_REG_40902,
            TT_PATENT_40401,
            TT_PATENT_50201,
            TT_PATENT_50301,
        )
        codes = [TT_ACH_40301, TT_ACH_40401, TT_ACH_40901,
                 TT_DMD_40301, TT_DMD_40401, TT_DMD_40901,
                 TT_COOP_40001, TT_COOP_40301, TT_COOP_40401, TT_COOP_40901, TT_COOP_40902,
                 TT_FAV_40401,
                 TT_AI_40301, TT_AI_40401, TT_AI_42901, TT_AI_50201, TT_AI_50301,
                 TT_ADMIN_40301, TT_ADMIN_40001,
                 TT_INST_40001, TT_INST_40401, TT_INST_40901,
                 TT_INST_REG_40001, TT_INST_REG_40901, TT_INST_REG_40401, TT_INST_REG_40902,
                 TT_PATENT_40401, TT_PATENT_50201, TT_PATENT_50301,
                 TT_FILE_40001, TT_FILE_40401, TT_FILE_50201]
        for code in codes:
            assert len(code) == 3


class TestConvenienceConstructors:
    def test_bad_request(self):
        from core.errors import bad_request
        e = bad_request("custom msg")
        assert e.code == "TT_COMMON_40001"
        assert e.message == "custom msg"
        assert e.http_status == 400

    def test_unauthorized(self):
        from core.errors import unauthorized
        e = unauthorized()
        assert e.code == "TT_COMMON_40101"

    def test_bootstrap_credential_invalid(self):
        from core.errors import bootstrap_credential_invalid
        e = bootstrap_credential_invalid()
        assert e.code == "TT_AUTH_40103"

    def test_conflict(self):
        from core.errors import conflict
        e = conflict()
        assert e.code == "TT_COMMON_40902"

    def test_not_found(self):
        from core.errors import not_found
        e = not_found()
        assert e.code == "TT_COMMON_40402"

    def test_demand_not_found(self):
        from core.errors import demand_not_found
        e = demand_not_found()
        assert e.code == "TT_DMD_40401"

    def test_achievement_not_found(self):
        from core.errors import achievement_not_found
        e = achievement_not_found()
        assert e.code == "TT_ACH_40401"

    def test_achievement_forbidden(self):
        from core.errors import achievement_forbidden
        e = achievement_forbidden()
        assert e.code == "TT_ACH_40301"

    def test_achievement_conflict(self):
        from core.errors import achievement_conflict
        e = achievement_conflict()
        assert e.code == "TT_ACH_40901"

    def test_demand_forbidden(self):
        from core.errors import demand_forbidden
        e = demand_forbidden()
        assert e.code == "TT_DMD_40301"

    def test_demand_conflict(self):
        from core.errors import demand_conflict
        e = demand_conflict()
        assert e.code == "TT_DMD_40901"

    def test_favorite_not_found(self):
        from core.errors import favorite_not_found
        e = favorite_not_found()
        assert e.code == "TT_FAV_40401"

    def test_coop_bad_request(self):
        from core.errors import coop_bad_request
        e = coop_bad_request()
        assert e.code == "TT_COOP_40001"

    def test_coop_forbidden(self):
        from core.errors import coop_forbidden
        e = coop_forbidden()
        assert e.code == "TT_COOP_40301"

    def test_coop_not_found(self):
        from core.errors import coop_not_found
        e = coop_not_found()
        assert e.code == "TT_COOP_40401"

    def test_coop_conflict(self):
        from core.errors import coop_conflict
        e = coop_conflict()
        assert e.code == "TT_COOP_40901"

    def test_coop_active_exists(self):
        from core.errors import coop_active_exists
        e = coop_active_exists()
        assert e.code == "TT_COOP_40902"

    def test_forbidden(self):
        from core.errors import forbidden
        e = forbidden()
        assert e.code == "TT_COMMON_40301"

    def test_ai_unavailable(self):
        from core.errors import ai_unavailable
        e = ai_unavailable()
        assert e.code == "TT_AI_50301"

    def test_ai_provider_failed_safe(self):
        from core.errors import ai_provider_failed
        e = ai_provider_failed("some generic error")
        assert e.code == "TT_AI_50201"
        assert e.message == "some generic error"

    def test_ai_provider_failed_redacts_sensitive(self):
        from core.errors import ai_provider_failed
        e = ai_provider_failed("provider qwen returned error")
        assert e.message == "AI 服务暂时不可用，请稍后重试"

    def test_ai_provider_failed_redacts_url(self):
        from core.errors import ai_provider_failed
        e = ai_provider_failed("https://api.example.com failed")
        assert e.message == "AI 服务暂时不可用，请稍后重试"

    def test_ai_provider_failed_redacts_key(self):
        from core.errors import ai_provider_failed
        e = ai_provider_failed("api_key=sk-1234 invalid")
        assert e.message == "AI 服务暂时不可用，请稍后重试"

    def test_ai_provider_failed_none_msg(self):
        from core.errors import ai_provider_failed
        e = ai_provider_failed(None)
        assert e.message == "AI 服务暂时不可用，请稍后重试"

    def test_patent_not_found(self):
        from core.errors import patent_not_found
        e = patent_not_found()
        assert e.code == "TT_PATENT_40401"

    def test_patent_unavailable(self):
        from core.errors import patent_unavailable
        e = patent_unavailable()
        assert e.code == "TT_PATENT_50301"

    def test_patent_provider_failed(self):
        from core.errors import patent_provider_failed
        e = patent_provider_failed()
        assert e.code == "TT_PATENT_50201"

    def test_file_upstream_error(self):
        from core.errors import file_upstream_error
        e = file_upstream_error()
        assert e.code == "TT_FILE_50201"


# ── core.response ───────────────────────────────────────────

class TestResponse:
    def test_success_default(self):
        from core.response import set_request_id, success
        set_request_id("test-req-123")
        result = success({"id": 1})
        assert result["code"] == 0
        assert result["message"] == "ok"
        assert result["data"] == {"id": 1}
        assert result["requestId"] == "test-req-123"

    def test_success_custom_message(self):
        from core.response import set_request_id, success
        set_request_id("test-req-456")
        result = success(None, "created")
        assert result["message"] == "created"
        assert result["data"] is None

    def test_error(self):
        from core.response import error, set_request_id
        set_request_id("test-req-789")
        resp = error("ERR_CODE", "error msg", 400)
        assert resp.status_code == 400

    def test_error_with_details(self):
        from core.response import error, set_request_id
        set_request_id("test-req-abc")
        resp = error("ERR_CODE", "error msg", 422, details=[{"field": "x"}])
        assert resp.status_code == 422

    def test_set_get_request_id(self):
        from core.response import get_request_id, set_request_id
        set_request_id("req-xyz")
        assert get_request_id() == "req-xyz"

    def test_get_request_id_default(self):
        from core.response import get_request_id
        # When no request_id is set, returns a uuid
        rid = get_request_id()
        assert isinstance(rid, str)
        assert len(rid) > 0


# ── core.password ───────────────────────────────────────────

class TestPassword:
    def test_hash_and_verify(self):
        from core.password import hash_password, verify_password
        hashed = hash_password("mypassword")
        assert verify_password("mypassword", hashed) is True

    def test_wrong_password(self):
        from core.password import hash_password, verify_password
        hashed = hash_password("correct")
        assert verify_password("wrong", hashed) is False

    def test_hash_format(self):
        from core.password import hash_password
        hashed = hash_password("test")
        parts = hashed.split("$")
        assert len(parts) == 4
        assert parts[0] == "pbkdf2_sha256"
        assert parts[1] == "200000"

    def test_different_hashes(self):
        from core.password import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # Different salts

    def test_malformed_stored(self):
        from core.password import verify_password
        assert verify_password("pwd", "bad-format") is False
        assert verify_password("pwd", "") is False
        assert verify_password("pwd", "wrong$algo$salt$hash") is False

    def test_empty_password(self):
        from core.password import hash_password, verify_password
        hashed = hash_password("")
        assert verify_password("", hashed) is True
        assert verify_password("not-empty", hashed) is False


# ── core.masking ────────────────────────────────────────────

class TestMasking:
    def test_mask_name_normal(self):
        from core.masking import mask_name
        assert mask_name("李经理") == "李**"

    def test_mask_name_single_char(self):
        from core.masking import mask_name
        assert mask_name("李") == "李**"

    def test_mask_name_empty(self):
        from core.masking import mask_name
        assert mask_name("") is None
        assert mask_name(None) is None

    def test_mask_phone_normal(self):
        from core.masking import mask_phone
        assert mask_phone("13912342222") == "139****2222"

    def test_mask_phone_short(self):
        from core.masking import mask_phone
        assert mask_phone("123") == "123"

    def test_mask_phone_empty(self):
        from core.masking import mask_phone
        assert mask_phone("") is None
        assert mask_phone(None) is None

    def test_mask_email_normal(self):
        from core.masking import mask_email
        assert mask_email("li@jm-green.com") == "l****@jm-green.com"

    def test_mask_email_short_local(self):
        from core.masking import mask_email
        result = mask_email("a@b.com")
        assert result == "a****@b.com"

    def test_mask_email_no_at(self):
        from core.masking import mask_email
        assert mask_email("not-an-email") is None

    def test_mask_email_empty(self):
        from core.masking import mask_email
        assert mask_email("") is None
        assert mask_email(None) is None

    def test_mask_wechat_normal(self):
        from core.masking import mask_wechat
        assert mask_wechat("jm_green_li") == "jm****i"

    def test_mask_wechat_short(self):
        from core.masking import mask_wechat
        assert mask_wechat("ab") == "**"
        assert mask_wechat("abc") == "***"

    def test_mask_wechat_empty(self):
        from core.masking import mask_wechat
        assert mask_wechat("") is None
        assert mask_wechat(None) is None

    def test_mask_contact(self):
        from core.masking import mask_contact
        contact = {
            "contactName": "张三",
            "contactTitle": "经理",
            "contactPhone": "13800138000",
            "contactEmail": "zhang@test.com",
            "contactWechat": "zhangsan_wx",
        }
        result = mask_contact(contact)
        assert result["contactName"] == "张**"
        assert result["contactTitle"] == "经理"  # Not masked
        assert result["contactPhone"] == "138****8000"
        assert result["contactEmail"] == "zh****@test.com"
        assert result["contactWechat"] == "zh****x"


# ── core.contact_validation ─────────────────────────────────

class TestContactValidation:
    def test_is_valid_phone(self):
        from core.contact_validation import is_valid_phone
        assert is_valid_phone("13800138000") is True
        assert is_valid_phone("12345678901") is True
        assert is_valid_phone("123") is False
        assert is_valid_phone("") is False
        assert is_valid_phone(None) is False
        assert is_valid_phone("abcdefghijk") is False

    def test_is_valid_email(self):
        from core.contact_validation import is_valid_email
        assert is_valid_email("test@example.com") is True
        assert is_valid_email("a@b.c") is True
        assert is_valid_email("invalid") is False
        assert is_valid_email("") is False
        assert is_valid_email(None) is False

    def test_is_valid_contact_way(self):
        from core.contact_validation import is_valid_contact_way
        assert is_valid_contact_way("0755-12345678") is True
        assert is_valid_contact_way("12345") is True
        assert is_valid_contact_way("abc") is False
        assert is_valid_contact_way("") is False

    def test_normalize_contact(self):
        from core.contact_validation import normalize_contact
        assert normalize_contact(None) == ""
        assert normalize_contact("  hello  ") == "hello"
        assert normalize_contact(123) == "123"

    def test_validate_phone_optional_empty(self):
        from core.contact_validation import validate_phone
        assert validate_phone("") is None
        assert validate_phone(None) is None

    def test_validate_phone_required_empty(self):
        from core.contact_validation import validate_phone
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_phone("", required=True)

    def test_validate_phone_valid(self):
        from core.contact_validation import validate_phone
        assert validate_phone("13800138000") == "13800138000"

    def test_validate_phone_invalid(self):
        from core.contact_validation import validate_phone
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_phone("123")

    def test_validate_email_optional_empty(self):
        from core.contact_validation import validate_email
        assert validate_email("") is None
        assert validate_email(None) is None

    def test_validate_email_required_empty(self):
        from core.contact_validation import validate_email
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_email("", required=True)

    def test_validate_email_valid(self):
        from core.contact_validation import validate_email
        assert validate_email("a@b.c") == "a@b.c"

    def test_validate_email_invalid(self):
        from core.contact_validation import validate_email
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_email("not-email")

    def test_validate_contact_way_optional_empty(self):
        from core.contact_validation import validate_contact_way
        assert validate_contact_way("") == ""
        assert validate_contact_way(None) == ""

    def test_validate_contact_way_required_empty(self):
        from core.contact_validation import validate_contact_way
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_contact_way("", required=True)

    def test_validate_contact_way_valid(self):
        from core.contact_validation import validate_contact_way
        assert validate_contact_way("0755-12345678") == "0755-12345678"

    def test_validate_contact_way_invalid(self):
        from core.contact_validation import validate_contact_way
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_contact_way("abc")

    def test_validate_contact_way_too_long(self):
        from core.contact_validation import validate_contact_way
        from core.errors import BizError
        with pytest.raises(BizError):
            validate_contact_way("1" * 65)


# ── core.pagination ─────────────────────────────────────────

class TestPagination:
    def _make_request(self, query_string=""):
        from starlette.requests import Request
        scope = {
            "type": "http",
            "method": "GET",
            "path": "/",
            "query_string": query_string.encode(),
            "headers": [],
        }
        return Request(scope)

    def test_defaults(self):
        from core.pagination import parse_page_args
        req = self._make_request()
        page, page_size, keyword = parse_page_args(req)
        assert page == 1
        assert page_size == 10
        assert keyword == ""

    def test_custom_values(self):
        from core.pagination import parse_page_args
        req = self._make_request("page=3&pageSize=20&keyword=test")
        page, page_size, keyword = parse_page_args(req)
        assert page == 3
        assert page_size == 20
        assert keyword == "test"

    def test_clamp_page_size(self):
        from core.pagination import parse_page_args
        req = self._make_request("pageSize=100")
        _, page_size, _ = parse_page_args(req)
        assert page_size == 50  # max

    def test_min_page(self):
        from core.pagination import parse_page_args
        req = self._make_request("page=-1")
        page, _, _ = parse_page_args(req)
        assert page == 1

    def test_invalid_page(self):
        from core.pagination import parse_page_args
        req = self._make_request("page=abc")
        page, _, _ = parse_page_args(req)
        assert page == 1

    def test_invalid_page_size(self):
        from core.pagination import parse_page_args
        req = self._make_request("pageSize=xyz")
        _, page_size, _ = parse_page_args(req)
        assert page_size == 10


# ── core.request_schemas ────────────────────────────────────

class TestRequestSchemas:
    def test_request_body_as_dict(self):
        from core.request_schemas import RequestBody
        body = RequestBody(extra_field="value")
        d = body.as_dict()
        assert d["extra_field"] == "value"

    def test_version_body(self):
        from core.request_schemas import VersionBody
        body = VersionBody(version=5)
        assert body.version == 5

    def test_login_request(self):
        from core.request_schemas import LoginRequest
        body = LoginRequest(username="admin", password="pass123")
        d = body.as_dict()
        assert d["username"] == "admin"
        assert d["password"] == "pass123"

    def test_login_request_phone(self):
        from core.request_schemas import LoginRequest
        body = LoginRequest(phone="13800138000", password="pass")
        d = body.as_dict()
        assert d["phone"] == "13800138000"

    def test_register_request(self):
        from core.request_schemas import RegisterRequest
        body = RegisterRequest(username="newuser", password="pass123")
        d = body.as_dict()
        assert d["username"] == "newuser"

    def test_register_request_phone(self):
        from core.request_schemas import RegisterRequest
        body = RegisterRequest(phone="13800138000", password="pass", displayName="Test")
        d = body.as_dict()
        assert d["phone"] == "13800138000"
        assert d["displayName"] == "Test"

    def test_bootstrap_request(self):
        from core.request_schemas import BootstrapRequest
        body = BootstrapRequest(hostCredential="some-cred")
        assert body.hostCredential == "some-cred"

    def test_refresh_token_request(self):
        from core.request_schemas import RefreshTokenRequest
        body = RefreshTokenRequest(refreshToken="token123")
        assert body.refreshToken == "token123"

    def test_profile_update_request(self):
        from core.request_schemas import ProfileUpdateRequest
        body = ProfileUpdateRequest(version=1, displayName="New Name")
        d = body.as_dict()
        assert d["displayName"] == "New Name"
        assert d["version"] == 1

    def test_change_password_request(self):
        from core.request_schemas import ChangePasswordRequest
        body = ChangePasswordRequest(currentPassword="old", newPassword="new")
        assert body.currentPassword == "old"
        assert body.newPassword == "new"

    def test_achievement_create_request(self):
        from core.request_schemas import AchievementCreateRequest
        body = AchievementCreateRequest(title="Test Achievement")
        d = body.as_dict()
        assert d["title"] == "Test Achievement"

    def test_demand_create_request(self):
        from core.request_schemas import DemandCreateRequest
        body = DemandCreateRequest(title="Test Demand", description="desc")
        d = body.as_dict()
        assert d["title"] == "Test Demand"
        assert d["description"] == "desc"

    def test_cooperation_create_request(self):
        from core.request_schemas import CooperationCreateRequest
        body = CooperationCreateRequest(targetType="achievement", targetId=1, contactShareConsent=True)
        d = body.as_dict()
        assert d["targetType"] == "achievement"
        assert d["targetId"] == 1
        assert d["contactShareConsent"] is True

    def test_institution_registration_request(self):
        from core.request_schemas import InstitutionRegistrationRequest
        body = InstitutionRegistrationRequest(
            kind="enterprise", name="Test Corp", contactName="Zhang",
            contactPhone="13800138000", username="testuser", password="pass123"
        )
        d = body.as_dict()
        assert d["name"] == "Test Corp"

    def test_ai_chat_request(self):
        from core.request_schemas import AiChatRequest
        body = AiChatRequest(message="hello")
        assert body.message == "hello"

    def test_ai_match_request(self):
        from core.request_schemas import AiMatchRequest
        body = AiMatchRequest(demandId=42)
        assert body.demandId == 42

    def test_patent_search_history_request(self):
        from core.request_schemas import PatentSearchHistoryRequest
        body = PatentSearchHistoryRequest(mode="keyword", keyword="AI")
        assert body.mode == "keyword"
        assert body.keyword == "AI"

    def test_review_reject_request(self):
        from core.request_schemas import ReviewRejectRequest
        body = ReviewRejectRequest(version=1, reason="not good enough")
        assert body.reason == "not good enough"

    def test_evaluation_task_request(self):
        from core.request_schemas import EvaluationTaskRequest
        body = EvaluationTaskRequest(achievementId=5)
        assert body.achievementId == 5

    def test_notification_read_request(self):
        from core.request_schemas import NotificationReadRequest
        body = NotificationReadRequest(category="cooperation")
        assert body.category == "cooperation"

    def test_inventor_ref(self):
        from core.request_schemas import InventorRef
        body = InventorRef(name="Dr. Smith", orgName="MIT")
        assert body.name == "Dr. Smith"
        assert body.orgName == "MIT"

    def test_media_item(self):
        from core.request_schemas import MediaItem
        body = MediaItem(fileId=42, role="image")
        assert body.fileId == 42
        assert body.role == "image"
