"""Email Security Gateway 内部诊断、20 项失败原因码与 CLI 安全门禁测试。"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from modules.security.email_diagnostics import (
    FAILURE_EXPLANATIONS,
    email_cleanup_expired,
    email_config_check,
    email_explain_failure,
    email_inspect_delivery,
    email_provider_check,
    email_redis_check,
    email_risk_snapshot,
)


def test_all_twenty_failure_explanations_and_aliases():
    assert len(FAILURE_EXPLANATIONS) == 20
    for code in list(FAILURE_EXPLANATIONS):
        info = email_explain_failure(code)
        assert info["known"] is True
        assert info["category"]
        assert info["summary"]
        assert info["recommended_action"]

    alias_info = email_explain_failure("EMAIL_COOLDOWN")
    assert alias_info["known"] is True
    assert alias_info["mapped_to"] == "RISK_BLOCKED"

    unknown_info = email_explain_failure("NON_EXISTENT_CODE")
    assert unknown_info["known"] is False


def test_email_provider_check_never_opens_real_network():
    # 将 socket 阻塞验证离线自检完全无真实网络外呼
    with patch("smtplib.SMTP", side_effect=AssertionError("Must never open real plain SMTP")):
        res = email_provider_check()
    assert res["real_send_attempted"] is False
    assert res["scope"] == "offline_contract_check_not_live_delivery"
    assert res["smtp_contract_ok"] is True
    assert res["ses_contract_ok"] is True


def test_email_config_redis_queue_and_inspection_redact_secrets():
    mock_cur = MagicMock()
    mock_cur.fetchall.side_effect = [
        [("auth_challenge", "send_state"), ("step_up_grant", "grant_hash")],
    ]
    with (
        patch("modules.security.email_diagnostics.email_redis_check", return_value={"connected": False}),
        patch("modules.security.email_diagnostics.get_cursor") as mock_gc,
    ):
        mock_gc.return_value.__enter__.return_value = mock_cur
        cfg = email_config_check()
    serialized = json.dumps(cfg, ensure_ascii=False)
    assert "SMTP_PASSWORD" not in cfg["settings"]
    assert "TENCENT_SES_SECRET_KEY" not in cfg["settings"]
    assert cfg["scope"] == "read_only_config_and_dependency_check"
    assert isinstance(cfg["configured"]["SMTP_PASSWORD"], bool)
    assert "postgres123" not in serialized

    # Redis check uses mock client without mutating counters
    fake_redis = MagicMock()
    fake_redis.ping.return_value = True
    fake_redis.eval.return_value = 1
    fake_redis.time.return_value = (1764000000, 0)
    with patch("modules.security.email_diagnostics._redis_client", return_value=fake_redis):
        r_chk = email_redis_check()
    assert r_chk["connected"] is True
    assert r_chk["lua"] is True

    fake_redis.zcount.return_value = 2
    fake_redis.ttl.return_value = 50
    fake_redis.get.return_value = "4"
    with patch("modules.security.email_diagnostics._redis_client", return_value=fake_redis):
        snap = email_risk_snapshot(account="alice", email="alice@example.com", ip="1.2.3.4", device_id="d1")
    assert snap["request_counters_mutated"] is False
    assert snap["redis_available"] is True
    assert "alice@example.com" not in json.dumps(snap)

    # Delivery / Challenge inspection
    with patch("modules.security.email_diagnostics.get_cursor") as mock_gc:
        insp_cur = MagicMock()
        insp_cur.fetchall.return_value = [
            {
                "id": "00000000-0000-0000-0000-000000000111",
                "request_id": "req-insp-1",
                "state": "processing",
                "outcome": None,
                "failure_stage": None,
                "failure_reason": None,
                "provider_status": None,
                "risk_rule_id": None,
                "provider_ids": ["<mid@example.com>"],
                "outcome_unknown": False,
                "retryable": False,
                "provider_called": True,
                "elapsed_ms": 20,
                "stale_processing": True,
                "channel": "email_otp",
                "purpose": "password_recovery",
                "challenge_status": "pending",
                "send_state": "unknown",
                "delivery_status_code": None,
                "delivery_reason_code": None,
            }
        ]
        mock_gc.return_value.__enter__.return_value = insp_cur
        deliv = email_inspect_delivery(challenge_id="00000000-0000-0000-0000-000000000111")
    assert deliv["tasks"][0]["stale_processing"] is True
    assert deliv["tasks"][0]["failure_reason"] == "PROVIDER_OUTCOME_UNKNOWN"
    assert "<mid@example.com>" not in json.dumps(deliv)

    with patch("modules.security.email_diagnostics.get_cursor") as mock_gc:
        c_cur = MagicMock()
        c_cur.fetchone.side_effect = [{"count": 1}, {"count": 2}, {"count": 3}, {"count": 4}]
        mock_gc.return_value.__enter__.return_value = c_cur
        dry = email_cleanup_expired(dry_run=True)
    assert dry == {
        "dry_run": True,
        "expired_challenges": 1,
        "expired_recovery_grants": 2,
        "expired_step_up_grants": 4,
        "expired_queue_rows_7d": 3,
    }


def test_email_gateway_ops_cli_subcommands_and_live_test_gate():
    tool_path = str(Path(__file__).resolve().parents[1] / "tools" / "email_gateway_ops.py")
    p_check = subprocess.run(
        [sys.executable, tool_path, "check-provider"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_check.returncode == 0
    out_check = json.loads(p_check.stdout)
    assert out_check["real_send_attempted"] is False
    assert out_check["smtp_contract_ok"] is True

    p_explain = subprocess.run(
        [sys.executable, tool_path, "explain-failure", "--code", "PROVIDER_OUTCOME_UNKNOWN"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_explain.returncode == 0
    assert json.loads(p_explain.stdout)["known"] is True

    # live-test 缺少双重开关与匹配目标必须被强制拒绝
    p_live = subprocess.run(
        [sys.executable, tool_path, "live-test", "--account", "u1", "--email", "a@example.com"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert p_live.returncode != 0
