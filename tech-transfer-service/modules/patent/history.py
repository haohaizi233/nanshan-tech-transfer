"""已登录用户的专利检索历史。"""

from core.errors import bad_request
from db import get_cursor

VALID_HISTORY_MODES = ("keyword", "assignee")
HISTORY_LIMIT = 10


def normalize_history_input(mode: str, keyword: str) -> tuple[str, str]:
    mode = (mode or "").strip()
    keyword = (keyword or "").strip()
    if mode not in VALID_HISTORY_MODES:
        raise bad_request("mode 必须是 keyword 或 assignee")
    if not keyword:
        raise bad_request("keyword 不能为空")
    if len(keyword) > 128:
        raise bad_request("keyword 长度不能超过 128")
    return mode, keyword


def _item(row: dict) -> dict:
    updated_at = row.get("updated_at")
    return {
        "keyword": row["keyword"],
        "mode": row["search_mode"],
        "updatedAt": updated_at.isoformat() if updated_at else None,
    }


def list_history(user_id: int, mode: str = "keyword") -> dict:
    mode, _ = normalize_history_input(mode, "_")
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT keyword, search_mode, updated_at
            FROM patent_search_history
            WHERE user_id=%s AND search_mode=%s
            ORDER BY updated_at DESC, id DESC
            LIMIT %s
            """,
            (user_id, mode, HISTORY_LIMIT),
        )
        rows = cur.fetchall() or []
    return {"list": [_item(row) for row in rows]}


def record_history(user_id: int, mode: str, keyword: str) -> dict:
    mode, keyword = normalize_history_input(mode, keyword)
    with get_cursor(commit=True) as cur:
        cur.execute(
            """
            INSERT INTO patent_search_history (user_id, search_mode, keyword)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id, search_mode, keyword)
            DO UPDATE SET updated_at=CURRENT_TIMESTAMP
            RETURNING keyword, search_mode, updated_at
            """,
            (user_id, mode, keyword),
        )
        row = cur.fetchone()
    return _item(row)


def clear_history(user_id: int, mode: str = "keyword") -> dict:
    mode, _ = normalize_history_input(mode, "_")
    with get_cursor(commit=True) as cur:
        cur.execute(
            "DELETE FROM patent_search_history WHERE user_id=%s AND search_mode=%s",
            (user_id, mode),
        )
        deleted = cur.rowcount
    return {"deleted": deleted}
