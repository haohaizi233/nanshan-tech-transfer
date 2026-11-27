"""P3-10 业务事件与运营指标测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from modules.analytics import service as analytics_service


def test_product_event_rejects_unknown_and_scrubs_pii():
    assert analytics_service.record_product_event("unknown_event") is False

    fake_cur = MagicMock()
    ok = analytics_service.record_product_event(
        "ai_match_requested",
        actor_user_id=42,
        target_type="achievement",
        target_id=101,
        metadata={
            "source": "miniapp",
            "phone": "13800138000",
            "access_token": "jwt_secret",
            "otp": "123456",
            "prompt": "full raw prompt",
            "resultCount": 3,
        },
        cur=fake_cur,
    )
    assert ok is True
    assert fake_cur.execute.called
    sql_arg, params_arg = fake_cur.execute.call_args[0]
    assert "product_event" in sql_arg
    dumped = str(params_arg[-1].adapted)
    assert "13800138000" not in dumped
    assert "jwt_secret" not in dumped
    assert "123456" not in dumped
    assert "full raw prompt" not in dumped
    assert "miniapp" in dumped
    assert "resultCount" in dumped


def test_operational_metrics_explicit_denominators():
    fake_cur = MagicMock()
    fake_cur.fetchall.return_value = [
        {"event_name": "ai_match_requested", "cnt": 20},
        {"event_name": "ai_result_clicked", "cnt": 5},
    ]
    fake_cur.fetchone.side_effect = [
        {"cnt": 12},
        {"cnt": 50},
        {"cnt": 18},
        {"total_reqs": 10, "accepted_cnt": 6, "completed_cnt": 3, "avg_hours": 14.5},
    ]

    class _Ctx:
        def __enter__(self):
            return fake_cur

        def __exit__(self, *_args):
            return False

    with patch("modules.analytics.service.get_cursor", return_value=_Ctx()):
        metrics = analytics_service.get_operational_metrics(days=30)

    assert metrics["windowDays"] == 30
    assert metrics["activeUsers"] == 12
    assert metrics["publishedAchievements"] == 50
    assert metrics["publishedDemands"] == 18
    assert metrics["aiCtr"] == 0.25
    assert metrics["cooperationAcceptRate"] == 0.6
    assert metrics["cooperationCompleteRate"] == 0.3
    assert metrics["avgCooperationHours"] == 14.5
    assert "aiCtr" in metrics["definitions"]
