import json
import unittest
from unittest.mock import patch

import requests
from contextlib import redirect_stderr
from io import StringIO

from app import llm_client, reranker
from app.llm_client import LLMError


def response(status, content=None):
    result = requests.Response()
    result.status_code = status
    result.headers["Content-Type"] = "application/json"
    result._content = json.dumps(content or {"error": "unavailable"}).encode()
    return result


class AgentQualityTests(unittest.TestCase):
    def test_invalid_runtime_deadlines_fail_configuration_validation(self):
        for value in [-1.0, float("nan"), float("inf")]:
            with self.subTest(value=value), patch.object(llm_client.settings, "AI_CHAT_TIMEOUT_SECONDS", value):
                with redirect_stderr(StringIO()), self.assertRaises(SystemExit):
                    llm_client.settings.validate()

    def test_business_query_regression_cases_keep_their_intent_without_model_calls(self):
        from app.router import classify_intent

        cases = [
            ("你好", "out_of_scope", []),
            ("找人工智能成果", "search_achievement", ["人工智能"]),
            ("查询机器视觉技术需求", "search_demand", ["机器视觉"]),
            ("有没有生物医药相关成果", "search_achievement", ["生物医药"]),
            ("芯片方面", "search_achievement", ["芯片"]),
        ]
        with patch("app.router._classify_intent_llm", side_effect=AssertionError("unexpected model call")):
            for query, intent, keywords in cases:
                with self.subTest(query=query):
                    route = classify_intent(query)
                    self.assertEqual(route.intent, intent)
                    self.assertEqual(route.keywords, keywords)

    def test_malformed_rankings_do_not_crash_or_introduce_unknown_candidates(self):
        candidates = [{"id": number} for number in range(1, 5)]
        with patch.object(reranker, "_call_reranker", return_value={
            "results": [None, 7, {"id": 999}, {"id": 2}, {"id": 2}, {"id": 1}],
        }):
            result = reranker.rerank_results("search_achievement", "机器视觉成果", candidates, top_n=2)
        self.assertEqual([item["id"] for item in result], [2, 1])

    def test_nested_candidate_fields_cannot_exhaust_reranking_context(self):
        candidates = [{
            "id": number, "title": "成果", "tech_intro": "技术" * 10000,
            "innovation_points": [{"content": "创新" * 10000}] * 30,
            "application_fields": ["领域" * 10000] * 30,
            "contact_phone": "13800138000",
        } for number in range(1, 21)]
        with patch.object(reranker, "_call_reranker", return_value={"results": [{"id": 1}]}) as model:
            result = reranker.rerank_results("search_achievement", "技术成果", candidates)
        self.assertTrue(model.called)
        if model.called:
            payload = json.dumps(model.call_args.args[0], ensure_ascii=False, default=str)
            self.assertLessEqual(len(payload), 24000)
            self.assertNotIn("13800138000", payload)
        self.assertEqual(result[0]["id"], 1)

    def test_rankings_cannot_select_candidates_omitted_from_the_model_context(self):
        candidates = [{
            "id": number, "title": "成果", "tech_intro": "技术" * 1000,
            "innovation_points": ["创新" * 1000] * 4,
            "application_fields": ["领域" * 1000] * 4,
        } for number in range(1, 21)]
        with patch.object(reranker.settings, "AI_RERANK_MAX_CHARS", 10000), patch.object(
            reranker, "_call_reranker", return_value={"results": [{"id": 20}]},
        ) as model:
            result = reranker.rerank_results("search_achievement", "查询成果", candidates, top_n=1)
        self.assertTrue(model.called)
        self.assertNotIn(20, [item["id"] for item in model.call_args.args[0]["candidates"]])
        self.assertEqual(result[0]["id"], 1)

    def test_low_remaining_budget_preserves_local_ranking_without_another_model_call(self):
        candidates = [{"id": number} for number in range(1, 5)]
        with patch.object(reranker, "remaining_seconds", return_value=0.1), patch.object(reranker, "_call_reranker") as model:
            result = reranker.rerank_results("search_demand", "找技术需求", candidates, top_n=2)
        self.assertEqual(result, candidates[:2])
        model.assert_not_called()

    def test_primary_retries_share_the_configured_wall_clock_budget(self):
        clock = [0.0]

        def post(*args, **kwargs):
            clock[0] += 0.8
            return response(503)

        with (
            patch.object(llm_client.settings, "LLM_FALLBACK_BUDGET_SECONDS", 1.0),
            patch.object(llm_client.time, "monotonic", side_effect=lambda: clock[0]),
            patch.object(llm_client.time, "sleep", side_effect=lambda delay: clock.__setitem__(0, clock[0] + delay)),
            patch.object(llm_client.random, "uniform", return_value=0.25),
            patch.object(llm_client.requests, "post", side_effect=post) as model,
            patch.object(llm_client, "_write_call_log"),
            patch.object(llm_client, "_FALLBACK_URL", None),
        ):
            with self.assertRaises(LLMError):
                llm_client.chat_completion([{"role": "user", "content": "query"}], timeout=10)
        self.assertEqual(model.call_count, 1)
        self.assertLessEqual(model.call_args.kwargs["timeout"][1], 1.0)

    def test_non_retryable_provider_errors_do_not_consume_fallback_quota(self):
        with (
            patch.object(llm_client.requests, "post", return_value=response(400)) as model,
            patch.object(llm_client, "_write_call_log"),
            patch.object(llm_client, "_FALLBACK_URL", "https://fallback.invalid"),
            patch.object(llm_client, "_FALLBACK_KEY", "test"),
        ):
            with self.assertRaises(LLMError):
                llm_client.chat_completion([{"role": "user", "content": "query"}])
        self.assertEqual(model.call_count, 1)

    def test_nested_model_call_restores_the_previous_deadline(self):
        llm_client._fallback_deadline_local.value = 123.0
        try:
            with (
                patch.object(llm_client.requests, "post", return_value=response(200, {
                    "choices": [{"message": {"content": "{}"}}],
                })),
                patch.object(llm_client, "_write_call_log"),
            ):
                llm_client.chat_completion([{"role": "user", "content": "query"}])
            self.assertEqual(llm_client._fallback_deadline_local.value, 123.0)
        finally:
            del llm_client._fallback_deadline_local.value


if __name__ == "__main__":
    unittest.main()
