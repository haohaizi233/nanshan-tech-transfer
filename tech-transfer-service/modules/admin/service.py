"""
admin 服务层（P0-3/P0-4）—— 管理审核

Architecture source: 04-backend-domain-design.md §5.4, 06-api-design.md §15 admin 组

设计约定：
- 无自有表：操作 achievement/demand 状态 + 写 audit_log（04 §5.4）
- 审核单事务：校验 pending_review → 置 published/rejected + 版本+1 + 写审计
- approve 副作用：published_at 置当前时间；reject 必填 reason（TT_ADMIN_40001）
- 通知入队（notification 模块）一期未实现，副作用仅审计留痕
- 队列项含提交人与提交时间（06 §15）
"""
from db import get_cursor
from core.errors import (
    BizError, bad_request, conflict,
    TT_ACH_40901, TT_DMD_40401, TT_DMD_40901,
    TT_ADMIN_40001,
)
from modules.audit.service import record as audit_record


def _page_args(args) -> tuple[int, int]:
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10
    return page, page_size


# ── 审核队列 ────────────────────────────────────────────────

def achievements_review_queue(args) -> dict:
    """GET /admin/achievements/review-queue —— pending_review 成果队列"""
    page, page_size = _page_args(args)
    category_code = (args.get("categoryCode") or "").strip()
    where = "a.status = 'pending_review' AND a.deleted_at IS NULL"
    params = []
    if category_code:
        where += " AND c.code = %s"
        params.append(category_code)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            WHERE {where}
            """,
            params,
        )
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT a.id, a.title, a.status, a.version, a.created_at, a.updated_at,
                   a.source_org_name, c.name AS category_name, c.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            LEFT JOIN app_user u ON a.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE {where}
            ORDER BY a.updated_at ASC, a.id ASC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []

    return _page_of(rows, page, page_size, total, _ach_queue_item)


def demands_review_queue(args) -> dict:
    """GET /admin/demands/review-queue —— pending_review 需求队列"""
    page, page_size = _page_args(args)
    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM demand WHERE status = 'pending_review' AND deleted_at IS NULL"
        )
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            """
            SELECT d.id, d.title, d.status, d.version, d.updated_at,
                   o.org_name, dc.name AS category_name, dc.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM demand d
            LEFT JOIN organization o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            LEFT JOIN app_user u ON d.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE d.status = 'pending_review' AND d.deleted_at IS NULL
            ORDER BY d.updated_at ASC, d.id ASC
            LIMIT %s OFFSET %s
            """,
            (page_size, offset),
        )
        rows = cur.fetchall() or []

    return _page_of(rows, page, page_size, total, _dmd_queue_item)


# ── 审核（approve / reject） ─────────────────────────────────

def review_achievement(admin_user: dict, ach_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/achievements/{id}/approve|reject 的事务实现"""
    action = body.get("_action")  # approve / reject（路由层注入）
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    reason = (body.get("reason") or "").strip()
    if action == "reject" and not reason:
        code, message, status = TT_ADMIN_40001
        raise BizError(code, message, status)

    to_status = "published" if action == "approve" else "rejected"
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status, version FROM achievement WHERE id = %s AND deleted_at IS NULL",
            (ach_id,),
        )
        row = cur.fetchone()
        if not row:
            raise bad_request("成果不存在")
        if row["status"] != "pending_review":
            code, message, http_status = TT_ACH_40901
            raise BizError(code, f"当前状态 {row['status']} 不允许审核（要求 pending_review）", http_status)
        if action == "approve":
            cur.execute(
                """
                UPDATE achievement SET status = 'published', published_at = NOW(),
                       reject_reason = NULL, version = version + 1
                WHERE id = %s AND version = %s
                """,
                (ach_id, version),
            )
        else:
            cur.execute(
                """
                UPDATE achievement SET status = 'rejected', reject_reason = %s, version = version + 1
                WHERE id = %s AND version = %s
                """,
                (reason, ach_id, version),
            )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

    audit_record(
        f"achievement.{action}", "achievement", resource_id=ach_id,
        actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
        details={"from": "pending_review", "to": to_status, "reason": reason or None},
        request_id=request_id,
    )
    return {"status": to_status}


def review_demand(admin_user: dict, demand_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/demands/{id}/approve|reject 的事务实现"""
    action = body.get("_action")
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    reason = (body.get("reason") or "").strip()
    if action == "reject" and not reason:
        code, message, status = TT_ADMIN_40001
        raise BizError(code, message, status)

    to_status = "published" if action == "approve" else "rejected"
    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status, version FROM demand WHERE id = %s AND deleted_at IS NULL",
            (demand_id,),
        )
        row = cur.fetchone()
        if not row:
            code, message, status = TT_DMD_40401
            raise BizError(code, "需求不存在", status)
        if row["status"] != "pending_review":
            code, message, http_status = TT_DMD_40901
            raise BizError(code, f"当前状态 {row['status']} 不允许审核（要求 pending_review）", http_status)
        if action == "approve":
            cur.execute(
                """
                UPDATE demand SET status = 'published', published_at = NOW(),
                       reject_reason = NULL, version = version + 1
                WHERE id = %s AND version = %s
                """,
                (demand_id, version),
            )
        else:
            cur.execute(
                """
                UPDATE demand SET status = 'rejected', reject_reason = %s, version = version + 1
                WHERE id = %s AND version = %s
                """,
                (reason, demand_id, version),
            )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

    audit_record(
        f"demand.{action}", "demand", resource_id=demand_id,
        actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
        details={"from": "pending_review", "to": to_status, "reason": reason or None},
        request_id=request_id,
    )
    return {"status": to_status}


# ── 审计日志查询 ─────────────────────────────────────────────

def list_audit_logs(args) -> dict:
    """GET /admin/audit-logs —— 分页 + actorUserId/targetType/requestId/时间范围"""
    page, page_size = _page_args(args)
    where = ["1=1"]
    params = []
    actor = (args.get("actorUserId") or "").strip()
    if actor:
        where.append("actor_user_id = %s")
        params.append(actor)
    resource_type = (args.get("targetType") or "").strip()
    if resource_type:
        where.append("resource_type = %s")
        params.append(resource_type)
    request_id = (args.get("requestId") or "").strip()
    if request_id:
        where.append("request_id = %s")
        params.append(request_id)

    where_sql = " WHERE " + " AND ".join(where)
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c FROM audit_log" + where_sql, params)
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            "SELECT * FROM audit_log" + where_sql + " ORDER BY id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []

    items = [
        {
            "id": r["id"],
            "actorUserId": r.get("actor_user_id"),
            "actorUserNo": r.get("actor_user_no"),
            "action": r["action"],
            "resourceType": r.get("resource_type"),
            "resourceId": r.get("resource_id"),
            "details": r.get("details"),
            "requestId": r.get("request_id"),
            "createdAt": r["created_at"].isoformat(),
        }
        for r in rows
    ]
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": total_pages, "list": items,
    }


# ── helpers ──────────────────────────────────────────────────

def _page_of(rows, page, page_size, total, fn):
    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total, "page": page, "pageSize": page_size,
        "totalPages": total_pages, "list": [fn(r) for r in rows],
    }


def _ach_queue_item(r):
    return {
        "id": r["id"], "title": r["title"], "status": r["status"], "version": r["version"],
        "categoryName": r.get("category_name"), "categoryCode": r.get("category_code"),
        "orgName": r.get("source_org_name"),
        "submitterUserNo": r.get("submitter_user_no"),
        "submitterName": r.get("submitter_name"),
        "submittedAt": (r.get("updated_at") or r.get("created_at")).isoformat(),
    }


def _dmd_queue_item(r):
    return {
        "id": r["id"], "title": r["title"], "status": r["status"], "version": r["version"],
        "categoryName": r.get("category_name"), "categoryCode": r.get("category_code"),
        "orgName": r.get("org_name"),
        "submitterUserNo": r.get("submitter_user_no"),
        "submitterName": r.get("submitter_name"),
        "submittedAt": r["updated_at"].isoformat(),
    }


# ═════════════════════════════════════════════════════════════
# Release Closure（P0-1 ~ P0-4）：Dashboard / Institution /
# Cooperation（只读）/ Users（只读）
# ═════════════════════════════════════════════════════════════

from core.errors import (
    TT_INST_40001, TT_INST_40401, TT_INST_40901, TT_COOP_40401, not_found,
)

INST_KINDS = ("platform", "invest", "service")
PLATFORM_TYPE_KEYS = ("poc", "pilot", "other")
INST_STATUSES = ("active", "disabled")

# Institution PATCH 可编辑字段（camel → snake）；kind/source 溯源/id/时间戳不可改
INST_EDITABLE = {
    "name": "name",
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
}


# ── P0-1 Dashboard ───────────────────────────────────────────

def dashboard_summary() -> dict:
    """GET /admin/dashboard/summary —— 单查询真实 COUNT，无假数据、无趋势。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM app_user
                WHERE status = 'active' AND deleted_at IS NULL)                 AS users,
              (SELECT COUNT(*) FROM achievement WHERE deleted_at IS NULL)       AS achievements,
              (SELECT COUNT(*) FROM demand WHERE deleted_at IS NULL)            AS demands,
              (SELECT COUNT(*) FROM cooperation_intent)                         AS cooperations,
              (SELECT COUNT(*) FROM achievement
                WHERE status = 'pending_review' AND deleted_at IS NULL)         AS pending_achievements,
              (SELECT COUNT(*) FROM demand
                WHERE status = 'pending_review' AND deleted_at IS NULL)         AS pending_demands,
              (SELECT COUNT(*) FROM institution WHERE status = 'active')        AS institutions
            """
        )
        r = cur.fetchone()

    pending_total = int(r["pending_achievements"]) + int(r["pending_demands"])
    return {
        "users": int(r["users"]),
        "achievements": int(r["achievements"]),
        "demands": int(r["demands"]),
        "cooperations": int(r["cooperations"]),
        "pendingAchievements": int(r["pending_achievements"]),
        "pendingDemands": int(r["pending_demands"]),
        "pendingTotal": pending_total,
        "institutions": int(r["institutions"]),
    }


# ── P0-2 Institution 管理端 ─────────────────────────────────

def _inst_admin_item(r):
    item = {
        "id": r["id"],
        "kind": r["kind"],
        "name": (r.get("name") or "").strip(),
        "intro": (r.get("intro") or "").strip(),
        "detailInfo": (r.get("detail_info") or "").strip(),
        "label": (r.get("label") or "").strip(),
        "logoFileId": (r.get("logo_file_id") or "").strip(),
        "sortOrder": int(r.get("sort_order") or 0),
        "status": r.get("status") or "active",
        "userType": (r.get("user_type") or "").strip(),
        "sourcePk": r.get("source_pk"),
        "sourceSite": (r.get("source_site") or "").strip(),
        "fetchedAt": r["fetched_at"].isoformat() if r.get("fetched_at") else None,
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }
    fid = item["logoFileId"]
    item["logoUrl"] = f"/api/file/{fid}" if fid else ""
    if r["kind"] == "platform":
        item.update({
            "serialNo": int(r.get("serial_no") or 0),
            "platformType": (r.get("platform_type") or "").strip(),
            "platformTypeKey": (r.get("platform_type_key") or "other").strip(),
            "unit": (r.get("support_unit") or "").strip(),
            "functionText": (r.get("functions") or "").strip(),
            "contact": (r.get("contact_person") or "").strip(),
            "phone": (r.get("contact_mobile") or "").strip(),
        })
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
            code, message, status = TT_INST_40001
            raise BizError(code, "机构名称不能为空", status)

    kind = None
    if require_kind:
        kind = (str(body.get("kind") or "").strip().lower())
        if kind not in INST_KINDS:
            code, message, status = TT_INST_40001
            raise BizError(code, f"kind 必须是 {'/'.join(INST_KINDS)}", status)
    elif "platform_type_key" in cleaned:
        key = str(cleaned["platform_type_key"]).strip().lower()
        if key not in PLATFORM_TYPE_KEYS:
            code, message, status = TT_INST_40001
            raise BizError(code, f"platformTypeKey 必须是 {'/'.join(PLATFORM_TYPE_KEYS)}", status)
    return cleaned, kind


def create_institution(admin_user: dict, body: dict, request_id=None) -> dict:
    """POST /admin/institutions —— 管理员录入（source_pk 留空，不与 ETL 冲突）。

    写入与审计同事务（§16）；新记录默认 status='active' 即公开可见。
    """
    cleaned, kind = _validate_inst_payload(body, require_kind=True)

    if kind == "platform":
        cleaned.setdefault("platform_type_key", "other")

    columns = ["kind", "status"]
    values: list = [kind, "active"]
    for snake in ("name", "intro", "detail_info", "label", "logo_file_id", "sort_order",
                  "user_type", "detail_activity_id", "platform_type", "platform_type_key",
                  "support_unit", "functions", "contact_person", "contact_mobile",
                  "serial_no"):
        if snake in cleaned:
            columns.append(snake)
            values.append(cleaned[snake])
    if "name" not in columns:
        code, message, status = TT_INST_40001
        raise BizError(code, "机构名称 name 必填", status)

    placeholders = ",".join(["%s"] * len(columns))
    with get_cursor(commit=True) as cur:
        cur.execute(
            f"INSERT INTO institution ({','.join(columns)}) VALUES ({placeholders}) RETURNING *",
            values,
        )
        row = cur.fetchone()
        audit_record(
            "institution.create", "institution", resource_id=row["id"],
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"kind": kind, "name": row["name"], "status": "active"},
            request_id=request_id, cur=cur,
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
        changed = {k: {"from": row.get(k), "to": after.get(k)}
                   for k in cleaned if row.get(k) != after.get(k)}
        audit_record(
            "institution.update", "institution", resource_id=inst_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"changed": changed} if changed else {"changed": {}},
            request_id=request_id, cur=cur,
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
            f"institution.{action}", "institution", resource_id=inst_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": row["status"], "to": to_status, "name": row["name"]},
            request_id=request_id, cur=cur,
        )
    return {"status": to_status}


# ── P0-3 Cooperation 管理端（READ ONLY，不动状态机） ────────

_COOP_FROM = """
FROM cooperation_intent ci
LEFT JOIN app_user iu ON ci.initiator_user_id = iu.id
LEFT JOIN user_profile ip ON iu.id = ip.user_id
LEFT JOIN app_user tu ON ci.target_owner_user_id = tu.id
LEFT JOIN user_profile tp ON tu.id = tp.user_id
LEFT JOIN demand d ON ci.target_type = 'demand' AND ci.target_id = d.id
LEFT JOIN achievement a ON ci.target_type = 'achievement' AND ci.target_id = a.id
"""

_COOP_LIST_SQL = """
SELECT ci.id, ci.initiator_user_id, ci.target_type, ci.target_id,
       ci.target_owner_user_id, ci.message, ci.status, ci.version,
       ci.created_at, ci.accepted_at, ci.confirmed_at, ci.completed_at, ci.closed_at,
       iu.user_no AS initiator_user_no, ip.display_name AS initiator_name,
       tu.user_no AS target_owner_user_no, tp.display_name AS target_owner_name,
       COALESCE(d.title, a.title) AS target_title
""" + _COOP_FROM


def _coop_admin_item(r):
    return {
        "id": r["id"],
        "initiatorUserId": r["initiator_user_id"],
        "initiatorUserNo": r.get("initiator_user_no"),
        "initiatorName": r.get("initiator_name"),
        "targetOwnerUserId": r["target_owner_user_id"],
        "targetOwnerUserNo": r.get("target_owner_user_no"),
        "targetOwnerName": r.get("target_owner_name"),
        "targetType": r["target_type"],
        "targetId": r["target_id"],
        "targetTitle": r.get("target_title"),
        "message": r.get("message"),
        "status": r["status"],
        "version": r["version"],
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "acceptedAt": r["accepted_at"].isoformat() if r.get("accepted_at") else None,
        "confirmedAt": r["confirmed_at"].isoformat() if r.get("confirmed_at") else None,
        "completedAt": r["completed_at"].isoformat() if r.get("completed_at") else None,
        "closedAt": r["closed_at"].isoformat() if r.get("closed_at") else None,
    }


def list_cooperations_admin(args) -> dict:
    """GET /admin/cooperations —— 只读列表：status 过滤 + keyword（双方用户/目标标题/留言）。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where, params = [], []
    if status:
        where.append("ci.status = %s")
        params.append(status)
    if keyword:
        like = f"%{keyword}%"
        where.append(
            "(ci.message ILIKE %s OR ip.display_name ILIKE %s OR tp.display_name ILIKE %s"
            " OR COALESCE(d.title, a.title) ILIKE %s)"
        )
        params.extend([like] * 4)
    where_sql = (" WHERE " + " AND ".join(where)) if where else ""

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c" + _COOP_FROM + where_sql, params)
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            _COOP_LIST_SQL + where_sql + " ORDER BY ci.id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    return _page_of(rows, page, page_size, total, _coop_admin_item)


def get_cooperation_admin(intent_id: int) -> dict:
    """GET /admin/cooperations/{id} —— 只读详情 + events（管理端视角，无参与方权限过滤）。"""
    with get_cursor() as cur:
        cur.execute(_COOP_LIST_SQL + " WHERE ci.id = %s", (intent_id,))
        row = cur.fetchone()
        if not row:
            code, message, status = TT_COOP_40401
            raise BizError(code, message, status)
        cur.execute(
            """
            SELECT id, event_type, from_status, to_status, operator_user_id,
                   operator_role, remark, created_at
            FROM cooperation_event WHERE intent_id = %s ORDER BY id ASC
            """,
            (intent_id,),
        )
        events = cur.fetchall() or []

    detail = _coop_admin_item(row)
    detail["events"] = [
        {
            "id": e["id"],
            "eventType": e["event_type"],
            "fromStatus": e.get("from_status"),
            "toStatus": e.get("to_status"),
            "operatorUserId": e.get("operator_user_id"),
            "operatorRole": e.get("operator_role"),
            "remark": e.get("remark"),
            "createdAt": e["created_at"].isoformat() if e.get("created_at") else None,
        }
        for e in events
    ]
    return detail


# ── P0-4 Users 管理端（READ ONLY，禁用功能 P1） ─────────────

_USER_FROM = """
FROM app_user u
LEFT JOIN user_profile p ON u.id = p.user_id
LEFT JOIN organization o ON p.org_id = o.id
"""

_USER_LIST_SQL = """
SELECT u.id, u.user_no, u.status, u.created_at, u.updated_at,
       p.display_name, p.user_type, p.phone, p.email, p.org_title,
       o.org_name,
       (SELECT COALESCE(array_agg(ur.role_code ORDER BY ur.role_code), ARRAY[]::varchar[])
          FROM user_role ur WHERE ur.user_id = u.id) AS roles
""" + _USER_FROM


def _user_admin_item(r):
    return {
        "userId": r["id"],
        "userNo": r["user_no"],
        "status": r["status"],
        "displayName": (r.get("display_name") or "").strip(),
        "userType": (r.get("user_type") or "").strip(),
        "phone": (r.get("phone") or "").strip(),
        "email": (r.get("email") or "").strip(),
        "orgName": r.get("org_name"),
        "orgTitle": (r.get("org_title") or "").strip(),
        "roles": list(r.get("roles") or []),
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
    }


def list_users_admin(args) -> dict:
    """GET /admin/users —— 只读列表：keyword（user_no/display_name/org_name）+ status。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where = ["u.deleted_at IS NULL"]
    params = []
    if status:
        where.append("u.status = %s")
        params.append(status)
    if keyword:
        like = f"%{keyword}%"
        where.append("(u.user_no ILIKE %s OR p.display_name ILIKE %s OR o.org_name ILIKE %s)")
        params.extend([like] * 3)
    where_sql = " WHERE " + " AND ".join(where)

    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS c " + _USER_FROM + where_sql, params)
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            _USER_LIST_SQL + where_sql + " ORDER BY u.id DESC LIMIT %s OFFSET %s",
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    return _page_of(rows, page, page_size, total, _user_admin_item)


def get_user_admin(user_id: int) -> dict:
    """GET /admin/users/{id} —— 用户 + profile + roles + 低成本统计（4 个 COUNT 子查询）。"""
    with get_cursor() as cur:
        cur.execute(_USER_LIST_SQL + " WHERE u.id = %s AND u.deleted_at IS NULL", (user_id,))
        row = cur.fetchone()
        if not row:
            raise not_found("用户不存在")
        cur.execute(
            """
            SELECT
              (SELECT COUNT(*) FROM achievement
                 WHERE owner_user_id = %s AND deleted_at IS NULL)  AS ach_count,
              (SELECT COUNT(*) FROM demand
                 WHERE owner_user_id = %s AND deleted_at IS NULL)   AS dmd_count,
              (SELECT COUNT(*) FROM cooperation_intent
                 WHERE initiator_user_id = %s OR target_owner_user_id = %s) AS coop_count,
              (SELECT COUNT(*) FROM favorite WHERE user_id = %s)   AS fav_count
            """,
            (user_id, user_id, user_id, user_id, user_id),
        )
        stat = cur.fetchone()

    item = _user_admin_item(row)
    item["statistics"] = {
        "achievementCount": int(stat["ach_count"]),
        "demandCount": int(stat["dmd_count"]),
        "cooperationCount": int(stat["coop_count"]),
        "favoriteCount": int(stat["fav_count"]),
    }
    return item
