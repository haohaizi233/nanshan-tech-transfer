"""P3-1 全链路 AI 数据隐私治理验收测试（PRIV-01 ~ PRIV-15）。"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from app import main as agent_main
from app.advisor import grounded_explanation
from app.formatters import format_achievement_card, format_demand_card
from app.privacy import DataClassification, sanitize_history_messages, strip_private_contact_text
from app.reranker import rerank_results
from app.schemas import ChatRequest, RouteResult


def _sample_achievement(**overrides):
    base = {
        "id": 101,
        "owner_user_id": 10,
        "status": "published",
        "deleted_at": None,
        "title": "高精度机器视觉检测系统",
        "source_org_name": "南山智能制造研究院",
        "tech_intro": "基于深度学习的工业缺陷检测系统，精度99.5%，专利号 CN202310123456.7。",
        "pricing_mode": "range",
        "price_min_wan": 50,
        "price_max_wan": 120,
        "maturity_level": "04_pilot_done",
        "application_fields": ["智能制造", "工业质检"],
        "innovation_points": ["亚像素级缺陷识别"],
        "contact_name": "张三",
        "contact_phone": "13800138000",
        "contact_email": "zhangsan@example.com",
        "view_count": 12,
        "created_at": "2026-10-01T00:00:00",
    }
    base.update(overrides)
    return base


def test_data_classification_levels_exist():
    expected = {"PUBLIC", "AUTHENTICATED", "OWNER_ONLY", "COOPERATION_AUTHORIZED", "ADMIN_ONLY", "SECRET"}
    assert {c.value for c in DataClassification} == expected


def test_priv_01_02_03_04_text_strips_phone_email_wechat_inventor_contact():
    # PRIV-01: 手机号；PRIV-02: 邮箱；PRIV-03: 微信号；PRIV-04: 发明人简介含联系方式
    raw = (
        "发明人张教授长期从事机器视觉研究。\n"
        "联系电话：13812345678\n"
        "如有合作意向请联系 139-1234-5678 或发邮件至 prof.zhang@lab.edu.cn。\n"
        "微信号：wx_zhang2026\n"
        "核心指标：准确率 99.2%，功率 15W。"
    )
    cleaned = strip_private_contact_text(raw)
    assert cleaned is not None
    assert "13812345678" not in cleaned
    assert "139-1234-5678" not in cleaned
    assert "prof.zhang@lab.edu.cn" not in cleaned
    assert "wx_zhang2026" not in cleaned
    assert "发明人张教授长期从事机器视觉研究" in cleaned
    assert "准确率 99.2%，功率 15W" in cleaned


def test_priv_05_06_07_llm_payload_and_card_and_evidence_have_no_raw_contact():
    # PRIV-05: 推荐原文包含敏感信息；PRIV-06: Mock LLM 捕获实际输入 Payload；PRIV-07: AI 卡片不包含明文联系方式
    candidates = [
        _sample_achievement(
            id=101 + i,
            tech_intro=f"机器视觉检测方案{i}，详情联系 1380013800{i} 或 test{i}@secret.com，微信号：wx_secret_{i}。",
            innovation_points=[f"创新点{i}（联系 1370013700{i}）"],
        )
        for i in range(4)
    ]
    captured_payloads = []

    def fake_chat_completion(messages, **_kwargs):
        captured_payloads.append(messages)
        return json.dumps(
            {
                "results": [
                    {
                        "id": 101,
                        "evidence": [{"field": "tech_intro", "quote": "详情联系 13800138000"}],
                        "analysis": "请联系 test0@secret.com 获取更多资料",
                    }
                ]
            },
            ensure_ascii=False,
        )

    with patch("app.reranker.chat_completion", side_effect=fake_chat_completion):
        ranked = rerank_results(
            intent="search_achievement",
            user_message="推荐机器视觉成果，我的手机是 13612345678",
            candidates=candidates,
            top_n=3,
        )

    assert len(captured_payloads) == 1
    dumped_llm_input = json.dumps(captured_payloads[0], ensure_ascii=False)
    assert "13800138000" not in dumped_llm_input
    assert "test0@secret.com" not in dumped_llm_input
    assert "wx_secret_0" not in dumped_llm_input
    assert "13700137000" not in dumped_llm_input
    assert "13612345678" not in dumped_llm_input

    card = format_achievement_card(candidates[0])
    card_json = json.dumps(card, ensure_ascii=False)
    assert "13800138000" not in card_json
    assert "zhangsan@example.com" not in card_json
    assert "wx_secret_0" not in card_json
    assert card["contact"]["phone"] == "138****8000"
    assert card["contact"]["email"] == "z***@example.com"

    # PRIV-05: 推荐依据不允许重新引入敏感信息
    ev, insight = grounded_explanation(
        {"evidence": [{"field": "tech_intro", "quote": "详情联系 13800138000"}], "analysis": "请联系 test0@secret.com"},
        candidates[0],
    )
    assert ev == []
    assert "test0@secret.com" not in insight


def test_priv_08_09_10_visibility_and_revocation_recheck():
    # PRIV-08: 用户无权限访问私有成果；PRIV-09: 重排过程中被下架；PRIV-10: 对话历史引用已撤销资源
    draft_item = _sample_achievement(id=201, owner_user_id=99, status="draft")
    deleted_item = _sample_achievement(id=202, owner_user_id=99, deleted_at="2026-11-01T00:00:00")
    published_item = _sample_achievement(id=203, owner_user_id=99, status="published")

    # 伪造非所有者 user_id=88 不能引用他人草稿
    with patch("app.main.get_visible_records", return_value=[]), patch(
        "app.main.evaluation_service.resolve_target", return_value=None
    ):
        refs = agent_main.get_reference_records("achievement", [201, 202], user_id=88)
    assert refs == []

    # PRIV-09: 重排结果中 203 在二次校验时已下架（status=offline），不得进入最终返回
    route = RouteResult(intent="search_achievement", keywords=["机器视觉"], limit=5)
    req = ChatRequest(message="机器视觉", exclude_owner_user_id=1)
    with patch("app.main.get_visible_records", return_value=[{**published_item, "status": "offline"}]):
        final = agent_main._final_records([published_item], req, route)
    assert final == []

    # PRIV-10: 对话历史引用已删除成果应被拒绝
    assert agent_main._reference_visible(deleted_item, "achievement", 99) is False
    assert agent_main._reference_visible(draft_item, "achievement", 88) is False


def test_priv_11_12_13_urls_specs_and_history():
    # PRIV-11: 敏感链接参数被剥离；PRIV-12: 合法技术参数不被误删；PRIV-13: 正常官网链接保留
    raw = (
        "重置链接 https://example.com/reset?token=sec_12345&page=2 "
        "官网 https://www.nanshan-tech.cn/labs "
        "参数：激光功率 500W，精度 ±0.01mm，专利号 CN202310123456.7，报价 80-120 万元。"
    )
    cleaned = strip_private_contact_text(raw)
    assert cleaned is not None
    assert "sec_12345" not in cleaned
    assert "https://example.com/reset?page=2" in cleaned
    assert "https://www.nanshan-tech.cn/labs" in cleaned
    assert "500W" in cleaned
    assert "CN202310123456.7" in cleaned
    assert "80-120" in cleaned

    # 多轮历史清洗
    hist = sanitize_history_messages([{"role": "user", "content": "联系 13800138000 看 https://a.cn?access_token=xyz"}])
    assert "13800138000" not in hist[0]["content"]
    assert "xyz" not in hist[0]["content"]


def test_priv_14_15_authorized_contact_and_demand_sanitization():
    # PRIV-14: AI 仅返回脱敏摘要，授权对接联系方式由主服务受权限门禁控制（此处验证 AI 侧永不返回明文）
    # PRIV-15: 需求卡片同样脱敏，不因缓存/格式化恢复明文
    demand = {
        "id": 301,
        "title": "寻求视觉检测方案 13811112222",
        "description": "预算 50 万元，联系 test@corp.cn，微信号：wx_corp01",
        "org_name_snapshot": "某精密制造公司",
        "region": "深圳南山",
        "budget_negotiable": False,
        "budget_min_wan": 40,
        "budget_max_wan": 60,
        "coop_mode": ["技术开发"],
        "contact_name": "李四",
        "contact_phone": "13911112222",
        "contact_email": "lisi@corp.cn",
    }
    card = format_demand_card(demand)
    dumped = json.dumps(card, ensure_ascii=False)
    assert "13811112222" not in dumped
    assert "13911112222" not in dumped
    assert "test@corp.cn" not in dumped
    assert "lisi@corp.cn" not in dumped
    assert "wx_corp01" not in dumped
    assert card["contact"]["phone"] == "139****2222"
