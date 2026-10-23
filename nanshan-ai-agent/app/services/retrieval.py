"""检索层公共构造：词条分层、相关度表达式、硬性条件片段。

修复的核心问题（真实库验证）：

1. **候选池按创建时间截断**：旧实现是 ``ORDER BY created_at DESC LIMIT 50``
   之后再在 Python 端打分。命中数超过 50 时，"最新但低相关"的内容会把
   "历史但高相关"的成果挤出候选池，相关性根本没机会生效。
   修复：把相关度计算下沉到 SQL，``ORDER BY 相关度 DESC, created_at DESC``，
   created_at 只作同分时的次级排序键。

2. **同义词 OR 爆炸**：一个"人工智能"展开成 8 个词、每词 5 个字段，
   候选池被"AI / 机器学习 / deep learning"这类宽松命中污染。
   修复：词条分层——用户原词系数 3、同义扩展系数 1，且扩展词数量受控。

3. **价格硬过滤把整库清空**：生产库 222/223 条成果报价为「面议」
   （price_min_wan / price_max_wan 均为 NULL），旧条件
   ``price_max_wan IS NOT NULL AND price_max_wan <= 上限``
   会把整个成果库过滤干净，用户问「100 万元以内的成果」恒定 0 条。
   修复：区间重叠语义——价格未知 ≠ 价格不符，不排除；非法数值才排除。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services import taxonomy
from app.services.query_utils import escape_like_term, normalize_search_terms


@dataclass(frozen=True)
class TermPlan:
    """一次查询使用的词条及其权重系数。"""

    literal: tuple[str, ...]
    expanded: tuple[str, ...]

    @property
    def all_terms(self) -> tuple[str, ...]:
        return self.literal + self.expanded

    def weighted(self) -> list[tuple[str, int]]:
        pairs = [(term, taxonomy.LITERAL_TERM_MULTIPLIER) for term in self.literal]
        pairs.extend((term, taxonomy.EXPANDED_TERM_MULTIPLIER) for term in self.expanded)
        return pairs


def build_term_plan(keywords: list[str], expansions: dict[str, list[str]]) -> TermPlan:
    """把用户关键词拆成「原词」与「同义扩展」两层。

    - 原词：用户真的说出来的词，权重系数 3；
    - 扩展：受控同义词表给出的补充词，权重系数 1；
    - 扩展词与原词重复时不重复计入。
    """
    normalized = normalize_search_terms(keywords)[: taxonomy.MAX_LITERAL_TERMS]
    literal: list[str] = []
    expanded: list[str] = []
    for term in normalized:
        term = term.strip()
        if not term:
            continue
        if term not in literal:
            literal.append(term)
        for candidate in expansions.get(term, []):
            candidate = candidate.strip()
            if not candidate or candidate in literal or candidate in expanded:
                continue
            expanded.append(candidate)
            if len(expanded) >= taxonomy.MAX_EXPANDED_TERMS:
                break
        if len(expanded) >= taxonomy.MAX_EXPANDED_TERMS:
            break
    return TermPlan(literal=tuple(literal), expanded=tuple(expanded))


def relevance_expression(kind: str, plan: TermPlan) -> tuple[str, list[str]]:
    """构造相关度表达式（SQL 片段 + 参数）。

    相关度 = Σ_词条 系数 × (标题命中×TITLE_WEIGHT + 正文命中×BODY_WEIGHT)

    标题与正文都改为引用 CTE 物化出来的检索列（``_searchable``），
    避免 PostgreSQL 对每行重复拼接多字段字符串。
    """
    parts: list[str] = []
    params: list[str] = []
    searchable = taxonomy.SEARCHABLE_COLUMN
    title_expr = taxonomy.collate("title")
    body_expr = taxonomy.collate(searchable)
    for term, multiplier in plan.weighted():
        like_value = f"%{escape_like_term(term)}%"
        parts.append(
            f"((CASE WHEN {title_expr} ILIKE %s ESCAPE E'\\\\' "
            f"THEN {taxonomy.TITLE_WEIGHT} ELSE 0 END)"
            f" + (CASE WHEN {body_expr} ILIKE %s ESCAPE E'\\\\' "
            f"THEN {taxonomy.BODY_WEIGHT} ELSE 0 END)) * {multiplier}"
        )
        params.extend([like_value, like_value])
    if not parts:
        return "0", []
    return " + ".join(parts), params


def keyword_condition(kind: str, plan: TermPlan) -> tuple[str, list[str]]:
    """构造关键词命中条件（各词条之间是 OR）。"""
    if not plan.all_terms:
        return "", []
    expression = taxonomy.collate(taxonomy.SEARCHABLE_COLUMN)
    parts: list[str] = []
    params: list[str] = []
    for term in plan.all_terms:
        parts.append(f"({expression}) ILIKE %s ESCAPE E'\\\\'")
        params.append(f"%{escape_like_term(term)}%")
    return "(" + " OR ".join(parts) + ")", params


def amount_condition(
    user_lower: float | None,
    user_upper: float | None,
    lower_column: str,
    upper_column: str,
) -> tuple[str, list]:
    """构造价格 / 预算条件（区间重叠语义，与 taxonomy.amount_band_matches 一致）。

    - 记录端价格未知（NULL）→ 不排除；
    - 记录端价格非法（NaN）→ 排除（与 Python 侧 fail closed 行为一致）；
    - 用户给上限 → 记录价格下限高于上限才排除；
    - 用户给下限 → 记录价格上限低于下限才排除。
    """
    if user_lower is None and user_upper is None:
        return "", []

    conditions = [
        f"({lower_column} IS NULL OR {lower_column} <> 'NaN'::numeric)",
        f"({upper_column} IS NULL OR {upper_column} <> 'NaN'::numeric)",
    ]
    params: list = []
    if user_upper is not None:
        conditions.append(
            f"({lower_column} IS NULL OR {lower_column} <= %s)"
        )
        params.append(user_upper)
    if user_lower is not None:
        conditions.append(
            f"({upper_column} IS NULL OR {upper_column} >= %s)"
        )
        params.append(user_lower)
    return "(" + " AND ".join(conditions) + ")", params


def coop_mode_condition(modes: list[str]) -> tuple[str, list[str]]:
    """构造合作方式条件：多个方式是 OR 关系，别名归一后命中任一即可。"""
    if not modes:
        return "", []
    spellings: list[str] = []
    for mode in modes:
        for spelling in taxonomy.resolve_coop_modes(mode):
            if spelling not in spellings:
                spellings.append(spelling)
    if not spellings:
        return "", []
    parts = []
    params: list[str] = []
    coop_expr = taxonomy.collate("coop_mode::text")
    for spelling in spellings:
        parts.append(f"{coop_expr} ILIKE %s ESCAPE E'\\\\'")
        params.append(f"%{escape_like_term(spelling)}%")
    return "(" + " OR ".join(parts) + ")", params


def score_items(
    kind: str,
    items: list[dict],
    plan: TermPlan,
) -> list[float]:
    """按与 SQL 完全一致的模型给候选打分（仅用于同分时的次级排序）。"""
    fields = taxonomy.fields_for(kind)
    scores: list[float] = []
    for item in items:
        title = str(item.get(fields.title_key) or "").lower()
        body = " ".join(
            str(item.get(key) or "").lower() for key in fields.body_keys
        )
        score = 0.0
        for term, multiplier in plan.weighted():
            needle = term.lower()
            if needle in title:
                score += taxonomy.TITLE_WEIGHT * multiplier
            if needle in body:
                score += taxonomy.BODY_WEIGHT * multiplier
        scores.append(score)
    return scores
