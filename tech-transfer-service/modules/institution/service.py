"""
统一机构库服务层（P0-1）

Architecture source: 05-data-model-design.md §8（capital 三表归并为 institution 一表）
接管 nanshan_capital（MySQL）三表数据，后端运行时零 MySQL 依赖。

对外两类消费方：
1. routes/institution.py —— 新路径 /institutions（统一机构 API）
2. modules/capital/service.py —— legacy 适配层（保持旧响应格式零差异）

可见性规则：status='active' 才对外可见（disabled 仅供管理端）。
"""

from db import get_cursor

KINDS = (
    "platform", "invest", "service",
    "university", "institute", "enterprise", "other",
)

# 平台类 keyword 命中字段（对齐旧 platform_base 五字段 LIKE）
PLATFORM_KEYWORD_FIELDS = ("name", "support_unit", "functions", "contact_person", "contact_mobile")
# 机构类 keyword 命中字段（invest 旧表两字段 / service 旧表三字段，由适配层传入）
ORG_KEYWORD_FIELDS = {
    "invest": ("name", "intro"),
    "service": ("name", "intro", "label"),
}


def _normalize_kind(kind: str) -> str:
    return (kind or "").strip().lower()


def _normalize_type_key(type_key: str) -> str:
    return (type_key or "").strip().lower()


def _query(
    page: int,
    page_size: int,
    kind: str | None,
    type_key: str = "",
    keyword: str = "",
    keyword_fields: tuple = (),
    platform_order: bool = False,
):
    """核心查询。返回 (total, rows)。

    - type_key 仅 poc/pilot 生效（platform_type_key 精确匹配）；other/all 不过滤
      ——对齐旧 capital service 的 type 行为（旧 SQL other 亦不过滤）
    - platform_order=True：platform 专用排序 serial_no ASC（对齐旧 ORDER BY serial_no）
      否则 sort_order ASC, source_pk ASC（对齐旧 ORDER BY sort_order, id）
    """
    where = ["status = 'active'"]
    params = []

    if kind:
        where.append("kind = %s")
        params.append(kind)
    if kind == "platform" and type_key in ("poc", "pilot"):
        where.append("platform_type_key = %s")
        params.append(type_key)
    if keyword and keyword_fields:
        like = f"%{keyword}%"
        parts = [f"{f} ILIKE %s" for f in keyword_fields]
        where.append("(" + " OR ".join(parts) + ")")
        params.extend([like] * len(keyword_fields))

    where_sql = " WHERE " + " AND ".join(where)

    if platform_order:
        order_sql = " ORDER BY serial_no ASC"
    else:
        order_sql = " ORDER BY sort_order ASC, source_pk ASC"

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM institution" + where_sql, params)
        total = int((cur.fetchone() or {}).get("c") or 0)
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT * FROM institution" + where_sql + order_sql + " LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []

    return total, rows


def _logo_url(file_id: str) -> str:
    fid = (file_id or "").strip()
    return f"/api/file/{fid}" if fid else ""


# ── legacy 适配层查询入口（供 modules/capital/service.py 调用） ──

def list_platform_rows(page: int, page_size: int, type_key: str, keyword: str):
    """platform 类原始行（含全部列），供 capital 适配层映射为旧响应格式"""
    return _query(
        page, page_size, "platform",
        type_key=type_key, keyword=keyword,
        keyword_fields=PLATFORM_KEYWORD_FIELDS,
        platform_order=True,
    )


def list_org_rows(kind: str, keyword_fields: tuple, page: int, page_size: int, keyword: str):
    """机构类原始行，供 capital 适配层映射为旧响应格式"""
    return _query(
        page, page_size, kind,
        keyword=keyword, keyword_fields=keyword_fields,
    )


# ── 新统一机构 API（routes/institution.py） ──

def list_institutions(page: int, page_size: int, kind: str, type_key: str, keyword: str) -> dict:
    """GET /institutions —— 统一机构列表（公开数据，仅 active）"""
    kw_fields = None
    if kind == "platform":
        kw_fields = PLATFORM_KEYWORD_FIELDS
    elif kind in ORG_KEYWORD_FIELDS:
        kw_fields = ORG_KEYWORD_FIELDS[kind]
    else:
        kw_fields = ("name", "intro", "support_unit", "label")

    total, rows = _query(
        page, page_size,
        kind if kind in KINDS else None,
        type_key=type_key, keyword=keyword,
        keyword_fields=kw_fields,
        platform_order=(kind == "platform"),
    )

    items = [_to_unified_item(r) for r in rows]
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": items,
    }


def get_institution_detail(inst_id: int) -> dict | None:
    """GET /institutions/{id} —— 统一机构详情（仅 active）"""
    with get_cursor() as cur:
        cur.execute(
            "SELECT * FROM institution WHERE id = %s AND status = 'active'",
            (inst_id,),
        )
        row = cur.fetchone()
    return _to_unified_item(row) if row else None


def _to_unified_item(row: dict) -> dict:
    """统一响应格式（camelCase，kind 专有字段按需输出）"""
    item = {
        "id": str(row["id"]),
        "kind": row["kind"],
        "name": (row.get("name") or "").strip(),
        "region": (row.get("region") or "").strip(),
        "intro": (row.get("intro") or "").strip(),
        "detailInfo": (row.get("detail_info") or "").strip(),
        "label": (row.get("label") or "").strip(),
        "logoFileId": (row.get("logo_file_id") or "").strip(),
        "logoUrl": _logo_url(row.get("logo_file_id")),
        "sortOrder": int(row.get("sort_order") or 0),
        "status": row.get("status") or "active",
    }
    if row["kind"] == "platform":
        item.update({
            "serialNo": int(row.get("serial_no") or 0),
            "platformType": (row.get("platform_type") or "").strip(),
            "platformTypeKey": (row.get("platform_type_key") or "other").strip(),
            "unit": (row.get("support_unit") or "").strip(),
            "functionText": (row.get("functions") or "").strip(),
            "contact": (row.get("contact_person") or "").strip(),
            "phone": (row.get("contact_mobile") or "").strip(),
        })
    return item
