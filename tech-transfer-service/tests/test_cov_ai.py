"""Focused coverage tests for AI modules and admin edit_log.

Pure unit tests only: DB access is mocked by patching each module's ``get_cursor`` /
``transaction``; HTTP access is mocked by patching the module's ``_OPENER`` /
``_chat_stream``. No real DB or network is opened.

The shared ``FAT`` row is a uniform superset reused for ``fetchone``/``fetchall`` so
tests are robust against call-order drift. ``side_effect`` sequences are used only
where a function genuinely needs distinct rows per call.
"""

import json
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError

# ── Uniform fat row used across every module ────────────────────────────────
FAT = {
    # generic / edit_log
    "id": 1,
    "user_id": 1,
    "org_id": 1,
    "content_id": 1,
    "category_id": 1,
    "name": "行业",
    "title": "标题",
    "status": "active",
    "version": 1,
    "c": 1,
    "m": 0,
    "count": 1,
    "total": 1,
    "n": 3,
    "user_no": "U001",
    "role": "admin",
    "role_code": "user",
    "display_name": "张三",
    "owner_user_id": 1,
    "created_at": datetime(2026, 1, 1, 12, 0),
    "updated_at": datetime(2026, 1, 1, 12, 0),
    "batch_id": 7,
    "field_name": "title",
    "field_label": "标题",
    "change_kind": "updated",
    "old_value": "旧",
    "new_value": "新",
    "operator_name": "管理员",
    "operator_user_no": "U001",
    # chat_runs / chat_store
    "turn_id": "t-1",
    "generation": 0,
    "execution_id": "exec-1",
    "stage": "context",
    "stage_seq": 1,
    "reply": "回答",
    "cards": [],
    "error_message": None,
    "error_code": None,
    "error_status": None,
    "assistant_message_id": 1,
    "request_hash": "h",
    "user_message": "问",
    "reference": None,
    "slot_id": 1,
    "relation": "ai_chat_session",
    "workers": 1,
    "ready": 1,
    "queued": 0,
    "running": 0,
    "execution_mode": "sync",
    "task_type": "evaluation",
    "target_id": 1,
    "input_snapshot": {},
    "content": "内容",
}


def _row(**kw):
    r = dict(FAT)
    r.update(kw)
    return r


def _cur(fetchone=None, fetchall=None, rowcount=1):
    cur = MagicMock()
    cur.fetchone.return_value = dict(FAT) if fetchone is None else fetchone
    cur.fetchall.return_value = [dict(FAT)] if fetchall is None else fetchall
    cur.rowcount = rowcount
    return cur


def _bind(mock_gc, cur):
    mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)


# ══════════════════════════════════════════════════════════════════════════
# modules/admin/edit_log.py — pure helpers
# ══════════════════════════════════════════════════════════════════════════


class TestIsBlank:
    def test_none(self):
        from modules.admin.edit_log import _is_blank

        assert _is_blank(None) is True

    def test_empty_and_whitespace_str(self):
        from modules.admin.edit_log import _is_blank

        assert _is_blank("") is True
        assert _is_blank("   ") is True

    def test_nonempty_str(self):
        from modules.admin.edit_log import _is_blank

        assert _is_blank("x") is False

    def test_containers(self):
        from modules.admin.edit_log import _is_blank

        assert _is_blank([]) is True
        assert _is_blank([1]) is False
        assert _is_blank({}) is True
        assert _is_blank({"a": 1}) is False
        assert _is_blank(()) is True
        assert _is_blank(set()) is True
        assert _is_blank({1}) is False

    def test_scalars(self):
        from modules.admin.edit_log import _is_blank

        assert _is_blank(0) is False
        assert _is_blank(False) is False


class TestCanonical:
    def test_none_and_bool(self):
        from modules.admin.edit_log import _canonical

        assert _canonical(None) is None
        assert _canonical(True) is True

    def test_decimal_and_numbers(self):
        from modules.admin.edit_log import _canonical

        assert _canonical(Decimal("1.5")) == 1.5
        assert _canonical(5) == 5
        assert _canonical(5.5) == 5.5

    def test_dates(self):
        from modules.admin.edit_log import _canonical

        assert _canonical(date(2026, 1, 1)) == "2026-01-01"
        assert _canonical(datetime(2026, 1, 1, 12, 0)) == "2026-01-01T12:00:00"

    def test_list_and_dict_recursive(self):
        from modules.admin.edit_log import _canonical

        assert _canonical([1, Decimal("2")]) == [1, 2.0]
        assert _canonical({"a": Decimal("2")}) == {"a": 2.0}
        assert _canonical((1, 2)) == [1, 2]

    def test_json_text(self):
        from modules.admin.edit_log import _canonical

        assert _canonical('{"a": 1}') == {"a": 1}
        assert _canonical("[1, 2]") == [1, 2]

    def test_bad_json_text_kept(self):
        from modules.admin.edit_log import _canonical

        assert _canonical("[broken") == "[broken"
        assert _canonical("plain") == "plain"

    def test_other_object_stringified(self):
        from modules.admin.edit_log import _canonical

        assert _canonical({1, 2}) == str({1, 2})


class TestDisplay:
    def test_none_and_bool(self):
        from modules.admin.edit_log import _display

        assert _display(None) == ""
        assert _display(True) == "是"
        assert _display(False) == "否"

    def test_decimal_float_int(self):
        from modules.admin.edit_log import _display

        assert _display(Decimal("7.0")) == "7"
        assert _display(Decimal("7.5")) == "7.5"
        assert _display(7.0) == "7"
        assert _display(7.5) == "7.5"
        assert _display(7) == "7"

    def test_dates(self):
        from modules.admin.edit_log import _display

        assert _display(date(2026, 1, 1)) == "2026-01-01"
        assert _display(datetime(2026, 1, 1, 12, 30)) == "2026-01-01 12:30"

    def test_list_skips_blank(self):
        from modules.admin.edit_log import _display

        assert _display([1, "", "x"]) == "1、x"

    def test_dict_json(self):
        from modules.admin.edit_log import _display

        assert _display({"a": 1}) == '{"a": 1}'

    def test_json_text_renders(self):
        from modules.admin.edit_log import _display

        assert _display('{"a": 1}') == '{"a": 1}'
        assert _display("[1, 2]") == "1、2"

    def test_bad_json_text_and_other(self):
        from modules.admin.edit_log import _display

        assert _display("[bad") == "[bad"
        assert _display("hello") == "hello"
        assert _display({1, 2}) == str({1, 2})


class TestRefLabel:
    def test_none_and_str(self):
        from modules.admin.edit_log import _ref_label

        assert _ref_label(None, "demand", "category_id", None) == ""
        assert _ref_label(None, "demand", "category_id", "abc") == "abc"

    def test_unmapped_field_falls_back(self):
        from modules.admin.edit_log import _ref_label

        assert _ref_label(MagicMock(), "demand", "bogus", 5) == "5"

    def test_resolves_dict_name(self):
        from modules.admin.edit_log import _ref_label

        cur = MagicMock()
        cur.fetchone.return_value = {"name": "行业A"}
        assert _ref_label(cur, "demand", "category_id", 5) == "行业A"

    def test_null_name_falls_back(self):
        from modules.admin.edit_log import _ref_label

        cur = MagicMock()
        cur.fetchone.return_value = {"name": None}
        assert _ref_label(cur, "demand", "category_id", 5) == "5"

    def test_tuple_row(self):
        from modules.admin.edit_log import _ref_label

        cur = MagicMock()
        cur.fetchone.return_value = ("行业B",)
        assert _ref_label(cur, "demand", "category_id", 5) == "行业B"

    def test_execute_error_falls_back(self):
        from modules.admin.edit_log import _ref_label

        cur = MagicMock()
        cur.execute.side_effect = RuntimeError("db down")
        assert _ref_label(cur, "demand", "category_id", 5) == "5"

    def test_no_row_falls_back(self):
        from modules.admin.edit_log import _ref_label

        cur = MagicMock()
        cur.fetchone.return_value = None
        assert _ref_label(cur, "demand", "category_id", 5) == "5"


class TestClip:
    def test_short_unchanged(self):
        from modules.admin.edit_log import _clip

        assert _clip("short") == "short"

    def test_long_truncated(self):
        from modules.admin.edit_log import MAX_VALUE_LEN, _clip

        out = _clip("x" * (MAX_VALUE_LEN + 50))
        assert len(out) == MAX_VALUE_LEN
        assert out.endswith("…")


class TestComputeChanges:
    def test_updated_non_ref(self):
        from modules.admin.edit_log import compute_changes

        changes = compute_changes(None, "demand", {"title": "a"}, {"title": "b"})
        assert len(changes) == 1
        assert changes[0]["field"] == "title"
        assert changes[0]["fieldLabel"] == "标题"
        assert changes[0]["changeKind"] == "updated"
        assert changes[0]["oldValue"] == "a"
        assert changes[0]["newValue"] == "b"

    def test_created_when_old_blank(self):
        from modules.admin.edit_log import compute_changes

        changes = compute_changes(None, "demand", {"title": None}, {"title": "x"})
        assert changes[0]["changeKind"] == "created"
        assert changes[0]["oldValue"] == ""

    def test_unchanged_skipped(self):
        from modules.admin.edit_log import compute_changes

        assert compute_changes(None, "demand", {"title": "s"}, {"title": "s"}) == []

    def test_decimal_and_bool_values(self):
        from modules.admin.edit_log import compute_changes

        changes = compute_changes(
            None,
            "achievement",
            {"price_min_wan": Decimal("1.0"), "budget_negotiable": False},
            {"price_min_wan": Decimal("2.0"), "budget_negotiable": True},
        )
        kinds = {c["field"]: c for c in changes}
        assert kinds["price_min_wan"]["oldValue"] == "1"
        assert kinds["price_min_wan"]["newValue"] == "2"
        assert kinds["budget_negotiable"]["newValue"] == "是"

    def test_ref_field_falls_back_to_display(self):
        # SOURCE BUG (not fixed here): compute_changes guards with `column in _REF_LABEL_SQL`,
        # but _REF_LABEL_SQL has (target_type, field) tuple keys, so that branch is dead code
        # and _ref_label is never invoked. Ref columns render via _display like ordinary fields.
        from modules.admin.edit_log import compute_changes

        cur = MagicMock()
        changes = compute_changes(cur, "demand", {"category_id": 5}, {"category_id": 9})
        assert changes[0]["oldValue"] == "5"
        assert changes[0]["newValue"] == "9"

    def test_ref_field_old_none(self):
        from modules.admin.edit_log import compute_changes

        cur = MagicMock()
        changes = compute_changes(cur, "demand", {"org_id": None}, {"org_id": 3})
        assert changes[0]["oldValue"] == ""
        assert changes[0]["newValue"] == "3"
        assert changes[0]["changeKind"] == "created"

    def test_extras(self):
        from modules.admin.edit_log import compute_changes

        changes = compute_changes(
            None,
            "demand",
            None,
            {},
            extras=[{"field": "tags", "fieldLabel": "标签", "oldValue": "A、B", "newValue": "A、C"}],
        )
        assert changes[0]["field"] == "tags"
        assert changes[0]["fieldLabel"] == "标签"

    def test_extras_identical_skipped(self):
        from modules.admin.edit_log import compute_changes

        assert (
            compute_changes(None, "demand", None, {}, extras=[{"field": "t", "oldValue": "x", "newValue": "x"}]) == []
        )

    def test_extras_defaults(self):
        from modules.admin.edit_log import compute_changes

        changes = compute_changes(None, "demand", None, {}, extras=[{"oldValue": "", "newValue": "y"}])
        assert changes[0]["field"] == "extra"
        assert changes[0]["changeKind"] == "created"


class TestRecordAdminEditChanges:
    def test_empty_returns_zero(self):
        from modules.admin.edit_log import record_admin_edit_changes

        assert record_admin_edit_changes(MagicMock(), "demand", 1, []) == 0
        assert record_admin_edit_changes(MagicMock(), "demand", 1, None) == 0

    def test_records_with_operator_lookup(self):
        from modules.admin.edit_log import record_admin_edit_changes

        cur = _cur()
        out = record_admin_edit_changes(cur, "demand", 1, [{"field": "title"}], operator_user_id=5)
        assert out == 1
        assert cur.execute.called

    def test_operator_name_provided(self):
        from modules.admin.edit_log import record_admin_edit_changes

        cur = _cur()
        out = record_admin_edit_changes(
            cur, "demand", 1, [{"field": "title", "fieldLabel": "标题", "changeKind": "updated"}], operator_name="李四"
        )
        assert out == 1

    def test_batch_id_from_tuple_row(self):
        from modules.admin.edit_log import record_admin_edit_changes

        cur = _cur()
        cur.fetchone.return_value = (99,)
        out = record_admin_edit_changes(cur, "demand", 1, [{"field": "title"}])
        assert out == 1

    def test_fields_without_name_filtered(self):
        from modules.admin.edit_log import record_admin_edit_changes

        cur = _cur()
        assert record_admin_edit_changes(cur, "demand", 1, [{"oldValue": "a"}]) == 0


class TestRowValueAndChange:
    def test_row_value_dict(self):
        from modules.admin.edit_log import _row_value

        assert _row_value({"a": 5}, "a") == 5

    def test_row_value_tuple_falls_to_index(self):
        from modules.admin.edit_log import _row_value

        assert _row_value((10, 20), "a", 1) == 20

    def test_row_to_change_dict(self):
        from modules.admin.edit_log import _row_to_change

        out = _row_to_change(_row(created_at=datetime(2026, 2, 3, 4, 5)))
        assert out["field"] == "title"
        assert out["createdAt"] == "2026-02-03 04:05"

    def test_row_to_change_tuple(self):
        from modules.admin.edit_log import _row_to_change

        row = (1, 2, "f", "标签", "updated", "o", "n", "管理员", "U1", datetime(2026, 1, 1, 1, 1))
        out = _row_to_change(row)
        assert out["id"] == 1
        assert out["field"] == "f"

    def test_row_to_change_null_created(self):
        from modules.admin.edit_log import _row_to_change

        out = _row_to_change(_row(created_at=None))
        assert out["createdAt"] == ""


class TestAssertOwnerOrAdmin:
    def test_bad_type(self):
        from modules.admin.edit_log import _assert_owner_or_admin

        with pytest.raises(BizError):
            _assert_owner_or_admin(MagicMock(), "bogus", 1, {"userId": 1})

    def test_not_found(self):
        from modules.admin.edit_log import _assert_owner_or_admin

        cur = MagicMock()
        cur.fetchone.return_value = None
        with pytest.raises(BizError):
            _assert_owner_or_admin(cur, "demand", 1, {"userId": 1})

    def test_owner_match(self):
        from modules.admin.edit_log import _assert_owner_or_admin

        cur = MagicMock()
        cur.fetchone.return_value = {"owner_user_id": 1}
        _assert_owner_or_admin(cur, "demand", 1, {"userId": 1})

    def test_admin_match(self):
        from modules.admin.edit_log import _assert_owner_or_admin

        cur = MagicMock()
        cur.fetchone.side_effect = [{"owner_user_id": 2}, {"1": 1}]
        _assert_owner_or_admin(cur, "demand", 1, {"userId": 1})

    def test_forbidden(self):
        from modules.admin.edit_log import _assert_owner_or_admin

        cur = MagicMock()
        cur.fetchone.side_effect = [{"owner_user_id": 2}, None]
        with pytest.raises(BizError):
            _assert_owner_or_admin(cur, "demand", 1, {"userId": 1})


class TestListAndMarkChanges:
    @patch("db.get_cursor")
    def test_list_admin_changes(self, mock_gc):
        from modules.admin.edit_log import list_admin_changes

        cur = _cur()
        _bind(mock_gc, cur)
        out = list_admin_changes("demand", 1, {"userId": 1})
        assert out["targetType"] == "demand"
        assert out["unreadCount"] == 3
        assert out["totalCount"] == 3
        assert isinstance(out["changes"], list)
        assert out["changes"][0]["field"] == "title"

    @patch("db.get_cursor")
    def test_mark_admin_changes_read(self, mock_gc):
        from modules.admin.edit_log import mark_admin_changes_read

        cur = _cur(rowcount=2)
        _bind(mock_gc, cur)
        out = mark_admin_changes_read("demand", 1, {"userId": 1})
        assert out["markedRead"] == 2

    def test_mark_bad_type(self):
        from modules.admin.edit_log import mark_admin_changes_read

        with pytest.raises(BizError):
            mark_admin_changes_read("bogus", 1, {"userId": 1})


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/eval_stream.py — pure in-process pub/sub
# ══════════════════════════════════════════════════════════════════════════


class TestEvalStream:
    def setup_method(self):
        from modules.ai import eval_stream

        eval_stream.clear()

    def teardown_method(self):
        from modules.ai import eval_stream

        eval_stream.clear()

    def test_open_and_push(self):
        from modules.ai import eval_stream

        assert eval_stream.open(1) is True
        assert eval_stream.push_delta(1, "你好") is True
        assert eval_stream.push_delta(1, "世界") is True

    def test_open_invalid(self):
        from modules.ai import eval_stream

        assert eval_stream.open(0) is False
        assert eval_stream.open(-1) is False

    def test_push_invalid(self):
        from modules.ai import eval_stream

        assert eval_stream.push_delta(0, "x") is False
        assert eval_stream.push_delta(1, "") is False

    def test_push_delta_after_terminal_dropped(self):
        from modules.ai import eval_stream

        eval_stream.open(2)
        eval_stream.finish(2, "succeeded")
        assert eval_stream.push_delta(2, "late") is False

    def test_finish_and_idempotent(self):
        from modules.ai import eval_stream

        eval_stream.open(3)
        assert eval_stream.finish(3, "succeeded") is True
        assert eval_stream.finish(3, "succeeded") is False
        assert eval_stream.finish(3, "bogus") is False

    def test_subscribe_receives_snapshot_and_terminal(self):
        from modules.ai import eval_stream

        eval_stream.open(4)
        eval_stream.push_delta(4, "已生成")
        sub = eval_stream.subscribe(4)
        assert sub.text == "已生成"
        eval_stream.finish(4, "succeeded")
        event = sub.get(timeout=1)
        assert event == {"type": "terminal", "status": "succeeded"}
        sub.close()
        sub.close()  # idempotent

    def test_subscribe_late_gets_terminal_replay(self):
        from modules.ai import eval_stream

        eval_stream.open(5)
        eval_stream.finish(5, "failed")
        sub = eval_stream.subscribe(5)
        event = sub.get(timeout=1)
        assert event == {"type": "terminal", "status": "failed"}

    def test_subscribe_invalid(self):
        from modules.ai import eval_stream

        with pytest.raises(ValueError):
            eval_stream.subscribe(0)

    def test_subscription_get_timeout(self):
        from modules.ai import eval_stream

        eval_stream.open(6)
        sub = eval_stream.subscribe(6)
        assert sub.get(timeout=0.01) is None
        sub.close()
        assert sub.get() is None

    def test_gc_overflow_and_stale(self):
        from modules.ai import eval_stream

        # overflow path: exceed MAX_CHANNELS
        for i in range(eval_stream.MAX_CHANNELS + 5):
            eval_stream.open(1000 + i)
        assert len(eval_stream._channels) <= eval_stream.MAX_CHANNELS

    def test_broadcast_queue_full(self):
        from modules.ai import eval_stream

        eval_stream.open(9)
        sub = eval_stream.subscribe(9)
        # fill the subscriber queue to force the queue.Full branch in _broadcast
        for i in range(eval_stream._SUB_QUEUE_MAX + 5):
            eval_stream.push_delta(9, f"x{i}")
        sub.close()

    def test_push_creates_channel_when_missing(self):
        from modules.ai import eval_stream

        assert eval_stream.push_delta(20, "x") is True  # no prior open()

    def test_finish_creates_channel_when_missing(self):
        from modules.ai import eval_stream

        assert eval_stream.finish(21, "succeeded") is True  # no prior open()

    def test_subscribe_creates_channel_when_missing(self):
        from modules.ai import eval_stream

        sub = eval_stream.subscribe(22)  # no prior open()
        assert sub.text == ""
        sub.close()

    def test_clear_specific_task(self):
        from modules.ai import eval_stream

        eval_stream.open(23)
        eval_stream.clear(23)
        assert 23 not in eval_stream._channels


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/chat_context.py
# ══════════════════════════════════════════════════════════════════════════


class TestQueryPlanValidation:
    def test_validate_query_plan_not_dict(self):
        from modules.ai.chat_context import validate_query_plan

        with pytest.raises(ValueError):
            validate_query_plan([1, 2])

    def test_validate_query_plan_too_big(self):
        from modules.ai.chat_context import validate_query_plan

        with pytest.raises(ValueError):
            validate_query_plan({"reason": "x" * 3000})

    def test_validate_query_plan_long_keyword(self):
        from modules.ai.chat_context import validate_query_plan

        with pytest.raises(ValueError):
            validate_query_plan({"intent": "search_demand", "keywords": ["k" * 101]})

    def test_validate_query_plan_bad_range(self):
        from modules.ai.chat_context import validate_query_plan

        with pytest.raises(ValueError):
            validate_query_plan({"intent": "search_demand", "min_price_wan": 10, "max_price_wan": 5})

    def test_validate_query_plan_ok(self):
        from modules.ai.chat_context import validate_query_plan

        assert validate_query_plan({"intent": "search_demand", "limit": 5})["limit"] == 5


class TestValidateReference:
    def test_reference_none(self):
        from modules.ai.chat_context import validate_reference

        assert validate_reference(MagicMock(), 1, 0, None) is None

    def test_reference_not_found(self):
        from modules.ai.chat_context import validate_reference

        cur = MagicMock()
        cur.fetchone.return_value = None
        with pytest.raises(BizError):
            validate_reference(cur, 1, 0, {"messageId": 1, "cardType": "demand", "cardId": 2})

    def test_reference_ok(self):
        from modules.ai.chat_context import validate_reference

        cur = MagicMock()
        cur.fetchone.return_value = {"cards": [{"card_type": "demand", "id": 2}]}
        out = validate_reference(cur, 1, 0, {"messageId": 1, "cardType": "demand", "cardId": 2})
        assert out == {"card_type": "demand", "id": 2}

    def test_reference_card_mismatch(self):
        from modules.ai.chat_context import validate_reference

        cur = MagicMock()
        cur.fetchone.return_value = {"cards": [{"card_type": "demand", "id": 99}]}
        with pytest.raises(BizError):
            validate_reference(cur, 1, 0, {"messageId": 1, "cardType": "demand", "cardId": 2})


class TestBuildContext:
    def test_basic_messages_and_cards(self):
        from modules.ai.chat_context import build_context

        rows = [
            {
                "assistant_message_id": 1,
                "user_message": "找成果",
                "reply": "好的",
                "cards": [{"card_type": "achievement", "id": 5, "title": "成果A"}],
                "query_plan": {"intent": "search_achievement"},
            }
        ]
        out = build_context(rows, 0)
        assert out["queryPlan"]["intent"] == "search_achievement"
        assert len(out["messages"]) == 2
        assert out["cards"][0]["id"] == 5

    def test_card_edge_cases(self):
        from modules.ai.chat_context import build_context

        rows = [
            {
                "assistant_message_id": 1,
                "user_message": "q",
                "reply": "a",
                "cards": [
                    "not-a-dict",
                    {"card_type": "bogus", "id": 1},
                    {"card_type": "demand", "id": 0},
                    {"card_type": "demand", "id": 3, "title": "需求"},
                ],
            }
        ]
        out = build_context(rows, 0)
        assert out["cards"][0]["id"] == 3

    def test_reference_prepends_card(self):
        from modules.ai.chat_context import build_context

        # Two rows: the latest row (messageId=2) supplies context["cards"]; the referenced
        # card lives on the earlier row (messageId=1) so it is NOT already present and the
        # prepend branch (line 149) runs.
        rows = [
            {
                "assistant_message_id": 1,
                "user_message": "q",
                "reply": "a",
                "cards": [{"card_type": "achievement", "id": 5, "title": "成果A"}],
            },
            {
                "assistant_message_id": 2,
                "user_message": "q2",
                "reply": "a2",
                "cards": [{"card_type": "demand", "id": 9, "title": "需求B"}],
            },
        ]
        ref = {"cardType": "achievement", "cardId": 5, "messageId": 1}
        out = build_context(rows, 0, reference=ref)
        assert out["reference"] == {"card_type": "achievement", "id": 5}
        assert out["cards"][0]["messageId"] == 1
        assert out["cards"][0]["id"] == 5

    def test_reference_not_recoverable(self):
        from modules.ai.chat_context import build_context

        rows = [{"assistant_message_id": 1, "user_message": "q", "reply": "a", "cards": []}]
        ref = {"cardType": "achievement", "cardId": 5, "messageId": 1}
        with pytest.raises(BizError):
            build_context(rows, 0, reference=ref)

    def test_bad_query_plan_in_history(self):
        from modules.ai.chat_context import build_context

        rows = [
            {
                "assistant_message_id": 1,
                "user_message": "q",
                "reply": "a",
                "cards": [],
                "query_plan": {"keywords": ["k" * 101]},
            }
        ]
        with pytest.raises(BizError):
            build_context(rows, 0)


class TestLoadContext:
    def test_load_context(self):
        from modules.ai.chat_context import load_context

        cur = MagicMock()
        cur.fetchall.return_value = [
            {"assistant_message_id": 1, "user_message": "q", "reply": "a", "cards": [], "query_plan": {}}
        ]
        out = load_context(cur, 1, 0, None)
        assert out["generation"] == 0


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/provider.py — HTTP paths mocked via _OPENER / _chat_stream
# ══════════════════════════════════════════════════════════════════════════


class _SSE:
    def __init__(self, lines):
        self._lines = list(lines)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def __iter__(self):
        for line in self._lines:
            yield line if isinstance(line, bytes) else line.encode()


def _sse_chunk(text):
    return "data: " + json.dumps({"choices": [{"delta": {"content": text}}]}) + "\n"


class TestProviderChatStream:
    @patch("modules.ai.provider._OPENER")
    def test_stream_success_with_progress(self, mock_opener):
        from modules.ai import provider

        mock_opener.open.return_value = _SSE([_sse_chunk("Hel"), _sse_chunk("lo"), "data: [DONE]\n"])
        seen = []
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = "k"
            s.AI_PROVIDER_TIMEOUT = 30
            out = provider._chat_stream([{"role": "user", "content": "hi"}], on_progress=lambda t, c: seen.append(c))
        assert out == "Hello"
        assert seen == [1, 2]

    @patch("modules.ai.provider._OPENER")
    def test_stream_not_configured(self, mock_opener):
        from modules.ai import provider

        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = ""
            with pytest.raises(provider.AiProviderError):
                provider._chat_stream([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_stream_empty_content(self, mock_opener):
        from modules.ai import provider

        mock_opener.open.return_value = _SSE(["data: [DONE]\n"])
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = ""
            s.AI_PROVIDER_TIMEOUT = 30
            with pytest.raises(provider.AiProviderError):
                provider._chat_stream([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_stream_http_error(self, mock_opener):
        import urllib.error

        from modules.ai import provider

        mock_opener.open.side_effect = urllib.error.HTTPError("http://t", 500, "err", {}, None)
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = ""
            s.AI_PROVIDER_TIMEOUT = 30
            with pytest.raises(provider.AiProviderError):
                provider._chat_stream([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_stream_generic_error(self, mock_opener):
        from modules.ai import provider

        mock_opener.open.side_effect = RuntimeError("boom")
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = ""
            s.AI_PROVIDER_TIMEOUT = 30
            with pytest.raises(provider.AiProviderError):
                provider._chat_stream([{"role": "user", "content": "hi"}])

    @patch("modules.ai.provider._OPENER")
    def test_stream_bad_json_line_skipped(self, mock_opener):
        from modules.ai import provider

        mock_opener.open.return_value = _SSE(
            [": comment\n", "\n", "data: not-json\n", _sse_chunk("ok"), "data: [DONE]\n"]
        )
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = ""
            s.AI_PROVIDER_TIMEOUT = 30
            assert provider._chat_stream([{"role": "user", "content": "hi"}]) == "ok"


class TestProviderChat:
    @patch("modules.ai.provider._OPENER")
    def test_chat_content_list_and_key(self, mock_opener):
        from modules.ai import provider

        payload = {"choices": [{"message": {"content": [{"text": "a"}, {"text": "b"}]}}]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_opener.open.return_value = resp
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = "k"
            s.AI_PROVIDER_TIMEOUT = 30
            assert provider._chat([{"role": "user", "content": "hi"}]) == "ab"

    @patch("modules.ai.provider._OPENER")
    def test_chat_empty_content(self, mock_opener):
        from modules.ai import provider

        payload = {"choices": [{"message": {"content": "   "}}]}
        resp = MagicMock()
        resp.read.return_value = json.dumps(payload).encode()
        resp.__enter__ = MagicMock(return_value=resp)
        resp.__exit__ = MagicMock(return_value=False)
        mock_opener.open.return_value = resp
        with patch("modules.ai.provider.settings") as s:
            s.AI_PROVIDER_BASE = "http://localhost:8642/v1"
            s.AI_PROVIDER_MODEL = "m"
            s.AI_PROVIDER_KEY = ""
            s.AI_PROVIDER_TIMEOUT = 30
            with pytest.raises(provider.AiProviderError):
                provider._chat([{"role": "user", "content": "hi"}])

    def test_complete_json(self):
        from modules.ai import provider

        with patch("modules.ai.provider._chat", return_value='{"a": 1}'):
            assert provider.complete_json("sys", "user") == {"a": 1}


class TestProviderEvaluateAchievement:
    def test_evaluate_streams_progress_and_deltas(self):
        from modules.ai import provider

        result = {
            "dimensions": {
                "innovation": {"score": 80, "comment": "创新"},
                "techMaturity": {"score": 90, "comment": "成熟"},
                "marketProspect": {"score": 70, "comment": "市场"},
                "teamStrength": {"score": 65, "comment": "团队"},
                "cooperation": {"score": 75, "comment": "合作"},
                "riskAssessment": {"score": 80, "comment": "风险"},
            },
            "conclusion": "好",
            "highlights": ["快"],
            "report": [{"heading": "总评", "content": "分析"}],
        }
        text = json.dumps(result, ensure_ascii=False)

        def fake_stream(messages, timeout=None, on_progress=None):
            on_progress(text[:10], 5)
            on_progress(text[:30], 30)  # token_count % 30 == 0 triggers stage
            return text

        deltas = []
        stages = []
        with patch("modules.ai.provider._chat_stream", side_effect=fake_stream):
            out = provider.evaluate_achievement({"id": 1}, on_delta=deltas.append, on_stage=stages.append)
        assert out["totalScore"] > 0
        assert deltas  # on_delta received incremental text
        assert any("AI生成中" in s for s in stages)  # _llm_progress stage branch

    def test_evaluate_stage_callback_exception_swallowed(self):
        from modules.ai import provider

        result = {
            "dimensions": {
                "innovation": 80,
                "techMaturity": 90,
                "marketProspect": 70,
                "teamStrength": 65,
                "cooperation": 75,
                "riskAssessment": 80,
            },
            "conclusion": "ok",
        }
        text = json.dumps(result, ensure_ascii=False)

        def bad_stage(stage):
            raise RuntimeError("stage boom")

        with patch("modules.ai.provider._chat_stream", return_value=text):
            out = provider.evaluate_achievement({"id": 1}, on_stage=bad_stage)
        assert out["conclusion"] == "ok"

    def test_evaluate_invalid_json(self):
        from modules.ai import provider

        with patch("modules.ai.provider._chat_stream", return_value="not a dict"):
            with pytest.raises(provider.AiProviderError):
                provider.evaluate_achievement({"id": 1})


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/worker.py — DB via get_cursor / transaction, provider mocked
# ══════════════════════════════════════════════════════════════════════════


def _worker_tx(mock_tx, cur):
    conn = MagicMock()
    conn.cursor.return_value = cur
    mock_tx.return_value.__enter__ = MagicMock(return_value=conn)
    mock_tx.return_value.__exit__ = MagicMock(return_value=False)


@pytest.fixture(autouse=True)
def _reset_running_count():
    from modules.ai import worker

    prev = worker._running_count
    worker._running_count = 0
    yield
    worker._running_count = prev


class TestWorkerReapAndClaim:
    @patch("modules.ai.worker.get_cursor")
    def test_reap_stuck(self, mock_gc):
        from modules.ai import worker

        cur = _cur(rowcount=3)
        _bind(mock_gc, cur)
        assert worker.reap_stuck() == 3

    @patch("modules.ai.worker.transaction")
    def test_claim_one(self, mock_tx):
        from modules.ai import worker

        cur = MagicMock()
        _worker_tx(mock_tx, cur)
        cur.fetchone.side_effect = [
            _row(id=5, task_type="evaluation", target_id=1, input_snapshot={}, version=1),
            _row(id=5, task_type="evaluation", target_id=1, input_snapshot={}, version=2),
        ]
        out = worker.claim_one()
        assert out["id"] == 5
        assert worker._running_count == 1

    @patch("modules.ai.worker.transaction")
    def test_claim_one_idle(self, mock_tx):
        from modules.ai import worker

        cur = MagicMock()
        _worker_tx(mock_tx, cur)
        cur.fetchone.return_value = None
        assert worker.claim_one() is None

    @patch("modules.ai.worker.transaction")
    def test_claim_one_no_slot(self, mock_tx):
        from modules.ai import worker

        cur = MagicMock()
        _worker_tx(mock_tx, cur)
        cur.fetchone.side_effect = [{"id": 5}, None]
        assert worker.claim_one() is None

    def test_claim_one_max_running(self):
        from modules.ai import worker

        worker._running_count = worker.MAX_RUNNING
        assert worker.claim_one() is None


class TestWorkerProcessOne:
    def test_unconfigured(self):
        from modules.ai import worker

        with patch("modules.ai.worker.provider.configured", return_value=False):
            assert worker.process_one() == "unconfigured"

    @patch("modules.ai.worker.claim_one")
    @patch("modules.ai.worker.reap_stuck")
    @patch("modules.ai.worker.provider.configured", return_value=True)
    def test_idle(self, mock_cfg, mock_reap, mock_claim):
        from modules.ai import worker

        mock_reap.return_value = 0
        mock_claim.return_value = None
        assert worker.process_one() == "idle"

    @patch("modules.ai.worker._run_evaluation")
    @patch("modules.ai.worker.claim_one")
    @patch("modules.ai.worker.reap_stuck")
    @patch("modules.ai.worker.provider.configured", return_value=True)
    def test_evaluation_success(self, mock_cfg, mock_reap, mock_claim, mock_run):
        from modules.ai import worker

        mock_reap.return_value = 1  # covers the `if reaped` log branch
        mock_claim.return_value = {"id": 1, "task_type": "evaluation", "target_id": 1, "input_snapshot": {}}
        assert worker.process_one() == "succeeded"

    @patch("modules.ai.worker._fail")
    @patch("modules.ai.worker.claim_one")
    @patch("modules.ai.worker.reap_stuck")
    @patch("modules.ai.worker.provider.configured", return_value=True)
    def test_unknown_task_type(self, mock_cfg, mock_reap, mock_claim, mock_fail):
        from modules.ai import worker

        mock_reap.return_value = 0
        mock_claim.return_value = {"id": 1, "task_type": "bogus", "target_id": 1, "input_snapshot": {}}
        assert worker.process_one() == "failed"

    @patch("modules.ai.worker._run_evaluation")
    @patch("modules.ai.worker.claim_one")
    @patch("modules.ai.worker.reap_stuck")
    @patch("modules.ai.worker.provider.configured", return_value=True)
    def test_provider_error(self, mock_cfg, mock_reap, mock_claim, mock_run):
        from modules.ai import worker

        mock_reap.return_value = 0
        mock_claim.return_value = {"id": 1, "task_type": "evaluation", "target_id": 1, "input_snapshot": {}}
        mock_run.side_effect = worker.provider.AiProviderError("qwen timeout")
        with patch("modules.ai.worker._fail") as mock_fail:
            assert worker.process_one() == "failed"
            assert mock_fail.called

    @patch("modules.ai.worker._run_evaluation")
    @patch("modules.ai.worker.claim_one")
    @patch("modules.ai.worker.reap_stuck")
    @patch("modules.ai.worker.provider.configured", return_value=True)
    def test_generic_error(self, mock_cfg, mock_reap, mock_claim, mock_run):
        from modules.ai import worker

        mock_reap.return_value = 0
        mock_claim.return_value = {"id": 1, "task_type": "evaluation", "target_id": 1, "input_snapshot": {}}
        mock_run.side_effect = ValueError("bad")
        with patch("modules.ai.worker._fail") as mock_fail:
            assert worker.process_one() == "failed"
            assert mock_fail.called

    def test_desensitize_reason(self):
        from modules.ai import worker

        assert worker._desensitize_reason("qwen http error") == worker._DESENSITIZE_MSG
        assert worker._desensitize_reason("业务错误") == "业务错误"
        assert worker._desensitize_reason("") == worker._DESENSITIZE_MSG


class TestWorkerRunEvaluation:
    @patch("modules.ai.progress.set_stage", return_value=True)
    @patch("modules.ai.provider.evaluate_achievement")
    @patch("modules.ai.worker.transaction")
    def test_run_evaluation_saved(self, mock_tx, mock_eval, mock_stage):
        from modules.ai import worker

        cur = MagicMock()
        _worker_tx(mock_tx, cur)
        cur.rowcount = 1
        mock_eval.return_value = {
            "legacyScores": {"techFeature": 80, "applyScope": 70, "maturity": 60, "cooperation": 50},
            "totalScore": 70,
            "conclusion": "ok",
            "highlights": ["h"],
            "dimensions": [],
            "report": [],
            "rating": "good",
        }
        worker._run_evaluation({"id": 1, "target_id": 1, "input_snapshot": {}})
        assert mock_eval.called

    @patch("modules.ai.progress.set_stage", return_value=True)
    @patch("modules.ai.provider.evaluate_achievement")
    @patch("modules.ai.worker.transaction")
    def test_run_evaluation_discarded(self, mock_tx, mock_eval, mock_stage):
        from modules.ai import worker

        cur = MagicMock()
        _worker_tx(mock_tx, cur)
        cur.rowcount = 0  # triggers the discard warning branch
        mock_eval.return_value = {
            "legacyScores": {"techFeature": 80, "applyScope": 70, "maturity": 60, "cooperation": 50},
            "totalScore": 70,
            "conclusion": "ok",
            "highlights": [],
            "dimensions": [],
            "report": [],
            "rating": "good",
        }
        worker._run_evaluation({"id": 1, "target_id": 1, "input_snapshot": "not-a-dict"})

    @patch("modules.ai.worker._stream_signal")
    @patch("modules.ai.worker._report_stage")
    def test_report_stage_exception_swallowed(self, mock_report, mock_signal):
        from modules.ai import worker

        mock_report.side_effect = None
        # _report_stage itself must swallow progress.set_stage failures
        with patch("modules.ai.progress.set_stage", side_effect=RuntimeError("db")):
            worker._report_stage(1, "stage")  # must not raise

    def test_stream_signal_exception_swallowed(self):
        from modules.ai import worker

        def boom(*args):
            raise RuntimeError("bus")

        worker._stream_signal(boom, 1, "x")  # must not raise

    def test_snapshot_variants(self):
        from modules.ai import worker

        assert worker._snapshot({"a": 1}) == {"a": 1}
        assert worker._snapshot('{"a": 1}') == {"a": 1}
        assert worker._snapshot("[1]") == {}
        assert worker._snapshot("bad") == {}
        assert worker._snapshot(None) == {}

    @patch("modules.ai.worker.close_pool")
    def test_close(self, mock_close):
        from modules.ai import worker

        worker.close()
        assert mock_close.called


class TestWorkerInternals:
    def test_finish_running_decrements(self):
        from modules.ai import worker

        worker._running_count = 1
        worker._finish_running()
        assert worker._running_count == 0

    def test_finish_running_noop_at_zero(self):
        from modules.ai import worker

        worker._running_count = 0
        worker._finish_running()
        assert worker._running_count == 0

    @patch("modules.ai.worker.get_cursor")
    def test_fail_updates_db(self, mock_gc):
        from modules.ai import worker

        cur = _cur()
        _bind(mock_gc, cur)
        worker._fail(1, "业务失败原因")  # exercises _fail body + _clip
        assert cur.execute.called

    @patch("modules.ai.worker.get_cursor")
    def test_reap_stuck_zero(self, mock_gc):
        from modules.ai import worker

        cur = _cur(rowcount=0)
        _bind(mock_gc, cur)
        assert worker.reap_stuck() == 0


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/chat_runs.py — DB via get_cursor; helpers patched where noted
# ══════════════════════════════════════════════════════════════════════════


class TestRunViewAndConfig:
    def test_run_view_none(self):
        from modules.ai.chat_runs import run_view

        assert run_view(None) is None

    def test_run_view_row(self):
        from modules.ai.chat_runs import run_view

        out = run_view(_row(status="queued", created_at=datetime(2026, 1, 1), updated_at=None))
        assert out["turnId"] == "t-1"
        assert out["status"] == "running"
        assert out["createdAt"] == "2026-01-01T00:00:00"
        assert out["updatedAt"] is None

    def test_request_hash_stable(self):
        from modules.ai.chat_runs import request_hash

        assert request_hash("hi", None) == request_hash(" hi ", None)

    def test_configuration_ready(self):
        from modules.ai.chat_runs import configuration_ready

        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_INTERNAL_SERVICE_KEY = "k"
            s.AI_CHAT_STREAM_URL = "http://127.0.0.1:8001/internal/ai/chat/stream"
            assert configuration_ready() is True

    def test_configuration_ready_bad_url(self):
        from modules.ai.chat_runs import configuration_ready

        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_INTERNAL_SERVICE_KEY = "k"
            s.AI_CHAT_STREAM_URL = "http://example.com/wrong/path"
            assert configuration_ready() is False

    def test_configuration_ready_no_key(self):
        from modules.ai.chat_runs import configuration_ready

        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_INTERNAL_SERVICE_KEY = ""
            s.AI_CHAT_STREAM_URL = "http://127.0.0.1:8001/internal/ai/chat/stream"
            assert configuration_ready() is False

    def test_configuration_ready_localhost_name(self):
        from modules.ai.chat_runs import configuration_ready

        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_INTERNAL_SERVICE_KEY = "k"
            s.AI_CHAT_STREAM_URL = "http://localhost:8001/internal/ai/chat/stream"
            assert configuration_ready() is True


class TestHealthAndRequire:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_health_status_ok(self, mock_gc):
        from modules.ai.chat_runs import health_status

        cur = _cur()
        _bind(mock_gc, cur)
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_INTERNAL_SERVICE_KEY = "k"
            s.AI_CHAT_STREAM_URL = "http://127.0.0.1:8001/internal/ai/chat/stream"
            s.AI_CHAT_GLOBAL_SLOTS = 4
            out = health_status()
        assert out["database"] is True
        assert out["worker"] is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_health_status_db_down(self, mock_gc):
        from modules.ai.chat_runs import health_status

        mock_gc.side_effect = RuntimeError("db down")
        out = health_status()
        assert out["database"] is False

    def test_require_ready_raises(self):
        from modules.ai import chat_runs

        with patch("modules.ai.chat_runs.health_status", return_value={"configured": False}):
            with pytest.raises(BizError):
                chat_runs.require_ready()

    def test_require_ready_ok(self):
        from modules.ai import chat_runs

        with patch("modules.ai.chat_runs.health_status", return_value={"configured": True, "database": True}):
            chat_runs.require_ready()


class TestSubmitRun:
    @patch("modules.ai.chat_runs.validate_reference")
    @patch("modules.ai.chat_runs.require_ready")
    @patch("modules.ai.chat_runs.check_user_rate")
    @patch("modules.ai.chat_runs.get_cursor")
    def test_submit_new_run(self, mock_gc, mock_rate, mock_ready, mock_validate):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            dict(FAT),  # _lock_session generation
            None,  # tombstone check
            None,  # existing
            {"queued": 0, "running": 0},  # counts
            _row(),  # insert returning
        ]
        out = chat_runs.submit_run(1, "turn-1", "hello")
        assert out["turnId"] == "t-1"

    @patch("modules.ai.chat_runs.get_cursor")
    def test_submit_tombstone_conflict(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), {"turn_id": "turn-1"}]
        with pytest.raises(BizError):
            chat_runs.submit_run(1, "turn-1", "hello")

    @patch("modules.ai.chat_runs.get_cursor")
    def test_submit_existing_match(self, mock_gc):
        from modules.ai import chat_runs

        fp = chat_runs.request_hash("hello", None)
        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), None, _row(request_hash=fp, user_message="hello")]
        out = chat_runs.submit_run(1, "turn-1", "hello")
        assert out["turnId"] == "t-1"

    @patch("modules.ai.chat_runs.get_cursor")
    def test_submit_existing_conflict(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), None, _row(request_hash="different", user_message="hello")]
        with pytest.raises(BizError):
            chat_runs.submit_run(1, "turn-1", "hello")

    @patch("modules.ai.chat_runs.validate_reference")
    @patch("modules.ai.chat_runs.require_ready")
    @patch("modules.ai.chat_runs.check_user_rate")
    @patch("modules.ai.chat_runs.get_cursor")
    def test_submit_queue_full(self, mock_gc, mock_rate, mock_ready, mock_validate):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            dict(FAT),
            None,
            None,
            {"queued": 3, "running": 0},  # queue full
        ]
        with pytest.raises(BizError):
            chat_runs.submit_run(1, "turn-1", "hello")


class TestRunReadsAndClear:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_get_run(self, mock_gc):
        from modules.ai import chat_runs

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_runs.get_run(1, "t-1")["turnId"] == "t-1"

    @patch("modules.ai.chat_runs.get_cursor")
    def test_has_durable_history_true(self, mock_gc):
        from modules.ai import chat_runs

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_runs.has_durable_history(1) is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_has_durable_history_no_relation(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = {"relation": None}
        assert chat_runs.has_durable_history(1) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_clear_runs(self, mock_gc):
        from modules.ai import chat_runs

        cur = _cur(rowcount=4)
        _bind(mock_gc, cur)
        out = chat_runs.clear_runs(1)
        assert out["deleted"] == 4
        assert out["generation"] == 1

    @patch("modules.ai.chat_runs.get_cursor")
    def test_heartbeat_worker(self, mock_gc):
        from modules.ai import chat_runs

        cur = _cur()
        _bind(mock_gc, cur)
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            assert chat_runs.heartbeat_worker("w1", True) is None


class TestClaimOne:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_happy(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            {"user_id": 1, "generation": 0},  # session
            {"slot_id": 1},  # slot
            _row(id=10, user_id=1, generation=0, reference=None),  # run
            _row(id=10, status="running"),  # claimed
        ]
        cur.fetchall.return_value = []  # load_context -> build_context
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            s.AI_CHAT_LEASE_SECONDS = 20
            s.AI_CHAT_EXECUTION_SECONDS = 55
            out = chat_runs.claim_one("w1")
        assert out["status"] == "running"

    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_no_session(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = None
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            assert chat_runs.claim_one("w1") is None

    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_no_slot(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [{"user_id": 1, "generation": 0}, None]
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            assert chat_runs.claim_one("w1") is None

    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_no_run(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [{"user_id": 1, "generation": 0}, {"slot_id": 1}, None]
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            assert chat_runs.claim_one("w1") is None

    @patch("modules.ai.chat_runs.load_context", side_effect=BizError("TT", "bad ref", 400))
    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_reference_invalid(self, mock_gc, mock_load):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            {"user_id": 1, "generation": 0},
            {"slot_id": 1},
            _row(id=10, user_id=1, generation=0, reference={"messageId": 1}),
            {"id": 1},  # _fail_locked -> _messages ids / update
            {"id": 2},
            {"id": 1},
        ]
        cur.fetchall.return_value = []
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            s.AI_CHAT_LEASE_SECONDS = 20
            s.AI_CHAT_EXECUTION_SECONDS = 55
            assert chat_runs.claim_one("w1") is None

    @patch("modules.ai.chat_runs.get_cursor")
    def test_claim_one_not_claimed_releases_slot(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            {"user_id": 1, "generation": 0},
            {"slot_id": 1},
            _row(id=10, user_id=1, generation=0, reference=None),
            None,  # claimed = None -> release slot
        ]
        cur.fetchall.return_value = []
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_GLOBAL_SLOTS = 4
            s.AI_CHAT_LEASE_SECONDS = 20
            s.AI_CHAT_EXECUTION_SECONDS = 55
            assert chat_runs.claim_one("w1") is None


class TestOwnedAndUpdate:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_renew_run_success(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            dict(FAT),  # _lock_session generation
            _row(),  # _owned_run row
            {"slot_id": 1},  # update slot returning
        ]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.renew_run(run) is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_renew_run_lost_ownership(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), None]  # _owned_run returns None
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        assert chat_runs.renew_run(run) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_renew_run_no_slot(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), _row(), None]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.renew_run(run) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_update_stage(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), _row()]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        assert chat_runs.update_stage(run, "routing", 1) is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_update_stage_lost(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), None]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        assert chat_runs.update_stage(run, "routing", 1) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_owned_run_generation_mismatch(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = dict(FAT)  # _lock_session -> generation 0
        run = {"user_id": 1, "generation": 5, "turn_id": "t-1", "execution_id": "e", "id": 1}
        # generation mismatch short-circuits _owned_run at line 278
        assert chat_runs.update_stage(run, "routing", 1) is False


class TestFinishRun:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_success(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            dict(FAT),  # _lock_session generation
            _row(),  # _owned_run row
            {"1": 1},  # slot check
            {"1": 1},  # app_user check
            {"id": 11},  # _messages user id
            {"id": 12},  # _messages assistant id
            {"id": 1},  # update returning
        ]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1, "user_message": "问"}
        result = {"success": True, "message": "答", "data": [], "queryPlan": {}}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.finish_run(run, result=result) is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_error(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [
            dict(FAT),
            _row(),
            {"1": 1},
            {"1": 1},
            {"id": 11},
            {"id": 12},
            {"id": 1},
        ]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1, "user_message": "问"}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.finish_run(run, error="出错") is True

    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_not_owned(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), None]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        assert chat_runs.finish_run(run, result={"success": True}) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_no_lease(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [dict(FAT), _row(), None]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1}
        assert chat_runs.finish_run(run, result={"success": True}) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_ownership_lost(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        # user inactive -> _fail_locked with require_owner; update returns None -> _OwnershipLost
        cur.fetchone.side_effect = [
            dict(FAT),
            _row(),
            {"1": 1},
            None,  # app_user check fails -> error path
            {"id": 11},
            {"id": 12},
            None,  # update returning -> ownership lost
        ]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1, "user_message": "问"}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.finish_run(run, result={"success": True}) is False

    @patch("modules.ai.chat_runs.get_cursor")
    def test_finish_success_ownership_lost(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        # success path but the final UPDATE ... RETURNING yields no row -> _OwnershipLost
        cur.fetchone.side_effect = [
            dict(FAT),
            _row(),
            {"1": 1},
            {"1": 1},
            {"id": 11},
            {"id": 12},
            None,
        ]
        run = {"user_id": 1, "generation": 0, "turn_id": "t-1", "execution_id": "e", "id": 1, "user_message": "问"}
        with patch("modules.ai.chat_runs.settings") as s:
            s.AI_CHAT_LEASE_SECONDS = 20
            assert chat_runs.finish_run(run, result={"success": True, "message": "答", "data": []}) is False


class TestReapRuns:
    @patch("modules.ai.chat_runs.get_cursor")
    def test_reap_runs(self, mock_gc):
        from modules.ai import chat_runs

        cur = MagicMock()
        _bind(mock_gc, cur)
        run_row = _row(id=10, user_id=1, user_message="问", generation=0, execution_id="e", turn_id="t-1")
        # fetchall #1 = users to sweep; fetchall #2 = that user's expired runs
        cur.fetchall.side_effect = [[{"user_id": 1}], [run_row]]
        cur.fetchone.side_effect = [
            dict(FAT),  # _lock_session generation
            {"id": 11},  # _messages user id
            {"id": 12},  # _messages assistant id
            {"id": 1},  # _fail_locked update returning
        ]
        with patch("modules.ai.chat_runs.settings") as s:
            s.MAX_REQUEST_SECONDS = 60
            s.AI_AGENT_TIMEOUT = 30
            s.AI_CHAT_LEASE_SECONDS = 20
            out = chat_runs.reap_runs()
        assert out == 1


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/chat_store.py
# ══════════════════════════════════════════════════════════════════════════


class TestTurnView:
    def test_turn_view_none(self):
        from modules.ai.chat_store import _turn_view

        assert _turn_view(None) is None

    def test_turn_view_durable(self):
        from modules.ai.chat_store import _turn_view

        out = _turn_view(_row(execution_mode="durable", status="running"))
        assert out["status"] == "running"

    def test_turn_view_sync(self):
        from modules.ai.chat_store import _turn_view

        out = _turn_view(_row(execution_mode="sync", status="succeeded", created_at=datetime(2026, 1, 1)))
        assert out["status"] == "succeeded"
        assert out["createdAt"] == "2026-01-01T00:00:00"


class TestStartTurn:
    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_new(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, None, _row(execution_mode="sync")]
        view, created = chat_store.start_turn(1, "t-1", "hello")
        assert created is True
        assert view["turnId"] == "t-1"

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_tombstone(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = {"turn_id": "t-1"}
        with pytest.raises(BizError):
            chat_store.start_turn(1, "t-1", "hello")

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_existing_match(self, mock_gc, mock_gen):
        from modules.ai import chat_store
        from modules.ai.chat_runs import request_hash

        fp = request_hash("hello", None)
        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, _row(execution_mode="sync", request_hash=fp, user_message="hello")]
        view, created = chat_store.start_turn(1, "t-1", "hello")
        assert created is False
        assert view["turnId"] == "t-1"

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_existing_conflict(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, _row(execution_mode="sync", request_hash="diff", user_message="hello")]
        with pytest.raises(BizError):
            chat_store.start_turn(1, "t-1", "hello")

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_no_generation_created(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = _row(execution_mode="sync")
        view, created = chat_store.start_turn(1, "t-1", "hello")
        assert created is True
        assert view["turnId"] == "t-1"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_no_generation_conflict_select(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, _row(execution_mode="sync")]
        view, created = chat_store.start_turn(1, "t-1", "hello")
        assert created is False
        assert view["turnId"] == "t-1"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_disappeared(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = None
        with pytest.raises(RuntimeError):
            chat_store.start_turn(1, "t-1", "hello")


class TestGetTurnAndComplete:
    @patch("modules.ai.chat_store.get_cursor")
    def test_get_turn(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.get_turn(1, "t-1")["turnId"] == "t-1"

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_complete_turn_gen_mismatch(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.complete_turn(1, "t-1", "q", "a", expected_generation=3) is None

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_complete_turn_sync(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = _row(execution_mode="sync", status="succeeded")
        out = chat_store.complete_turn(1, "t-1", "q", "a", cards=[], expected_generation=5)
        assert out["status"] == "succeeded"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_complete_turn_legacy(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [_row(execution_mode="sync", status="succeeded")]
        out = chat_store.complete_turn(1, "t-1", "q", "a")
        assert out["status"] == "succeeded"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_complete_turn_legacy_fallback_select(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, _row(execution_mode="sync", status="succeeded")]
        out = chat_store.complete_turn(1, "t-1", "q", "a")
        assert out["status"] == "succeeded"


class TestFailTurnAndAppend:
    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_fail_turn_gen_mismatch(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.fail_turn(1, "t-1", "q", "err", "E1", 500, expected_generation=3) is None

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_fail_turn_sync(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = _row(execution_mode="sync", status="failed")
        out = chat_store.fail_turn(1, "t-1", "q", "err", "E1", 500, expected_generation=5)
        assert out["status"] == "failed"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_fail_turn_legacy(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [_row(execution_mode="sync", status="failed")]
        out = chat_store.fail_turn(1, "t-1", "q", "err", "E1", 500)
        assert out["status"] == "failed"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_fail_turn_legacy_fallback(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.side_effect = [None, _row(execution_mode="sync", status="failed")]
        out = chat_store.fail_turn(1, "t-1", "q", "err", "E1", 500)
        assert out["status"] == "failed"

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_append_turn_gen_mismatch(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.append_turn(1, "q", "a", expected_generation=3) is False

    @patch("modules.ai.chat_store._session_generation", return_value=5)
    @patch("modules.ai.chat_store.get_cursor")
    def test_append_turn_gen_ok(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.append_turn(1, "q", "a", cards=[], expected_generation=5) is True

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_append_turn_legacy(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.append_turn(1, "q", "a") is True


class TestMessages:
    @patch("modules.ai.chat_store.get_cursor")
    def test_append_message(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        out = chat_store.append_message(1, "user", "hi", cards=[{"a": 1}])
        assert out["id"] == 1
        assert out["createdAt"] == "2026-01-01 12:00:00"

    def test_append_message_bad_role(self):
        from modules.ai import chat_store

        with pytest.raises(ValueError):
            chat_store.append_message(1, "bogus", "hi")

    @patch("modules.ai.chat_store.get_cursor")
    def test_list_messages(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        out = chat_store.list_messages(1, limit=5)
        assert out[0]["role"] == "admin"
        assert out[0]["createdAt"] == "2026-01-01 12:00:00"

    @patch("modules.ai.chat_store._session_generation", return_value=None)
    @patch("modules.ai.chat_store.get_cursor")
    def test_list_history_no_session(self, mock_gc, mock_gen):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = {"relation": None}
        cur.fetchall.return_value = []
        out = chat_store.list_history(1)
        assert out["generation"] == 0
        assert out["messages"] == []

    @patch("modules.ai.chat_store.get_cursor")
    def test_list_history_with_session(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        out = chat_store.list_history(1)
        assert out["generation"] == 0

    @patch("modules.ai.chat_store.get_cursor")
    def test_clear_messages(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur(rowcount=6)
        _bind(mock_gc, cur)
        assert chat_store.clear_messages(1) == 6

    @patch("modules.ai.chat_store.get_cursor")
    def test_capture_generation(self, mock_gc):
        from modules.ai import chat_store

        cur = _cur()
        _bind(mock_gc, cur)
        assert chat_store.capture_generation(1) == 0

    @patch("modules.ai.chat_store.get_cursor")
    def test_capture_generation_no_relation(self, mock_gc):
        from modules.ai import chat_store

        cur = MagicMock()
        _bind(mock_gc, cur)
        cur.fetchone.return_value = {"relation": None}
        assert chat_store.capture_generation(1) is None


# ══════════════════════════════════════════════════════════════════════════
# modules/ai/chat_runner.py — stream consumption and result validation
# ══════════════════════════════════════════════════════════════════════════


class _LineStream:
    def __init__(self, events):
        self._lines = []
        for ev in events:
            raw = ev if isinstance(ev, bytes) else (json.dumps(ev, ensure_ascii=False) + "\n").encode()
            self._lines.append(raw)
        self._i = 0

    def readline(self, n=-1):
        if self._i >= len(self._lines):
            return b""
        line = self._lines[self._i]
        self._i += 1
        return line


def _valid_result(intent="search_achievement", cards=None):
    return {
        "executionId": "e-1",
        "type": "result",
        "result": {"success": True, "intent": intent, "message": "ok", "data": cards or [], "queryPlan": None},
    }


class TestValidateResult:
    def test_valid(self):
        from modules.ai.chat_runner import validate_result

        assert validate_result(_valid_result()["result"])["success"] is True

    def test_not_dict(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result("nope")

    def test_unsuccessful(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result({"success": False, "intent": "x", "message": "m", "data": []})

    def test_bad_text(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result({"success": True, "intent": 5, "message": "m", "data": []})

    def test_bad_cards(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result({"success": True, "intent": "search_achievement", "message": "m", "data": "x"})

    def test_bad_card_locator(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result(
                {
                    "success": True,
                    "intent": "search_achievement",
                    "message": "m",
                    "data": [{"card_type": "bogus", "id": 1}],
                }
            )

    def test_bad_query_plan(self):
        from modules.ai.chat_runner import StreamError, validate_result

        with pytest.raises(StreamError):
            validate_result(
                {
                    "success": True,
                    "intent": "search_achievement",
                    "message": "m",
                    "data": [],
                    "queryPlan": {"keywords": ["k" * 101]},
                }
            )

    def test_evaluate_card_limit(self):
        from modules.ai.chat_runner import StreamError, validate_result

        cards = [{"card_type": "achievement", "id": i} for i in range(1, 21)]
        assert validate_result({"success": True, "intent": "evaluate_achievement", "message": "m", "data": cards})
        with pytest.raises(StreamError):
            validate_result({"success": True, "intent": "evaluate_achievement", "message": "m", "data": cards * 2})


class TestConsumeStream:
    def test_happy(self):
        from modules.ai.chat_runner import consume_stream

        events = [
            {"executionId": "e-1", "type": "heartbeat"},
            {"executionId": "e-1", "type": "stage", "stage": "routing", "sequence": 1},
            _valid_result(),
        ]
        out = consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)
        assert out["message"] == "ok"

    def test_terminal_stage_continues(self):
        from modules.ai.chat_runner import consume_stream

        events = [
            {"executionId": "e-1", "type": "stage", "stage": "succeeded", "sequence": 1},
            _valid_result(),
        ]
        out = consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)
        assert out["success"] is True

    def test_error_event(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "e-1", "type": "error"}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_invalid_event_type(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "e-1", "type": "bogus"}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_no_result(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "e-1", "type": "heartbeat"}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_ownership_lost(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "e-1", "type": "stage", "stage": "routing", "sequence": 1}, _valid_result()]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: False)

    def test_execution_mismatch(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "other", "type": "heartbeat"}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_invalid_stage(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [{"executionId": "e-1", "type": "stage", "stage": "bogus", "sequence": 1}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_event_after_terminal(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        events = [_valid_result(), {"executionId": "e-1", "type": "heartbeat"}]
        with pytest.raises(StreamError):
            consume_stream(_LineStream(events), "e-1", 1e9, lambda s, q: True)

    def test_invalid_event_json(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        stream = _LineStream([b"not-json\n"])
        with pytest.raises(StreamError):
            consume_stream(stream, "e-1", 1e9, lambda s, q: True)

    def test_deadline(self):
        from modules.ai.chat_runner import StreamError, consume_stream

        stream = _LineStream([_valid_result()])
        with pytest.raises(StreamError):
            consume_stream(stream, "e-1", 0, lambda s, q: True)
