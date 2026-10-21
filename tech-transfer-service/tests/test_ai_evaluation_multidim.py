"""AI 成果评价增强（多维评分）测试。

覆盖：
- modules/ai/evaluation.py 纯函数评分域：
  维度注册表 / 权重 / 评分换算 / 等级分档 / LLM 输出规范化 / DB 行 → API 视图
- modules/ai/service.py：list_evaluations 评价历史（分页、过滤、列表不含报告全文）
- routes/ai.py：GET /api/tech-transfer/v1/ai/evaluations 评价历史接口契约

兼容性约束（禁止破坏）：
- 013 Phase C 旧四列（score_tech/score_application/score_maturity/score_feasibility）
  由多维 1:1 派生，视图 scores 字段保持旧形状；
- 旧数据（enhance 前、dimensions 为空）不补造新维度分。
"""
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import jwt
import pytest

from config import settings


# ── helpers ───────────────────────────────────────────────────
def _mock_cursor_context(cursor):
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return ctx


def _full_dimensions_payload(**overrides):
    """六维齐全的 LLM 评价 payload（dict 形态）。"""
    data = {
        "dimensions": {
            "innovation": {"score": 80, "comment": "创新点明确"},
            "techMaturity": {"score": 90, "comment": "中试成熟"},
            "marketProspect": {"score": 70, "comment": "市场可期"},
            "teamStrength": {"score": 60, "comment": "团队完整"},
            "cooperation": {"score": 50, "comment": "合作灵活"},
            "riskAssessment": {"score": 40, "comment": "风险可控"},
        },
        "conclusion": "总体良好",
        "highlights": ["亮点A", "亮点B"],
        "report": [{"heading": "综合评价", "content": "内容A"}],
    }
    data.update(overrides)
    return data


def _new_eval_row(**overrides):
    """enhance 后（多维）ai_evaluation 行。"""
    row = {
        "id": 11,
        "task_id": 101,
        "achievement_id": 5,
        "achievement_title": "测试成果",
        "score_tech": 80.0,
        "score_application": 70.0,
        "score_maturity": 90.0,
        "score_feasibility": 50.0,
        "total_score": 68.4,
        "summary": "总体良好",
        "suggestions": ["亮点A", "亮点B"],
        "dimensions": [
            {"key": "innovation", "score": 80, "comment": "创新点明确"},
            {"key": "techMaturity", "score": 90, "comment": "中试成熟"},
            {"key": "marketProspect", "score": 70, "comment": "市场可期"},
            {"key": "teamStrength", "score": 60, "comment": "团队完整"},
            {"key": "cooperation", "score": 50, "comment": "合作灵活"},
            {"key": "riskAssessment", "score": 40, "comment": "风险可控"},
        ],
        "report_sections": [{"heading": "综合评价", "content": "内容A"}],
        "rating": "fair",
        "created_at": datetime(2026, 10, 20, 12, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


def _legacy_eval_row(**overrides):
    """enhance 前（013 四维）ai_evaluation 行：无 dimensions / report / rating。"""
    row = {
        "id": 3,
        "task_id": 301,
        "achievement_id": 7,
        "achievement_title": "旧成果",
        "score_tech": 72.0,
        "score_application": 68.0,
        "score_maturity": 75.0,
        "score_feasibility": 60.0,
        "total_score": 72.0,
        "summary": "旧结论",
        "suggestions": "旧亮点",
        "dimensions": None,
        "report_sections": None,
        "rating": None,
        "created_at": datetime(2026, 9, 1, 8, 0, 0, tzinfo=timezone.utc),
    }
    row.update(overrides)
    return row


@pytest.fixture
def client():
    from fastapi.testclient import TestClient

    with patch("db.init_pool"), patch("db.close_pool"), \
            patch("db.get_cursor") as get_cursor, patch("db.get_conn") as get_conn:
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.fetchall.return_value = []
        get_cursor.return_value = _mock_cursor_context(cursor)
        connection = MagicMock()
        get_conn.return_value = _mock_cursor_context(connection)
        from app import app
        with TestClient(app, raise_server_exceptions=False) as test_client:
            yield test_client


def _auth(user_id):
    now = int(time.time())
    token = jwt.encode(
        {
            "sub": str(user_id), "userNo": f"U{user_id:03d}", "roles": ["user"],
            "type": "access", "iat": now, "exp": now + 3600,
        },
        settings.JWT_SECRET,
        algorithm=settings.JWT_ALGORITHM,
    )
    return {"Authorization": f"Bearer {token}"}


# ── 维度注册表 / 权重 ─────────────────────────────────────────
class TestDimensionRegistry:
    def test_six_dimensions_in_display_order(self):
        from modules.ai.evaluation import DIMENSION_KEYS
        assert DIMENSION_KEYS == (
            "innovation", "techMaturity", "marketProspect",
            "teamStrength", "cooperation", "riskAssessment",
        )

    def test_weights_sum_to_one(self):
        from modules.ai.evaluation import DIMENSION_WEIGHTS
        assert abs(sum(DIMENSION_WEIGHTS.values()) - 1.0) < 1e-9

    def test_all_weights_positive(self):
        from modules.ai.evaluation import DIMENSION_WEIGHTS
        assert all(0 < w < 1 for w in DIMENSION_WEIGHTS.values())

    def test_every_dimension_has_label_and_hint(self):
        from modules.ai.evaluation import DIMENSIONS
        for dim in DIMENSIONS:
            assert dim["label"]
            assert dim["hint"]

    def test_label_weight_maps_cover_registry(self):
        from modules.ai.evaluation import (
            DIMENSION_KEYS, DIMENSION_LABELS, DIMENSION_WEIGHTS,
        )
        assert set(DIMENSION_LABELS) == set(DIMENSION_KEYS)
        assert set(DIMENSION_WEIGHTS) == set(DIMENSION_KEYS)

    def test_legacy_map_targets_are_real_dimensions(self):
        from modules.ai.evaluation import DIMENSION_KEYS, LEGACY_SCORE_MAP
        assert set(LEGACY_SCORE_MAP) == {
            "techFeature", "applyScope", "maturity", "cooperation",
        }
        assert set(LEGACY_SCORE_MAP.values()) <= set(DIMENSION_KEYS)


# ── 评分算法：百分制 / 加权总分 / 等级 / 五分制 ───────────────
class TestScoreMath:
    def test_clamp_score_normal(self):
        from modules.ai.evaluation import clamp_score
        assert clamp_score(88) == 88.0
        assert clamp_score("72.5") == 72.5

    def test_clamp_score_rounds_to_one_decimal(self):
        from modules.ai.evaluation import clamp_score
        assert clamp_score(88.88) == 88.9

    @pytest.mark.parametrize("value,expected", [
        (150, 100.0), ("120", 100.0), (-5, 0.0), ("-1", 0.0), (0, 0.0), (100, 100.0),
    ])
    def test_clamp_score_bounds(self, value, expected):
        from modules.ai.evaluation import clamp_score
        assert clamp_score(value) == expected

    @pytest.mark.parametrize("value", ["abc", None, [1], {}])
    def test_clamp_score_rejects_non_numeric(self, value):
        from modules.ai.evaluation import EvaluationDataError, clamp_score
        with pytest.raises(EvaluationDataError):
            clamp_score(value)

    def test_compute_total_weighted(self):
        from modules.ai.evaluation import compute_total
        scores = {
            "innovation": 80, "techMaturity": 90, "marketProspect": 70,
            "teamStrength": 60, "cooperation": 50, "riskAssessment": 40,
        }
        # 80*.18 + 90*.22 + 70*.20 + 60*.15 + 50*.12 + 40*.13 = 68.4
        assert compute_total(scores) == 68.4

    def test_compute_total_all_zero(self):
        from modules.ai.evaluation import compute_total
        assert compute_total({}) == 0.0

    def test_compute_total_missing_dimension_counts_zero(self):
        from modules.ai.evaluation import compute_total
        assert compute_total({"innovation": 100}) == 18.0

    def test_compute_total_ignores_unknown_dimensions(self):
        from modules.ai.evaluation import compute_total
        scores = {
            "innovation": 100, "techMaturity": 0, "marketProspect": 0,
            "teamStrength": 0, "cooperation": 0, "riskAssessment": 0,
            "bogus": 100,
        }
        assert compute_total(scores) == 18.0

    def test_compute_total_clamps_input_scores(self):
        from modules.ai.evaluation import compute_total
        scores = {
            "innovation": 150, "techMaturity": -20, "marketProspect": 0,
            "teamStrength": 0, "cooperation": 0, "riskAssessment": 0,
        }
        assert compute_total(scores) == 18.0  # 100 * 0.18

    @pytest.mark.parametrize("total,code,label", [
        (100.0, "excellent", "优秀"),
        (85.0, "excellent", "优秀"),
        (84.9, "good", "良好"),
        (70.0, "good", "良好"),
        (69.9, "fair", "一般"),
        (60.0, "fair", "一般"),
        (59.9, "weak", "待改进"),
        (0.0, "weak", "待改进"),
    ])
    def test_rating_bands(self, total, code, label):
        from modules.ai.evaluation import rating_for
        assert rating_for(total) == (code, label)

    @pytest.mark.parametrize("total,star", [
        (100.0, 5.0), (80.0, 4.0), (76.0, 3.8), (0.0, 0.0),
    ])
    def test_star_for(self, total, star):
        from modules.ai.evaluation import star_for
        assert star_for(total) == star

    def test_star_for_clamps_range(self):
        from modules.ai.evaluation import star_for
        assert star_for(130.0) == 5.0
        assert star_for(-10.0) == 0.0


# ── LLM 输出规范化 ─────────────────────────────────────────────
class TestNormalization:
    def test_dict_form_full(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(_full_dimensions_payload())
        keys = [d["key"] for d in result["dimensions"]]
        assert keys == [
            "innovation", "techMaturity", "marketProspect",
            "teamStrength", "cooperation", "riskAssessment",
        ]
        first = result["dimensions"][0]
        assert first["label"] == "创新性"
        assert first["score"] == 80.0
        assert first["weight"] == 0.18
        assert first["comment"] == "创新点明确"

    def test_list_form_full(self):
        from modules.ai.evaluation import normalize_llm_result
        data = {
            "dimensions": [
                {"key": "innovation", "score": 80},
                {"key": "techMaturity", "score": 90},
                {"key": "marketProspect", "score": 70},
                {"key": "teamStrength", "score": 60},
                {"key": "cooperation", "score": 50},
                {"key": "riskAssessment", "score": 40},
            ],
        }
        result = normalize_llm_result(data)
        assert [d["score"] for d in result["dimensions"]] == \
            [80.0, 90.0, 70.0, 60.0, 50.0, 40.0]

    def test_list_form_ignores_unknown_keys(self):
        from modules.ai.evaluation import normalize_llm_result
        data = {
            "dimensions": [
                {"key": "innovation", "score": 80},
                {"key": "techMaturity", "score": 90},
                {"key": "marketProspect", "score": 70},
                {"key": "teamStrength", "score": 60},
                {"key": "cooperation", "score": 50},
                {"key": "riskAssessment", "score": 40},
                {"key": "bogus", "score": 99},
            ],
        }
        result = normalize_llm_result(data)
        assert len(result["dimensions"]) == 6
        assert all(d["key"] != "bogus" for d in result["dimensions"])

    def test_flat_form(self):
        from modules.ai.evaluation import normalize_llm_result
        data = {
            "dimensions": {
                "innovation": 88,
                "techMaturity": 92,
                "marketProspect": 75,
                "teamStrength": 65,
                "cooperation": 55,
                "riskAssessment": 45,
            },
        }
        result = normalize_llm_result(data)
        assert result["dimensions"][0]["score"] == 88.0
        assert result["dimensions"][0]["comment"] == ""

    def test_missing_dimension_raises(self):
        from modules.ai.evaluation import EvaluationDataError, normalize_llm_result
        data = _full_dimensions_payload()
        del data["dimensions"]["innovation"]
        with pytest.raises(EvaluationDataError):
            normalize_llm_result(data)

    @pytest.mark.parametrize("payload", [[1, 2], "text", 42, None])
    def test_non_object_raises(self, payload):
        from modules.ai.evaluation import EvaluationDataError, normalize_llm_result
        with pytest.raises(EvaluationDataError):
            normalize_llm_result(payload)

    def test_missing_dimensions_raises(self):
        from modules.ai.evaluation import EvaluationDataError, normalize_llm_result
        with pytest.raises(EvaluationDataError):
            normalize_llm_result({"conclusion": "x"})

    def test_invalid_score_raises(self):
        from modules.ai.evaluation import EvaluationDataError, normalize_llm_result
        data = _full_dimensions_payload()
        data["dimensions"]["innovation"]["score"] = "abc"
        with pytest.raises(EvaluationDataError):
            normalize_llm_result(data)

    def test_comment_clipped_to_200(self):
        from modules.ai.evaluation import MAX_COMMENT_CHARS, normalize_llm_result
        data = _full_dimensions_payload()
        data["dimensions"]["innovation"]["comment"] = "x" * 300
        result = normalize_llm_result(data)
        assert len(result["dimensions"][0]["comment"]) == MAX_COMMENT_CHARS == 200

    def test_conclusion_aliases_and_clip(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(
                conclusion=None, summary="别名结论" * 200,
            )
        )
        assert result["conclusion"].startswith("别名结论")
        assert len(result["conclusion"]) <= 600

    def test_highlights_string_becomes_list(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(_full_dimensions_payload(highlights="单条亮点"))
        assert result["highlights"] == ["单条亮点"]

    def test_highlights_capped_and_clipped(self):
        from modules.ai.evaluation import MAX_HIGHLIGHTS, normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(
                highlights=["x" * 300] + [f"h{i}" for i in range(10)] + [""],
            )
        )
        assert len(result["highlights"]) == MAX_HIGHLIGHTS == 8
        assert len(result["highlights"][0]) == 200
        assert "" not in result["highlights"]

    def test_highlights_suggestions_alias(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(highlights=None, suggestions=["s1", "s2"])
        )
        assert result["highlights"] == ["s1", "s2"]

    def test_report_dict_becomes_list(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(report={"heading": "h", "content": "c"})
        )
        assert result["report"] == [{"heading": "h", "content": "c"}]

    def test_report_title_body_alias(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(report=[{"title": "h", "body": "c"}])
        )
        assert result["report"] == [{"heading": "h", "content": "c"}]

    def test_report_skips_invalid_and_empty_items(self):
        from modules.ai.evaluation import normalize_llm_result
        result = normalize_llm_result(
            _full_dimensions_payload(
                report=[
                    "not a dict",
                    {"heading": "", "content": "c"},
                    {"heading": "h", "content": ""},
                    {"heading": "ok", "content": "body"},
                ],
            )
        )
        assert result["report"] == [{"heading": "ok", "content": "body"}]

    def test_report_capped_and_content_clipped(self):
        from modules.ai.evaluation import (
            MAX_REPORT_SECTIONS, MAX_SECTION_CONTENT_CHARS, normalize_llm_result,
        )
        result = normalize_llm_result(
            _full_dimensions_payload(
                report=[
                    {"heading": f"h{i}", "content": "y" * 2000} for i in range(12)
                ],
            )
        )
        assert len(result["report"]) == MAX_REPORT_SECTIONS == 8
        assert all(len(s["content"]) == MAX_SECTION_CONTENT_CHARS == 1200
                   for s in result["report"])

    def test_report_sections_alias(self):
        from modules.ai.evaluation import normalize_llm_result
        data = _full_dimensions_payload()
        del data["report"]
        data["reportSections"] = [{"heading": "h", "content": "c"}]
        result = normalize_llm_result(data)
        assert result["report"] == [{"heading": "h", "content": "c"}]


# ── assemble_result：评分体系 + 013 兼容列 ─────────────────────
class TestAssembleResult:
    def test_full_assemble(self):
        from modules.ai.evaluation import assemble_result, normalize_llm_result
        result = assemble_result(normalize_llm_result(_full_dimensions_payload()))
        assert result["totalScore"] == 68.4
        assert result["starScore"] == 3.4
        assert result["rating"] == "fair"
        assert result["ratingLabel"] == "一般"
        assert result["conclusion"] == "总体良好"
        assert result["highlights"] == ["亮点A", "亮点B"]
        assert result["report"] == [{"heading": "综合评价", "content": "内容A"}]

    def test_legacy_scores_derived_one_to_one(self):
        from modules.ai.evaluation import assemble_result, normalize_llm_result
        result = assemble_result(normalize_llm_result(_full_dimensions_payload()))
        assert result["legacyScores"] == {
            "techFeature": 80.0,
            "applyScope": 70.0,
            "maturity": 90.0,
            "cooperation": 50.0,
        }

    def test_dimensions_carried_through_with_registry_metadata(self):
        from modules.ai.evaluation import (
            DIMENSION_LABELS, DIMENSION_WEIGHTS, assemble_result,
            normalize_llm_result,
        )
        result = assemble_result(normalize_llm_result(_full_dimensions_payload()))
        for dim in result["dimensions"]:
            assert dim["label"] == DIMENSION_LABELS[dim["key"]]
            assert dim["weight"] == DIMENSION_WEIGHTS[dim["key"]]

    def test_perfect_scores_rate_excellent(self):
        from modules.ai.evaluation import assemble_result, normalize_llm_result
        data = {
            "dimensions": {
                key: {"score": 100}
                for key in (
                    "innovation", "techMaturity", "marketProspect",
                    "teamStrength", "cooperation", "riskAssessment",
                )
            },
        }
        result = assemble_result(normalize_llm_result(data))
        assert result["totalScore"] == 100.0
        assert result["starScore"] == 5.0
        assert result["rating"] == "excellent"
        assert result["ratingLabel"] == "优秀"


# ── build_evaluation_view：DB 行 → API 视图 ────────────────────
class TestBuildEvaluationView:
    def test_new_data_full_multidim_view(self):
        from modules.ai.evaluation import build_evaluation_view, star_for
        view = build_evaluation_view(_new_eval_row())
        assert view["evaluationId"] == 11
        assert view["taskId"] == 101
        assert view["achievementId"] == 5
        assert view["achievementTitle"] == "测试成果"
        # 013 兼容四列保持旧形状
        assert view["scores"] == {
            "techFeature": 80.0,
            "applyScope": 70.0,
            "maturity": 90.0,
            "cooperation": 50.0,
        }
        assert view["totalScore"] == 68.4
        assert view["conclusion"] == "总体良好"
        assert view["highlights"] == ["亮点A", "亮点B"]

    def test_new_data_dimensions_enriched(self):
        from modules.ai.evaluation import build_evaluation_view, star_for
        view = build_evaluation_view(_new_eval_row())
        assert len(view["dimensions"]) == 6
        first = view["dimensions"][0]
        assert first["key"] == "innovation"
        assert first["label"] == "创新性"
        assert first["score"] == 80.0
        assert first["weight"] == 0.18
        assert first["starScore"] == star_for(80.0)
        assert first["comment"] == "创新点明确"

    def test_new_data_report_preserved(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_new_eval_row())
        assert view["report"] == [{"heading": "综合评价", "content": "内容A"}]

    def test_new_data_rating_from_row(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_new_eval_row())
        assert view["rating"] == "fair"
        assert view["ratingLabel"] == "一般"
        assert view["starScore"] == 3.4  # 68.4 / 20

    def test_json_string_columns_parsed(self):
        import json
        from modules.ai.evaluation import build_evaluation_view
        row = _new_eval_row(
            dimensions=json.dumps(_new_eval_row()["dimensions"], ensure_ascii=False),
            report_sections=json.dumps(
                [{"heading": "综合评价", "content": "内容A"}], ensure_ascii=False
            ),
            suggestions=json.dumps(["亮点A", "亮点B"], ensure_ascii=False),
        )
        view = build_evaluation_view(row)
        assert len(view["dimensions"]) == 6
        assert view["report"] == [{"heading": "综合评价", "content": "内容A"}]
        assert view["highlights"] == ["亮点A", "亮点B"]

    def test_legacy_data_keeps_only_real_scores(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_legacy_eval_row())
        # 禁止给旧数据补造新维度分
        assert view["dimensions"] == []
        assert view["report"] == []
        assert view["scores"] == {
            "techFeature": 72.0,
            "applyScope": 68.0,
            "maturity": 75.0,
            "cooperation": 60.0,
        }
        assert view["totalScore"] == 72.0

    def test_legacy_data_rating_computed_from_total(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_legacy_eval_row())
        assert view["rating"] == "good"   # 72.0 ≥ 70
        assert view["ratingLabel"] == "良好"
        assert view["starScore"] == 3.6

    def test_invalid_row_rating_falls_back_to_computed(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_new_eval_row(rating="great"))
        assert view["rating"] == "fair"
        assert view["ratingLabel"] == "一般"

    def test_highlights_single_string_normalized(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_legacy_eval_row(suggestions="旧亮点"))
        assert view["highlights"] == ["旧亮点"]

    def test_unknown_dimension_keys_filtered(self):
        from modules.ai.evaluation import build_evaluation_view
        row = _new_eval_row(dimensions=_new_eval_row()["dimensions"] + [
            {"key": "bogus", "score": 99},
        ])
        view = build_evaluation_view(row)
        assert len(view["dimensions"]) == 6
        assert all(d["key"] != "bogus" for d in view["dimensions"])

    def test_model_version_placeholder_present(self):
        from modules.ai.evaluation import build_evaluation_view
        view = build_evaluation_view(_new_eval_row())
        assert "modelVersionLabel" in view


# ── list_evaluations：评价历史（service 层）────────────────────
class TestListEvaluations:
    @patch("modules.ai.service.get_cursor")
    def test_history_returns_paginated_views_without_report(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 2}
        cur.fetchall.return_value = [
            _new_eval_row(id=12, task_id=102),
            _new_eval_row(id=11, task_id=101),
        ]
        mock_gc.return_value = _mock_cursor_context(cur)

        result = list_evaluations(7, page=1, page_size=10)
        assert result["total"] == 2
        assert result["page"] == 1
        assert result["pageSize"] == 10
        assert len(result["list"]) == 2
        item = result["list"][0]
        assert item["evaluationId"] == 12
        assert item["taskId"] == 102
        # 列表不带报告全文（详情走 taskId）
        assert "report" not in item
        assert item["createdAt"] is not None

    @patch("modules.ai.service.get_cursor")
    def test_history_page_clamped(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_context(cur)

        result = list_evaluations(7, page=0, page_size=999)
        assert result["page"] == 1
        assert result["pageSize"] == 50  # 上限 50
        # 第二条 SQL（分页查询）的参数 = [user_id, limit, offset]
        params = cur.execute.call_args_list[1].args[1]
        assert params == [7, 50, 0]

    @patch("modules.ai.service.get_cursor")
    def test_history_offset_follows_page(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_context(cur)

        list_evaluations(7, page=3, page_size=10)
        params = cur.execute.call_args_list[1].args[1]
        assert params == [7, 10, 20]

    @patch("modules.ai.service.get_cursor")
    def test_history_filters_by_achievement(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_context(cur)

        list_evaluations(7, page=1, page_size=10, achievement_id=5)
        count_sql = cur.execute.call_args_list[0].args[0]
        page_sql = cur.execute.call_args_list[1].args[0]
        assert "e.achievement_id = %s" in count_sql
        assert "e.achievement_id = %s" in page_sql
        assert cur.execute.call_args_list[0].args[1] == [7, 5]
        assert cur.execute.call_args_list[1].args[1] == [7, 5, 10, 0]

    @patch("modules.ai.service.get_cursor")
    def test_history_scoped_to_current_user(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 0}
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_context(cur)

        list_evaluations(42)
        assert "t.created_by_user_id = %s" in cur.execute.call_args_list[0].args[0]
        assert cur.execute.call_args_list[0].args[1][0] == 42

    @patch("modules.ai.service.get_cursor")
    def test_history_empty(self, mock_gc):
        from modules.ai.service import list_evaluations
        cur = MagicMock()
        cur.fetchone.return_value = None  # COUNT 行缺失防御
        cur.fetchall.return_value = []
        mock_gc.return_value = _mock_cursor_context(cur)

        result = list_evaluations(7)
        assert result == {
            "list": [], "total": 0, "page": 1, "pageSize": 10,
        }


# ── GET /ai/evaluations：评价历史接口 ──────────────────────────
BASE = "/api/tech-transfer/v1"


class TestEvaluationHistoryRoute:
    @patch("routes.ai.settings.AI_FEATURE_ENABLED", True)
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.list_evaluations")
    def test_history_contract(self, list_evaluations, _active, client):
        payload = {
            "list": [{
                "evaluationId": 11, "taskId": 101, "achievementId": 5,
                "achievementTitle": "测试成果",
                "scores": {"techFeature": 80.0, "applyScope": 70.0,
                           "maturity": 90.0, "cooperation": 50.0},
                "dimensions": [], "report": [],
                "totalScore": 68.4, "starScore": 3.4,
                "rating": "fair", "ratingLabel": "一般",
                "conclusion": "总体良好", "highlights": ["亮点A"],
                "createdAt": "2026-10-20T12:00:00+00:00",
            }],
            "total": 1, "page": 1, "pageSize": 10,
        }
        list_evaluations.return_value = payload

        resp = client.get(f"{BASE}/ai/evaluations", headers=_auth(7))
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"] == payload
        list_evaluations.assert_called_once_with(7, 1, 10, None)

    @patch("routes.ai.settings.AI_FEATURE_ENABLED", True)
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.list_evaluations")
    def test_history_query_args_forwarded(self, list_evaluations, _active, client):
        list_evaluations.return_value = {"list": [], "total": 0, "page": 2, "pageSize": 5}
        resp = client.get(
            f"{BASE}/ai/evaluations?page=2&pageSize=5&achievementId=9",
            headers=_auth(7),
        )
        assert resp.status_code == 200
        list_evaluations.assert_called_once_with(7, 2, 5, 9)

    @pytest.mark.parametrize("raw", ["abc", "0", "-3", "1.5x"])
    @patch("routes.ai.settings.AI_FEATURE_ENABLED", True)
    @patch("core.middleware._user_is_active", return_value=True)
    @patch("routes.ai.list_evaluations")
    def test_history_rejects_invalid_achievement_id(self, list_evaluations, _active, client, raw):
        resp = client.get(
            f"{BASE}/ai/evaluations?achievementId={raw}", headers=_auth(7)
        )
        assert resp.status_code == 400
        assert resp.json()["code"] == "TT_COMMON_40001"
        list_evaluations.assert_not_called()

    @patch("routes.ai.settings.AI_FEATURE_ENABLED", True)
    def test_history_requires_auth(self, client):
        resp = client.get(f"{BASE}/ai/evaluations")
        assert resp.status_code == 401

    @patch("routes.ai.settings.AI_FEATURE_ENABLED", True)
    @patch("core.middleware._user_is_active", return_value=True)
    def test_history_end_to_end_with_db_rows(self, _active, client):
        """路由 → service → build_evaluation_view 全链路（DB mock）。"""
        cur = MagicMock()
        cur.fetchone.return_value = {"n": 1}
        cur.fetchall.return_value = [_new_eval_row()]
        with patch("modules.ai.service.get_cursor") as mock_gc:
            mock_gc.return_value = _mock_cursor_context(cur)
            resp = client.get(f"{BASE}/ai/evaluations", headers=_auth(7))

        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["total"] == 1
        assert data["page"] == 1
        item = data["list"][0]
        assert item["evaluationId"] == 11
        assert item["achievementTitle"] == "测试成果"
        assert len(item["dimensions"]) == 6
        assert item["ratingLabel"] == "一般"
        assert "report" not in item

    @patch("routes.ai.settings.AI_FEATURE_ENABLED", False)
    def test_history_disabled_when_ai_switch_off(self, client):
        resp = client.get(f"{BASE}/ai/evaluations", headers=_auth(7))
        assert resp.status_code >= 400
