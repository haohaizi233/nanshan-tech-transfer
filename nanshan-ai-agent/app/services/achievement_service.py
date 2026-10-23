from typing import Any

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services import retrieval, taxonomy
from app.services.query_utils import escape_like_term


# 受控同义词表：既是检索扩展表，也是「裸领域词」启发式的白名单。
# 实际取值集中在 taxonomy.KEYWORD_EXPANSIONS，这里保留同名导出以兼容既有引用。
KEYWORD_EXPANSIONS = taxonomy.KEYWORD_EXPANSIONS

MATURITY_ORDER = taxonomy.MATURITY_ORDER


# 显式列清单：CTE 与外层 SELECT 共用同一份，
# 目的是把物化出来的 `_searchable` 留在 CTE 内部，不随结果字典外流。
_COLUMNS = (
    "id",
    "owner_user_id",
    "status",
    "deleted_at",
    "title",
    "source_org_name",
    "tech_intro",
    "pricing_mode",
    "price_min_wan",
    "price_max_wan",
    "maturity_level",
    "application_fields",
    "innovation_points",
    "contact_name",
    "contact_phone",
    "contact_email",
    "view_count",
    "created_at",
)

_PROJECTION = ",\n            ".join(_COLUMNS)


def get_allowed_maturity_levels(
    min_maturity: str | None,
) -> list[str]:

    if not min_maturity:
        return []

    if min_maturity not in MATURITY_ORDER:
        return []

    index = MATURITY_ORDER.index(min_maturity)

    return MATURITY_ORDER[index:]


def expand_keywords(keywords: list[str]) -> list[str]:
    """兼容入口：返回参与检索的全部词条（原词 + 同义扩展）。"""
    plan = retrieval.build_term_plan(keywords, KEYWORD_EXPANSIONS)
    return list(plan.all_terms)


@trace_stage("retrieve_achievements")
def search_achievements(
    keywords: list[str],
    organization: str | None = None,
    min_price_wan: float | None = None,
    max_price_wan: float | None = None,
    min_maturity: str | None = None,
    limit: int = 10,
    exclude_owner_user_id: int | None = None,
    target_ids: list[int] | None = None,
    region: str | None = None,
) -> list[dict]:

    limit = min(max(limit, 1), 30)

    plan = retrieval.build_term_plan(keywords, KEYWORD_EXPANSIONS)

    # 基表条件：先过滤再拼接可检索文本（性能关键，见 taxonomy.searchable_cte）。
    base_conditions = [
        "status = 'published'",
        "deleted_at IS NULL",
    ]
    base_params: list = []

    params = []
    if region:
        raise ValueError("成果未披露地域字段，无法核实该地域条件")
    if target_ids is not None:
        if not target_ids:
            return []
        base_conditions.append("id = ANY(%s)")
        base_params.append(target_ids[:10])

    # 不把用户自己的成果推荐给自己（owner_user_id 可空：未绑定归属人的成果仍可被检索到）
    if exclude_owner_user_id is not None:
        base_conditions.append("(owner_user_id IS NULL OR owner_user_id <> %s)")
        base_params.append(exclude_owner_user_id)

    # =========================
    # 关键词（原词 + 同义扩展，OR 关系）
    # =========================
    # 关键词条件依赖物化后的检索列，只能留在 CTE 外层。

    keyword_sql, keyword_params = retrieval.keyword_condition("achievement", plan)
    outer_conditions: list[str] = []
    if keyword_sql:
        outer_conditions.append(keyword_sql)
        params.extend(keyword_params)

    # =========================
    # 机构
    # =========================

    if organization:
        base_conditions.append(
            "source_org_name COLLATE \"C\" ILIKE %s ESCAPE E'\\\\'"
        )

        base_params.append(
            f"%{escape_like_term(organization)}%"
        )

    # =========================
    # 报价区间（重叠语义：价格未知不排除，非法数值排除）
    # =========================

    amount_sql, amount_params = retrieval.amount_condition(
        min_price_wan,
        max_price_wan,
        "price_min_wan",
        "price_max_wan",
    )
    if amount_sql:
        base_conditions.append(amount_sql)
        base_params.extend(amount_params)

    # =========================
    # 成熟度
    # =========================

    allowed_maturity = (
        get_allowed_maturity_levels(
            min_maturity
        )
    )

    if allowed_maturity:

        placeholders = ",".join(
            ["%s"] * len(allowed_maturity)
        )

        base_conditions.append(
            f"maturity_level IN ({placeholders})"
        )

        base_params.extend(allowed_maturity)

    # 相关度下沉到 SQL：候选池按相关度排序，created_at 只作同分次级键。
    # （旧实现是 ORDER BY created_at DESC LIMIT 50，高相关的历史成果会被挤掉。）
    relevance_sql, relevance_params = retrieval.relevance_expression("achievement", plan)

    # 可检索文本在 CTE 里物化一次，供相关度与关键词条件共用，
    # 避免 PostgreSQL 对每行重复拼接 5 个字段的字符串。
    projection = _PROJECTION

    base_where = " AND ".join(base_conditions)
    outer_where = " AND ".join(outer_conditions)
    where_clause = f"WHERE {outer_where}" if outer_where else ""

    # 参数顺序必须与 SQL 中占位符出现的先后一致：
    #   1) CTE 内的基表过滤参数（WHERE 出现在 CTE 中，最先）
    #   2) SELECT 里的相关度参数
    #   3) 外层 WHERE 里的关键词参数
    #   4) LIMIT
    params = base_params + relevance_params + params
    params.append(50)

    sql = f"""
        {taxonomy.searchable_cte("achievement", "achievement", projection, base_where)}
        SELECT
            {_COLUMNS[0]},
            {", ".join(_COLUMNS[1:])},
            ({relevance_sql}) AS _rel
        FROM base
        {where_clause}
        ORDER BY _rel DESC, created_at DESC
        LIMIT %s;
    """

    with get_db() as conn:
        with conn.cursor() as cur:

            cur.execute(
                sql,
                tuple(params),
            )

            rows = cur.fetchall()

    results = []

    for row in rows:

        item = dict(row)

        # 内部列只服务于 SQL 计算，不允许出现在返回给上层的字典里。
        item.pop(taxonomy.SEARCHABLE_COLUMN, None)
        item["_score"] = item.pop("_rel", 0) or 0

        results.append(item)

    return results[:limit]
