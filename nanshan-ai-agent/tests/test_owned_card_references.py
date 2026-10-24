from unittest.mock import patch

import pytest

from app import main
from app.schemas import ChatRequest


def achievement(identifier=1, owner=7, status="published", deleted=None):
    return {"id": identifier, "title": "当前成果", "tech_intro": "当前资料", "owner_user_id": owner,
            "status": status, "deleted_at": deleted}


def reference_request(message="介绍这项", ids=(1,)):
    cards = [{"card_type": "achievement", "id": identifier, "title": "旧标题", "messageId": 5} for identifier in ids]
    context = {"schemaVersion": 1, "generation": 2, "queryPlan": {"intent": "evaluate_achievement"}, "cards": cards, "messages": []}
    if len(ids) == 1:
        context["reference"] = {"card_type": "achievement", "id": ids[0]}
    return ChatRequest(message=message, exclude_owner_user_id=7, context=context)


@pytest.mark.parametrize("status", ["published", "draft", "pending_review", "offline"])
def test_owned_evaluation_card_can_be_introduced_using_current_data(status):
    with patch.object(main, "search_achievements", return_value=[]), \
            patch.object(main.evaluation_service, "resolve_target", return_value=achievement(status=status)), \
            patch.object(main, "classify_intent", side_effect=AssertionError("no model")), \
            patch.object(main.evaluation_service, "evaluate", side_effect=AssertionError("no evaluation side effect")):
        result = main._process_ai_chat(reference_request())
    assert len(result.data) == 1
    assert result.data[0]["title"] == "当前成果"
    assert "旧标题" not in result.message


@pytest.mark.parametrize("record", [None, achievement(owner=8, status="draft"), achievement(deleted="deleted")])
def test_reference_never_discloses_deleted_or_other_owners_private_records(record):
    with patch.object(main, "search_achievements", return_value=[]), \
            patch.object(main.evaluation_service, "resolve_target", return_value=record):
        result = main._process_ai_chat(reference_request())
    assert result.data == []
    assert "不可用" in result.message


def test_ownership_is_rechecked_before_reference_response():
    with patch.object(main, "search_achievements", return_value=[]), \
            patch.object(main.evaluation_service, "resolve_target", side_effect=[achievement(), achievement(owner=8, status="draft")]):
        result = main._process_ai_chat(reference_request())
    assert result.data == []


def test_two_owned_cards_can_be_compared_without_entering_recommendation_search():
    with patch.object(main, "search_achievements", return_value=[]), \
            patch.object(main.evaluation_service, "resolve_target", side_effect=lambda user_id, target_id: achievement(identifier=target_id)):
        result = main._process_ai_chat(reference_request("比较第一个和第二个成果", (1, 2)))
    assert len(result.data) == 2
