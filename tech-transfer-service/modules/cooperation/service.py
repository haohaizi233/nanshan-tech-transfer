"""
对接模块服务层 —— 意向创建、列表/详情、状态机（accept/reject/confirm/cancel/complete）、事件时间线

Architecture source: 04-backend-domain-design.md §4.8, 05-data-model-design.md §6.2/§6.3,
                     06-api-design.md §5（cooperation 状态机与权限矩阵）、openapi.yaml paths /cooperations
状态机（后端强校验）:
  pending  → accepted / rejected / cancelled (target_owner: accept / reject；initiator: cancel=撤回)
  accepted → confirmed / cancelled      (双方: confirm / cancel)
  confirmed → completed / cancelled     (双方: complete / cancel)
副作用:
  accept   → 同一目标的其他 pending 意向自动拒绝（event=auto_rejected，同一事务）
  confirm  → 目标为需求时自动流转 matched
数据权限:
  详情/事件仅 initiator / target_owner 可见，其余 404（防探测）
平台协助对接（assisted，2026-09-07）:
  目标内容 owner_user_id 为 NULL（管理员代录入、真实机构无平台账号）时，
  意向自动进入 assisted 模式：target_owner 恒为 NULL，普通用户（含发起方）对目标方
  动作（accept/reject）一律 404 防探测，由平台代为执行（assist-transition）；
  由平台运营线下联系真实机构，assist_status 记录处理阶段，
  机构明确同意（target_agreed）后 Admin 才能以 platform_assisted 模式代为 accept，
  accepted 后联系方式才向申请人解锁（脱敏逻辑不变，凭 status 判断）。
"""
import json

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
# 对接被接受及之后的终态 —— 联系方式解锁阈值（脱敏用）
ACCEPTED_STATUSES = ("accepted", "confirmed", "completed")

# 合作意向：由用户每次发起对接时选择，与账号主体类型/合作方向画像完全解耦
# （主体类型/画像仅用于推荐，见 user_profile.subject_type / business_capabilities）
INTENT_TYPES = {
    "demand": (
        "provide_solution",     # 提供技术方案
        "provide_achievement",  # 提供现有成果
        "joint_rnd",            # 联合研发
        "provide_service",      # 提供技术服务
        "investment",           # 投融资支持
        "other",                # 其他
    ),
    "achievement": (
        "purchase",             # 技术购买
        "license",              # 技术许可
        "joint_rnd",            # 联合研发
        "commercialization",    # 成果转化
        "pilot_validation",     # 场景验证
        "investment",           # 投融资
        "other",                # 其他
    ),
}

# op → (允许的前置状态, 目标状态, 允许角色, 时间戳列, 事件类型)
TRANSITIONS = {
    "accept":   {"from": ("pending",),              "to": "accepted",  "roles": ("target_owner",), "ts": "accepted_at",  "event": "accepted"},
    "reject":   {"from": ("pending",),              "to": "rejected",  "roles": ("target_owner",), "ts": "closed_at",    "event": "rejected"},
    "confirm":  {"from": ("accepted",),             "to": "confirmed", "roles": ("initiator", "target_owner"), "ts": "confirmed_at", "event": "confirmed"},
    "cancel":   {"from": ("pending", "accepted", "confirmed"), "to": "cancelled", "roles": ("initiator", "target_owner"), "ts": "closed_at", "event": "cancelled"},
    "complete": {"from": ("confirmed",),            "to": "completed", "roles": ("initiator", "target_owner"), "ts": "completed_at", "event": "completed"},
}

# ── 平台协助对接（assisted）──────────────────────────────────
# 运营处理阶段（与主状态分离；unreachable 等仍属 status=pending）
ASSIST_STATUSES = (
    "queued",           # 已入队，待运营跟进
    "contacting",       # 运营正在联系真实机构
    "waiting_reply",    # 已联系，等待机构回复
    "target_agreed",    # 机构明确同意 —— Admin 代为 accept 的强制前置
    "target_rejected",  # 机构明确拒绝
    "unreachable",      # 联系不上
)

# assist_status 流转表（仅 assisted 意向、主状态 pending 期间）
ASSIST_STATUS_TRANSITIONS = {
    "queued": ("contacting", "unreachable"),
    "contacting": ("waiting_reply", "target_agreed", "target_rejected", "unreachable"),
    "waiting_reply": ("contacting", "target_agreed", "target_rejected", "unreachable"),
    "unreachable": ("contacting",),
}

# Admin 代目标机构操作的状态机（仅 assisted；event/operator_role=platform_admin 留痕）
ADMIN_TRANSITIONS = {
    "accept":   {"from": ("pending",),              "to": "accepted",  "ts": "accepted_at",  "event": "accepted",  "require_assist": "target_agreed"},
    "reject":   {"from": ("pending",),              "to": "rejected",  "ts": "closed_at",    "event": "rejected",  "require_assist": None},
    "confirm":  {"from": ("accepted",),             "to": "confirmed", "ts": "confirmed_at", "event": "confirmed", "require_assist": None},
    "cancel":   {"from": ("accepted", "confirmed"), "to": "cancelled", "ts": "closed_at",    "event": "cancelled", "require_assist": None},
    "complete": {"from": ("confirmed",),            "to": "completed", "ts": "completed_at", "event": "completed", "require_assist": None},
}


def _validate_target_type(target_type: str):
    if target_type not in TARGET_TYPES:
        raise bad_request(f"targetType 必须是 {'/'.join(TARGET_TYPES)}")


def _validate_intent_type(target_type: str, intent_type):
    """合作意向按目标类型校验；None/空串放行（兼容不带意向的历史调用方）"""
    if intent_type is None or intent_type == "":
        return None
    intent_type = str(intent_type).strip()
    allowed = INTENT_TYPES[target_type]
    if intent_type not in allowed:
        raise bad_request(
            f"intentType 必须是 {'/'.join(allowed)}（目标为 {target_type}）"
        )
    return intent_type


def has_accepted_intent(cur, target_type: str, target_id: int, user_id) -> bool:
    """该用户作为发起方、且已被目标方接受的对接是否存在（accepted/confirmed/completed）。

    联系方式脱敏判断：目标方接受对接后，发起方才可查看目标方完整联系方式。
    """
    if user_id is None:
        return False
    cur.execute(
        """
        SELECT 1 FROM cooperation_intent
        WHERE target_type=%s AND target_id=%s
          AND initiator_user_id=%s
          AND status IN ('accepted', 'confirmed', 'completed')
        LIMIT 1
        """,
        (target_type, target_id, user_id),
    )
    return cur.fetchone() is not None


def _load_target(cur, target_type: str, target_id: int):
    """加载对接目标（须 published）；owner_user_id 为 NULL 表示平台代录（assisted）"""
    if target_type == "demand":
        cur.execute(
            "SELECT id, owner_user_id, status, org_id FROM demand WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    else:
        cur.execute(
            "SELECT id, owner_user_id, status, org_id FROM achievement WHERE id=%s AND deleted_at IS NULL",
            (target_id,),
        )
    return cur.fetchone()


def _target_summary(cur, target_type: str, target_id: int):
    if target_type == "demand":
        cur.execute(
            """
            SELECT d.title, d.status, o.name AS org_name
            FROM demand d
            LEFT JOIN institution o ON d.org_id = o.id
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


def _counterpart_display(cur, row, user_id: int):
    """对接对方展示名：direct=对方账号 display_name；assisted=目标机构名（无平台账号）。"""
    if row["initiator_user_id"] == user_id:
        counterpart_id = row["target_owner_user_id"]  # assisted 时为 None
    else:
        counterpart_id = row["initiator_user_id"]
    if counterpart_id is None:
        if row.get("target_org_id"):
            cur.execute("SELECT name FROM institution WHERE id=%s", (row["target_org_id"],))
            org = cur.fetchone()
            if org and org.get("name"):
                return org["name"]
        return None
    cur.execute("SELECT display_name FROM user_profile WHERE user_id=%s", (counterpart_id,))
    p = cur.fetchone()
    return (p or {}).get("display_name")


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
        "intentType": row.get("intent_type"),
        "message": row.get("message"),
        "status": row["status"],
        "handlingMode": row.get("handling_mode") or "direct",
        "assistStatus": row.get("assist_status"),
        "acceptMode": row.get("accept_mode"),
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

    intent_type = _validate_intent_type(target_type, body.get("intentType"))

    message = body.get("message")
    if message is not None:
        message = str(message).strip()[:1000] or None

    # 联系方式共享同意：提交申请即视为同意平台将申请方联系方式提供给目标机构/平台运营；
    # 前端显式传 false 时拒绝创建（不静默落库）
    if body.get("contactShareConsent") is False:
        raise bad_request("发起对接需同意平台向目标机构提供您的联系方式")

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

        # 处理模式：目标方无平台账号（管理员代录入）→ assisted，平台协助对接
        handling_mode = "direct" if target["owner_user_id"] is not None else "assisted"

        # 申请方联系方式快照：创建时点生成，防止事后改资料导致历史申请联系人漂移
        cur.execute(
            """
            SELECT p.display_name, p.phone, p.email, p.org_title, o.name AS org_name
            FROM user_profile p
            LEFT JOIN institution o ON p.org_id = o.id
            WHERE p.user_id = %s
            """,
            (user_id,),
        )
        prof = cur.fetchone() or {}
        contact_snapshot = json.dumps(
            {
                "displayName": prof.get("display_name"),
                "phone": prof.get("phone"),
                "email": prof.get("email"),
                "orgTitle": prof.get("org_title"),
                "orgName": prof.get("org_name"),
            },
            ensure_ascii=False,
        )

        cur.execute(
            """
            INSERT INTO cooperation_intent
                (initiator_user_id, target_type, target_id, target_owner_user_id,
                 intent_type, message, handling_mode, assist_status, target_org_id,
                 initiator_contact_snapshot, contact_share_consent_at)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW())
            RETURNING id
            """,
            (user_id, target_type, target_id, target["owner_user_id"],
             intent_type, message, handling_mode,
             "queued" if handling_mode == "assisted" else None,
             target.get("org_id"), contact_snapshot),
        )
        intent_id = cur.fetchone()["id"]
        _insert_event(cur, intent_id, "created", None, "pending",
                      user_id, "initiator", message)

    audit_record(
        "cooperation.create", "cooperation_intent", resource_id=intent_id,
        actor_user_id=user_id, actor_user_no=user_no,
        details={"targetType": target_type, "targetId": target_id,
                 "handlingMode": handling_mode},
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
        # 对方展示名：direct=对方账号；assisted=目标机构名
        name = _counterpart_display(cur, row, user_id)
        if name is None:
            name = "目标机构"
        detail["counterpartDisplayName"] = name
        detail["platformAssisted"] = (row.get("handling_mode") or "direct") == "assisted"
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
            name = _counterpart_display(cur, row, user_id)
            if name is None:
                name = "目标机构"
            item["counterpartDisplayName"] = name
            item["platformAssisted"] = (row.get("handling_mode") or "direct") == "assisted"
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

def _auto_reject_other_pending(cur, row, intent_id: int, operator_user_id: int):
    """accept 副作用：同一目标的其他 pending 意向自动拒绝（同一事务）"""
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
                      operator_user_id, "system", "对方已接受其他意向")


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
        # assisted 意向的目标方动作（accept/reject）只能由平台代为执行
        # （assist-transition），普通用户（含发起方）一律 404 防探测
        if (row.get("handling_mode") or "direct") == "assisted" \
                and set(rule["roles"]) == {"target_owner"}:
            raise coop_not_found()
        if role not in rule["roles"]:
            raise coop_forbidden(f"仅 {'/'.join(rule['roles'])} 可执行 {op}")
        if row["status"] not in rule["from"]:
            raise coop_conflict(
                f"当前状态 {row['status']} 不允许 {op}（要求 {'/'.join(rule['from'])}）"
            )
        # pending 阶段撤回是发起方专属动作；目标方此时应使用 reject
        if op == "cancel" and row["status"] == "pending" and role != "initiator":
            raise coop_forbidden("仅发起方可撤回待响应的对接申请")

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

        # 目标方自行接受 → accept_mode=self（历史行为语义化）
        if op == "accept":
            cur.execute(
                "UPDATE cooperation_intent SET accept_mode='self' WHERE id=%s",
                (intent_id,),
            )

        _insert_event(cur, intent_id, rule["event"], row["status"], rule["to"],
                      user_id, role, remark)

        if op == "accept":
            _auto_reject_other_pending(cur, row, intent_id, user_id)

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


# ── 平台协助对接：Admin 运营操作 ──────────────────────────────

def update_assist_status(admin_user: dict, intent_id: int, body: dict, request_id=None):
    """POST /admin/cooperations/{id}/assist-status —— 运营处理阶段流转（仅 assisted + pending）。

    assist_status 是主状态机之外的操作台账：queued → contacting → waiting_reply →
    target_agreed / target_rejected / unreachable。CAS 于 assist_status 本身，
    不动 version（主状态机乐观锁语义不受运营台账影响）。
    """
    to_status = str(body.get("assistStatus") or "").strip()
    if to_status not in ASSIST_STATUSES:
        raise bad_request(f"assistStatus 必须是 {'/'.join(ASSIST_STATUSES)}")
    note = body.get("note")
    if note is not None:
        note = str(note).strip()[:500] or None

    with get_cursor(commit=True) as cur:
        row = _get_intent_row(cur, intent_id)
        if not row:
            raise coop_not_found()
        if (row.get("handling_mode") or "direct") != "assisted":
            raise bad_request("仅平台协助（assisted）意向可更新处理阶段")
        if row["status"] != "pending":
            raise coop_conflict(f"主状态 {row['status']} 不允许更新处理阶段（要求 pending）")
        current = row.get("assist_status") or "queued"
        if to_status not in ASSIST_STATUS_TRANSITIONS.get(current, ()):
            raise coop_conflict(f"处理阶段 {current} 不允许流转到 {to_status}")

        cur.execute(
            """
            UPDATE cooperation_intent
            SET assist_status=%s, handled_by_user_id=%s,
                assist_note=COALESCE(%s, assist_note)
            WHERE id=%s AND assist_status IS NOT DISTINCT FROM %s AND status='pending'
            """,
            (to_status, admin_user["userId"], note, intent_id, current),
        )
        if cur.rowcount == 0:
            raise conflict("处理阶段已被其他运营更新，请刷新后重试")

        event_remark = f"处理阶段 {current} → {to_status}" + (f"：{note}" if note else "")
        _insert_event(cur, intent_id, "assist_status_change", row["status"], row["status"],
                      admin_user["userId"], "platform_admin", event_remark)

        audit_record(
            "cooperation.assist_status", "cooperation_intent", resource_id=intent_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details={"from": current, "to": to_status, "note": note},
            request_id=request_id, cur=cur,
        )
    return {"id": intent_id, "status": row["status"], "assistStatus": to_status}


def admin_assist_transition(admin_user: dict, intent_id: int, body: dict, request_id=None):
    """POST /admin/cooperations/{id}/assist-transition —— 平台代目标机构操作主状态机。

    仅 assisted 意向（目标机构无平台账号，无人可代其点击）。
    accept 强制前置 assist_status='target_agreed'：真实机构明确同意后才能代为接受，
    同意事实先由运营录入系统（update_assist_status），再执行代操作 —— 全程审计留痕。
    """
    action = str(body.get("action") or "").strip()
    if action not in ADMIN_TRANSITIONS:
        raise bad_request(f"action 必须是 {'/'.join(ADMIN_TRANSITIONS)}")
    rule = ADMIN_TRANSITIONS[action]
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    reason = body.get("reason")
    if reason is not None:
        reason = str(reason).strip()[:500] or None
    if action == "reject" and not reason:
        raise bad_request("reject 必须携带 reason")
    # 代 accept 必须填写确认依据（线下获得机构明确同意的事实记录）
    # 防止管理员看到申请就直接点接受，必须先联系机构并获得明确同意
    confirmation_note = body.get("confirmationNote")
    if confirmation_note is not None:
        confirmation_note = str(confirmation_note).strip()[:500] or None
    if action == "accept" and not confirmation_note:
        raise bad_request("accept 必须携带 confirmationNote（确认依据：真实机构明确同意对接的记录）")

    with get_cursor(commit=True) as cur:
        row = _get_intent_row(cur, intent_id)
        if not row:
            raise coop_not_found()
        if (row.get("handling_mode") or "direct") != "assisted":
            raise bad_request("仅平台协助（assisted）意向可由平台代为操作")
        if row["status"] not in rule["from"]:
            raise coop_conflict(
                f"当前状态 {row['status']} 不允许 {action}（要求 {'/'.join(rule['from'])}）"
            )
        if rule["require_assist"] and row.get("assist_status") != rule["require_assist"]:
            raise coop_conflict(
                f"须先将处理阶段更新为 {rule['require_assist']}（真实机构明确同意）才能代为 {action}"
            )

        cur.execute(
            f"""
            UPDATE cooperation_intent
            SET status=%s, version=version+1, {rule['ts']}=NOW(),
                handled_by_user_id=%s,
                accept_mode=CASE WHEN %s='accept' THEN 'platform_assisted' ELSE accept_mode END
            WHERE id=%s AND version=%s
            """,
            (rule["to"], admin_user["userId"], action, intent_id, version),
        )
        if cur.rowcount == 0:
            raise conflict("version 不匹配，请刷新后重试（乐观锁）")

        # 操作留痕：reject 用 reason，accept 用 confirmationNote 作为确认依据写入事件备注
        event_remark = reason
        if action == "accept" and confirmation_note:
            event_remark = f"确认依据：{confirmation_note}"
        _insert_event(cur, intent_id, rule["event"], row["status"], rule["to"],
                      admin_user["userId"], "platform_admin", event_remark)

        if action == "accept":
            _auto_reject_other_pending(cur, row, intent_id, admin_user["userId"])
        if action == "confirm" and row["target_type"] == "demand":
            cur.execute(
                "UPDATE demand SET status='matched', version=version+1 WHERE id=%s AND status='published'",
                (row["target_id"],),
            )

        audit_details = {"from": row["status"], "to": rule["to"],
                         "onBehalfOf": "target_org", "reason": reason or None}
        if action == "accept":
            audit_details["confirmationNote"] = confirmation_note

        audit_record(
            f"cooperation.admin_{action}", "cooperation_intent", resource_id=intent_id,
            actor_user_id=admin_user["userId"], actor_user_no=admin_user.get("userNo", ""),
            details=audit_details,
            request_id=request_id, cur=cur,
        )

    return {
        "id": intent_id,
        "status": rule["to"],
        "acceptMode": "platform_assisted" if action == "accept" else row.get("accept_mode"),
    }
