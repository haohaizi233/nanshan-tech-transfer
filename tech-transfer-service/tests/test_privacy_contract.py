"""跨服务隐私脱敏契约测试（确保 tech-transfer-service 与 nanshan-ai-agent 规则不发生语义漂移）。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

from modules.achievement.extract import strip_private_contact_text as svc_strip
from modules.ai import chat_store
from modules.ai import provider as ai_provider

_AGENT_PRIVACY_PATH = Path(__file__).resolve().parents[2] / "nanshan-ai-agent" / "app" / "privacy.py"
_SPEC = importlib.util.spec_from_file_location("agent_privacy", _AGENT_PRIVACY_PATH)
assert _SPEC and _SPEC.loader
_AGENT_PRIVACY = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_AGENT_PRIVACY)
agent_strip = _AGENT_PRIVACY.strip_private_contact_text


_CONTRACT_VECTORS = [
    "",
    None,
    "基于深度学习的工业视觉检测技术，精度99.5%，专利 CN202310123456.7。",
    "请联系张三 13812345678 或发送邮件到 zhang@example.com。",
    "微信号：wx_demo_01，官网 https://www.nanshan.gov.cn/tech",
    "回调地址 https://auth.example.com/cb?token=secret123&code=998877&page=1",
    "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N_XgL0n3I9PlFUP0THsR8U",
    "联系电话：13900139000\n技术路线：采用多模态融合框架。",
]


@pytest.mark.parametrize("text", _CONTRACT_VECTORS)
def test_cross_service_privacy_sanitization_contract(text):
    assert svc_strip(text) == agent_strip(text)


def test_ai_evaluation_provider_sanitizes_snapshot_before_llm():
    captured_messages = []

    def fake_chat_stream(messages, **_kwargs):
        captured_messages.append(messages)
        return (
            '{"dimensions":{"innovation":{"score":80,"comment":"好"},'
            '"techMaturity":{"score":75,"comment":"好"},'
            '"marketProspect":{"score":80,"comment":"好"},'
            '"teamStrength":{"score":80,"comment":"好"},'
            '"cooperation":{"score":75,"comment":"好"},'
            '"riskAssessment":{"score":75,"comment":"好"}},'
            '"conclusion":"良好","highlights":["亮点1"],"report":[{"heading":"总评","content":"分析内容"}]}'
        )

    snapshot = {
        "id": 1,
        "title": "视觉检测 13800138000",
        "tech_intro": "技术简介，联系 dev@lab.cn，微信号：wx_dev99，链接 https://x.cn?token=abc",
        "source_org_name": "南山实验室",
    }
    with patch.object(ai_provider, "_chat_stream", side_effect=fake_chat_stream):
        ai_provider.evaluate_achievement(snapshot)

    assert len(captured_messages) == 1
    user_payload = captured_messages[0][1]["content"]
    assert "13800138000" not in user_payload
    assert "dev@lab.cn" not in user_payload
    assert "wx_dev99" not in user_payload
    assert "token=abc" not in user_payload


def test_chat_store_sanitizes_legacy_cards_on_read():
    legacy_card = {
        "id": 1,
        "title": "成果A",
        "description": "联系 13811112222 或 a@b.com",
        "advisorSummary": "微信号：wx_old99",
        "matchReason": ["原文：13900001111"],
    }
    sanitized = chat_store._sanitize_cards([legacy_card])[0]
    assert "13811112222" not in sanitized["description"]
    assert "a@b.com" not in sanitized["description"]
    assert "wx_old99" not in sanitized["advisorSummary"]
    assert "13900001111" not in sanitized["matchReason"][0]
