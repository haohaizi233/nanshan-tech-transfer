"""evaluate_achievement 对话工具化测试：意图分发 + evaluation_service 调用（mock）。

约定与 test_conversation.py 一致：unittest + patch，不打真实 LLM / HTTP / DB。
"""
import io
import json
import unittest
import urllib.error
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app import main
from app.schemas import ChatRequest, RouteResult
from app.services import evaluation_service

EVALUATION_VIEW = {
    "evaluationId": 11,
    "taskId": 7,
    "achievementId": 5,
    "achievementTitle": "仿生灵巧手",
    "totalScore": 87.5,
    "conclusion": "技术路线清晰，建议补充中试数据。",
    "highlights": ["结构设计完整", "应用场景明确"],
    "dimensions": [
        {"key": "tech", "label": "技术水平", "score": 90, "weight": 0.3, "starScore": 4.5, "comment": "结构紧凑"},
    ],
    "rating": "good",
    "ratingLabel": "良好",
    "starScore": 4.5,
}


def record(owner=7, identifier=5, title="仿生灵巧手"):
    return {
        "id": identifier,
        "owner_user_id": owner,
        "status": "published",
        "deleted_at": None,
        "title": title,
        "source_org_name": "某某研究院",
        "tech_intro": "仿生灵巧手简介",
        "pricing_mode": "negotiable",
        "price_min_wan": None,
        "price_max_wan": None,
        "maturity_level": "03_pilot_ready",
        "application_fields": ["智能制造"],
        "innovation_points": "轻量化",
        "contact_name": "张三",
        "contact_phone": "13800001234",
        "contact_email": "a@b.com",
        "view_count": 3,
        "created_at": None,
    }


def context(cards=None, plan=None):
    return {"schemaVersion": 1, "generation": 2, "queryPlan": plan or {},
            "cards": cards or [], "messages": []}


def locator(identifier, title="仿生灵巧手", message_id=5):
    return {"card_type": "achievement", "id": identifier, "title": title, "messageId": message_id}


def succeeded_outcome():
    return {"status": "succeeded", "taskId": 7, "evaluation": {
        "totalScore": 87.5, "rating": "good", "ratingLabel": "良好",
        "conclusion": "技术路线清晰。", "highlights": ["结构设计完整"],
        "dimensions": EVALUATION_VIEW["dimensions"],
    }}


class RouteSchemaTests(unittest.TestCase):
    """意图识别结果的 schema 约束（evaluate_achievement 专用字段）。"""

    def test_evaluate_route_accepts_target_id_and_target_name(self):
        route = RouteResult(intent="evaluate_achievement", target_id=3)
        self.assertEqual(route.target_id, 3)
        route = RouteResult(intent="evaluate_achievement", target_name="仿生灵巧手")
        self.assertEqual(route.target_name, "仿生灵巧手")

    def test_evaluate_route_rejects_search_only_conditions(self):
        for values in [{"min_price_wan": 10}, {"max_price_wan": 100}, {"min_maturity": "03_pilot_ready"},
                       {"organization": "研究院"}, {"region": "深圳"}, {"coop_modes": ["技术转让"]},
                       {"min_budget_wan": 1}, {"max_budget_wan": 2}]:
            with self.subTest(values=values), self.assertRaises(ValidationError):
                RouteResult(intent="evaluate_achievement", **values)

    def test_target_id_must_be_positive(self):
        with self.assertRaises(ValidationError):
            RouteResult(intent="evaluate_achievement", target_id=0)

    def test_evaluation_request_detection(self):
        for text in ("帮我评估刚才那个成果", "评估一下仿生灵巧手", "评估成果3", "查看仿生灵巧手的评估结果"):
            self.assertTrue(main._is_evaluation_request(text), text)
        for text in ("比较第一个和第二个", "机器视觉成果", "你好"):
            self.assertFalse(main._is_evaluation_request(text), text)

    def test_view_only_prefers_existing_result(self):
        for text in ("查看仿生灵巧手的评估结果", "仿生灵巧手的评估报告出来了吗", "评估进度怎么样"):
            self.assertTrue(main._wants_existing_result(text), text)
        for text in ("评估一下仿生灵巧手", "帮我评估刚才那个成果", "评估成果3", "重新评估仿生灵巧手"):
            self.assertFalse(main._wants_existing_result(text), text)


class EvaluationServiceTests(unittest.TestCase):
    """evaluation_service：创建后立即返回 pending（不再同步轮询）；prefer_existing 查历史。"""

    def test_create_returns_pending_immediately(self):
        responses = [{"taskId": 7, "status": "queued", "isNew": True}]
        with patch.object(evaluation_service, "_api", side_effect=responses) as api:
            outcome = evaluation_service.evaluate(7, 5)
        self.assertEqual(outcome["status"], "pending")
        self.assertEqual(outcome["taskId"], 7)
        self.assertIsNone(outcome["evaluation"])
        self.assertEqual(outcome["progressStage"], "排队中")  # 创建响应未带进度时的默认文案
        self.assertEqual(api.call_count, 1)  # 只创建任务，不同步轮询等待结果
        self.assertEqual(api.call_args_list[0].args[:2], ("POST", "/internal/ai/evaluation-tasks"))
        self.assertEqual(api.call_args_list[0].kwargs["payload"], {"userId": 7, "achievementId": 5})

    def test_pending_reports_created_progress_stage(self):
        responses = [
            {"taskId": 7, "status": "queued", "isNew": True, "progressStage": "正在生成评价报告"},
        ]
        with patch.object(evaluation_service, "_api", side_effect=responses) as api:
            outcome = evaluation_service.evaluate(7, 5)
        self.assertEqual(outcome["status"], "pending")
        self.assertEqual(outcome["taskId"], 7)
        self.assertEqual(outcome["progressStage"], "正在生成评价报告")
        self.assertIsNone(outcome["evaluation"])
        self.assertEqual(api.call_count, 1)  # 不做轮询，进度由前端 stream 获取

    def test_create_errors_raise_user_safe_error(self):
        # 创建接口业务拒绝：错误原文（已脱敏文案）透传给调用方
        error = evaluation_service.EvaluationError("AI 服务暂时不可用，请稍后重试")
        with patch.object(evaluation_service, "_api", side_effect=error):
            with self.assertRaises(evaluation_service.EvaluationError) as caught:
                evaluation_service.evaluate(7, 5)
        self.assertEqual(caught.exception.user_message, "AI 服务暂时不可用，请稍后重试")

        # 创建响应缺少 taskId：无法追踪任务，报通用错误
        with patch.object(evaluation_service, "_api", return_value={"status": "queued"}):
            with self.assertRaises(evaluation_service.EvaluationError) as caught:
                evaluation_service.evaluate(7, 5)
        self.assertEqual(caught.exception.user_message, evaluation_service.GENERIC_ERROR)

    def test_prefer_existing_returns_summarized_result(self):
        # prefer_existing 只查历史：已有评估 → succeeded + 摘要，不再创建任务
        payload = {"list": [dict(EVALUATION_VIEW, taskId=7)], "total": 1, "page": 1, "pageSize": 1}
        with patch.object(evaluation_service, "_api", return_value=payload) as api:
            outcome = evaluation_service.evaluate(7, 5, prefer_existing=True)
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(outcome["taskId"], 7)
        summary = outcome["evaluation"]
        self.assertEqual(
            set(summary),
            {"totalScore", "rating", "ratingLabel", "conclusion", "highlights", "dimensions"},
        )
        self.assertEqual(summary["totalScore"], 87.5)
        self.assertEqual(summary["ratingLabel"], "良好")
        self.assertEqual(summary["highlights"], ["结构设计完整", "应用场景明确"])
        self.assertEqual(len(summary["dimensions"]), 1)
        api.assert_called_once()  # 只查历史，不创建任务
        self.assertEqual(api.call_args.args[:2], ("GET", "/internal/ai/evaluations"))

    def test_evaluate_never_polls_after_create(self):
        # 第二个响应是瞬时故障：若 evaluate 还会轮询就会消费它并受影响；
        # 新行为只调创建接口，后续状态由前端 stream 获取。
        responses = [
            {"taskId": 7, "status": "queued", "isNew": True},
            evaluation_service.EvaluationError(evaluation_service.GENERIC_ERROR),
        ]
        with patch.object(evaluation_service, "_api", side_effect=responses) as api:
            outcome = evaluation_service.evaluate(7, 5)
        self.assertEqual(outcome["status"], "pending")
        self.assertEqual(api.call_count, 1)

    def test_prefer_existing_skips_task_creation(self):
        payload = {"list": [dict(EVALUATION_VIEW, taskId=7)], "total": 1, "page": 1, "pageSize": 1}
        with patch.object(evaluation_service, "_api", return_value=payload) as api:
            outcome = evaluation_service.evaluate(7, 5, prefer_existing=True)
        self.assertEqual(outcome["status"], "succeeded")
        self.assertEqual(outcome["evaluation"]["totalScore"], 87.5)
        api.assert_called_once()
        self.assertEqual(api.call_args.args[:2], ("GET", "/internal/ai/evaluations"))
        self.assertEqual(api.call_args.kwargs["query"],
                         {"userId": 7, "achievementId": 5, "page": 1, "pageSize": 1})

    def test_prefer_existing_without_history_reports_missing(self):
        with patch.object(evaluation_service, "_api", return_value={"list": [], "total": 0}):
            outcome = evaluation_service.evaluate(7, 5, prefer_existing=True)
        self.assertEqual(outcome["status"], "missing")

    def test_api_unwraps_success_envelope_and_maps_biz_error(self):
        def fake_response(payload):
            response = MagicMock()
            response.__enter__.return_value = SimpleNamespace(read=lambda: json.dumps(payload).encode())
            response.__exit__.return_value = False
            return response

        with patch.object(evaluation_service.urllib.request, "urlopen",
                          return_value=fake_response({"code": 0, "message": "ok", "data": {"taskId": 7}})) as opener:
            data = evaluation_service._api("POST", "/internal/ai/evaluation-tasks", payload={"userId": 7})
        self.assertEqual(data, {"taskId": 7})
        request = opener.call_args.args[0]
        self.assertEqual(request.get_header("X-ai-service-key"), evaluation_service._service_key())
        self.assertEqual(request.full_url, evaluation_service.settings.TECH_TRANSFER_API_URL + "/internal/ai/evaluation-tasks")

        body = json.dumps({"code": "TT_ACH_40301", "message": "非成果所有者"}).encode()
        error = urllib.error.HTTPError("http://x", 403, "Forbidden", None, io.BytesIO(body))
        with patch.object(evaluation_service.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(evaluation_service.EvaluationError) as caught:
                evaluation_service._api("POST", "/internal/ai/evaluation-tasks", payload={"userId": 7})
        self.assertEqual(caught.exception.user_message, "仅成果所有者可以发起评估，请确认该成果属于你。")

    def test_api_unreachable_raises_user_safe_error(self):
        error = urllib.error.URLError("connection refused")
        with patch.object(evaluation_service.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(evaluation_service.EvaluationError) as caught:
                evaluation_service._api("POST", "/internal/ai/evaluation-tasks", payload={"userId": 7})
        self.assertEqual(caught.exception.user_message, evaluation_service.GENERIC_ERROR)


class EvaluateDispatchTests(unittest.TestCase):
    """_process_ai_chat 的 evaluate_achievement 意图分发。"""

    def evaluate_route(self, **kwargs):
        return RouteResult(intent="evaluate_achievement", **kwargs)

    def test_named_target_runs_tool_and_returns_frontend_card(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(main, "search_achievements", side_effect=AssertionError("no search")), \
                patch.object(evaluation_service, "resolve_target", return_value=record()) as resolve, \
                patch.object(evaluation_service, "evaluate", return_value=succeeded_outcome()) as evaluate:
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertTrue(result.success)
        self.assertEqual(result.intent, "evaluate_achievement")
        self.assertIn("评估完成", result.message)
        self.assertIn("87.5 分（良好）", result.message)
        self.assertEqual(len(result.data), 1)
        card = result.data[0]
        self.assertEqual(card["card_type"], "achievement")
        self.assertEqual(card["id"], 5)
        self.assertEqual(card["evaluation"], succeeded_outcome()["evaluation"])
        resolve.assert_called_once_with(7, target_id=None, target_name="仿生灵巧手")
        evaluate.assert_called_once_with(7, 5, prefer_existing=False)
        self.assertEqual(result.queryPlan["intent"], "evaluate_achievement")

    def test_view_only_message_prefers_existing_result(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record()), \
                patch.object(evaluation_service, "evaluate", return_value=succeeded_outcome()) as evaluate:
            result = main._process_ai_chat(ChatRequest(message="查看仿生灵巧手的评估结果", exclude_owner_user_id=7))
        self.assertEqual(result.intent, "evaluate_achievement")
        evaluate.assert_called_once_with(7, 5, prefer_existing=True)

    def test_evaluate_intent_never_enters_search_pipeline(self):
        route = self.evaluate_route(target_id=3)
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(main, "search_achievements", side_effect=AssertionError("no search")), \
                patch.object(evaluation_service, "resolve_target", return_value=record(identifier=3)) as resolve, \
                patch.object(evaluation_service, "evaluate", return_value=succeeded_outcome()):
            result = main._process_ai_chat(ChatRequest(message="评估成果3", exclude_owner_user_id=7))
        self.assertEqual(result.intent, "evaluate_achievement")
        resolve.assert_called_once_with(7, target_id=3, target_name=None)

    def test_referenced_card_evaluation_skips_intent_model(self):
        route = RouteResult(intent="search_achievement", keywords=["机器视觉"])
        with patch.object(main, "classify_intent", side_effect=AssertionError("no model")), \
                patch.object(main, "search_achievements", side_effect=AssertionError("no search")), \
                patch.object(evaluation_service, "resolve_target", return_value=record(identifier=2)) as resolve, \
                patch.object(evaluation_service, "evaluate", return_value=succeeded_outcome()) as evaluate:
            result = main._process_ai_chat(ChatRequest(
                message="帮我评估刚才那个成果", exclude_owner_user_id=7,
                context=context([locator(2)]),
            ))
        self.assertEqual(result.intent, "evaluate_achievement")
        resolve.assert_called_once_with(7, target_id=2, target_name=None)
        evaluate.assert_called_once_with(7, 2, prefer_existing=False)
        self.assertEqual(result.data[0]["id"], 2)

    def test_login_required(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", side_effect=AssertionError("no lookup")):
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手"))
        self.assertIn("登录", result.message)

    def test_non_owner_is_rejected_before_tool_call(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record(owner=99)), \
                patch.object(evaluation_service, "evaluate", side_effect=AssertionError("no tool")):
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertIn("仅成果所有者", result.message)

    def test_missing_target_clarifies(self):
        route = self.evaluate_route(target_name="不存在的成果")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=None):
            result = main._process_ai_chat(ChatRequest(message="评估一下不存在的成果", exclude_owner_user_id=7))
        self.assertIn("没有找到", result.message)

    def test_lookup_error_maps_to_database_unavailable(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", side_effect=RuntimeError("db down")):
            with self.assertRaises(HTTPException) as caught:
                main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertEqual(caught.exception.status_code, 503)

    def test_pending_reply_keeps_user_informed(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        outcome = {"status": "pending", "taskId": 7, "progressStage": "正在生成评价报告"}
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record()), \
                patch.object(evaluation_service, "evaluate", return_value=outcome):
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertIn("任务进行中", result.message)
        self.assertIn("正在生成评价报告", result.message)
        self.assertIsNone(result.data[0]["evaluation"])

    def test_failed_reply_surfaces_desensitized_reason(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        outcome = {"status": "failed", "taskId": 7, "failReason": "AI 服务暂时不可用，请稍后重试"}
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record()), \
                patch.object(evaluation_service, "evaluate", return_value=outcome):
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertIn("评估未完成", result.message)
        self.assertIn("AI 服务暂时不可用", result.message)

    def test_missing_history_reply_suggests_starting_evaluation(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        outcome = {"status": "missing", "taskId": None, "evaluation": None}
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record()), \
                patch.object(evaluation_service, "evaluate", return_value=outcome):
            result = main._process_ai_chat(ChatRequest(message="查看仿生灵巧手的评估结果", exclude_owner_user_id=7))
        self.assertIn("暂无评估结果", result.message)

    def test_evaluation_error_becomes_user_safe_clarification(self):
        route = self.evaluate_route(target_name="仿生灵巧手")
        error = evaluation_service.EvaluationError("评估发起太频繁了，请稍后再试。", code="TT_AI_42901", status_code=429)
        with patch.object(main, "classify_intent", return_value=route), \
                patch.object(evaluation_service, "resolve_target", return_value=record()), \
                patch.object(evaluation_service, "evaluate", side_effect=error):
            result = main._process_ai_chat(ChatRequest(message="评估一下仿生灵巧手", exclude_owner_user_id=7))
        self.assertEqual(result.message, "评估发起太频繁了，请稍后再试。")


if __name__ == "__main__":
    unittest.main()
