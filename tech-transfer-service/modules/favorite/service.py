"""
收藏模块服务层 —— 收藏列表、收藏/取消（幂等）

Architecture source: 04-backend-domain-design.md §4.9, 05-data-model-design.md §6.1,
                     openapi.yaml paths /me/favorites、/favorites/{targetType}/{targetId}
设计说明：
- 取消收藏即物理 DELETE（收藏是纯关系，无审计价值，审计走 audit_log）
- PUT/DELETE 均幂等：重复 PUT 返回既有记录；DELETE 不存在返回成功
- 列表内嵌目标摘要；目标已下线（非 published）仍返回并标注，不静默丢失收藏
- 新增收藏：公开内容、本人内容、或已接受对接的双方（确认后离开列表仍可收藏）
"""
from db import get_cursor
from core.errors import bad_request, favorite_not_found
from modules.audit.service import record as audit_record
from modules.cooperation.service import can_access_target, is_accepted_dock_party

TARGET_TYPES = ("achievement", "demand")


def _validate_target_type(target_type: str):
    if target_type not in TARGET_TYPES:
        raise bad_request(f"targetType 必须是 {'/'.join(TARGET_TYPES)}")


def _load_target(cur, target_type: str, target_id: int):
    """加载目标行（含 owner），不存在返回 None"""
    if target_type == "demand":
        cur.execute(
            "SELECT id, title, owner_user_id, status FROM demand WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    else:
        cur.execute(
            "SELECT id, title, owner_user_id, status FROM achievement WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    return cur.fetchone()


def _target_summary(cur, target_type: str, target_id: int):
    """收藏列表内嵌的目标摘要（列表页展示用；下线目标仍返回并标注 status）"""
    if target_type == "demand":
        cur.execute(
            """
            SELECT d.id, d.title, d.status, d.description,
                   o.name AS org_name, o.intro AS org_intro
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
            WHERE d.id=%s AND d.deleted_at IS NULL
            """,
            (target_id,),
        )
    else:
        cur.execute(
            """
            SELECT id, title, status, tech_intro, source_org_name AS org_name
            FROM achievement
            WHERE id=%s AND deleted_at IS NULL
            """,
            (target_id,),
        )
    row = cur.fetchone()
    if not row:
        return None
    desc = row.get("description") if target_type == "demand" else row.get("tech_intro")
    return {
        "title": row["title"],
        "orgName": row.get("org_name"),
        "status": row["status"],
        "desc": (desc or "")[:120],
    }


# ── 收藏 / 取消（幂等） ──────────────────────────────────────

def add_favorite(user_id: int, user_no: str, target_type: str, target_id: int, request_id=None):
    _validate_target_type(target_type)
    try:
        target_id = int(target_id)
    except (ValueError, TypeError):
        raise bad_request("targetId 必须是整数")

    with get_cursor(commit=True) as cur:
        target = _load_target(cur, target_type, target_id)
        if not target:
            raise favorite_not_found()
        dock_party = False
        if target["status"] != "published" and target["owner_user_id"] != user_id:
            dock_party = is_accepted_dock_party(cur, target_type, target_id, user_id)
        if not can_access_target(
            user_id,
            owner_user_id=target["owner_user_id"],
            status=target["status"],
            is_dock_party=dock_party,
        ):
            raise favorite_not_found()

        cur.execute(
            "INSERT INTO favorite (user_id, target_type, target_id) VALUES (%s, %s, %s) ON CONFLICT DO NOTHING",
            (user_id, target_type, target_id),
        )
        cur.execute(
            """
            SELECT id, created_at FROM favorite
            WHERE user_id=%s AND target_type=%s AND target_id=%s
            """,
            (user_id, target_type, target_id),
        )
        row = cur.fetchone()

        audit_record(
            "favorite.add", "favorite", resource_id=row["id"],
            actor_user_id=user_id, actor_user_no=user_no,
            details={"targetType": target_type, "targetId": target_id},
            request_id=request_id, cur=cur,
        )

    return {
        "id": row["id"],
        "favoritedAt": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
    }


def remove_favorite(user_id: int, user_no: str, target_type: str, target_id: int, request_id=None):
    _validate_target_type(target_type)
    try:
        target_id = int(target_id)
    except (ValueError, TypeError):
        raise bad_request("targetId 必须是整数")

    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM favorite WHERE user_id=%s AND target_type=%s AND target_id=%s",
            (user_id, target_type, target_id),
        )

        audit_record(
            "favorite.remove", "favorite",
            actor_user_id=user_id, actor_user_no=user_no,
            details={"targetType": target_type, "targetId": target_id},
            request_id=request_id, cur=cur,
        )

    return None


# ── 我的收藏列表 ─────────────────────────────────────────────

def list_my_favorites(user_id: int, args):
    _validate_target_type(args.get("targetType") or "")
    target_type = args.get("targetType")

    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10

    with get_cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) AS c FROM favorite WHERE user_id=%s AND target_type=%s",
            (user_id, target_type),
        )
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(
            """
            SELECT id, target_id, created_at FROM favorite
            WHERE user_id=%s AND target_type=%s
            ORDER BY id DESC
            LIMIT %s OFFSET %s
            """,
            (user_id, target_type, page_size, offset),
        )
        rows = cur.fetchall() or []

        list_items = []
        for row in rows:
            item = {
                "id": row["id"],
                "targetType": target_type,
                "targetId": row["target_id"],
                "favoritedAt": row["created_at"].strftime("%Y-%m-%d %H:%M:%S"),
            }
            summary = _target_summary(cur, target_type, row["target_id"])
            if summary:
                item["targetSummary"] = summary
            else:
                # 目标已被硬删除（如测试清理直删 DB）：仍嵌入占位摘要，
                # 兑现「已下线目标仍返回并标注，不静默丢失收藏」契约
                item["targetSummary"] = {
                    "title": None,
                    "orgName": None,
                    "status": "deleted",
                    "desc": "",
                }
            list_items.append(item)

    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
        "list": list_items,
    }
