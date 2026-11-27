"""管理端机构目录增删改查与批量导入子模块（由 modules/admin/service.py 门面重导出）。"""

from __future__ import annotations

from core.contact_validation import validate_contact_way
from core.errors import (
    TT_INST_40001,
    TT_INST_40401,
    TT_INST_40901,
    BizError,
)
from db import get_cursor
from modules.admin.schemas import (
    INST_KINDS,
    PLATFORM_TYPE_KEYS,
)
from modules.audit.service import record as audit_record

INST_STATUSES = ("active", "disabled")
PLATFORM_TYPE_LABELS = {
    "poc": "概念验证中心",
    "pilot": "中小试基地",
    "other": "其他",
}

INST_EDITABLE = {
    "name": "name",
    "region": "region",
    "intro": "intro",
    "detailInfo": "detail_info",
    "label": "label",
    "logoFileId": "logo_file_id",
    "sortOrder": "sort_order",
    "userType": "user_type",
    "detailActivityId": "detail_activity_id",
    "platformType": "platform_type",
    "platformTypeKey": "platform_type_key",
    "unit": "support_unit",
    "functionText": "functions",
    "contact": "contact_person",
    "phone": "contact_mobile",
    "serialNo": "serial_no",
    "sourceStatus": "source_status",
    "orderNum": "order_num",
}


def _page_args(args, default_size=20, max_size=100):
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(max_size, int(args.get("pageSize") or default_size)))
    except (ValueError, TypeError):
        page_size = default_size
    return page, page_size


def _page_of(rows, page, page_size, total, fn):
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [fn(r) for r in rows],
    }


def _inst_admin_item(r):
    item = {
        "id": r["id"],
        "kind": r["kind"],
        "name": (r.get("name") or "").strip(),
        "region": (r.get("region") or "").strip(),
        "intro": (r.get("intro") or "").strip(),
        "detailInfo": (r.get("detail_info") or "").strip(),
        "label": (r.get("label") or "").strip(),
        "logoFileId": (r.get("logo_file_id") or "").strip(),
        "sortOrder": int(r.get("sort_order") or 0),
        "status": r.get("status") or "active",
        "userType": (r.get("user_type") or "").strip(),
        "unit": (r.get("support_unit") or "").strip(),
        "functionText": (r.get("functions") or "").strip(),
        "contact": (r.get("contact_person") or "").strip(),
        "phone": (r.get("contact_mobile") or "").strip(),
        "platformType": (r.get("platform_type") or "").strip(),
        "platformTypeKey": (r.get("platform_type_key") or "other").strip(),
        "serialNo": int(r.get("serial_no") or 0),
        "sourcePk": r.get("source_pk"),
        "sourceStatus": r.get("source_status"),
        "orderNum": r.get("order_num"),
        "sourceSite": (r.get("source_site") or "").strip(),
        "sourceApi": (r.get("source_api") or "").strip(),
        "fetchedAt": r["fetched_at"].isoformat() if r.get("fetched_at") else None,
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }
    fid = item["logoFileId"]
    item["logoUrl"] = f"/api/file/{fid}" if fid else ""
    if r["kind"] == "platform":
        item.update(
            {
                "serialNo": int(r.get("serial_no") or 0),
                "platformType": (r.get("platform_type") or "").strip(),
                "platformTypeKey": (r.get("platform_type_key") or "other").strip(),
                "unit": (r.get("support_unit") or "").strip(),
                "functionText": (r.get("functions") or "").strip(),
                "contact": (r.get("contact_person") or "").strip(),
                "phone": (r.get("contact_mobile") or "").strip(),
                "sourceStatus": r.get("source_status"),
                "orderNum": r.get("order_num"),
            }
        )
    return item


def list_institutions_admin(args) -> dict:
    """GET /admin/institutions —— 管理端列表（含 disabled，默认全量）。"""
    page, page_size = _page_args(args)
    kind = (args.get("kind") or "").strip().lower()
    type_key = (args.get("type") or "").strip().lower()
    status = (args.get("status") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where, params = [], []
    if kind in INST_KINDS:
        where.append("kind = %s")
        params.append(kind)
        if kind == "platform" and type_key in ("poc", "pilot"):
            where.append("platform_type_key = %s")
            params.append(type_key)
    if status in INST_STATUSES:
        where.append("status = %s")
        params.append(status)
    if keyword:
        like = f"%{keyword}%"
        where.append("(name ILIKE %s OR intro ILIKE %s OR label ILIKE %s OR support_unit ILIKE %s)")
        params.extend([like] * 4)

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM institution" + where_sql, params)
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT * FROM institution" + where_sql + " ORDER BY id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    return _page_of(rows, page, page_size, total, _inst_admin_item)


def get_institution_admin(inst_id: int) -> dict:
    """GET /admin/institutions/{id} —— 全状态可见（disabled 亦可查）。"""
    with get_cursor() as cur:
        cur.execute("SELECT * FROM institution WHERE id = %s", (inst_id,))
        row = cur.fetchone()
    if not row:
        code, message, status = TT_INST_40401
        raise BizError(code, message, status)
    return _inst_admin_item(row)


def _validate_inst_payload(body: dict, require_kind: bool):
    """Create/Update 共用校验。返回清洗后的字段 dict（snake_case 键）。"""
    cleaned = {}
    for camel, snake in INST_EDITABLE.items():
        if camel in body and body[camel] is not None:
            cleaned[snake] = body[camel]
    if "name" in cleaned:
        cleaned["name"] = str(cleaned["name"]).strip()
        if not cleaned["name"]:
            code, _message, status = TT_INST_40001
            raise BizError(code, "机构名称不能为空", status)
    if "contact_mobile" in cleaned:
        cleaned["contact_mobile"] = validate_contact_way(
            cleaned["contact_mobile"], required=False, field_name="联系方式"
        )

    kind = None
    if require_kind:
        kind = str(body.get("kind") or "").strip().lower()
        if kind not in INST_KINDS:
            code, _message, status = TT_INST_40001
            raise BizError(code, f"kind 必须是 {'/'.join(INST_KINDS)}", status)
    if "platform_type_key" in cleaned:
        key = str(cleaned["platform_type_key"]).strip().lower()
        if key not in PLATFORM_TYPE_KEYS:
            code, _message, status = TT_INST_40001
            raise BizError(code, f"platformTypeKey 必须是 {'/'.join(PLATFORM_TYPE_KEYS)}", status)
        cleaned["platform_type_key"] = key
        if "platform_type" not in cleaned or not str(cleaned.get("platform_type") or "").strip():
            cleaned["platform_type"] = PLATFORM_TYPE_LABELS.get(key, "")
    return cleaned, kind


def create_institution(admin_user: dict, body: dict, request_id=None) -> dict:
    """POST /admin/institutions —— 管理员录入（source_pk 留空，不与 ETL 冲突）。

    写入与审计同事务（§16）；新记录默认 status='active' 即公开可见。
    """
    cleaned, kind = _validate_inst_payload(body, require_kind=True)

    if kind == "platform":
        cleaned.setdefault("platform_type_key", "other")
        cleaned.setdefault("platform_type", PLATFORM_TYPE_LABELS.get(cleaned["platform_type_key"], ""))

    columns = ["kind", "status"]
    values: list = [kind, "active"]
    for snake in (
        "name",
        "region",
        "intro",
        "detail_info",
        "label",
        "logo_file_id",
        "sort_order",
        "user_type",
        "detail_activity_id",
        "platform_type",
        "platform_type_key",
        "support_unit",
        "functions",
        "contact_person",
        "contact_mobile",
        "serial_no",
        "source_status",
        "order_num",
    ):
        if snake in cleaned:
            columns.append(snake)
            values.append(cleaned[snake])
    if "name" not in columns:
        code, _message, status = TT_INST_40001
        raise BizError(code, "机构名称 name 必填", status)

    placeholders = ",".join(["%s"] * len(columns))
    with get_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO institution ({','.join(columns)}) VALUES ({placeholders}) RETURNING *",
            values,
        )
        row = cur.fetchone()
        audit_record(
            "institution.create",
            "institution",
            resource_id=row["id"],
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"kind": kind, "name": row["name"], "status": "active"},
            request_id=request_id,
            cur=cur,
        )
    return _inst_admin_item(row)


def update_institution(admin_user: dict, inst_id: int, body: dict, request_id=None) -> dict:
    """PATCH /admin/institutions/{id} —— 部分更新可编辑字段（id/kind/source 不可改）。

    institution 无 version 列（schema convention），不加乐观锁；
    updated_at 由 trg_institution_updated_at 触发器自动维护。
    """
    cleaned, _kind = _validate_inst_payload(body, require_kind=False)
    if not cleaned:
        code, message, status = TT_INST_40001
        raise BizError(code, "没有可更新字段", status)

    with get_cursor(commit=True) as cur:
        cur.execute("SELECT * FROM institution WHERE id = %s FOR UPDATE", (inst_id,))
        row = cur.fetchone()
        if not row:
            code, message, status = TT_INST_40401
            raise BizError(code, message, status)

        sets = ", ".join(f"{snake} = %s" for snake in cleaned)
        cur.execute(
            f"UPDATE institution SET {sets} WHERE id = %s",
            list(cleaned.values()) + [inst_id],
        )
        cur.execute("SELECT * FROM institution WHERE id = %s", (inst_id,))
        after = cur.fetchone()
        changed = {k: {"from": row.get(k), "to": after.get(k)} for k in cleaned if row.get(k) != after.get(k)}
        audit_record(
            "institution.update",
            "institution",
            resource_id=inst_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"changed": changed} if changed else {"changed": {}},
            request_id=request_id,
            cur=cur,
        )
    return _inst_admin_item(after)


def set_institution_status(admin_user: dict, inst_id: int, action: str, request_id=None) -> dict:
    """POST /admin/institutions/{id}/online|offline —— 上下架。

    action='online' → status='active'（公开可见）；'offline' → 'disabled'（仅管理端可见）。
    语义对齐既有 status enum（§5.5/5.6：不改 CHECK 约束）。幂等冲突 → 409。
    """
    to_status = "active" if action == "online" else "disabled"
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id, status, name FROM institution WHERE id = %s FOR UPDATE", (inst_id,))
        row = cur.fetchone()
        if not row:
            code, message, status = TT_INST_40401
            raise BizError(code, message, status)
        if row["status"] == to_status:
            code, message, status = TT_INST_40901
            raise BizError(code, f"机构已是 {to_status} 状态，无需重复操作", status)
        cur.execute(
            "UPDATE institution SET status = %s WHERE id = %s",
            (to_status, inst_id),
        )
        audit_record(
            f"institution.{action}",
            "institution",
            resource_id=inst_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"from": row["status"], "to": to_status, "name": row["name"]},
            request_id=request_id,
            cur=cur,
        )
    return {"status": to_status}


CAPITAL_IMPORT_KINDS = ("platform", "invest", "service")


def _to_int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalize_import_item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        code, _message, status = TT_INST_40001
        raise BizError(code, "导入行必须是对象", status)
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in CAPITAL_IMPORT_KINDS:
        code, _message, status = TT_INST_40001
        raise BizError(code, "kind 必须是 platform/invest/service", status)
    name = str(raw.get("name") or "").strip()
    if not name:
        code, _message, status = TT_INST_40001
        raise BizError(code, "机构名称 name 必填", status)
    platform_type_key = str(raw.get("platformTypeKey") or raw.get("platform_type_key") or "").strip().lower()
    if kind == "platform":
        if platform_type_key not in ("poc", "pilot", "other"):
            platform_type_key = "poc"
    else:
        platform_type_key = platform_type_key or "other"
    source_pk = raw.get("sourcePk") if raw.get("sourcePk") is not None else raw.get("source_pk")
    source_pk = _to_int_or_none(source_pk)
    sort_order = _to_int_or_none(raw.get("sortOrder") if raw.get("sortOrder") is not None else raw.get("sort_order"))
    serial_no = _to_int_or_none(raw.get("serialNo") if raw.get("serialNo") is not None else raw.get("serial_no"))
    source_status = _to_int_or_none(
        raw.get("sourceStatus") if raw.get("sourceStatus") is not None else raw.get("source_status")
    )
    order_num = _to_int_or_none(raw.get("orderNum") if raw.get("orderNum") is not None else raw.get("order_num"))
    return {
        "kind": kind,
        "name": name,
        "region": str(raw.get("region") or "").strip(),
        "intro": str(raw.get("intro") or "").strip(),
        "label": str(raw.get("label") or "").strip(),
        "unit": str(raw.get("unit") or raw.get("support_unit") or "").strip(),
        "functionText": str(raw.get("functionText") or raw.get("functions") or raw.get("platform_fun") or "").strip(),
        "contact": str(raw.get("contact") or raw.get("contact_person") or "").strip(),
        "phone": str(raw.get("phone") or raw.get("contact_mobile") or "").strip(),
        "platformTypeKey": platform_type_key,
        "platformType": str(raw.get("platformType") or raw.get("platform_type") or "").strip(),
        "sortOrder": sort_order or 0,
        "sourcePk": source_pk,
        "status": "active" if str(raw.get("status") or "active").strip().lower() != "disabled" else "disabled",
        "serialNo": serial_no,
        "sourceStatus": source_status,
        "orderNum": order_num,
        "sourceSite": str(raw.get("sourceSite") or raw.get("source_site") or "").strip(),
        "sourceApi": str(raw.get("sourceApi") or raw.get("source_api") or "").strip(),
        "fetchedAt": str(raw.get("fetchedAt") or raw.get("fetched_at") or "").strip() or None,
        "logoFileId": str(raw.get("logoFileId") or raw.get("logo_file_id") or "").strip(),
        "detailInfo": str(raw.get("detailInfo") or raw.get("detail_info") or "").strip(),
        "userType": str(raw.get("userType") or raw.get("user_type") or "").strip(),
    }


def import_institutions(admin_user: dict, body: dict, request_id=None) -> dict:
    """Idempotent capital-resource upsert keyed by (kind, source_pk) or (kind, name)."""
    items = body.get("items") if isinstance(body, dict) else None
    if not isinstance(items, list) or not items:
        code, _message, status = TT_INST_40001
        raise BizError(code, "items 必须是非空数组", status)
    if len(items) > 500:
        code, _message, status = TT_INST_40001
        raise BizError(code, "单次最多导入 500 条", status)

    created = 0
    updated = 0
    results = []
    with get_cursor(commit=True) as cur:
        for raw in items:
            item = _normalize_import_item(raw)
            existing = None
            if item["sourcePk"] is not None:
                cur.execute(
                    "SELECT id FROM institution WHERE kind=%s AND source_pk=%s",
                    (item["kind"], item["sourcePk"]),
                )
                existing = cur.fetchone()
            if existing is None:
                cur.execute(
                    "SELECT id FROM institution WHERE kind=%s AND name=%s ORDER BY id LIMIT 1",
                    (item["kind"], item["name"]),
                )
                existing = cur.fetchone()
            values = (
                item["name"],
                item["region"],
                item["intro"],
                item["label"],
                item["unit"],
                item["functionText"],
                item["contact"],
                item["phone"],
                item["platformTypeKey"],
                item["platformType"],
                item["sortOrder"],
                item["status"],
                item["sourcePk"],
                item["serialNo"],
                item["sourceStatus"],
                item["orderNum"],
                item["sourceSite"],
                item["sourceApi"],
                item["fetchedAt"],
                item["logoFileId"],
                item["detailInfo"],
                item["userType"],
            )
            if existing:
                cur.execute(
                    """
                    UPDATE institution SET
                        name=%s, region=%s, intro=%s, label=%s,
                        support_unit=%s, functions=%s, contact_person=%s, contact_mobile=%s,
                        platform_type_key=%s, platform_type=%s, sort_order=%s,
                        status=%s, source_pk=COALESCE(%s, source_pk),
                        serial_no=COALESCE(%s, serial_no),
                        source_status=COALESCE(%s, source_status),
                        order_num=COALESCE(%s, order_num),
                        source_site=COALESCE(NULLIF(%s, ''), source_site),
                        source_api=COALESCE(NULLIF(%s, ''), source_api),
                        fetched_at=COALESCE(%s::timestamptz, fetched_at),
                        logo_file_id=COALESCE(NULLIF(%s, ''), logo_file_id),
                        detail_info=COALESCE(NULLIF(%s, ''), detail_info),
                        user_type=COALESCE(NULLIF(%s, ''), user_type)
                    WHERE id=%s
                    RETURNING id
                    """,
                    values + (existing["id"],),
                )
                row_id = cur.fetchone()["id"]
                updated += 1
                action = "update"
            else:
                cur.execute(
                    """
                    INSERT INTO institution (
                        kind, name, region, intro, label, support_unit, functions,
                        contact_person, contact_mobile, platform_type_key, platform_type,
                        sort_order, status, source_pk,
                        serial_no, source_status, order_num, source_site, source_api, fetched_at,
                        logo_file_id, detail_info, user_type
                    ) VALUES (
                        %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                        %s,%s,%s,%s,%s,%s::timestamptz,
                        %s,%s,%s
                    )
                    RETURNING id
                    """,
                    (item["kind"],) + values,
                )
                row_id = cur.fetchone()["id"]
                created += 1
                action = "create"
            # Include the canonical row so the admin UI can reconcile only the
            # affected rows after an import instead of refetching the table.
            results.append({**item, "id": row_id, "action": action})
        audit_record(
            "institution.import",
            "institution",
            resource_id=None,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"created": created, "updated": updated, "total": len(items)},
            request_id=request_id,
            cur=cur,
        )
    return {"created": created, "updated": updated, "total": len(items), "list": results}


def delete_institution(admin_user: dict, inst_id: int, request_id=None) -> dict:
    """Hard-delete a capital/institution row when it is not referenced by memberships or content."""
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT id, name, kind FROM institution WHERE id=%s FOR UPDATE", (inst_id,))
        row = cur.fetchone()
        if not row:
            code, message, status = TT_INST_40401
            raise BizError(code, message, status)
        # 引用检查：任何子表存在引用即拒绝硬删，列出引用来源便于人工处理。
        references: list[str] = []
        cur.execute("SELECT 1 FROM achievement WHERE org_id=%s AND deleted_at IS NULL LIMIT 1", (inst_id,))
        if cur.fetchone():
            references.append("achievement.org_id")
        cur.execute("SELECT 1 FROM demand WHERE org_id=%s AND deleted_at IS NULL LIMIT 1", (inst_id,))
        if cur.fetchone():
            references.append("demand.org_id")
        cur.execute("SELECT 1 FROM organization_membership WHERE org_id=%s LIMIT 1", (inst_id,))
        if cur.fetchone():
            references.append("organization_membership.org_id")
        # organization_application 通过 requested_name 关联机构名而非 org_id 外键，
        # 这里按名称匹配兜底，避免漏掉待审/已审的入驻申请。
        cur.execute(
            """
            SELECT 1 FROM organization_application a
            JOIN institution i ON i.id = %s AND i.name = a.requested_name
            WHERE a.status IN ('pending', 'approved') LIMIT 1
            """,
            (inst_id,),
        )
        if cur.fetchone():
            references.append("organization_application (by name)")
        if references:
            code, message, status = TT_INST_40901
            raise BizError(
                code,
                f"该机构仍被以下表引用，不能删除，请改为下架：{', '.join(references)}",
                status,
            )
        cur.execute("DELETE FROM institution WHERE id=%s", (inst_id,))
        audit_record(
            "institution.delete",
            "institution",
            resource_id=inst_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"name": row["name"], "kind": row["kind"]},
            request_id=request_id,
            cur=cur,
        )
    return {"id": inst_id, "deleted": True}
