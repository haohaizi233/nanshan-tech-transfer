from db import get_cursor

VALID_CATEGORIES = ('review', 'cooperation', 'organization', 'membership')

def emit_notification(cur, *, recipient_user_id, category, event_type, source_type, source_id, title, body=None, target_path=None, dedupe_key=None):
    key = dedupe_key or f'{event_type}:{recipient_user_id}:{source_type}:{source_id}'
    cur.execute('''INSERT INTO notification_inbox (recipient_user_id, category, event_type, source_type, source_id, title, body, target_path, dedupe_key)
        VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (dedupe_key) DO NOTHING RETURNING id''',
        (recipient_user_id, category, event_type, source_type, source_id, title, body, target_path, key))
    return {'created': cur.fetchone() is not None}

def summary(user_id):
    with get_cursor() as cur:
        cur.execute('''SELECT category, COUNT(*) AS count FROM notification_inbox
            WHERE recipient_user_id=%s AND read_at IS NULL GROUP BY category''', (user_id,))
        counts = {row['category']: int(row['count']) for row in cur.fetchall()}
    categories = {key: counts.get(key, 0) for key in VALID_CATEGORIES}
    return {'total': sum(categories.values()), 'categories': categories}

def mark_read(user_id, category):
    if category not in VALID_CATEGORIES:
        raise ValueError('无效通知分类')
    with get_cursor(commit=True) as cur:
        cur.execute('''UPDATE notification_inbox SET read_at=NOW()
            WHERE recipient_user_id=%s AND category=%s AND read_at IS NULL''', (user_id, category))
        return {'updated': cur.rowcount}
