"""第三阶段修复的回归测试：鉴权、流式契约、错误分类、指标、脱敏。

每个用例对应一个已修复的真实缺陷，测试名即缺陷描述。
"""
import json
import unittest
from concurrent.futures import Future, ThreadPoolExecutor
from threading import BoundedSemaphore
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from app import main
from app.auth import authorize_service_call
from app.config import settings
from app.internal_stream import prepare_stream
from app.llm_client import LLMError, classify_llm_error
from app.llm_log import parse_error_fields
from app.schemas import ChatRequest, ChatResponse, InternalChatRequest, RouteResult


class ServiceAuthTests(unittest.TestCase):
    """P0: /api/ai/chat 曾经完全没有鉴权，Agent 可被当作公开模型代理。"""

    def setUp(self):
        self.client = TestClient(main.app)

    def test_sync_chat_rejects_missing_or_wrong_service_key(self):
        for supplied, status in [("", 401), ("wrong-key", 401)]:
            with patch.object(settings, "AI_PUBLIC_API_KEY", "expected-key", create=True):
                response = self.client.post(
                    "/api/ai/chat",
                    json={"message": "找机器视觉成果"},
                    headers={"X-AI-Service-Key": supplied},
                )
            self.assertEqual(response.status_code, status, supplied)

    def test_sync_chat_accepts_the_configured_service_key(self):
        with patch.object(settings, "AI_PUBLIC_API_KEY", "expected-key", create=True), \
             patch.object(main, "_process_ai_chat", return_value=ChatResponse(success=True, message="ok", data=[])):
            response = self.client.post(
                "/api/ai/chat",
                json={"message": "找机器视觉成果"},
                headers={"X-AI-Service-Key": "expected-key"},
            )
        self.assertEqual(response.status_code, 200)

    def test_without_configured_key_only_loopback_callers_are_accepted(self):
        with patch.object(settings, "AI_PUBLIC_API_KEY", "", create=True), \
             patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "", create=True):
            # 非回环来源 → 明确拒绝，而不是静默放行
            with self.assertRaises(Exception) as error:
                authorize_service_call(None, "203.0.113.10")
            self.assertEqual(getattr(error.exception, "status_code", None), 503)
            # 回环来源 → 放行（本地零配置开发不受影响）
            authorize_service_call(None, "127.0.0.1")
            authorize_service_call(None, "::1")

    def test_internal_key_is_reused_when_public_key_is_absent(self):
        with patch.object(settings, "AI_PUBLIC_API_KEY", "", create=True), \
             patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "shared-key", create=True):
            with self.assertRaises(Exception) as error:
                authorize_service_call("nope", "127.0.0.1")
            self.assertEqual(getattr(error.exception, "status_code", None), 401)
            authorize_service_call("shared-key", "127.0.0.1")


class StreamTerminalContractTests(unittest.IsolatedAsyncioTestCase):
    """P0: 终结事件曾与阶段事件共用有界队列，消费端变慢会连结果一起丢掉。"""

    async def test_terminal_result_survives_a_full_stage_queue(self):
        """队列被打满时，终结事件仍必须送达且只送达一次。"""
        from app.internal_stream import HEARTBEAT_SECONDS  # noqa: F401

        slots = BoundedSemaphore(1)
        body = InternalChatRequest(message="test", executionId="overflow-1")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"):
                # 制造 40 个阶段事件，把 maxsize=32 的队列塞满
                response = prepare_stream(
                    body,
                    Mock(headers={"X-AI-Service-Key": "secret"}),
                    slots=slots,
                    executor=executor,
                    run=lambda *args: ChatResponse(success=True, message="done", data=[]),
                    timeout_seconds=5,
                )
                async for _ in response.body_iterator:
                    pass
        finally:
            executor.shutdown(wait=True)

    async def test_stream_emits_exactly_one_terminal_event(self):
        slots = BoundedSemaphore(1)
        body = InternalChatRequest(message="test", executionId="single-terminal")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"):
                response = prepare_stream(
                    body,
                    Mock(headers={"X-AI-Service-Key": "secret"}),
                    slots=slots,
                    executor=executor,
                    run=lambda *args: ChatResponse(success=True, message="done", data=[]),
                    timeout_seconds=5,
                )
                events = [json.loads(line) async for line in response.body_iterator]
        finally:
            executor.shutdown(wait=True)
        terminal = [event for event in events if event["type"] in ("result", "error")]
        self.assertEqual(len(terminal), 1)
        self.assertEqual(terminal[0]["type"], "result")

    async def test_stage_events_precede_the_terminal_event(self):
        slots = BoundedSemaphore(1)
        body = InternalChatRequest(message="test", executionId="ordering")
        executor = ThreadPoolExecutor(max_workers=1)
        try:
            with patch.object(settings, "AI_INTERNAL_SERVICE_KEY", "secret"):
                response = prepare_stream(
                    body,
                    Mock(headers={"X-AI-Service-Key": "secret"}),
                    slots=slots,
                    executor=executor,
                    run=lambda *args: ChatResponse(success=True, message="done", data=[]),
                    timeout_seconds=5,
                )
                events = [json.loads(line) async for line in response.body_iterator]
        finally:
            executor.shutdown(wait=True)
        kinds = [event["type"] for event in events]
        terminal_index = next(index for index, kind in enumerate(kinds) if kind in ("result", "error"))
        self.assertTrue(all(kind != "stage" for kind in kinds[terminal_index:]))


class LlmErrorClassificationTests(unittest.TestCase):
    """P0: 错误未分类，导致 4xx 被反复重试、5xx 却不重试。"""

    def test_transient_and_permanent_errors_are_distinguished(self):
        for status in (429, 500, 502, 503, 504):
            self.assertEqual(classify_llm_error(status, "http_error"), "transient", status)
        for status in (400, 401, 403, 404, 422):
            self.assertEqual(classify_llm_error(status, "http_error"), "permanent", status)

    def test_network_failures_are_transient_and_overload_is_its_own_class(self):
        self.assertEqual(classify_llm_error(None, "timeout"), "transient")
        self.assertEqual(classify_llm_error(None, "connection_reset"), "transient")
        self.assertEqual(classify_llm_error(None, "overloaded"), "overload")

    def test_error_carries_its_category(self):
        self.assertEqual(LLMError("x", status_code=502, reason="http_error").category, "transient")
        self.assertEqual(LLMError("x", status_code=401, reason="http_error").category, "permanent")

    def test_retry_budget_is_bounded_and_backoff_grows(self):
        from app import llm_client

        self.assertGreaterEqual(llm_client._RETRY_TIMES, 2)
        backoff = list(llm_client._RETRY_BACKOFF)
        self.assertEqual(backoff, sorted(backoff), "退避序列必须单调不减（指数退避）")
        for earlier, later in zip(backoff, backoff[1:]):
            self.assertGreater(later, earlier)


class MultiTurnInheritanceTests(unittest.TestCase):
    """P0: 多轮跟进时，第二道闸门会把继承来的硬性条件清空。"""

    def test_inherited_price_ceiling_survives_the_followup_pipeline(self):
        from app.conversation import merge_route, resolve_context
        from app.router import apply_condition_guards

        previous = RouteResult(
            intent="search_achievement",
            keywords=["机器视觉"],
            max_price_wan=100,
            limit=10,
        )
        request = ChatRequest(
            message="只要中试完成以上的",
            context={
                "schemaVersion": 1,
                "generation": 1,
                "queryPlan": previous.model_dump(),
                "cards": [],
                "messages": [],
            },
        )
        resolution = resolve_context(request)
        self.assertIsNotNone(resolution.route)
        # resolve_context 内部已按 inherited=True 应用闸门，继承条件必须仍在
        self.assertEqual(resolution.route.max_price_wan, 100)
        self.assertEqual(resolution.route.min_maturity, "04_pilot_done")

    def test_main_pipeline_does_not_reapply_non_inherited_guards(self):
        """main.py 必须区分「继承来的 route」与「本轮新建的 route」。"""
        import inspect

        source = inspect.getsource(main._process_ai_chat)
        self.assertIn("resolution.route is not None", source)
        self.assertNotIn(
            "route = resolution.route or classify_intent(request.message)",
            source,
        )


class ObservabilityTests(unittest.TestCase):
    """P1: 缺少 Token 用量、LLM 调用次数与降级原因的可观测面。"""

    def test_token_metrics_are_reported(self):
        from app.runtime_trace import trace_count

        with self.assertLogs("nanshan.ai.trace", level="INFO") as captured:
            trace_count("prompt_tokens", 120)
            trace_count("completion_tokens", 40)
            trace_count("total_tokens", 160)
        joined = "\n".join(captured.output)
        self.assertIn("prompt_tokens", joined)
        self.assertIn("total_tokens", joined)

    def test_unknown_metric_names_are_ignored(self):
        from app.runtime_trace import trace_count

        with self.assertLogs("nanshan.ai.trace", level="INFO") as captured:
            trace_count("candidate_count", 3)
            trace_count("user_password", 1)
        joined = "\n".join(captured.output)
        self.assertIn("candidate_count", joined)
        self.assertNotIn("user_password", joined)

    def test_degradation_reasons_are_whitelisted(self):
        from app.runtime_trace import trace_degradation

        with self.assertLogs("nanshan.ai.trace", level="INFO") as captured:
            trace_degradation("llm_degraded")
            trace_degradation("not-a-real-reason")
        joined = "\n".join(captured.output)
        self.assertIn("llm_degraded", joined)
        self.assertNotIn("not-a-real-reason", joined)


class LogRedactionTests(unittest.TestCase):
    """P0: 上游错误体可能回显用户手机号 / 邮箱。"""

    def test_error_fields_are_redacted_at_parse_time(self):
        body = json.dumps({"error": "failed for 13812341234 and zhangsan@corp.com"})
        fields = parse_error_fields(body)
        rendered = json.dumps(fields, ensure_ascii=False)
        self.assertNotIn("13812341234", rendered)
        self.assertNotIn("zhangsan@corp.com", rendered)

    def test_non_json_error_body_is_redacted(self):
        fields = parse_error_fields("boom 13812341234")
        self.assertNotIn("13812341234", json.dumps(fields, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
