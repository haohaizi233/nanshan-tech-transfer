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
):
    """写一条审计日志；失败仅打印，不影响业务主流程"""
    try:
        with get_cursor(commit=True) as cur:
            cur.execute(
                """
                INSERT INTO audit_log
                    (actor_user_id, actor_user_no, action, resource_type,
                     resource_id, details, ip_address, request_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    actor_user_id,
                    actor_user_no,
                    action,
                    resource_type,
                    str(resource_id) if resource_id is not None else None,
                    json.dumps(details, ensure_ascii=False) if details is not None else None,
                    ip_address,
                    request_id,
                ),
            )
    except Exception as e:
        print(f"[audit] write failed (ignored): action={action} resource={resource_type}/{resource_id} err={e}")
