import importlib.util
import io
import json
from pathlib import Path

import pytest

from modules.ai.chat_context import validate_query_plan
from modules.ai.chat_runner import StreamError, consume_stream, validate_result


def route_payload(intent, **values):
    source = Path(__file__).resolve().parents[2] / "nanshan-ai-agent/app/schemas.py"
    spec = importlib.util.spec_from_file_location("agent_command_contract_schemas", source)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RouteResult(intent=intent, **values).model_dump()


@pytest.mark.parametrize("intent", ["search_achievement", "search_demand", "evaluate_achievement", "out_of_scope"])
def test_backend_accepts_actual_agent_route_payload(intent):
    plan = route_payload(intent)
    assert validate_query_plan(plan) == plan
    assert validate_result({"success": True, "intent": intent, "message": "ok", "data": [], "queryPlan": plan})


def test_evaluation_target_survives_contract():
    plan = route_payload("evaluate_achievement", target_id=3, target_name="测试成果")
    assert validate_query_plan(plan)["target_id"] == 3


def test_invalid_target_is_rejected():
    with pytest.raises(ValueError):
        validate_query_plan({"intent": "evaluate_achievement", "target_id": -1})


def test_twenty_owned_evaluation_cards_survive_the_stream_contract():
    result = {
        "success": True, "intent": "evaluate_achievement", "message": "请选择成果",
        "queryPlan": route_payload("evaluate_achievement"),
        "data": [{"card_type": "achievement", "id": number, "pickAction": "evaluate"} for number in range(1, 21)],
    }
    stream = io.BytesIO((json.dumps({"type": "result", "executionId": "picker", "result": result}) + "\n").encode())
    assert consume_stream(stream, "picker", float("inf"), lambda *args: True)["data"] == result["data"]


@pytest.mark.parametrize("intent,count", [("evaluate_achievement", 21), ("search_achievement", 11), ("search_demand", 11)])
def test_card_budgets_remain_bounded(intent, count):
    with pytest.raises(StreamError):
        validate_result({"success": True, "intent": intent, "message": "ok", "data": [
            {"card_type": "achievement", "id": number} for number in range(1, count + 1)
        ]})
