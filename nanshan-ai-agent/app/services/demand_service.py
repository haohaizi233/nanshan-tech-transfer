from typing import Any

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services import retrieval, taxonomy
from app.services.query_utils import escape_like_term


@trace_stage("retrieve_demands")
def search_demands(
    keywords: list[str],
    organization: str | None = None,
    region: str | None = None,
    min_budget_wan: float | None = None,
    max_budget_wan: float | None = None,
    coop_modes: list[str] | None = None,
    limit: int = 10,
    exclude_owner_user_id: int | None = None,
    target_ids: list[int] | None = None,
) -> list[dict]:

    limit = min(max(limit, 1), 30)

    plan = retrieval.build_term_plan(keywords, taxonomy.KEYWORD_EXPANSIONS)

    conditions = [
        "status = 'published'",
        "deleted_at IS NULL",

        """
        title NOT IN (
            '1',
            '11',
            '111',
            '222',
            '测试'
        )
        """,

        "title NOT ILIKE 'T008%%'",
    ]

    params = []
    if target_ids is not None:
        if not target_ids:
            return []
        conditions.append("id = ANY(%s)")
        params.append(target_ids[:10])

    # 不把用户自己的需求推荐给自己
    if exclude_owner_user_id is not None:
        conditions.append("(owner_user_id IS NULL OR owner_user_id <> %s)")
        params.append(exclude_owner_user_id)

    # =========================
    # 关键词（原词 + 同义扩展，OR 关系）
    # =========================

    keyword_sql, keyword_params = retrieval.keyword_condition("demand", plan)
    if keyword_sql:
        conditions.append(keyword_sql)
        params.extend(keyword_params)

    # =========================
    # 发布机构
    # =========================

    if organization:

        conditions.append(
            "org_name_snapshot ILIKE %s ESCAPE E'\\\\'"
        )

        params.append(
            f"%{escape_like_term(organization)}%"
        )

    # =========================
    # 地域
    # =========================

    if region:

        conditions.append(
            "region ILIKE %s ESCAPE E'\\\\'"
        )

        params.append(
            f"%{escape_like_term(region)}%"
        )

    # =========================
    # 预算区间（重叠语义：预算未知不排除，非法数值排除）
    # =========================

    amount_sql, amount_params = retrieval.amount_condition(
        min_budget_wan,
        max_budget_wan,
        "budget_min_wan",
        "budget_max_wan",
    )
    if amount_sql:
        conditions.append(amount_sql)
        params.extend(amount_params)

    # =========================
    # 合作方式（多个方式是 OR 关系，别名归一后命中任一即可）
    # =========================

    coop_sql, coop_params = retrieval.coop_mode_condition(list(coop_modes or []))
    if coop_sql:
        conditions.append(coop_sql)
        params.extend(coop_params)

    where_clause = " AND ".join(
        conditions
    )

    # 相关度下沉到 SQL：候选池按相关度排序，created_at 只作同分次级键。
    relevance_sql, relevance_params = retrieval.relevance_expression("demand", plan)

    params = relevance_params + params
    params.append(50)

    sql = f"""
        SELECT
            id,
            owner_user_id,
            status,
            deleted_at,
            title,
            description,
            org_name_snapshot,
            budget_negotiable,
            budget_min_wan,
            budget_max_wan,
            contact_name,
            contact_phone,
            contact_email,
            view_count,
            region,
            coop_mode,
            created_at,
            ({relevance_sql}) AS _rel
        FROM demand
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
