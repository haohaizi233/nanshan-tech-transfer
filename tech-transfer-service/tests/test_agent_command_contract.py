import importlib.util
from pathlib import Path

import pytest

from modules.ai.chat_context import validate_query_plan
from modules.ai.chat_runner import validate_result


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
