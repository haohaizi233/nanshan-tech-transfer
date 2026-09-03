"""
对接模块服务层 —— 意向创建、列表/详情、状态机（accept/reject/confirm/cancel/complete）、事件时间线

Architecture source: 04-backend-domain-design.md §4.8, 05-data-model-design.md §6.2/§6.3,
                     06-api-design.md §5（cooperation 状态机与权限矩阵）、openapi.yaml paths /cooperations
状态机（后端强校验）:
  pending  → accepted / rejected        (target_owner: accept / reject)
  accepted → confirmed / cancelled      (双方: confirm / cancel)
  confirmed → completed / cancelled     (双方: complete / cancel)
副作用:
  accept   → 同一目标的其他 pending 意向自动拒绝（event=auto_rejected，同一事务）
  confirm  → 目标为需求时自动流转 matched
数据权限:
  详情/事件仅 initiator / target_owner 可见，其余 404（防探测）
"""
from db import get_cursor
from core.errors import (
    bad_request,
    conflict,
    coop_active_exists,
    coop_bad_request,
    coop_conflict,
    coop_forbidden,
    coop_not_found,
)
from modules.audit.service import record as audit_record

TARGET_TYPES = ("achievement", "demand")
ACTIVE_STATUSES = ("pending", "accepted", "confirmed")

# op → (允许的前置状态, 目标状态, 允许角色, 时间戳列, 事件类型)
TRANSITIONS = {
    "accept":   {"from": ("pending",),              "to": "accepted",  "roles": ("target_owner",), "ts": "accepted_at",  "event": "accepted"},
    "reject":   {"from": ("pending",),              "to": "rejected",  "roles": ("target_owner",), "ts": "closed_at",    "event": "rejected"},
    "confirm":  {"from": ("accepted",),             "to": "confirmed", "roles": ("initiator", "target_owner"), "ts": "confirmed_at", "event": "confirmed"},
    "cancel":   {"from": ("accepted", "confirmed"), "to": "cancelled", "roles": ("initiator", "target_owner"), "ts": "closed_at",   "event": "cancelled"},
    "complete": {"from": ("confirmed",),            "to": "completed", "roles": ("initiator", "target_owner"), "ts": "completed_at", "event": "completed"},
}


def _validate_target_type(target_type: str):
    if target_type not in TARGET_TYPES:
        raise bad_request(f"targetType 必须是 {'/'.join(TARGET_TYPES)}")


def _load_target(cur, target_type: str, target_id: int):
    """加载对接目标（须 published）"""
    if target_type == "demand":
        cur.execute(
            "SELECT id, owner_user_id, status FROM demand WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    else:
        cur.execute(
            "SELECT id, owner_user_id, status FROM achievement WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    return cur.fetchone()


def _target_summary(cur, target_type: str, target_id: int):
    if target_type == "demand":
        cur.execute(
            """
            SELECT d.title, d.status, o.org_name
            FROM demand d
            LEFT JOIN organization o ON d.org_id = o.id
            WHERE d.id=%s AND d.deleted_at IS NULL
            """,
            (target_id,),
        )
    else:
        cur.execute(
            "SELECT title, status, source_org_name AS org_name FROM achievement WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    row = cur.fetchone()
    if not row:
        return {"title": "(目标已下线)", "orgName": None, "status": "offline"}
    return {"title": row["title"], "orgName": row.get("org_name"), "status": row["status"]}


def _fmt(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def _row_to_intent(row, user_id: int):
    my_role = None
    if row["initiator_user_id"] == user_id:
        my_role = "initiator"
    elif row["target_owner_user_id"] == user_id:
        my_role = "target_owner"
    return {
        "id": row["id"],
        "initiatorUserId": row["initiator_user_id"],
        "targetType": row["target_type"],
        "targetId": row["target_id"],
        "targetOwnerUserId": row["target_owner_user_id"],
        "message": row.get("message"),
        "status": row["status"],
        "version": row["version"],
        "createdAt": _fmt(row.get("created_at")),
        "acceptedAt": _fmt(row.get("accepted_at")),
        "confirmedAt": _fmt(row.get("confirmed_at")),
        "completedAt": _fmt(row.get("completed_at")),
        "closedAt": _fmt(row.get("closed_at")),
        "myRole": my_role,
    }


def _get_intent_row(cur, intent_id: int):
    cur.execute("SELECT * FROM cooperation_intent WHERE id=%s", (intent_id,))
    return cur.fetchone()


def _insert_event(cur, intent_id: int, event_type: str, from_status, to_status,
                  operator_user_id: int, operator_role: str, remark=None):
    cur.execute(
        """
        INSERT INTO cooperation_event
            (intent_id, event_type, from_status, to_status,
             operator_user_id, operator_role, remark)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (intent_id, event_type, from_status, to_status,
         operator_user_id, operator_role, remark),
    )


def _require_role(row, user_id: int):
    """返回操作者角色；非参与方抛 404（防探测）"""
    if row["initiator_user_id"] == user_id:
        return "initiator"
    if row["target_owner_user_id"] == user_id:
        return "target_owner"
    raise coop_not_found()


# ── 发起意向 ─────────────────────────────────────────────────

def create_intent(user_id: int, user_no: str, body: dict, request_id=None):
    if not isinstance(body, dict):
        raise bad_request("请求体必须是 JSON 对象")

    target_type = body.get("targetType") or ""
    _validate_target_type(target_type)
    try:
        target_id = int(body.get("targetId"))
    except (ValueError, TypeError):
        raise bad_request("targetId 必须是整数")

    message = body.get("message")
    if message is not None:
        message = str(message).strip()[:1000] or None

    with get_cursor(commit=True) as cur:
        target = _load_target(cur, target_type, target_id)
        if not target or target["status"] != "published":
            raise coop_not_found("对接目标不存在或未发布")
        if target["owner_user_id"] == user_id:
            raise coop_bad_request()

        placeholders = ",".join(["%s"] * len(ACTIVE_STATUSES))
        cur.execute(
            f"""
            SELECT id FROM cooperation_intent
            WHERE initiator_user_id=%s AND target_type=%s AND target_id=%s
              AND status IN ({placeholders})
            """,
            (user_id, target_type, target_id) + ACTIVE_STATUSES,
        )
        if cur.fetchone():
            raise coop_active_exists()

        cur.execute(
            """
            INSERT INTO cooperation_intent
                (initiator_user_id, target_type, target_id, target_owner_user_id, message)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (user_id, target_type, target_id, target["owner_user_id"], message),
        )
        intent_id = cur.lastrowid
        _insert_event(cur, intent_id, "created", None, "pending",
                      user_id, "initiator", message)

    audit_record(
        "cooperation.create", "cooperation_intent", resource_id=intent_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"targetType": target_type, "targetId": target_id},
        request_id=request_id,
    )
    return get_intent_detail(intent_id, user_id)


# ── 查询 ─────────────────────────────────────────────────────

def get_intent_detail(intent_id: int, user_id: int):
    with get_cursor() as cur:
        row = _get_intent_row(cur, intent_id)
        if not row:
            raise coop_not_found()
        role = _require_role(row, user_id)  # 非参与方 404

        detail = _row_to_intent(row, user_id)
        # 对方展示名（user_profile.display_name）
        counterpart_id = (
            row["target_owner_user_id"] if role == "initiator" else row["initiator_user_id"]
        )
        cur.execute(
            "SELECT display_name FROM user_profile WHERE user_id=%s",
            (counterpart_id,),
        )
        p = cur.fetchone()
        detail["counterpartDisplayName"] = (p or {}).get("display_name")
        detail["targetSummary"] = _target_summary(cur, row["target_type"], row["target_id"])
    return detail


def list_my_intents(user_id: int, args):
    role = (args.get("role") or "both").strip()
    if role not in ("initiator", "target", "both"):
        raise bad_request("role 必须是 initiator/target/both")
    status = (args.get("status") or "").strip()

    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10

    where = " WHERE 1=1"
    params = []
    if role == "initiator":
        where += " AND c.initiator_user_id=%s"
        params.append(user_id)
    elif role == "target":
        where += " AND c.target_owner_user_id=%s"
        params.append(user_id)
    else:
        where += " AND (c.initiator_user_id=%s OR c.target_owner_user_id=%s)"
        params.extend([user_id, user_id])
    if status:
        where += " AND c.status=%s"
        params.append(status)

    with get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM cooperation_intent c{where}", params)
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(
            f"""
            SELECT c.* FROM cooperation_intent c{where}
            ORDER BY c.id DESC
            LIMIT %s OFFSET %s
            """,
            params + [page_size, offset],
        )
        rows = cur.fetchall() or []

        items = []
        for row in rows:
            item = _row_to_intent(row, user_id)
            item["targetSummary"] = _target_summary(cur, row["target_type"], row["target_id"])
            counterpart_id = (
                row["target_owner_user_id"]
                if row["initiator_user_id"] == user_id
                else row["initiator_user_id"]
            )
            cur.execute(
                "SELECT display_name FROM user_profile WHERE user_id=%s",
                (counterpart_id,),
            )
            p = cur.fetchone()
            item["counterpartDisplayName"] = (p or {}).get("display_name")
            items.append(item)

    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
        "list": items,
    }


def list_events(intent_id: int, user_id: int, args):
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 20)))
    except (ValueError, TypeError):
        page_size = 20

    with get_cursor() as cur:
        row = _get_intent_row(cur, intent_id)
        if not row:
            raise coop_not_found()
        _require_role(row, user_id)

        cur.execute("SELECT COUNT(*) AS c FROM cooperation_event WHERE intent_id=%s", (intent_id,))
        total = int((cur.fetchone() or {}).get("c") or 0)

        offset = (page - 1) * page_size
        cur.execute(
            """
            SELECT id, event_type, from_status, to_status, operator_role, remark, created_at
            FROM cooperation_event
            WHERE intent_id=%s
            ORDER BY id ASC
            LIMIT %s OFFSET %s
            """,
            (intent_id, page_size, offset),
        )
        rows = cur.fetchall() or []

    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
        "list": [
            {
                "id": r["id"],
                "intentId": intent_id,
                "eventType": r["event_type"],
                "fromStatus": r.get("from_status"),
                "toStatus": r["to_status"],
                "operatorRole": r["operator_role"],
                "remark": r.get("remark"),
                "createdAt": _fmt(r.get("created_at")),
            }
            for r in rows
        ],
    }


# ── 状态机 ───────────────────────────────────────────────────

def _transition(user_id: int, user_no: str, intent_id: int, version, op: str,
                remark=None, request_id=None):
    rule = TRANSITIONS[op]
    if version is None:
        raise bad_request(f"{op} 必须携带 version（乐观锁）")
    if remark:
        remark = str(remark).strip()[:500] or None

    with get_cursor(commit=True) as cur:
        row = _get_intent_row(cur, intent_id)
        if not row:
            raise coop_not_found()
        role = _require_role(row, user_id)
        if role not in rule["roles"]:
            raise coop_forbidden(f"仅 {'/'.join(rule['roles'])} 可执行 {op}")
        if row["status"] not in rule["from"]:
            raise coop_conflict(
                f"当前状态 {row['status']} 不允许 {op}（要求 {'/'.join(rule['from'])}）"
            )

        cur.execute(
            f"""
            UPDATE cooperation_intent
            SET status=%s, version=version+1, {rule['ts']}=NOW()
            WHERE id=%s AND version=%s
            """,
            (rule["to"], intent_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        _insert_event(cur, intent_id, rule["event"], row["status"], rule["to"],
                      user_id, role, remark)

        # accept 副作用：同一目标的其他 pending 意向自动拒绝（同一事务）
        if op == "accept":
            cur.execute(
                """
                SELECT id, initiator_user_id FROM cooperation_intent
                WHERE target_type=%s AND target_id=%s AND status='pending' AND id<>%s
                FOR UPDATE
                """,
                (row["target_type"], row["target_id"], intent_id),
            )
            for loser in cur.fetchall() or []:
                cur.execute(
                    """
                    UPDATE cooperation_intent
                    SET status='rejected', version=version+1, closed_at=NOW()
                    WHERE id=%s
                    """,
                    (loser["id"],),
                )
                _insert_event(cur, loser["id"], "auto_rejected", "pending", "rejected",
                              user_id, "system", "对方已接受其他意向")

        # confirm 副作用：目标为需求时自动流转 matched
        if op == "confirm" and row["target_type"] == "demand":
            cur.execute(
                "UPDATE demand SET status='matched', version=version+1 WHERE id=%s AND status='published'",
                (row["target_id"],),
            )

    audit_record(
        f"cooperation.{op}", "cooperation_intent", resource_id=intent_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"from": row["status"], "to": rule["to"]},
        request_id=request_id,
    )
    return get_intent_detail(intent_id, user_id)


def accept_intent(user_id: int, user_no: str, intent_id: int, version, request_id=None):
    return _transition(user_id, user_no, intent_id, version, "accept", request_id=request_id)


def reject_intent(user_id: int, user_no: str, intent_id: int, version, reason, request_id=None):
    if not reason or not str(reason).strip():
        raise bad_request("reject 必须携带 reason")
    return _transition(user_id, user_no, intent_id, version, "reject",
                       remark=reason, request_id=request_id)


def confirm_intent(user_id: int, user_no: str, intent_id: int, version, request_id=None):
    return _transition(user_id, user_no, intent_id, version, "confirm", request_id=request_id)


def cancel_intent(user_id: int, user_no: str, intent_id: int, version, reason, request_id=None):
    return _transition(user_id, user_no, intent_id, version, "cancel",
                       remark=reason, request_id=request_id)


def complete_intent(user_id: int, user_no: str, intent_id: int, version, remark, request_id=None):
    return _transition(user_id, user_no, intent_id, version, "complete",
                       remark=remark, request_id=request_id)
