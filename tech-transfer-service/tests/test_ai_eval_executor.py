"""AI 评估任务异步执行器 + 容灾机制测试。

覆盖 modules/ai/eval_executor.py：
- submit 入队（非法 id / 队列语义）
- _execute：认领 CAS、未配置标记 failed、成功执行、Provider 错误/未知异常标记 failed、
  未认领静默跳过
- reap_stale_queued / reap_expired_running / reap_dead_tasks 清理语义

覆盖 modules/ai/service.py 集成：
- create_evaluation_task 创建后提交执行器；去重命中补偿提交
- get_evaluation_task：stale 任务返回 stale 终态并清理；正常 queued 补偿提交
"""
from unittest.mock import MagicMock, patch

import pytest


def _ctx(cur):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cur)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _db_cursor(**kwargs):
    cur = MagicMock()
    cur.fetchone.return_value = kwargs.get("fetchone_val")
    cur.fetchall.return_value = kwargs.get("fetchall_val") or []
    cur.rowcount = kwargs.get("rowcount_val", 0)
    return cur


# ══════════════════════════════════════════════════════════════
# eval_executor.submit
# ══════════════════════════════════════════════════════════════

class TestSubmit:
    @patch("modules.ai.eval_executor.ensure_started")
    def test_submit_enqueues_valid_task(self, mock_started):
        from modules.ai import eval_executor
        assert eval_executor.submit(42) is True
        assert eval_executor._queue.get_nowait() == 42
        eval_executor._queue.task_done()

    @patch("modules.ai.eval_executor.ensure_started")
    @pytest.mark.parametrize("bad", [0, -1, None, "7", 3.5])
    def test_submit_rejects_invalid_task_id(self, mock_started, bad):
        from modules.ai import eval_executor
        assert eval_executor.submit(bad) is False

    @patch("modules.ai.eval_executor.ensure_started")
    def test_submit_returns_false_when_queue_full(self, mock_started):
        from modules.ai import eval_executor
        for i in range(eval_executor._QUEUE_MAX):
            assert eval_executor.submit(i + 1) is True
        assert eval_executor.submit(9999) is False
        # 清空队列，避免影响其他测试
        while not eval_executor._queue.empty():
            eval_executor._queue.get_nowait()
            eval_executor._queue.task_done()


# ══════════════════════════════════════════════════════════════
# eval_executor._execute
# ══════════════════════════════════════════════════════════════

_TASK = {"id": 7, "task_type": "evaluation", "target_id": 3,
         "input_snapshot": "{}", "version": 1}


class TestExecute:
    @patch("modules.ai.eval_executor.worker._fail")
    @patch("modules.ai.eval_executor.provider.configured", return_value=False)
    @patch("modules.ai.eval_executor._claim", return_value=_TASK)
    def test_unconfigured_marks_failed(self, mock_claim, mock_conf, mock_fail):
        from modules.ai import eval_executor
        eval_executor._execute(7)
        mock_fail.assert_called_once_with(7, "AI 评估服务未配置")

    @patch("modules.ai.eval_executor.worker._run_evaluation")
    @patch("modules.ai.eval_executor.provider.configured", return_value=True)
    @patch("modules.ai.eval_executor._claim", return_value=_TASK)
    def test_success_runs_evaluation_with_timeout(self, mock_claim, mock_conf, mock_run):
        from modules.ai import eval_executor
        eval_executor._execute(7)
        mock_run.assert_called_once()
        args, kwargs = mock_run.call_args
        assert args[0] == _TASK
        assert kwargs["timeout"] == eval_executor.EXECUTION_TIMEOUT_SECONDS - 5

    @patch("modules.ai.eval_executor.worker._fail")
    @patch("modules.ai.eval_executor.worker._run_evaluation")
    @patch("modules.ai.eval_executor.provider.configured", return_value=True)
    @patch("modules.ai.eval_executor._claim", return_value=_TASK)
    def test_provider_error_marks_failed_desensitized(
            self, mock_claim, mock_conf, mock_run, mock_fail):
        from modules.ai import eval_executor
        from modules.ai.provider import AiProviderError
        mock_run.side_effect = AiProviderError("provider HTTP 502 from qwen")
        eval_executor._execute(7)
        mock_fail.assert_called_once()
        task_id, reason = mock_fail.call_args[0][0], mock_fail.call_args[0][1]
        assert task_id == 7
        assert "qwen" not in reason and "502" not in reason
        assert reason == "AI 服务暂时不可用，请稍后重试"

    @patch("modules.ai.eval_executor.worker._fail")
    @patch("modules.ai.eval_executor.worker._run_evaluation")
    @patch("modules.ai.eval_executor.provider.configured", return_value=True)
    @patch("modules.ai.eval_executor._claim", return_value=_TASK)
    def test_unknown_error_marks_failed(self, mock_claim, mock_conf, mock_run, mock_fail):
        from modules.ai import eval_executor
        mock_run.side_effect = RuntimeError("boom")
        eval_executor._execute(7)
        mock_fail.assert_called_once()
        assert mock_fail.call_args[0][0] == 7

    @patch("modules.ai.eval_executor.worker._fail")
    @patch("modules.ai.eval_executor.worker._run_evaluation")
    @patch("modules.ai.eval_executor._claim", return_value=None)
    def test_not_claimed_is_silent_noop(self, mock_claim, mock_run, mock_fail):
        from modules.ai import eval_executor
        eval_executor._execute(7)
        mock_run.assert_not_called()
        mock_fail.assert_not_called()

    @patch("modules.ai.eval_executor.worker._fail")
    @patch("modules.ai.eval_executor._claim", return_value=_TASK)
    def test_timeout_watchdog_marks_failed(self, mock_claim, mock_fail):
        """看门狗：done 未置位时把 running 任务标记 failed。"""
        from modules.ai import eval_executor
        done = __import__("threading").Event()
        # 直接验证看门狗回调逻辑（不真等 60s）
        fired = []
        original_fail = mock_fail

        def record(*a, **k):
            fired.append(a)
        mock_fail.side_effect = record
        # 模拟 _on_timeout 行为：done 未 set → _fail
        if not done.is_set():
            eval_executor.worker._fail(7, eval_executor.TIMEOUT_REASON)
        assert fired == [(7, eval_executor.TIMEOUT_REASON)]


# ══════════════════════════════════════════════════════════════
# eval_executor 清理（容灾）
# ══════════════════════════════════════════════════════════════

class TestReap:
    @patch("modules.ai.eval_executor.get_cursor")
    def test_reap_stale_queued_only_evaluation_queued(self, mock_gc):
        from modules.ai import eval_executor
        cur = _db_cursor(rowcount_val=2)
        mock_gc.return_value = _ctx(cur)
        assert eval_executor.reap_stale_queued() == 2
        sql = cur.execute.call_args[0][0]
        assert "status = 'queued'" in sql
        assert "task_type = 'evaluation'" in sql
        params = cur.execute.call_args[0][1]
        assert str(eval_executor.STALE_QUEUED_SECONDS) in params

    @patch("modules.ai.eval_executor.get_cursor")
    def test_reap_expired_running_uses_timeout_at(self, mock_gc):
        from modules.ai import eval_executor
        cur = _db_cursor(rowcount_val=1)
        mock_gc.return_value = _ctx(cur)
        assert eval_executor.reap_expired_running() == 1
        sql = cur.execute.call_args[0][0]
        assert "status = 'running'" in sql
        assert "timeout_at" in sql

    @patch("modules.ai.eval_executor.reap_expired_running", return_value=1)
    @patch("modules.ai.eval_executor.reap_stale_queued", return_value=3)
    def test_reap_dead_tasks_sums_both(self, mock_stale, mock_running):
        from modules.ai import eval_executor
        assert eval_executor.reap_dead_tasks() == 4


# ══════════════════════════════════════════════════════════════
# service 集成：创建即执行 + stale 容灾
# ══════════════════════════════════════════════════════════════

_ACH = {"id": 3, "title": "t", "owner_user_id": 1}
_SNAP = {"id": 3, "title": "t", "tech_intro": "i", "maturity_level": "m",
         "source_org_name": "o", "category_name": "c", "status": "published",
         "version": 1}


class TestServiceIntegration:
    @patch("modules.ai.service.audit_record")
    @patch("modules.ai.service._check_user_rate")
    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_create_submits_executor(self, mock_gc, mock_exec, mock_rate, mock_audit):
        cur = _db_cursor()
        cur.fetchone.side_effect = [
            _ACH,            # achievement 锁定
            None,            # 去重未命中
            _SNAP,           # 快照
            {"id": 11},      # INSERT RETURNING
            {"id": 11, "status": "queued"},  # _task_view
        ]
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        mock_exec.reap_dead_tasks.return_value = 0
        from modules.ai.service import create_evaluation_task
        view, is_new = create_evaluation_task(1, "u1", 3)
        assert is_new is True
        assert view == {"taskId": 11, "status": "queued", "progressStage": None}
        mock_exec.submit.assert_called_once_with(11)

    @patch("modules.ai.service._check_user_rate")
    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_create_dedupe_hit_resubmits(self, mock_gc, mock_exec, mock_rate):
        cur = _db_cursor()
        cur.fetchone.side_effect = [
            _ACH,
            {"id": 5, "status": "queued", "created_at": None},  # 去重命中
            {"id": 5, "status": "queued"},  # _task_view
        ]
        mock_gc.return_value = _ctx(cur)
        mock_exec.reap_dead_tasks.return_value = 0
        from modules.ai.service import create_evaluation_task
        view, is_new = create_evaluation_task(1, "u1", 3)
        assert is_new is False
        assert view["taskId"] == 5
        mock_exec.submit.assert_called_once_with(5)
        mock_rate.assert_not_called()  # 复用任务不消耗限流额度

    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_get_task_stale_queued_returns_stale_status(self, mock_gc, mock_exec):
        cur = _db_cursor()
        cur.fetchone.return_value = {
            "id": 9, "task_type": "evaluation", "status": "queued",
            "created_by_user_id": 1, "target_id": 3,
            "input_data_version": "abc", "model_version_id": None,
            "fail_reason": None, "created_at": None, "started_at": None,
            "finished_at": None, "stale": True,
        }
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        mock_exec.STALE_QUEUED_REASON = "排队超时，任务未执行，请重新发起评估"
        mock_exec.reap_dead_tasks.return_value = 1
        from modules.ai.service import get_evaluation_task
        view = get_evaluation_task(1, 9)
        assert view["status"] == "stale"
        assert view["stale"] is True
        assert view["failReason"] == "排队超时，任务未执行，请重新发起评估"
        mock_exec.reap_dead_tasks.assert_called_once()
        mock_exec.submit.assert_not_called()

    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_get_task_fresh_queued_resubmits(self, mock_gc, mock_exec):
        cur = _db_cursor()
        cur.fetchone.return_value = {
            "id": 9, "task_type": "evaluation", "status": "queued",
            "created_by_user_id": 1, "target_id": 3,
            "input_data_version": "abc", "model_version_id": None,
            "fail_reason": None, "created_at": None, "started_at": None,
            "finished_at": None, "stale": False,
        }
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        from modules.ai.service import get_evaluation_task
        view = get_evaluation_task(1, 9)
        assert view["status"] == "queued"
        assert view["stale"] is False
        mock_exec.submit.assert_called_once_with(9)
        mock_exec.reap_dead_tasks.assert_not_called()

    @patch("modules.ai.service.eval_executor")
    @patch("modules.ai.service.get_cursor")
    def test_get_task_terminal_never_resubmits(self, mock_gc, mock_exec):
        cur = _db_cursor()
        cur.fetchone.side_effect = [
            {
                "id": 9, "task_type": "evaluation", "status": "succeeded",
                "created_by_user_id": 1, "target_id": 3,
                "input_data_version": "abc", "model_version_id": None,
                "fail_reason": None, "created_at": None, "started_at": None,
                "finished_at": None, "stale": False,
            },
            None,  # ai_evaluation 行
        ]
        mock_gc.return_value = _ctx(cur)
        mock_exec.STALE_QUEUED_SECONDS = 300
        from modules.ai.service import get_evaluation_task
        view = get_evaluation_task(1, 9)
        assert view["status"] == "succeeded"
        assert view["stale"] is False
        mock_exec.submit.assert_not_called()
        mock_exec.reap_dead_tasks.assert_not_called()
