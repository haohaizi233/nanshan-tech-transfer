"""机构注册申请（公开注册页 → 平台审核 → 机构管理员开通）。

与 membership 模块的关系：本模块是 Vue 注册页/后台契约的适配层，
申请数据落在 organization_application（迁移 011），审批复用
membership 的系统管理员状态机（approve/reject_organization_application）；
机构权限始终由 membership 实时判定，不写 user_role。

公开注册一次性完成两件事（单事务）：
1. 创建首位机构管理员账号（username/password → user_credential）
2. 提交机构入驻申请（pending）

审核通过后：机构建档（institution，source_site='self_registration'）
+ 申请人成为该机构 admin 成员，即可用该账号登录 Vue 后台
（_get_roles 实时附加 org_admin 角色）。
"""

import re

import psycopg2

from core.contact_validation import validate_email, validate_phone
from core.errors import bad_request, conflict, not_found
from db import get_cursor, transaction
from modules.audit.service import record as audit_record
from modules.identity.service import create_password_account
from modules.membership.service import (
    approve_organization_application,
    reject_organization_application,
)

PUBLIC_KINDS = ("university", "institute", "enterprise", "invest", "service", "other")
LIST_STATUSES = ("pending", "approved", "rejected", "cancelled")


def create_institution_registration(body: dict, request_id=None) -> dict:
    if not isinstance(body, dict):
        raise bad_request("请求体必须是 JSON 对象")

    kind = str(body.get("kind") or "").strip()
    if kind not in PUBLIC_KINDS:
        raise bad_request(f"kind 必须是 {'/'.join(PUBLIC_KINDS)} 之一")
    name = str(body.get("name") or "").strip()
    if not name:
        raise bad_request("机构名称必填")
    if len(name) > 128:
        raise bad_request("机构名称长度不能超过 128")
    contact_name = str(body.get("contactName") or "").strip()
    if not contact_name:
        raise bad_request("联系人姓名必填")
    if len(contact_name) > 64:
        raise bad_request("联系人姓名长度不能超过 64")
    contact_phone = validate_phone(body.get("contactPhone"), required=True, field_name="联系电话")
    username = str(body.get("username") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.-]{4,64}", username):
        raise bad_request("登录账号须为 4-64 位字母、数字或 . _ -")
    password = body.get("password") or ""
    if len(password) < 8 or len(password) > 128:
        raise bad_request("密码长度须为 8-128 位")

    region = str(body.get("region") or "").strip() or None
    if region and len(region) > 64:
        raise bad_request("region 长度不能超过 64")
    credit_code = str(body.get("creditCode") or "").strip() or None
    if credit_code and len(credit_code) > 64:
        raise bad_request("creditCode 长度不能超过 64")
    email = validate_email(body.get("email"), required=False)
    # 申请表无独立 intro 列：简介暂存 proof_material，审核通过后回填 institution.intro
    intro = str(body.get("intro") or "").strip() or None
    if intro and len(intro) > 5000:
        raise bad_request("intro 长度不能超过 5000")

    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1 FROM user_credential WHERE username=%s", (username,))
                if cur.fetchone():
                    raise conflict("该登录账号已存在")
                cur.execute("SELECT 1 FROM institution WHERE name=%s", (name,))
                if cur.fetchone():
                    raise conflict("同名机构已存在")

                user_id, user_no = create_password_account(
                    cur, username, password,
                    display_name=contact_name, phone=contact_phone, email=email,
                )
                cur.execute(
                    """
                    INSERT INTO organization_application
                        (applicant_user_id, requested_name, requested_type, credit_code,
                         region, contact_name, contact_phone, contact_email, proof_material)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, status, version
                    """,
                    (user_id, name, kind, credit_code, region,
                     contact_name, contact_phone, email, intro),
                )
                application = cur.fetchone()
                audit_record(
                    "user.registration.submit", "app_user",
                    resource_id=user_id, actor_user_id=user_id, actor_user_no=user_no,
                    details={"username": username, "via": "institution_registration"},
                    request_id=request_id, cur=cur,
                )
                audit_record(
                    "institution_registration.submit", "organization_application",
                    resource_id=application["id"], actor_user_id=user_id,
                    actor_user_no=user_no,
                    details={"name": name, "kind": kind},
                    request_id=request_id, cur=cur,
                )
                return {
                    "applicationId": application["id"],
                    "status": application["status"],
                    "version": application["version"],
                    "username": username,
                }
    except psycopg2.IntegrityError as exc:
        if exc.pgcode == "23505":
            raise conflict("该登录账号已存在") from exc
        raise


def list_institution_registrations(args) -> dict:
    """平台管理端的机构注册申请列表（admin/institution-registrations 契约）。"""
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(100, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10
    status = (args.get("registrationStatus") or "").strip()
    if status and status != "all" and status not in LIST_STATUSES:
        raise bad_request(f"registrationStatus 必须是 {'/'.join(LIST_STATUSES)} 或 all")

    where = ""
    params: list = []
    if status and status != "all":
        where = " WHERE a.status = %s"
        params.append(status)

    with get_cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS total FROM organization_application a{where}",
            params,
        )
        total = int(cur.fetchone()["total"])
        cur.execute(
            f"""
            SELECT a.id, a.requested_name, a.requested_type, a.credit_code, a.region,
                   a.contact_name, a.contact_phone, a.contact_email, a.proof_material,
                   a.status, a.review_reason, a.created_at,
                   u.user_no, p.display_name, p.phone, c.username
            FROM organization_application a
            JOIN app_user u ON u.id = a.applicant_user_id
            LEFT JOIN user_profile p ON p.user_id = a.applicant_user_id
            LEFT JOIN user_credential c ON c.user_id = a.applicant_user_id
            {where}
            ORDER BY a.id DESC
            LIMIT %s OFFSET %s
            """,
            [*params, page_size, (page - 1) * page_size],
        )
        rows = cur.fetchall() or []

    def _item(row: dict) -> dict:
        applied_at = row["created_at"]
        return {
            "id": row["id"],
            "name": row["requested_name"],
            "kind": row["requested_type"],
            "creditCode": row["credit_code"],
            "region": row["region"],
            "applicantName": row["contact_name"] or row["display_name"],
            "applicantPhone": row["contact_phone"] or row["phone"],
            "username": row["username"],
            "appliedAt": applied_at.strftime("%Y-%m-%d %H:%M:%S") if applied_at else None,
            "registrationStatus": row["status"],
            "rejectReason": row["review_reason"],
        }

    return {
        "list": [_item(r) for r in rows],
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": (total + page_size - 1) // page_size if total else 0,
    }


def _load_application_version(application_id: int, select_extra: str = "") -> dict:
    with get_cursor() as cur:
        cur.execute(
            f"SELECT version{select_extra} FROM organization_application WHERE id = %s",
            (application_id,),
        )
        row = cur.fetchone()
    if not row:
        raise not_found("机构注册申请不存在")
    return row


def approve_institution_registration(admin: dict, application_id: int, request_id=None) -> dict:
    row = _load_application_version(application_id, ", proof_material")
    result = approve_organization_application(
        admin, application_id, row["version"], request_id=request_id,
    )

    # 机构简介（暂存于 proof_material）回填建档结果（仅空值时写入，不覆盖人工维护）
    org_id = result.get("orgId")
    intro = (row.get("proof_material") or "").strip()
    if org_id and intro:
        with get_cursor(commit=True) as cur:
            cur.execute(
                "UPDATE institution SET intro=%s WHERE id=%s AND (intro IS NULL OR intro='')",
                (intro, org_id),
            )
    return result


def reject_institution_registration(admin: dict, application_id: int, reason,
                                    request_id=None) -> dict:
    row = _load_application_version(application_id)
    return reject_organization_application(
        admin, application_id, row["version"], reason, request_id=request_id,
    )
