import json
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from core.request_schemas import AiChatRequest


def test_chat_reference_is_strict_and_client_context_is_forbidden():
    body = AiChatRequest(message="介绍", reference={"messageId": 8, "cardType": "achievement", "cardId": 3})
    assert body.reference.cardId == 3
    with pytest.raises(ValidationError):
        AiChatRequest(message="hello", context={"messages": []})
    with pytest.raises(ValidationError):
        AiChatRequest(message="hello", reference={"messageId": 8, "cardType": "achievement", "cardId": True})


def test_request_hash_normalizes_text_but_includes_reference():
    from modules.ai.chat_runs import request_hash

    assert request_hash(" hello ") == request_hash("hello")
    assert request_hash("hello", {"messageId": 2, "cardType": "achievement", "cardId": 4}) != request_hash("hello")


def test_context_preserves_complete_pairs_and_limits():
    from modules.ai.chat_context import build_context

    rows = [
        {
            "user_message": "u" * 1000,
            "reply": "a" * 1000,
            "assistant_message_id": number,
            "query_plan": {"intent": "search_achievement", "keywords": ["water"]},
            "cards": [{"card_type": "achievement", "id": card, "title": "t" * 100} for card in range(1, 12)],
        }
        for number in range(1, 5)
    ]
    result = build_context(rows, 2)
    assert len(result["messages"]) == 4
    assert all(len(message["content"]) <= 800 for message in result["messages"])
    assert len(result["cards"]) == 10
    assert all(len(card["title"]) <= 80 for card in result["cards"])
    assert len(json.dumps(result, ensure_ascii=False)) <= 8000


def test_reference_must_appear_in_the_owned_message():
    from core.errors import BizError
    from modules.ai.chat_context import validate_reference_cards

    with pytest.raises(BizError):
        validate_reference_cards([], {"messageId": 8, "cardType": "achievement", "cardId": 3})
    assert validate_reference_cards(
        [{"id": 3, "card_type": "achievement"}], {"messageId": 8, "cardType": "achievement", "cardId": 3}
    ) == {"card_type": "achievement", "id": 3}


def test_async_route_accepts_only_after_persistent_submission():
    from starlette.requests import Request

    from routes.ai import ai_chat

    request = Request({"type": "http", "headers": [(b"prefer", b"respond-async")]})
    with (
        patch("routes.ai.settings.AI_CHAT_RUNS_ENABLED", True),
        patch("routes.ai.submit_run") as submit,
        patch("routes.ai.check_user_rate"),
        patch("routes.ai._forward_to_agent") as forward,
    ):
        submit.return_value = {
            "turnId": "test",
            "status": "running",
            "generation": 1,
            "stage": "queued",
            "stageSeq": 0,
            "pollAfterMs": 2000,
        }
        response = ai_chat(AiChatRequest(message="hello", turnId="test"), {"userId": 7}, request)
    assert response.status_code == 202
    assert json.loads(response.body)["data"]["stage"] == "queued"
    forward.assert_not_called()


def test_new_mode_defaults_off():
    from config import Settings

    assert Settings(_env_file=None).AI_CHAT_RUNS_ENABLED is False


def test_clear_after_disabling_mode_still_uses_generation_and_tombstones():
    from routes.ai import ai_chat_messages_clear

    with (
        patch("routes.ai.settings.AI_CHAT_RUNS_ENABLED", False),
        patch("routes.ai.has_durable_history", return_value=True),
        patch("routes.ai.clear_runs", return_value={"deleted": 2, "generation": 3}) as clear,
    ):
        result = ai_chat_messages_clear({"userId": 7})
    assert result["data"]["generation"] == 3
    clear.assert_called_once_with(7)


def test_context_skips_incomplete_turns_without_valid_message_id():
    from modules.ai.chat_context import build_context

    result = build_context(
        [
            {
                "user_message": "legacy",
                "reply": "reply",
                "cards": [{"card_type": "achievement", "id": 2, "title": "old"}],
            }
        ],
        0,
    )
    assert result["messages"] == []
    assert result["cards"] == []


def test_context_keeps_last_successful_query_across_non_search_reply():
    from modules.ai.chat_context import build_context

    result = build_context(
        [
            {
                "assistant_message_id": 2,
                "user_message": "找水处理",
                "reply": "候选",
                "query_plan": {"intent": "search_achievement", "keywords": ["水处理"], "max_price_wan": 50},
            },
            {"assistant_message_id": 4, "user_message": "怎么发布", "reply": "流程", "query_plan": {}},
        ],
        0,
    )
    assert result["queryPlan"] == {"intent": "search_achievement", "keywords": ["水处理"], "max_price_wan": 50}


def test_reference_without_owned_locator_is_rejected_instead_of_synthesized():
    from core.errors import BizError
    from modules.ai.chat_context import build_context

    with pytest.raises(BizError):
        build_context([], 0, {"messageId": 8, "cardType": "achievement", "cardId": 3})


def test_h5_async_preflight_allows_prefer_header(app_client):
    response = app_client.options(
        "/api/tech-transfer/v1/ai/chat",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "prefer,content-type,authorization",
        },
    )
    assert response.status_code == 200


def test_worker_once_reports_failed_execution_as_failure():
    from unittest.mock import MagicMock

    from tools import run_ai_chat_worker as worker

    context = MagicMock()
    with (
        patch("sys.argv", ["worker", "--once"]),
        patch.object(worker.chat_runs, "configuration_ready", return_value=True),
        patch.object(worker.chat_runs, "reap_runs"),
        patch.object(worker.chat_runs, "heartbeat_worker"),
        patch.object(worker.chat_runs, "claim_one", return_value={"execution_id": "test"}),
        patch.object(worker, "probe_agent", return_value=True),
        patch.object(worker, "get_cursor", return_value=context),
        patch.object(worker, "execute_run", return_value="failed"),
        patch.object(worker, "close_pool"),
        patch.object(worker.signal, "signal"),
    ):
        assert worker.main() == 1


@pytest.mark.parametrize("cleared_during_forward", [False, True])
def test_match_history_uses_the_generation_captured_before_forward(cleared_during_forward):
    from unittest.mock import MagicMock

    from core.request_schemas import AiMatchRequest
    from routes.ai import ai_match

    demand_cursor = MagicMock()
    demand_cursor.fetchone.return_value = {
        "id": 12, "title": "水处理", "description": "技术需求", "owner_user_id": 7, "status": "published",
    }
    history_cursor = MagicMock()
    generation = [4]

    def forward(*_args, **_kwargs):
        if cleared_during_forward:
            generation[0] += 1
        return {"success": True, "message": "找到成果", "data": [{"card_type": "achievement", "id": 3}]}

    with (
        patch("db.get_cursor") as demand_context,
        patch("modules.ai.chat_store.get_cursor") as history_context,
        patch("modules.ai.chat_store._session_generation", side_effect=lambda *_args: generation[0]),
        patch("routes.ai.check_user_rate"),
        patch("routes.ai.settings.AI_AGENT_URL", "http://127.0.0.1:8000"),
        patch("routes.ai._forward_to_agent", side_effect=forward),
    ):
        demand_context.return_value.__enter__.return_value = demand_cursor
        history_context.return_value.__enter__.return_value = history_cursor
        response = ai_match(AiMatchRequest(demandId=12), {"userId": 7})

    assert response["data"]["cards"][0]["id"] == 3
    writes = [call.args for call in history_cursor.execute.call_args_list if "INSERT INTO ai_chat_message" in call.args[0]]
    if cleared_during_forward:
        assert writes == []
    else:
        assert len(writes) == 1
        assert writes[0][1][0:4] == (7, "匹配需求：水处理", 4, None)
        assert writes[0][1][4:6] == (7, "找到成果")
        assert writes[0][1][7:] == (4, None)
