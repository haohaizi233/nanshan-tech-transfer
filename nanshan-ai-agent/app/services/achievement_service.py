from typing import Any

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services import retrieval, taxonomy
from app.services.query_utils import escape_like_term


# 受控同义词表：既是检索扩展表，也是「裸领域词」启发式的白名单。
# 实际取值集中在 taxonomy.KEYWORD_EXPANSIONS，这里保留同名导出以兼容既有引用。
KEYWORD_EXPANSIONS = taxonomy.KEYWORD_EXPANSIONS

MATURITY_ORDER = taxonomy.MATURITY_ORDER


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

    conditions = [
        "status = 'published'",
        "deleted_at IS NULL",
    ]

    params = []
    if region:
        raise ValueError("成果未披露地域字段，无法核实该地域条件")
    if target_ids is not None:
        if not target_ids:
            return []
        conditions.append("id = ANY(%s)")
        params.append(target_ids[:10])

    # 不把用户自己的成果推荐给自己（owner_user_id 可空：未绑定归属人的成果仍可被检索到）
    if exclude_owner_user_id is not None:
        conditions.append("(owner_user_id IS NULL OR owner_user_id <> %s)")
        params.append(exclude_owner_user_id)

    # =========================
    # 关键词（原词 + 同义扩展，OR 关系）
    # =========================

    keyword_sql, keyword_params = retrieval.keyword_condition("achievement", plan)
    if keyword_sql:
        conditions.append(keyword_sql)
        params.extend(keyword_params)

    # =========================
    # 机构
    # =========================

    if organization:
        conditions.append(
            "source_org_name ILIKE %s ESCAPE E'\\\\'"
        )

        params.append(
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
        conditions.append(amount_sql)
        params.extend(amount_params)

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

        conditions.append(
            f"maturity_level IN ({placeholders})"
        )

        params.extend(allowed_maturity)

    where_clause = " AND ".join(
        conditions
    )

    # 相关度下沉到 SQL：候选池按相关度排序，created_at 只作同分次级键。
    # （旧实现是 ORDER BY created_at DESC LIMIT 50，高相关的历史成果会被挤掉。）
    relevance_sql, relevance_params = retrieval.relevance_expression("achievement", plan)

    params = relevance_params + params
    params.append(50)

    sql = f"""
        SELECT
            id,
            owner_user_id,
            status,
            deleted_at,
            title,
            source_org_name,
            tech_intro,
            pricing_mode,
            price_min_wan,
            price_max_wan,
            maturity_level,
            application_fields,
            innovation_points,
            contact_name,
            contact_phone,
            contact_email,
            view_count,
            created_at,
            ({relevance_sql}) AS _rel
        FROM achievement
        WHERE {where_clause}
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

        item["_score"] = item.pop("_rel", 0) or 0

        results.append(item)

    return results[:limit]
