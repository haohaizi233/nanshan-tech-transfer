from typing import Any

from app.database import get_db
from app.runtime_trace import trace_stage
from app.services.achievement_service import expand_keywords
from app.services.query_utils import escape_like_term, normalize_search_terms


def _calculate_score(
    item: dict[str, Any],
    search_terms: list[str],
) -> int:

    score = 0

    title = str(item.get("title") or "").lower()
    description = str(
        item.get("description") or ""
    ).lower()
    org_name = str(
        item.get("org_name_snapshot") or ""
    ).lower()
    region = str(item.get("region") or "").lower()
    coop_mode = str(
        item.get("coop_mode") or ""
    ).lower()

    for term in search_terms:
        term = term.lower()

        if term in title:
            score += 5

        if term in description:
            score += 3

        if term in org_name:
            score += 1

        if term in region:
            score += 1

        if term in coop_mode:
            score += 1

    return score


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
) -> list[dict]:

    limit = min(max(limit, 1), 30)

    coop_modes = normalize_search_terms(coop_modes or [])[:5]

    search_terms = expand_keywords(
        keywords
    )

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

    # 不把用户自己的需求推荐给自己
    if exclude_owner_user_id is not None:
        conditions.append("(owner_user_id IS NULL OR owner_user_id <> %s)")
        params.append(exclude_owner_user_id)

    # =========================
    # 关键词
    # =========================

    if search_terms:

        keyword_conditions = []

        for term in search_terms:

            like_value = f"%{escape_like_term(term)}%"

            keyword_conditions.append(
                """
                (
                    title ILIKE %s ESCAPE E'\\\\'
                    OR description ILIKE %s ESCAPE E'\\\\'
                    OR org_name_snapshot ILIKE %s ESCAPE E'\\\\'
                    OR region ILIKE %s ESCAPE E'\\\\'
                    OR coop_mode::text ILIKE %s ESCAPE E'\\\\'
                )
                """
            )

            params.extend([
                like_value,
                like_value,
                like_value,
                like_value,
                like_value,
            ])

        conditions.append(
            "("
            + " OR ".join(keyword_conditions)
            + ")"
        )

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
    # 最低预算
    # =========================

    if min_budget_wan is not None:

        conditions.append(
            """
            budget_min_wan IS NOT NULL
            AND budget_min_wan >= %s
            """
        )

        params.append(
            min_budget_wan
        )

    # =========================
    # 最高预算
    # =========================

    if max_budget_wan is not None:

        conditions.append(
            """
            budget_max_wan IS NOT NULL
            AND budget_max_wan <= %s
            """
        )

        params.append(
            max_budget_wan
        )

    # =========================
    # 合作方式
    # =========================

    for mode in coop_modes:

        conditions.append(
            "coop_mode::text ILIKE %s ESCAPE E'\\\\'"
        )

        params.append(
            f"%{escape_like_term(mode)}%"
        )

    where_clause = " AND ".join(
        conditions
    )

    params.append(50)

    sql = f"""
        SELECT
            id,
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
            created_at
        FROM demand
        WHERE {where_clause}
        ORDER BY created_at DESC
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

        item["_score"] = (
            _calculate_score(
                item,
                search_terms,
            )
            if search_terms
            else 1
        )

        results.append(item)

    results.sort(
        key=lambda x: x["_score"],
        reverse=True,
    )

    return results[:limit]
