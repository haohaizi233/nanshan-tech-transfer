"""Tests for achievement/content.py, achievement/extract.py, file/service.py,
core/middleware.py, core/rate_limit.py, core/exception_handlers.py, config.py, app.py,
achievement/service.py helpers."""
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError


def _mock_cur_ctx(mock_cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ── achievement/content.py ──────────────────────────────────

class TestAchievementContent:
    def test_section_codes(self):
        from modules.achievement.content import SECTION_CODES
        assert "innovation" in SECTION_CODES
        assert "technical_route" in SECTION_CODES

    def test_link_types(self):
        from modules.achievement.content import LINK_TYPES
        assert "official_site" in LINK_TYPES

    def test_media_roles(self):
        from modules.achievement.content import MEDIA_ROLES
        assert "cover" in MEDIA_ROLES

    def test_supports_internal_patent_lookup_true(self):
        from modules.achievement.content import supports_internal_patent_lookup
        assert supports_internal_patent_lookup("CN12345678A") is True

    def test_supports_internal_patent_lookup_false(self):
        from modules.achievement.content import supports_internal_patent_lookup
        assert supports_internal_patent_lookup("") is False
        assert supports_internal_patent_lookup(None) is False

    def test_text_valid(self):
        from modules.achievement.content import _text
        assert _text("hello", "f", 100) == "hello"

    def test_text_strips(self):
        from modules.achievement.content import _text
        assert _text("  hello  ", "f", 100) == "hello"

    def test_text_empty(self):
        from modules.achievement.content import _text
        assert _text("", "f", 100) is None

    def test_text_none(self):
        from modules.achievement.content import _text
        assert _text(None, "f", 100) is None

    def test_text_required_empty(self):
        from modules.achievement.content import _text
        with pytest.raises(BizError):
            _text("", "f", 100, required=True)

    def test_text_too_long(self):
        from modules.achievement.content import _text
        with pytest.raises(BizError):
            _text("x" * 101, "f", 100)

    def test_sort_order_valid(self):
        from modules.achievement.content import _sort_order
        assert _sort_order(5, "f", 0) == 5
        assert _sort_order(None, "f", 3) == 3

    def test_sort_order_string(self):
        from modules.achievement.content import _sort_order
        assert _sort_order("7", "f", 0) == 7

    def test_sort_order_invalid(self):
        from modules.achievement.content import _sort_order
        with pytest.raises(BizError):
            _sort_order("abc", "f", 0)

    def test_sort_order_negative(self):
        from modules.achievement.content import _sort_order
        with pytest.raises(BizError):
            _sort_order(-1, "f", 0)

    def test_sort_order_too_large(self):
        from modules.achievement.content import _sort_order
        with pytest.raises(BizError):
            _sort_order(10001, "f", 0)

    def test_sort_order_bool(self):
        from modules.achievement.content import _sort_order
        with pytest.raises(BizError):
            _sort_order(True, "f", 0)

    def test_parse_content_empty(self):
        from modules.achievement.content import parse_content_payload
        assert parse_content_payload({}) == {}

    def test_parse_content_tags(self):
        from modules.achievement.content import parse_content_payload
        result = parse_content_payload({"tags": ["AI", "ML"]})
        assert result["tags"] == ["AI", "ML"]

    def test_parse_content_tags_dedup(self):
        from modules.achievement.content import parse_content_payload
        result = parse_content_payload({"tags": ["AI", "AI"]})
        assert result["tags"] == ["AI"]

    def test_parse_content_tags_too_many(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({"tags": [f"t{i}" for i in range(21)]})

    def test_parse_content_legacy_media(self):
        from modules.achievement.content import parse_content_payload
        result = parse_content_payload({"mediaFileIds": [10, 20]})
        assert "media" in result
        assert len(result["media"]) == 2

    def test_parse_content_media_conflict(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({"media": [], "mediaFileIds": [1]})

    def test_parse_content_sections(self):
        from modules.achievement.content import parse_content_payload
        result = parse_content_payload({
            "sections": [{"code": "innovation", "title": "创新点", "content": "test"}]
        })
        assert len(result["sections"]) == 1

    def test_section_code_validation(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({
                "sections": [{"code": "invalid_code", "title": "T", "content": "C"}]
            })

    def test_media_role_validation(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({
                "media": [{"fileId": 1, "role": "invalid_role"}]
            })

    def test_media_missing_file_id(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({
                "media": [{"role": "cover"}]
            })

    def test_section_missing_content(self):
        from modules.achievement.content import parse_content_payload
        with pytest.raises(BizError):
            parse_content_payload({
                "sections": [{"code": "innovation", "title": "T"}]
            })

    def test_load_content(self):
        from modules.achievement.content import load_content
        cur = MagicMock()
        cur.fetchall.return_value = []
        result = load_content(cur, 1)
        assert isinstance(result, dict)


# ── achievement/extract.py ──────────────────────────────────

class TestAchievementExtract:
    def test_clean_label(self):
        from modules.achievement.extract import clean_label
        assert clean_label("  hello  ") == "hello"
        assert clean_label("") == ""

    def test_parse_labeled_line(self):
        from modules.achievement.extract import parse_labeled_line
        label, value = parse_labeled_line("名称: Test Corp")
        assert label is not None
        assert "Test Corp" in value

    def test_map_maturity(self):
        from modules.achievement.extract import map_maturity
        result = map_maturity("实验室验证")
        assert isinstance(result, str)

    def test_map_pricing(self):
        from modules.achievement.extract import map_pricing
        result = map_pricing("面议")
        assert isinstance(result, str)

    def test_looks_like_title(self):
        from modules.achievement.extract import looks_like_title
        assert isinstance(looks_like_title("Some Title"), bool)

    def test_split_names(self):
        from modules.achievement.extract import split_names
        result = split_names("Zhang San, Li Si")
        assert isinstance(result, list)
        assert len(result) >= 1

    def test_assign_field(self):
        from modules.achievement.extract import assign_field
        target = {}
        assign_field(target, "title", "Test")
        assert target["title"] == "Test"

    def test_append_link(self):
        from modules.achievement.extract import append_link
        target = {"links": []}
        append_link(target, "Homepage", "https://example.com", "official_site")
        assert len(target["links"]) == 1

    def test_harvest_fields_from_text(self):
        from modules.achievement.extract import harvest_fields_from_text
        result = harvest_fields_from_text("成果名称: AI技术\n技术简介: 人工智能技术方案")
        assert isinstance(result, dict)


# ── file/service.py helpers ─────────────────────────────────

class TestFileServiceHelpers:
    def test_safe_name(self):
        from modules.file.service import _safe_name
        assert _safe_name("test.pdf") == "test.pdf"
        assert _safe_name("") == "upload"
        assert len(_safe_name("x" * 300)) == 255

    def test_validate_upload_bad_extension(self):
        from modules.file.service import _validate_upload
        with pytest.raises(BizError):
            _validate_upload("test.exe", "application/octet-stream", b"content")

    def test_validate_upload_empty(self):
        from modules.file.service import _validate_upload
        with pytest.raises(BizError):
            _validate_upload("test.pdf", "application/pdf", b"")

    def test_validate_upload_pdf_bad_magic(self):
        from modules.file.service import _validate_upload
        with pytest.raises(BizError):
            _validate_upload("test.pdf", "application/pdf", b"not a pdf")

    def test_validate_upload_pdf_valid(self):
        from modules.file.service import _validate_upload
        suffix, mime = _validate_upload("test.pdf", "application/pdf", b"%PDF-1.4 content")
        assert suffix == ".pdf"
        assert mime == "application/pdf"

    def test_validate_upload_office_doc(self):
        from modules.file.service import _validate_upload
        ole2 = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1" + b"\x00" * 100
        suffix, mime = _validate_upload("test.doc", "application/msword", ole2)
        assert suffix == ".doc"

    def test_validate_upload_office_bad_magic(self):
        from modules.file.service import _validate_upload
        with pytest.raises(BizError):
            _validate_upload("test.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"not a docx")

    def test_image_dimensions_non_image(self):
        from modules.file.service import _image_dimensions
        w, h = _image_dimensions(".pdf", b"data")
        assert w is None and h is None

    def test_file_proxy_error(self):
        from modules.file.service import FileProxyError
        err = FileProxyError(400, "bad")
        assert err.http_status == 400
        assert err.msg == "bad"

    def test_thumbnail_path(self):
        from modules.file.service import thumbnail_path_for_file
        p = thumbnail_path_for_file(42)
        assert "42.jpg" in str(p)

    def test_proxy_file_invalid_id(self):
        from modules.file.service import proxy_file, FileProxyError
        with pytest.raises(FileProxyError):
            proxy_file("")

    def test_proxy_file_bad_chars(self):
        from modules.file.service import proxy_file, FileProxyError
        with pytest.raises(FileProxyError):
            proxy_file("!@#$%")


# ── core/middleware.py ──────────────────────────────────────

class TestCoreMiddleware:
    def test_user_is_active(self):
        from core.middleware import _user_is_active
        assert _user_is_active(1) is True

    def test_identity_from_access_token_valid(self):
        from core.middleware import identity_from_access_token
        import time
        from config import settings
        import jwt
        payload = {"sub": "1", "userNo": "U001", "roles": ["user"],
                   "type": "access", "iat": int(time.time()), "exp": int(time.time()) + 3600}
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        result = identity_from_access_token(token)
        assert result is not None

    def test_identity_from_access_token_expired(self):
        from core.middleware import identity_from_access_token
        import time
        from config import settings
        import jwt
        payload = {"sub": "1", "userNo": "U001", "roles": ["user"],
                   "type": "access", "iat": int(time.time()) - 7200, "exp": int(time.time()) - 3600}
        token = jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
        result = identity_from_access_token(token)
        assert result is None

    def test_identity_from_access_token_bad(self):
        from core.middleware import identity_from_access_token
        assert identity_from_access_token("bad-token") is None


# ── core/rate_limit.py ──────────────────────────────────────

class TestCoreRateLimit:
    def test_sweep_locked(self):
        from core.rate_limit import _sweep_locked
        # Should not raise
        _sweep_locked(0.0)

    def test_check_basic(self):
        from core.rate_limit import _check
        # Should not raise for normal usage
        _check("test_key", limit=100, window_s=60)

    def test_is_trusted_proxy(self):
        from core.rate_limit import _is_trusted_proxy
        assert isinstance(_is_trusted_proxy("127.0.0.1"), bool)

    def test_parse_trusted_proxies(self):
        from core.rate_limit import _parse_trusted_proxies
        result = _parse_trusted_proxies()
        assert isinstance(result, tuple)


# ── core/exception_handlers.py ──────────────────────────────

class TestExceptionHandlers:
    def test_register_exception_handlers(self):
        from core.exception_handlers import register_exception_handlers
        from fastapi import FastAPI
        app = FastAPI()
        register_exception_handlers(app)
        # Should not raise

    def test_desensitize_upstream_body(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("some error text")
        assert isinstance(result, str)

    def test_desensitize_upstream_body_long(self):
        from core.exception_handlers import _desensitize_upstream_body
        result = _desensitize_upstream_body("x" * 500, limit=100)
        assert len(result) <= 150  # some margin for truncation message


# ── config.py ───────────────────────────────────────────────

class TestConfig:
    def test_settings_exists(self):
        from config import settings
        assert settings is not None

    def test_settings_jwt(self):
        from config import settings
        assert settings.JWT_SECRET
        assert settings.JWT_ALGORITHM

    def test_settings_access_token_expires(self):
        from config import settings
        assert settings.ACCESS_TOKEN_EXPIRES > 0

    def test_settings_refresh_token_expires(self):
        from config import settings
        assert settings.REFRESH_TOKEN_EXPIRES_DAYS > 0

    def test_mock_ticket_prefix(self):
        from config import MOCK_TICKET_PREFIX
        assert isinstance(MOCK_TICKET_PREFIX, str)

    def test_settings_media_base_url(self):
        from config import settings
        assert settings.MEDIA_BASE_URL

    def test_settings_max_upload_bytes(self):
        from config import settings
        assert settings.MAX_UPLOAD_BYTES > 0

    def test_settings_ai_feature(self):
        from config import settings
        assert hasattr(settings, "AI_FEATURE_ENABLED")


# ── app.py ──────────────────────────────────────────────────

class TestApp:
    def test_app_exists(self):
        from app import app
        assert app is not None

    def test_app_title(self):
        from app import app
        assert app.title


# ── db.py ───────────────────────────────────────────────────

class TestDb:
    def test_db_imports(self):
        import db
        assert hasattr(db, "get_cursor")
        assert hasattr(db, "get_conn")

    def test_db_init_pool(self):
        import db
        assert callable(db.init_pool)

    def test_db_close_pool(self):
        import db
        assert callable(db.close_pool)


# ── achievement/service.py helpers ──────────────────────────

class TestAchievementServiceHelpers:
    def test_parse_page_args(self):
        from modules.achievement.service import _parse_page_args
        page, size, kw, cat, mat, ind = _parse_page_args({})
        assert page == 1
        assert size == 10
        assert kw == ""
        assert cat == ""

    def test_parse_page_args_values(self):
        from modules.achievement.service import _parse_page_args
        page, size, kw, cat, mat, ind = _parse_page_args({
            "page": "2", "pageSize": "20", "keyword": "AI",
            "category": "tech", "maturityLevel": "01_idea", "industryId": "5"
        })
        assert page == 2
        assert size == 20
        assert kw == "AI"

    def test_parse_page_args_bad_values(self):
        from modules.achievement.service import _parse_page_args
        page, size, kw, cat, mat, ind = _parse_page_args({"page": "abc"})
        assert page == 1
        assert size == 10

    def test_row_to_list_item(self):
        from modules.achievement.service import _row_to_list_item
        row = {
            "id": 1, "title": "Test", "source_org_name": "Corp",
            "tech_intro": "intro", "maturity_level": "01_idea", "maturity_desc": None,
            "application_fields": '["AI"]', "pricing_mode": "negotiable",
            "price_min_wan": 10.0, "price_max_wan": 50.0,
            "view_count": 5, "published_at": datetime(2026, 1, 1),
            "owner_user_id": 1, "org_id": None, "certified_org_name": None,
            "category_name": "Tech", "category_code": "T",
            "industries": "[]", "cover_file_id": None,
        }
        result = _row_to_list_item(row, user_id=1)
        assert result["id"] == 1
        assert result["isMine"] is True
        assert result["platformAssisted"] is False

    def test_row_to_list_item_json_fields(self):
        from modules.achievement.service import _row_to_list_item
        row = {
            "id": 2, "title": "T2", "source_org_name": None,
            "tech_intro": None, "maturity_level": None, "maturity_desc": None,
            "application_fields": None, "pricing_mode": None,
            "price_min_wan": None, "price_max_wan": None,
            "view_count": 0, "published_at": None,
            "owner_user_id": None, "org_id": 1, "certified_org_name": "Cert",
            "category_name": None, "category_code": None,
            "industries": None, "cover_file_id": None,
        }
        result = _row_to_list_item(row, user_id=1)
        assert result["isMine"] is False
        assert result["platformAssisted"] is True

    def test_org_cert_payload(self):
        from modules.achievement.service import _org_cert_payload
        assert _org_cert_payload({"org_id": 1}) == {"orgId": 1, "orgCertified": True}
        assert _org_cert_payload({"org_id": None}) == {"orgId": None, "orgCertified": False}

    def test_display_source_org(self):
        from modules.achievement.service import _display_source_org
        assert _display_source_org({"org_id": 1, "certified_org_name": "Cert", "source_org_name": "Src"}) == "Cert"
        assert _display_source_org({"org_id": None, "source_org_name": "Src"}) == "Src"

    def test_transitions(self):
        from modules.achievement.service import TRANSITIONS
        assert "submit" in TRANSITIONS
        assert "offline" in TRANSITIONS

    def test_editable_statuses(self):
        from modules.achievement.service import EDITABLE_STATUSES
        assert "draft" in EDITABLE_STATUSES
        assert "rejected" in EDITABLE_STATUSES
        assert "offline" in EDITABLE_STATUSES

    def test_pricing_modes(self):
        from modules.achievement.service import PRICING_MODES
        assert "negotiable" in PRICING_MODES
        assert "license" in PRICING_MODES

    def test_parse_upsert_body_not_dict(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body("bad", partial=False)

    def test_parse_upsert_body_missing_title(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({}, partial=False)

    def test_parse_upsert_body_empty_title(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "  "}, partial=False)

    def test_parse_upsert_body_title_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "x" * 201}, partial=False)

    def test_parse_upsert_body_invalid_maturity(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "maturityLevel": "bad"}, partial=False)

    def test_parse_upsert_body_invalid_pricing(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "pricingMode": "bad"}, partial=False)

    def test_parse_upsert_body_invalid_achievement_kind(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "achievementKind": "bad"}, partial=False)

    def test_parse_upsert_body_field_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "titleEn": "x" * 501}, partial=False)

    def test_parse_upsert_body_invalid_price(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "priceMinWan": -1}, partial=False)

    def test_parse_upsert_body_price_non_numeric(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "priceMaxWan": "abc"}, partial=False)

    def test_parse_upsert_body_app_fields_not_list(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "applicationFields": "bad"}, partial=False)

    def test_parse_upsert_body_app_fields_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "applicationFields": ["x" * 129]}, partial=False)

    def test_parse_upsert_body_inventor_refs_not_list(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": "bad"}, partial=False)

    def test_parse_upsert_body_inventor_ref_not_dict(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": ["bad"]}, partial=False)

    def test_parse_upsert_body_inventor_missing_name(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": [{}]}, partial=False)

    def test_parse_upsert_body_inventor_name_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": [{"name": "x" * 65}]}, partial=False)

    def test_parse_upsert_body_inventor_org_name_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": [{"name": "Z", "orgName": "x" * 129}]}, partial=False)

    def test_parse_upsert_body_inventor_invalid_person_type(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": [{"name": "Z", "personType": "bad"}]}, partial=False)

    def test_parse_upsert_body_inventor_invalid_sort_order(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "inventorRefs": [{"name": "Z", "sortOrder": "bad"}]}, partial=False)

    def test_parse_upsert_body_invalid_category_id(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "categoryId": "bad"}, partial=False)

    def test_parse_upsert_body_invalid_org_id(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "orgId": "bad"}, partial=False)

    def test_cooperation_capacity_valid(self):
        from modules.achievement.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationPolicy": "parallel"}, fields)
        assert fields["cooperation_policy"] == "parallel"

    def test_cooperation_capacity_invalid_policy(self):
        from modules.achievement.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationPolicy": "bad"}, {})

    @patch("modules.achievement.service.get_cursor")
    def test_list_categories(self, mock_gc):
        from modules.achievement.service import list_categories
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 1, "code": "AI", "name": "AI Tech", "sort_order": 1}
        ]
        mock_gc.return_value = _mock_cur_ctx(cur)
        result = list_categories()
        assert len(result) == 1
        assert result[0]["code"] == "AI"

    @patch("modules.achievement.service.get_cursor")
    def test_list_industries(self, mock_gc):
        from modules.achievement.service import list_industries
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 1, "code": "T1", "name": "Tech", "parent_id": None, "sort_order": 1}
        ]
        mock_gc.return_value = _mock_cur_ctx(cur)
        result = list_industries()
        assert len(result) == 1

    @patch("modules.achievement.service.get_cursor")
    def test_get_achievement_detail_not_found(self, mock_gc):
        from modules.achievement.service import get_achievement_detail
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value = _mock_cur_ctx(cur)
        assert get_achievement_detail(999) is None

    def test_inventor_person_types(self):
        from modules.achievement.service import INVENTOR_PERSON_TYPES
        assert "first_inventor" in INVENTOR_PERSON_TYPES
        assert "co_inventor" in INVENTOR_PERSON_TYPES

    def test_cooperation_capacity_exclusive_gt1(self):
        from modules.achievement.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationPolicy": "exclusive", "cooperationCapacity": 2}, {})

    def test_cooperation_capacity_invalid(self):
        from modules.achievement.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationCapacity": "abc"}, {})

    def test_cooperation_capacity_zero(self):
        from modules.achievement.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationCapacity": 0}, {})

    def test_cooperation_capacity_none_clears(self):
        from modules.achievement.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationCapacity": None}, fields)
        assert fields["cooperation_capacity"] is None

    def test_parse_upsert_body_contact_too_long(self):
        from modules.achievement.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "T", "contactName": "x" * 65}, partial=False)