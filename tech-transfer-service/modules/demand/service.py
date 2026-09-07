"""
需求模块服务层 —— 列表、详情、创建、编辑、状态机（submit/cancel/close）

Architecture source: 04-backend-domain-design.md §4.6, 05-data-model-design.md §5,
                     06-api-design.md §8（需求组）、§5.2/§5.5（状态机与权限矩阵）
状态机（后端强校验，前端按钮仅引导）:
  draft / rejected → pending_review   (submit)
  published        → cancelled        (cancel)
  published / matched → closed        (close)
"""
import json
import re

from db import get_cursor
from core.errors import (
    bad_request,
    conflict,
    demand_conflict,
    demand_forbidden,
    demand_not_found,
)
from core.masking import mask_contact
from modules.audit.service import record as audit_record
from modules.cooperation.service import has_accepted_intent
from modules.membership.service import assert_active_membership

# 状态流转表（06 §5.5 权限矩阵）
TRANSITIONS = {
    "submit": {"from": ("draft", "rejected"), "to": "pending_review", "action": "demand.submit"},
    "cancel": {"from": ("published",), "to": "cancelled", "action": "demand.cancel"},
    "close": {"from": ("published", "matched"), "to": "closed", "action": "demand.close"},
}

EDITABLE_STATUSES = ("draft", "rejected")

SORT_WHITELIST = {
    "published_at.desc": "d.published_at DESC, d.id DESC",
    "created_at.desc": "d.created_at DESC, d.id DESC",
}

_UPSERT_FIELDS = (
    "title", "categoryId", "orgId", "description", "region", "coopMode",
    "budgetMinWan", "budgetMaxWan", "budgetNegotiable", "expectDeadline",
    "deadlineDesc", "contactName", "contactTitle", "contactPhone",
    "contactEmail", "contactWechat",
)


# ── 参数解析与校验 ───────────────────────────────────────────

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
    return page, page_size, keyword


def _parse_upsert_body(body: dict, partial: bool):
    """校验 DemandUpsertRequest，返回 (db_fields, tags)

    partial=True（PATCH）：只取传入字段；False（POST）：title/description 必填。
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

    if "description" in body and body["description"] is not None:
        description = str(body["description"]).strip()
        if not description:
            raise bad_request("description 不能为空")
        fields["description"] = description
    elif not partial:
        raise bad_request("description 必填")

    for key, column, max_len in (
        ("region", "region", 64),
        ("deadlineDesc", "deadline_desc", 128),
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

    if "coopMode" in body and body["coopMode"] is not None:
        modes = body["coopMode"]
        if not isinstance(modes, list) or any(not isinstance(m, str) for m in modes):
            raise bad_request("coopMode 必须是字符串数组")
        fields["coop_mode"] = json.dumps([m.strip() for m in modes if m.strip()], ensure_ascii=False)

    for key in ("budgetMinWan", "budgetMaxWan"):
        if key in body and body[key] is not None:
            try:
                val = float(body[key])
            except (ValueError, TypeError):
                raise bad_request(f"{key} 必须是数字")
            if val < 0:
                raise bad_request(f"{key} 不能为负数")
            fields["budget_min_wan" if key == "budgetMinWan" else "budget_max_wan"] = val

    if "budgetNegotiable" in body and body["budgetNegotiable"] is not None:
        if not isinstance(body["budgetNegotiable"], bool):
            raise bad_request("budgetNegotiable 必须是布尔值")
        fields["budget_negotiable"] = bool(body["budgetNegotiable"])

    if "expectDeadline" in body and body["expectDeadline"] is not None:
        val = str(body["expectDeadline"]).strip()
        if not re.match(r"^\d{4}-\d{2}-\d{2}$", val):
            raise bad_request("expectDeadline 格式必须是 YYYY-MM-DD")
        fields["expect_deadline"] = val

    if "categoryId" in body and body["categoryId"] is not None:
        try:
            fields["category_id"] = int(body["categoryId"])
        except (ValueError, TypeError):
            raise bad_request("categoryId 必须是整数")

    if "orgId" in body and body["orgId"] is not None:
        try:
            fields["org_id"] = int(body["orgId"])
        except (ValueError, TypeError):
            raise bad_request("orgId 必须是整数")

    # Legacy organization names are display snapshots, never canonical identities.
    if "orgName" in body and body["orgName"] is not None:
        org_name = str(body["orgName"]).strip()
        if len(org_name) > 128:
            raise bad_request("orgName 长度不能超过 128")
        fields["org_name_snapshot"] = org_name or None

    if "orgIntro" in body and body["orgIntro"] is not None:
        org_intro = str(body["orgIntro"]).strip()
        if len(org_intro) > 2000:
            raise bad_request("orgIntro 长度不能超过 2000")
        fields["org_intro"] = org_intro or None

    if "categoryName" in body and body["categoryName"] is not None:
        category_name = str(body["categoryName"]).strip()
        if len(category_name) > 64:
            raise bad_request("categoryName 长度不能超过 64")
        fields["category_name"] = category_name or None

    tags = body.get("tags")
    if tags is not None:
        if not isinstance(tags, list) or any(not isinstance(t, str) for t in tags):
            raise bad_request("tags 必须是字符串数组")

    return fields, tags


def _validate_refs(cur, fields):
    """Validate foreign keys; user publication also requires active membership."""
    if "category_id" in fields:
        cur.execute("SELECT id FROM demand_category WHERE id=%s", (fields["category_id"],))
        if not cur.fetchone():
            raise bad_request("categoryId 不存在")
    if "org_id" in fields:
        cur.execute("SELECT id FROM organization WHERE id=%s", (fields["org_id"],))
        if not cur.fetchone():
            raise bad_request("orgId 不存在")


def _resolve_name_refs(cur, fields):
    """Legacy administrative entry only; never used by user create/update paths."""
    org_name = fields.pop("org_name_snapshot", None)
    org_intro = fields.pop("org_intro", None)
    if org_intro and not org_name:
        raise bad_request("orgIntro 需与 orgName 一起提供")
    if org_name:
        cur.execute("SELECT id FROM organization WHERE org_name=%s", (org_name,))
        row = cur.fetchone()
        if row:
            org_id = row["id"]
            if org_intro:
                cur.execute(
                    "UPDATE organization SET intro=%s WHERE id=%s AND (intro IS NULL OR intro='')",
                    (org_intro, org_id),
                )
        else:
            cur.execute(
                "INSERT INTO organization (org_name, intro) VALUES (%s, %s) RETURNING id",
                (org_name, org_intro),
            )
            org_id = cur.fetchone()["id"]
        fields["org_id"] = org_id
    _resolve_category_name(cur, fields)


def _resolve_category_name(cur, fields):
    """Preserve legacy category resolution; organization text cannot mutate organizations."""
    org_intro = fields.pop("org_intro", None)
    category_name = fields.pop("category_name", None)

    if org_intro and not fields.get("org_name_snapshot"):
        raise bad_request("orgIntro 需与 orgName 一起提供")

    if category_name:
        cur.execute(
            "SELECT id FROM demand_category WHERE code=%s OR name=%s",
            (category_name, category_name),
        )
        row = cur.fetchone()
        if row:
            fields["category_id"] = row["id"]
        else:
            cur.execute(
                "INSERT INTO demand_category (code, name) VALUES (%s, %s) RETURNING id",
                (category_name, category_name),
            )
            fields["category_id"] = cur.fetchone()["id"]


# ── 标签 ─────────────────────────────────────────────────────

def _load_tags(cur, demand_ids):
    if not demand_ids:
        return {}
    placeholders = ",".join(["%s"] * len(demand_ids))
    cur.execute(
        f"""
        SELECT r.demand_id, t.name
        FROM demand_tag_relation r
        JOIN demand_tag t ON r.tag_id = t.id
        WHERE r.demand_id IN ({placeholders})
        ORDER BY t.id
        """,
        tuple(demand_ids),
    )
    result = {}
    for row in cur.fetchall() or []:
        result.setdefault(row["demand_id"], []).append(row["name"])
    return result


def _sync_tags(cur, demand_id: int, tag_names):
    if tag_names is None:
        return
    names = [n.strip()[:64] for n in tag_names if n and n.strip()]
    cur.execute("DELETE FROM demand_tag_relation WHERE demand_id=%s", (demand_id,))
    for name in dict.fromkeys(names):
        cur.execute("SELECT id FROM demand_tag WHERE code=%s", (name,))
        row = cur.fetchone()
        if row:
            tag_id = row["id"]
        else:
            cur.execute(
                "INSERT INTO demand_tag (code, name) VALUES (%s, %s) RETURNING id",
                (name, name),
            )
            tag_id = cur.fetchone()["id"]
        cur.execute(
            "INSERT INTO demand_tag_relation (demand_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
            (demand_id, tag_id),
        )


# ── 行转 DTO ─────────────────────────────────────────────────

def _parse_json(raw):
    if raw and isinstance(raw, str):
        try:
            return json.loads(raw)
        except (ValueError, TypeError):
            return []
    return raw or []


def _row_to_summary(row, tags, user_id):
    is_owner = row["owner_user_id"] == user_id
    return {
        "id": row["id"],
        "title": row["title"],
        "orgName": row.get("org_name"),
        "region": row.get("region"),
        "coopMode": _parse_json(row.get("coop_mode")),
        "budgetMinWan": float(row["budget_min_wan"]) if row.get("budget_min_wan") is not None else None,
        "budgetMaxWan": float(row["budget_max_wan"]) if row.get("budget_max_wan") is not None else None,
        "budgetNegotiable": bool(row.get("budget_negotiable")),
        "deadlineDesc": row.get("deadline_desc"),
        "categoryName": row.get("category_name"),
        "tags": tags.get(row["id"], []),
        "status": row["status"],
        "isMine": is_owner,
        "version": row.get("version"),
        # 审核反馈仅返回给本人，公开列表与其他用户不暴露原因。
        "rejectReason": row.get("reject_reason") if is_owner else None,
        "viewCount": int(row.get("view_count") or 0),
        "publishedAt": row["published_at"].strftime("%Y-%m-%d %H:%M") if row.get("published_at") else None,
    }


def _row_to_detail(row, tags, user_id, contact_visible=False):
    is_owner = row["owner_user_id"] == user_id
    detail = _row_to_summary(row, tags, user_id)
    # 联系方式：仅发布方本人或已被接受的对接（accepted/confirmed/completed）可见明文，
    # 其余查看者（含未登录游客）一律脱敏 —— 防止绕过平台私下联系。
    if contact_visible:
        contact = {
            "contactName": row.get("contact_name"),
            "contactTitle": row.get("contact_title"),
            "contactPhone": row.get("contact_phone"),
            "contactEmail": row.get("contact_email"),
            "contactWechat": row.get("contact_wechat"),
        }
    else:
        contact = mask_contact({
            "contactName": row.get("contact_name"),
            "contactTitle": row.get("contact_title"),
            "contactPhone": row.get("contact_phone"),
            "contactEmail": row.get("contact_email"),
            "contactWechat": row.get("contact_wechat"),
        })
    detail.update({
        "version": row["version"],
        "rejectReason": row.get("reject_reason") if is_owner else None,
        "description": row["description"],
        "expectDeadline": str(row["expect_deadline"]) if row.get("expect_deadline") else None,
        "orgIntro": row.get("org_intro"),
        **contact,
    })
    return detail


# ── 查询 ─────────────────────────────────────────────────────

_BASE_SELECT = """
    SELECT d.*, COALESCE(d.org_name_snapshot, o.org_name) AS org_name, o.intro AS org_intro,
           c.name AS category_name, c.code AS category_code
    FROM demand d
    LEFT JOIN organization o ON d.org_id = o.id
    LEFT JOIN demand_category c ON d.category_id = c.id
"""


def list_demands(args, user_id: int):
    page, page_size, keyword = _parse_page_args(args)
    category_code = (args.get("categoryCode") or "").strip()
    include_mine = str(args.get("includeMine") or "").lower() in ("1", "true", "yes")
    sort = SORT_WHITELIST.get(args.get("sort") or "published_at.desc", SORT_WHITELIST["published_at.desc"])

    where = " WHERE d.deleted_at IS NULL AND d.status='published'"
    if include_mine:
        where = " WHERE d.deleted_at IS NULL AND (d.status='published' OR d.owner_user_id=%s)"
    params = [user_id] if include_mine else []

    if keyword:
        where += " AND (d.title LIKE %s OR d.description LIKE %s OR COALESCE(d.org_name_snapshot, o.org_name) LIKE %s)"
        like = f"%{keyword}%"
        params.extend([like, like, like])

    if category_code:
        where += " AND c.code=%s"
        params.append(category_code)

    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM demand d LEFT JOIN organization o ON d.org_id=o.id LEFT JOIN demand_category c ON d.category_id=c.id{where}", params)
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(f"{_BASE_SELECT}{where} ORDER BY {sort} LIMIT %s OFFSET %s", params + [page_size, offset])
        rows = cur.fetchall() or []
        tags = _load_tags(cur, [r["id"] for r in rows])

    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
        "list": [_row_to_summary(r, tags, user_id) for r in rows],
    }


def list_my_demands(user_id: int, args):
    page, page_size, _ = _parse_page_args(args)
    status = (args.get("status") or "").strip()

    where = " WHERE d.deleted_at IS NULL AND d.owner_user_id=%s"
    params = [user_id]
    if status:
        where += " AND d.status=%s"
        params.append(status)

    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM demand d{where}", params)
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(f"{_BASE_SELECT}{where} ORDER BY d.created_at DESC, d.id DESC LIMIT %s OFFSET %s", params + [page_size, offset])
        rows = cur.fetchall() or []
        tags = _load_tags(cur, [r["id"] for r in rows])

    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
        "list": [_row_to_summary(r, tags, user_id) for r in rows],
    }


def _get_demand_row(cur, demand_id: int):
    cur.execute(f"{_BASE_SELECT} WHERE d.id=%s AND d.deleted_at IS NULL", (demand_id,))
    return cur.fetchone()


def get_demand_detail(demand_id: int, user_id: int):
    with get_cursor(commit=True) as cur:
        row = _get_demand_row(cur, demand_id)
        if not row:
            raise demand_not_found()
        if row["status"] != "published" and row["owner_user_id"] != user_id:
            # 防探测：非公开需求对非 owner 一律 404
            raise demand_not_found()

        # 草稿/驳回等非公开内容不计入浏览量；已发布内容在同一事务中原子累加。
        if row["status"] == "published":
            cur.execute(
                """
                UPDATE demand
                SET view_count = view_count + 1
                WHERE id=%s AND status='published' AND deleted_at IS NULL
                RETURNING view_count
                """,
                (demand_id,),
            )
            row["view_count"] = (cur.fetchone() or {}).get("view_count", 0)

        tags = _load_tags(cur, [demand_id])
        contact_visible = (
            row["owner_user_id"] == user_id
            or has_accepted_intent(cur, "demand", demand_id, user_id)
        )
    return _row_to_detail(row, tags, user_id, contact_visible)


# ── 写操作 ───────────────────────────────────────────────────

def create_demand(user_id: int, user_no: str, body: dict, request_id=None):
    fields, tags = _parse_upsert_body(body, partial=False)
    if "ownerUserId" in body:
        print(f"[demand] WARNING: request body contains ownerUserId (ignored), user={user_no}")
    if fields.get("budget_min_wan") is not None and fields.get("budget_max_wan") is not None:
        if fields["budget_min_wan"] > fields["budget_max_wan"]:
            raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

    with get_cursor(commit=True) as cur:
        if "org_id" in fields:
            assert_active_membership(cur, user_id, fields["org_id"])
        _resolve_category_name(cur, fields)
        _validate_refs(cur, fields)
        cur.execute(
            """
            INSERT INTO demand
                (owner_user_id, title, category_id, org_id, org_name_snapshot, description, region,
                 coop_mode, budget_min_wan, budget_max_wan, budget_negotiable,
                 expect_deadline, deadline_desc, contact_name, contact_title,
                 contact_phone, contact_email, contact_wechat, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'draft')
            RETURNING id
            """,
            (
                user_id,
                fields.get("title"),
                fields.get("category_id"),
                fields.get("org_id"),
                fields.get("org_name_snapshot"),
                fields.get("description"),
                fields.get("region"),
                fields.get("coop_mode"),
                fields.get("budget_min_wan"),
                fields.get("budget_max_wan"),
                fields.get("budget_negotiable", False),
                fields.get("expect_deadline"),
                fields.get("deadline_desc"),
                fields.get("contact_name"),
                fields.get("contact_title"),
                fields.get("contact_phone"),
                fields.get("contact_email"),
                fields.get("contact_wechat"),
            ),
        )
        demand_id = cur.fetchone()["id"]
        if tags is not None:
            _sync_tags(cur, demand_id, tags)

    audit_record(
        "demand.create", "demand", resource_id=demand_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"title": fields.get("title")}, request_id=request_id,
    )
    return get_demand_detail(demand_id, user_id)


def update_demand(user_id: int, user_no: str, demand_id: int, body: dict, request_id=None):
    fields, tags = _parse_upsert_body(body, partial=True)
    if fields.get("budget_min_wan") is not None and fields.get("budget_max_wan") is not None:
        if fields["budget_min_wan"] > fields["budget_max_wan"]:
            raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

    version = body.get("version")
    if version is None:
        raise bad_request("编辑需求必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        row = _get_demand_row(cur, demand_id)
        if not row:
            raise demand_not_found()
        if row["owner_user_id"] != user_id:
            raise demand_forbidden()
        if row["status"] not in EDITABLE_STATUSES:
            raise demand_conflict(f"当前状态 {row['status']} 不允许编辑（仅 draft/rejected 可编辑）")

        if "org_id" in fields:
            assert_active_membership(cur, user_id, fields["org_id"])
        _resolve_category_name(cur, fields)
        _validate_refs(cur, fields)
        if fields:
            set_clause = ", ".join(f"{k}=%s" for k in fields)
            cur.execute(
                f"UPDATE demand SET {set_clause}, version=version+1 WHERE id=%s AND version=%s",
                list(fields.values()) + [demand_id, version],
            )
            if cur.rowcount == 0:
                raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        if tags is not None:
            _sync_tags(cur, demand_id, tags)

    audit_record(
        "demand.update", "demand", resource_id=demand_id,
        actor_user_id=user_id, actor_user_no=user_no, request_id=request_id,
    )
    return get_demand_detail(demand_id, user_id)


def _transition(user_id: int, user_no: str, demand_id: int, version, op: str, request_id=None):
    rule = TRANSITIONS[op]
    if version is None:
        raise bad_request(f"{op} 必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        row = _get_demand_row(cur, demand_id)
        if not row:
            raise demand_not_found()
        if row["owner_user_id"] != user_id:
            raise demand_forbidden()
        if row["status"] not in rule["from"]:
            raise demand_conflict(
                f"当前状态 {row['status']} 不允许 {op}"
                f"（要求 {('/'.join(rule['from']))}）"
            )
        cur.execute(
            "UPDATE demand SET status=%s, version=version+1 WHERE id=%s AND version=%s",
            (rule["to"], demand_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

    audit_record(
        rule["action"], "demand", resource_id=demand_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"from": row["status"], "to": rule["to"]}, request_id=request_id,
    )
    return {"status": rule["to"]}


def submit_demand(user_id: int, user_no: str, demand_id: int, version, request_id=None):
    return _transition(user_id, user_no, demand_id, version, "submit", request_id)


def cancel_demand(user_id: int, user_no: str, demand_id: int, version, request_id=None):
    return _transition(user_id, user_no, demand_id, version, "cancel", request_id)


def close_demand(user_id: int, user_no: str, demand_id: int, version, request_id=None):
    return _transition(user_id, user_no, demand_id, version, "close", request_id)
