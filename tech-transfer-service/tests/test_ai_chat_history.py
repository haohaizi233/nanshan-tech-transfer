"""Persistence and route tests for recoverable, idempotent AI chat turns."""
from datetime import datetime, timezone
import time
from unittest.mock import MagicMock, patch

import jwt
import pytest
from pydantic import ValidationError

from config import settings


def _mock_cursor_context(cursor):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _turn_row(**overrides):
    row = {
        "turn_id": "turn-123",
        "status": "running",
        "reply": None,
        "cards": None,
        "error_message": None,
        "error_code": None,
        "error_status": None,
        "created_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 10, 17, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with patch("db.init_pool"), patch("db.close_pool"), \
            patch("db.get_cursor") as get_cursor, patch("db.get_conn") as get_conn:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        get_cursor.return_value = _mock_cursor_context(cursor)
        connection = MagicMock()
        get_conn.return_value = _mock_cursor_context(connection)
        from app import app
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client


def _auth(user_id):
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user_id), "userNo": f"U{user_id:03d}", "roles": ["user"],
            "type": "access", "iat": now, "exp": now + 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


class TestAiChatTurnSchema:
    def test_turn_id_is_optional_for_legacy_clients(self):
        from core.request_schemas import AiChatRequest

        assert AiChatRequest(message="hello").turnId is None

    def test_turn_id_accepts_bounded_safe_identifiers(self):
        from core.request_schemas import AiChatRequest

        assert AiChatRequest(message="hello", turnId="local:abc-123").turnId == "local:abc-123"

    @pytest.mark.parametrize("turn_id", ["", "bad id", "x" * 65, "../turn"])
    def test_turn_id_rejects_invalid_identifiers(self, turn_id):
        from core.request_schemas import AiChatRequest

        with pytest.raises(ValidationError):
            AiChatRequest(message="hello", turnId=turn_id)


class TestAiChatTurnStore:
    @pytest.fixture(autouse=True)
    def legacy_schema(self):
        with patch("modules.ai.chat_store._session_generation", return_value=None):
            yield

    @patch("modules.ai.chat_store.get_cursor")
    def test_start_turn_creates_once_and_returns_existing_on_duplicate(self, mock_get_cursor):
        from modules.ai.chat_store import start_turn

        cur = MagicMock()
        cur.fetchone.side_effect = [_turn_row(), None, _turn_row()]
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        created, is_new = start_turn(7, "turn-123", "hello")
        existing, is_duplicate_new = start_turn(7, "turn-123", "hello again")

        assert is_new is True
        assert created["status"] == "running"
        assert is_duplicate_new is False
        assert existing["turnId"] == "turn-123"
        assert "ON CONFLICT" in cur.execute.call_args_list[0].args[0]

    @patch("modules.ai.chat_store.get_cursor")
    def test_get_turn_query_is_scoped_by_user_and_turn_id(self, mock_get_cursor):
        from modules.ai.chat_store import get_turn

        cur = MagicMock()
        cur.fetchone.return_value = _turn_row()
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        result = get_turn(8, "turn-123")

        assert result["turnId"] == "turn-123"
        assert "WHERE user_id = %s AND turn_id = %s" in cur.execute.call_args.args[0]
        assert cur.execute.call_args.args[1] == (8, "turn-123")

    @patch("modules.ai.chat_store.get_cursor")
    def test_turn_result_and_message_pair_commit_atomically(self, mock_get_cursor):
        from modules.ai.chat_store import complete_turn

        cur = MagicMock()
        cur.fetchone.return_value = _turn_row(status="succeeded", reply="Found it", cards=[{"id": 4}])
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        result = complete_turn(7, "turn-123", "hello", "Found it", [{"id": 4}])

        assert result["status"] == "succeeded"
        assert result["cards"] == [{"id": 4}]
        assert cur.execute.call_count == 3
        assert "UPDATE ai_chat_turn" in cur.execute.call_args_list[0].args[0]
        assert cur.execute.call_args_list[1].args[1][1] == "hello"

    @patch("modules.ai.chat_store.get_cursor")
    def test_duplicate_completion_never_inserts_a_second_message_pair(self, mock_get_cursor):
        from modules.ai.chat_store import complete_turn

        cur = MagicMock()
        cur.fetchone.side_effect = [None, _turn_row(status="succeeded", reply="Already done")]
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        result = complete_turn(7, "turn-123", "hello", "Already done", [])

        assert result["status"] == "succeeded"
        assert cur.execute.call_count == 2

    @patch("modules.ai.chat_store.get_cursor")
    def test_fail_turn_persists_failure_and_one_message_pair(self, mock_get_cursor):
        from modules.ai.chat_store import fail_turn

        cur = MagicMock()
        cur.fetchone.return_value = _turn_row(
            status="failed", reply="AI unavailable", error_message="AI unavailable",
            error_code="TT_AI_50301", error_status=503,
        )
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        result = fail_turn(7, "turn-123", "hello", "AI unavailable", "TT_AI_50301", 503)

        assert result["status"] == "failed"
        assert result["errorStatus"] == 503
        assert cur.execute.call_count == 3

    @patch("modules.ai.chat_store.get_cursor")
    def test_clear_messages_also_removes_turns(self, mock_get_cursor):
        from modules.ai.chat_store import clear_messages

        cur = MagicMock()
        cur.rowcount = 2
        mock_get_cursor.return_value = _mock_cursor_context(cur)

        assert clear_messages(7) == 2
        assert cur.execute.call_count == 2
        assert "DELETE FROM ai_chat_turn" in cur.execute.call_args_list[0].args[0]
        assert "DELETE FROM ai_chat_message" in cur.execute.call_args_list[1].args[0]


class TestAiChatTurnRoutes:
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.list_history")
    def test_http_history_matches_the_shared_client_contract(self, list_history, _active, client):
        import json
        from pathlib import Path

        fixture = Path(__file__).resolve().parents[2] / "南山小程序" / "南山" / "tests" / "fixtures" / "ai-chat-history-contract.json"
        expected = json.loads(fixture.read_text(encoding="utf-8"))
        list_history.return_value = {key: value for key, value in expected.items() if key != "referenceSupported"}
        with patch("routes.ai.settings.AI_CHAT_RUNS_ENABLED", True):
            response = client.get("/api/tech-transfer/v1/ai/chat/messages", headers=_auth(7))
        assert response.status_code == 200
        assert response.json()["data"] == expected
        list_history.assert_called_once_with(7)

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    @patch("routes.ai.complete_turn")
    def test_new_turn_is_persisted_and_returns_agent_result(
        self, complete_turn, forward, start_turn, _rate
    ):
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = ({"turnId": "turn-123", "status": "running"}, True)
            forward.return_value = {"success": True, "message": "Found it", "data": [{"id": 4}]}
            complete_turn.return_value = {
                "turnId": "turn-123", "status": "succeeded", "reply": "Found it", "cards": [{"id": 4}]
            }

            response = ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        assert response["data"]["message"] == "Found it"
        assert response["data"]["data"] == [{"id": 4}]
        start_turn.assert_called_once_with(7, "turn-123", "hello")
        complete_turn.assert_called_once()

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    @patch("routes.ai.complete_turn")
    def test_cleared_turn_during_generation_does_not_return_unpersisted_answer(
        self, complete_turn, forward, start_turn, _rate
    ):
        from core.errors import BizError
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = ({"turnId": "turn-123", "status": "running"}, True)
            forward.return_value = {"success": True, "message": "Found it", "data": []}
            complete_turn.return_value = None

            with pytest.raises(BizError) as exc_info:
                ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        assert exc_info.value.http_status == 409
        assert exc_info.value.code == "TT_COMMON_40902"
        assert exc_info.value.details == {"reason": "chat_history_cleared", "turnId": "turn-123"}
        complete_turn.assert_called_once()

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    @patch("routes.ai.fail_turn")
    def test_upstream_failure_is_saved_and_not_retried_for_same_turn(
        self, fail_turn, forward, start_turn, _rate
    ):
        from core.errors import BizError
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = ({"turnId": "turn-123", "status": "running"}, True)
            forward.side_effect = BizError("TT_AI_50301", "Unavailable", 503)
            with pytest.raises(BizError):
                ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        fail_turn.assert_called_once_with(7, "turn-123", "hello", "Unavailable", "TT_AI_50301", 503)

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    def test_duplicate_succeeded_turn_does_not_call_agent(self, forward, start_turn, _rate):
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = (
                {"turnId": "turn-123", "status": "succeeded", "reply": "Already answered", "cards": []},
                False,
            )
            response = ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        forward.assert_not_called()
        assert response["data"]["message"] == "Already answered"

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    def test_duplicate_running_turn_returns_accepted_without_calling_agent(self, forward, start_turn, _rate):
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = ({"turnId": "turn-123", "status": "running"}, False)
            response = ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        forward.assert_not_called()
        assert response.status_code == 202
        assert response.body

    @patch("routes.ai.check_user_rate")
    @patch("routes.ai.start_turn")
    @patch("routes.ai._forward_to_agent")
    def test_duplicate_failed_turn_does_not_retry_model(self, forward, start_turn, _rate):
        from core.errors import BizError
        from core.request_schemas import AiChatRequest
        from routes.ai import ai_chat

        with patch("routes.ai.settings.AI_AGENT_URL", "http://agent"):
            start_turn.return_value = (
                {"turnId": "turn-123", "status": "failed", "errorMessage": "Unavailable",
                 "errorCode": "TT_AI_50301", "errorStatus": 503},
                False,
            )
            with pytest.raises(BizError) as exc_info:
                ai_chat(AiChatRequest(message="hello", turnId="turn-123"), {"userId": 7})

        forward.assert_not_called()
        assert exc_info.value.http_status == 503

    @patch("routes.ai.get_chat_turn")
    def test_turn_status_is_scoped_to_authenticated_user(self, get_turn):
        from routes.ai import ai_chat_turn_detail

        get_turn.return_value = None
        with pytest.raises(Exception) as exc_info:
            ai_chat_turn_detail("turn-123", {"userId": 8})

        get_turn.assert_called_once_with(8, "turn-123")
        assert getattr(exc_info.value, "http_status", None) == 404

    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.get_chat_turn")
    def test_http_turn_status_uses_authenticated_account(self, get_turn, _active, client):
        get_turn.side_effect = lambda user_id, turn_id: (
            {"turnId": turn_id, "status": "running"} if user_id == 7 else None
        )

        found = client.get("/api/tech-transfer/v1/ai/chat/turns/turn-123", headers=_auth(7))
        hidden = client.get("/api/tech-transfer/v1/ai/chat/turns/turn-123", headers=_auth(8))

        assert found.status_code == 200
        assert found.json()["data"]["status"] == "running"
        assert hidden.status_code == 404
        assert [call.args[0] for call in get_turn.call_args_list] == [7, 8]

