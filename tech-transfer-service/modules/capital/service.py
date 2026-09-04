"""
capital service — 资本对接只读接口（legacy 适配层）

Architecture source: 04-backend-domain-design.md §capital
Source: extracted from app.py inline code (Phase A)

P0-1 改造：数据源从 nanshan_capital（MySQL）三表切换为 tech_transfer.institution（PG），
对外函数签名与响应格式保持不变（routes/capital.py 零改动），由
tools/baseline 工具对 legacy_capital_baseline.json 做 diff 验证。
切换后后端运行时不再依赖 MySQL。
"""

from modules.institution.service import list_platform_rows, list_org_rows


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
        "name": (row.get("name") or "").strip(),
        "platformType": ptype,
        "platformTypeKey": row.get("platform_type_key") or _map_type_key(ptype),
        "unit": (row.get("support_unit") or "").strip(),
        "functionText": (row.get("functions") or "").strip(),
        "contact": (row.get("contact_person") or "").strip(),
        "phone": (row.get("contact_mobile") or "").strip(),
    }


def _row_to_org_item(row: dict, kind: str) -> dict:
    return {
        "id": str(row.get("source_pk") or row.get("id") or ""),
        "name": (row.get("name") or "").strip(),
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
    # type 行为对齐旧实现：poc/pilot 过滤，other/all 不过滤（institution service 内处理）
    total, rows = list_platform_rows(page, page_size, type_key, keyword)
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_platform_item(r) for r in rows],
    }


def list_orgs(kind: str, keyword_fields: list, page: int, page_size: int, keyword: str):
    # kind 转换：legacy 路由传 "invest"/"bank"，institution 表 kind=invest/service
    table_kind = "invest" if kind == "invest" else "service"
    # 旧 MySQL 列名 -> institution 列名映射（org_name 已归一为 name）
    field_map = {"org_name": "name", "intro": "intro", "label": "label"}
    mapped = tuple(field_map.get(f, f) for f in keyword_fields)
    total, rows = list_org_rows(table_kind, mapped, page, page_size, keyword)
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_org_item(r, kind) for r in rows],
    }
