"""
审计服务 —— 最佳努力写入 audit_log，不阻塞主流程

Architecture source: 04-backend-domain-design.md §4.14, 05-data-model-design.md audit_log
"""
import json

from db import get_cursor


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
        actor_user_no,
        action,
        resource_type,
        str(resource_id) if resource_id is not None else None,
        json.dumps(details, ensure_ascii=False) if details is not None else None,
        ip_address,
        request_id,
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
