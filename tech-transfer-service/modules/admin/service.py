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

from core.contact_validation import validate_contact_way
from core.errors import (
    TT_ACH_40901,
    TT_ADMIN_40001,
    TT_DMD_40401,
    TT_DMD_40901,
    BizError,
    achievement_not_found,
    bad_request,
    conflict,
    coop_conflict,
    coop_forbidden,
    coop_not_found,
    demand_not_found,
    forbidden,
)
from db import get_cursor
from modules.achievement.content import load_content, sync_content
from modules.achievement.service import (
    _parse_upsert_body,
    _sync_inventors,
    _validate_refs,
)
from modules.audit.service import record as audit_record
from modules.cooperation.service import (
    _release_target_slot,
    _reserve_target_slot,
)
from modules.demand.service import (
    _parse_upsert_body as _parse_demand_upsert_body,
)
from modules.demand.service import (
    _resolve_name_refs as _resolve_demand_name_refs,
)
from modules.demand.service import (
    _sync_tags as _sync_demand_tags,
)
from modules.demand.service import (
    _validate_refs as _validate_demand_refs,
)
from modules.notification.service import emit_notification


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


def scope_org_ids(scope: dict) -> list[int]:
    """Canonical institutions an org-admin may manage; empty for platform admins."""
    if scope.get("isPlatformAdmin"):
        return []
    raw = scope.get("orgIds")
    if raw:
        return [int(item) for item in raw]
    if scope.get("orgId") is not None:
        return [int(scope["orgId"])]
    return []


def _sql_in(column: str, values: list) -> tuple[str, list]:
    placeholders = ",".join(["%s"] * len(values))
    return f"{column} IN ({placeholders})", list(values)


def _coop_org_visibility_sql(scope: dict) -> tuple[str, list]:
    org_ids = scope_org_ids(scope)
    if not org_ids:
        raise forbidden("机构管理员未绑定有效机构")
    placeholders = ",".join(["%s"] * len(org_ids))
    sql = (
        f"(COALESCE(ci.target_org_id, d.org_id, a.org_id) IN ({placeholders})"
        f" OR EXISTS (SELECT 1 FROM organization_membership m"
        f" WHERE m.user_id = ci.initiator_user_id AND m.status = 'active'"
        f" AND m.org_id IN ({placeholders})))"
    )
    return sql, list(org_ids) + list(org_ids)


def _user_membership_scope_sql(scope: dict) -> tuple[str, list]:
    org_ids = scope_org_ids(scope)
    if not org_ids:
        raise forbidden("机构管理员未绑定有效机构")
    placeholders = ",".join(["%s"] * len(org_ids))
    sql = (
        "EXISTS (SELECT 1 FROM organization_membership om"
        " WHERE om.user_id = u.id AND om.status = 'active'"
        f" AND om.org_id IN ({placeholders}))"
    )
    return sql, list(org_ids)


def append_org_row_filter(where: list, params: list, scope: dict, column: str = "org_id") -> None:
    org_ids = scope_org_ids(scope)
    if not org_ids:
        return
    clause, values = _sql_in(column, org_ids)
    where.append(clause)
    params.extend(values)


def append_content_scope(where: list, params: list, scope: dict, alias: str) -> None:
    """Filter writes with the same visibility as list/detail, including unassigned legacy rows."""
    predicate, values = organization_content_scope(scope, alias)
    if predicate:
        where.append(predicate)
        params.extend(values)


def _restrict_org_admin_fields(scope: dict, fields: dict, *, is_create: bool, kind: str) -> None:
    if scope.get("isPlatformAdmin"):
        return
    fields.pop("org_name", None)
    fields.pop("org_intro", None)
    fields.pop("org_name_snapshot", None)
    if kind == "achievement":
        fields.pop("source_org_name", None)
    if not is_create:
        fields.pop("org_id", None)
        return
    requested = fields.get("org_id")
    org_ids = scope_org_ids(scope)
    if requested is not None and org_ids and int(requested) not in org_ids:
        fields.pop("org_id", None)


def list_content_organizations_admin(scope: dict) -> list[dict]:
    """后台内容录入使用的已启用机构（统一机构目录 institution）。

    平台管理员返回全部活跃机构；机构管理员只返回本机构
    （创建/编辑内容的机构归属由服务端强制为本机构，此处仅控制下拉展示）。
    """
    org_ids = scope_org_ids(scope)
    if org_ids:
        clause, params = _sql_in("id", org_ids)
        org_filter = f" AND {clause}"
    else:
        org_filter = ""
        params = []
    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT id, name, kind
            FROM institution
            WHERE status = 'active'{org_filter}
            ORDER BY name, id
            """,
            params,
        )
        return [
            {"id": row["id"], "name": row["name"], "kind": row["kind"]}
            for row in (cur.fetchall() or [])
        ]


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
            "SELECT status, version, owner_user_id FROM achievement WHERE id = %s AND deleted_at IS NULL",
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
        if row.get("owner_user_id"):
            emit_notification(cur, recipient_user_id=row["owner_user_id"], category="review",
                event_type=f"achievement.{action}", source_type="achievement", source_id=ach_id,
                title="成果审核已通过" if action == "approve" else "成果审核未通过", body=reason or None,
                target_path="/subpackages/tech-transfer/pages/mine-list/mine-list")

        audit_record(
            f"achievement.{action}", "achievement", resource_id=ach_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": "pending_review", "to": to_status, "reason": reason or None},
            request_id=request_id, cur=cur,
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
            "SELECT status, version, owner_user_id FROM demand WHERE id = %s AND deleted_at IS NULL",
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
        if row.get("owner_user_id"):
            emit_notification(cur, recipient_user_id=row["owner_user_id"], category="review",
                event_type=f"demand.{action}", source_type="demand", source_id=demand_id,
                title="需求审核已通过" if action == "approve" else "需求审核未通过", body=reason or None,
                target_path="/subpackages/tech-transfer/pages/mine-list/mine-list")

        audit_record(
            f"demand.{action}", "demand", resource_id=demand_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": "pending_review", "to": to_status, "reason": reason or None},
            request_id=request_id, cur=cur,
        )

    return {"status": to_status}


# ── 下架 / 关闭（管理端对已发布内容做下线，机构范围与列表一致）──

ACHIEVEMENT_OFFLINE_REASON_CODES = (
    "cooperated", "expired", "superseded", "duplicate", "no_longer_available", "other",
)
DEMAND_CLOSE_REASON_CODES = (
    "fulfilled", "budget_changed", "timeline_changed", "duplicate", "no_longer_needed", "other",
)

def offline_achievement_admin(scope: dict, ach_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/achievements/{id}/offline —— 管理端下架已发布成果（published → offline）。"""
    version = (body or {}).get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    reason_code = (body or {}).get("reasonCode") or None
    if reason_code and reason_code not in ACHIEVEMENT_OFFLINE_REASON_CODES:
        raise bad_request("reasonCode 不合法")
    reason = str((body or {}).get("reason") or "").strip()[:500] or None

    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [ach_id]
        append_content_scope(where, params, scope, "achievement")
        cur.execute(
            f"SELECT status, owner_user_id FROM achievement WHERE {' AND '.join(where)}",
            params,
        )
        row = cur.fetchone()
        if not row:
            raise achievement_not_found()
        if row["status"] != "published":
            code, message, http_status = TT_ACH_40901
            raise BizError(code, f"当前状态 {row['status']} 不允许下架（要求 published）", http_status)

        cur.execute(
            """
            UPDATE achievement
            SET status = 'offline', version = version + 1,
                offline_reason_code = COALESCE(%s, offline_reason_code),
                offline_reason_note = COALESCE(%s, offline_reason_note)
            WHERE id = %s AND version = %s
            """,
            (reason_code, reason, ach_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        if row.get("owner_user_id"):
            emit_notification(cur, recipient_user_id=row["owner_user_id"], category="review",
                event_type="achievement.offline", source_type="achievement", source_id=ach_id,
                title="成果已被下架", body=reason,
                target_path="/subpackages/tech-transfer/pages/mine-list/mine-list")

        audit_record(
            "achievement.offline", "achievement", resource_id=ach_id,
            actor_user_id=scope["userId"], actor_user_no=scope.get("userNo", ""),
            details={"from": "published", "to": "offline", "reason": reason, "reasonCode": reason_code},
            request_id=request_id, cur=cur,
        )

    return {"status": "offline"}

def close_demand_admin(scope: dict, demand_id: int, body: dict, request_id=None) -> dict:
    """POST /admin/demands/{id}/close —— 管理端关闭已发布/对接中的需求。"""
    version = (body or {}).get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    reason_code = (body or {}).get("reasonCode") or None
    reason_note = None
    if reason_code:
        if reason_code not in DEMAND_CLOSE_REASON_CODES:
            raise bad_request("reasonCode 不合法")
        reason_note = str((body or {}).get("reasonNote") or "").strip()[:500] or None

    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [demand_id]
        append_content_scope(where, params, scope, "demand")
        cur.execute(
            f"SELECT status, owner_user_id FROM demand WHERE {' AND '.join(where)}",
            params,
        )
        row = cur.fetchone()
        if not row:
            raise demand_not_found()
        if row["status"] not in ("published", "matched"):
            code, message, http_status = TT_DMD_40901
            raise BizError(code, f"当前状态 {row['status']} 不允许关闭（要求 published/matched）", http_status)

        cur.execute(
            """
            UPDATE demand
            SET status = 'closed', version = version + 1,
                closure_reason_code = COALESCE(%s, closure_reason_code),
                closure_reason_note = COALESCE(%s, closure_reason_note)
            WHERE id = %s AND version = %s
            """,
            (reason_code, reason_note, demand_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        if row.get("owner_user_id"):
            emit_notification(cur, recipient_user_id=row["owner_user_id"], category="review",
                event_type="demand.close", source_type="demand", source_id=demand_id,
                title="需求已被关闭", body=reason_note,
                target_path="/subpackages/tech-transfer/pages/mine-list/mine-list")

        audit_record(
            "demand.close", "demand", resource_id=demand_id,
            actor_user_id=scope["userId"], actor_user_no=scope.get("userNo", ""),
            details={"from": row["status"], "to": "closed", "reasonCode": reason_code, "reasonNote": reason_note},
            request_id=request_id, cur=cur,
        )

    return {"status": "closed"}

# ── 软删除（admin 删除走 UPDATE deleted_at，保留行用于追溯；列表已过滤 deleted_at IS NULL）──

def soft_delete_achievement_admin(scope: dict, ach_id: int, request_id=None) -> dict:
    """管理员软删除成果：置 deleted_at=NOW()，不物理删除，保留审计追溯。

    所有列表/详情查询均带 deleted_at IS NULL 过滤，软删除后对终端立即不可见。
    """
    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [ach_id]
        append_content_scope(where, params, scope, "achievement")
        cur.execute(
            f"""
            UPDATE achievement
            SET deleted_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE {" AND ".join(where)}
            """,
            params,
        )
        if cur.rowcount == 0:
            raise achievement_not_found()
        audit_record(
            "achievement.admin_delete", "achievement", resource_id=ach_id,
            actor_user_id=scope["userId"], actor_user_no=scope.get("userNo", ""),
            details={"soft": True},
            request_id=request_id, cur=cur,
        )
    return {"id": ach_id, "deleted": True}


def soft_delete_demand_admin(scope: dict, demand_id: int, request_id=None) -> dict:
    """管理员软删除需求：置 deleted_at=NOW()，不物理删除，保留审计追溯。"""
    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [demand_id]
        append_content_scope(where, params, scope, "demand")
        cur.execute(
            f"""
            UPDATE demand
            SET deleted_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE {" AND ".join(where)}
            """,
            params,
        )
        if cur.rowcount == 0:
            raise demand_not_found()
        audit_record(
            "demand.admin_delete", "demand", resource_id=demand_id,
            actor_user_id=scope["userId"], actor_user_no=scope.get("userNo", ""),
            details={"soft": True},
            request_id=request_id, cur=cur,
        )
    return {"id": demand_id, "deleted": True}


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
    TT_COOP_40401,
    TT_INST_40001,
    TT_INST_40401,
    TT_INST_40901,
    not_found,
)

INST_KINDS = (
    "platform", "invest", "service",
    "university", "institute", "enterprise", "other",
)
PLATFORM_TYPE_KEYS = ("poc", "pilot", "other")
PLATFORM_TYPE_LABELS = {
    "poc": "概念验证中心",
    "pilot": "中小试基地",
    "other": "其他",
}
INST_STATUSES = ("active", "disabled")

# Institution PATCH 可编辑字段（camel → snake）；kind/source 溯源/id/时间戳不可改
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
              (SELECT COUNT(*) FROM organization_application
                WHERE status = 'pending')                                        AS pending_organization_applications,
              (SELECT COUNT(*) FROM organization_admin_application
                WHERE status = 'pending')                                        AS pending_organization_admin_applications,
              (SELECT COUNT(*) FROM organization_membership_application
                WHERE status = 'pending')                                        AS pending_membership_applications,
              (SELECT COUNT(*) FROM cooperation_intent
                WHERE status = 'pending')                                        AS pending_cooperations,
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

    pending_total = sum(int(r[key]) for key in (
        "pending_achievements", "pending_demands", "pending_organization_applications",
        "pending_organization_admin_applications", "pending_membership_applications", "pending_cooperations",
    ))
    return {
        "users": int(r["users"]),
        "achievements": int(r["achievements"]),
        "demands": int(r["demands"]),
        "cooperations": int(r["cooperations"]),
        "pendingAchievements": int(r["pending_achievements"]),
        "pendingDemands": int(r["pending_demands"]),
        "pendingOrganizationApplications": int(r["pending_organization_applications"]),
        "pendingOrganizationAdminApplications": int(r["pending_organization_admin_applications"]),
        "pendingMembershipApplications": int(r["pending_membership_applications"]),
        "pendingCooperations": int(r["pending_cooperations"]),
        "pendingTotal": pending_total,
        "institutions": int(r["institutions"]),
        "achievementStatusCounts": ach_status,
        "demandStatusCounts": dmd_status,
    }


def _notification_categories(*, review: int, cooperation: int, organization: int, membership: int) -> dict:
    categories = {
        "review": int(review),
        "cooperation": int(cooperation),
        "organization": int(organization),
        "membership": int(membership),
    }
    return {"total": sum(categories.values()), "categories": categories}


def notification_summary(scope: dict | None = None) -> dict:
    """轻量后台角标：仅聚合待处理数量，不读取待办正文或列表。

    平台管理员看全平台待办；机构管理员只看本机构成果/需求待审、相关对接，
    以及本机构成员认证申请。机构入驻/机构管理员申请仍属平台审核范围。
    """
    if not scope or scope.get("isPlatformAdmin"):
        data = dashboard_summary()
        return _notification_categories(
            review=data["pendingAchievements"] + data["pendingDemands"],
            cooperation=data["pendingCooperations"],
            organization=data["pendingOrganizationApplications"],
            membership=data["pendingOrganizationAdminApplications"] + data["pendingMembershipApplications"],
        )

    org_ids = scope_org_ids(scope)
    if not org_ids:
        return _notification_categories(review=0, cooperation=0, organization=0, membership=0)

    ach_pred, ach_params = organization_content_scope(scope, "a")
    dmd_pred, dmd_params = organization_content_scope(scope, "d")
    coop_sql, coop_params = _coop_org_visibility_sql(scope)
    member_clause, member_params = _sql_in("org_id", org_ids)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT
              (SELECT COUNT(*) FROM achievement a
                WHERE a.status = 'pending_review' AND a.deleted_at IS NULL
                  AND ({ach_pred})) AS pending_achievements,
              (SELECT COUNT(*) FROM demand d
                WHERE d.status = 'pending_review' AND d.deleted_at IS NULL
                  AND ({dmd_pred})) AS pending_demands,
              (SELECT COUNT(*) FROM cooperation_intent ci
                LEFT JOIN achievement a ON ci.target_type = 'achievement' AND ci.target_id = a.id
                LEFT JOIN demand d ON ci.target_type = 'demand' AND ci.target_id = d.id
                WHERE ci.status = 'pending' AND ({coop_sql})) AS pending_cooperations,
              (SELECT COUNT(*) FROM organization_membership_application
                WHERE status = 'pending' AND {member_clause}) AS pending_membership_applications
            """,
            ach_params + dmd_params + coop_params + member_params,
        )
        row = cur.fetchone() or {}

    return _notification_categories(
        review=int(row.get("pending_achievements") or 0) + int(row.get("pending_demands") or 0),
        cooperation=int(row.get("pending_cooperations") or 0),
        organization=0,
        membership=int(row.get("pending_membership_applications") or 0),
    )


def dashboard_todos(limit: int = 20) -> dict:
    """Unified system-admin work queue; organization applications appear only once."""
    limit = max(1, min(int(limit or 20), 100))
    union_from = """
            FROM (
                SELECT 'achievement' AS kind, a.id, a.title,
                       COALESCE(a.updated_at, a.created_at) AS created_at
                FROM achievement a
                WHERE a.status = 'pending_review' AND a.deleted_at IS NULL
                UNION ALL
                SELECT 'demand' AS kind, d.id, d.title,
                       COALESCE(d.updated_at, d.created_at) AS created_at
                FROM demand d
                WHERE d.status = 'pending_review' AND d.deleted_at IS NULL
                UNION ALL
                SELECT 'organization_application' AS kind, a.id, a.requested_name AS title, a.created_at
                FROM organization_application a
                WHERE a.status = 'pending'
                UNION ALL
                SELECT 'organization_admin_application' AS kind, a.id,
                       CONCAT(COALESCE(u.user_no, '用户'), ' 申请成为 ', COALESCE(o.name, '机构'), ' 管理员') AS title,
                       a.created_at
                FROM organization_admin_application a
                JOIN app_user u ON u.id = a.user_id
                JOIN institution o ON o.id = a.org_id
                WHERE a.status = 'pending'
                UNION ALL
                SELECT 'membership_application' AS kind, a.id,
                       CONCAT(COALESCE(u.user_no, '用户'), ' 申请加入 ', COALESCE(o.name, '机构')) AS title,
                       a.created_at
                FROM organization_membership_application a
                JOIN app_user u ON u.id = a.user_id
                JOIN institution o ON o.id = a.org_id
                WHERE a.status = 'pending'
                UNION ALL
                SELECT 'cooperation' AS kind, c.id,
                       COALESCE(a.title, d.title, '待处理合作对接') AS title, c.created_at
                FROM cooperation_intent c
                LEFT JOIN achievement a ON c.target_type = 'achievement' AND c.target_id = a.id
                LEFT JOIN demand d ON c.target_type = 'demand' AND c.target_id = d.id
                WHERE c.status = 'pending'
            ) AS todo
    """
    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS total {union_from}")
        total = int((cur.fetchone() or {}).get("total") or 0)
        cur.execute(
            f"""
            SELECT kind, id, title, created_at
            {union_from}
            ORDER BY created_at DESC, id DESC
            LIMIT %s
            """,
            (limit,),
        )
        rows = cur.fetchall() or []

    routes = {
        "achievement": "/admin/achievements",
        "demand": "/admin/requirements",
        "organization_application": "/admin/membership-review?tab=organization",
        "organization_admin_application": "/admin/membership-review?tab=org-admin",
        "membership_application": "/admin/membership-review?tab=member",
        "cooperation": "/admin/cooperation",
    }
    labels = {
        "achievement": "成果待审",
        "demand": "需求待审",
        "organization_application": "机构入驻审核",
        "organization_admin_application": "机构管理员审核",
        "membership_application": "成员认证审核",
        "cooperation": "待处理对接",
    }
    items = [
        {
            "id": f"{row['kind']}-{row['id']}",
            "kind": row["kind"],
            "title": row.get("title") or "待处理事项",
            "label": labels[row["kind"]],
            "route": routes[row["kind"]],
            "createdAt": row.get("created_at"),
        }
        for row in rows
    ]
    return {"total": total, "list": items}


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

    from datetime import datetime, timedelta, timezone

    today = datetime.now(timezone(timedelta(hours=8))).date()
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
        item.update({
            "serialNo": int(r.get("serial_no") or 0),
            "platformType": (r.get("platform_type") or "").strip(),
            "platformTypeKey": (r.get("platform_type_key") or "other").strip(),
            "unit": (r.get("support_unit") or "").strip(),
            "functionText": (r.get("functions") or "").strip(),
            "contact": (r.get("contact_person") or "").strip(),
            "phone": (r.get("contact_mobile") or "").strip(),
            "sourceStatus": r.get("source_status"),
            "orderNum": r.get("order_num"),
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
    if "contact_mobile" in cleaned:
        cleaned["contact_mobile"] = validate_contact_way(
            cleaned["contact_mobile"], required=False, field_name="联系方式"
        )

    kind = None
    if require_kind:
        kind = (str(body.get("kind") or "").strip().lower())
        if kind not in INST_KINDS:
            code, message, status = TT_INST_40001
            raise BizError(code, f"kind 必须是 {'/'.join(INST_KINDS)}", status)
    if "platform_type_key" in cleaned:
        key = str(cleaned["platform_type_key"]).strip().lower()
        if key not in PLATFORM_TYPE_KEYS:
            code, message, status = TT_INST_40001
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
    for snake in ("name", "region", "intro", "detail_info", "label", "logo_file_id", "sort_order",
                  "user_type", "detail_activity_id", "platform_type", "platform_type_key",
                  "support_unit", "functions", "contact_person", "contact_mobile",
                  "serial_no", "source_status", "order_num"):
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


CAPITAL_IMPORT_KINDS = ("platform", "invest", "service")


def _to_int_or_none(v):
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _normalize_import_item(raw: dict) -> dict:
    if not isinstance(raw, dict):
        code, message, status = TT_INST_40001
        raise BizError(code, "导入行必须是对象", status)
    kind = str(raw.get("kind") or "").strip().lower()
    if kind not in CAPITAL_IMPORT_KINDS:
        code, message, status = TT_INST_40001
        raise BizError(code, "kind 必须是 platform/invest/service", status)
    name = str(raw.get("name") or "").strip()
    if not name:
        code, message, status = TT_INST_40001
        raise BizError(code, "机构名称 name 必填", status)
    platform_type_key = str(raw.get("platformTypeKey") or raw.get("platform_type_key") or "").strip().lower()
    if kind == "platform":
        if platform_type_key not in ("poc", "pilot", "other"):
            platform_type_key = "poc"
    else:
        platform_type_key = platform_type_key or "other"
    source_pk = raw.get("sourcePk") if raw.get("sourcePk") is not None else raw.get("source_pk")
    source_pk = _to_int_or_none(source_pk)
    sort_order = _to_int_or_none(
        raw.get("sortOrder") if raw.get("sortOrder") is not None else raw.get("sort_order")
    )
    serial_no = _to_int_or_none(
        raw.get("serialNo") if raw.get("serialNo") is not None else raw.get("serial_no")
    )
    source_status = _to_int_or_none(
        raw.get("sourceStatus") if raw.get("sourceStatus") is not None else raw.get("source_status")
    )
    order_num = _to_int_or_none(
        raw.get("orderNum") if raw.get("orderNum") is not None else raw.get("order_num")
    )
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
        code, message, status = TT_INST_40001
        raise BizError(code, "items 必须是非空数组", status)
    if len(items) > 500:
        code, message, status = TT_INST_40001
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
                item["name"], item["region"], item["intro"], item["label"],
                item["unit"], item["functionText"], item["contact"], item["phone"],
                item["platformTypeKey"], item["platformType"], item["sortOrder"],
                item["status"], item["sourcePk"],
                item["serialNo"], item["sourceStatus"], item["orderNum"],
                item["sourceSite"], item["sourceApi"], item["fetchedAt"],
                item["logoFileId"], item["detailInfo"], item["userType"],
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
            results.append({"id": row_id, "name": item["name"], "kind": item["kind"], "action": action})
        audit_record(
            "institution.import", "institution", resource_id=None,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"created": created, "updated": updated, "total": len(items)},
            request_id=request_id, cur=cur,
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
            "institution.delete", "institution", resource_id=inst_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"name": row["name"], "kind": row["kind"]},
            request_id=request_id, cur=cur,
        )
    return {"id": inst_id, "deleted": True}


# ── P0-3 Cooperation 管理端（READ ONLY + 平台协助运营操作走 cooperation 模块） ──

_COOP_FROM = """
FROM cooperation_intent ci
LEFT JOIN app_user iu ON ci.initiator_user_id = iu.id
LEFT JOIN user_profile ip ON iu.id = ip.user_id
LEFT JOIN app_user tu ON ci.target_owner_user_id = tu.id
LEFT JOIN user_profile tp ON tu.id = tp.user_id
LEFT JOIN demand d ON ci.target_type = 'demand' AND ci.target_id = d.id
LEFT JOIN achievement a ON ci.target_type = 'achievement' AND ci.target_id = a.id
LEFT JOIN institution org ON COALESCE(ci.target_org_id, d.org_id, a.org_id) = org.id
"""

_COOP_LIST_SQL = """
SELECT ci.id, ci.initiator_user_id, ci.target_type, ci.target_id,
       ci.target_owner_user_id, ci.intent_type, ci.message, ci.status, ci.version,
       ci.created_at, ci.accepted_at, ci.confirmed_at, ci.completed_at, ci.closed_at,
       ci.handling_mode, ci.assist_status, ci.accept_mode, ci.handled_by_user_id,
       COALESCE(ci.target_org_id, d.org_id, a.org_id) AS target_org_id,
       ci.initiator_contact_snapshot, ci.assist_note, ci.contact_share_consent_at,
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


def list_cooperations_admin(args, scope: dict) -> dict:
    """GET /admin/cooperations：按状态、协助模式和关键字筛选；机构管理员仅查看本机构相关记录。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip().lower()
    handling_mode = (args.get("handlingMode") or "").strip().lower()
    assist_status = (args.get("assistStatus") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where, params = [], []
    if not scope.get("isPlatformAdmin"):
        clause, values = _coop_org_visibility_sql(scope)
        where.append(clause)
        params.extend(values)
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


def get_cooperation_admin(intent_id: int, scope: dict) -> dict:
    """GET /admin/cooperations/{id} —— 只读详情 + events（管理端视角，无参与方权限过滤）。"""
    with get_cursor() as cur:
        where = ["ci.id = %s"]
        params = [intent_id]
        if not scope.get("isPlatformAdmin"):
            clause, values = _coop_org_visibility_sql(scope)
            where.append(clause)
            params.extend(values)
        cur.execute(_COOP_LIST_SQL + " WHERE " + " AND ".join(where), params)
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
        detail["canReview"] = _can_review_cooperation(scope, row, cur)

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

def _insert_admin_cooperation_event(
    cur,
    intent_id: int,
    event_type: str,
    from_status: str | None,
    to_status: str,
    operator_user_id: int,
    operator_role: str,
    remark: str | None = None,
):
    """后台处理对接时写入状态事件。"""
    cur.execute(
        """
        INSERT INTO cooperation_event
            (
                intent_id,
                event_type,
                from_status,
                to_status,
                operator_user_id,
                operator_role,
                remark
            )
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            intent_id,
            event_type,
            from_status,
            to_status,
            operator_user_id,
            operator_role,
            remark,
        ),
    )


def _target_owner_in_managed_orgs(cur, target_owner_user_id, org_ids: list[int]) -> bool:
    """目标持有方是否属于机构管理员所管机构（含普通成员发布的内容）。"""
    if cur is None or not target_owner_user_id or not org_ids:
        return False
    placeholders = ",".join(["%s"] * len(org_ids))
    cur.execute(
        f"""
        SELECT 1 FROM organization_membership
        WHERE user_id = %s AND status = 'active' AND org_id IN ({placeholders})
        LIMIT 1
        """,
        [int(target_owner_user_id)] + [int(item) for item in org_ids],
    )
    return cur.fetchone() is not None


def _can_review_cooperation(scope: dict, row: dict, cur=None) -> bool:
    """
    对接审核权限：

    - 平台管理员：可处理全部 pending 对接（不可审自己发起的）；
    - 机构管理员：可处理目标属于本机构、或自己作为目标持有方的 pending 对接；
    - 发起方仅能看，不可接受自己发起的申请。
    """
    if row["status"] != "pending":
        return False

    user_id = int(scope.get("userId") or 0)
    if int(row.get("initiator_user_id") or 0) == user_id:
        return False

    if scope.get("isPlatformAdmin"):
        return True

    org_ids = scope_org_ids(scope)
    target_org_id = row.get("target_org_id")
    if target_org_id is not None and org_ids and int(target_org_id) in set(org_ids):
        return True

    if int(row.get("target_owner_user_id") or 0) == user_id:
        return True

    return _target_owner_in_managed_orgs(cur, row.get("target_owner_user_id"), org_ids)


def admin_review_cooperation(
    scope: dict,
    intent_id: int,
    body: dict,
    action: str,
    request_id=None,
) -> dict:
    """
    后台处理对接申请。

    action:
    - accept：pending -> accepted
    - reject：pending -> rejected

    不修改小程序已有的 accept/reject 状态机；
    此函数仅为 admin / org_admin 后台提供处理入口。
    """
    if action not in ("accept", "reject"):
        raise bad_request("对接处理动作只能是 accept 或 reject")

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("处理对接必须携带正整数 version")

    reason = (body.get("reason") or "").strip()
    if action == "reject" and not reason:
        raise bad_request("驳回对接必须填写 reason")

    to_status = "accepted" if action == "accept" else "rejected"
    timestamp_column = "accepted_at" if action == "accept" else "closed_at"

    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            SELECT
                ci.id,
                ci.initiator_user_id,
                ci.target_type,
                ci.target_id,
                ci.target_owner_user_id,
                ci.status,
                ci.version,
                ci.handling_mode,
                ci.assist_status,
                ci.slot_reserved,
                COALESCE(ci.target_org_id, d.org_id, a.org_id) AS target_org_id
            FROM cooperation_intent ci
            LEFT JOIN demand d
                ON ci.target_type = 'demand'
               AND ci.target_id = d.id
            LEFT JOIN achievement a
                ON ci.target_type = 'achievement'
               AND ci.target_id = a.id
            WHERE ci.id = %s
            FOR UPDATE OF ci
            """,
            (intent_id,),
        )
        row = cur.fetchone()

        if not row:
            raise coop_not_found()

        if not _can_review_cooperation(scope, row):
            raise coop_forbidden("无权处理该对接申请")

        if row["status"] != "pending":
            raise coop_conflict("只有待处理的对接申请可以接受或驳回")

        if action == "accept" and (row.get("handling_mode") or "direct") == "assisted":
            raise coop_conflict("平台协助对接须待目标机构明确同意后，通过协助处理流程接受")

        cur.execute(
            f"""
            UPDATE cooperation_intent
            SET
                status = %s,
                version = version + 1,
                {timestamp_column} = NOW()
            WHERE id = %s
              AND version = %s
            """,
            (to_status, intent_id, version),
        )

        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        operator_role = (
            "admin"
            if scope.get("isPlatformAdmin")
            else "org_admin"
        )

        _insert_admin_cooperation_event(
            cur,
            intent_id=intent_id,
            event_type="accepted" if action == "accept" else "rejected",
            from_status="pending",
            to_status=to_status,
            operator_user_id=scope["userId"],
            operator_role=operator_role,
            remark=reason or None,
        )

        # 接受某条对接后，同一目标的其他待处理对接自动驳回。
        # 与小程序原有 accept 行为保持一致。
        if action == "accept":
            # 名额预占（与用户路径 _transition 保持一致）：exclusive/limited
            # 目标必须在 accept 时原子扣减 cooperation_remaining，否则可被超量接受。
            slot = _reserve_target_slot(cur, row, intent_id)
            cur.execute(
                """
                SELECT id
                FROM cooperation_intent
                WHERE target_type = %s
                  AND target_id = %s
                  AND status = 'pending'
                  AND id <> %s
                FOR UPDATE
                """,
                (
                    row["target_type"],
                    row["target_id"],
                    intent_id,
                ),
            )
            other_pending_rows = cur.fetchall() or []

            for other in other_pending_rows:
                other_id = other["id"]

                cur.execute(
                    """
                    UPDATE cooperation_intent
                    SET
                        status = 'rejected',
                        version = version + 1,
                        closed_at = NOW()
                    WHERE id = %s
                    """,
                    (other_id,),
                )

                _insert_admin_cooperation_event(
                    cur,
                    intent_id=other_id,
                    event_type="auto_rejected",
                    from_status="pending",
                    to_status="rejected",
                    operator_user_id=scope["userId"],
                    operator_role="system",
                    remark="目标内容已接受其他对接申请",
                )
            # 独占或最后一席：closePending 时 _reserve_target_slot 已返回，
            # 上面的 auto_reject 已覆盖全部其他 pending，语义一致。
        else:
            # reject 释放该意向已预占的名额（若曾 accept 过又因状态回退等场景）
            _release_target_slot(cur, row, intent_id)

        # 通知发起方：对接申请已被处理（与用户路径 _transition 保持一致）
        emit_notification(
            cur,
            recipient_user_id=row["initiator_user_id"],
            category="cooperation",
            event_type=f"cooperation.{'accepted' if action == 'accept' else 'rejected'}",
            source_type="cooperation",
            source_id=intent_id,
            title=f"对接状态更新：{to_status}",
            body=reason or None,
            target_path=(
                f"/subpackages/tech-transfer/pages/dock-detail/dock-detail"
                f"?type={row['target_type']}&id={row['target_id']}&intentId={intent_id}"
            ),
            dedupe_key=f"cooperation:{intent_id}:{action}:{to_status}",
        )

        audit_record(
            f"cooperation.admin_{action}",
            "cooperation_intent",
            resource_id=intent_id,
            actor_user_id=scope["userId"],
            actor_user_no=scope.get("userNo", ""),
            details={
                "from": "pending",
                "to": to_status,
                "targetType": row["target_type"],
                "targetId": row["target_id"],
                "targetOrgId": row.get("target_org_id"),
                "reason": reason or None,
            },
            request_id=request_id,
            cur=cur,
        )

    return get_cooperation_admin(intent_id, scope)


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


def organization_content_scope(scope: dict, alias: str) -> tuple[str | None, list]:
    """Return the content visibility predicate for a platform/org administrator.

    Institution administrators manage their institution's content plus unassigned
    publications owned by current members (legacy posts from before certification).
    Content already bound to another institution stays out of this scope.
    """
    if scope.get("isPlatformAdmin"):
        return None, []
    org_ids = scope_org_ids(scope)
    if not org_ids and scope.get("orgId") is not None:
        org_ids = [int(scope["orgId"])]
    if not org_ids:
        return (
            f"({alias}.org_id = %s OR ({alias}.org_id IS NULL AND {alias}.owner_user_id = %s))",
            [scope.get("orgId"), scope["userId"]],
        )
    org_clause, org_params = _sql_in(f"{alias}.org_id", org_ids)
    member_clause, member_params = _sql_in("m.org_id", org_ids)
    return (
        f"({org_clause} OR ({alias}.org_id IS NULL AND {alias}.owner_user_id IN ("
        f"SELECT m.user_id FROM organization_membership m "
        f"WHERE {member_clause} AND m.status='active')))",
        org_params + member_params,
    )


def can_claim_unassigned_content(scope: dict, row: dict) -> bool:
    if scope.get("isPlatformAdmin") or not (scope.get("orgId") or scope_org_ids(scope)):
        return False
    if row.get("org_id") is not None or not row.get("owner_user_id"):
        return False
    if row.get("owner_in_org") is False:
        return False
    if row.get("owner_in_org") is True:
        return True
    return row.get("owner_user_id") == scope.get("userId")


def claim_unassigned_content(scope: dict, content_type: str, content_id: int, version: int, request_id=None) -> dict:
    """Attach a member's unassigned publication to the administrator's institution."""
    tables = {"achievement": "achievement", "demand": "demand"}
    table = tables.get(content_type)
    if not table:
        raise bad_request("contentType 必须是 achievement 或 demand")
    org_ids = scope_org_ids(scope)
    if scope.get("isPlatformAdmin") or not org_ids:
        raise forbidden("仅机构管理员可归属本机构成员的历史内容")
    claim_org_id = org_ids[0] if len(org_ids) == 1 else int(scope.get("orgId") or org_ids[0])
    if not isinstance(version, int) or version < 1:
        raise bad_request("归属内容必须携带正整数 version")

    with get_cursor(commit=True) as cur:
        cur.execute(
            f"SELECT id, org_id, owner_user_id, version FROM {table} "
            "WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
            (content_id,),
        )
        row = cur.fetchone()
        if not row:
            raise achievement_not_found() if content_type == "achievement" else demand_not_found()
        cur.execute(
            "SELECT 1 FROM organization_membership "
            "WHERE user_id=%s AND org_id=%s AND status='active'",
            (row.get("owner_user_id"), claim_org_id),
        )
        owner_in_org = bool(cur.fetchone())
        if not can_claim_unassigned_content(scope, {**row, "owner_in_org": owner_in_org}):
            raise forbidden("只能归属本机构成员尚未关联其他机构的历史内容")
        if row["version"] != version:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")
        cur.execute("SELECT name FROM institution WHERE id=%s", (claim_org_id,))
        inst = cur.fetchone()
        org_name = inst["name"] if inst else None
        if content_type == "demand":
            cur.execute(
                "UPDATE demand SET org_id=%s, org_name_snapshot=%s, version=version+1 "
                "WHERE id=%s AND version=%s RETURNING id, org_id, version",
                (claim_org_id, org_name, content_id, version),
            )
        else:
            cur.execute(
                "UPDATE achievement SET org_id=%s, source_org_name=%s, version=version+1 "
                "WHERE id=%s AND version=%s RETURNING id, org_id, version",
                (claim_org_id, org_name, content_id, version),
            )
        updated = cur.fetchone()

    audit_record(
        f"{content_type}.organization_claim",
        table,
        resource_id=content_id,
        actor_user_id=scope["userId"],
        actor_user_no=scope.get("userNo", ""),
        details={"orgId": claim_org_id, "previousOrgId": None},
        request_id=request_id,
    )
    return {"id": updated["id"], "orgId": updated["org_id"], "version": updated["version"]}


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
        "orgName": r.get("institution_name") or r.get("source_org_name"),
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


def list_achievements_admin(args, scope: dict) -> dict:
    """GET /admin/achievements —— 全量成果列表（status/categoryCode/keyword 过滤 + 分页）。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip()
    category_code = (args.get("categoryCode") or "").strip()
    keyword = (args.get("keyword") or "").strip()

    where = ["a.deleted_at IS NULL"]
    params = []

    scope_predicate, scope_params = organization_content_scope(scope, "a")
    if scope_predicate:
        where.append(scope_predicate)
        params.extend(scope_params)

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
            SELECT a.id, a.title, a.status, a.version, a.org_id, a.tech_intro, a.source_org_name,
                   a.view_count, a.reject_reason, a.published_at, a.created_at, a.updated_at,
                   a.owner_user_id, o.name AS institution_name,
                   c.name AS category_name, c.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            LEFT JOIN institution o ON a.org_id = o.id
            LEFT JOIN app_user u ON a.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            {where_sql}
            ORDER BY a.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []
    items = _page_of(rows, page, page_size, total, _ach_admin_item)
    for item, row in zip(items["list"], rows):
        item["pendingOrgAssignment"] = can_claim_unassigned_content(scope, {**row, "owner_in_org": True})
    return items


def get_achievement_admin(ach_id: int, scope: dict) -> dict:
    """GET /admin/achievements/{id} —— 成果详情（任意状态，含发明人与审核信息）。"""
    # with get_cursor() as cur:
    #     cur.execute(
    #         """
    #         SELECT a.*, c.name AS category_name, c.code AS category_code,
    #                u.user_no AS submitter_user_no, p.display_name AS submitter_name
    #         FROM achievement a
    #         LEFT JOIN achievement_category c ON a.category_id = c.id
    #         LEFT JOIN app_user u ON a.owner_user_id = u.id
    #         LEFT JOIN user_profile p ON u.id = p.user_id
    #         WHERE a.id = %s AND a.deleted_at IS NULL
    #         """,
    #         (ach_id,),
    #     )
    where = ["a.id = %s", "a.deleted_at IS NULL"]
    params = [ach_id]

    scope_predicate, scope_params = organization_content_scope(scope, "a")
    if scope_predicate:
        where.append(scope_predicate)
        params.extend(scope_params)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT a.*, c.name AS category_name, c.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM achievement a
            LEFT JOIN achievement_category c ON a.category_id = c.id
            LEFT JOIN app_user u ON a.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE {" AND ".join(where)}
            """,
            params,
        )
        row = cur.fetchone()
        if not row:
            raise achievement_not_found()
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
        content = load_content(cur, ach_id)

    detail = _ach_admin_item(row)
    detail.update({
        "techIntro": row.get("tech_intro"),
        "techRoute": row.get("tech_route"),
        "maturityLevel": row.get("maturity_level"),
        "maturityDesc": row.get("maturity_desc"),
        "pricingMode": row.get("pricing_mode"),
        "priceMinWan": float(row["price_min_wan"]) if row.get("price_min_wan") is not None else None,
        "priceMaxWan": float(row["price_max_wan"]) if row.get("price_max_wan") is not None else None,
        "categoryId": row.get("category_id"),
        "orgId": row.get("org_id"),
        "sourceOrgName": row.get("source_org_name"),
        "contactName": row.get("contact_name"),
        "contactTitle": row.get("contact_title"),
        "contactPhone": row.get("contact_phone"),
        "contactEmail": row.get("contact_email"),
        "contactWechat": row.get("contact_wechat"),
        "inventors": [
            {
                "name": inv["name"],
                "orgName": inv.get("org_name"),
                "contribution": inv.get("contribution"),
            }
            for inv in inventors
        ],
        "sections": content.get("sections") or [],
        "patents": content.get("patents") or [],
        "links": content.get("links") or [],
        "media": content.get("media") or [],
    })
    application_fields = row.get("application_fields")
    if application_fields and isinstance(application_fields, str):
        try:
            application_fields = json.loads(application_fields)
        except (ValueError, TypeError):
            application_fields = []
    detail["applicationFields"] = application_fields if isinstance(application_fields, list) else []
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


def list_demands_admin(args, scope: dict) -> dict:
    """GET /admin/demands —— 全量需求列表（status/categoryCode/keyword 过滤 + 分页）。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip()
    category_code = (args.get("categoryCode") or "").strip()
    keyword = (args.get("keyword") or "").strip()

    where = ["d.deleted_at IS NULL"]
    params = []

    scope_predicate, scope_params = organization_content_scope(scope, "d")
    if scope_predicate:
        where.append(scope_predicate)
        params.extend(scope_params)

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
            SELECT d.id, d.title, d.status, d.version, d.org_id, d.region,
                   d.budget_min_wan, d.budget_max_wan, d.budget_negotiable,
                   d.reject_reason, d.published_at, d.created_at, d.updated_at,
                   d.owner_user_id,
                   COALESCE(o.name, d.org_name_snapshot) AS org_name, dc.name AS category_name, dc.code AS category_code,
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
    items = _page_of(rows, page, page_size, total, _dmd_admin_item)
    for item, row in zip(items["list"], rows):
        item["pendingOrgAssignment"] = can_claim_unassigned_content(scope, {**row, "owner_in_org": True})
    return items


def get_demand_admin(demand_id: int, scope: dict) -> dict:
    """GET /admin/demands/{id} —— 需求详情（任意状态，含联系方式与标签）。"""
    where = ["d.id = %s", "d.deleted_at IS NULL"]
    params = [demand_id]

    scope_predicate, scope_params = organization_content_scope(scope, "d")
    if scope_predicate:
        where.append(scope_predicate)
        params.extend(scope_params)

    with get_cursor() as cur:
        cur.execute(
            f"""
            SELECT d.*, o.name AS org_name, o.intro AS org_intro,
                   dc.name AS category_name, dc.code AS category_code,
                   u.user_no AS submitter_user_no, p.display_name AS submitter_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            LEFT JOIN demand_category dc ON d.category_id = dc.id
            LEFT JOIN app_user u ON d.owner_user_id = u.id
            LEFT JOIN user_profile p ON u.id = p.user_id
            WHERE {" AND ".join(where)}
            """,
            params,
        )
        row = cur.fetchone()

        if not row:
            raise demand_not_found()
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
        "categoryId": row.get("category_id"),
        "orgId": row.get("org_id"),
        "budgetMinWan": float(row["budget_min_wan"]) if row.get("budget_min_wan") is not None else None,
        "budgetMaxWan": float(row["budget_max_wan"]) if row.get("budget_max_wan") is not None else None,
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


def list_users_admin(args, scope: dict) -> dict:
    """GET /admin/users —— 只读列表：keyword（user_no/display_name/org_name）+ status。"""
    page, page_size = _page_args(args)
    status = (args.get("status") or "").strip().lower()
    keyword = (args.get("keyword") or "").strip()

    where = ["u.deleted_at IS NULL"]
    params = []
    if not scope.get("isPlatformAdmin"):
        clause, values = _user_membership_scope_sql(scope)
        where.append(clause)
        params.extend(values)
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


def get_user_admin(user_id: int, scope: dict) -> dict:
    """GET /admin/users/{id} —— 用户 + profile + roles + 低成本统计（4 个 COUNT 子查询）。"""
    with get_cursor() as cur:
        where = ["u.id = %s", "u.deleted_at IS NULL"]
        params = [user_id]
        if not scope.get("isPlatformAdmin"):
            clause, values = _user_membership_scope_sql(scope)
            where.append(clause)
            params.extend(values)
        cur.execute(_USER_LIST_SQL + " WHERE " + " AND ".join(where), params)
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
        WHERE u.id = %s
          AND u.status = 'active'
          AND u.deleted_at IS NULL
          AND EXISTS (
            SELECT 1 FROM organization_membership m
            WHERE m.user_id = u.id AND m.org_id = %s AND m.status = 'active'
          )
        """,
        (owner_user_id, org_id),
    )
    if not cur.fetchone():
        raise bad_request("归属用户不存在、已禁用，或未绑定所选机构")

    return owner_user_id

def _content_write_context(cur, scope: dict, body: dict, fields: dict) -> tuple[int, int, int]:
    """
    返回：
    - org_id：内容所属机构
    - owner_user_id：内容业务归属人
    - created_by_user_id：实际创建操作人
    """
    actor_user_id = scope["userId"]

    # 平台管理员：仍然可以代机构、代用户录入。
    if scope.get("isPlatformAdmin"):
        org_id = fields.get("org_id")
        if org_id is None:
            raise bad_request("后台录入必须选择所属机构")

        owner_user_id = _admin_owner_user_id(cur, body, org_id)
        return org_id, owner_user_id, actor_user_id

    # 机构管理员：机构和归属人均由登录身份决定，绝不信任请求体中的外机构 ID。
    org_ids = scope_org_ids(scope)
    if not org_ids:
        raise bad_request("机构管理员未绑定有效机构")

    requested = fields.get("org_id")
    if requested is not None:
        org_id = int(requested)
        if org_id not in org_ids:
            raise forbidden("机构管理员只能归属自己管理的机构")
    elif len(org_ids) == 1:
        org_id = org_ids[0]
    else:
        raise bad_request("管理多家机构时必须指定 orgId")

    fields["org_id"] = org_id

    owner_user_id = _admin_owner_user_id(
        cur,
        {"ownerUserId": actor_user_id},
        org_id,
    )
    return org_id, owner_user_id, actor_user_id

def _resolve_admin_save_action(
    scope: dict,
    body: dict,
    *,
    is_create: bool,
) -> tuple[str | None, str | None]:
    """
    返回：
    - save_action：draft / submit / publish / None
    - target_status：draft / pending_review / published / None

    新增接口未传 saveAction 时，为兼容旧前端，默认保存草稿。
    编辑接口未传 saveAction 时，仅更新内容，不改状态。
    """
    raw_action = body.get("saveAction")

    if raw_action is None or not str(raw_action).strip():
        return ("draft", "draft") if is_create else (None, None)

    save_action = str(raw_action).strip().lower()

    if scope.get("isPlatformAdmin"):
        action_to_status = {
            "draft": "draft",
            "publish": "published",
        }
        if save_action not in action_to_status:
            raise bad_request("平台管理员 saveAction 只能是 draft 或 publish")
        return save_action, action_to_status[save_action]

    # backend_identity 已保证这里是有效 org_admin。
    action_to_status = {
        "draft": "draft",
        "submit": "pending_review",
    }
    if save_action not in action_to_status:
        raise forbidden("机构管理员只能保存草稿或提交审核")
    return save_action, action_to_status[save_action]


def _assert_admin_status_transition(
    kind: str,
    current_status: str,
    target_status: str | None,
    is_platform: bool,
) -> None:
    """拒绝编辑弹窗对当前状态机不合法的 saveAction，避免误提交变成 400/404。"""
    if target_status is None:
        return

    if kind == "achievement":
        draft_from = ("draft", "rejected", "pending_review", "offline")
        submit_from = ("draft", "rejected", "offline")
        publish_from = ("draft", "rejected", "pending_review", "offline", "published")
    else:
        draft_from = ("draft", "rejected", "pending_review")
        submit_from = ("draft", "rejected")
        publish_from = ("draft", "rejected", "pending_review", "published")

    if target_status == "draft":
        allowed = draft_from
        message = "当前状态不能保存为草稿"
    elif target_status == "pending_review":
        allowed = submit_from
        message = (
            "只有草稿、已驳回或已下架的成果可以提交审核"
            if kind == "achievement"
            else "只有草稿或已驳回的需求可以提交审核"
        )
    elif target_status == "published":
        if not is_platform:
            raise forbidden("机构管理员不能直接发布")
        allowed = publish_from
        message = "当前状态不能直接发布"
    else:
        raise bad_request("不支持的保存动作")

    if current_status not in allowed:
        raise bad_request(message)

def create_achievement_admin(
    scope: dict,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员新增成果。

    默认状态为 draft；后续仍通过 submit + approve 流程发布。
    传 ownerUserId 指定归属人；未传 = 平台代录（owner NULL，进入平台协助对接），
    录入人 created_by_user_id 恒为当前管理员。
    """
    fields, inventor_refs, content = _parse_upsert_body(body, partial=False)

    save_action, target_status = _resolve_admin_save_action(
        scope,
        body,
        is_create=True,
    )

    _restrict_org_admin_fields(scope, fields, is_create=True, kind="achievement")

    min_price = fields.get("price_min_wan")
    max_price = fields.get("price_max_wan")
    if min_price is not None and max_price is not None and min_price > max_price:
        raise bad_request("priceMinWan 不能大于 priceMaxWan")

    with get_cursor(commit=True) as cur:
        if fields.get("category_id") is None:
            raise bad_request("后台录入必须选择成果分类")

        org_id, owner_user_id, created_by_user_id = _content_write_context(
            cur, scope, body, fields
        )
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
                created_by_user_id,
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

        # 新增时先统一落 draft；同一个事务内再按动作切换状态，
        # 外部不会看到中间状态。
        if target_status != "draft":
            cur.execute(
                """
                UPDATE achievement
                SET status = %s,
                    published_at = CASE
                        WHEN %s = 'published' THEN NOW()
                        ELSE NULL
                    END,
                    reject_reason = NULL
                WHERE id = %s
                """,
                (target_status, target_status, ach_id),
            )

        if inventor_refs:
            _sync_inventors(cur, ach_id, inventor_refs)
        sync_content(cur, ach_id, created_by_user_id or scope["userId"], content, allow_existing_media=True)

        # cur=cur：成果写入和审计日志处于同一个事务
        audit_record(
            "achievement.admin_create",
            "achievement",
            resource_id=ach_id,
            actor_user_id=scope["userId"],
            actor_user_no=scope.get("userNo", ""),
            details={
                "title": fields.get("title"),
                "ownerUserId": owner_user_id,
                "saveAction": save_action,
                "status": target_status,
            },
            request_id=request_id,
            cur=cur,
        )

    return get_achievement_admin(ach_id, scope)


def update_achievement_admin(
    scope: dict,
    ach_id: int,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员编辑任意未删除成果。

    不允许通过编辑接口直接变更 owner、status、审核信息；
    status 仍应由审核/上下架接口处理。
    """
    fields, inventor_refs, content = _parse_upsert_body(body, partial=True)

    save_action, target_status = _resolve_admin_save_action(
        scope,
        body,
        is_create=False,
    )

    _restrict_org_admin_fields(scope, fields, is_create=False, kind="achievement")

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("编辑成果必须携带正整数 version")

    if not fields and inventor_refs is None and target_status is None and not content:
        raise bad_request("没有可更新的成果字段")

    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [ach_id]
        append_content_scope(where, params, scope, "achievement")

        cur.execute(
            f"""
            SELECT id, version, status, price_min_wan, price_max_wan
            FROM achievement
            WHERE {" AND ".join(where)}
            """,
            params,
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
        set_values = list(fields.values())

        if target_status is not None:
            _assert_admin_status_transition(
                "achievement",
                current["status"],
                target_status,
                bool(scope.get("isPlatformAdmin")),
            )

            set_clauses.append("status=%s")
            set_values.append(target_status)

            if target_status == "published":
                set_clauses.append("published_at=NOW()")
                set_clauses.append("reject_reason=NULL")
            elif target_status == "pending_review":
                set_clauses.append("published_at=NULL")
                set_clauses.append("reject_reason=NULL")
            else:
                # 保存草稿时不应保留历史发布时间。
                set_clauses.append("published_at=NULL")

        set_clauses.append("version=version+1")

        update_where = [
            "id = %s",
            "version = %s",
            "deleted_at IS NULL",
        ]
        update_params = set_values + [ach_id, version]
        append_content_scope(update_where, update_params, scope, "achievement")

        cur.execute(
            f"""
            UPDATE achievement
            SET {", ".join(set_clauses)}
            WHERE {" AND ".join(update_where)}
            """,
            update_params,
        )

        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        # 传 [] 表示清空发明人；没传 inventorRefs 则不处理。
        if inventor_refs is not None:
            _sync_inventors(cur, ach_id, inventor_refs)
        if content:
            sync_content(cur, ach_id, scope["userId"], content, allow_existing_media=True)

        audit_record(
            "achievement.admin_update",
            "achievement",
            resource_id=ach_id,
            actor_user_id=scope["userId"],
            actor_user_no=scope.get("userNo", ""),
            details={
                "updatedFields": list(fields.keys()),
                "saveAction": save_action,
                "status": target_status or current["status"],
            },
            request_id=request_id,
            cur=cur,
        )

    return get_achievement_admin(ach_id, scope)

# ── 后台需求新增 / 编辑 ─────────────────────────────────────

def create_demand_admin(
    scope: dict,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员新增需求。

    默认状态为 draft；后续仍经过 submit + approve 才发布。
    传 ownerUserId 指定需求归属人；未传 = 平台代录（owner NULL，进入平台协助对接），
    录入人 created_by_user_id 恒为当前管理员。
    """
    fields, tags, attachments = _parse_demand_upsert_body(body, partial=False)

    save_action, target_status = _resolve_admin_save_action(
        scope,
        body,
        is_create=True,
    )

    _restrict_org_admin_fields(scope, fields, is_create=True, kind="demand")

    min_budget = fields.get("budget_min_wan")
    max_budget = fields.get("budget_max_wan")
    if min_budget is not None and max_budget is not None:
        if min_budget > max_budget:
            raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

    with get_cursor(commit=True) as cur:
        if fields.get("category_id") is None:
            raise bad_request("后台录入必须选择需求分类")

        org_id, owner_user_id, created_by_user_id = _content_write_context(
            cur, scope, body, fields
        )

        # orgName / categoryName：仅平台管理员可通过名称改绑机构。
        _resolve_demand_name_refs(
            cur, fields, allow_org_mutate=bool(scope.get("isPlatformAdmin"))
        )
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
                created_by_user_id,
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

        if target_status != "draft":
            cur.execute(
                """
                UPDATE demand
                SET status = %s,
                    published_at = CASE
                        WHEN %s = 'published' THEN NOW()
                        ELSE NULL
                    END,
                    reject_reason = NULL
                WHERE id = %s
                """,
                (target_status, target_status, demand_id),
            )

        if tags is not None:
            _sync_demand_tags(cur, demand_id, tags)

        audit_record(
            "demand.admin_create",
            "demand",
            resource_id=demand_id,
            actor_user_id=scope["userId"],
            actor_user_no=scope.get("userNo", ""),
            details={
                "title": fields.get("title"),
                "ownerUserId": owner_user_id,
                "saveAction": save_action,
                "status": target_status,
            },
            request_id=request_id,
            cur=cur,
        )

    return get_demand_admin(demand_id, scope)


def update_demand_admin(
    scope: dict,
    demand_id: int,
    body: dict,
    request_id=None,
) -> dict:
    """
    管理员编辑任意未删除需求。

    不允许用该接口直接修改 owner、status、审核结果。
    status 仍由审核、取消、关闭等专用接口处理。
    """
    fields, tags, attachments = _parse_demand_upsert_body(body, partial=True)

    save_action, target_status = _resolve_admin_save_action(
        scope,
        body,
        is_create=False,
    )

    _restrict_org_admin_fields(scope, fields, is_create=False, kind="demand")

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("编辑需求必须携带正整数 version")

    if not fields and tags is None and target_status is None:
        raise bad_request("没有可更新的需求字段")

    with get_cursor(commit=True) as cur:
        where = ["id = %s", "deleted_at IS NULL"]
        params = [demand_id]
        append_content_scope(where, params, scope, "demand")

        cur.execute(
            f"""
            SELECT id, version, status, budget_min_wan, budget_max_wan
            FROM demand
            WHERE {" AND ".join(where)}
            """,
            params,
        )
        current = cur.fetchone()

        if not current:
            raise demand_not_found()

        # orgName / categoryName 在这里转成真正的 ID。
        _resolve_demand_name_refs(
            cur, fields, allow_org_mutate=bool(scope.get("isPlatformAdmin"))
        )
        _validate_demand_refs(cur, fields)

        # PATCH 只传一个预算字段时，仍与数据库中的另一个预算字段一起校验。
        min_budget = fields.get("budget_min_wan", current.get("budget_min_wan"))
        max_budget = fields.get("budget_max_wan", current.get("budget_max_wan"))

        if min_budget is not None and max_budget is not None:
            if float(min_budget) > float(max_budget):
                raise bad_request("budgetMinWan 不能大于 budgetMaxWan")

        set_clauses = [f"{column}=%s" for column in fields]
        set_values = list(fields.values())

        if target_status is not None:
            _assert_admin_status_transition(
                "demand",
                current["status"],
                target_status,
                bool(scope.get("isPlatformAdmin")),
            )

            set_clauses.append("status=%s")
            set_values.append(target_status)

            if target_status == "published":
                set_clauses.append("published_at=NOW()")
                set_clauses.append("reject_reason=NULL")
            elif target_status == "pending_review":
                set_clauses.append("published_at=NULL")
                set_clauses.append("reject_reason=NULL")
            else:
                set_clauses.append("published_at=NULL")

        set_clauses.append("version=version+1")

        update_where = [
            "id = %s",
            "version = %s",
            "deleted_at IS NULL",
        ]
        update_params = set_values + [demand_id, version]
        append_content_scope(update_where, update_params, scope, "demand")

        cur.execute(
            f"""
            UPDATE demand
            SET {", ".join(set_clauses)}
            WHERE {" AND ".join(update_where)}
            """,
            update_params,
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
            actor_user_id=scope["userId"],
            actor_user_no=scope.get("userNo", ""),
            details={
                "updatedFields": list(fields.keys()),
                "saveAction": save_action,
                "status": target_status or current["status"],
            },
            request_id=request_id,
            cur=cur,
        )

    return get_demand_admin(demand_id, scope)


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
