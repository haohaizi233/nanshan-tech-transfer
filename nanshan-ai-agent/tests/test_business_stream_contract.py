import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main


class BusinessStreamContractTests(unittest.TestCase):
    def test_real_agent_stream_is_consumed_by_business_transport_without_field_translation(self):
        root = Path(__file__).resolve().parents[2]
        consumer = """
import io
import json
import sys
import time
sys.path.insert(0, sys.argv[1])
from modules.ai.chat_runner import consume_stream
stages = []
result = consume_stream(io.BytesIO(sys.stdin.buffer.read()), 'contract-one', time.monotonic() + 5, lambda stage, sequence: stages.append(stage))
print(json.dumps({'success': result['success'], 'intent': result['intent'], 'cards': result['data'], 'stages': stages}))
"""
        with patch.object(main.settings, "AI_INTERNAL_SERVICE_KEY", "contract-only-key"):
            with TestClient(main.app) as client:
                response = client.post("/internal/ai/chat/stream", headers={"X-AI-Service-Key": "contract-only-key"}, json={"executionId": "contract-one", "message": "你好", "exclude_owner_user_id": 99, "context": {"schemaVersion": 1, "generation": 1, "queryPlan": {}, "cards": [], "messages": []}})
        self.assertEqual(response.status_code, 200)
        process = subprocess.run([sys.executable, "-c", consumer, str(root / "tech-transfer-service")], input=response.content, capture_output=True, timeout=20)
        self.assertEqual(process.returncode, 0, process.stderr.decode("utf-8", "replace")[-1600:])
        result = json.loads(process.stdout)
        self.assertTrue(result["success"])
        self.assertEqual(result["cards"], [])
        self.assertIn("context", result["stages"])
        self.assertIn("formatting", result["stages"])
        self.assertNotIn("reranking", result["stages"])
