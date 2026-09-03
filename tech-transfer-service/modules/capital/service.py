"""
capital service — 资本对接只读查询

Architecture source: 04-backend-domain-design.md §capital
Source: extracted from app.py inline code (Phase A)

Tables: nanshan_capital.platform_base, .featured_invest_org, .ip_service_org
Note: Phase B will migrate these tables to tech_transfer schema.
"""

import pymysql

from config import CAPITAL_DB_HOST, CAPITAL_DB_PORT, CAPITAL_DB_USER, CAPITAL_DB_PASSWORD

CAPITAL_DB_CONFIG = {
    "host": CAPITAL_DB_HOST,
    "port": CAPITAL_DB_PORT,
    "user": CAPITAL_DB_USER,
    "password": CAPITAL_DB_PASSWORD,
    "database": "nanshan_capital",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}


def _get_capital_conn():
    return pymysql.connect(**CAPITAL_DB_CONFIG)


def _map_type_key(platform_type: str) -> str:
    t = (platform_type or "").strip()
    if "概念验证" in t:
        return "poc"
    if "中小试" in t or "中试" in t:
        return "pilot"
    return "other"


def _row_to_platform_item(row: dict) -> dict:
    ptype = (row.get("platform_type") or "").strip()
    return {
        "id": str(row.get("serial_no") or row.get("id") or ""),
        "serialNo": int(row.get("serial_no") or 0),
        "name": (row.get("platform_name") or "").strip(),
        "platformType": ptype,
        "platformTypeKey": _map_type_key(ptype),
        "unit": (row.get("support_unit") or "").strip(),
        "functionText": (row.get("platform_fun") or "").strip(),
        "contact": (row.get("contact_person") or "").strip(),
        "phone": (row.get("contact_mobile") or "").strip(),
    }


def _row_to_org_item(row: dict, kind: str) -> dict:
    return {
        "id": str(row.get("id") or row.get("account") or ""),
        "name": (row.get("org_name") or "").strip(),
        "intro": (row.get("intro") or "").strip(),
        "detailInfo": (row.get("detail_info") or "").strip(),
        "label": (row.get("label") or "").strip(),
        "logoFileId": (row.get("logo_file_id") or "").strip(),
        "logoUrl": _logo_url(row.get("logo_file_id") or ""),
        "kind": kind,
        "sortOrder": int(row.get("sort_order") or 0),
    }


def _logo_url(file_id: str) -> str:
    fid = (file_id or "").strip()
    if not fid:
        return ""
    return f"/api/file/{fid}"


def list_platforms(page: int, page_size: int, type_key: str, keyword: str):
    where_sql = " WHERE 1=1"
    params = []
    if type_key == "poc":
        where_sql += " AND platform_type LIKE %s"
        params.append("%概念验证%")
    elif type_key == "pilot":
        where_sql += " AND (platform_type LIKE %s OR platform_type LIKE %s)"
        params.extend(["%中小试%", "%中试%"])
        where_sql += " AND platform_type NOT LIKE %s"
        params.append("%概念验证%")
    if keyword:
        where_sql += " AND (platform_name LIKE %s OR support_unit LIKE %s OR platform_fun LIKE %s OR contact_person LIKE %s OR contact_mobile LIKE %s)"
        like = f"%{keyword}%"
        params.extend([like, like, like, like, like])

    count_sql = "SELECT COUNT(*) AS c FROM platform_base" + where_sql
    list_sql = "SELECT id, serial_no, platform_name, platform_type, support_unit, platform_fun, contact_person, contact_mobile FROM platform_base" + where_sql + " ORDER BY serial_no ASC LIMIT %s OFFSET %s"

    conn = _get_capital_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = int((cur.fetchone() or {}).get("c") or 0)
            offset = (page - 1) * page_size
            cur.execute(list_sql, params + [page_size, offset])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_platform_item(r) for r in rows],
    }


def list_orgs(table: str, kind: str, keyword_fields: list, page: int, page_size: int, keyword: str):
    where_sql = " WHERE 1=1"
    params = []
    if keyword:
        like = f"%{keyword}%"
        parts = [f"{f} LIKE %s" for f in keyword_fields]
        where_sql += " AND (" + " OR ".join(parts) + ")"
        params.extend([like] * len(keyword_fields))

    count_sql = f"SELECT COUNT(*) AS c FROM {table}" + where_sql
    list_sql = f"SELECT * FROM {table}" + where_sql + " ORDER BY sort_order ASC, id ASC LIMIT %s OFFSET %s"

    conn = _get_capital_conn()
    try:
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = int((cur.fetchone() or {}).get("c") or 0)
            offset = (page - 1) * page_size
            cur.execute(list_sql, params + [page_size, offset])
            rows = cur.fetchall() or []
    finally:
        conn.close()

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_org_item(r, kind) for r in rows],
    }
