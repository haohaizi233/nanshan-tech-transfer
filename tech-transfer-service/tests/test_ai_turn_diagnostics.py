from unittest.mock import MagicMock, patch

from tools import diagnose_ai_turn as diagnostics


def database_turn(message="/评估"):
    database = MagicMock()
    database.__enter__.return_value.fetchall.return_value = [{"entry": {
        "turn_id": "test-turn", "user_id": 7, "user_message": message,
        "status": "failed", "stage": "failed", "stage_seq": 6,
        "context_snapshot": {"reference": {"id": 99}},
    }}]
    return database


def test_default_diagnostics_do_not_send_requests_or_print_private_context():
    with patch.object(diagnostics, "get_cursor", return_value=database_turn()), patch.object(diagnostics, "post_agent") as post:
        report = diagnostics.diagnose("test-turn")
    post.assert_not_called()
    assert report["acceptsTwentyEvaluationCards"] is True
    assert "user_message" not in report["turn"]
    assert "context_snapshot" not in report["turn"]


def test_probe_refuses_commands_that_could_create_evaluation_tasks():
    with patch.object(diagnostics, "get_cursor", return_value=database_turn("/评估 3")), patch.object(diagnostics, "post_agent") as post:
        report = diagnostics.diagnose("test-turn", probe=True)
    post.assert_not_called()
    assert report["probe"] == "refused_non_picker_command"


def test_picker_probe_drops_historical_references_and_outputs_only_metadata():
    with patch.object(diagnostics, "get_cursor", return_value=database_turn()), patch.object(diagnostics, "post_agent", return_value={"intent": "evaluate_achievement", "data": [{"id": 3, "contact": "private"}]}) as post:
        report = diagnostics.diagnose("test-turn", probe=True)
    payload = post.call_args.args[2]
    assert payload["message"] == "/评估"
    assert payload["context"]["cards"] == []
    assert "reference" not in payload["context"]
    assert report["probe"]["cards"] == 1
    assert "private" not in str(report)
