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


def _session_generation(cur, user_id):
    cur.execute("SELECT to_regclass('ai_chat_session') AS relation")
    relation = cur.fetchone()
    if not relation or not relation['relation']:
        return None
    from modules.ai.chat_runs import _lock_session
    return _lock_session(cur, user_id)


def capture_generation(user_id):
    with get_cursor(commit=True) as cur:
        return _session_generation(cur, user_id)


def _turn_view(row: dict | None) -> dict | None:
    if not row:
        return None
    if row.get('execution_mode') == 'durable':
        from modules.ai.chat_runs import run_view
        return run_view(row)
    def format_time(value):
        return value.isoformat() if value else None
    result = {
        'turnId': row['turn_id'],
        'status': row['status'],
        'reply': row.get('reply'),
        'cards': row.get('cards'),
        'errorMessage': row.get('error_message'),
        'errorCode': row.get('error_code'),
        'errorStatus': row.get('error_status'),
        'createdAt': format_time(row.get('created_at')),
        'updatedAt': format_time(row.get('updated_at')),
    }
    if 'generation' in row:
        result['generation'] = row['generation']
    return result


def start_turn(user_id: int, turn_id: str, user_message: str, reference=None) -> tuple[dict, bool]:
    """Create a running turn once, or return the existing per-user turn."""
    with get_cursor(commit=True) as cur:
        generation = _session_generation(cur, user_id)
        if generation is not None:
            from core.errors import conflict
            from modules.ai.chat_runs import request_hash
            cur.execute("SELECT 1 FROM ai_chat_tombstone WHERE user_id = %s AND turn_id = %s AND expires_at > clock_timestamp()", (user_id, turn_id))
            if cur.fetchone():
                raise conflict('该轮次已清空，请重新发起提问', {'reason': 'chat_history_cleared', 'accepted': False})
            cur.execute("SELECT * FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s", (user_id, turn_id))
            existing = cur.fetchone()
            fingerprint = request_hash(user_message, reference)
            if existing:
                if (existing.get('request_hash') or request_hash(existing['user_message'])) != fingerprint:
                    raise conflict('相同 turnId 的请求内容不一致', {'reason': 'turn_request_conflict', 'accepted': False})
                return _turn_view(existing), False
            cur.execute(
                """INSERT INTO ai_chat_turn(user_id, turn_id, status, user_message, execution_mode, request_hash, generation, reference)
                   VALUES (%s, %s, 'running', %s, 'sync', %s, %s, %s) RETURNING *""",
                (user_id, turn_id, user_message.strip(), fingerprint, generation, Json(reference) if reference else None),
            )
            return _turn_view(cur.fetchone()), True
        cur.execute(
            '''INSERT INTO ai_chat_turn (user_id, turn_id, status, user_message)
               VALUES (%s, %s, 'running', %s)
               ON CONFLICT (user_id, turn_id) DO NOTHING
               RETURNING turn_id, status, reply, cards, error_message, error_code,
                         error_status, created_at, updated_at''',
            (user_id, turn_id, user_message),
        )
        row = cur.fetchone()
        created = row is not None
        if row is None:
            cur.execute(
                '''SELECT turn_id, status, reply, cards, error_message, error_code,
                          error_status, created_at, updated_at
                   FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s''',
                (user_id, turn_id),
            )
            row = cur.fetchone()
    if row is None:
        raise RuntimeError('AI chat turn disappeared after insert conflict')
    return _turn_view(row), created


def get_turn(user_id: int, turn_id: str) -> dict | None:
    """Read a turn only inside the authenticated user's namespace."""
    with get_cursor() as cur:
        cur.execute(
            '''SELECT *
               FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s''',
            (user_id, turn_id),
        )
        row = cur.fetchone()
    return _turn_view(row)


def _insert_turn_messages(cur, user_id: int, user_message: str, assistant_message: str, cards=None, generation=None, turn_id=None):
    cards_json = Json(cards) if cards is not None else None
    if generation is not None:
        cur.execute(
            """INSERT INTO ai_chat_message(user_id, role, content, cards, generation, turn_id)
               VALUES (%s, 'user', %s, NULL, %s, %s), (%s, 'assistant', %s, %s, %s, %s)""",
            (user_id, user_message, generation, turn_id, user_id, assistant_message or '', cards_json, generation, turn_id),
        )
        return
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


def _finish_sync_turn(cur, user_id, turn_id, user_message, reply, cards, generation, error_code=None, error_status=None):
    status = 'failed' if error_code else 'succeeded'
    cur.execute(
        """UPDATE ai_chat_turn SET status = %s, reply = %s, cards = %s,
                  error_message = %s, error_code = %s, error_status = %s,
                  updated_at = now(), completed_at = now()
           WHERE user_id = %s AND turn_id = %s AND generation = %s
             AND execution_mode = 'sync' AND status = 'running' AND user_message = %s RETURNING *""",
        (status, reply or '', Json(cards) if cards is not None else None,
         reply if error_code else None, error_code, error_status, user_id, turn_id, generation, user_message.strip()),
    )
    row = cur.fetchone()
    if row:
        _insert_turn_messages(cur, user_id, user_message, reply, cards, generation)
    return _turn_view(row)


def complete_turn(user_id: int, turn_id: str, user_message: str, reply: str, cards=None, expected_generation=None) -> dict | None:
    """Atomically finish a running turn and persist its user/assistant message pair."""
    cards_json = Json(cards) if cards is not None else None
    with get_cursor(commit=True) as cur:
        generation = _session_generation(cur, user_id)
        if generation is not None:
            if expected_generation != generation:
                return None
            return _finish_sync_turn(cur, user_id, turn_id, user_message, reply, cards, generation)
        cur.execute(
            '''UPDATE ai_chat_turn
               SET status = 'succeeded', reply = %s, cards = %s,
                   error_message = NULL, error_code = NULL, error_status = NULL,
                   updated_at = now(), completed_at = now()
               WHERE user_id = %s AND turn_id = %s AND status = 'running'
               RETURNING turn_id, status, reply, cards, error_message, error_code,
                         error_status, created_at, updated_at''',
            (reply or '', cards_json, user_id, turn_id),
        )
        row = cur.fetchone()
        if row is not None:
            _insert_turn_messages(cur, user_id, user_message, reply or '', cards)
        else:
            cur.execute(
                '''SELECT turn_id, status, reply, cards, error_message, error_code,
                          error_status, created_at, updated_at
                   FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s''',
                (user_id, turn_id),
            )
            row = cur.fetchone()
    return _turn_view(row)


def fail_turn(
    user_id: int, turn_id: str, user_message: str, error_message: str,
    error_code: str, error_status: int, expected_generation=None,
) -> dict | None:
    """Atomically persist a failed turn and its visible user/assistant message pair."""
    with get_cursor(commit=True) as cur:
        generation = _session_generation(cur, user_id)
        if generation is not None:
            if expected_generation != generation:
                return None
            return _finish_sync_turn(cur, user_id, turn_id, user_message, error_message, None, generation, error_code, error_status)
        cur.execute(
            '''UPDATE ai_chat_turn
               SET status = 'failed', reply = %s, error_message = %s,
                   error_code = %s, error_status = %s,
                   updated_at = now(), completed_at = now()
               WHERE user_id = %s AND turn_id = %s AND status = 'running'
               RETURNING turn_id, status, reply, cards, error_message, error_code,
                         error_status, created_at, updated_at''',
            (error_message or '', error_message or '', error_code, error_status, user_id, turn_id),
        )
        row = cur.fetchone()
        if row is not None:
            _insert_turn_messages(cur, user_id, user_message, error_message or '')
        else:
            cur.execute(
                '''SELECT turn_id, status, reply, cards, error_message, error_code,
                          error_status, created_at, updated_at
                   FROM ai_chat_turn WHERE user_id = %s AND turn_id = %s''',
                (user_id, turn_id),
            )
            row = cur.fetchone()
    return _turn_view(row)


def append_turn(user_id: int, user_message: str, assistant_message: str, cards=None, expected_generation=None) -> bool:
    """原子写入一轮对话（user + assistant），避免只落一半。"""
    cards_json = Json(cards) if cards is not None else None
    with get_cursor(commit=True) as cur:
        generation = _session_generation(cur, user_id)
        if generation is not None:
            if expected_generation != generation:
                return False
            _insert_turn_messages(cur, user_id, user_message, assistant_message, cards, generation)
            return True
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
        return True


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
    with get_cursor() as cur:
        return _list_messages(cur, user_id, limit)


def list_history(user_id: int, limit: int = 100) -> dict:
    with get_cursor() as cur:
        cur.execute("SELECT to_regclass('ai_chat_session') AS relation")
        relation = cur.fetchone()
        generation = 0
        if relation and relation['relation']:
            cur.execute("SELECT generation FROM ai_chat_session WHERE user_id = %s FOR SHARE", (user_id,))
            session = cur.fetchone()
            if session:
                generation = session['generation']
        return {'messages': _list_messages(cur, user_id, limit, generation), 'generation': generation}


def _list_messages(cur, user_id, limit, generation=None):
    limit = max(1, min(int(limit or 100), 200))
    generation_filter = '' if generation is None else " AND COALESCE((to_jsonb(ai_chat_message)->>'generation')::bigint, 0) = %s"
    parameters = (user_id, limit) if generation is None else (user_id, generation, limit)
    cur.execute(
            '''SELECT id, role, content, cards, created_at,
                      to_jsonb(ai_chat_message)->>'turn_id' AS turn_id,
                      COALESCE((to_jsonb(ai_chat_message)->>'generation')::bigint, 0) AS generation
               FROM ai_chat_message
               WHERE user_id = %s''' + generation_filter + '''
               ORDER BY id DESC
               LIMIT %s''',
            parameters,
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
            'turnId': row.get('turn_id'),
            'generation': row.get('generation', 0),
        }
        for row in rows
    ]


def clear_messages(user_id: int) -> int:
    """清空当前用户的聊天记录和轮次状态，返回删除的消息条数。"""
    with get_cursor(commit=True) as cur:
        cur.execute('DELETE FROM ai_chat_turn WHERE user_id = %s', (user_id,))
        cur.execute('DELETE FROM ai_chat_message WHERE user_id = %s', (user_id,))
        return cur.rowcount
