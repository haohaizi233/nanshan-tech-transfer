import io
import os
from pathlib import Path
import subprocess
import sys

from modules.ai.chat_runner import consume_stream


def test_real_agent_http_stream_is_accepted_by_chat_worker():
    agent = Path(__file__).resolve().parents[2] / "nanshan-ai-agent"
    script = '''
import sys
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import main
records = [dict(id=number, title="test achievement", source_org_name="test org", tech_intro="test description", owner_user_id=7, status="published") for number in range(1, 21)]
with patch.object(main.evaluation_service, "list_owned_targets", return_value=records), patch.object(main, "classify_intent", side_effect=AssertionError("unexpected model call")):
    with TestClient(main.app) as client:
        response = client.post("/internal/ai/chat/stream", headers={"X-AI-Service-Key": "integration-key"}, json={"message": "/评估", "exclude_owner_user_id": 7, "executionId": "integration-picker", "context": {"schemaVersion": 1, "generation": 0, "queryPlan": {}, "messages": [], "cards": []}})
        assert response.status_code == 200, response.status_code
        sys.stdout.buffer.write(response.content)
'''
    environment = {**os.environ, "AI_INTERNAL_SERVICE_KEY": "integration-key", "LLM_API_URL": "https://example.invalid", "LLM_API_KEY": "test", "LLM_MODEL": "test", "AI_DB_HOST": "127.0.0.1", "AI_DB_NAME": "test", "AI_DB_USER": "test", "AI_DB_PASSWORD": "test"}
    completed = subprocess.run([sys.executable, "-c", script], cwd=agent, env=environment, capture_output=True, timeout=20)
    assert completed.returncode == 0, completed.stderr.decode(errors="replace")
    stages = []
    result = consume_stream(io.BytesIO(completed.stdout), "integration-picker", float("inf"), lambda stage, sequence: stages.append(stage))
    assert result["intent"] == "evaluate_achievement"
    assert len(result["data"]) == 20
    assert all(card["pickAction"] == "evaluate" for card in result["data"])
    assert "formatting" in stages
