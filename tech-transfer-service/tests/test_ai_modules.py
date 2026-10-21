"""Tests for modules/ai/* (provider, worker, chat_store, service)."""
import json
from datetime import datetime
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from core.errors import BizError


def _mock_cur_ctx(mock_cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=mock_cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


# ── provider ────────────────────────────────────────────────

class TestAiProvider:
    def test_parse_json_content_valid(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('{"key": "value"}')
        assert result == {"key": "value"}

    def test_parse_json_content_fenced(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('```json\n{"key": "value"}\n```')
        assert result == {"key": "value"}

    def test_parse_json_content_empty(self):
        from modules.ai.provider import parse_json_content
        with pytest.raises(Exception):
            parse_json_content("")

    def test_parse_json_content_with_surrounding_text(self):
        from modules.ai.provider import parse_json_content
        result = parse_json_content('Here is the result: {"a": 1} done')
        assert result == {"a": 1}

    def test_parse_json_content_no_json(self):
        from modules.ai.provider import parse_json_content
        with pytest.raises(Exception):
            parse_json_content("no json here at all")

    def test_configured(self):
        from modules.ai.provider import configured
        with patch("modules.ai.provider.settings") as mock_settings:
            mock_settings.AI_PROVIDER_BASE = "http://test"
            assert configured() is True
            mock_settings.AI_PROVIDER_BASE = ""
            assert configured() is False

    def test_evaluate_achievement_scores(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = {
                "dimensions": {
                    "innovation": {"score": 80, "comment": "创新明确"},
                    "techMaturity": {"score": 90, "comment": "成熟度高"},
                    "marketProspect": {"score": 70, "comment": "市场可期"},
                    "teamStrength": {"score": 60, "comment": "团队完整"},
                    "cooperation": {"score": 85, "comment": "合作灵活"},
                    "riskAssessment": {"score": 75, "comment": "风险可控"},
                },
                "conclusion": "Good",
                "highlights": ["Fast", "Reliable"],
                "report": [{"heading": "总体评价", "content": "详细分析"}],
            }
            result = evaluate_achievement({"id": 1, "title": "Test"})
        assert [d["key"] for d in result["dimensions"]] == [
            "innovation", "techMaturity", "marketProspect",
            "teamStrength", "cooperation", "riskAssessment",
        ]
        assert result["dimensions"][0]["score"] == 80.0
        assert result["dimensions"][0]["weight"] == 0.18
        # 013 兼容四列 ← 多维 1:1 派生
        assert result["legacyScores"] == {
            "techFeature": 80.0, "applyScope": 70.0,
            "maturity": 90.0, "cooperation": 85.0,
        }
        assert result["totalScore"] == pytest.approx(77.15, abs=0.2)
        assert result["highlights"] == ["Fast", "Reliable"]
        assert result["report"] == [{"heading": "总体评价", "content": "详细分析"}]
        assert result["rating"] in {"excellent", "good", "fair", "weak"}

    def test_evaluate_achievement_fallback_total(self):
        from modules.ai.provider import evaluate_achievement
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = {
                # 扁平写法 + LLM 未回 totalScore：由权重换算
                "dimensions": {
                    "innovation": 80, "techMaturity": 90, "marketProspect": 70,
                    "teamStrength": 60, "cooperation": 85, "riskAssessment": 75,
                },
            }
            result = evaluate_achievement({"id": 1})
            assert result["totalScore"] == pytest.approx(77.15, abs=0.2)
            assert result["conclusion"] == ""

    def test_evaluate_achievement_invalid_scores(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = {"not_scores": 1}
            with pytest.raises(AiProviderError):
                evaluate_achievement({"id": 1})

    def test_evaluate_achievement_non_dict(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = [1, 2]
            with pytest.raises(AiProviderError):
                evaluate_achievement({"id": 1})

    def test_evaluate_highlights_not_list(self):
        from modules.ai.provider import evaluate_achievement
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = {
                "dimensions": {
                    "innovation": 80, "techMaturity": 90, "marketProspect": 70,
                    "teamStrength": 60, "cooperation": 85, "riskAssessment": 75,
                },
                "highlights": "single string",
            }
            result = evaluate_achievement({"id": 1})
            assert isinstance(result["highlights"], list)

    def test_evaluate_score_missing_key(self):
        from modules.ai.provider import evaluate_achievement, AiProviderError
        with patch("modules.ai.provider.complete_json") as mock_complete:
            mock_complete.return_value = {
                "dimensions": {
                    "innovation": 80, "techMaturity": 90, "marketProspect": 70,
                    "teamStrength": 60, "cooperation": 85,
                    # riskAssessment 缺失
                },
            }
            with pytest.raises(AiProviderError):
                evaluate_achievement({"id": 1})


# ── worker ──────────────────────────────────────────────────

class TestAiWorker:
    def test_clip(self):
        from modules.ai.worker import _clip
        assert _clip("error") == "error"
        assert _clip(None) == "AI 服务暂时不可用，请稍后重试"
        assert len(_clip("x" * 600)) == 500

    def test_desensitize_reason_empty(self):
        from modules.ai.worker import _desensitize_reason
        assert _desensitize_reason("") == "AI 服务暂时不可用，请稍后重试"

    def test_desensitize_reason_none(self):
        from modules.ai.worker import _desensitize_reason
        assert _desensitize_reason(None) == "AI 服务暂时不可用，请稍后重试"

    def test_desensitize_reason_safe(self):
        from modules.ai.worker import _desensitize_reason
        assert _desensitize_reason("unknown task_type") == "unknown task_type"

    def test_desensitize_reason_provider(self):
        from modules.ai.worker import _desensitize_reason
        assert _desensitize_reason("qwen error") == "AI 服务暂时不可用，请稍后重试"

    def test_desensitize_reason_url(self):
        from modules.ai.worker import _desensitize_reason
        assert _desensitize_reason("https://api.example.com failed") == "AI 服务暂时不可用，请稍后重试"

    def test_snapshot_dict(self):
        from modules.ai.worker import _snapshot
        assert _snapshot({"a": 1}) == {"a": 1}

    def test_snapshot_json_string(self):
        from modules.ai.worker import _snapshot
        assert _snapshot('{"a": 1}') == {"a": 1}

    def test_snapshot_bad_json(self):
        from modules.ai.worker import _snapshot
        assert _snapshot("bad") == {}

    def test_snapshot_empty(self):
        from modules.ai.worker import _snapshot
        assert _snapshot(None) == {}

    def test_snapshot_non_dict_json(self):
        from modules.ai.worker import _snapshot
        assert _snapshot("[1, 2]") == {}

    def test_finish_running(self):
        import modules.ai.worker as w
        w._running_count = 3
        w._finish_running()
        assert w._running_count == 2

    def test_finish_running_at_zero(self):
        import modules.ai.worker as w
        w._running_count = 0
        w._finish_running()
        assert w._running_count == 0

    @patch("modules.ai.worker.provider")
    def test_process_one_unconfigured(self, mock_prov):
        from modules.ai.worker import process_one
        mock_prov.configured.return_value = False
        assert process_one() == "unconfigured"

    @patch("modules.ai.worker.claim_one", return_value=None)
    @patch("modules.ai.worker.reap_stuck", return_value=0)
    @patch("modules.ai.worker.provider")
    def test_process_one_idle(self, mock_prov, mock_reap, mock_claim):
        from modules.ai.worker import process_one
        mock_prov.configured.return_value = True
        assert process_one() == "idle"


# ── chat_store ──────────────────────────────────────────────

class TestChatStore:
    @pytest.fixture(autouse=True)
    def legacy_schema(self):
        with patch("modules.ai.chat_store._session_generation", return_value=None):
            yield

    @patch("modules.ai.chat_store.get_cursor")
    def test_append_message_valid(self, mock_gc):
        from modules.ai.chat_store import append_message
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1, "created_at": datetime(2026, 1, 1)}
        mock_gc.return_value = _mock_cur_ctx(cur)
        result = append_message(1, "user", "hello")
        assert result["id"] == 1
        assert "2026-01-01" in result["createdAt"]

    def test_append_message_invalid_role(self):
        from modules.ai.chat_store import append_message
        with pytest.raises(ValueError):
            append_message(1, "bad", "hello")

    @patch("modules.ai.chat_store.get_cursor")
    def test_list_messages(self, mock_gc):
        from modules.ai.chat_store import list_messages
        cur = MagicMock()
        cur.fetchall.return_value = [
            {"id": 2, "role": "assistant", "content": "hi", "cards": None, "created_at": datetime(2026, 1, 1)},
            {"id": 1, "role": "user", "content": "hello", "cards": None, "created_at": datetime(2026, 1, 1)},
        ]
        mock_gc.return_value = _mock_cur_ctx(cur)
        result = list_messages(1, 50)
        assert len(result) == 2
        assert result[0]["id"] == 1  # reversed to ascending

    @patch("modules.ai.chat_store.get_cursor")
    def test_clear_messages(self, mock_gc):
        from modules.ai.chat_store import clear_messages
        cur = MagicMock()
        cur.rowcount = 5
        mock_gc.return_value = _mock_cur_ctx(cur)
        assert clear_messages(1) == 5

    @patch("modules.ai.chat_store.get_cursor")
    def test_append_turn(self, mock_gc):
        from modules.ai.chat_store import append_turn
        cur = MagicMock()
        mock_gc.return_value = _mock_cur_ctx(cur)
        append_turn(1, "user msg", "assistant msg", cards=[{"id": 1}])
        assert cur.execute.call_count == 2


# ── service ─────────────────────────────────────────────────

class TestAiService:
    def test_parse_reasons_none(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons(None) == []

    def test_parse_reasons_list(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons(["a", "b"]) == ["a", "b"]

    def test_parse_reasons_json_string(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons('["a"]') == ["a"]

    def test_parse_reasons_invalid(self):
        from modules.ai.service import _parse_reasons
        assert _parse_reasons("bad") == []

    def test_iso_with_dt(self):
        from modules.ai.service import _iso
        assert _iso(datetime(2026, 1, 1)) == "2026-01-01T00:00:00"

    def test_iso_none(self):
        from modules.ai.service import _iso
        assert _iso(None) is None

    def test_desensitize_none(self):
        from modules.ai.service import _desensitize_fail_reason
        assert _desensitize_fail_reason(None) is None

    def test_desensitize_safe(self):
        from modules.ai.service import _desensitize_fail_reason
        assert _desensitize_fail_reason("unknown error") == "unknown error"

    def test_desensitize_provider(self):
        from modules.ai.service import _desensitize_fail_reason
        assert _desensitize_fail_reason("qwen failed") == "AI 服务暂时不可用，请稍后重试"

    def test_desensitize_empty(self):
        from modules.ai.service import _desensitize_fail_reason
        result = _desensitize_fail_reason("")
        assert not result  # None or empty string

    @patch("modules.ai.service.get_cursor")
    def test_task_view(self, mock_gc):
        from modules.ai.service import _task_view
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 1, "status": "queued"}
        mock_gc.return_value = _mock_cur_ctx(cur)
        result = _task_view(1)
        assert result["taskId"] == 1
        assert result["status"] == "queued"

    def test_snapshot_fields(self):
        from modules.ai.service import SNAPSHOT_FIELDS_EVAL
        assert "id" in SNAPSHOT_FIELDS_EVAL
        assert "title" in SNAPSHOT_FIELDS_EVAL
