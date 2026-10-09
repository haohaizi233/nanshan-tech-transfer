"""
成果模块服务层 —— 列表、详情、搜索、创建、编辑、状态机（submit/offline）

Architecture source: 04-backend-domain-design.md §4.5, 05-data-model-design.md §4,
                     06-api-design.md §7（成果组）、§5.1（状态机）
状态机（后端强校验，前端按钮仅引导）:
  draft / rejected / offline → pending_review   (submit)
  published        → offline          (offline)
编辑允许 draft / rejected / offline（published 编辑需先 offline 再改）
"""
import json

from db import get_cursor
from modules.membership.service import assert_active_membership, resolve_content_organization
from core.contact_validation import validate_email, validate_phone
from core.errors import (
    bad_request,
    conflict,
    achievement_conflict,
    achievement_forbidden,
    achievement_not_found,
)
from core.masking import mask_contact
from modules.audit.service import record as audit_record
from modules.cooperation.service import can_access_target, has_accepted_intent, is_accepted_dock_party
from modules.achievement.maturity import (
    MATURITY_LABELS,
    MATURITY_LEVELS,
    resolve_maturity_desc,
)
from modules.achievement.content import parse_content_payload, sync_content, load_content

PRICING_MODES = ("negotiable", "license", "transfer", "cooperation", "other")


def _parse_cooperation_capacity(body, fields, partial=False):
    if "cooperationPolicy" in body:
        policy = body["cooperationPolicy"]
        if policy not in ("parallel", "exclusive"):
            raise bad_request("cooperationPolicy 必须是 parallel 或 exclusive")
        fields["cooperation_policy"] = policy
    if "cooperationCapacity" in body:
        capacity = body["cooperationCapacity"]
        if capacity is None or capacity == "":
            fields["cooperation_capacity"] = None
            fields["cooperation_remaining"] = None
        else:
            try:
                capacity = int(capacity)
            except (TypeError, ValueError):
                raise bad_request("cooperationCapacity 必须是正整数或空（不限量）")
            if capacity < 1:
                raise bad_request("cooperationCapacity 必须大于 0")
            if fields.get("cooperation_policy") == "exclusive" and capacity != 1:
                raise bad_request("exclusive 仅允许 1 个对接名额")
            fields["cooperation_capacity"] = capacity
            # 创建时直接置满；编辑时由 update_achievement 按 delta 调整 remaining，
            # 保留已消耗名额，防止 owner 编辑下线内容时绕过 accept/release 状态机恢复名额。
            if not partial:
                fields["cooperation_remaining"] = capacity
INVENTOR_PERSON_TYPES = ("first_inventor", "co_inventor", "team_member")

TRANSITIONS = {
    "submit": {"from": ("draft", "rejected", "offline"), "to": "pending_review", "action": "achievement.submit"},
    "offline": {"from": ("published",), "to": "offline", "action": "achievement.offline"},
}

EDITABLE_STATUSES = ("draft", "rejected", "offline")


def _org_cert_payload(row):
    org_id = row.get("org_id")
    return {"orgId": org_id, "orgCertified": org_id is not None}


def _display_source_org(row):
    if row.get("org_id"):
        return row.get("certified_org_name") or row.get("source_org_name")
    return row.get("source_org_name")


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
    industry_id = (args.get("industryId") or "").strip()
    return page, page_size, keyword, category, maturity, industry_id


def _row_to_list_item(row, user_id=None):
    fields = row.get("application_fields")
    if fields and isinstance(fields, str):
        try:
            fields = json.loads(fields)
        except (ValueError, TypeError):
            fields = []
    elif fields is None:
        fields = []

    cover_id = row.get("cover_file_id")
    industries = row.get("industries") or []
    if isinstance(industries, str):
        try:
            industries = json.loads(industries)
        except (ValueError, TypeError):
            industries = []
    return {
        "id": row["id"],
        "title": row["title"],
        "sourceOrgName": _display_source_org(row),
        "orgId": row.get("org_id"),
        "orgCertified": row.get("org_id") is not None,
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "industries": industries,
        "techIntro": (row.get("tech_intro") or "")[:120],
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": resolve_maturity_desc(row.get("maturity_level"), row.get("maturity_desc")),
        "applicationFields": fields,
        "pricingMode": row.get("pricing_mode"),
        "priceMinWan": float(row["price_min_wan"]) if row.get("price_min_wan") else None,
        "priceMaxWan": float(row["price_max_wan"]) if row.get("price_max_wan") else None,
        "viewCount": row.get("view_count", 0),
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
        "isMine": user_id is not None and row.get("owner_user_id") == user_id,
        "platformAssisted": row.get("owner_user_id") is None,
        "cover": ({
            "fileId": cover_id,
            "url": f"{__import__('config').settings.MEDIA_BASE_URL.rstrip('/')}/{cover_id}",
            "thumbnailUrl": f"{__import__('config').settings.MEDIA_BASE_URL.rstrip('/')}/{cover_id}?variant=thumbnail",
        } if cover_id else None),
    }


def list_achievements(args, user_id=None):
    page, page_size, keyword, category, maturity, industry_id = _parse_page_args(args)

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

    if industry_id:
        try:
            industry_id = int(industry_id)
        except (TypeError, ValueError):
            raise bad_request("industryId 必须是整数")
        where += " AND EXISTS (SELECT 1 FROM achievement_industry ai WHERE ai.achievement_id=a.id AND ai.industry_id=%s)"
        params.append(industry_id)

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
               a.view_count, a.published_at, a.owner_user_id, a.org_id,
               o.name AS certified_org_name,
               c.name AS category_name, c.code AS category_code,
               COALESCE((SELECT jsonb_agg(jsonb_build_object('id',i.id,'code',i.code,'name',i.name,'parentId',i.parent_id) ORDER BY ai.sort_order,ai.id)
                         FROM achievement_industry ai JOIN industry i ON i.id=ai.industry_id AND i.enabled
                         WHERE ai.achievement_id=a.id), '[]'::jsonb) AS industries,
               (SELECT am.file_id FROM achievement_media am JOIN file_object fo ON fo.id=am.file_id AND fo.status='active' WHERE am.achievement_id=a.id AND am.media_role='cover' ORDER BY am.sort_order,am.id LIMIT 1) AS cover_file_id
        FROM achievement a
        LEFT JOIN achievement_category c ON a.category_id=c.id
        LEFT JOIN institution o ON a.org_id=o.id
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
    # 已发布内容对登录用户可见；未发布内容仅 owner 或已接受对接的双方可见。
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT a.*, c.name AS category_name, c.code AS category_code,
                   o.name AS certified_org_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id=c.id
            LEFT JOIN institution o ON a.org_id=o.id
            WHERE a.id=%s AND a.deleted_at IS NULL
            """,
            (ach_id,),
        )
        row = cur.fetchone()
        if not row:
            return None

        dock_party = False
        if row.get("status") != "published" and row.get("owner_user_id") != user_id:
            dock_party = is_accepted_dock_party(cur, "achievement", ach_id, user_id)
        if not can_access_target(
            user_id,
            owner_user_id=row.get("owner_user_id"),
            status=row.get("status"),
            is_dock_party=dock_party,
        ):
            return None

        if row.get("status") == "published":
            cur.execute(
                """
                UPDATE achievement
                SET view_count = view_count + 1
                WHERE id=%s AND status='published' AND deleted_at IS NULL
                RETURNING view_count
                """,
                (ach_id,),
            )
            updated = cur.fetchone()
            if updated:
                row = dict(row)
                row["view_count"] = updated["view_count"]

        # 联系方式：仅发布方本人或已被接受的对接（accepted/confirmed/completed）可见明文
        contact_visible = (
            user_id is not None and row.get("owner_user_id") == user_id
        ) or has_accepted_intent(cur, "achievement", ach_id, user_id)

        cur.execute(
            """
            SELECT i.name, i.org_name, i.department, i.title, i.bio, i.homepage_url, i.avatar_file_id, ai.sort_order, ai.contribution
            FROM achievement_inventor ai
            JOIN inventor i ON ai.inventor_id=i.id
            WHERE ai.achievement_id=%s
            ORDER BY ai.sort_order
            """,
            (ach_id,),
        )
        inventors = cur.fetchall() or []
        dynamic_content = load_content(cur, ach_id)

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
        "titleEn": row.get("title_en"),
        "achievementKind": row.get("achievement_kind") or "technology",
        "sourceOrgName": _display_source_org(row),
        "orgId": row.get("org_id"),
        "orgCertified": row.get("org_id") is not None,
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "techIntro": row.get("tech_intro"),
        "techRoute": row.get("tech_route"),
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": resolve_maturity_desc(row.get("maturity_level"), row.get("maturity_desc")),
        "applicationFields": fields,
        "innovationPoints": innovations,
        "pricingMode": row.get("pricing_mode"),
        "priceMinWan": float(row["price_min_wan"]) if row.get("price_min_wan") else None,
        "priceMaxWan": float(row["price_max_wan"]) if row.get("price_max_wan") else None,
        **contact,
        "viewCount": row.get("view_count", 0),
        "publishedAt": row.get("published_at").strftime("%Y-%m-%d") if row.get("published_at") else None,
        "status": row.get("status"),
        "version": row.get("version"),
        "isMine": user_id is not None and row.get("owner_user_id") == user_id,
        "platformAssisted": row.get("owner_user_id") is None,
        "inventors": [
            {
                "name": inv["name"],
                "orgName": inv.get("org_name"),
                "department": inv.get("department"),
                "title": inv.get("title"),
                "bio": inv.get("bio"),
                "homepageUrl": inv.get("homepage_url"),
                "avatarFileId": inv.get("avatar_file_id"),
                "avatarUrl": (f"{__import__('config').settings.MEDIA_BASE_URL.rstrip('/')}/{inv['avatar_file_id']}" if inv.get("avatar_file_id") else None),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
        **dynamic_content,
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


def list_industries():
    """读取平台配置的产业目录；不返回停用项，也不替旧成果虚构产业标签。"""
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, code, name, parent_id, sort_order FROM industry WHERE enabled ORDER BY parent_id NULLS FIRST, sort_order, id"
        )
        rows = cur.fetchall() or []
    return [
        {"id": row["id"], "code": row["code"], "name": row["name"], "parentId": row["parent_id"], "sortOrder": row["sort_order"]}
        for row in rows
    ]


# ── 写操作（P0-5）──────────────────────────────────────────

def _parse_upsert_body(body: dict, partial: bool):
    """校验 AchievementUpsertRequest（openapi.yaml），返回 (db_fields, inventor_refs)

    partial=True（PATCH）：只取传入字段；False（POST）：只要求 title。
    sections / patents / links / media / inventors / industryIds 由内容子模型处理，
    基础字段与动态内容在同一事务内同步，避免出现“DTO 接收但未落库”的假成功。
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

    if "pricingMode" in body and body["pricingMode"] is not None:
        val = str(body["pricingMode"]).strip()
        if val not in PRICING_MODES:
            raise bad_request(f"pricingMode 必须是 {PRICING_MODES} 之一")
        fields["pricing_mode"] = val

    for key, column, max_len in (
        ("titleEn", "title_en", 500),
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

    if "achievementKind" in body:
        kind = str(body.get("achievementKind") or "").strip()
        if kind not in ("technology", "patent", "project", "product", "other"):
            raise bad_request("achievementKind 无效")
        fields["achievement_kind"] = kind

    if fields.get("contact_phone"):
        fields["contact_phone"] = validate_phone(fields["contact_phone"], field_name="联系电话")
    if fields.get("contact_email"):
        fields["contact_email"] = validate_email(fields["contact_email"], field_name="联系邮箱")

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

    if fields.get("maturity_level") and not fields.get("maturity_desc"):
        fields["maturity_desc"] = MATURITY_LABELS.get(fields["maturity_level"])

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
            extra = {}
            for api_key, column, maximum in (
                ("department", "department", 128), ("title", "title", 128),
                ("bio", "bio", 10000), ("phone", "phone", 32), ("email", "email", 128),
                ("homepageUrl", "homepage_url", 2048),
            ):
                value = ref.get(api_key)
                if value is not None:
                    value = str(value).strip() or None
                    if value and len(value) > maximum:
                        raise bad_request(f"inventorRefs[{i}].{api_key} 长度不能超过 {maximum}")
                    extra[column] = value
            if extra.get("phone"):
                extra["phone"] = validate_phone(extra["phone"], field_name="完成人电话")
            if extra.get("email"):
                extra["email"] = validate_email(extra["email"], field_name="完成人邮箱")
            if extra.get("homepage_url"):
                # 防止 javascript: 等危险 scheme 存入公开成果详情
                from urllib.parse import urlparse
                parsed = urlparse(extra["homepage_url"])
                if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                    raise bad_request(f"inventorRefs[{i}].homepageUrl 必须是 http(s) URL")
            if ref.get("avatarFileId") is not None:
                try:
                    extra["avatar_file_id"] = int(ref["avatarFileId"])
                except (TypeError, ValueError):
                    raise bad_request(f"inventorRefs[{i}].avatarFileId 必须是整数")
            cleaned.append({
                "name": name, "org_name": org_name,
                "person_type": person_type, "sort_order": sort_order, **extra,
            })
        deduped = []
        seen = set()
        for ref in cleaned:
            key = (ref["name"], ref["org_name"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(ref)

    _parse_cooperation_capacity(body, fields, partial=partial)
    return fields, inventor_refs if inventor_refs is None else deduped, parse_content_payload(body)


def _validate_refs(cur, fields):
    if "category_id" in fields:
        cur.execute("SELECT id FROM achievement_category WHERE id=%s", (fields["category_id"],))
        if not cur.fetchone():
            raise bad_request("categoryId 不存在")
    if "org_id" in fields:
        cur.execute("SELECT id, name FROM institution WHERE id=%s", (fields["org_id"],))
        institution = cur.fetchone()
        if not institution:
            raise bad_request("orgId 不存在")
        # 展示文本与认证机构分离：sourceOrgName 用户自填原样保留；
        # 仅在调用方未提供时回填所选机构名（管理端只选机构的场景）。
        if "source_org_name" not in fields:
            fields["source_org_name"] = institution["name"]


def _sync_inventors(cur, ach_id: int, refs, user_id: int | None = None):
    """整体替换成果-完成人关联（inventor 按 name+org_name get-or-create）"""
    avatar_ids = [ref.get("avatar_file_id") for ref in refs if ref.get("avatar_file_id")]
    if avatar_ids and user_id is not None:
        cur.execute("SELECT id FROM file_object WHERE created_by=%s AND status='active' AND id = ANY(%s)", (user_id, avatar_ids))
        if {int(row["id"]) for row in cur.fetchall()} != set(avatar_ids):
            raise bad_request("完成人头像不存在、已删除或不属于当前用户")
    cur.execute("DELETE FROM achievement_inventor WHERE achievement_id=%s", (ach_id,))
    for ref in refs:
        cur.execute(
            "SELECT id FROM inventor WHERE name=%s AND (org_name IS NOT DISTINCT FROM %s)",
            (ref["name"], ref["org_name"]),
        )
        row = cur.fetchone()
        if row:
            inventor_id = row["id"]
            enrich = {key: value for key, value in ref.items() if key in {"person_type", "department", "title", "bio", "phone", "email", "homepage_url", "avatar_file_id"} and value is not None}
            if enrich:
                assignments = ", ".join(
                    f"{column}=COALESCE(%s, {column})" if column == "avatar_file_id" else f"{column}=COALESCE(NULLIF(%s, ''), {column})"
                    for column in enrich
                )
                cur.execute(f"UPDATE inventor SET {assignments}, updated_at=CURRENT_TIMESTAMP WHERE id=%s", list(enrich.values()) + [inventor_id])
        else:
            cur.execute(
                """
                INSERT INTO inventor (name, org_name, person_type, department, title, bio, phone, email, homepage_url, avatar_file_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id
                """,
                (ref["name"], ref["org_name"], ref["person_type"], ref.get("department"), ref.get("title"), ref.get("bio"), ref.get("phone"), ref.get("email"), ref.get("homepage_url"), ref.get("avatar_file_id")),
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
        SELECT i.name, i.org_name, i.person_type, i.department, i.title, i.bio, i.homepage_url, i.avatar_file_id, ai.sort_order, ai.contribution
        FROM achievement_inventor ai
        JOIN inventor i ON ai.inventor_id=i.id
        WHERE ai.achievement_id=%s
        ORDER BY ai.sort_order
        """,
        (ach_id,),
    )
    inventors = cur.fetchall() or []
    dynamic_content = load_content(cur, ach_id)

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
        "titleEn": row.get("title_en"),
        "achievementKind": row.get("achievement_kind") or "technology",
        "sourceOrgName": _display_source_org(row),
        "orgId": row.get("org_id"),
        "orgCertified": row.get("org_id") is not None,
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "techIntro": row.get("tech_intro"),
        "techRoute": row.get("tech_route"),
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": resolve_maturity_desc(row.get("maturity_level"), row.get("maturity_desc")),
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
                "department": inv.get("department"),
                "title": inv.get("title"),
                "bio": inv.get("bio"),
                "homepageUrl": inv.get("homepage_url"),
                "avatarFileId": inv.get("avatar_file_id"),
                "avatarUrl": (f"{__import__('config').settings.MEDIA_BASE_URL.rstrip('/')}/{inv['avatar_file_id']}" if inv.get("avatar_file_id") else None),
                "sortOrder": inv.get("sort_order"),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
        **dynamic_content,
    }


def _owner_detail_public(ach_id: int, user_id=None):
    with get_cursor() as cur:
        return _owner_detail(cur, ach_id, user_id)


def create_achievement(
    user_id: int,
    user_no: str,
    body: dict,
    request_id=None,
    source_import_item_id: int | None = None,
    media_owner_user_id: int | None = None,
):
    fields, inventor_refs, content = _parse_upsert_body(body, partial=False)
    if fields.get("price_min_wan") is not None and fields.get("price_max_wan") is not None:
        if fields["price_min_wan"] > fields["price_max_wan"]:
            raise bad_request("priceMinWan 不能大于 priceMaxWan")

    with get_cursor(commit=True) as cur:
        selected_org_id = resolve_content_organization(cur, user_id, fields.get("org_id"))
        if selected_org_id is not None:
            fields["org_id"] = selected_org_id
        _validate_refs(cur, fields)
        cur.execute(
            """
            INSERT INTO achievement
                (owner_user_id, created_by_user_id, title, category_id, org_id, source_org_name,
                 tech_intro, tech_route, maturity_level, maturity_desc, achievement_kind, title_en,
                 application_fields, innovation_points, pricing_mode,
                 price_min_wan, price_max_wan, contact_name, contact_title,
                 contact_phone, contact_email, contact_wechat, source_import_item_id, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
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
                fields.get("achievement_kind", "technology"),
                fields.get("title_en"),
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
                source_import_item_id,
            ),
        )
        ach_id = cur.fetchone()["id"]
        if inventor_refs:
            _sync_inventors(cur, ach_id, inventor_refs, user_id)
        # 导入候选媒体由执行导入的账号持有；平台管理员审核确认时，
        # 只对这类有来源追溯的内部导入记录沿用其文件归属。
        sync_content(cur, ach_id, media_owner_user_id or user_id, content)

        audit_record(
            "achievement.create", "achievement", resource_id=ach_id,
            actor_user_id=user_id, actor_user_no=user_no,
            details={"title": fields.get("title")}, request_id=request_id, cur=cur,
        )

    return _owner_detail_public(ach_id, user_id)


def update_achievement(user_id: int, user_no: str, ach_id: int, body: dict, request_id=None):
    fields, inventor_refs, content = _parse_upsert_body(body, partial=True)
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
                f"当前状态 {row['status']} 不允许编辑（仅 draft/rejected/offline 可编辑）"
            )

        # 编辑 cooperationCapacity 时按 delta 调整 remaining，保留已消耗名额
        if "cooperation_capacity" in fields:
            new_cap = fields["cooperation_capacity"]
            old_cap = row.get("cooperation_capacity")
            old_rem = row.get("cooperation_remaining")
            if new_cap is None:
                fields["cooperation_remaining"] = None
            elif old_cap is None or old_rem is None:
                # 从不限量切到限量：直接置满
                fields["cooperation_remaining"] = new_cap
            else:
                # 按差值平移，不恢复已消耗名额
                fields["cooperation_remaining"] = max(0, min(new_cap, old_rem + (new_cap - old_cap)))

        if "org_id" in fields:
            assert_active_membership(cur, user_id, fields["org_id"])
        _validate_refs(cur, fields)
        has_child_mutation = inventor_refs is not None or bool(content)
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            cur.execute(
                f"UPDATE achievement SET {set_clause}, version=version+1 WHERE id=%s AND version=%s",
                list(fields.values()) + [ach_id, version],
            )
            if cur.rowcount == 0:
                raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        elif has_child_mutation:
            # 内容型 PATCH（仅改 sections/media/attachments/inventors）也必须
            # 校验乐观锁并 bump version，否则并发写可双成功、子表后写覆盖先写。
            cur.execute(
                "UPDATE achievement SET version=version+1 WHERE id=%s AND version=%s",
                (ach_id, version),
            )
            if cur.rowcount == 0:
                raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        if inventor_refs is not None:
            _sync_inventors(cur, ach_id, inventor_refs, user_id)
        sync_content(cur, ach_id, user_id, content)

        audit_record(
            "achievement.update", "achievement", resource_id=ach_id,
            actor_user_id=user_id, actor_user_no=user_no, request_id=request_id, cur=cur,
        )

    return _owner_detail_public(ach_id, user_id)


def _transition(user_id: int, user_no: str, ach_id: int, version, op: str, reason=None, reason_code=None, request_id=None):
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
        if op == 'offline' and reason_code:
            if reason_code not in ('cooperated', 'expired', 'superseded', 'duplicate', 'no_longer_available', 'other'):
                raise bad_request('reasonCode 不合法')
        else:
            reason_code = None
        cur.execute(
            "UPDATE achievement SET status=%s, version=version+1, offline_reason_code=COALESCE(%s, offline_reason_code), offline_reason_note=COALESCE(%s, offline_reason_note) WHERE id=%s AND version=%s",
            (rule["to"], reason_code, str(reason or '').strip()[:500] or None, ach_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        audit_record(
            rule["action"], "achievement", resource_id=ach_id,
            actor_user_id=user_id, actor_user_no=user_no,
            details={"from": row["status"], "to": rule["to"], "reason": reason or None, "reasonCode": reason_code},
            request_id=request_id, cur=cur,
        )

    return {"status": rule["to"]}


def submit_achievement(user_id: int, user_no: str, ach_id: int, version, request_id=None):
    return _transition(user_id, user_no, ach_id, version, "submit", request_id=request_id)


def offline_achievement(user_id: int, user_no: str, ach_id: int, version, reason=None, reason_code=None, request_id=None):
    return _transition(user_id, user_no, ach_id, version, "offline", reason=reason, reason_code=reason_code, request_id=request_id)


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
                   a.org_id, o.name AS certified_org_name,
                   c.name AS category_name, c.code AS category_code,
                   (SELECT am.file_id FROM achievement_media am JOIN file_object fo ON fo.id=am.file_id AND fo.status='active' WHERE am.achievement_id=a.id AND am.media_role='cover' ORDER BY am.sort_order,am.id LIMIT 1) AS cover_file_id
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id=c.id
            LEFT JOIN institution o ON a.org_id=o.id
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
        "sourceOrgName": _display_source_org(row),
        "orgId": row.get("org_id"),
        "orgCertified": row.get("org_id") is not None,
        "categoryName": row.get("category_name"),
        "categoryCode": row.get("category_code"),
        "techIntro": (row.get("tech_intro") or "")[:120],
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": resolve_maturity_desc(row.get("maturity_level"), row.get("maturity_desc")),
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
