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
import json

from db import get_cursor
from core.errors import (
    BizError, bad_request, conflict,
    TT_ACH_40901, TT_DMD_40401, TT_DMD_40901,
    TT_ADMIN_40001,
)
from modules.audit.service import record as audit_record

from core.errors import achievement_not_found
from modules.achievement.service import (
    _parse_upsert_body,
    _validate_refs,
    _sync_inventors,
)

from core.errors import demand_not_found
from modules.demand.service import (
    _parse_upsert_body as _parse_demand_upsert_body,
    _resolve_name_refs as _resolve_demand_name_refs,
    _sync_tags as _sync_demand_tags,
    _validate_refs as _validate_demand_refs,
)


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


def list_demand_categories_admin() -> list[dict]:
    """后台需求录入使用的受控分类字典。"""
    with get_cursor() as cur:
        cur.execute("SELECT id, code, name FROM demand_category ORDER BY sort_order, id")
        return [{"id": row["id"], "code": row["code"], "name": row["name"]} for row in (cur.fetchall() or [])]


def list_content_organizations_admin() -> list[dict]:
    """后台内容录入使用的已启用机构（统一机构目录 institution）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT id, name
            FROM institution
            WHERE status = 'active'
            ORDER BY name, id
            """
        )
        return [{"id": row["id"], "name": row["name"]} for row in (cur.fetchall() or [])]


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
                   o.name AS org_name, dc.name AS category_name, dc.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
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
        cur.execute(
            "SELECT status, COUNT(*) AS c FROM achievement "
            "WHERE deleted_at IS NULL GROUP BY status"
        )
        ach_status = {row["status"]: int(row["c"]) for row in (cur.fetchall() or [])}
        cur.execute(
            "SELECT status, COUNT(*) AS c FROM demand "
            "WHERE deleted_at IS NULL GROUP BY status"
        )
        dmd_status = {row["status"]: int(row["c"]) for row in (cur.fetchall() or [])}

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
        "achievementStatusCounts": ach_status,
        "demandStatusCounts": dmd_status,
    }


def dashboard_trend(days) -> dict:
    """GET /admin/dashboard/trend?days= —— 近 N 日每日新增（用户/成果/需求），无数据补 0。"""
    try:
        days = int(days)
    except (ValueError, TypeError):
        days = 7
    days = max(1, min(90, days))

    with get_cursor() as cur:
        cur.execute(
            """
            SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'MM-DD') AS day,
                   COUNT(*) AS c
            FROM app_user
            WHERE created_at >= CURRENT_TIMESTAMP - make_interval(days => %s)
                  AND deleted_at IS NULL
            GROUP BY 1
            """,
            (days - 1,),
        )
        users = {row["day"]: int(row["c"]) for row in (cur.fetchall() or [])}
        cur.execute(
            """
            SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'MM-DD') AS day,
                   COUNT(*) AS c
            FROM achievement
            WHERE created_at >= CURRENT_TIMESTAMP - make_interval(days => %s)
                  AND deleted_at IS NULL
            GROUP BY 1
            """,
            (days - 1,),
        )
        achievements = {row["day"]: int(row["c"]) for row in (cur.fetchall() or [])}
        cur.execute(
            """
            SELECT to_char(created_at AT TIME ZONE 'Asia/Shanghai', 'MM-DD') AS day,
                   COUNT(*) AS c
            FROM demand
            WHERE created_at >= CURRENT_TIMESTAMP - make_interval(days => %s)
                  AND deleted_at IS NULL
            GROUP BY 1
            """,
            (days - 1,),
        )
        demands = {row["day"]: int(row["c"]) for row in (cur.fetchall() or [])}

    from datetime import date, timedelta

    today = date.today()
    labels, users_seq, ach_seq, dmd_seq = [], [], [], []
    for i in range(days - 1, -1, -1):
        day = today - timedelta(days=i)
        key = day.strftime("%m-%d")
        labels.append(key)
        users_seq.append(users.get(key, 0))
        ach_seq.append(achievements.get(key, 0))
        dmd_seq.append(demands.get(key, 0))
    return {
        "days": days,
        "labels": labels,
        "users": users_seq,
        "achievements": ach_seq,
        "demands": dmd_seq,
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


# ── P0-3 Cooperation 管理端（READ ONLY + 平台协助运营操作走 cooperation 模块） ──

_COOP_FROM = """
FROM cooperation_intent ci
LEFT JOIN app_user iu ON ci.initiator_user_id = iu.id
LEFT JOIN user_profile ip ON iu.id = ip.user_id
LEFT JOIN app_user tu ON ci.target_owner_user_id = tu.id
LEFT JOIN user_profile tp ON tu.id = tp.user_id
LEFT JOIN demand d ON ci.target_type = 'demand' AND ci.target_id = d.id
LEFT JOIN achievement a ON ci.target_type = 'achievement' AND ci.target_id = a.id
LEFT JOIN institution org ON ci.target_org_id = org.id
"""

_COOP_LIST_SQL = """
SELECT ci.id, ci.initiator_user_id, ci.target_type, ci.target_id,
       ci.target_owner_user_id, ci.intent_type, ci.message, ci.status, ci.version,
       ci.created_at, ci.accepted_at, ci.confirmed_at, ci.completed_at, ci.closed_at,
       ci.handling_mode, ci.assist_status, ci.accept_mode, ci.handled_by_user_id,
       ci.target_org_id, ci.initiator_contact_snapshot, ci.assist_note, ci.contact_share_consent_at,
       iu.user_no AS initiator_user_no, ip.display_name AS initiator_name,
       tu.user_no AS target_owner_user_no, tp.display_name AS target_owner_name,
       COALESCE(d.title, a.title) AS target_title,
       org.name AS target_org_name
""" + _COOP_FROM


def _coop_admin_item(r):
    return {
        "id": r["id"],
        "initiatorUserId": r["initiator_user_id"],
        "initiatorUserNo": r.get("initiator_user_no"),
        "initiatorName": r.get("initiator_name"),
        "targetOwnerUserId": r.get("target_owner_user_id"),
        "targetOwnerUserNo": r.get("target_owner_user_no"),
        "targetOwnerName": r.get("target_owner_name"),
        "targetType": r["target_type"],
        "targetId": r["target_id"],
        "targetTitle": r.get("target_title"),
        "intentType": r.get("intent_type"),
        "message": r.get("message"),
        "status": r["status"],
        "handlingMode": r.get("handling_mode") or "direct",
        "assistStatus": r.get("assist_status"),
        "acceptMode": r.get("accept_mode"),
        "handledByUserId": r.get("handled_by_user_id"),
        "targetOrgId": r.get("target_org_id"),
        "targetOrgName": r.get("target_org_name"),
        "initiatorContact": r.get("initiator_contact_snapshot"),
        "assistNote": r.get("assist_note"),
        "contactShareConsentAt": (
            r["contact_share_consent_at"].isoformat()
            if r.get("contact_share_consent_at") else None
        ),
        "version": r["version"],
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "acceptedAt": r["accepted_at"].isoformat() if r.get("accepted_at") else None,
        "confirmedAt": r["confirmed_at"].isoformat() if r.get("confirmed_at") else None,
        "completedAt": r["completed_at"].isoformat() if r.get("completed_at") else None,
        "closedAt": r["closed_at"].isoformat() if r.get("closed_at") else None,
    }


def list_cooperations_admin(args) -> dict:
    """GET /admin/cooperations —— 只读列表：status/handlingMode/assistStatus 过滤 + keyword。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip().lower()
    handling_mode = (args.get("handlingMode") or "").strip().lower()
    assist_status = (args.get("assistStatus") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where, params = [], []
    if status:
        where.append("ci.status = %s")
        params.append(status)
    if handling_mode:
        where.append("ci.handling_mode = %s")
        params.append(handling_mode)
    if assist_status:
        where.append("ci.assist_status = %s")
        params.append(assist_status)
    if keyword:
        like = f"%{keyword}%"
        where.append(
            "(ci.message ILIKE %s OR ip.display_name ILIKE %s OR tp.display_name ILIKE %s"
            " OR COALESCE(d.title, a.title) ILIKE %s OR org.name ILIKE %s)"
        )
        params.extend([like] * 5)
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


# ── P0-5 成果/需求全量管理列表（后台管理页数据源，任意状态可读） ──

_ACH_STATUS_LABELS = {
    "draft": "草稿", "pending_review": "待审核",
    "published": "已发布", "offline": "已下架", "rejected": "已驳回",
}
_DMD_STATUS_LABELS = {
    "draft": "草稿", "pending_review": "待审核",
    "published": "已发布", "matched": "对接中",
    "closed": "已关闭", "rejected": "已驳回",
}


def _ach_admin_item(r) -> dict:
    status = r["status"]
    owner_id = r.get("owner_user_id")
    return {
        "id": r["id"],
        "title": r["title"],
        "status": status,
        "statusLabel": _ACH_STATUS_LABELS.get(status, status),
        "version": r["version"],
        "categoryName": r.get("category_name"),
        "categoryCode": r.get("category_code"),
        "orgName": r.get("source_org_name"),
        "ownerUserId": owner_id,
        "platformAssisted": owner_id is None,
        "submitterUserNo": r.get("submitter_user_no"),
        "submitterName": r.get("submitter_name"),
        "viewCount": int(r.get("view_count") or 0),
        "techIntro": (r.get("tech_intro") or "")[:120],
        "rejectReason": r.get("reject_reason"),
        "publishedAt": r["published_at"].isoformat() if r.get("published_at") else None,
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def list_achievements_admin(args) -> dict:
    """GET /admin/achievements —— 全量成果列表（status/categoryCode/keyword 过滤 + 分页）。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip()
    category_code = (args.get("categoryCode") or "").strip()
    keyword = (args.get("keyword") or "").strip()

    where = ["a.deleted_at IS NULL"]
    params = []
    if status:
        where.append("a.status = %s")
        params.append(status)
    if category_code:
        where.append("c.code = %s")
        params.append(category_code)
    if keyword:
        like = f"%{keyword}%"
        where.append("(a.title ILIKE %s OR a.source_org_name ILIKE %s)")
        params.extend([like, like])
    where_sql = " WHERE " + " AND ".join(where)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            {where_sql}
            """,
            params,
        )
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT a.id, a.title, a.status, a.version, a.tech_intro, a.source_org_name,
                   a.view_count, a.reject_reason, a.published_at, a.created_at, a.updated_at,
                   a.owner_user_id,
                   c.name AS category_name, c.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            LEFT JOIN app_user u ON a.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            {where_sql}
            ORDER BY a.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    return _page_of(rows, page, page_size, total, _ach_admin_item)


def get_achievement_admin(ach_id: int) -> dict:
    """GET /admin/achievements/{id} —— 成果详情（任意状态，含发明人与审核信息）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT a.*, c.name AS category_name, c.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            LEFT JOIN app_user u ON a.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE a.id = %s AND a.deleted_at IS NULL
            """,
            (ach_id,),
        )
        row = cur.fetchone()
        if not row:
            raise bad_request("成果不存在")
        cur.execute(
            """
            SELECT i.name, i.org_name, ai.sort_order, ai.contribution
            FROM achievement_inventor ai
            JOIN inventor i ON ai.inventor_id = i.id
            WHERE ai.achievement_id = %s
            ORDER BY ai.sort_order
            """,
            (ach_id,),
        )
        inventors = cur.fetchall() or []

    detail = _ach_admin_item(row)
    detail.update({
        "techIntro": row.get("tech_intro"),
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": row.get("maturity_desc"),
        "contactName": row.get("contact_name"),
        "contactPhone": row.get("contact_phone"),
        "contactEmail": row.get("contact_email"),
        "inventors": [
            {
                "name": inv["name"],
                "orgName": inv.get("org_name"),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
    })
    innovations = row.get("innovation_points")
    if innovations and isinstance(innovations, str):
        try:
            innovations = json.loads(innovations)
        except (ValueError, TypeError):
            innovations = []
    detail["innovationPoints"] = innovations if isinstance(innovations, list) else []
    return detail


def _dmd_admin_item(r) -> dict:
    status = r["status"]
    budget = None
    if r.get("budget_min_wan") is not None or r.get("budget_max_wan") is not None:
        lo = r.get("budget_min_wan")
        hi = r.get("budget_max_wan")
        if lo is not None and hi is not None:
            budget = f"{int(lo)}万-{int(hi)}万元"
        elif lo is not None:
            budget = f"{int(lo)}万元以上"
        else:
            budget = f"{int(hi)}万元以内"
    return {
        "id": r["id"],
        "title": r["title"],
        "status": status,
        "statusLabel": _DMD_STATUS_LABELS.get(status, status),
        "version": r["version"],
        "categoryName": r.get("category_name"),
        "categoryCode": r.get("category_code"),
        "orgName": r.get("org_name"),
        "region": r.get("region"),
        "budget": budget,
        "budgetNegotiable": bool(r.get("budget_negotiable")),
        "ownerUserId": r.get("owner_user_id"),
        "platformAssisted": r.get("owner_user_id") is None,
        "submitterUserNo": r.get("submitter_user_no"),
        "submitterName": r.get("submitter_name"),
        "rejectReason": r.get("reject_reason"),
        "publishedAt": r["published_at"].isoformat() if r.get("published_at") else None,
        "createdAt": r["created_at"].isoformat() if r.get("created_at") else None,
        "updatedAt": r["updated_at"].isoformat() if r.get("updated_at") else None,
    }


def list_demands_admin(args) -> dict:
    """GET /admin/demands —— 全量需求列表（status/categoryCode/keyword 过滤 + 分页）。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip()
    category_code = (args.get("categoryCode") or "").strip()
    keyword = (args.get("keyword") or "").strip()

    where = ["d.deleted_at IS NULL"]
    params = []
    if status:
        where.append("d.status = %s")
        params.append(status)
    if category_code:
        where.append("dc.code = %s")
        params.append(category_code)
    if keyword:
        like = f"%{keyword}%"
        where.append("(d.title ILIKE %s OR o.name ILIKE %s)")
        params.extend([like, like])
    where_sql = " WHERE " + " AND ".join(where)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT COUNT(*) AS c
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            {where_sql}
            """,
            params,
        )
        total = int(cur.fetchone()["c"])
        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT d.id, d.title, d.status, d.version, d.region,
                   d.budget_min_wan, d.budget_max_wan, d.budget_negotiable,
                   d.reject_reason, d.published_at, d.created_at, d.updated_at,
                   d.owner_user_id,
                   o.name AS org_name, dc.name AS category_name, dc.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            LEFT JOIN app_user u ON d.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            {where_sql}
            ORDER BY d.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    return _page_of(rows, page, page_size, total, _dmd_admin_item)


def get_demand_admin(demand_id: int) -> dict:
    """GET /admin/demands/{id} —— 需求详情（任意状态，含联系方式与标签）。"""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT d.*, o.name AS org_name, o.intro AS org_intro,
                   dc.name AS category_name, dc.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            LEFT JOIN app_user u ON d.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE d.id = %s AND d.deleted_at IS NULL
            """,
            (demand_id,),
        )
        row = cur.fetchone()
        if not row:
            code, message, status = TT_DMD_40401
            raise BizError(code, message, status)
        cur.execute(
            """
            SELECT t.name FROM demand_tag_relation r
            JOIN demand_tag t ON r.tag_id = t.id
            WHERE r.demand_id = %s ORDER BY t.id
            """,
            (demand_id,),
        )
        tags = [r["name"] for r in (cur.fetchall() or [])]

    detail = _dmd_admin_item(row)
    detail.update({
        "description": row.get("description"),
        "coopMode": row.get("coop_mode"),
        "orgIntro": row.get("org_intro"),
        "tags": tags,
        "contactName": row.get("contact_name"),
        "contactTitle": row.get("contact_title"),
        "contactPhone": row.get("contact_phone"),
        "contactEmail": row.get("contact_email"),
    })
    return detail


# ── P0-4 Users 管理端（READ ONLY，禁用功能 P1） ─────────────

_USER_FROM = """
FROM app_user u
LEFT JOIN user_profile p ON u.id = p.user_id
LEFT JOIN institution o ON p.org_id = o.id
"""

_USER_LIST_SQL = """
SELECT u.id, u.user_no, u.status, u.created_at, u.updated_at,
       p.display_name, p.user_type, p.phone, p.email, p.org_id, p.org_title,
       o.name AS org_name,
       (SELECT COALESCE(array_agg(ur.role_code ORDER BY ur.role_code), ARRAY[]::varchar[])
          FROM user_role ur WHERE ur.user_id = u.id) AS roles,
       (SELECT COALESCE(json_agg(t ORDER BY t.id), '[]'::json)
          FROM (SELECT m.id, m.org_id, i.name AS org_name, m.role, m.status, m.version
                  FROM organization_membership m
                  JOIN institution i ON i.id = m.org_id
                 WHERE m.user_id = u.id AND m.status = 'active') t) AS memberships
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
        "orgId": r.get("org_id"),
        "orgName": r.get("org_name"),
        "orgTitle": (r.get("org_title") or "").strip(),
        "roles": list(r.get("roles") or []),
        "organizationMemberships": [
            {"id": m["id"], "orgId": m["org_id"], "orgName": m["org_name"],
             "role": m["role"], "status": m["status"], "version": m["version"]}
            for m in (r.get("memberships") or [])
        ],
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
        where.append("(u.user_no ILIKE %s OR p.display_name ILIKE %s OR o.name ILIKE %s)")
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

def _admin_owner_user_id(cur, body: dict, org_id: int):
    """后台代录归属用户解析。

    未传 ownerUserId = 平台代录：owner_user_id 落 NULL（真实机构尚无平台账号），
    内容进入「平台协助对接」流程；传了则要求用户存在、启用且绑定所选机构。
    """
    raw_owner_id = body.get("ownerUserId")
    if raw_owner_id is None:
        return None

    try:
        owner_user_id = int(raw_owner_id)
    except (ValueError, TypeError):
        raise bad_request("ownerUserId 必须是整数")

    cur.execute(
        """
        SELECT u.id
        FROM app_user u
        JOIN user_profile p ON p.user_id = u.id
        WHERE u.id = %s
          AND u.status = 'active'
          AND u.deleted_at IS NULL
          AND p.org_id = %s
        """,
        (owner_user_id, org_id),
    )
    if not cur.fetchone():
        raise bad_request("归属用户不存在、已禁用，或未绑定所选机构")

    return owner_user_id


def create_achievement_admin(
    admin_user: dict,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员新增成果。

    默认状态为 draft；后续仍通过 submit + approve 流程发布。
    传 ownerUserId 指定归属人；未传 = 平台代录（owner NULL，进入平台协助对接），
    录入人 created_by_user_id 恒为当前管理员。
    """
    fields, inventor_refs = _parse_upsert_body(body, partial=False)

    min_price = fields.get("price_min_wan")
    max_price = fields.get("price_max_wan")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise bad_request("priceMinWan 不能大于 priceMaxWan")

    with get_cursor(commit=True) as cur:
        org_id = fields.get("org_id")
        if org_id is None:
            raise bad_request("后台录入必须选择所属机构")
        if fields.get("category_id") is None:
            raise bad_request("后台录入必须选择成果分类")
        owner_user_id = _admin_owner_user_id(cur, body, org_id)
        _validate_refs(cur, fields)

        cur.execute(
            """
            INSERT INTO achievement
                (
                    owner_user_id,
                    created_by_user_id,
                    title,
                    category_id,
                    org_id,
                    source_org_name,
                    tech_intro,
                    tech_route,
                    maturity_level,
                    maturity_desc,
                    application_fields,
                    innovation_points,
                    pricing_mode,
                    price_min_wan,
                    price_max_wan,
                    contact_name,
                    contact_title,
                    contact_phone,
                    contact_email,
                    contact_wechat,
                    status
                )
            VALUES
                (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, 'draft'
                )
            RETURNING id
            """,
            (
                owner_user_id,
                admin_user["userId"],
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

        # cur=cur：成果写入和审计日志处于同一个事务
        audit_record(
            "achievement.admin_create",
            "achievement",
            resource_id=ach_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={
                "title": fields.get("title"),
                "ownerUserId": owner_user_id,
                "platformAssisted": owner_user_id is None,
                "status": "draft",
            },
            request_id=request_id,
            cur=cur,
        )

    return get_achievement_admin(ach_id)


def update_achievement_admin(
    admin_user: dict,
    ach_id: int,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员编辑任意未删除成果。

    不允许通过编辑接口直接变更 owner、status、审核信息；
    status 仍应由审核/上下架接口处理。
    """
    fields, inventor_refs = _parse_upsert_body(body, partial=True)

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("编辑成果必须携带正整数 version")

    if not fields and inventor_refs is None:
        raise bad_request("没有可更新的成果字段")

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT id, version, price_min_wan, price_max_wan
            FROM achievement
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (ach_id,),
        )
        current = cur.fetchone()

        if not current:
            raise achievement_not_found()

        _validate_refs(cur, fields)

        # PATCH 只传其中一个报价时，也要同已有值一起校验范围。
        min_price = fields.get("price_min_wan", current.get("price_min_wan"))
        max_price = fields.get("price_max_wan", current.get("price_max_wan"))

        if min_price is not None and max_price is not None:
            if float(min_price) > float(max_price):
                raise bad_request("priceMinWan 不能大于 priceMaxWan")

        set_clauses = [f"{column}=%s" for column in fields]
        set_clauses.append("version=version+1")

        cur.execute(
            f"""
            UPDATE achievement
            SET {", ".join(set_clauses)}
            WHERE id = %s
              AND version = %s
              AND deleted_at IS NULL
            """,
            list(fields.values()) + [ach_id, version],
        )

        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        # 传 [] 表示清空发明人；没传 inventorRefs 则不处理。
        if inventor_refs is not None:
            _sync_inventors(cur, ach_id, inventor_refs)

        audit_record(
            "achievement.admin_update",
            "achievement",
            resource_id=ach_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"updatedFields": list(fields.keys())},
            request_id=request_id,
            cur=cur,
        )

    return get_achievement_admin(ach_id)

# ── 后台需求新增 / 编辑 ─────────────────────────────────────

def create_demand_admin(
    admin_user: dict,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员新增需求。

    默认状态为 draft；后续仍经过 submit + approve 才发布。
    传 ownerUserId 指定需求归属人；未传 = 平台代录（owner NULL，进入平台协助对接），
    录入人 created_by_user_id 恒为当前管理员。
    """
    fields, tags = _parse_demand_upsert_body(body, partial=False)

    min_budget = fields.get("budget_min_wan")
    max_budget = fields.get("budget_max_wan")
    if min_budget is not None and max_budget is not None:
        if min_budget > max_budget:
            raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

    with get_cursor(commit=True) as cur:
        org_id = fields.get("org_id")
        if org_id is None:
            raise bad_request("后台录入必须选择所属机构")
        if fields.get("category_id") is None:
            raise bad_request("后台录入必须选择需求分类")
        owner_user_id = _admin_owner_user_id(cur, body, org_id)

        # orgName / categoryName 自动转换或创建对应机构、分类。
        _resolve_demand_name_refs(cur, fields)
        _validate_demand_refs(cur, fields)

        cur.execute(
            """
            INSERT INTO demand
                (
                    owner_user_id,
                    created_by_user_id,
                    title,
                    category_id,
                    org_id,
                    description,
                    region,
                    coop_mode,
                    budget_min_wan,
                    budget_max_wan,
                    budget_negotiable,
                    expect_deadline,
                    deadline_desc,
                    contact_name,
                    contact_title,
                    contact_phone,
                    contact_email,
                    contact_wechat,
                    status
                )
            VALUES
                (
                    %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    %s, %s, 'draft'
                )
            RETURNING id
            """,
            (
                owner_user_id,
                admin_user["userId"],
                fields.get("title"),
                fields.get("category_id"),
                fields.get("org_id"),
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
            _sync_demand_tags(cur, demand_id, tags)

        audit_record(
            "demand.admin_create",
            "demand",
            resource_id=demand_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={
                "title": fields.get("title"),
                "ownerUserId": owner_user_id,
                "platformAssisted": owner_user_id is None,
                "status": "draft",
            },
            request_id=request_id,
            cur=cur,
        )

    return get_demand_admin(demand_id)


def update_demand_admin(
    admin_user: dict,
    demand_id: int,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员编辑任意未删除需求。

    不允许用该接口直接修改 owner、status、审核结果。
    status 仍由审核、取消、关闭等专用接口处理。
    """
    fields, tags = _parse_demand_upsert_body(body, partial=True)

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("编辑需求必须携带正整数 version")

    if not fields and tags is None:
        raise bad_request("没有可更新的需求字段")

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT id, version, budget_min_wan, budget_max_wan
            FROM demand
            WHERE id = %s
              AND deleted_at IS NULL
            """,
            (demand_id,),
        )
        current = cur.fetchone()

        if not current:
            raise demand_not_found()

        # orgName / categoryName 在这里转成真正的 ID。
        _resolve_demand_name_refs(cur, fields)
        _validate_demand_refs(cur, fields)

        # PATCH 只传一个预算字段时，仍与数据库中的另一个预算字段一起校验。
        min_budget = fields.get("budget_min_wan", current.get("budget_min_wan"))
        max_budget = fields.get("budget_max_wan", current.get("budget_max_wan"))

        if min_budget is not None and max_budget is not None:
            if float(min_budget) > float(max_budget):
                raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

        set_clauses = [f"{column}=%s" for column in fields]
        set_clauses.append("version=version+1")

        cur.execute(
            f"""
            UPDATE demand
            SET {", ".join(set_clauses)}
            WHERE id = %s
              AND version = %s
              AND deleted_at IS NULL
            """,
            list(fields.values()) + [demand_id, version],
        )

        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        # 传 tags: [] 表示清空标签；不传 tags 则不改标签。
        if tags is not None:
            _sync_demand_tags(cur, demand_id, tags)

        audit_record(
            "demand.admin_update",
            "demand",
            resource_id=demand_id,
            actor_user_id=admin_user["userId"],
            actor_user_no=admin_user.get("userNo", ""),
            details={"updatedFields": list(fields.keys())},
            request_id=request_id,
            cur=cur,
        )

    return get_demand_admin(demand_id)


# ── 代无账号内容提交审核（平台协助闭环：owner NULL 时无人可 submit） ──

def submit_achievement_admin(admin_user: dict, ach_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/achievements/{id}/submit —— 代平台代录成果提交审核。

    仅允许 owner_user_id IS NULL 的内容（有归属用户的草稿应由归属用户自行提交）。
    draft / rejected → pending_review，随后走既有 approve / reject 审核流。
    """
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status, version, owner_user_id FROM achievement WHERE id=%s AND deleted_at IS NULL",
            (ach_id,),
        )
        row = cur.fetchone()
        if not row:
            raise achievement_not_found()
        if row["owner_user_id"] is not None:
            raise bad_request("该成果有归属用户，应由归属用户自行提交审核")
        if row["status"] not in ("draft", "rejected"):
            raise achievement_conflict(
                f"当前状态 {row['status']} 不允许提交审核（要求 draft/rejected）"
            )
        cur.execute(
            "UPDATE achievement SET status='pending_review', version=version+1 WHERE id=%s AND version=%s",
            (ach_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        audit_record(
            "achievement.admin_submit", "achievement", resource_id=ach_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": row["status"], "to": "pending_review", "onBehalfOf": "platform"},
            request_id=request_id, cur=cur,
        )
    return {"status": "pending_review"}


def submit_demand_admin(admin_user: dict, demand_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/demands/{id}/submit —— 代平台代录需求提交审核（仅 owner NULL）。"""
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "SELECT status, version, owner_user_id FROM demand WHERE id=%s AND deleted_at IS NULL",
            (demand_id,),
        )
        row = cur.fetchone()
        if not row:
            raise demand_not_found()
        if row["owner_user_id"] is not None:
            raise bad_request("该需求有归属用户，应由归属用户自行提交审核")
        if row["status"] not in ("draft", "rejected"):
            raise demand_conflict(
                f"当前状态 {row['status']} 不允许提交审核（要求 draft/rejected）"
            )
        cur.execute(
            "UPDATE demand SET status='pending_review', version=version+1 WHERE id=%s AND version=%s",
            (demand_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        audit_record(
            "demand.admin_submit", "demand", resource_id=demand_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": row["status"], "to": "pending_review", "onBehalfOf": "platform"},
            request_id=request_id, cur=cur,
        )
    return {"status": "pending_review"}
