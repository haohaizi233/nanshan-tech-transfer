from core.errors import bad_request
from db import get_cursor
from modules.audit.service import record as audit_record

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
        raise bad_request('无效通知分类')
    with get_cursor(commit=True) as cur:
        cur.execute('''UPDATE notification_inbox SET read_at=NOW()
            WHERE recipient_user_id=%s AND category=%s AND read_at IS NULL''', (user_id, category))
        return {'updated': cur.rowcount}


def list_notifications(user_id, args):
    try:
        page = max(1, int(args.get('page') or 1))
        page_size = max(1, min(50, int(args.get('pageSize') or 20)))
    except (TypeError, ValueError):
        page, page_size = 1, 20
    unread_only = str(args.get('unreadOnly') or '').lower() in ('1', 'true')
    category = str(args.get('category') or '').strip()
    if category and category not in VALID_CATEGORIES:
        raise bad_request('无效通知分类')
    where = 'recipient_user_id=%s'
    params = [user_id]
    if category:
        where += ' AND category=%s'
        params.append(category)
    if unread_only:
        where += ' AND read_at IS NULL'
    with get_cursor() as cur:
        cur.execute(f'SELECT COUNT(*) AS count FROM notification_inbox WHERE {where}', params)
        total = int((cur.fetchone() or {}).get('count') or 0)
        cur.execute(f'''SELECT id, category, event_type, source_type, source_id, title, body,
            target_path, occurred_at, read_at FROM notification_inbox WHERE {where}
            ORDER BY occurred_at DESC, id DESC LIMIT %s OFFSET %s''',
            params + [page_size, (page - 1) * page_size])
        rows = cur.fetchall() or []
    return {
        'total': total, 'page': page, 'pageSize': page_size,
        'list': [{'id': row['id'], 'category': row['category'], 'eventType': row['event_type'],
                  'sourceType': row['source_type'], 'sourceId': row['source_id'], 'title': row['title'],
                  'body': row.get('body'), 'targetPath': row.get('target_path'),
                  'occurredAt': row['occurred_at'].strftime('%Y-%m-%d %H:%M:%S'),
                  'readAt': row['read_at'].strftime('%Y-%m-%d %H:%M:%S') if row.get('read_at') else None}
                 for row in rows],
    }


def mark_notification_read(user_id, notification_id):
    with get_cursor(commit=True) as cur:
        cur.execute('''UPDATE notification_inbox SET read_at=COALESCE(read_at, NOW())
            WHERE id=%s AND recipient_user_id=%s''', (notification_id, user_id))
        if cur.rowcount > 0:
            audit_record(
                "notification.read", "notification", resource_id=notification_id,
                actor_user_id=user_id, cur=cur,
            )
        return {'updated': cur.rowcount}


def mark_all_read(user_id):
    with get_cursor(commit=True) as cur:
        cur.execute('UPDATE notification_inbox SET read_at=NOW() WHERE recipient_user_id=%s AND read_at IS NULL', (user_id,))
        return {'updated': cur.rowcount}
