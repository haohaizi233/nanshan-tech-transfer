"""Phase R (R09): 邮件投递状态异步对账与腾讯 Cloud SES 官方 DeliverStatus (0/1/2/3/8) 及配置指纹匹配测试。"""

from __future__ import annotations

from contextlib import ExitStack
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

from modules.security.delivery_models import ProviderError
from modules.security.email_gateway import reconcile_email_delivery
from modules.security.email_providers import SmtpEmailProvider, TencentSesProvider


def _mock_row(
    *,
    send_state: str = "accepted",
    provider_name: str | None = "tencent",
    provider_config_id: str | None = "cfg-match-1",
    provider_message_ids=None,
    created_at=None,
):
    return {
        "provider_message_ids": provider_message_ids if provider_message_ids is not None else ["mid-target"],
        "send_state": send_state,
        "provider_name": provider_name,
        "provider_config_id": provider_config_id,
        "created_at": created_at or datetime(2026, 11, 25, 2, 0, tzinfo=UTC),
    }


def _reconcile_with_provider(row: dict, provider, transition_outcome: str = "transitioned"):
    cur = MagicMock()
    cur.fetchone.side_effect = [row, {"status": "pending", "send_state": "delivered"}]
    cur.rowcount = 1
    with ExitStack() as stack:
        stack.enter_context(
            patch("modules.security.email_gateway.get_cursor")
        ).return_value.__enter__.return_value = cur
        stack.enter_context(patch("modules.security.email_gateway.get_email_provider", return_value=provider))
        stack.enter_context(patch("modules.security.email_gateway.audit_record"))
        stack.enter_context(patch("modules.security.email_gateway._engine"))
        res = reconcile_email_delivery("ch-reconcile-1")
    return res, cur


def test_reconcile_rejects_provider_switch_config_change_and_unavailable():
    row = _mock_row(provider_name="smtp", provider_config_id="smtp-cfg-1")
    ses_prov = TencentSesProvider("AKIDTEST1234", "secret", "noreply@example.com")

    res_switch, _ = _reconcile_with_provider(row, ses_prov)
    assert res_switch["supported"] is False
    assert res_switch["reason_code"] == "provider_configuration_changed"
    assert res_switch["requires_manual_review"] is True

    # 同 Provider 但发信配置指纹已变化（切换账号/域名/模板）-> 拒绝核对，防止错查
    ses_other = TencentSesProvider("AKIDOTHER99", "secret", "other@example.com")
    row_cfg = _mock_row(provider_name="tencent", provider_config_id=ses_prov.provider_config_id)
    assert ses_other.provider_config_id != ses_prov.provider_config_id
    res_cfg, _ = _reconcile_with_provider(row_cfg, ses_other)
    assert res_cfg["supported"] is False
    assert res_cfg["reason_code"] == "provider_configuration_changed"
    assert res_cfg["requires_manual_review"] is True

    # SMTP provider_config_id 指纹随 host/port/from_email 稳定生成
    smtp1 = SmtpEmailProvider("smtp.example.com", 465, "user", "pass", True, 10, from_email="a@example.com")
    smtp2 = SmtpEmailProvider("smtp.example.com", 465, "user", "pass", True, 10, from_email="b@example.com")
    assert smtp1.provider_config_id != smtp2.provider_config_id

    # Provider 不可用（关闭或缺失凭证）返回 provider_unavailable 而不抛未捕获异常
    cur = MagicMock()
    cur.fetchone.return_value = row_cfg
    with (
        patch("modules.security.email_gateway.get_cursor") as mock_gc,
        patch("modules.security.email_gateway.get_email_provider", side_effect=ProviderError("disabled")),
    ):
        mock_gc.return_value.__enter__.return_value = cur
        res_unavail = reconcile_email_delivery("ch-unavail")
    assert res_unavail["reason_code"] == "provider_unavailable"
    assert res_unavail["requires_manual_review"] is True


def test_ses_official_deliver_status_mapping_message_id_matching_and_no_raw_deliver_message():
    ses = TencentSesProvider("AKIDMATCH123", "secret", "noreply@example.com")
    base_row = _mock_row(provider_name="tencent", provider_config_id=ses.provider_config_id)

    # 1. 不匹配 MessageId -> 拒绝误更新
    ses.query_status = MagicMock(
        return_value={
            "accepted": True,
            "records": [{"MessageId": "unrelated-mid-999", "DeliverStatus": 1, "DeliverTime": 1000}],
        }
    )
    res_mismatch, _cur_m = _reconcile_with_provider(base_row, ses)
    assert res_mismatch["reason_code"] == "provider_message_mismatch"
    assert res_mismatch["requires_manual_review"] is True

    # 2. 官方 0 (queued) 与 8 (delayed) 绝不标为 delivered，也不落库失败原因
    for status_code, expected_reason in ((0, "ses_in_queue"), (8, "ses_delayed")):
        ses.query_status = MagicMock(
            return_value={
                "accepted": True,
                "records": [{"MessageId": "mid-target", "DeliverStatus": status_code, "DeliverTime": 100}],
            }
        )
        res_wait, _ = _reconcile_with_provider(base_row, ses)
        assert res_wait["state"] == "accepted"
        assert res_wait["reason_code"] == expected_reason

    # 3. 多条同名 MessageId 记录按最大 DeliverTime 取最新状态；DeliverMessage 中的敏感内容绝不落库
    for code, expected_state, expected_reason in (
        (1, "delivered", "ses_delivered"),
        (2, "delivery_failed", "ses_dropped"),
        (3, "bounced", "ses_esp_rejected"),
    ):
        ses.query_status = MagicMock(
            return_value={
                "accepted": True,
                "records": [
                    {"MessageId": "mid-target", "DeliverStatus": 0, "DeliverTime": 100, "DeliverMessage": "queued"},
                    {
                        "MessageId": "mid-target",
                        "DeliverStatus": code,
                        "DeliverTime": 200,
                        "DeliverMessage": "victim@qq.com mailbox rejected with PII",
                    },
                ],
            }
        )
        res_done, cur_done = _reconcile_with_provider(base_row, ses)
        assert res_done["reason_code"] == expected_reason
        sql_blob = " ".join(str(c.args) for c in cur_done.execute.call_args_list)
        assert "victim@qq.com" not in sql_blob

    # 4. 未知 DeliverStatus 保留原状态并标记 requires_manual_review
    ses.query_status = MagicMock(
        return_value={"accepted": True, "records": [{"MessageId": "mid-target", "DeliverStatus": 99}]}
    )
    res_unk, _ = _reconcile_with_provider(base_row, ses)
    assert res_unk["reason_code"] == "unknown_provider_status"
    assert res_unk["requires_manual_review"] is True


def test_ses_query_status_defaults_to_shanghai_date_and_supports_offset():
    ses = TencentSesProvider("AKIDDATE1234", "secret", "noreply@example.com")
    captured = {}

    def _fake_tc3(action, payload):
        captured["action"] = action
        captured["payload"] = payload
        return {"Response": {"RequestId": "rq-1", "EmailStatusList": []}}

    ses._tc3_request = _fake_tc3
    shanghai_today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
    ses.query_status(["mid-abc"], offset=200)
    assert captured["action"] == "GetSendEmailStatus"
    assert captured["payload"]["RequestDate"] == shanghai_today
    assert captured["payload"]["Offset"] == 200
    assert captured["payload"]["MessageId"] == "mid-abc"
