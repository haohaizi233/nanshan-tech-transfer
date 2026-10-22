"""AI 评估实时阶段回传（ai_task.progress_stage）测试。

覆盖：
- modules/ai/progress.py：set_stage 写库（仅 running 守卫）+ 异常兜底
- modules/ai/worker.py：_run_evaluation 五阶段顺序回传（1/5 直写，2/3/4 走 provider 回调）
- modules/ai/provider.py：evaluate_achievement on_stage 回调（阶段 2/3/4）+
  回调异常不影响评价主流程
- modules/ai/service.py：GET 视图返回 progressStage / progress_stage
"""
import json
from unittest.mock import MagicMock, patch

import pytest


def _ctx(cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _llm_payload() -> dict:
    return {
        "dimensions": {
            "innovation": {"score": 80, "comment": "创新明确"},
            "techMaturity": {"score": 90, "comment": "成熟度高"},
            "marketProspect": {"score": 70, "comment": "市场可期"},
            "teamStrength": {"score": 60, "comment": "团队完整"},
            "cooperation": {"score": 85, "comment": "合作灵活"},
            "riskAssessment": {"score": 75, "comment": "风险可控"},
        },
        "conclusion": "Good",
        "highlights": ["Fast"],
        "report": [{"heading": "总体评价", "content": "详细分析"}],
    }


# ══════════════════════════════════════════════════════════════
# modules/ai/progress.set_stage
# ══════════════════════════════════════════════════════════════

class TestSetStage:
    @patch("db.get_cursor")
    def test_set_stage_updates_running_only(self, mock_gc):
        from modules.ai import progress
        cur = MagicMock()
        cur.rowcount = 1
        mock_gc.return_value = _ctx(cur)
        assert progress.set_stage(7, progress.STAGE_ANALYZING) is True
        sql = cur.execute.call_args[0][0]
        params = cur.execute.call_args[0][1]
        assert "progress_stage" in sql
        assert "status = 'running'" in sql  # 终态任务不被迟到的进度写回污染
        assert "task_type = 'evaluation'" in sql
        assert params == (progress.STAGE_ANALYZING, 7)

    @patch("db.get_cursor")
    def test_set_stage_swallows_db_error(self, mock_gc):
        from modules.ai import progress
        mock_gc.side_effect = RuntimeError("db down")
        assert progress.set_stage(7, progress.STAGE_SAVING) is False  # best-effort

    @pytest.mark.parametrize("bad_id,bad_stage", [
        (0, "x"), (-1, "x"), (None, "x"), ("7", "x"), (7, ""), (7, None),
    ])
    @patch("db.get_cursor")
    def test_set_stage_rejects_invalid_input(self, mock_gc, bad_id, bad_stage):
        from modules.ai import progress
        assert progress.set_stage(bad_id, bad_stage) is False
        mock_gc.assert_not_called()

    def test_stage_texts_fit_column(self):
        from modules.ai import progress
        # VARCHAR(64)：文案不被截断
        assert all(0 < len(s) <= 64 for s in progress.STAGES)
        assert len(progress.STAGES) == 5


# ══════════════════════════════════════════════════════════════
# modules/ai/worker._run_evaluation：五阶段顺序
# ══════════════════════════════════════════════════════════════

_TASK = {"id": 7, "task_type": "evaluation", "target_id": 3,
         "input_snapshot": '{"id": 3}', "version": 1}


class TestRunEvaluationStages:
    def _run(self, mock_set_stage, mock_eval):
        from modules.ai import worker
        mock_eval.return_value = {
            "legacyScores": {"techFeature": 80.0, "applyScope": 70.0,
                             "maturity": 90.0, "cooperation": 85.0},
            "totalScore": 77.2, "conclusion": "Good",
            "highlights": ["Fast"], "dimensions": [], "report": [],
            "rating": "good",
        }
        with patch("modules.ai.worker.transaction") as mock_tx:
            cur = MagicMock()
            cur.rowcount = 1
            mock_tx.return_value = _ctx(cur)
            worker._run_evaluation(_TASK, timeout=55)

    @patch("modules.ai.worker.progress.set_stage")
    @patch("modules.ai.worker.provider.evaluate_achievement")
    def test_run_evaluation_reports_all_five_stages(self, mock_eval, mock_set):
        from modules.ai import progress
        recorded = []
        mock_set.side_effect = lambda task_id, stage: recorded.append((task_id, stage))

        def fake_eval(snapshot, timeout=None, on_stage=None, on_delta=None):
            # 阶段2/3/4 由 provider 在真实执行中回调；这里模拟回调
            for stage in (progress.STAGE_ANALYZING, progress.STAGE_REPORT,
                          progress.STAGE_SCORING):
                on_stage(stage)
            return mock_eval.return_value

        mock_eval.side_effect = fake_eval
        self._run(mock_set, mock_eval)

        assert [stage for _, stage in recorded] == [
            progress.STAGE_READING,     # 阶段1：快照加载
            progress.STAGE_ANALYZING,   # 阶段2：LLM 调用
            progress.STAGE_REPORT,      # 阶段3：解析输出
            progress.STAGE_SCORING,     # 阶段4：评分换算
            progress.STAGE_SAVING,      # 阶段5：写库
        ]
        assert all(task_id == 7 for task_id, _ in recorded)
        # 阶段5 在落库事务之前
        assert mock_set.call_args_list[-1][0] == (7, progress.STAGE_SAVING)

    @patch("modules.ai.worker.progress.set_stage")
    @patch("modules.ai.worker.provider.evaluate_achievement")
    def test_run_evaluation_passes_on_stage_callback(self, mock_eval, mock_set):
        from modules.ai import progress
        self._run(mock_set, mock_eval)
        kwargs = mock_eval.call_args[1]
        assert callable(kwargs.get("on_stage"))
        # 回调写回同一任务
        kwargs["on_stage"](progress.STAGE_ANALYZING)
        assert mock_set.call_args[0] == (7, progress.STAGE_ANALYZING)

    @patch("modules.ai.worker.progress.set_stage")
    @patch("modules.ai.worker.provider.evaluate_achievement")
    def test_stage_failure_does_not_break_evaluation(self, mock_eval, mock_set):
        from modules.ai import progress
        mock_set.side_effect = RuntimeError("progress write failed")
        self._run(mock_set, mock_eval)  # 不抛异常即通过
        mock_eval.assert_called_once()


# ══════════════════════════════════════════════════════════════
# modules/ai/provider.evaluate_achievement：on_stage 回调
# ══════════════════════════════════════════════════════════════

class TestProviderStages:
    @patch("modules.ai.provider._chat_stream")
    def test_on_stage_called_in_order(self, mock_stream):
        from modules.ai import progress
        from modules.ai.provider import evaluate_achievement
        mock_stream.return_value = json.dumps(_llm_payload(), ensure_ascii=False)
        stages = []
        result = evaluate_achievement(
            {"id": 1}, timeout=5, on_stage=stages.append,
        )
        assert stages == [
            progress.STAGE_ANALYZING,  # LLM 调用前
            progress.STAGE_REPORT,     # 解析 LLM 输出
            progress.STAGE_SCORING,    # evaluation 评分换算
        ]
        assert result["totalScore"] > 0

    @patch("modules.ai.provider._chat_stream")
    def test_on_stage_optional_and_error_tolerant(self, mock_stream):
        from modules.ai.provider import evaluate_achievement
        mock_stream.return_value = json.dumps(_llm_payload(), ensure_ascii=False)
        # 不传 on_stage：正常完成
        assert evaluate_achievement({"id": 1})["totalScore"] > 0

        def boom(_stage):
            raise RuntimeError("callback crashed")

        # 回调抛异常：不影响评价主流程
        assert evaluate_achievement({"id": 1}, on_stage=boom)["totalScore"] > 0

    @patch("modules.ai.provider._chat_stream")
    def test_stage_report_emitted_before_normalize_error(self, mock_stream):
        from modules.ai import progress
        from modules.ai.provider import evaluate_achievement, AiProviderError
        mock_stream.return_value = json.dumps({"not_scores": 1})
        stages = []
        with pytest.raises(AiProviderError):
            evaluate_achievement({"id": 1}, on_stage=stages.append)
        # 至少回传到「正在生成评价报告」（解析失败也已告知用户进行到哪一步）
        assert progress.STAGE_ANALYZING in stages
        assert progress.STAGE_REPORT in stages


# ══════════════════════════════════════════════════════════════
# modules/ai/service.get_evaluation_task：进度字段回传
# ══════════════════════════════════════════════════════════════

class TestServiceProgressView:
    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_running_task_returns_progress_stage(self, mock_gc, mock_exec):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 9, "task_type": "evaluation", "status": "running",
            "created_by_user_id": 1, "target_id": 3,
            "input_data_version": "abc", "model_version_id": None,
            "fail_reason": None,
            "progress_stage": "AI正在分析技术内容",
            "created_at": None, "started_at": None, "finished_at": None,
            "stale": False,
        }
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        from modules.ai.service import get_evaluation_task
        view = get_evaluation_task(1, 9)
        assert view["status"] == "running"
        assert view["progressStage"] == "AI正在分析技术内容"
        assert view["progress_stage"] == "AI正在分析技术内容"  # 下划线别名

    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_missing_progress_stage_returns_none(self, mock_gc, mock_exec):
        cur = MagicMock()
        cur.fetchone.return_value = {
            "id": 9, "task_type": "evaluation", "status": "queued",
            "created_by_user_id": 1, "target_id": 3,
            "input_data_version": "abc", "model_version_id": None,
            "fail_reason": None, "progress_stage": None,
            "created_at": None, "started_at": None, "finished_at": None,
            "stale": False,
        }
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        from modules.ai.service import get_evaluation_task
        view = get_evaluation_task(1, 9)
        assert view["progressStage"] is None
        assert view["progress_stage"] is None

    @patch("modules.ai.service.get_cursor")
    def test_task_view_carries_progress_stage(self, mock_gc):
        cur = MagicMock()
        cur.fetchone.return_value = {"id": 11, "status": "running",
                                     "progress_stage": "正在计算综合评分"}
        mock_gc.return_value = _ctx(cur)
        from modules.ai.service import _task_view
        view = _task_view(11)
        assert view["progressStage"] == "正在计算综合评分"
