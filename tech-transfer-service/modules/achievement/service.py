"""
成果模块服务层 —— 列表、详情、搜索
"""
import json
from db import get_cursor

def _parse_page_args(args):
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10
    keyword = (args.get("keyword") or "").strip()
    category = (args.get("category") or "").strip()
    maturity = (args.get("maturityLevel") or "").strip()
    return page, page_size, keyword, category, maturity


def _row_to_list_item(row):
    fields = row.get("application_fields")
    if fields and isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except (ValueError, TypeError):
            fields = []
    elif fields is None:
        fields = []

    return {
        "id": row["id"],
        "title": row["title"],
        "sourceOrgName": row.get("source_org_name"),
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "techIntro": (row.get("tech_intro") or "")[:120],
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": row.get("maturity_desc"),
        "applicationFields": fields,
        "pricingMode": row.get("pricing_mode"),
        "priceMinWan": float(row["price_min_wan"]) if row.get("price_min_wan") else None,
        "priceMaxWan": float(row["price_max_wan"]) if row.get("price_max_wan") else None,
        "viewCount": row.get("view_count", 0),
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
    }


def list_achievements(args):
    page, page_size, keyword, category, maturity = _parse_page_args(args)

    where = " WHERE a.status='published' AND a.deleted_at IS NULL"
    params = []

    if keyword:
        where += " AND (a.title LIKE %s OR a.tech_intro LIKE %s OR a.source_org_name LIKE %s)"
        like = f"%{keyword}%"
        params.extend([like, like, like])

    if category:
        where += " AND c.code=%s"
        params.append(category)

    if maturity:
        where += " AND a.maturity_level=%s"
        params.append(maturity)

    count_sql = f"""
        SELECT COUNT(*) AS c
        FROM achievement a
        LEFT JOIN achievement_category c ON a.category_id=c.id
        {where}
    """
    list_sql = f"""
        SELECT a.id, a.title, a.source_org_name, a.tech_intro,
               a.maturity_level, a.maturity_desc, a.application_fields,
               a.pricing_mode, a.price_min_wan, a.price_max_wan,
               a.view_count, a.published_at,
               c.name AS category_name, c.code AS category_code
        FROM achievement a
        LEFT JOIN achievement_category c ON a.category_id=c.id
        {where}
        ORDER BY a.published_at DESC, a.id DESC
        LIMIT %s OFFSET %s
    """

    with get_cursor() as cur:
        cur.execute(count_sql, params)
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(list_sql, params + [page_size, offset])
        rows = cur.fetchall() or []

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_list_item(r) for r in rows],
    }


def get_achievement_detail(ach_id: int):
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.*, c.name AS category_name, c.code AS category_code
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id=c.id
            WHERE a.id=%s AND a.status='published' AND a.deleted_at IS NULL
            """,
            (ach_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        cur.execute(
            """
            SELECT i.name, i.org_name, ai.sort_order, ai.contribution
            FROM achievement_inventor ai
            JOIN inventor i ON ai.inventor_id=i.id
            WHERE ai.achievement_id=%s
            ORDER BY ai.sort_order
            """,
            (ach_id,),
        )
        inventors = cur.fetchall() or []

    fields = row.get("application_fields")
    if fields and isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except (ValueError, TypeError):
            fields = []
    elif fields is None:
        fields = []

    innovations = row.get("innovation_points")
    if innovations and isinstance(innovations, str):
        try:
            innovations = json.loads(innovations)
        except (ValueError, TypeError):
            innovations = []
    elif innovations is None:
        innovations = []

    return {
        "id": row["id"],
        "title": row["title"],
        "sourceOrgName": row.get("source_org_name"),
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "techIntro": row.get("tech_intro"),
        "techRoute": row.get("tech_route"),
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": row.get("maturity_desc"),
        "applicationFields": fields,
        "innovationPoints": innovations,
        "pricingMode": row.get("pricing_mode"),
        "priceMinWan": float(row["price_min_wan"]) if row.get("price_min_wan") else None,
        "priceMaxWan": float(row["price_max_wan"]) if row.get("price_max_wan") else None,
        "contactName": row.get("contact_name"),
        "contactTitle": row.get("contact_title"),
        "contactPhone": row.get("contact_phone"),
        "contactEmail": row.get("contact_email"),
        "contactWechat": row.get("contact_wechat"),
        "viewCount": row.get("view_count", 0),
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
        "inventors": [
            {
                "name": inv["name"],
                "orgName": inv.get("org_name"),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
    }


def list_categories():
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, code, name, sort_order FROM achievement_category WHERE enabled ORDER BY sort_order"
        )
        rows = cur.fetchall() or []
    return [
        {"id": r["id"], "code": r["code"], "name": r["name"], "sortOrder": r["sort_order"]}
        for r in rows
    ]
