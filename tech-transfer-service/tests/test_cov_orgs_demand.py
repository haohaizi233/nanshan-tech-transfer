"""Coverage tests for cooperation / membership / demand / file service modules.

Pure unit tests: all DB access is mocked via the service module's ``get_cursor``
(or ``transaction`` for membership).  No real DB / network calls.
"""

import io
import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from core.errors import BizError

# ── fat row shared by every mocked fetchone / fetchall ────────────────────

FAT = {
    # generic
    "id": 1,
    "user_id": 1,
    "org_id": 1,
    "category_id": 1,
    "name": "n",
    "title": "t",
    "status": "active",
    "version": 1,
    "c": 1,
    "total": 1,
    "user_no": "U001",
    "role": "member",
    "role_code": "user",
    "created_at": datetime(2026, 1, 1, 12, 0),
    "updated_at": datetime(2026, 1, 1, 12, 0),
    # cooperation
    "initiator_user_id": 1,
    "target_owner_user_id": 2,
    "target_type": "demand",
    "target_id": 10,
    "target_org_id": 1,
    "intent_type": "provide_solution",
    "message": "hello",
    "handling_mode": "direct",
    "assist_status": "queued",
    "accept_mode": None,
    "last_contact_at": None,
    "next_followup_at": None,
    "attempt_count": 0,
    "slot_reserved": False,
    "outcome_status": None,
    "outcome_cooperation_mode": None,
    "outcome_signed": None,
    "outcome_amount_wan": None,
    "outcome_failure_reason": None,
    "outcome_note": None,
    "accepted_at": None,
    "confirmed_at": None,
    "completed_at": None,
    "closed_at": None,
    "owner_user_id": 1,
    "cooperation_policy": "parallel",
    "cooperation_remaining": None,
    "cooperation_capacity": None,
    "org_name": "Test Org",
    "contact_name": "张三",
    "contact_title": "经理",
    "contact_phone": "13800138000",
    "contact_email": "test@example.com",
    "contact_wechat": "wx123",
    "display_name": "张三",
    "initiator_contact_snapshot": None,
    "event_type": "created",
    "from_status": None,
    "to_status": "pending",
    "operator_role": "initiator",
    "remark": "ok",
    # membership
    "applicant_user_id": 1,
    "requested_name": "New Org",
    "requested_type": "enterprise",
    "credit_code": "91110000MA00000000",
    "department": "R&D",
    "work_email": "work@example.com",
    "apply_note": "note",
    "reason": "reason",
    "real_name": "张三",
    "proof_material": "proof",
    "review_reason": None,
    "reviewed_by_user_id": None,
    "reviewed_at": None,
    "region": "深圳",
    "address": "地址",
    "website": "https://example.com",
    # demand
    "description": "desc",
    "coop_mode": '["joint_rnd"]',
    "budget_min_wan": 10.0,
    "budget_max_wan": 100.0,
    "budget_negotiable": True,
    "deadline_desc": "asap",
    "category_name": "tech",
    "category_code": "tech",
    "reject_reason": None,
    "view_count": 5,
    "published_at": datetime(2026, 1, 1, 12, 0),
    "expect_deadline": "2026-06-01",
    "org_intro": "intro",
    "org_name_snapshot": "snapshot",
    # file / attachment
    "file_id": 1,
    "demand_id": 1,
    "attachment_role": "attachment",
    "sort_order": 0,
    "caption": None,
    "original_name": "test.png",
    "mime_type": "image/png",
    "size_bytes": 1024,
    "storage_key": "1/abc.png",
    "created_by": 1,
    "linked": False,
    "width": 100,
    "height": 100,
}


def _fat(**kw):
    """Return a copy of FAT with overrides."""
    d = dict(FAT)
    d.update(kw)
    return d


def _cur():
    cur = MagicMock()
    cur.fetchone.return_value = dict(FAT)
    cur.fetchall.return_value = [dict(FAT)]
    cur.rowcount = 1
    return cur


def _cur_seq(*seq, rows=None, rowcount=1):
    """Cursor whose fetchone pops *seq* first, then falls back to FAT."""
    cur = MagicMock()
    queue = list(seq)

    def _next():
        return queue.pop(0) if queue else dict(FAT)

    cur.fetchone.side_effect = _next
    cur.fetchall.return_value = rows if rows is not None else [dict(FAT)]
    cur.rowcount = rowcount
    return cur


def _cur_sql(routes, rows=None, rowcount=1):
    """Cursor that routes fetchone based on the last executed SQL substring.

    *routes* is a list of ``(sql_substring, value)`` pairs; the first match wins.
    Unmatched calls return a copy of FAT.
    """
    cur = MagicMock()
    state = {"sql": ""}

    def _execute(sql, *a, **kw):
        state["sql"] = sql
        return None

    def _fetchone():
        for needle, val in routes:
            if needle in state["sql"]:
                return val
        return dict(FAT)

    cur.execute.side_effect = _execute
    cur.fetchone.side_effect = _fetchone
    cur.fetchall.return_value = rows if rows is not None else [dict(FAT)]
    cur.rowcount = rowcount
    return cur


def _gc(mock_gc, cur):
    mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)


def _tx(mock_tx, cur):
    conn = MagicMock()
    conn.cursor.return_value.__enter__ = MagicMock(return_value=cur)
    conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_tx.return_value.__enter__ = MagicMock(return_value=conn)
    mock_tx.return_value.__exit__ = MagicMock(return_value=False)


# ── tiny image factories (for file-service tests) ────────────────────────


def _png_bytes(size=(10, 10), mode="RGB"):
    img = Image.new(mode, size, "red" if mode == "RGB" else 128)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _jpeg_bytes(size=(10, 10)):
    img = Image.new("RGB", size, "blue")
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


ADMIN = {"userId": 1, "userNo": "U001", "isPlatformAdmin": True}
USER = {"userId": 1, "userNo": "U001"}


# ═════════════════════════════════════════════════════════════════════════
# modules/cooperation/service.py
# ═════════════════════════════════════════════════════════════════════════


class TestCoopHelpers:
    def test_is_accepted_dock_party_true(self):
        from modules.cooperation.service import is_accepted_dock_party

        cur = _cur()
        assert is_accepted_dock_party(cur, "demand", 1, 1) is True

    def test_is_accepted_dock_party_none_user(self):
        from modules.cooperation.service import is_accepted_dock_party

        cur = _cur()
        assert is_accepted_dock_party(cur, "demand", 1, None) is False

    def test_is_accepted_dock_party_no_row(self):
        from modules.cooperation.service import is_accepted_dock_party

        cur = _cur()
        cur.fetchone.return_value = None
        assert is_accepted_dock_party(cur, "demand", 1, 1) is False

    def test_load_target_demand(self):
        from modules.cooperation.service import _load_target

        cur = _cur()
        row = _load_target(cur, "demand", 10)
        assert row["status"] == "active"

    def test_load_target_achievement(self):
        from modules.cooperation.service import _load_target

        cur = _cur()
        row = _load_target(cur, "achievement", 3)
        assert row is not None

    def test_target_summary_demand(self):
        from modules.cooperation.service import _target_summary

        cur = _cur()
        out = _target_summary(cur, "demand", 10)
        assert out["title"] == "t"
        assert out["status"] == "active"

    def test_target_summary_achievement(self):
        from modules.cooperation.service import _target_summary

        cur = _cur()
        out = _target_summary(cur, "achievement", 3)
        assert "title" in out

    def test_target_summary_not_found(self):
        from modules.cooperation.service import _target_summary

        cur = _cur()
        cur.fetchone.return_value = None
        out = _target_summary(cur, "demand", 10)
        assert out["title"] == "(目标已下线)"
        assert out["status"] == "offline"

    def test_counterpart_display_direct(self):
        from modules.cooperation.service import _counterpart_display

        cur = _cur()
        row = _fat(initiator_user_id=1, target_owner_user_id=2)
        name = _counterpart_display(cur, row, 1)
        assert name == "张三"

    def test_counterpart_display_assisted_with_org(self):
        from modules.cooperation.service import _counterpart_display

        cur = _cur()
        row = _fat(initiator_user_id=1, target_owner_user_id=None, target_org_id=5)
        cur.fetchone.return_value = {"name": "OrgX"}
        name = _counterpart_display(cur, row, 1)
        assert name == "OrgX"

    def test_counterpart_display_assisted_no_org_name(self):
        from modules.cooperation.service import _counterpart_display

        cur = _cur()
        row = _fat(initiator_user_id=1, target_owner_user_id=None, target_org_id=5)
        cur.fetchone.return_value = {"name": None}
        assert _counterpart_display(cur, row, 1) is None

    def test_counterpart_display_assisted_no_org_id(self):
        from modules.cooperation.service import _counterpart_display

        cur = _cur()
        row = _fat(initiator_user_id=1, target_owner_user_id=None, target_org_id=None)
        assert _counterpart_display(cur, row, 1) is None

    def test_target_contact_found(self):
        from modules.cooperation.service import _target_contact

        cur = _cur()
        out = _target_contact(cur, "demand", 10)
        assert out["contactName"] == "张三"
        assert out["contactPhone"] == "13800138000"

    def test_target_contact_not_found(self):
        from modules.cooperation.service import _target_contact

        cur = _cur()
        cur.fetchone.return_value = None
        assert _target_contact(cur, "achievement", 1) is None

    def test_counterpart_contact_target_owner_pending(self):
        from modules.cooperation.service import _counterpart_contact

        cur = _cur()
        snap = json.dumps({"displayName": "李四", "phone": "13900139000"})
        row = _fat(status="pending", initiator_contact_snapshot=snap)
        out = _counterpart_contact(cur, row, "target_owner")
        assert out["available"] is True
        assert out["masked"] is False

    def test_counterpart_contact_target_owner_closed(self):
        from modules.cooperation.service import _counterpart_contact

        cur = _cur()
        snap = json.dumps({"displayName": "李四", "phone": "13900139000"})
        row = _fat(status="cancelled", initiator_contact_snapshot=snap)
        out = _counterpart_contact(cur, row, "target_owner")
        assert out["masked"] is True

    def test_counterpart_contact_initiator_unlocked(self):
        from modules.cooperation.service import _counterpart_contact

        cur = _cur()
        row = _fat(status="accepted")
        out = _counterpart_contact(cur, row, "initiator")
        assert out["available"] is True
        assert out["masked"] is False

    def test_counterpart_contact_initiator_locked(self):
        from modules.cooperation.service import _counterpart_contact

        cur = _cur()
        row = _fat(status="pending")
        out = _counterpart_contact(cur, row, "initiator")
        assert out["masked"] is True

    def test_row_to_intent_target_owner(self):
        from modules.cooperation.service import _row_to_intent

        row = _fat(initiator_user_id=2, target_owner_user_id=1)
        out = _row_to_intent(row, 1)
        assert out["myRole"] == "target_owner"

    def test_row_to_intent_initiator(self):
        from modules.cooperation.service import _row_to_intent

        row = _fat(initiator_user_id=1, target_owner_user_id=2)
        out = _row_to_intent(row, 1)
        assert out["myRole"] == "initiator"

    def test_get_intent_row(self):
        from modules.cooperation.service import _get_intent_row

        cur = _cur()
        row = _get_intent_row(cur, 1)
        assert row["id"] == 1


class TestCoopReserveRelease:
    def test_reserve_slot_no_target(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = None
        with pytest.raises(BizError):
            _reserve_target_slot(cur, _fat(target_type="demand", target_id=10), 1)

    def test_reserve_slot_not_published(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = _fat(status="offline", cooperation_remaining=5)
        with pytest.raises(BizError):
            _reserve_target_slot(cur, _fat(target_type="demand", target_id=10), 1)

    def test_reserve_slot_unlimited(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", cooperation_remaining=None, cooperation_policy="parallel")
        out = _reserve_target_slot(cur, _fat(target_type="demand", target_id=10), 1)
        assert out["reserved"] is False
        assert out["closePending"] is False

    def test_reserve_slot_exclusive(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", cooperation_remaining=None, cooperation_policy="exclusive")
        out = _reserve_target_slot(cur, _fat(target_type="achievement", target_id=3), 1)
        assert out["closePending"] is True

    def test_reserve_slot_exhausted(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", cooperation_remaining=0)
        with pytest.raises(BizError):
            _reserve_target_slot(cur, _fat(target_type="demand", target_id=10), 1)

    def test_reserve_slot_last_one(self):
        from modules.cooperation.service import _reserve_target_slot

        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", cooperation_remaining=1, cooperation_policy="parallel")
        out = _reserve_target_slot(cur, _fat(target_type="demand", target_id=10), 1)
        assert out["reserved"] is True
        assert out["closePending"] is True

    def test_release_slot_no_reservation(self):
        from modules.cooperation.service import _release_target_slot

        cur = _cur()
        _release_target_slot(cur, _fat(slot_reserved=False), 1)
        cur.execute.assert_not_called()

    def test_release_slot_releases(self):
        from modules.cooperation.service import _release_target_slot

        cur = _cur()
        _release_target_slot(cur, _fat(slot_reserved=True, target_type="demand", target_id=10), 1)
        assert cur.execute.call_count == 2


class TestCoopCreateIntent:
    def _body(self, **kw):
        b = {"targetType": "demand", "targetId": 10, "contactShareConsent": True}
        b.update(kw)
        return b

    def test_body_not_dict(self):
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", "not-a-dict")

    def test_bad_target_type(self):
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body(targetType="bogus"))

    def test_bad_target_id(self):
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body(targetId="abc"))

    def test_no_consent(self):
        from modules.cooperation.service import create_intent

        body = self._body()
        del body["contactShareConsent"]
        with pytest.raises(BizError):
            create_intent(1, "U001", body)

    @patch("modules.cooperation.service.get_cursor")
    def test_target_not_published(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft")
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())

    @patch("modules.cooperation.service.get_cursor")
    def test_own_content(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())

    @patch("modules.cooperation.service.get_cursor")
    def test_capacity_exhausted(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=2, cooperation_remaining=0)
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())

    @patch("modules.cooperation.service.get_cursor")
    def test_exclusive_conflict(self, mock_gc):
        target = _fat(status="published", owner_user_id=2, cooperation_policy="exclusive")
        cur = _cur_sql(
            routes=[
                ("FROM demand", target),
                ("SELECT 1 FROM cooperation_intent", {"1": 1}),
            ],
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())

    @patch("modules.cooperation.service.get_cursor")
    def test_duplicate_active(self, mock_gc):
        target = _fat(status="published", owner_user_id=2)
        cur = _cur_sql(
            routes=[
                ("FROM demand", target),
                ("SELECT id FROM cooperation_intent", {"id": 99}),
            ],
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())

    @patch("modules.cooperation.service.get_cursor")
    def test_happy_path(self, mock_gc):
        target = _fat(status="published", owner_user_id=2, org_id=1, cooperation_remaining=None)
        cur = _cur_seq(target, None)  # load_target → active-check(None); rest = FAT
        _gc(mock_gc, cur)
        from modules.cooperation.service import create_intent

        out = create_intent(1, "U001", self._body(message="hi"))
        assert isinstance(out, dict)
        assert out["myRole"] == "initiator"
        assert "counterpartContact" in out

    @patch("modules.cooperation.service.get_cursor")
    def test_unique_violation(self, mock_gc):
        from psycopg2.errors import UniqueViolation

        target = _fat(status="published", owner_user_id=2, org_id=1, cooperation_remaining=None)
        cur = _cur_seq(target, None)
        _gc(mock_gc, cur)
        orig = cur.execute.side_effect
        calls = {"n": 0}

        def _exec(sql, *a, **kw):
            calls["n"] += 1
            if calls["n"] == 4:  # the INSERT INTO cooperation_intent
                raise UniqueViolation()
            return orig(sql, *a, **kw) if callable(orig) else None

        cur.execute.side_effect = _exec
        from modules.cooperation.service import create_intent

        with pytest.raises(BizError):
            create_intent(1, "U001", self._body())


class TestCoopQueries:
    @patch("modules.cooperation.service.get_cursor")
    def test_get_intent_detail(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.cooperation.service import get_intent_detail

        out = get_intent_detail(1, 1)
        assert out["id"] == 1
        assert out["myRole"] == "initiator"
        assert "counterpartContact" in out
        assert "targetSummary" in out
        assert out["platformAssisted"] is False

    @patch("modules.cooperation.service.get_cursor")
    def test_get_intent_detail_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.cooperation.service import get_intent_detail

        with pytest.raises(BizError):
            get_intent_detail(1, 1)

    @patch("modules.cooperation.service.get_cursor")
    def test_get_intent_detail_not_participant(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(initiator_user_id=2, target_owner_user_id=3)
        _gc(mock_gc, cur)
        from modules.cooperation.service import get_intent_detail

        with pytest.raises(BizError):
            get_intent_detail(1, 99)

    @patch("modules.cooperation.service.get_cursor")
    def test_list_my_intents_both(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.cooperation.service import list_my_intents

        out = list_my_intents(1, {})
        assert out["total"] == 1
        assert len(out["list"]) == 1
        assert out["totalPages"] == 1

    @patch("modules.cooperation.service.get_cursor")
    def test_list_my_intents_initiator(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.cooperation.service import list_my_intents

        out = list_my_intents(1, {"role": "initiator", "status": "pending"})
        assert out["page"] == 1

    @patch("modules.cooperation.service.get_cursor")
    def test_list_my_intents_target(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.cooperation.service import list_my_intents

        out = list_my_intents(1, {"role": "target", "page": "2", "pageSize": "5"})
        assert out["page"] == 2
        assert out["pageSize"] == 5

    def test_list_my_intents_bad_role(self):
        from modules.cooperation.service import list_my_intents

        with pytest.raises(BizError):
            list_my_intents(1, {"role": "bogus"})

    @patch("modules.cooperation.service.get_cursor")
    def test_list_events(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.cooperation.service import list_events

        out = list_events(1, 1, {"page": "1", "pageSize": "10"})
        assert out["total"] == 1
        assert out["list"][0]["eventType"] == "created"
        assert out["list"][0]["intentId"] == 1


class TestCoopAutoReject:
    @patch("modules.cooperation.service.get_cursor")
    def test_auto_reject_with_losers(self, mock_gc):
        cur = _cur_seq(rows=[{"id": 5, "initiator_user_id": 9}, {"id": 6, "initiator_user_id": 8}])
        _gc(mock_gc, cur)
        from modules.cooperation.service import _auto_reject_other_pending

        _auto_reject_other_pending(cur, _fat(target_type="demand", target_id=10), 1, 1)
        assert cur.execute.call_count >= 4  # SELECT + 2 UPDATE + 2 event INSERT

    @patch("modules.cooperation.service.get_cursor")
    def test_auto_reject_no_losers(self, mock_gc):
        cur = _cur_seq(rows=[])
        _gc(mock_gc, cur)
        from modules.cooperation.service import _auto_reject_other_pending

        _auto_reject_other_pending(cur, _fat(target_type="demand", target_id=10), 1, 1)
        assert cur.execute.call_count == 1


class TestCoopTransitions:
    # -- accept --

    @patch("modules.cooperation.service.get_cursor")
    def test_accept_intent_happy(self, mock_gc):
        intent = _fat(status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2)
        target = _fat(status="published", cooperation_remaining=None, cooperation_policy="parallel")
        cur = _cur_sql(routes=[("cooperation_intent WHERE id", intent), ("SELECT cooperation_policy", target)])
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        out = accept_intent(2, "U001", 1, 1)
        assert isinstance(out, dict)
        assert "status" in out

    @patch("modules.cooperation.service.get_cursor")
    def test_accept_intent_close_pending(self, mock_gc):
        intent = _fat(status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2)
        target = _fat(status="published", cooperation_remaining=1, cooperation_policy="exclusive")
        cur = _cur_sql(
            routes=[("cooperation_intent WHERE id", intent), ("SELECT cooperation_policy", target)],
            rows=[{"id": 9, "initiator_user_id": 99}],
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        out = accept_intent(2, "U001", 1, 1)
        assert isinstance(out, dict)

    def test_accept_version_required(self):
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(2, "U001", 1, None)

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(2, "U001", 1, 1)

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_not_participant(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(initiator_user_id=2, target_owner_user_id=3)
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(99, "U001", 1, 1)

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_assisted_target_owner_blocked(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", initiator_user_id=1, target_owner_user_id=2)
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(2, "U001", 1, 1)

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_wrong_role(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(
            status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(1, "U001", 1, 1)  # initiator cannot accept

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_wrong_status(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(
            status="accepted", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(2, "U001", 1, 1)

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_cancel_pending_not_initiator(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(
            status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import cancel_intent

        with pytest.raises(BizError):
            cancel_intent(2, "U001", 1, 1, "reason")

    @patch("modules.cooperation.service.get_cursor")
    def test_transition_version_conflict(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(
            status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2
        )
        cur.rowcount = 0
        _gc(mock_gc, cur)
        from modules.cooperation.service import accept_intent

        with pytest.raises(BizError):
            accept_intent(2, "U001", 1, 1)

    # -- reject --

    @patch("modules.cooperation.service.get_cursor")
    def test_reject_happy(self, mock_gc):
        intent = _fat(
            status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2, slot_reserved=True
        )
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import reject_intent

        out = reject_intent(2, "U001", 1, 1, "not interested")
        assert isinstance(out, dict)

    def test_reject_requires_reason(self):
        from modules.cooperation.service import reject_intent

        with pytest.raises(BizError):
            reject_intent(2, "U001", 1, 1, "")

    # -- confirm --

    @patch("modules.cooperation.service.get_cursor")
    def test_confirm_happy(self, mock_gc):
        intent = _fat(
            status="accepted", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2, target_type="demand"
        )
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import confirm_intent

        out = confirm_intent(1, "U001", 1, 1)
        assert isinstance(out, dict)

    @patch("modules.cooperation.service.get_cursor")
    def test_confirm_achievement_target(self, mock_gc):
        intent = _fat(
            status="accepted",
            handling_mode="direct",
            initiator_user_id=1,
            target_owner_user_id=2,
            target_type="achievement",
        )
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import confirm_intent

        out = confirm_intent(2, "U001", 1, 1)
        assert isinstance(out, dict)

    # -- cancel --

    @patch("modules.cooperation.service.get_cursor")
    def test_cancel_initiator_pending(self, mock_gc):
        intent = _fat(status="pending", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2)
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import cancel_intent

        out = cancel_intent(1, "U001", 1, 1, "withdrawn")
        assert isinstance(out, dict)

    # -- complete --

    @patch("modules.cooperation.service.get_cursor")
    def test_complete_with_outcome(self, mock_gc):
        intent = _fat(status="confirmed", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2)
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import complete_intent

        outcome = {
            "status": "cooperated",
            "cooperationMode": "license",
            "signed": True,
            "amountWan": 50.5,
            "failureReason": None,
            "note": "good deal",
        }
        out = complete_intent(1, "U001", 1, 1, "done", outcome=outcome)
        assert isinstance(out, dict)

    @patch("modules.cooperation.service.get_cursor")
    def test_complete_no_outcome(self, mock_gc):
        intent = _fat(status="confirmed", handling_mode="direct", initiator_user_id=1, target_owner_user_id=2)
        cur = _cur_seq(intent)
        _gc(mock_gc, cur)
        from modules.cooperation.service import complete_intent

        out = complete_intent(2, "U001", 1, 1, "done")
        assert isinstance(out, dict)

    def test_complete_bad_outcome_type(self):
        from modules.cooperation.service import complete_intent

        with pytest.raises(BizError):
            complete_intent(1, "U001", 1, 1, "done", outcome="not-a-dict")

    def test_complete_bad_outcome_status(self):
        from modules.cooperation.service import complete_intent

        with pytest.raises(BizError):
            complete_intent(1, "U001", 1, 1, "done", outcome={"status": "bogus"})

    def test_complete_negative_amount(self):
        from modules.cooperation.service import complete_intent

        with pytest.raises(BizError):
            complete_intent(1, "U001", 1, 1, "done", outcome={"status": "cooperated", "amountWan": -1})

    def test_complete_not_cooperated_needs_reason(self):
        from modules.cooperation.service import complete_intent

        with pytest.raises(BizError):
            complete_intent(1, "U001", 1, 1, "done", outcome={"status": "not_cooperated"})


class TestCoopAssist:
    def _admin(self):
        return {"userId": 1, "userNo": "A001"}

    def test_update_assist_status_bad_status(self):
        from modules.cooperation.service import update_assist_status

        with pytest.raises(BizError):
            update_assist_status(self._admin(), 1, {"assistStatus": "bogus"})

    @patch("modules.cooperation.service.get_cursor")
    def test_update_assist_status_not_assisted(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="direct")
        _gc(mock_gc, cur)
        from modules.cooperation.service import update_assist_status

        with pytest.raises(BizError):
            update_assist_status(self._admin(), 1, {"assistStatus": "contacting"})

    @patch("modules.cooperation.service.get_cursor")
    def test_update_assist_status_not_pending(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="accepted")
        _gc(mock_gc, cur)
        from modules.cooperation.service import update_assist_status

        with pytest.raises(BizError):
            update_assist_status(self._admin(), 1, {"assistStatus": "contacting"})

    @patch("modules.cooperation.service.get_cursor")
    def test_update_assist_status_bad_transition(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        _gc(mock_gc, cur)
        from modules.cooperation.service import update_assist_status

        with pytest.raises(BizError):
            update_assist_status(self._admin(), 1, {"assistStatus": "target_agreed"})

    @patch("modules.cooperation.service.get_cursor")
    def test_update_assist_status_cas_conflict(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        cur.rowcount = 0
        _gc(mock_gc, cur)
        from modules.cooperation.service import update_assist_status

        with pytest.raises(BizError):
            update_assist_status(self._admin(), 1, {"assistStatus": "contacting"})

    @patch("modules.cooperation.service.get_cursor")
    def test_update_assist_status_happy(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        _gc(mock_gc, cur)
        from modules.cooperation.service import update_assist_status

        out = update_assist_status(
            self._admin(), 1, {"assistStatus": "contacting", "note": "called", "nextFollowupAt": "2026-02-01"}
        )
        assert out["assistStatus"] == "contacting"
        assert out["status"] == "pending"

    # -- admin_assist_transition --

    def test_admin_action_bad(self):
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "bogus", "version": 1})

    def test_admin_action_no_version(self):
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "reject", "reason": "r"})

    def test_admin_reject_no_reason(self):
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "reject", "version": 1})

    def test_admin_accept_no_note(self):
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "accept", "version": 1})

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_not_assisted(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="direct")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "reject", "version": 1, "reason": "r"})

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_wrong_status(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="accepted", assist_status="target_agreed")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "reject", "version": 1, "reason": "r"})

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_accept_needs_target_agreed(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "accept", "version": 1, "confirmationNote": "ok"})

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_version_conflict(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        cur.rowcount = 0
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        with pytest.raises(BizError):
            admin_assist_transition(self._admin(), 1, {"action": "reject", "version": 1, "reason": "r"})

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_accept_happy(self, mock_gc):
        intent = _fat(handling_mode="assisted", status="pending", assist_status="target_agreed", target_type="demand")
        target = _fat(status="published", cooperation_remaining=None, cooperation_policy="parallel")
        cur = _cur_sql(routes=[("cooperation_intent WHERE id", intent), ("SELECT cooperation_policy", target)])
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        out = admin_assist_transition(
            self._admin(), 1, {"action": "accept", "version": 1, "confirmationNote": "agreed"}
        )
        assert out["status"] == "accepted"
        assert out["acceptMode"] == "platform_assisted"

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_reject_happy(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="pending", assist_status="queued")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        out = admin_assist_transition(self._admin(), 1, {"action": "reject", "version": 1, "reason": "declined"})
        assert out["status"] == "rejected"

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_confirm_demand(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="accepted", target_type="demand")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        out = admin_assist_transition(self._admin(), 1, {"action": "confirm", "version": 1})
        assert out["status"] == "confirmed"

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_cancel(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(
            handling_mode="assisted", status="accepted", target_type="achievement", slot_reserved=True
        )
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        out = admin_assist_transition(self._admin(), 1, {"action": "cancel", "version": 1, "reason": "stop"})
        assert out["status"] == "cancelled"

    @patch("modules.cooperation.service.get_cursor")
    def test_admin_complete(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(handling_mode="assisted", status="confirmed", target_type="achievement")
        _gc(mock_gc, cur)
        from modules.cooperation.service import admin_assist_transition

        out = admin_assist_transition(self._admin(), 1, {"action": "complete", "version": 1})
        assert out["status"] == "completed"


# ═════════════════════════════════════════════════════════════════════════
# modules/membership/service.py
# ═════════════════════════════════════════════════════════════════════════


class TestMembershipLists:
    @patch("modules.membership.service.get_cursor")
    def test_list_org_members(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import list_org_members

        out = list_org_members(ADMIN, 1, None, 1, 10)
        assert out["total"] == 1
        assert len(out["list"]) == 1

    @patch("modules.membership.service.get_cursor")
    def test_list_membership_applications(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import list_membership_applications

        out = list_membership_applications(ADMIN, 1, "pending", 1, 10)
        assert out["total"] == 1

    @patch("modules.membership.service.get_cursor")
    def test_list_org_records_bad_table(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import _list_org_records

        with pytest.raises(ValueError):
            _list_org_records(ADMIN, 1, "bogus_table", None, 1, 10)

    @patch("modules.membership.service.get_cursor")
    def test_list_organization_applications(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import list_organization_applications

        out = list_organization_applications(ADMIN, "pending", 1, 10)
        assert out["total"] == 1

    @patch("modules.membership.service.get_cursor")
    def test_list_organization_admin_applications(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import list_organization_admin_applications

        out = list_organization_admin_applications(ADMIN, None, 1, 10)
        assert out["total"] == 1

    @patch("modules.membership.service.get_cursor")
    def test_list_system_applications_bad_table(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.membership.service import _list_system_applications

        with pytest.raises(ValueError):
            _list_system_applications(ADMIN, "bogus", None, 1, 10)


class TestMembershipActivate:
    def test_activate_no_existing(self):
        from modules.membership.service import _activate_membership

        cur = _cur_seq(None)  # no existing → INSERT
        row = _activate_membership(cur, 2, 1, "member", 1)
        assert row["role"] == "member"

    def test_activate_promote_admin(self):
        from modules.membership.service import _activate_membership

        existing = _fat(id=5, role="member", status="active", version=1)
        cur = _cur_seq(existing, _fat(id=5, role="admin", status="active", version=2))
        row = _activate_membership(cur, 2, 1, "admin", 1)
        assert row["role"] == "admin"

    def test_activate_revoked_reinstated(self):
        from modules.membership.service import _activate_membership

        existing = _fat(id=5, role="member", status="revoked", version=3)
        cur = _cur_seq(existing, _fat(id=5, role="member", status="active", version=4))
        row = _activate_membership(cur, 2, 1, "member", 1)
        assert row["status"] == "active"

    def test_activate_duplicate_member(self):
        from modules.membership.service import _activate_membership

        existing = _fat(role="member", status="active")
        cur = _cur_seq(existing)
        with pytest.raises(BizError):
            _activate_membership(cur, 2, 1, "member", 1)

    def test_activate_same_role_conflict(self):
        from modules.membership.service import _activate_membership

        existing = _fat(role="admin", status="active")
        cur = _cur_seq(existing)
        with pytest.raises(BizError):
            _activate_membership(cur, 2, 1, "admin", 1)

    def test_activate_stale_version(self):
        from modules.membership.service import _activate_membership

        existing = _fat(role="member", status="active", version=1)
        cur = _cur_seq(existing, None)  # UPDATE returns nothing
        with pytest.raises(BizError):
            _activate_membership(cur, 2, 1, "admin", 1)

    def test_activate_insert_returns_none(self):
        from modules.membership.service import _activate_membership

        cur = _cur_seq(None, None)  # no existing; INSERT RETURNING gives None
        with pytest.raises(BizError):
            _activate_membership(cur, 2, 1, "member", 1)

    def test_activate_revoked_update_returns_none(self):
        from modules.membership.service import _activate_membership

        existing = _fat(role="member", status="revoked", version=3)
        cur = _cur_seq(existing, None)  # UPDATE RETURNING gives None
        with pytest.raises(BizError):
            _activate_membership(cur, 2, 1, "member", 1)


class TestMembershipApprove:
    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_approve_membership_application(self, mock_tx, mock_ac):
        application = _fat(id=10, user_id=2, org_id=1, department="R&D", title="Eng")
        reviewed = _fat(id=10, user_id=2, org_id=1, status="approved", version=2)
        membership = _fat(id=5, user_id=2, org_id=1, role="member", status="active", version=1)
        cur = _cur_seq(application, _fat(), reviewed, None, membership)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_membership_application

        out = approve_membership_application(ADMIN, 10, 1)
        assert out["status"] == "approved"
        assert out["membership"]["role"] == "member"

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_approve_not_found(self, mock_tx, mock_ac):
        cur = _cur_seq(None)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_membership_application

        with pytest.raises(BizError):
            approve_membership_application(ADMIN, 10, 1)

    @patch("modules.membership.service.transaction")
    def test_approve_version_conflict(self, mock_tx):
        application = _fat(id=10, user_id=2, org_id=1, department="R&D", title="Eng")
        cur = _cur_seq(application, _fat(), None)  # reviewed=None → conflict
        _tx(mock_tx, cur)
        from modules.membership.service import approve_membership_application

        with pytest.raises(BizError):
            approve_membership_application(ADMIN, 10, 1)

    @patch("modules.membership.service.transaction")
    def test_reject_membership_application(self, mock_tx):
        application = _fat(id=10, user_id=2, org_id=1)
        reviewed = _fat(id=10, user_id=2, org_id=1, status="rejected", version=2)
        cur = _cur_seq(application, _fat(), reviewed)
        _tx(mock_tx, cur)
        from modules.membership.service import reject_membership_application

        out = reject_membership_application(ADMIN, 10, 1, "bad fit")
        assert out["status"] == "rejected"

    def test_reject_requires_reason(self):
        from modules.membership.service import reject_membership_application

        with pytest.raises(BizError):
            reject_membership_application(ADMIN, 10, 1, "  ")

    @patch("modules.membership.service.transaction")
    def test_reject_not_found(self, mock_tx):
        cur = _cur_seq(None)
        _tx(mock_tx, cur)
        from modules.membership.service import reject_membership_application

        with pytest.raises(BizError):
            reject_membership_application(ADMIN, 10, 1, "r")

    @patch("modules.membership.service.transaction")
    def test_reject_version_conflict(self, mock_tx):
        application = _fat(id=10, user_id=2, org_id=1)
        cur = _cur_seq(application, _fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import reject_membership_application

        with pytest.raises(BizError):
            reject_membership_application(ADMIN, 10, 1, "r")


class TestMembershipRevoke:
    @patch("modules.membership.service.transaction")
    def test_revoke_membership(self, mock_tx):
        membership = _fat(id=5, user_id=2, org_id=1, role="member")
        revoked = _fat(id=5, user_id=2, org_id=1, role="member", status="revoked", version=2)
        cur = _cur_seq(membership, _fat(), revoked)
        _tx(mock_tx, cur)
        from modules.membership.service import revoke_membership

        out = revoke_membership(ADMIN, 5, 1, "violation")
        assert out["status"] == "revoked"

    def test_revoke_requires_reason(self):
        from modules.membership.service import revoke_membership

        with pytest.raises(BizError):
            revoke_membership(ADMIN, 5, 1, "")

    @patch("modules.membership.service.transaction")
    def test_revoke_not_found(self, mock_tx):
        cur = _cur_seq(None)
        _tx(mock_tx, cur)
        from modules.membership.service import revoke_membership

        with pytest.raises(BizError):
            revoke_membership(ADMIN, 5, 1, "r")

    @patch("modules.membership.service.transaction")
    def test_revoke_version_conflict(self, mock_tx):
        membership = _fat(id=5, user_id=2, org_id=1, role="member")
        cur = _cur_seq(membership, _fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import revoke_membership

        with pytest.raises(BizError):
            revoke_membership(ADMIN, 5, 1, "r")


class TestOrgAdminFlows:
    @patch("modules.membership.service.transaction")
    def test_apply_organization_admin(self, mock_tx):
        cur = _cur_seq(_fat(), None, None, _fat(id=20, user_id=1, org_id=1, status="pending", version=1))
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization_admin

        out = apply_organization_admin(USER, {"orgId": 1, "realName": "张三", "reason": "want admin"})
        assert out["status"] == "pending"

    @patch("modules.membership.service.transaction")
    def test_apply_org_admin_not_found(self, mock_tx):
        cur = _cur_seq(None)
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization_admin

        with pytest.raises(BizError):
            apply_organization_admin(USER, {"orgId": 99})

    @patch("modules.membership.service.transaction")
    def test_apply_org_admin_already_admin(self, mock_tx):
        cur = _cur_seq(_fat(), _fat())
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization_admin

        with pytest.raises(BizError):
            apply_organization_admin(USER, {"orgId": 1})

    @patch("modules.membership.service.transaction")
    def test_apply_org_admin_duplicate(self, mock_tx):
        cur = _cur_seq(_fat(), None, _fat())
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization_admin

        with pytest.raises(BizError):
            apply_organization_admin(USER, {"orgId": 1})

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_approve_org_admin_application(self, mock_tx, mock_ac):
        application = _fat(id=20, user_id=2, org_id=1, department="D", title="T")
        reviewed = _fat(id=20, user_id=2, org_id=1, status="approved", version=2)
        membership = _fat(id=6, user_id=2, org_id=1, role="admin", status="active", version=1)
        cur = _cur_seq(_fat(), application, reviewed, None, membership)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_admin_application

        out = approve_organization_admin_application(ADMIN, 20, 1)
        assert out["status"] == "approved"
        assert out["membership"]["role"] == "admin"

    @patch("modules.membership.service.transaction")
    def test_approve_org_admin_not_found(self, mock_tx):
        cur = _cur_seq(_fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_admin_application

        with pytest.raises(BizError):
            approve_organization_admin_application(ADMIN, 20, 1)

    @patch("modules.membership.service.transaction")
    def test_approve_org_admin_version_conflict(self, mock_tx):
        application = _fat(id=20, user_id=2, org_id=1)
        cur = _cur_seq(_fat(), application, None)  # reviewed=None → conflict
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_admin_application

        with pytest.raises(BizError):
            approve_organization_admin_application(ADMIN, 20, 1)

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_grant_organization_admin(self, mock_tx, mock_ac):
        granted = _fat(id=5, user_id=2, org_id=1, role="admin", status="active", version=2)
        cur = _cur_seq(_fat(), granted)
        _tx(mock_tx, cur)
        from modules.membership.service import grant_organization_admin

        out = grant_organization_admin(ADMIN, 5, 1)
        assert out["role"] == "admin"

    @patch("modules.membership.service.transaction")
    def test_grant_version_conflict(self, mock_tx):
        cur = _cur_seq(_fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import grant_organization_admin

        with pytest.raises(BizError):
            grant_organization_admin(ADMIN, 5, 1)

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_revoke_organization_admin(self, mock_tx, mock_ac):
        revoked = _fat(id=5, user_id=2, org_id=1, role="admin", status="revoked", version=2)
        cur = _cur_seq(_fat(), revoked)
        _tx(mock_tx, cur)
        from modules.membership.service import revoke_organization_admin

        out = revoke_organization_admin(ADMIN, 5, 1, "abuse")
        assert out["status"] == "revoked"

    def test_revoke_org_admin_requires_reason(self):
        from modules.membership.service import revoke_organization_admin

        with pytest.raises(BizError):
            revoke_organization_admin(ADMIN, 5, 1, " ")

    @patch("modules.membership.service.transaction")
    def test_revoke_org_admin_conflict(self, mock_tx):
        cur = _cur_seq(_fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import revoke_organization_admin

        with pytest.raises(BizError):
            revoke_organization_admin(ADMIN, 5, 1, "r")


class TestOrgApplications:
    @patch("modules.membership.service.transaction")
    def test_apply_organization(self, mock_tx):
        application = _fat(id=30, applicant_user_id=1, status="pending", version=1)
        cur = _cur_seq(None, None, application)
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization

        out = apply_organization(
            USER,
            {
                "requestedName": "New Org",
                "contactPhone": "13800138000",
                "contactEmail": "test@example.com",
                "contactName": "张三",
            },
        )
        assert out["status"] == "pending"

    @patch("modules.membership.service.transaction")
    def test_apply_org_pending_exists(self, mock_tx):
        cur = _cur_seq(_fat())
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization

        with pytest.raises(BizError):
            apply_organization(USER, {"requestedName": "X", "contactPhone": "13800138000"})

    @patch("modules.membership.service.transaction")
    def test_apply_org_name_exists(self, mock_tx):
        cur = _cur_seq(None, _fat())
        _tx(mock_tx, cur)
        from modules.membership.service import apply_organization

        with pytest.raises(BizError):
            apply_organization(USER, {"requestedName": "X", "contactPhone": "13800138000"})

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_approve_organization_application(self, mock_tx, mock_ac):
        application = _fat(
            id=30,
            applicant_user_id=2,
            requested_name="New Org",
            requested_type="enterprise",
            region="深圳",
            credit_code="9111",
        )
        reviewed = _fat(id=30, applicant_user_id=2, status="approved", version=2)
        org = {"id": 42}
        membership = _fat(id=7, user_id=2, org_id=42, role="admin", status="active", version=1)
        cur = _cur_seq(_fat(), application, reviewed, None, org, None, membership)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_application

        out = approve_organization_application(ADMIN, 30, 1)
        assert out["orgId"] == 42
        assert out["membership"]["role"] == "admin"

    @patch("modules.membership.service.transaction")
    def test_approve_org_app_not_found(self, mock_tx):
        cur = _cur_seq(_fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_application

        with pytest.raises(BizError):
            approve_organization_application(ADMIN, 30, 1)

    @patch("modules.membership.service.transaction")
    def test_approve_org_app_version_conflict(self, mock_tx):
        application = _fat(id=30, applicant_user_id=2, requested_name="Org", requested_type="enterprise")
        cur = _cur_seq(_fat(), application, None)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_application

        with pytest.raises(BizError):
            approve_organization_application(ADMIN, 30, 1)

    @patch("modules.membership.service.transaction")
    def test_approve_org_app_name_conflict(self, mock_tx):
        application = _fat(id=30, applicant_user_id=2, requested_name="Dup", requested_type="enterprise")
        reviewed = _fat(id=30, applicant_user_id=2, status="approved", version=2)
        cur = _cur_seq(_fat(), application, reviewed, _fat())  # name check → truthy → conflict
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_application

        with pytest.raises(BizError):
            approve_organization_application(ADMIN, 30, 1)

    @patch("modules.membership.service.auth_cache")
    @patch("modules.membership.service.transaction")
    def test_approve_org_app_invalid_kind(self, mock_tx, mock_ac):
        application = _fat(
            id=30, applicant_user_id=2, requested_name="OrgX", requested_type="bogus_kind", region="R", credit_code="C"
        )
        reviewed = _fat(id=30, applicant_user_id=2, status="approved", version=2)
        org = {"id": 55}
        membership = _fat(id=8, user_id=2, org_id=55, role="admin", status="active", version=1)
        cur = _cur_seq(_fat(), application, reviewed, None, org, None, membership)
        _tx(mock_tx, cur)
        from modules.membership.service import approve_organization_application

        out = approve_organization_application(ADMIN, 30, 1)
        assert out["orgId"] == 55

    @patch("modules.membership.service.transaction")
    def test_reject_org_application(self, mock_tx):
        application = _fat(id=30, applicant_user_id=2)
        reviewed = _fat(id=30, applicant_user_id=2, status="rejected", version=2)
        cur = _cur_seq(_fat(), application, reviewed)
        _tx(mock_tx, cur)
        from modules.membership.service import reject_organization_application

        out = reject_organization_application(ADMIN, 30, 1, "not real")
        assert out["status"] == "rejected"

    @patch("modules.membership.service.transaction")
    def test_reject_org_admin_application(self, mock_tx):
        application = _fat(id=20, user_id=2, org_id=1)
        reviewed = _fat(id=20, user_id=2, org_id=1, status="rejected", version=2)
        cur = _cur_seq(_fat(), application, reviewed)
        _tx(mock_tx, cur)
        from modules.membership.service import reject_organization_admin_application

        out = reject_organization_admin_application(ADMIN, 20, 1, "no proof")
        assert out["status"] == "rejected"

    def test_reject_system_requires_reason(self):
        from modules.membership.service import _reject_system_application

        with pytest.raises(BizError):
            _reject_system_application(ADMIN, "organization_application", 1, 1, "", "msg", "action")

    def test_reject_system_bad_table(self):
        from modules.membership.service import _reject_system_application

        with pytest.raises(ValueError):
            _reject_system_application(ADMIN, "bogus_table", 1, 1, "r", "msg", "action")

    @patch("modules.membership.service.transaction")
    def test_reject_system_not_found(self, mock_tx):
        cur = _cur_seq(_fat(), None)
        _tx(mock_tx, cur)
        from modules.membership.service import _reject_system_application

        with pytest.raises(BizError):
            _reject_system_application(ADMIN, "organization_application", 1, 1, "r", "not found", "action")

    @patch("modules.membership.service.transaction")
    def test_reject_system_version_conflict(self, mock_tx):
        application = _fat(id=1, applicant_user_id=2)
        cur = _cur_seq(_fat(), application, None)
        _tx(mock_tx, cur)
        from modules.membership.service import _reject_system_application

        with pytest.raises(BizError):
            _reject_system_application(ADMIN, "organization_application", 1, 1, "r", "msg", "action")


# ═════════════════════════════════════════════════════════════════════════
# modules/demand/service.py
# ═════════════════════════════════════════════════════════════════════════


class TestDemandHelpers:
    def test_validate_refs_ok(self):
        from modules.demand.service import _validate_refs

        cur = _cur()
        _validate_refs(cur, {"category_id": 1, "org_id": 1})

    def test_validate_refs_bad_category(self):
        from modules.demand.service import _validate_refs

        cur = _cur()
        cur.fetchone.return_value = None
        with pytest.raises(BizError):
            _validate_refs(cur, {"category_id": 99})

    def test_validate_refs_bad_org(self):
        from modules.demand.service import _validate_refs

        cur = _cur()
        cur.fetchone.return_value = None
        with pytest.raises(BizError):
            _validate_refs(cur, {"org_id": 99})

    def test_resolve_name_refs_no_mutate(self):
        from modules.demand.service import _resolve_name_refs

        cur = _cur()
        fields = {"org_name_snapshot": "X", "org_intro": "I"}
        _resolve_name_refs(cur, fields, allow_org_mutate=False)
        assert "org_name_snapshot" not in fields

    def test_resolve_name_refs_intro_without_name(self):
        from modules.demand.service import _resolve_name_refs

        cur = _cur()
        with pytest.raises(BizError):
            _resolve_name_refs(cur, {"org_intro": "I"}, allow_org_mutate=True)

    def test_resolve_name_refs_existing_org(self):
        from modules.demand.service import _resolve_name_refs

        cur = _cur()
        cur.fetchone.return_value = {"id": 5}
        fields = {"org_name_snapshot": "X", "org_intro": "I"}
        _resolve_name_refs(cur, fields, allow_org_mutate=True)
        assert fields["org_id"] == 5

    def test_resolve_name_refs_new_org(self):
        from modules.demand.service import _resolve_name_refs

        cur = _cur_seq(None, {"id": 9})
        fields = {"org_name_snapshot": "BrandNew"}
        _resolve_name_refs(cur, fields, allow_org_mutate=True)
        assert fields["org_id"] == 9

    def test_sync_tags_none(self):
        from modules.demand.service import _sync_tags

        cur = _cur()
        _sync_tags(cur, 1, None)
        cur.execute.assert_not_called()

    def test_sync_tags_creates(self):
        from modules.demand.service import _sync_tags

        cur = _cur_seq(None, {"id": 5})
        _sync_tags(cur, 1, ["ai", "ai", " ml "])
        assert cur.execute.call_count >= 4  # DELETE + SELECT + INSERT + INSERT relation

    def test_load_attachments(self):
        from modules.demand.service import _load_attachments

        cur = _cur()
        rows = [_fat(file_id=3, original_name="a.pdf", mime_type="application/pdf", size_bytes=2048)]
        cur.fetchall.return_value = rows
        out = _load_attachments(cur, 1)
        assert out[0]["fileId"] == 3
        assert out[0]["name"] == "a.pdf"

    def test_sync_attachments_none(self):
        from modules.demand.service import _sync_attachments

        cur = _cur()
        _sync_attachments(cur, 1, 1, None)
        cur.execute.assert_not_called()

    def test_sync_attachments_missing_file(self):
        from modules.demand.service import _sync_attachments

        cur = _cur()
        cur.fetchall.return_value = []  # no matching files
        with pytest.raises(BizError):
            _sync_attachments(cur, 1, 1, [{"fileId": 1, "role": "attachment", "sort": 0, "caption": None}])

    def test_sync_attachments_ok(self):
        from modules.demand.service import _sync_attachments

        cur = _cur()
        cur.fetchall.return_value = [{"id": 1}]
        _sync_attachments(cur, 1, 1, [{"fileId": 1, "role": "attachment", "sort": 0, "caption": "c"}])
        assert cur.execute.call_count == 3  # SELECT + DELETE + INSERT


class TestDemandListAndDetail:
    @patch("modules.demand.service.get_cursor")
    def test_list_demands(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import list_demands

        out = list_demands({"keyword": "ai", "categoryCode": "tech", "includeMine": "1"}, 1)
        assert out["total"] == 1
        assert out["list"][0]["title"] == "t"

    @patch("modules.demand.service.get_cursor")
    def test_list_my_demands_with_status(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import list_my_demands

        out = list_my_demands(1, {"status": "draft"})
        assert out["total"] == 1

    @patch("modules.demand.service.get_cursor")
    def test_get_demand_detail_published(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import get_demand_detail

        out = get_demand_detail(1, 1)
        assert out["id"] == 1
        assert out["isMine"] is True

    @patch("modules.demand.service.get_cursor")
    def test_get_demand_detail_draft_owner(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import get_demand_detail

        out = get_demand_detail(1, 1)
        assert out["status"] == "draft"

    @patch("modules.demand.service.get_cursor")
    def test_get_demand_detail_not_owner_hidden(self, mock_gc):
        cur = _cur_seq(_fat(status="draft", owner_user_id=2), None)  # dock_party → None
        _gc(mock_gc, cur)
        from modules.demand.service import get_demand_detail

        with pytest.raises(BizError):
            get_demand_detail(1, 99)

    @patch("modules.demand.service.get_cursor")
    def test_get_demand_detail_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.demand.service import get_demand_detail

        with pytest.raises(BizError):
            get_demand_detail(1, 1)


class TestDemandCreate:
    def _body(self, **kw):
        b = {"title": "Need AI", "description": "Looking for AI solution"}
        b.update(kw)
        return b

    @patch("modules.demand.service.get_cursor")
    def test_create_happy(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import create_demand

        out = create_demand(1, "U001", self._body(ownerUserId=999))  # covers warning line
        assert out["title"] == "t"  # from FAT row in get_demand_detail
        assert "contactPhone" in out

    @patch("modules.demand.service.get_cursor")
    def test_create_with_refs(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import create_demand

        body = self._body(categoryId=1, orgId=1, categoryName="tech", budgetMinWan=1, budgetMaxWan=10)
        out = create_demand(1, "U001", body)
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_create_budget_order(self, mock_gc):
        cur = _cur()
        _gc(mock_gc, cur)
        from modules.demand.service import create_demand

        with pytest.raises(BizError):
            create_demand(1, "U001", self._body(budgetMinWan=100, budgetMaxWan=1))

    @patch("modules.demand.service.get_cursor")
    def test_create_with_tags_attachments(self, mock_gc):
        cur = _cur_sql(routes=[])
        _gc(mock_gc, cur)
        from modules.demand.service import create_demand

        body = self._body(tags=["ai", "ml"], attachments=[{"fileId": 1, "role": "image", "caption": "pic"}])
        out = create_demand(1, "U001", body)
        assert isinstance(out, dict)


class TestDemandUpdate:
    @patch("modules.demand.service.get_cursor")
    def test_update_happy(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1, cooperation_capacity=None, cooperation_remaining=None)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"title": "updated", "version": 1})
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_update_requires_version(self, mock_gc):
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"title": "x"})

    @patch("modules.demand.service.get_cursor")
    def test_update_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_not_owner(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft", owner_user_id=2)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_wrong_status(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_capacity_delta(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1, cooperation_capacity=5, cooperation_remaining=3)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"cooperationCapacity": 8, "version": 1})
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_update_capacity_none(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1, cooperation_capacity=5, cooperation_remaining=3)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"cooperationCapacity": None, "version": 1})
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_update_capacity_new(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1, cooperation_capacity=None, cooperation_remaining=None)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"cooperationCapacity": 3, "version": 1})
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_update_tags_only(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"tags": ["a"], "version": 1})
        assert isinstance(out, dict)

    @patch("modules.demand.service.get_cursor")
    def test_update_version_conflict(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1)
        cur = _cur_seq(row, rowcount=0)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_tags_version_conflict(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1)
        cur = _cur_seq(row, rowcount=0)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"tags": ["a"], "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_budget_order(self, mock_gc):
        from modules.demand.service import update_demand

        with pytest.raises(BizError):
            update_demand(1, "U001", 1, {"budgetMinWan": 100, "budgetMaxWan": 1, "version": 1})

    @patch("modules.demand.service.get_cursor")
    def test_update_with_org_id(self, mock_gc):
        row = _fat(status="draft", owner_user_id=1)
        cur = _cur_seq(row)
        _gc(mock_gc, cur)
        from modules.demand.service import update_demand

        out = update_demand(1, "U001", 1, {"orgId": 1, "version": 1})
        assert isinstance(out, dict)


class TestDemandTransition:
    @patch("modules.demand.service.get_cursor")
    def test_submit_demand(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import submit_demand

        out = submit_demand(1, "U001", 1, 1)
        assert out["status"] == "pending_review"

    @patch("modules.demand.service.get_cursor")
    def test_cancel_demand(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import cancel_demand

        out = cancel_demand(1, "U001", 1, 1, "no_longer_needed", "done")
        assert out["status"] == "cancelled"

    @patch("modules.demand.service.get_cursor")
    def test_close_demand(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="matched", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import close_demand

        out = close_demand(1, "U001", 1, 1, "fulfilled", "done")
        assert out["status"] == "closed"

    def test_transition_requires_version(self):
        from modules.demand.service import submit_demand

        with pytest.raises(BizError):
            submit_demand(1, "U001", 1, None)

    @patch("modules.demand.service.get_cursor")
    def test_transition_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.demand.service import submit_demand

        with pytest.raises(BizError):
            submit_demand(1, "U001", 1, 1)

    @patch("modules.demand.service.get_cursor")
    def test_transition_not_owner(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft", owner_user_id=2)
        _gc(mock_gc, cur)
        from modules.demand.service import submit_demand

        with pytest.raises(BizError):
            submit_demand(1, "U001", 1, 1)

    @patch("modules.demand.service.get_cursor")
    def test_transition_wrong_status(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import submit_demand

        with pytest.raises(BizError):
            submit_demand(1, "U001", 1, 1)

    @patch("modules.demand.service.get_cursor")
    def test_transition_bad_reason_code(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="published", owner_user_id=1)
        _gc(mock_gc, cur)
        from modules.demand.service import cancel_demand

        with pytest.raises(BizError):
            cancel_demand(1, "U001", 1, 1, "bogus_reason", "note")

    @patch("modules.demand.service.get_cursor")
    def test_transition_version_conflict(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(status="draft", owner_user_id=1)
        cur.rowcount = 0
        _gc(mock_gc, cur)
        from modules.demand.service import submit_demand

        with pytest.raises(BizError):
            submit_demand(1, "U001", 1, 1)


# ═════════════════════════════════════════════════════════════════════════
# modules/file/service.py
# ═════════════════════════════════════════════════════════════════════════


class TestFileUpload:
    def _settings_patch(self, tmp_path):
        return patch("modules.file.service.settings")

    @patch("modules.file.service.get_cursor")
    def test_create_uploaded_file(self, mock_gc, tmp_path):
        cur = _cur()
        cur.fetchone.return_value = {"id": 42, "created_at": datetime(2026, 1, 1)}
        _gc(mock_gc, cur)
        from modules.file.service import create_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            mock_settings.MEDIA_BASE_URL = "/api/files"
            data = _png_bytes()
            out = create_uploaded_file(1, "test.png", "image/png", data)
        assert out["id"] == 42
        assert out["mimeType"] == "image/png"
        assert out["sizeBytes"] == len(data)
        assert out["width"] == 10

    @patch("modules.file.service.get_cursor")
    def test_create_upload_pdf(self, mock_gc, tmp_path):
        cur = _cur()
        cur.fetchone.return_value = {"id": 43, "created_at": datetime(2026, 1, 1)}
        _gc(mock_gc, cur)
        from modules.file.service import create_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            mock_settings.MEDIA_BASE_URL = "/api/files"
            out = create_uploaded_file(1, "doc.pdf", "application/pdf", b"%PDF-1.4 test")
        assert out["mimeType"] == "application/pdf"

    def test_create_upload_too_large(self, tmp_path):
        from modules.file.service import create_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            mock_settings.MAX_UPLOAD_BYTES = 10
            with pytest.raises(BizError):
                create_uploaded_file(1, "big.png", "image/png", _png_bytes())

    def test_validate_bad_extension(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("evil.exe", "application/octet-stream", b"data")

    def test_validate_empty(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("test.png", "image/png", b"")

    def test_validate_bad_image_signature(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("test.png", "image/png", b"\x89PNG\r\n\x1a\n" + b"garbage")

    def test_validate_wrong_image_magic(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("test.png", "image/png", b"JPEGDATA_not_png")

    def test_validate_webp_wrong_header(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("test.webp", "image/webp", b"RIFF\x00\x00\x00\x00XXXX")

    def test_validate_declared_mime_mismatch(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("doc.pdf", "text/plain", b"%PDF-1.4")

    def test_validate_pdf_bad_magic(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload("doc.pdf", "application/pdf", b"not a pdf")

    def test_validate_office_bad_magic(self):
        from modules.file.service import _validate_upload

        with pytest.raises(BizError):
            _validate_upload(
                "doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"XX"
            )

    def test_validate_office_ok(self):
        from modules.file.service import _validate_upload

        suffix, _mime = _validate_upload(
            "doc.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", b"PK\x03\x04data"
        )
        assert suffix == ".docx"


class TestFileThumbnail:
    def test_thumbnail_path(self, tmp_path):
        from modules.file.service import thumbnail_path_for_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            p = thumbnail_path_for_file(5)
        assert p.name == "5.jpg"

    def test_get_thumbnail_non_image(self, tmp_path):
        from modules.file.service import get_uploaded_thumbnail

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            with pytest.raises(BizError):
                get_uploaded_thumbnail(tmp_path / "x", "application/pdf", 1)

    def test_get_thumbnail_generates(self, tmp_path):
        from modules.file.service import get_uploaded_thumbnail

        src = tmp_path / "src.png"
        src.write_bytes(_png_bytes())
        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            thumb, mime = get_uploaded_thumbnail(src, "image/png", 1)
        assert mime == "image/jpeg"
        assert thumb.exists()

    def test_get_thumbnail_grayscale(self, tmp_path):
        """Cover the non-RGB branch of _write_thumbnail (lines 134-135)."""
        from modules.file.service import get_uploaded_thumbnail

        src = tmp_path / "gray.png"
        src.write_bytes(_png_bytes(mode="L"))
        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            thumb, _mime = get_uploaded_thumbnail(src, "image/png", 2)
        assert thumb.exists()

    def test_get_thumbnail_rgba(self, tmp_path):
        """Cover the RGBA/P-transparency branch of _write_thumbnail (lines 130-133)."""
        from modules.file.service import get_uploaded_thumbnail

        src = tmp_path / "alpha.png"
        src.write_bytes(_png_bytes(mode="RGBA"))
        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            thumb, _mime = get_uploaded_thumbnail(src, "image/png", 4)
        assert thumb.exists()

    def test_get_thumbnail_bad_image(self, tmp_path):
        from modules.file.service import get_uploaded_thumbnail

        src = tmp_path / "bad.png"
        src.write_bytes(b"not an image")
        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = tmp_path
            with pytest.raises(BizError):
                get_uploaded_thumbnail(src, "image/png", 3)


class TestFileAccess:
    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_owner(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        key = "1/abc.png"
        fpath = media / key
        fpath.parent.mkdir(parents=True)
        fpath.write_bytes(_png_bytes())
        cur = _cur()
        cur.fetchone.return_value = _fat(
            id=1, storage_key=key, original_name="a.png", mime_type="image/png", created_by=1
        )
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            _path, mime, name = get_uploaded_file(1, 1)
        assert name == "a.png"
        assert mime == "image/png"

    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with pytest.raises(BizError):
            get_uploaded_file(1, 1)

    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_public_ok(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        key = "1/xyz.png"
        fpath = media / key
        fpath.parent.mkdir(parents=True)
        fpath.write_bytes(_png_bytes())
        cur = _cur_seq(
            _fat(id=1, storage_key=key, original_name="a.png", mime_type="image/png", created_by=2),
            {"1": 1},  # readable check passes
        )
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            _path, _mime, name = get_uploaded_file(1, 1)
        assert name == "a.png"

    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_forbidden(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        cur = _cur_seq(_fat(id=1, storage_key="x.png", created_by=2), None)  # not readable
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            with pytest.raises(BizError):
                get_uploaded_file(1, 1)

    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_admin_import(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        key = "1/abc.png"
        fpath = media / key
        fpath.parent.mkdir(parents=True)
        fpath.write_bytes(_png_bytes())
        cur = _cur_seq(
            _fat(id=1, storage_key=key, original_name="a.png", mime_type="image/png", created_by=2),
            None,  # first readability check fails
            {"1": 1},  # import-staged check passes
        )
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            _path, _mime, name = get_uploaded_file(1, 1, can_review_import_media=True)
        assert name == "a.png"

    @patch("modules.file.service.get_cursor")
    def test_get_uploaded_file_path_escape(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        cur = _cur()
        cur.fetchone.return_value = _fat(id=1, storage_key="../escape.png", created_by=1, mime_type="image/png")
        _gc(mock_gc, cur)
        from modules.file.service import get_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            with pytest.raises(BizError):
                get_uploaded_file(1, 1)


class TestFileDelete:
    @patch("modules.file.service.get_cursor")
    def test_delete_uploaded_file(self, mock_gc, tmp_path):
        media = tmp_path / "media"
        media.mkdir()
        key = "1/abc.png"
        fpath = media / key
        fpath.parent.mkdir(parents=True)
        fpath.write_bytes(_png_bytes())
        cur = _cur_seq(_fat(storage_key=key, created_by=1), {"linked": False})
        _gc(mock_gc, cur)
        from modules.file.service import delete_uploaded_file

        with patch("modules.file.service.settings") as mock_settings:
            mock_settings.media_root_path = media
            delete_uploaded_file(1, 1)
        assert not fpath.exists()

    @patch("modules.file.service.get_cursor")
    def test_delete_not_found(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _gc(mock_gc, cur)
        from modules.file.service import delete_uploaded_file

        with pytest.raises(BizError):
            delete_uploaded_file(1, 1)

    @patch("modules.file.service.get_cursor")
    def test_delete_not_owner(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = _fat(storage_key="x", created_by=2)
        _gc(mock_gc, cur)
        from modules.file.service import delete_uploaded_file

        with pytest.raises(BizError):
            delete_uploaded_file(1, 1)

    @patch("modules.file.service.get_cursor")
    def test_delete_linked(self, mock_gc):
        cur = _cur_seq(_fat(storage_key="x", created_by=1), {"linked": True})
        _gc(mock_gc, cur)
        from modules.file.service import delete_uploaded_file

        with pytest.raises(BizError):
            delete_uploaded_file(1, 1)


class TestFileProxy:
    def test_proxy_invalid_id(self, tmp_path):
        from modules.file.service import FileProxyError, proxy_file

        with patch("modules.file.service.LOGO_CACHE", tmp_path):
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("@#$")
        assert exc_info.value.http_status == 400

    def test_proxy_cached(self, tmp_path):
        from modules.file.service import proxy_file

        cached = tmp_path / "abc123.png"
        cached.write_bytes(_png_bytes())
        with patch("modules.file.service.LOGO_CACHE", tmp_path):
            path, mime = proxy_file("abc123")
        assert path == cached
        assert mime == "image/png"

    def test_proxy_fetch_ok(self, tmp_path):
        from modules.file.service import proxy_file

        content = _jpeg_bytes()
        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/jpeg"}
        mock_resp.read.side_effect = [content, b""]
        mock_urlopen = MagicMock()
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            mock_settings.MAX_PROXY_BYTES = None
            path, mime = proxy_file("xyz789")
        assert mime == "image/jpeg"
        assert path.exists()

    def test_proxy_empty_content(self, tmp_path):
        from modules.file.service import FileProxyError, proxy_file

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.side_effect = [b""]
        mock_urlopen = MagicMock()
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("id1")
        assert exc_info.value.http_status == 404

    def test_proxy_too_large(self, tmp_path):
        from modules.file.service import FileProxyError, proxy_file

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.side_effect = [b"x" * 200]
        mock_urlopen = MagicMock()
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 1
            mock_settings.MAX_PROXY_BYTES = 10
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("big1")
        assert exc_info.value.http_status == 413

    def test_proxy_http_error(self, tmp_path):
        import urllib.error

        from modules.file.service import FileProxyError, proxy_file

        mock_urlopen = MagicMock()
        mock_urlopen.side_effect = urllib.error.HTTPError("https://x", 500, "err", {}, None)
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("err1")
        assert exc_info.value.http_status == 502

    def test_proxy_generic_error(self, tmp_path):
        from modules.file.service import FileProxyError, proxy_file

        mock_urlopen = MagicMock()
        mock_urlopen.side_effect = ConnectionError("net down")
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 20 * 1024 * 1024
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("err2")
        assert exc_info.value.http_status == 502

    def test_proxy_file_proxy_error_passthrough(self, tmp_path):
        from modules.file.service import FileProxyError, proxy_file

        mock_resp = MagicMock()
        mock_resp.headers = {"Content-Type": "image/png"}
        mock_resp.read.side_effect = [b"y" * 200]
        mock_urlopen = MagicMock()
        mock_urlopen.return_value.__enter__ = MagicMock(return_value=mock_resp)
        mock_urlopen.return_value.__exit__ = MagicMock(return_value=False)
        with (
            patch("modules.file.service.LOGO_CACHE", tmp_path),
            patch("modules.file.service.settings") as mock_settings,
            patch("urllib.request.urlopen", mock_urlopen),
        ):
            mock_settings.SZTE_FILE_URL = "https://example.com/{file_id}"
            mock_settings.MAX_UPLOAD_BYTES = 1
            mock_settings.MAX_PROXY_BYTES = 10
            with pytest.raises(FileProxyError) as exc_info:
                proxy_file("big2")
        assert exc_info.value.http_status == 413
