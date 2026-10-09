from typing import Any

from app.database import get_db
from app.services.query_utils import escape_like_term, normalize_search_terms


# 第一版先用受控同义词表
KEYWORD_EXPANSIONS = {
    "人工智能": [
        "人工智能",
        "AI",
        "artificial intelligence",
        "机器学习",
        "machine learning",
        "深度学习",
        "deep learning",
    ],
    "AI": [
        "AI",
        "人工智能",
        "artificial intelligence",
        "machine learning",
        "deep learning",
    ],
    "机器视觉": [
        "机器视觉",
        "machine vision",
        "computer vision",
        "视觉检测",
        "图像识别",
    ],
    "生物医药": [
        "生物医药",
        "生物",
        "医药",
        "生物医学",
        "生物技术",
        "biology",
        "biological",
        "pharmaceutical",
        "medical",
    ],
    "生物": [
        "生物",
        "生物医药",
        "生物医学",
        "生物技术",
        "医药",
        "biology",
        "biological",
        "pharmaceutical",
        "medical",
    ],
    "芯片": [
        "芯片",
        "半导体",
        "集成电路",
        "chip",
        "semiconductor",
        "integrated circuit",
    ],
}

MATURITY_ORDER = [
    "01_idea",
    "02_lab",
    "03_pilot_ready",
    "04_pilot_done",
    "05_mass_ready",
    "06_mass_done",
]


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
    result: list[str] = []

    for keyword in normalize_search_terms(keywords):
        keyword = keyword.strip()

        if not keyword:
            continue

        expansions = KEYWORD_EXPANSIONS.get(
            keyword,
            [keyword],
        )

        for item in expansions:
            if item not in result:
                result.append(item)
            if len(result) >= 8:
                return result

    return result


def _calculate_score(
    item: dict[str, Any],
    search_terms: list[str],
) -> int:
    """
    第一版简单相关度评分。

    标题命中权重最高。
    技术简介、应用领域、创新点其次。
    """
    score = 0

    title = str(item.get("title") or "").lower()
    tech_intro = str(item.get("tech_intro") or "").lower()
    source_org = str(item.get("source_org_name") or "").lower()
    application_fields = str(
        item.get("application_fields") or ""
    ).lower()
    innovation_points = str(
        item.get("innovation_points") or ""
    ).lower()

    for term in search_terms:
        term = term.lower()

        if term in title:
            score += 5

        if term in tech_intro:
            score += 3

        if term in application_fields:
            score += 3

        if term in innovation_points:
            score += 3

        if term in source_org:
            score += 1

    return score


def search_achievements(
    keywords: list[str],
    organization: str | None = None,
    min_price_wan: float | None = None,
    max_price_wan: float | None = None,
    min_maturity: str | None = None,
    limit: int = 10,
    exclude_owner_user_id: int | None = None,
) -> list[dict]:

    limit = min(max(limit, 1), 30)

    search_terms = expand_keywords(keywords)

    conditions = [
        "status = 'published'"
    ]

    params = []

    # 不把用户自己的成果推荐给自己（owner_user_id 可空：未绑定归属人的成果仍可被检索到）
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
                    OR tech_intro ILIKE %s ESCAPE E'\\\\'
                    OR source_org_name ILIKE %s ESCAPE E'\\\\'
                    OR application_fields::text ILIKE %s ESCAPE E'\\\\'
                    OR innovation_points::text ILIKE %s ESCAPE E'\\\\'
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
    # 最低价格
    # =========================

    if min_price_wan is not None:

        conditions.append(
            """
            price_min_wan IS NOT NULL
            AND price_min_wan >= %s
            """
        )

        params.append(min_price_wan)

    # =========================
    # 最高价格
    # =========================

    if max_price_wan is not None:

        conditions.append(
            """
            price_max_wan IS NOT NULL
            AND price_max_wan <= %s
            """
        )

        params.append(max_price_wan)

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

    params.append(50)

    sql = f"""
        SELECT
            id,
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
            created_at
        FROM achievement
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