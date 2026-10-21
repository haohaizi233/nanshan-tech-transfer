from unittest.mock import Mock

from modules.ai import chat_store


def test_sync_history_preserves_generation_without_advertising_durable_card_reference():
    cursor = Mock()
    cursor.fetchone.return_value = {"turn_id": "sync-one", "status": "succeeded", "generation": 2}
    chat_store._finish_sync_turn(cursor, 7, "sync-one", "question", "reply", [{"card_type": "achievement", "id": 42}], 2)
    statement, parameters = cursor.execute.call_args.args
    assert "INSERT INTO ai_chat_message" in statement
    assert parameters[2] == 2
    assert parameters[7] == 2
    assert parameters[3] is None
    assert parameters[8] is None
