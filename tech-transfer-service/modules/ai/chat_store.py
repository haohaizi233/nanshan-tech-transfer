"""AI 聊天记录入库（快照）。

- append_message：写入一条 user/assistant 消息；assistant 推荐卡片时 cards 存完整快照数组。
- list_messages：按 id 升序返回最近 limit 条（内部按 id DESC 取后再 reverse）。
- clear_messages：清空当前用户的全部聊天记录。

设计要点：
- 只持久化真实对话轮（用户文本、助手文本/卡片）；欢迎语、demand-picker 等过渡 UI 不入库。
- 卡片存完整快照而非仅 id：加载即开即用、零回查；卡片自带 id，点击仍跳最新详情页。
- 失败的 AI 调用（503 等）由 routes/ai.py 通过 append_turn 入库，刷新后仍可见用户原问题。
"""

from psycopg2.extras import Json

from db import get_cursor

_VALID_ROLES = ('user', 'assistant')


def append_turn(user_id: int, user_message: str, assistant_message: str, cards=None) -> None:
    """原子写入一轮对话（user + assistant），避免只落一半。"""
    cards_json = Json(cards) if cards is not None else None
    with get_cursor(commit=True) as cur:
        cur.execute(
            '''INSERT INTO ai_chat_message (user_id, role, content, cards)
               VALUES (%s, 'user', %s, NULL)''',
            (user_id, user_message),
        )
        cur.execute(
            '''INSERT INTO ai_chat_message (user_id, role, content, cards)
               VALUES (%s, 'assistant', %s, %s)''',
            (user_id, assistant_message or '', cards_json),
        )


def append_message(user_id: int, role: str, content: str, cards=None) -> dict:
    """追加一条聊天消息，返回 {id, createdAt}。"""
    if role not in _VALID_ROLES:
        raise ValueError(f'invalid role: {role!r}')
    cards_json = Json(cards) if cards is not None else None
    with get_cursor(commit=True) as cur:
        cur.execute(
            '''INSERT INTO ai_chat_message (user_id, role, content, cards)
               VALUES (%s, %s, %s, %s)
               RETURNING id, created_at''',
            (user_id, role, content or '', cards_json),
        )
        row = cur.fetchone()
    return {
        'id': row['id'],
        'createdAt': row['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
    }


def list_messages(user_id: int, limit: int = 100) -> list[dict]:
    """返回当前用户最近 limit 条聊天消息（按时间升序）。"""
    limit = max(1, min(int(limit or 100), 200))
    with get_cursor() as cur:
        cur.execute(
            '''SELECT id, role, content, cards, created_at
               FROM ai_chat_message
               WHERE user_id = %s
               ORDER BY id DESC
               LIMIT %s''',
            (user_id, limit),
        )
        rows = cur.fetchall() or []
    rows.reverse()  # 升序回放
    return [
        {
            'id': row['id'],
            'role': row['role'],
            'content': row.get('content') or '',
            'cards': row.get('cards') or None,
            'createdAt': row['created_at'].strftime('%Y-%m-%d %H:%M:%S'),
        }
        for row in rows
    ]


def clear_messages(user_id: int) -> int:
    """清空当前用户的全部聊天记录，返回删除条数。"""
    with get_cursor(commit=True) as cur:
        cur.execute('DELETE FROM ai_chat_message WHERE user_id = %s', (user_id,))
        return cur.rowcount
