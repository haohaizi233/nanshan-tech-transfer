"""
AI 成果评价增强 —— 多维评价模型 / 评分算法 / 结果规范化（P: 成果评价增强）

设计来源：用户需求（多维度评价 + 评分体系 + AI 报告生成 + 历史记录），
         与 013_ai_evaluation（Phase C 四维）向后兼容。

职责划分：
- 本模块是「纯函数」评分域：维度注册表、权重、总分/等级/五分制换算、
  LLM 输出规范化、DB 行 → API 视图组装。不碰 DB、不发 HTTP。
- LLM 调用在 modules/ai/provider.py；写库在 modules/ai/worker.py；
  读取组装在 modules/ai/service.py。

评分体系：
- 百分制：每维 0-100，加权总分 totalScore = Σ score×weight（权重和=1）
- 五分制：starScore = totalScore / 20（0-5.0，1 位小数，读取时派生不落库）
- 等级：excellent(≥85 优秀) / good(≥70 良好) / fair(≥60 一般) / weak(<60 待改进)

兼容映射（LEGACY_SCORE_MAP）：013 四列由多维 1:1 派生写入，保证旧读取方
（含旧前端）拿到的仍是真实评分，不做假数据回填。
"""
from __future__ import annotations

import json
from typing import Any

# ── 维度注册表（顺序即前端展示顺序）────────────────────────────
# weight 权重和必须为 1.0（有单测守护）；comment 由 LLM 按维生成。
DIMENSIONS: tuple[dict, ...] = (
    {"key": "innovation", "label": "创新性", "weight": 0.18,
     "hint": "技术/模式创新程度、与现有方案的差异化、知识产权布局"},
    {"key": "techMaturity", "label": "技术成熟度", "weight": 0.22,
     "hint": "研发阶段、中试/量产可行性、技术指标先进性与稳定性"},
    {"key": "marketProspect", "label": "市场前景", "weight": 0.20,
     "hint": "市场规模、应用场景广度、商业化路径与竞争格局"},
    {"key": "teamStrength", "label": "团队实力", "weight": 0.15,
     "hint": "团队背景、研发能力、成果转化经验与组织保障"},
    {"key": "cooperation", "label": "合作可行性", "weight": 0.12,
     "hint": "合作方式灵活度、转化门槛、投入产出与落地周期"},
    {"key": "riskAssessment", "label": "风险评估", "weight": 0.13,
     "hint": "技术/市场/合规/实施风险的可控程度（分越高风险越可控）"},
)

DIMENSION_KEYS: tuple[str, ...] = tuple(d["key"] for d in DIMENSIONS)
DIMENSION_LABELS: dict[str, str] = {d["key"]: d["label"] for d in DIMENSIONS}
DIMENSION_WEIGHTS: dict[str, float] = {d["key"]: d["weight"] for d in DIMENSIONS}

# 013 Phase C 四列 ← 新维度 1:1 派生（score_tech/score_application/
# score_maturity/score_feasibility）。列语义见 013 迁移注释。
LEGACY_SCORE_MAP: dict[str, str] = {
    "techFeature": "innovation",       # 技术特点 ← 创新性
    "applyScope": "marketProspect",    # 应用范围 ← 市场前景
    "maturity": "techMaturity",        # 成熟度 ← 技术成熟度
    "cooperation": "cooperation",      # 合作可行性 ← 合作可行性
}

# 等级分档（下界 → (code, label)）
RATING_BANDS: tuple[tuple[float, str, str], ...] = (
    (85.0, "excellent", "优秀"),
    (70.0, "good", "良好"),
    (60.0, "fair", "一般"),
    (0.0, "weak", "待改进"),
)

# 输出长度上限（防御 LLM 超长输出撑爆响应/存储）
MAX_COMMENT_CHARS = 200
MAX_HIGHLIGHTS = 8
MAX_REPORT_SECTIONS = 8
MAX_SECTION_CONTENT_CHARS = 1200


class EvaluationDataError(ValueError):
    """LLM/外部输入的评价数据不合法（缺维度、类型错误等）。"""


# ── 评分算法 ───────────────────────────────────────────────────
def clamp_score(value: Any) -> float:
    """归一为 0-100 百分制，1 位小数；无法解析抛 EvaluationDataError。"""
    try:
        score = float(value)
    except (TypeError, ValueError):
        raise EvaluationDataError(f"score is not numeric: {value!r}")
    return round(max(0.0, min(100.0, score)), 1)


def compute_total(scores: dict[str, float]) -> float:
    """加权总分：Σ score×weight（权重和=1）。未知维度忽略，缺失维度记 0。

    注：normalize_llm_result 保证六维齐全后才走到这里；对部分输入按 0 计，
    与「无数据不假分」不冲突——这里处理的是已确认的评分输入。
    """
    total = 0.0
    for key, weight in DIMENSION_WEIGHTS.items():
        total += clamp_score(scores.get(key, 0.0)) * weight
    return round(max(0.0, min(100.0, total)), 1)


def rating_for(total_score: float) -> tuple[str, str]:
    """百分制总分 → (rating_code, rating_label)。"""
    total = float(total_score)
    for lower, code, label in RATING_BANDS:
        if total >= lower:
            return code, label
    return "weak", "待改进"


def star_for(total_score: float) -> float:
    """百分制 → 五分制（0-5.0，1 位小数）。"""
    return round(max(0.0, min(5.0, float(total_score) / 20.0)), 1)


def _clip(text: Any, limit: int) -> str:
    return str(text or "").strip()[:limit]


# ── LLM 输出规范化 ─────────────────────────────────────────────
def _normalize_dimensions(data: dict) -> list[dict]:
    raw = data.get("dimensions")
    if isinstance(raw, list):
        by_key = {}
        for item in raw:
            if isinstance(item, dict) and item.get("key") in DIMENSION_LABELS:
                by_key[item["key"]] = item
        raw = by_key
    if not isinstance(raw, dict):
        raise EvaluationDataError("dimensions missing")
    dims = []
    for key in DIMENSION_KEYS:
        item = raw.get(key)
        if not isinstance(item, dict):
            # 兼容扁平写法：{"innovation": 88}
            if item is not None:
                item = {"score": item}
            else:
                raise EvaluationDataError(f"dimension missing: {key}")
        dims.append({
            "key": key,
            "label": DIMENSION_LABELS[key],
            "score": clamp_score(item.get("score")),
            "weight": DIMENSION_WEIGHTS[key],
            "comment": _clip(item.get("comment"), MAX_COMMENT_CHARS),
        })
    return dims


def _normalize_report(data: dict) -> list[dict]:
    raw = data.get("report") or data.get("reportSections") or []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise EvaluationDataError("report is not a list")
    sections = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        heading = _clip(item.get("heading") or item.get("title"), 60)
        content = _clip(item.get("content") or item.get("body"), MAX_SECTION_CONTENT_CHARS)
        if heading and content:
            sections.append({"heading": heading, "content": content})
        if len(sections) >= MAX_REPORT_SECTIONS:
            break
    return sections


def normalize_llm_result(data: Any) -> dict:
    """把 LLM 返回的评价 JSON 规范成标准结构（不做评分换算，见 assemble_result）。

    输出：{dimensions:[{key,label,score,weight,comment}], conclusion, highlights, report}
    非法数据抛 EvaluationDataError（调用方转 AiProviderError 走任务失败链路）。
    """
    if not isinstance(data, dict):
        raise EvaluationDataError("evaluation JSON is not an object")
    return {
        "dimensions": _normalize_dimensions(data),
        "conclusion": _clip(data.get("conclusion") or data.get("summary"), 600),
        "highlights": _normalize_highlights(data.get("highlights") or data.get("suggestions")),
        "report": _normalize_report(data),
    }


def _normalize_highlights(raw: Any) -> list[str]:
    if raw is None:
        return []
    if not isinstance(raw, list):
        raw = [raw]
    return [text for text in (_clip(x, 200) for x in raw) if text][:MAX_HIGHLIGHTS]


def assemble_result(normalized: dict) -> dict:
    """评分体系换算：维度评分 → 总分/等级/五分制 + 013 兼容四列。

    输出：
      {
        "dimensions": [...],
        "totalScore": float, "starScore": float,
        "rating": "good", "ratingLabel": "良好",
        "conclusion": str, "highlights": [...], "report": [...],
        "legacyScores": {"techFeature":…, "applyScope":…, "maturity":…, "cooperation":…},
      }
    """
    dimensions = normalized["dimensions"]
    scores = {d["key"]: d["score"] for d in dimensions}
    total = compute_total(scores)
    rating, rating_label = rating_for(total)
    legacy = {
        legacy_key: scores[dim_key]
        for legacy_key, dim_key in LEGACY_SCORE_MAP.items()
    }
    return {
        "dimensions": dimensions,
        "totalScore": total,
        "starScore": star_for(total),
        "rating": rating,
        "ratingLabel": rating_label,
        "conclusion": normalized.get("conclusion") or "",
        "highlights": normalized.get("highlights") or [],
        "report": normalized.get("report") or [],
        "legacyScores": legacy,
    }


# ── DB 行 → API 视图 ───────────────────────────────────────────
def _loads(value: Any, default):
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return default


def build_evaluation_view(row: dict) -> dict:
    """ai_evaluation 行（含 achievement_title）→ 前端 evaluation 视图。

    - 新数据（dimensions 非空）：完整多维视图，scores 为 013 兼容四维。
    - 旧数据（enhance 前）：只给真实存在的旧四维 + totalScore/conclusion/
      highlights，dimensions=[]、report=[]（禁止给旧数据补造新维度分）。
    """
    dimensions = _loads(row.get("dimensions"), [])
    report = _loads(row.get("report_sections"), [])
    raw_highlights = row.get("suggestions")
    highlights = _loads(raw_highlights, None)
    if highlights is None:
        # 兼容纯文本亮点（非 JSON）：真实数据保留，不静默丢弃
        highlights = [str(raw_highlights)] if isinstance(raw_highlights, str) and raw_highlights.strip() else []
    if not isinstance(highlights, list):
        highlights = [str(highlights)]
    total = float(row.get("total_score") or 0)

    view = {
        "evaluationId": row.get("id"),
        "taskId": row.get("task_id"),
        "achievementId": row["achievement_id"],
        "achievementTitle": row.get("achievement_title") or "",
        "scores": {
            "techFeature": float(row.get("score_tech") or 0),
            "applyScope": float(row.get("score_application") or 0),
            "maturity": float(row.get("score_maturity") or 0),
            "cooperation": float(row.get("score_feasibility") or 0),
        },
        "totalScore": total,
        "conclusion": row.get("summary") or "",
        "highlights": [str(x) for x in highlights if str(x).strip()],
        "modelVersionLabel": None,
    }

    if dimensions:
        dims = []
        for item in dimensions:
            if not isinstance(item, dict) or item.get("key") not in DIMENSION_LABELS:
                continue
            score = clamp_score(item.get("score"))
            dims.append({
                "key": item["key"],
                "label": item.get("label") or DIMENSION_LABELS[item["key"]],
                "score": score,
                "weight": DIMENSION_WEIGHTS[item["key"]],
                "starScore": star_for(score),
                "comment": _clip(item.get("comment"), MAX_COMMENT_CHARS),
            })
        view["dimensions"] = dims
        view["report"] = [s for s in report if isinstance(s, dict)] if isinstance(report, list) else []
    else:
        view["dimensions"] = []
        view["report"] = []

    # rating 以行内值为准；旧数据按 total_score 现算等级（真实分档，非假分）
    rating = row.get("rating")
    if rating in {code for _, code, _ in RATING_BANDS}:
        label = next(lbl for _, code, lbl in RATING_BANDS if code == rating)
    else:
        rating, label = rating_for(total)
    view["rating"] = rating
    view["ratingLabel"] = label
    view["starScore"] = star_for(total)
    return view
