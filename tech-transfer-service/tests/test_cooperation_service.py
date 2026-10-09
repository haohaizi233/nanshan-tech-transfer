"""Tests for modules/cooperation/service.py — helpers, transitions, access control."""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError


def _mock_cur_ctx(mock_cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


class TestValidateTargetType:
    def test_valid(self):
        from modules.cooperation.service import _validate_target_type
        _validate_target_type("achievement")  # no error

    def test_invalid(self):
        from modules.cooperation.service import _validate_target_type
        with pytest.raises(BizError):
            _validate_target_type("bad")


class TestValidateIntentType:
    def test_none_passes(self):
        from modules.cooperation.service import _validate_intent_type
        assert _validate_intent_type("achievement", None) is None

    def test_empty_passes(self):
        from modules.cooperation.service import _validate_intent_type
        assert _validate_intent_type("achievement", "") is None

    def test_valid(self):
        from modules.cooperation.service import _validate_intent_type
        assert _validate_intent_type("achievement", "purchase") == "purchase"

    def test_invalid(self):
        from modules.cooperation.service import _validate_intent_type
        with pytest.raises(BizError):
            _validate_intent_type("achievement", "bad_type")


class TestCanAccessTarget:
    def test_published_always_visible(self):
        from modules.cooperation.service import can_access_target
        assert can_access_target(None, owner_user_id=1, status="published") is True

    def test_owner_can_access(self):
        from modules.cooperation.service import can_access_target
        assert can_access_target(1, owner_user_id=1, status="draft") is True

    def test_dock_party_can_access(self):
        from modules.cooperation.service import can_access_target
        assert can_access_target(2, owner_user_id=1, status="draft", is_dock_party=True) is True

    def test_non_owner_no_access(self):
        from modules.cooperation.service import can_access_target
        assert can_access_target(2, owner_user_id=1, status="draft") is False

    def test_anon_no_access_draft(self):
        from modules.cooperation.service import can_access_target
        assert can_access_target(None, owner_user_id=1, status="draft") is False


class TestHelperFunctions:
    def test_fmt_with_dt(self):
        from modules.cooperation.service import _fmt
        dt = datetime(2026, 1, 1, 12, 0, 0)
        assert _fmt(dt) == "2026-01-01 12:00:00"

    def test_fmt_none(self):
        from modules.cooperation.service import _fmt
        assert _fmt(None) is None

    def test_decode_contact_snapshot_valid_json(self):
        from modules.cooperation.service import _decode_contact_snapshot
        data = json.dumps({"displayName": "Zhang", "phone": "138"})
        result = _decode_contact_snapshot(data)
        assert result["contactName"] == "Zhang"

    def test_decode_contact_snapshot_dict(self):
        from modules.cooperation.service import _decode_contact_snapshot
        result = _decode_contact_snapshot({"displayName": "Li", "orgName": "Co"})
        assert result["contactName"] == "Li"
        assert result["orgName"] == "Co"

    def test_decode_contact_snapshot_invalid(self):
        from modules.cooperation.service import _decode_contact_snapshot
        assert _decode_contact_snapshot("bad json") is None
        assert _decode_contact_snapshot(None) is None
        assert _decode_contact_snapshot(123) is None

    def test_contact_response_no_contact(self):
        from modules.cooperation.service import _contact_response
        result = _contact_response(None, masked=True)
        assert result["available"] is False

    def test_contact_response_empty_contact(self):
        from modules.cooperation.service import _contact_response
        result = _contact_response({}, masked=True)
        assert result["available"] is False

    def test_contact_response_with_data(self):
        from modules.cooperation.service import _contact_response
        contact = {"contactName": "Zhang", "contactPhone": "13800138000", "contactEmail": "z@t.com"}
        result = _contact_response(contact, masked=False)
        assert result["available"] is True
        assert result["masked"] is False
        assert result["phone"] == "13800138000"

    def test_contact_response_masked(self):
        from modules.cooperation.service import _contact_response
        contact = {"contactName": "Zhang", "contactPhone": "13800138000"}
        result = _contact_response(contact, masked=True, reason="not yet")
        assert result["masked"] is True
        assert result["phone"] == "138****8000"

    def test_require_role_initiator(self):
        from modules.cooperation.service import _require_role
        row = {"initiator_user_id": 1, "target_owner_user_id": 2}
        assert _require_role(row, 1) == "initiator"

    def test_require_role_target_owner(self):
        from modules.cooperation.service import _require_role
        row = {"initiator_user_id": 1, "target_owner_user_id": 2}
        assert _require_role(row, 2) == "target_owner"

    def test_require_role_unknown(self):
        from modules.cooperation.service import _require_role
        row = {"initiator_user_id": 1, "target_owner_user_id": 2}
        with pytest.raises(BizError):
            _require_role(row, 3)

    def test_row_to_intent_initiator(self):
        from modules.cooperation.service import _row_to_intent
        row = {
            "id": 1, "initiator_user_id": 1, "target_owner_user_id": 2,
            "target_type": "achievement", "target_id": 10,
            "intent_type": "purchase", "message": "hi",
            "status": "pending", "handling_mode": "direct",
            "assist_status": None, "accept_mode": None,
            "last_contact_at": None, "next_followup_at": None,
            "attempt_count": 0, "slot_reserved": False,
            "outcome_status": None, "outcome_cooperation_mode": None,
            "outcome_signed": None, "outcome_amount_wan": None,
            "outcome_failure_reason": None, "outcome_note": None,
            "version": 1, "created_at": datetime(2026, 1, 1),
            "accepted_at": None, "confirmed_at": None,
            "completed_at": None, "closed_at": None,
            "target_org_id": None,
        }
        result = _row_to_intent(row, 1)
        assert result["myRole"] == "initiator"
        assert result["handlingMode"] == "direct"


class TestHasAcceptedIntent:
    def test_none_user(self):
        from modules.cooperation.service import has_accepted_intent
        cur = MagicMock()
        assert has_accepted_intent(cur, "achievement", 1, None) is False

    def test_exists(self):
        from modules.cooperation.service import has_accepted_intent
        cur = MagicMock()
        cur.fetchone.return_value = {"1": 1}
        assert has_accepted_intent(cur, "achievement", 1, 1) is True

    def test_not_exists(self):
        from modules.cooperation.service import has_accepted_intent
        cur = MagicMock()
        cur.fetchone.return_value = None
        assert has_accepted_intent(cur, "achievement", 1, 1) is False


class TestIsAcceptedDockParty:
    def test_none_user(self):
        from modules.cooperation.service import is_accepted_dock_party
        cur = MagicMock()
        assert is_accepted_dock_party(cur, "demand", 1, None) is False


class TestTransitions:
    def test_accept_transition(self):
        from modules.cooperation.service import TRANSITIONS
        t = TRANSITIONS["accept"]
        assert t["to"] == "accepted"
        assert "pending" in t["from"]

    def test_all_transitions_exist(self):
        from modules.cooperation.service import TRANSITIONS
        for op in ("accept", "reject", "confirm", "cancel", "complete"):
            assert op in TRANSITIONS

    def test_intent_types_demand(self):
        from modules.cooperation.service import INTENT_TYPES
        assert "provide_solution" in INTENT_TYPES["demand"]

    def test_intent_types_achievement(self):
        from modules.cooperation.service import INTENT_TYPES
        assert "purchase" in INTENT_TYPES["achievement"]


class TestAssistStatuses:
    def test_assist_statuses(self):
        from modules.cooperation.service import ASSIST_STATUSES
        assert "queued" in ASSIST_STATUSES
        assert "target_agreed" in ASSIST_STATUSES

    def test_assist_transitions(self):
        from modules.cooperation.service import ASSIST_STATUS_TRANSITIONS
        assert "contacting" in ASSIST_STATUS_TRANSITIONS["queued"]


class TestInsertEvent:
    def test_insert_event(self):
        from modules.cooperation.service import _insert_event
        cur = MagicMock()
        _insert_event(cur, 1, "accepted", "pending", "accepted", 1, "target_owner", remark="ok")
        cur.execute.assert_called_once()


class TestCreateIntent:
    @patch("modules.cooperation.service.get_cursor")
    def test_invalid_body(self, mock_gc):
        from modules.cooperation.service import create_intent
        with pytest.raises(BizError):
            create_intent(1, "U001", "bad")

    @patch("modules.cooperation.service.get_cursor")
    def test_invalid_target_type(self, mock_gc):
        from modules.cooperation.service import create_intent
        with pytest.raises(BizError):
            create_intent(1, "U001", {"targetType": "bad", "targetId": 1, "contactShareConsent": True})

    @patch("modules.cooperation.service.get_cursor")
    def test_missing_consent(self, mock_gc):
        from modules.cooperation.service import create_intent
        with pytest.raises(BizError):
            create_intent(1, "U001", {"targetType": "achievement", "targetId": 1})

    @patch("modules.cooperation.service.get_cursor")
    def test_target_not_found(self, mock_gc):
        from modules.cooperation.service import create_intent
        cur = MagicMock()
        cur.fetchone.return_value = None
        mock_gc.return_value = _mock_cur_ctx(cur)
        with pytest.raises(BizError):
            create_intent(1, "U001", {"targetType": "achievement", "targetId": 999, "contactShareConsent": True})