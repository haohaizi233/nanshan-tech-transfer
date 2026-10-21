"""
管理员修改内容的字段级变更日志（admin_edit_log）—— 发布者可见变更对比

业务背景：后台管理员修改了发布者的需求/成果后，发布者打开详情页应能看到
「哪些字段被修改了、修改前后各是什么」。本模块负责：

- compute_changes        : 对比旧值与新值，产出字段级差异（仅真实变化的字段）
- record_admin_edit_changes : 与业务写同事务落 admin_edit_log（一行一个字段）
- list_admin_changes     : 发布者拉取自己内容的变更（未读数 + 字段级对比）
- mark_admin_changes_read: 发布者看过后标记已读

展示约定（手机端字段级对比卡片，非 diff 样式）：
- change_kind='created'（绿色）：旧值为空、新值非空 —— “修改前”显示“未填写”
- change_kind='updated'（黄色）：其余真实变化（含清空 —— “修改后”显示“已清空”）
- old_value/new_value 落库即为展示文本（引用字段解析成名称、JSON 数组拼成顿号列表），
  查询侧零加工，前端直接渲染。

权限：仅内容归属人（发布者）与平台管理员可见/可标记已读。
"""
import json
from datetime import date, datetime
from decimal import Decimal

from core.errors import bad_request, forbidden

MAX_FIELD_NAME = 64
MAX_FIELD_LABEL = 64
MAX_OPERATOR_USER_NO = 32
MAX_OPERATOR_NAME = 64
MAX_VALUE_LEN = 4000
MAX_CHANGES_PER_RESPONSE = 100

# ── 字段中文名（对比卡片上的“字段名”）──────────────────────────
FIELD_LABELS = {
    "demand": {
        "title": "标题",
        "description": "需求说明",
        "region": "所在地区",
        "coop_mode": "合作方式",
        "budget_min_wan": "预算下限（万元）",
        "budget_max_wan": "预算上限（万元）",
        "budget_negotiable": "预算面议",
        "expect_deadline": "期望完成时间",
        "deadline_desc": "期望周期",
        "contact_name": "联系人",
        "contact_title": "联系人职务",
        "contact_phone": "联系电话",
        "contact_email": "联系邮箱",
        "contact_wechat": "联系微信",
        "category_id": "所属行业",
        "category_name": "所属行业",
        "org_id": "所属机构",
        "org_name_snapshot": "机构名称",
        "cooperation_policy": "合作策略",
        "cooperation_capacity": "对接名额",
    },
    "achievement": {
        "title": "成果名称",
        "title_en": "英文名称",
        "tech_intro": "技术简介",
        "tech_route": "技术路径",
        "maturity_level": "成熟度",
        "maturity_desc": "成熟度说明",
        "achievement_kind": "成果类型",
        "source_org_name": "来源单位",
        "application_fields": "应用领域",
        "innovation_points": "创新点",
        "pricing_mode": "报价方式",
        "price_min_wan": "最低报价（万元）",
        "price_max_wan": "最高报价（万元）",
        "contact_name": "联系人",
        "contact_title": "联系人职务",
        "contact_phone": "联系电话",
        "contact_email": "联系邮箱",
        "contact_wechat": "联系微信",
        "category_id": "所属分类",
        "org_id": "所属机构",
    },
}

# 引用型字段：落库是 ID，展示时解析成名称
_REF_LABEL_SQL = {
    ("demand", "category_id"): "SELECT name FROM demand_category WHERE id=%s",
    ("demand", "org_id"): "SELECT name FROM institution WHERE id=%s",
    ("achievement", "category_id"): "SELECT name FROM achievement_category WHERE id=%s",
    ("achievement", "org_id"): "SELECT name FROM institution WHERE id=%s",
}


# ── 值归一化 / 展示文本 ──────────────────────────────────────

def _is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, tuple, dict, set)):
        return len(value) == 0
    return False


def _canonical(value):
    """归一化到可比较的形态：jsonb/JSON 文本、Decimal、日期统一处理。"""
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _canonical(v) for k, v in value.items()}
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("[", "{"):
            try:
                return _canonical(json.loads(text))
            except (ValueError, TypeError):
                return text
        return text
    return str(value)


def _display(value) -> str:
    """把落库值渲染成手机端卡片上的展示文本。"""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, Decimal):
        value = float(value)
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()[:10] if not isinstance(value, datetime) else value.strftime("%Y-%m-%d %H:%M")
    if isinstance(value, (list, tuple)):
        return "、".join(_display(item) for item in value if not _is_blank(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, str):
        text = value.strip()
        if text[:1] in ("[", "{"):
            try:
                return _display(json.loads(text))
            except (ValueError, TypeError):
                return text
        return text
    return str(value)


def _ref_label(cur, target_type: str, field: str, value):
    """引用字段（ID）解析为可读名称；解析失败退回原始展示。"""
    if value is None or isinstance(value, str):
        return _display(value)
    sql = _REF_LABEL_SQL.get((target_type, field))
    if not sql:
        return _display(value)
    try:
        cur.execute(sql, (int(value),))
        row = cur.fetchone()
    except Exception:
        return _display(value)
    if not row:
        return _display(value)
    if isinstance(row, dict):
        return str(row.get("name") or _display(value))
    return str(row[0] or _display(value))


def _clip(text: str) -> str:
    return text if len(text) <= MAX_VALUE_LEN else text[: MAX_VALUE_LEN - 1] + "…"


# ── 差异计算 ─────────────────────────────────────────────────

def compute_changes(cur, target_type: str, old_row, fields: dict, extras=None) -> list[dict]:
    """对比旧值与本次写入值，产出字段级变更（只保留真实变化的字段）。

    cur        : 同事务游标（引用字段解析名称用，可为 None）
    old_row    : 更新前的行（dict / RealDictRow），None 视为全部空
    fields     : 本次写入的 column → 新值（DB 形态）
    extras     : 追加的合成变更，如标签/完成人：
                 [{"field": "tags", "fieldLabel": "标签",
                   "oldValue": "A、B", "newValue": "A、C"}]（均为展示文本）
    """
    labels = FIELD_LABELS.get(target_type, {})
    changes = []
    for column, new_value in (fields or {}).items():
        old_value = old_row.get(column) if old_row else None
        if _canonical(old_value) == _canonical(new_value):
            continue
        if column in _REF_LABEL_SQL:
            old_text = _ref_label(cur, target_type, column, old_value) if old_value is not None else ""
            new_text = _ref_label(cur, target_type, column, new_value) if new_value is not None else ""
        else:
            old_text = _display(old_value)
            new_text = _display(new_value)
        changes.append({
            "field": column[:MAX_FIELD_NAME],
            "fieldLabel": (labels.get(column) or column)[:MAX_FIELD_LABEL],
            "changeKind": "created" if _is_blank(old_value) and not _is_blank(new_value) else "updated",
            "oldValue": _clip(old_text),
            "newValue": _clip(new_text),
        })

    for item in extras or []:
        old_text = str(item.get("oldValue") or "")
        new_text = str(item.get("newValue") or "")
        if old_text == new_text:
            continue
        changes.append({
            "field": str(item.get("field") or "extra")[:MAX_FIELD_NAME],
            "fieldLabel": str(item.get("fieldLabel") or item.get("field") or "其他")[:MAX_FIELD_LABEL],
            "changeKind": "created" if not old_text.strip() and new_text.strip() else "updated",
            "oldValue": _clip(old_text),
            "newValue": _clip(new_text),
        })
    return changes


# ── 写入（与管理端业务写同事务） ──────────────────────────────

def record_admin_edit_changes(
    cur,
    target_type: str,
    target_id: int,
    changes: list[dict],
    operator_user_id=None,
    operator_user_no=None,
    operator_name=None,
) -> int:
    """把一次管理员修改的字段级差异写入 admin_edit_log。

    与业务写共用 cur（同事务）：业务回滚则变更日志同步回滚，不会出现
    “记录了变更但数据没改”的假日志。无实际变化时直接返回 0。
    """
    changes = [c for c in (changes or []) if c.get("field")]
    if not changes:
        return 0
    if not operator_name and operator_user_id:
        try:
            cur.execute("SELECT display_name FROM user_profile WHERE user_id=%s", (operator_user_id,))
            profile = cur.fetchone()
            operator_name = _row_value(profile, "display_name") if profile else None
        except Exception:
            operator_name = None
    cur.execute("SELECT nextval('admin_edit_log_batch_seq') AS batch_id")
    row = cur.fetchone()
    batch_id = row["batch_id"] if isinstance(row, dict) else row[0]
    for change in changes:
        cur.execute(
            """
            INSERT INTO admin_edit_log
                (batch_id, target_type, target_id, field_name, field_label,
                 change_kind, old_value, new_value,
                 operator_user_id, operator_user_no, operator_name)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """,
            (
                batch_id,
                target_type,
                target_id,
                change.get("field"),
                change.get("fieldLabel") or change.get("field"),
                change.get("changeKind") or "updated",
                change.get("oldValue") or None,
                change.get("newValue") or None,
                operator_user_id,
                (operator_user_no or None) and str(operator_user_no)[:MAX_OPERATOR_USER_NO],
                (operator_name or None) and str(operator_name)[:MAX_OPERATOR_NAME],
            ),
        )
    return len(changes)


# ── 查询 / 已读（发布者侧） ──────────────────────────────────

_TABLE_BY_TYPE = {"demand": "demand", "achievement": "achievement"}


def _assert_owner_or_admin(cur, target_type: str, target_id: int, user: dict) -> None:
    """仅内容归属人（发布者）与平台管理员可见变更对比。"""
    table = _TABLE_BY_TYPE.get(target_type)
    if not table:
        raise bad_request("targetType 仅支持 demand / achievement")
    cur.execute(
        f"SELECT owner_user_id FROM {table} WHERE id=%s AND deleted_at IS NULL",
        (target_id,),
    )
    row = cur.fetchone()
    if not row:
        from core.errors import not_found
        raise not_found("内容不存在或已删除")
    owner_user_id = row["owner_user_id"] if isinstance(row, dict) else row[0]
    viewer_id = user.get("userId")
    if owner_user_id is not None and viewer_id == owner_user_id:
        return
    # 平台管理员（user_role 实时判定）可查看；归属为空（平台代录）时无人可见
    cur.execute(
        "SELECT 1 FROM user_role WHERE user_id=%s AND role_code='admin'",
        (viewer_id,),
    )
    if cur.fetchone():
        return
    raise forbidden("仅发布者本人可以查看管理员修改记录")


def _row_value(row, key: str, index: int = 0):
    """兼容 RealDictRow（按 key）与普通 tuple 游标（按下标）。"""
    try:
        return row[key]
    except (TypeError, KeyError, IndexError):
        return row[index]


def _row_to_change(row) -> dict:
    created_at = _row_value(row, "created_at", 9)
    return {
        "id": _row_value(row, "id", 0),
        "batchId": _row_value(row, "batch_id", 1),
        "field": _row_value(row, "field_name", 2),
        "fieldLabel": _row_value(row, "field_label", 3),
        "changeKind": _row_value(row, "change_kind", 4),
        "oldValue": _row_value(row, "old_value", 5) or "",
        "newValue": _row_value(row, "new_value", 6) or "",
        "operatorName": _row_value(row, "operator_name", 7) or _row_value(row, "operator_user_no", 8) or "管理员",
        "createdAt": created_at.strftime("%Y-%m-%d %H:%M") if hasattr(created_at, "strftime") else str(created_at or ""),
    }


def list_admin_changes(target_type: str, target_id: int, user: dict) -> dict:
    """"GET /demands|achievements/{id}/admin-changes —— 未读数 + 字段级对比。"""
    from db import get_cursor

    with get_cursor() as cur:
        _assert_owner_or_admin(cur, target_type, target_id, user)
        cur.execute(
            """
            SELECT id, batch_id, field_name, field_label, change_kind,
                   old_value, new_value, operator_name, operator_user_no, created_at
            FROM admin_edit_log
            WHERE target_type=%s AND target_id=%s
            ORDER BY id DESC
            LIMIT %s
            """,
            (target_type, target_id, MAX_CHANGES_PER_RESPONSE),
        )
        rows = cur.fetchall() or []
        cur.execute(
            "SELECT COUNT(*) AS n FROM admin_edit_log WHERE target_type=%s AND target_id=%s AND read_at IS NULL",
            (target_type, target_id),
        )
        count_row = cur.fetchone()
        unread = _row_value(count_row, "n")
        cur.execute(
            "SELECT COUNT(*) AS n FROM admin_edit_log WHERE target_type=%s AND target_id=%s",
            (target_type, target_id),
        )
        total_row = cur.fetchone()
        total = _row_value(total_row, "n")

    changes = [_row_to_change(row) for row in rows]
    return {
        "targetType": target_type,
        "targetId": target_id,
        "unreadCount": int(unread or 0),
        "totalCount": int(total or 0),
        "changes": changes,
    }


def mark_admin_changes_read(target_type: str, target_id: int, user: dict) -> dict:
    """POST /demands|achievements/{id}/admin-changes/read —— 标记已读。"""
    from db import get_cursor

    if target_type not in _TABLE_BY_TYPE:
        raise bad_request("targetType 仅支持 demand / achievement")
    with get_cursor(commit=True) as cur:
        _assert_owner_or_admin(cur, target_type, target_id, user)
        cur.execute(
            """
            UPDATE admin_edit_log
            SET read_at = NOW()
            WHERE target_type=%s AND target_id=%s AND read_at IS NULL
            """,
            (target_type, target_id),
        )
        marked = cur.rowcount or 0
    return {"targetType": target_type, "targetId": target_id, "markedRead": int(marked)}
