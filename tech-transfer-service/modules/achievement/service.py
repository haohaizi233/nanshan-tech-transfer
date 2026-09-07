"""
成果模块服务层 —— 列表、详情、搜索、创建、编辑、状态机（submit/offline）

Architecture source: 04-backend-domain-design.md §4.5, 05-data-model-design.md §4,
                     06-api-design.md §7（成果组）、§5.1（状态机）
状态机（后端强校验，前端按钮仅引导）:
  draft / rejected → pending_review   (submit)
  published        → offline          (offline)
编辑仅允许 draft / rejected（published 编辑需先 offline）
"""
import json

from db import get_cursor
from modules.membership.service import assert_active_membership
from core.errors import (
    bad_request,
    conflict,
    achievement_conflict,
    achievement_forbidden,
    achievement_not_found,
)
from core.masking import mask_contact
from modules.audit.service import record as audit_record
from modules.cooperation.service import has_accepted_intent

MATURITY_LEVELS = ("01_idea", "02_lab", "03_pilot_ready", "04_pilot_done", "05_mass_ready")
PRICING_MODES = ("negotiable", "license", "transfer", "cooperation", "other")
INVENTOR_PERSON_TYPES = ("first_inventor", "co_inventor", "team_member")

TRANSITIONS = {
    "submit": {"from": ("draft", "rejected"), "to": "pending_review", "action": "achievement.submit"},
    "offline": {"from": ("published",), "to": "offline", "action": "achievement.offline"},
}

EDITABLE_STATUSES = ("draft", "rejected")


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


def _row_to_list_item(row, user_id=None):
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
        "isMine": user_id is not None and row.get("owner_user_id") == user_id,
        "platformAssisted": row.get("owner_user_id") is None,
    }


def list_achievements(args, user_id=None):
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
               a.view_count, a.published_at, a.owner_user_id,
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
        "list": [_row_to_list_item(r, user_id) for r in rows],
    }


def get_achievement_detail(ach_id: int, user_id=None):
    # 详情访问量以 SQL 自增实现，避免并发访问时发生“读-改-写”丢失。
    # 仅已发布且未删除的成果可进入该路径。
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            UPDATE achievement
            SET view_count = view_count + 1
            WHERE id=%s AND status='published' AND deleted_at IS NULL
            RETURNING view_count
            """,
            (ach_id,),
        )
        if not cur.fetchone():
            return None

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

        # 联系方式：仅发布方本人或已被接受的对接（accepted/confirmed/completed）可见明文
        contact_visible = (
            user_id is not None and row.get("owner_user_id") == user_id
        ) or has_accepted_intent(cur, "achievement", ach_id, user_id)

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

    raw_contact = {
        "contactName": row.get("contact_name"),
        "contactTitle": row.get("contact_title"),
        "contactPhone": row.get("contact_phone"),
        "contactEmail": row.get("contact_email"),
        "contactWechat": row.get("contact_wechat"),
    }
    contact = raw_contact if contact_visible else mask_contact(raw_contact)

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
        **contact,
        "viewCount": row.get("view_count", 0),
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
        "isMine": user_id is not None and row.get("owner_user_id") == user_id,
        "platformAssisted": row.get("owner_user_id") is None,
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


# ── 写操作（P0-5）──────────────────────────────────────────

def _parse_upsert_body(body: dict, partial: bool):
    """校验 AchievementUpsertRequest（openapi.yaml），返回 (db_fields, inventor_refs)

    partial=True（PATCH）：只取传入字段；False（POST）：title/maturityLevel/pricingMode 必填。
    tags / mediaFileIds：成果域无对应表（一期冻结 schema 无 achievement_tag / file_object），
    接受但忽略（打印告警），不静默落库 —— 06 §幂等同 ownerUserId 处理方式。
    """
    if not isinstance(body, dict):
        raise bad_request("请求体必须是 JSON 对象")

    fields = {}
    if "title" in body and body["title"] is not None:
        title = str(body["title"]).strip()
        if not title:
            raise bad_request("title 不能为空")
        if len(title) > 200:
            raise bad_request("title 长度不能超过 200")
        fields["title"] = title
    elif not partial:
        raise bad_request("title 必填")

    if "maturityLevel" in body and body["maturityLevel"] is not None:
        val = str(body["maturityLevel"]).strip()
        if val not in MATURITY_LEVELS:
            raise bad_request(f"maturityLevel 必须是 {MATURITY_LEVELS} 之一")
        fields["maturity_level"] = val
    elif not partial:
        raise bad_request("maturityLevel 必填")

    if "pricingMode" in body and body["pricingMode"] is not None:
        val = str(body["pricingMode"]).strip()
        if val not in PRICING_MODES:
            raise bad_request(f"pricingMode 必须是 {PRICING_MODES} 之一")
        fields["pricing_mode"] = val
    elif not partial:
        raise bad_request("pricingMode 必填")

    for key, column, max_len in (
        ("techIntro", "tech_intro", 5000),
        ("techRoute", "tech_route", 5000),
        ("maturityDesc", "maturity_desc", 255),
        ("sourceOrgName", "source_org_name", 128),
        ("contactName", "contact_name", 64),
        ("contactTitle", "contact_title", 64),
        ("contactPhone", "contact_phone", 32),
        ("contactEmail", "contact_email", 128),
        ("contactWechat", "contact_wechat", 64),
    ):
        if key in body and body[key] is not None:
            val = str(body[key]).strip()
            if len(val) > max_len:
                raise bad_request(f"{key} 长度不能超过 {max_len}")
            fields[column] = val or None

    for key in ("applicationFields", "innovationPoints"):
        if key in body and body[key] is not None:
            val = body[key]
            if not isinstance(val, list) or any(not isinstance(x, str) for x in val):
                raise bad_request(f"{key} 必须是字符串数组")
            items = [x.strip() for x in val if x.strip()]
            if any(len(x) > 128 for x in items):
                raise bad_request(f"{key} 单项长度不能超过 128")
            column = "application_fields" if key == "applicationFields" else "innovation_points"
            fields[column] = json.dumps(items, ensure_ascii=False)

    for key in ("priceMinWan", "priceMaxWan"):
        if key in body and body[key] is not None:
            try:
                val = float(body[key])
            except (ValueError, TypeError):
                raise bad_request(f"{key} 必须是数字")
            if val < 0:
                raise bad_request(f"{key} 不能为负数")
            fields["price_min_wan" if key == "priceMinWan" else "price_max_wan"] = val

    for key in ("categoryId", "orgId"):
        if key in body and body[key] is not None:
            try:
                fields["category_id" if key == "categoryId" else "org_id"] = int(body[key])
            except (ValueError, TypeError):
                raise bad_request(f"{key} 必须是整数")

    if "ownerUserId" in body:
        print(f"[achievement] WARNING: request body contains ownerUserId (ignored)")
    if body.get("tags"):
        print(f"[achievement] WARNING: tags accepted but ignored (no achievement_tag table in phase 1)")
    if body.get("mediaFileIds"):
        print(f"[achievement] WARNING: mediaFileIds accepted but ignored (file_object not in phase 1)")

    inventor_refs = body.get("inventorRefs")
    if inventor_refs is not None:
        if not isinstance(inventor_refs, list):
            raise bad_request("inventorRefs 必须是数组")
        cleaned = []
        for i, ref in enumerate(inventor_refs):
            if not isinstance(ref, dict):
                raise bad_request(f"inventorRefs[{i}] 必须是对象")
            name = str(ref.get("name") or "").strip()
            if not name:
                raise bad_request(f"inventorRefs[{i}].name 必填")
            if len(name) > 64:
                raise bad_request(f"inventorRefs[{i}].name 长度不能超过 64")
            org_name = str(ref.get("orgName") or "").strip() or None
            if org_name and len(org_name) > 128:
                raise bad_request(f"inventorRefs[{i}].orgName 长度不能超过 128")
            person_type = ref.get("personType")
            if person_type is not None and person_type not in INVENTOR_PERSON_TYPES:
                raise bad_request(
                    f"inventorRefs[{i}].personType 必须是 {INVENTOR_PERSON_TYPES} 之一"
                )
            sort_order = ref.get("sortOrder", i)
            try:
                sort_order = int(sort_order)
            except (ValueError, TypeError):
                raise bad_request(f"inventorRefs[{i}].sortOrder 必须是整数")
            cleaned.append({
                "name": name, "org_name": org_name,
                "person_type": person_type, "sort_order": sort_order,
            })
        deduped = []
        seen = set()
        for ref in cleaned:
            key = (ref["name"], ref["org_name"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ref)

    return fields, inventor_refs if inventor_refs is None else deduped


def _validate_refs(cur, fields):
    if "category_id" in fields:
        cur.execute("SELECT id FROM achievement_category WHERE id=%s", (fields["category_id"],))
        if not cur.fetchone():
            raise bad_request("categoryId 不存在")
    if "org_id" in fields:
        cur.execute("SELECT id FROM institution WHERE id=%s", (fields["org_id"],))
        if not cur.fetchone():
            raise bad_request("orgId 不存在")


def _sync_inventors(cur, ach_id: int, refs):
    """整体替换成果-完成人关联（inventor 按 name+org_name get-or-create）"""
    cur.execute("DELETE FROM achievement_inventor WHERE achievement_id=%s", (ach_id,))
    for ref in refs:
        cur.execute(
            "SELECT id FROM inventor WHERE name=%s AND (org_name IS NOT DISTINCT FROM %s)",
            (ref["name"], ref["org_name"]),
        )
        row = cur.fetchone()
        if row:
            inventor_id = row["id"]
        else:
            cur.execute(
                """
                INSERT INTO inventor (name, org_name, person_type)
                VALUES (%s, %s, %s) RETURNING id
                """,
                (ref["name"], ref["org_name"], ref["person_type"]),
            )
            inventor_id = cur.fetchone()["id"]
        cur.execute(
            """
            INSERT INTO achievement_inventor (achievement_id, inventor_id, sort_order)
            VALUES (%s, %s, %s)
            """,
            (ach_id, inventor_id, ref["sort_order"]),
        )


def _get_ach_row(cur, ach_id: int):
    cur.execute(
        "SELECT * FROM achievement WHERE id=%s AND deleted_at IS NULL",
        (ach_id,),
    )
    return cur.fetchone()


def _owner_detail(cur, ach_id: int, user_id=None):
    """owner 视角详情（写接口返回值）：不限 status，含 version/rejectReason"""
    cur.execute(
        """
        SELECT a.*, c.name AS category_name, c.code AS category_code
        FROM achievement a
        LEFT JOIN achievement_category c ON a.category_id=c.id
        WHERE a.id=%s AND a.deleted_at IS NULL
        """,
        (ach_id,),
    )
    row = cur.fetchone()
    if not row:
        return None

    cur.execute(
        """
        SELECT i.name, i.org_name, i.person_type, ai.sort_order, ai.contribution
        FROM achievement_inventor ai
        JOIN inventor i ON ai.inventor_id=i.id
        WHERE ai.achievement_id=%s
        ORDER BY ai.sort_order
        """,
        (ach_id,),
    )
    inventors = cur.fetchall() or []

    def as_list(raw):
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except (ValueError, TypeError):
                return []
        return raw or []

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
        "applicationFields": as_list(row.get("application_fields")),
        "innovationPoints": as_list(row.get("innovation_points")),
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
        "status": row.get("status"),
        "version": row.get("version"),
        "rejectReason": row.get("reject_reason"),
        "isMine": user_id is not None and row.get("owner_user_id") == user_id,
        "platformAssisted": row.get("owner_user_id") is None,
        "inventors": [
            {
                "name": inv["name"],
                "orgName": inv.get("org_name"),
                "personType": inv.get("person_type"),
                "sortOrder": inv.get("sort_order"),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
    }


def _owner_detail_public(ach_id: int, user_id=None):
    with get_cursor() as cur:
        return _owner_detail(cur, ach_id, user_id)


def create_achievement(user_id: int, user_no: str, body: dict, request_id=None):
    fields, inventor_refs = _parse_upsert_body(body, partial=False)
    if fields.get("price_min_wan") is not None and fields.get("price_max_wan") is not None:
        if fields["price_min_wan"] > fields["price_max_wan"]:
            raise bad_request("priceMinWan 不能大于 priceMaxWan")

    with get_cursor(commit=True) as cur:
        if "org_id" in fields:
            assert_active_membership(cur, user_id, fields["org_id"])
        _validate_refs(cur, fields)
        cur.execute(
            """
            INSERT INTO achievement
                (owner_user_id, created_by_user_id, title, category_id, org_id, source_org_name,
                 tech_intro, tech_route, maturity_level, maturity_desc,
                 application_fields, innovation_points, pricing_mode,
                 price_min_wan, price_max_wan, contact_name, contact_title,
                 contact_phone, contact_email, contact_wechat, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
            RETURNING id
            """,
            (
                user_id,
                user_id,
                fields.get("title"),
                fields.get("category_id"),
                fields.get("org_id"),
                fields.get("source_org_name"),
                fields.get("tech_intro"),
                fields.get("tech_route"),
                fields.get("maturity_level"),
                fields.get("maturity_desc"),
                fields.get("application_fields"),
                fields.get("innovation_points"),
                fields.get("pricing_mode"),
                fields.get("price_min_wan"),
                fields.get("price_max_wan"),
                fields.get("contact_name"),
                fields.get("contact_title"),
                fields.get("contact_phone"),
                fields.get("contact_email"),
                fields.get("contact_wechat"),
            ),
        )
        ach_id = cur.fetchone()["id"]
        if inventor_refs:
            _sync_inventors(cur, ach_id, inventor_refs)

    audit_record(
        "achievement.create", "achievement", resource_id=ach_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"title": fields.get("title")}, request_id=request_id,
    )
    return _owner_detail_public(ach_id, user_id)


def update_achievement(user_id: int, user_no: str, ach_id: int, body: dict, request_id=None):
    fields, inventor_refs = _parse_upsert_body(body, partial=True)
    if fields.get("price_min_wan") is not None and fields.get("price_max_wan") is not None:
        if fields["price_min_wan"] > fields["price_max_wan"]:
            raise bad_request("priceMinWan 不能大于 priceMaxWan")

    version = body.get("version")
    if version is None:
        raise bad_request("编辑成果必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        row = _get_ach_row(cur, ach_id)
        if not row:
            raise achievement_not_found()
        if row["owner_user_id"] != user_id:
            raise achievement_forbidden()
        if row["status"] not in EDITABLE_STATUSES:
            raise achievement_conflict(
                f"当前状态 {row['status']} 不允许编辑（仅 draft/rejected 可编辑）"
            )

        if "org_id" in fields:
            assert_active_membership(cur, user_id, fields["org_id"])
        _validate_refs(cur, fields)
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            cur.execute(
                f"UPDATE achievement SET {set_clause}, version=version+1 WHERE id=%s AND version=%s",
                list(fields.values()) + [ach_id, version],
            )
            if cur.rowcount == 0:
                raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        if inventor_refs is not None:
            _sync_inventors(cur, ach_id, inventor_refs)

    audit_record(
        "achievement.update", "achievement", resource_id=ach_id,
        actor_user_id=user_id, actor_user_no=user_no, request_id=request_id,
    )
    return _owner_detail_public(ach_id, user_id)


def _transition(user_id: int, user_no: str, ach_id: int, version, op: str, reason=None, request_id=None):
    rule = TRANSITIONS[op]
    if version is None:
        raise bad_request(f"{op} 必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        row = _get_ach_row(cur, ach_id)
        if not row:
            raise achievement_not_found()
        if row["owner_user_id"] != user_id:
            raise achievement_forbidden()
        if row["status"] not in rule["from"]:
            raise achievement_conflict(
                f"当前状态 {row['status']} 不允许 {op}"
                f"（要求 {'/'.join(rule['from'])}）"
            )
        cur.execute(
            "UPDATE achievement SET status=%s, version=version+1 WHERE id=%s AND version=%s",
            (rule["to"], ach_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

    audit_record(
        rule["action"], "achievement", resource_id=ach_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"from": row["status"], "to": rule["to"], "reason": reason or None},
        request_id=request_id,
    )
    return {"status": rule["to"]}


def submit_achievement(user_id: int, user_no: str, ach_id: int, version, request_id=None):
    return _transition(user_id, user_no, ach_id, version, "submit", request_id=request_id)


def offline_achievement(user_id: int, user_no: str, ach_id: int, version, reason=None, request_id=None):
    return _transition(user_id, user_no, ach_id, version, "offline", reason=reason, request_id=request_id)


def list_my_achievements(user_id: int, args):
    """GET /me/achievements —— 本人成果（全状态），status 可选过滤"""
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10
    status = (args.get("status") or "").strip()

    where = " WHERE a.deleted_at IS NULL AND a.owner_user_id=%s"
    params = [user_id]
    if status:
        where += " AND a.status=%s"
        params.append(status)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id=c.id
            {where}
            """,
            params,
        )
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT a.id, a.title, a.source_org_name, a.tech_intro, a.status,
                   a.maturity_level, a.maturity_desc, a.application_fields,
                   a.pricing_mode, a.price_min_wan, a.price_max_wan,
                   a.view_count, a.published_at, a.version, a.reject_reason,
                   c.name AS category_name, c.code AS category_code
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id=c.id
            {where}
            ORDER BY a.created_at DESC, a.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_my_list_item(r) for r in rows],
    }


def _my_list_item(row):
    fields = row.get("application_fields")
    if isinstance(fields, str):
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
        "status": row.get("status"),
        "version": row.get("version"),
        "rejectReason": row.get("reject_reason"),
        "isMine": True,
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
    }
