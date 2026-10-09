"""Tests for modules/patent/normalize.py — normalization, parsing, cleaning."""
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError


class TestPatentNormalize:
    # ── is_publication_no ────────────────────────────────────
    def test_valid_cn(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no("CN12345678A") is True

    def test_valid_ep(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no("EP1234567") is True

    def test_empty(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no("") is False

    def test_none(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no(None) is False

    def test_too_long(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no("x" * 33) is False

    def test_random_text(self):
        from modules.patent.normalize import is_publication_no
        assert is_publication_no("hello world") is False

    # ── to_simplified ────────────────────────────────────────
    def test_simplified_english(self):
        from modules.patent.normalize import to_simplified
        assert to_simplified("hello") == "hello"

    def test_simplified_empty(self):
        from modules.patent.normalize import to_simplified
        assert to_simplified("") == ""

    def test_simplified_none(self):
        from modules.patent.normalize import to_simplified
        assert to_simplified(None) is None

    # ── clean_text ───────────────────────────────────────────
    def test_clean_none(self):
        from modules.patent.normalize import clean_text
        assert clean_text(None) == ""

    def test_clean_html_tags(self):
        from modules.patent.normalize import clean_text
        result = clean_text("<b>bold</b> text")
        assert "<b>" not in result
        assert "bold" in result

    def test_clean_entities(self):
        from modules.patent.normalize import clean_text
        result = clean_text("&amp; &lt;test&gt;")
        assert "&amp;" not in result
        assert "&" in result

    def test_clean_whitespace(self):
        from modules.patent.normalize import clean_text
        assert clean_text("  hello   world  ") == "hello world"

    def test_clean_urls(self):
        from modules.patent.normalize import clean_text
        result = clean_text("See https://patents.google.com/patent/US123")
        assert "patents.google.com" not in result

    def test_clean_nbsp(self):
        from modules.patent.normalize import clean_text
        result = clean_text("hello\u00a0world")
        assert "\u00a0" not in result

    # ── clean_multiline ──────────────────────────────────────
    def test_clean_multiline_none(self):
        from modules.patent.normalize import clean_multiline
        assert clean_multiline(None) == ""

    def test_clean_multiline_text(self):
        from modules.patent.normalize import clean_multiline
        result = clean_multiline("Hello\nWorld")
        assert isinstance(result, str)

    # ── clean_date ───────────────────────────────────────────
    def test_clean_date_valid(self):
        from modules.patent.normalize import clean_date
        result = clean_date("2026-01-01")
        assert result == "2026-01-01"

    def test_clean_date_none(self):
        from modules.patent.normalize import clean_date
        assert clean_date(None) is None

    def test_clean_date_empty(self):
        from modules.patent.normalize import clean_date
        assert clean_date("") is None

    def test_clean_date_slash_format(self):
        from modules.patent.normalize import clean_date
        result = clean_date("2026/01/01")
        assert result == "2026-01-01"

    # ── infer_patent_type ────────────────────────────────────
    def test_infer_type_cn(self):
        from modules.patent.normalize import infer_patent_type
        result = infer_patent_type("CN12345678A")
        assert isinstance(result, str)

    def test_infer_type_us(self):
        from modules.patent.normalize import infer_patent_type
        result = infer_patent_type("US1234567")
        assert isinstance(result, str)

    def test_infer_type_empty(self):
        from modules.patent.normalize import infer_patent_type
        result = infer_patent_type("")
        assert isinstance(result, str)

    # ── contains_source_leak ─────────────────────────────────
    def test_source_leak_clean(self):
        from modules.patent.normalize import contains_source_leak
        assert contains_source_leak("Just normal text") is False

    def test_source_leak_url(self):
        from modules.patent.normalize import contains_source_leak
        assert contains_source_leak("Check https://patents.google.com") is True

    def test_source_leak_none(self):
        from modules.patent.normalize import contains_source_leak
        assert contains_source_leak(None) is False

    # ── assert_no_source_leak ────────────────────────────────
    def test_assert_no_source_leak_clean(self):
        from modules.patent.normalize import assert_no_source_leak
        assert_no_source_leak({"title": "Clean", "abstract": "Clean abstract"})

    def test_assert_no_source_leak_dirty(self):
        from modules.patent.normalize import assert_no_source_leak
        with pytest.raises(BizError):
            assert_no_source_leak({"title": "Check https://patents.google.com"})

    # ── page_meta ────────────────────────────────────────────
    def test_page_meta(self):
        from modules.patent.normalize import page_meta
        result = page_meta(100, 1, 10)
        assert result["total"] == 100
        assert result["page"] == 1
        assert result["pageSize"] == 10
        assert result["totalPages"] == 10

    def test_page_meta_empty(self):
        from modules.patent.normalize import page_meta
        result = page_meta(0, 1, 10)
        assert result["totalPages"] == 0

    # ── _contains_cjk ────────────────────────────────────────
    def test_contains_cjk_chinese(self):
        from modules.patent.normalize import _contains_cjk
        assert _contains_cjk("你好") is True

    def test_contains_cjk_english(self):
        from modules.patent.normalize import _contains_cjk
        assert _contains_cjk("hello") is False

    def test_contains_cjk_mixed(self):
        from modules.patent.normalize import _contains_cjk
        assert _contains_cjk("hello你好") is True

    # ── map_search_hit ───────────────────────────────────────
    def test_map_search_hit_valid(self):
        from modules.patent.normalize import map_search_hit
        raw = {
            "publication_no": "CN12345678A",
            "title": "Test Patent",
            "abstract": "An abstract",
            "applicants": "Corp",
            "inventors": "Zhang",
            "filing_date": "2026-01-01",
        }
        result = map_search_hit(raw)
        assert result is not None
        assert result["publicationNo"] == "CN12345678A"

    def test_map_search_hit_missing_pub_no(self):
        from modules.patent.normalize import map_search_hit
        result = map_search_hit({"title": "No pub no"})
        assert result is None

    # ── format_patent_content_blocks ─────────────────────────
    def test_format_content_blocks_none(self):
        from modules.patent.normalize import format_patent_content_blocks
        result = format_patent_content_blocks(None)
        assert result == []

    def test_format_content_blocks_empty(self):
        from modules.patent.normalize import format_patent_content_blocks
        result = format_patent_content_blocks("")
        assert result == []

    def test_format_content_blocks_text(self):
        from modules.patent.normalize import format_patent_content_blocks
        result = format_patent_content_blocks("Simple text content")
        assert isinstance(result, list)

    # ── _semantic_marker ─────────────────────────────────────
    def test_semantic_marker(self):
        from modules.patent.normalize import _semantic_marker
        result = _semantic_marker("sup", "1")
        assert isinstance(result, str)
        assert "1" in result