import unittest
from unittest.mock import MagicMock, patch

from app import main, reranker
from app.schemas import ChatRequest, RouteResult


class AdvisorTests(unittest.TestCase):
    def test_platform_help_uses_verified_navigation_without_database_or_model_calls(self):
        cases = [
            ("介绍一下南山科转通平台", "我要发成果"),
            ("怎么发布成果", "我要发成果"),
            ("怎么发布成果并申请对接", "提交对接意向"),
            ("如何发布技术需求", "我要发需求"),
            ("如何申请对接", "提交对接意向"),
            ("这个成果怎么对接", "提交对接意向"),
            ("怎么查看对接进度", "意向请求"),
            ("如何进行机构认证", "机构认证"),
            ("怎么收藏成果", "收藏"),
            ("如何登录", "我的"),
            ("你好", "介绍"),
        ]
        with patch.object(main, "classify_intent", side_effect=AssertionError("unexpected model")), patch.object(main, "search_achievements") as search:
            for query, expected in cases:
                with self.subTest(query=query):
                    result = main._process_ai_chat(ChatRequest(message=query))
                    self.assertIn(expected, result.message)
                    self.assertEqual(result.data, [])
        search.assert_not_called()

    def test_generic_recommendation_and_unresolved_card_reference_ask_for_context(self):
        for query in ["给我推荐几个好的成果", "介绍一下第一个", "这个适合我吗", "介绍这个成果", "第一个有什么优势", "介绍第一个成果的应用领域", "这个成果的预算是多少", "它有哪些亮点"]:
            with self.subTest(query=query), patch.object(main, "classify_intent", side_effect=AssertionError("unexpected model")):
                result = main._process_ai_chat(ChatRequest(message=query))
                self.assertIn("请", result.message)
                self.assertEqual(result.data, [])

    def test_recommendations_include_grounded_introduction_reasons_and_missing_information(self):
        item = {"id": 7, "title": "机器视觉检测", "tech_intro": "用于生产线缺陷检测", "application_fields": ["工业质检"]}
        route = RouteResult(intent="search_achievement", keywords=["机器视觉"])
        with patch.object(main, "classify_intent", return_value=route), patch.object(main, "search_achievements", return_value=[item]), patch.object(main, "rerank_results", return_value=[item]):
            result = main._process_ai_chat(ChatRequest(message="推荐机器视觉成果"))
        card = result.data[0]
        self.assertIn("生产线缺陷检测", card["advisorSummary"])
        self.assertTrue(any("机器视觉" in reason for reason in card["matchReason"]))
        self.assertTrue(any("成熟度" in concern for concern in card["advisorCautions"]))
        self.assertTrue(any("报价" in concern for concern in card["advisorCautions"]))
        self.assertIn("推荐", result.message)
        self.assertIn("场景", result.message)

    def test_introduction_is_not_replaced_by_platform_help(self):
        from app.advisor import local_reply
        self.assertIsNone(local_reply("平台有哪些机器视觉成果"))
        self.assertIsNone(local_reply("介绍机器视觉成果"))

    def test_long_near_generic_input_does_not_trigger_regex_backtracking(self):
        from app.advisor import local_reply
        self.assertIsNone(local_reply("好的" * 900 + "X"))

    def test_no_match_response_does_not_invent_recommendations(self):
        route = RouteResult(intent="search_achievement", keywords=["机器人"])
        with patch.object(main, "classify_intent", return_value=route), patch.object(main, "search_achievements", return_value=[]):
            result = main._process_ai_chat(ChatRequest(message="推荐机器人技术成果"))
        self.assertEqual(result.data, [])
        self.assertIn("条件", result.message)

    def test_reranker_adds_explanations_without_a_separate_writer_call(self):
        candidates = [{"id": number, "tech_intro": "用于工业质检", "title": "机器视觉成果"} for number in range(1, 5)]
        with patch.object(reranker, "_call_reranker", return_value={"results": [{
            "id": 2, "evidence": [{"field": "tech_intro", "quote": "工业质检"}],
            "analysis": "可优先核对工业质检场景中的适配条件。",
        }]}) as model:
            result = reranker.rerank_results("search_achievement", "推荐机器视觉成果", candidates)
        model.assert_called_once()
        self.assertEqual(result[0]["id"], 2)
        self.assertEqual(result[0]["_advisor_evidence"], ["工业质检"])
        self.assertIn("适配", result[0]["_advisor_insight"])

    def test_fabricated_evidence_metrics_or_contact_fields_are_not_exposed(self):
        from app.advisor import grounded_explanation
        item = {"id": 1, "tech_intro": "用于工业质检", "contact_phone": "13900000000"}
        for ranking in [
            {"evidence": [{"field": "tech_intro", "quote": "通过国家认证"}], "analysis": "保证通过认证"},
            {"evidence": [{"field": "contact_phone", "quote": "13900000000"}], "analysis": "请拨打13900000000"},
            {"evidence": [{"field": "tech_intro", "quote": "工业质检"}], "analysis": "可提升效率99%"},
        ]:
            with self.subTest(ranking=ranking):
                self.assertEqual(grounded_explanation(ranking, item)[1], "")

    def test_explicit_introduction_and_recommendation_templates_do_not_need_llm_routing(self):
        from app.router import classify_intent
        with patch("app.router._classify_intent_llm", side_effect=AssertionError("unexpected model")):
            for query in ["介绍一下机器视觉成果", "推荐人工智能成果", "解读生物医药成果"]:
                with self.subTest(query=query):
                    result = classify_intent(query)
                    self.assertEqual(result.intent, "search_achievement")
                    self.assertNotIn("介绍", "".join(result.keywords))

    def test_complex_recommendation_uses_semantic_filters_instead_of_searching_the_whole_sentence(self):
        from app.router import classify_intent
        route = RouteResult(intent="search_achievement", keywords=["机器视觉", "工业质检"], max_price_wan=100)
        with patch("app.router._classify_intent_llm", return_value=route) as classify:
            result = classify_intent("推荐适合工业质检的机器视觉成果，预算100万以内")
        classify.assert_called_once()
        self.assertEqual(result.max_price_wan, 100)

    def test_retrieval_excludes_soft_deleted_records_from_recommendations(self):
        from app.services import achievement_service, demand_service
        for module, search in [(achievement_service, achievement_service.search_achievements), (demand_service, demand_service.search_demands)]:
            database = MagicMock()
            cursor = database.__enter__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchall.return_value = []
            with self.subTest(module=module.__name__), patch.object(module, "get_db", return_value=database):
                self.assertEqual(search(keywords=["机器视觉"]), [])
            sql = cursor.execute.call_args.args[0]
            self.assertIn("deleted_at IS NULL", sql)

    def test_malformed_explanation_fields_do_not_break_valid_rankings(self):
        from app.advisor import grounded_explanation
        item = {"tech_intro": "用于工业质检"}
        for entry in [None, 7, {"field": []}, {"field": "tech_intro", "quote": {}}, {"field": "tech_intro", "quote": None}]:
            with self.subTest(entry=entry):
                self.assertEqual(grounded_explanation({"evidence": [entry], "analysis": []}, item), ([], ""))


if __name__ == "__main__":
    unittest.main()
