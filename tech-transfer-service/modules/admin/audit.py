"""管理端审计日志查询子模块（由 modules/admin/service.py 门面重导出）。"""

from __future__ import annotations

from db import get_cursor


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
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": items,
    }
