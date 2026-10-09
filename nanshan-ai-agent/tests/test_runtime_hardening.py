import unittest
from unittest.mock import Mock, patch

import requests

from app.llm_client import LLMError, chat_completion
from app.reranker import rerank_results
from app.runtime_budget import reset_deadline, set_deadline


class RuntimeHardeningTests(unittest.TestCase):
    def _response(self, status_code):
        response = requests.Response()
        response.status_code = status_code
        response.headers["Content-Type"] = "application/json"
        response._content = b'{"error":"upstream rejected request"}'
        return response

    def test_non_retryable_http_status_is_not_retried(self):
        with (
            patch("app.llm_client.requests.post", return_value=self._response(401)) as post,
            patch("app.llm_client._write_call_log"),
            patch("app.llm_client.time.sleep"),
        ):
            with self.assertRaises(LLMError):
                chat_completion([{"role": "user", "content": "hello"}], timeout=1)

        self.assertEqual(post.call_count, 1)

    def test_model_error_logging_preserves_llm_error(self):
        from app.llm_client import _write_call_log

        with patch("app.llm_client.enqueue_llm_log") as enqueue:
            _write_call_log(
                ok=False,
                input_payload={"model": "test", "url": "http://gateway", "messages": []},
                attempt=0,
                status=None,
                reason="connection_reset",
                error_type="ConnectionError",
                error_message="connection reset",
            )

        enqueue.assert_called_once()

    def test_reranker_network_error_does_not_issue_a_second_model_call(self):
        candidates = [{"id": 1}, {"id": 2}, {"id": 3}]
        with patch(
            "app.reranker.chat_completion",
            side_effect=LLMError("gateway unavailable", reason="connection_reset"),
        ) as completion:
            result = rerank_results(
                "search_achievement",
                "find AI results",
                candidates,
                top_n=2,
            )

        self.assertEqual(completion.call_count, 1)
        self.assertEqual(result, candidates[:2])

    def test_database_discards_connection_after_query_error(self):
        from app import database

        connection = Mock(closed=0)
        pool = Mock()
        pool.getconn.return_value = connection
        with (
            patch.object(database, "_pool", pool),
            patch.object(database, "_connection_slots"),
        ):
            with self.assertRaisesRegex(RuntimeError, "query failed"):
                with database.get_db():
                    raise RuntimeError("query failed")

        pool.putconn.assert_called_once_with(connection, close=True)

    def test_search_term_escapes_like_wildcards(self):
        from app.services.query_utils import escape_like_term

        self.assertEqual(escape_like_term(r"50%_ready\x"), r"50\%\_ready\\x")

    def test_expired_chat_budget_rejects_without_calling_model(self):
        token = set_deadline(0)
        try:
            with patch("app.llm_client.requests.post") as post:
                with self.assertRaisesRegex(LLMError, "超过总时限"):
                    chat_completion([{"role": "user", "content": "hello"}])
            post.assert_not_called()
        finally:
            reset_deadline(token)

    def test_explicit_query_marker_uses_rules_when_model_is_unavailable(self):
        from app.router import classify_intent

        with patch(
            "app.router._classify_intent_llm",
            side_effect=LLMError("gateway unavailable", reason="connection_reset"),
        ):
            route = classify_intent("我想找机器视觉科技成果，预算100万以内")

        self.assertEqual(route.intent, "search_achievement")
        self.assertIn("机器视觉", route.keywords)

    def test_database_health_uses_503_on_failure(self):
        from app import main

        with patch("app.main.get_db", side_effect=RuntimeError("database down")):
            response = main.db_health()

        self.assertEqual(response.status_code, 503)

    def test_expanded_search_terms_are_bounded(self):
        from app.services.achievement_service import expand_keywords

        terms = expand_keywords(["人工智能", "机器视觉", "芯片", "生物医药"])
        self.assertLessEqual(len(terms), 8)


if __name__ == "__main__":
    unittest.main()