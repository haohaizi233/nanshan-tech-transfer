"""
审计服务 —— 最佳努力写入 audit_log，不阻塞主流程

Architecture source: 04-backend-domain-design.md §4.14, 05-data-model-design.md audit_log
"""
import json

from db import get_cursor

# audit_log 列宽（001 baseline / 028 migration）。超长写入会触发 22001，
# 同事务模式下会连带回滚业务操作，因此写库前统一按列宽截断兜底。
_MAX_ACTOR_USER_NO = 32
_MAX_ACTION = 64
_MAX_RESOURCE_TYPE = 64
_MAX_RESOURCE_ID = 64
_MAX_REQUEST_ID = 64


def _clip(value, limit: int):
    """按数据库列宽截断字符串；None 原样返回。"""
    if value is None:
        return None
    text = str(value)
    if len(text) <= limit:
        return text
    print(f"[audit] value truncated to {limit} chars: {text[:limit]}…")
    return text[:limit]


def record(
    action: str,
    resource_type: str,
    resource_id=None,
    actor_user_id=None,
    actor_user_no=None,
    details=None,
    ip_address=None,
    request_id=None,
    cur=None,
):
    """写一条审计日志；失败仅打印，不影响业务主流程

    cur=None（默认）：自开事务提交（存量行为不变）；
    cur=外部游标：在同事务内写入，由调用方统一 COMMIT/ROLLBACK
    —— Release Closure §16：管理端写操作要求状态变更与审计同事务。
    """
    sql = """
        INSERT INTO audit_log
            (actor_user_id, actor_user_no, action, resource_type,
             resource_id, details, ip_address, request_id)
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    values = (
        actor_user_id,
        _clip(actor_user_no, _MAX_ACTOR_USER_NO),
        _clip(action, _MAX_ACTION),
        _clip(resource_type, _MAX_RESOURCE_TYPE),
        _clip(resource_id, _MAX_RESOURCE_ID),
        json.dumps(details, ensure_ascii=False) if details is not None else None,
        ip_address,
        _clip(request_id, _MAX_REQUEST_ID),
    )
    try:
        if cur is not None:
            # 同事务模式：异常必须向上抛，由调用方 ROLLBACK（保持原子性）
            cur.execute(sql, values)
            return
        with get_cursor(commit=True) as own:
            own.execute(sql, values)
    except Exception as e:
        if cur is not None:
            raise
        print(f"[audit] write failed (ignored): action={action} resource={resource_type}/{resource_id} err={e}")
