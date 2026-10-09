"""Tests for modules/demand/service.py — parse, validate, query, CRUD, transitions."""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError


# ── helpers ─────────────────────────────────────────────────

def _mock_cursor_ctx(mock_cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _sample_demand_row(**overrides):
    base = {
        "id": 1, "title": "Test Demand", "description": "desc", "owner_user_id": 1,
        "created_by_user_id": 1, "status": "draft", "version": 1,
        "org_id": None, "org_name_snapshot": "TestOrg", "org_intro": None,
        "category_id": None, "category_name": None, "category_code": None,
        "region": "SZ", "coop_mode": '["技术转让"]',
        "budget_min_wan": None, "budget_max_wan": None, "budget_negotiable": False,
        "expect_deadline": None, "deadline_desc": None,
        "contact_name": "Zhang", "contact_title": "Mgr",
        "contact_phone": "13800138000", "contact_email": "z@t.com", "contact_wechat": None,
        "reject_reason": None, "view_count": 0, "published_at": None,
        "created_at": datetime(2026, 1, 1), "updated_at": None,
        "cooperation_policy": None, "cooperation_capacity": None,
        "cooperation_remaining": None, "closure_reason_code": None,
        "closure_reason_note": None, "org_name": "TestOrg",
    }
    base.update(overrides)
    return base


# ── _parse_upsert_body ─────────────────────────────────────

class TestParseUpsertBody:
    def test_full_create(self):
        from modules.demand.service import _parse_upsert_body
        body = {
            "title": "Need AI", "description": "We need an AI solution",
            "region": "SZ", "coopMode": ["技术转让"], "budgetMinWan": 10, "budgetMaxWan": 50,
            "budgetNegotiable": False, "expectDeadline": "2026-12-31",
            "categoryId": 1, "orgId": 2, "contactName": "Zhang", "contactPhone": "13800138000",
            "contactEmail": "z@t.com", "tags": ["AI", "ML"],
        }
        fields, tags, attachments = _parse_upsert_body(body, partial=False)
        assert fields["title"] == "Need AI"
        assert fields["description"] == "We need an AI solution"
        assert tags == ["AI", "ML"]
        assert attachments is None

    def test_partial_update(self):
        from modules.demand.service import _parse_upsert_body
        body = {"title": "Updated"}
        fields, tags, attachments = _parse_upsert_body(body, partial=True)
        assert fields["title"] == "Updated"
        assert "description" not in fields

    def test_missing_title_not_partial(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"description": "desc"}, partial=False)

    def test_missing_description_not_partial(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t"}, partial=False)

    def test_empty_title_raises(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "", "description": "d"}, partial=False)

    def test_title_too_long(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "x" * 201, "description": "d"}, partial=False)

    def test_empty_description(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "  "}, partial=False)

    def test_invalid_coop_mode(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "coopMode": "not-list"}, partial=False)

    def test_budget_negative(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "budgetMinWan": -1}, partial=False)

    def test_budget_non_numeric(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "budgetMaxWan": "abc"}, partial=False)

    def test_budget_negotiable_not_bool(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "budgetNegotiable": "yes"}, partial=False)

    def test_invalid_deadline_format(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "expectDeadline": "2026/01/01"}, partial=False)

    def test_invalid_category_id(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "categoryId": "abc"}, partial=False)

    def test_invalid_org_id(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "orgId": "xyz"}, partial=False)

    def test_tags_not_list(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "tags": "AI"}, partial=False)

    def test_attachments_too_many(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "attachments": [{}] * 21}, partial=False)

    def test_attachments_invalid_item(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "attachments": ["bad"]}, partial=False)

    def test_attachments_invalid_file_id(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "attachments": [{"fileId": "abc"}]}, partial=False)

    def test_attachments_invalid_role(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "attachments": [{"fileId": 1, "role": "bad"}]}, partial=False)

    def test_attachments_valid(self):
        from modules.demand.service import _parse_upsert_body
        fields, tags, att = _parse_upsert_body(
            {"title": "t", "description": "d", "attachments": [{"fileId": 1, "role": "image"}]}, partial=False
        )
        assert len(att) == 1
        assert att[0]["fileId"] == 1

    def test_contact_field_length(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "contactName": "x" * 65}, partial=False)

    def test_org_name_too_long(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "orgName": "x" * 129}, partial=False)

    def test_org_intro_too_long(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "orgIntro": "x" * 2001}, partial=False)

    def test_category_name_too_long(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body({"title": "t", "description": "d", "categoryName": "x" * 65}, partial=False)

    def test_body_not_dict(self):
        from modules.demand.service import _parse_upsert_body
        with pytest.raises(BizError):
            _parse_upsert_body("bad", partial=False)


# ── cooperation capacity ────────────────────────────────────

class TestCooperationCapacity:
    def test_parallel_valid(self):
        from modules.demand.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationPolicy": "parallel", "cooperationCapacity": 5}, fields)
        assert fields["cooperation_policy"] == "parallel"
        assert fields["cooperation_capacity"] == 5

    def test_exclusive_one(self):
        from modules.demand.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationPolicy": "exclusive", "cooperationCapacity": 1}, fields)
        assert fields["cooperation_capacity"] == 1

    def test_exclusive_gt1_raises(self):
        from modules.demand.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationPolicy": "exclusive", "cooperationCapacity": 2}, {})

    def test_invalid_policy(self):
        from modules.demand.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationPolicy": "bad"}, {})

    def test_capacity_none_clears(self):
        from modules.demand.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationCapacity": None}, fields)
        assert fields["cooperation_capacity"] is None

    def test_capacity_empty_string_clears(self):
        from modules.demand.service import _parse_cooperation_capacity
        fields = {}
        _parse_cooperation_capacity({"cooperationCapacity": ""}, fields)
        assert fields["cooperation_capacity"] is None

    def test_capacity_non_int_raises(self):
        from modules.demand.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationCapacity": "abc"}, {})

    def test_capacity_zero_raises(self):
        from modules.demand.service import _parse_cooperation_capacity
        with pytest.raises(BizError):
            _parse_cooperation_capacity({"cooperationCapacity": 0}, {})


# ── helper functions ────────────────────────────────────────

class TestHelpers:
    def test_parse_page_args_defaults(self):
        from modules.demand.service import _parse_page_args
        page, size, kw = _parse_page_args({})
        assert page == 1
        assert size == 10
        assert kw == ""

    def test_parse_page_args_values(self):
        from modules.demand.service import _parse_page_args
        page, size, kw = _parse_page_args({"page": "3", "pageSize": "20", "keyword": "AI"})
        assert page == 3
        assert size == 20
        assert kw == "AI"

    def test_parse_page_args_bad_values(self):
        from modules.demand.service import _parse_page_args
        page, size, kw = _parse_page_args({"page": "abc", "pageSize": "xyz"})
        assert page == 1
        assert size == 10

    def test_parse_json_valid(self):
        from modules.demand.service import _parse_json
        assert _parse_json('["a","b"]') == ["a", "b"]

    def test_parse_json_invalid(self):
        from modules.demand.service import _parse_json
        assert _parse_json("bad json") == []

    def test_parse_json_none(self):
        from modules.demand.service import _parse_json
        assert _parse_json(None) == []

    def test_parse_json_non_string(self):
        from modules.demand.service import _parse_json
        assert _parse_json(["a"]) == ["a"]

    def test_org_cert_payload(self):
        from modules.demand.service import _org_cert_payload
        assert _org_cert_payload({"org_id": 1}) == {"orgId": 1, "orgCertified": True}
        assert _org_cert_payload({"org_id": None}) == {"orgId": None, "orgCertified": False}

    def test_row_to_summary(self):
        from modules.demand.service import _row_to_summary
        row = _sample_demand_row(owner_user_id=1, status="draft", budget_min_wan=10.0, published_at=datetime(2026, 1, 1))
        result = _row_to_summary(row, {}, user_id=1)
        assert result["id"] == 1
        assert result["title"] == "Test Demand"
        assert result["isMine"] is True
        assert result["platformAssisted"] is False
        assert result["budgetMinWan"] == 10.0
        assert result["publishedAt"] == "2026-01-01 00:00"

    def test_row_to_summary_not_mine(self):
        from modules.demand.service import _row_to_summary
        row = _sample_demand_row(owner_user_id=2, status="published")
        result = _row_to_summary(row, {}, user_id=1)
        assert result["isMine"] is False

    def test_row_to_summary_platform(self):
        from modules.demand.service import _row_to_summary
        row = _sample_demand_row(owner_user_id=None)
        result = _row_to_summary(row, {}, user_id=1)
        assert result["platformAssisted"] is True

    def test_row_to_detail(self):
        from modules.demand.service import _row_to_detail
        row = _sample_demand_row(owner_user_id=1, version=1, description="desc text",
                                  contact_name="Zhang", contact_phone="13800138000")
        result = _row_to_detail(row, {}, user_id=1, contact_visible=True)
        assert result["description"] == "desc text"
        assert result["contactName"] == "Zhang"
        assert result["contactPhone"] == "13800138000"

    def test_row_to_detail_masked(self):
        from modules.demand.service import _row_to_detail
        row = _sample_demand_row(owner_user_id=2, contact_name="Zhang", contact_phone="13800138000")
        result = _row_to_detail(row, {}, user_id=1, contact_visible=False)
        assert result["contactPhone"] == "138****8000"


# ── transitions ─────────────────────────────────────────────

class TestTransitions:
    def test_submit_from_draft(self):
        from modules.demand.service import TRANSITIONS
        t = TRANSITIONS["submit"]
        assert "draft" in t["from"]
        assert t["to"] == "pending_review"

    def test_cancel_from_published(self):
        from modules.demand.service import TRANSITIONS
        t = TRANSITIONS["cancel"]
        assert "published" in t["from"]
        assert t["to"] == "cancelled"

    def test_close_from_published_and_matched(self):
        from modules.demand.service import TRANSITIONS
        t = TRANSITIONS["close"]
        assert "published" in t["from"]
        assert "matched" in t["from"]
        assert t["to"] == "closed"

    def test_editable_statuses(self):
        from modules.demand.service import EDITABLE_STATUSES
        assert "draft" in EDITABLE_STATUSES
        assert "rejected" in EDITABLE_STATUSES

    def test_sort_whitelist(self):
        from modules.demand.service import SORT_WHITELIST
        assert "published_at.desc" in SORT_WHITELIST
        assert "created_at.desc" in SORT_WHITELIST


# ── _load_tags ──────────────────────────────────────────────

class TestLoadTags:
    def test_empty_ids(self):
        from modules.demand.service import _load_tags
        cur = MagicMock()
        result = _load_tags(cur, [])
        assert result == {}

    def test_with_data(self):
        from modules.demand.service import _load_tags
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"demand_id": 1, "name": "AI"},
            {"demand_id": 1, "name": "ML"},
            {"demand_id": 2, "name": "NLP"},
        ]
        result = _load_tags(cur, [1, 2])
        assert result[1] == ["AI", "ML"]
        assert result[2] == ["NLP"]


# ── _sync_tags ──────────────────────────────────────────────

class TestSyncTags:
    def test_none_skips(self):
        from modules.demand.service import _sync_tags
        cur = MagicMock()
        _sync_tags(cur, 1, None)
        cur.execute.assert_not_called()

    def test_creates_new_tags(self):
        from modules.demand.service import _sync_tags
        cur = MagicMock()
        cur.fetchone.side_effect = [None, {"id": 10}]
        _sync_tags(cur, 1, ["NewTag"])
        assert cur.execute.call_count >= 3  # DELETE + SELECT + INSERT tag + INSERT rel


# ── list_demands / list_my_demands ──────────────────────────

class TestListDemands:
    @patch("modules.demand.service.get_cursor")
    @patch("modules.demand.service._load_tags", return_value={})
    def test_list_demands_empty(self, mock_tags, mock_gc):
        from modules.demand.service import list_demands
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_ctx(cur)
        result = list_demands({}, user_id=1)
        assert result["total"] == 0
        assert result["list"] == []

    @patch("modules.demand.service.get_cursor")
    @patch("modules.demand.service._load_tags", return_value={})
    def test_list_my_demands(self, mock_tags, mock_gc):
        from modules.demand.service import list_my_demands
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_ctx(cur)
        result = list_my_demands(1, {})
        assert result["total"] == 0

    @patch("modules.demand.service.get_cursor")
    @patch("modules.demand.service._load_tags", return_value={})
    def test_list_demands_with_keyword(self, mock_tags, mock_gc):
        from modules.demand.service import list_demands
        cur = MagicMock()
        cur.fetchone.return_value = {"c": 1}
        cur.fetchall.return_value = [_sample_demand_row()]
        mock_gc.return_value = _mock_cursor_ctx(cur)
        result = list_demands({"keyword": "AI", "includeMine": "1", "categoryCode": "tech"}, user_id=1)
        assert result["total"] == 1


# ── get_demand_detail ───────────────────────────────────────

class TestGetDemandDetail:
    @patch("modules.demand.service.get_cursor")
    @patch("modules.demand.service.has_accepted_intent", return_value=False)
    @patch("modules.demand.service.is_accepted_dock_party", return_value=False)
    def test_not_found(self, mock_dock, mock_intent, mock_gc):
        from modules.demand.service import get_demand_detail
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value = _mock_cursor_ctx(cur)
        with pytest.raises(BizError):
            get_demand_detail(999, 1)

    @patch("modules.demand.service.get_cursor")
    @patch("modules.demand.service.has_accepted_intent", return_value=False)
    @patch("modules.demand.service._load_tags", return_value={})
    @patch("modules.demand.service._load_attachments", return_value=[])
    def test_published_detail(self, mock_att, mock_tags, mock_intent, mock_gc):
        from modules.demand.service import get_demand_detail
        cur = MagicMock()
        row = _sample_demand_row(status="published", owner_user_id=1)
        cur.fetchone.side_effect = [row, {"view_count": 1}]
        mock_gc.return_value = _mock_cursor_ctx(cur)
        result = get_demand_detail(1, 1)
        assert result["id"] == 1


# ── _resolve_category_name ──────────────────────────────────

class TestResolveCategoryName:
    def test_existing_category(self):
        from modules.demand.service import _resolve_category_name
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 5}
        fields = {"category_name": "AI"}
        _resolve_category_name(cur, fields)
        assert fields["category_id"] == 5

    def test_new_category(self):
        from modules.demand.service import _resolve_category_name
        cur = MagicMock()
        cur.fetchone.side_effect = [None, {"id": 10}]
        fields = {"category_name": "NewCat"}
        _resolve_category_name(cur, fields)
        assert fields["category_id"] == 10

    def test_org_intro_without_org_name(self):
        from modules.demand.service import _resolve_category_name
        cur = MagicMock()
        fields = {"org_intro": "intro text"}
        with pytest.raises(BizError):
            _resolve_category_name(cur, fields)