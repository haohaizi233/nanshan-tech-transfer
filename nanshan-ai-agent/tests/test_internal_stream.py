import json
import unittest
import asyncio
from concurrent.futures import Future
from threading import BoundedSemaphore
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import main
from app.config import settings
from app.schemas import ChatResponse, InternalChatRequest
from app.internal_stream import prepare_stream


class InternalStreamTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(main.app)

    def test_private_stream_fails_closed_without_key_or_with_wrong_key(self):
        for configured, supplied, status in [("", "", 503), ("secret", "", 401), ("secret", "wrong", 401)]:
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", configured, create=True):
                response = self.client.post("/internal/ai/chat/stream", json={"message": "你好", "executionId": "run-1"}, headers={"X-AI-Service-Key": supplied})
                self.assertEqual(response.status_code, status)

    def test_private_readiness_checks_configuration_without_model_call(self):
        with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"), patch.object(main, "classify_intent", side_effect=AssertionError("no model")):
            self.assertEqual(self.client.get("/internal/ai/ready").status_code, 401)
            ready = self.client.get("/internal/ai/ready", headers={"X-AI-Service-Key": "secret"})
        self.assertEqual(ready.status_code, 200)
        self.assertEqual(ready.json()["schemaVersion"], 1)
        self.assertEqual(ready.json()["capacity"], settings.AI_CHAT_MAX_CONCURRENCY)
        self.assertLessEqual(ready.json()["executionBudgetSeconds"], 55)

    def test_stream_real_stages_and_one_terminal_result(self):
        with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret", create=True):
            response = self.client.post("/internal/ai/chat/stream", json={"message": "你好", "executionId": "run-1"}, headers={"X-AI-Service-Key": "secret"})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertTrue(all(event["executionId"] == "run-1" for event in events))
        stages = [event for event in events if event["type"] == "stage"]
        self.assertEqual([event["stage"] for event in stages], ["context", "formatting"])
        self.assertEqual([event["sequence"] for event in stages], [1, 2])
        terminal = [event for event in events if event["type"] in ("result", "error")]
        self.assertEqual(len(terminal), 1)
        self.assertTrue(terminal[0]["result"]["success"])

    def test_stream_error_does_not_expose_exception_details(self):
        with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret", create=True), patch.object(main, "_process_ai_chat", side_effect=RuntimeError("private-password")):
            response = self.client.post("/internal/ai/chat/stream", json={"message": "你好", "executionId": "run-2"}, headers={"X-AI-Service-Key": "secret"})
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual(events[-1]["type"], "error")
        self.assertNotIn("private-password", response.text)

    def test_small_search_skips_reranking_stage_but_real_model_rerank_emits_it(self):
        item = {"id": 1, "title": "机器视觉", "tech_intro": "用于工业质检"}
        for count, expected in [(1, False), (4, True)]:
            records = [{**item, "id": number} for number in range(1, count + 1)]
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"), patch.object(main, "search_achievements", return_value=records), patch("app.reranker._call_reranker", return_value={"results": [{"id": 1}]}):
                response = self.client.post("/internal/ai/chat/stream", json={"message": "找机器视觉成果", "executionId": "run-3"}, headers={"X-AI-Service-Key": "secret"})
            events = [json.loads(line) for line in response.text.splitlines()]
            stages = [event["stage"] for event in events if event["type"] == "stage"]
            self.assertEqual("reranking" in stages, expected)
            self.assertIn("retrieving", stages)


class StreamLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def test_slow_consumer_cannot_observe_success_before_terminal_result(self):
        from unittest.mock import Mock
        clock = [0.0]
        executor = Mock()

        def submit(callback):
            callback()
            completed = Future()
            completed.set_result(None)
            return completed

        executor.submit.side_effect = submit
        body = InternalChatRequest(message="test", executionId="slow-reader")
        with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"), patch("app.internal_stream.time.monotonic", side_effect=lambda: clock[0]):
            response = prepare_stream(body, Mock(headers={"X-AI-Service-Key": "secret"}), slots=BoundedSemaphore(1), executor=executor,
                run=lambda *args: ChatResponse(success=True, intent="out_of_scope", message="done", data=[]), timeout_seconds=1)
            first = json.loads(await response.body_iterator.__anext__())
            clock[0] = 2.0
            remaining = [json.loads(line) async for line in response.body_iterator]
        self.assertEqual(first["type"], "result")
        self.assertFalse(remaining)

    async def test_running_timeout_retains_capacity_until_actual_future_completes(self):
        from unittest.mock import Mock
        worker = Future()
        worker.set_running_or_notify_cancel()
        executor = Mock()
        executor.submit.return_value = worker
        slots = BoundedSemaphore(1)
        body = InternalChatRequest(message="test", executionId="timeout-1")
        with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"):
            response = prepare_stream(body, Mock(headers={"X-AI-Service-Key": "secret"}), slots=slots, executor=executor, run=Mock(), timeout_seconds=0.01)
            lines = [line async for line in response.body_iterator]
        self.assertEqual(json.loads(lines[-1])["reason"], "timeout")
        self.assertFalse(slots.acquire(blocking=False))
        worker.set_result(None)
        self.assertTrue(slots.acquire(blocking=False))

    async def test_oversize_result_has_one_error_and_never_an_early_success_stage(self):
        from concurrent.futures import ThreadPoolExecutor
        from unittest.mock import Mock
        slots = BoundedSemaphore(1)
        body = InternalChatRequest(message="test", executionId="size-1")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"):
                response = prepare_stream(body, Mock(headers={"X-AI-Service-Key": "secret"}), slots=slots, executor=executor,
                    run=lambda *args: ChatResponse(success=True, message="长" * 100000, data=[]), timeout_seconds=1)
                events = [json.loads(line) async for line in response.body_iterator]
        finally:
            executor.shutdown(wait=True)
        self.assertEqual(events[-1]["reason"], "stream_limit")
        self.assertFalse(any(event.get("stage") == "succeeded" for event in events))
        self.assertEqual(sum(event["type"] in ("result", "error") for event in events), 1)


if __name__ == "__main__":
    unittest.main()
