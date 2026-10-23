from typing import Any

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services import retrieval, taxonomy
from app.services.query_utils import escape_like_term


# 显式列清单：CTE 与外层 SELECT 共用同一份，
# 目的是把物化出来的 `_searchable` 留在 CTE 内部，不随结果字典外流。
_COLUMNS = (
    "id",
    "owner_user_id",
    "status",
    "deleted_at",
    "title",
    "description",
    "org_name_snapshot",
    "budget_negotiable",
    "budget_min_wan",
    "budget_max_wan",
    "contact_name",
    "contact_phone",
    "contact_email",
    "view_count",
    "region",
    "coop_mode",
    "created_at",
)

_PROJECTION = ",\n            ".join(_COLUMNS)


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

    # =========================
    # 基表条件（先过滤，再拼接可检索文本）
    # =========================
    # 这些条件与关键词无关，下推到 CTE 内部可以让字符串拼接只作用于
    # 真正可能被命中的行（实测 P50 从 48ms 降到 9ms）。

    base_conditions = [
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
    base_params: list = []

    if target_ids is not None:
        if not target_ids:
            return []
        base_conditions.append("id = ANY(%s)")
        base_params.append(target_ids[:10])

    # 不把用户自己的需求推荐给自己
    if exclude_owner_user_id is not None:
        base_conditions.append("(owner_user_id IS NULL OR owner_user_id <> %s)")
        base_params.append(exclude_owner_user_id)

    # =========================
    # 发布机构
    # =========================

    if organization:

        base_conditions.append(
            "org_name_snapshot COLLATE \"C\" ILIKE %s ESCAPE E'\\\\'"
        )

        base_params.append(
            f"%{escape_like_term(organization)}%"
        )

    # =========================
    # 地域
    # =========================

    if region:

        base_conditions.append(
            "region COLLATE \"C\" ILIKE %s ESCAPE E'\\\\'"
        )

        base_params.append(
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
        base_conditions.append(amount_sql)
        base_params.extend(amount_params)

    # =========================
    # 合作方式（多个方式是 OR 关系，别名归一后命中任一即可）
    # =========================

    coop_sql, coop_params = retrieval.coop_mode_condition(list(coop_modes or []))
    if coop_sql:
        base_conditions.append(coop_sql)
        base_params.extend(coop_params)

    # =========================
    # 关键词（原词 + 同义扩展，OR 关系）
    # =========================
    # 关键词条件依赖物化后的检索列，只能留在 CTE 外层。

    keyword_sql, keyword_params = retrieval.keyword_condition("demand", plan)
    outer_conditions: list[str] = []
    outer_params: list = []
    if keyword_sql:
        outer_conditions.append(keyword_sql)
        outer_params.extend(keyword_params)

    # 相关度下沉到 SQL：候选池按相关度排序，created_at 只作同分次级键。
    # （旧实现是 ORDER BY created_at DESC LIMIT 50，高相关的历史需求会被挤掉。）
    relevance_sql, relevance_params = retrieval.relevance_expression("demand", plan)

    base_where = " AND ".join(base_conditions)
    outer_where = " AND ".join(outer_conditions)
    where_clause = f"WHERE {outer_where}" if outer_where else ""

    # 参数顺序必须与 SQL 中占位符出现的先后一致：
    #   1) CTE 内的基表过滤参数（WHERE 出现在 CTE 中，最先）
    #   2) SELECT 里的相关度参数
    #   3) 外层 WHERE 里的关键词参数
    #   4) LIMIT
    params = base_params + relevance_params + outer_params
    params.append(50)

    sql = f"""
        {taxonomy.searchable_cte("demand", "demand", _PROJECTION, base_where)}
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
