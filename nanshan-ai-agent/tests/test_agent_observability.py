import asyncio
import logging
import unittest
from concurrent.futures import Future
from threading import BoundedSemaphore
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException

from app import main
from app.schemas import ChatRequest


class AgentSlotTests(unittest.IsolatedAsyncioTestCase):
    async def test_submit_failure_returns_capacity(self):
        slots = BoundedSemaphore(1)
        with (
            patch.object(main, "_chat_slots", slots),
            patch.object(main._chat_executor, "submit", side_effect=RuntimeError("executor closed")),
        ):
            with self.assertRaises(RuntimeError):
                await main.ai_chat(ChatRequest(message="test"), Mock(headers={}))
        self.assertTrue(slots.acquire(blocking=False))
        self.assertFalse(slots.acquire(blocking=False))

    async def test_queued_worker_is_cancelled_and_returns_capacity_on_timeout(self):
        worker = Future()
        slots = BoundedSemaphore(1)
        request = Mock(headers={})
        request.is_disconnected = AsyncMock(return_value=False)
        with (
            patch.object(main, "_chat_slots", slots),
            patch.object(main._chat_executor, "submit", return_value=worker),
            patch.object(main.settings, "AI_CHAT_TIMEOUT_SECONDS", 0.01),
        ):
            with self.assertRaises(HTTPException):
                await main.ai_chat(ChatRequest(message="test"), request)
            await asyncio.sleep(0)
        self.assertTrue(worker.cancelled())
        self.assertTrue(slots.acquire(blocking=False))
        self.assertFalse(slots.acquire(blocking=False))

    async def test_timeout_does_not_release_capacity_until_worker_has_really_finished(self):
        worker = Future()
        worker.set_running_or_notify_cancel()
        slots = BoundedSemaphore(1)
        request = Mock(headers={})
        request.is_disconnected = AsyncMock(return_value=False)
        with (
            patch.object(main, "_chat_slots", slots),
            patch.object(main._chat_executor, "submit", return_value=worker),
            patch.object(main.settings, "AI_CHAT_TIMEOUT_SECONDS", 0.01),
        ):
            try:
                with self.assertRaises(HTTPException) as error:
                    await main.ai_chat(ChatRequest(message="test"), request)
                self.assertEqual(error.exception.status_code, 504)
                self.assertFalse(slots.acquire(blocking=False))
            finally:
                worker.set_result(None)
                await asyncio.sleep(0)
        self.assertTrue(slots.acquire(blocking=False))


class AgentTraceTests(unittest.TestCase):
    def test_callers_can_shorten_but_not_expand_the_agent_timeout(self):
        with patch.object(main.settings, "AI_CHAT_TIMEOUT_SECONDS", 90):
            self.assertEqual(main.chat_timeout_seconds("12.5"), 12.5)
            for value in ["9999", "nan", "inf", "bad", "-1", None]:
                self.assertEqual(main.chat_timeout_seconds(value), 90)

    def test_request_traces_are_scoped_and_do_not_log_prompt_contents(self):
        from app.runtime_trace import current_trace_id, request_trace, trace_stage

        with request_trace("request-one"):
            self.assertEqual(current_trace_id(), "request-one")
            with self.assertLogs("nanshan.ai.trace", level=logging.INFO) as captured:
                with trace_stage("retrieval"):
                    pass
            with request_trace("request-two"):
                self.assertEqual(current_trace_id(), "request-two")
            self.assertEqual(current_trace_id(), "request-one")
        self.assertEqual(current_trace_id(), "")
        self.assertIn("stage=retrieval", captured.output[0])
        self.assertIn("request-one", captured.output[0])

    def test_untrusted_trace_headers_are_replaced_and_stage_failures_are_measured(self):
        from app.runtime_trace import current_trace_id, request_trace, trace_stage

        with request_trace("unsafe\nheader"):
            self.assertNotIn("unsafe", current_trace_id())
            with self.assertLogs("nanshan.ai.trace", level=logging.INFO) as captured:
                with self.assertRaises(ValueError):
                    with trace_stage("rerank"):
                        raise ValueError("private user content")
        self.assertIn("outcome=error", captured.output[0])
        self.assertNotIn("private user content", captured.output[0])
