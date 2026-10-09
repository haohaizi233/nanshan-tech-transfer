"""Organization membership authorization and transactional state machines."""

import psycopg2

from core.contact_validation import validate_email, validate_phone
from core.errors import bad_request, conflict, forbidden, not_found
from db import get_cursor, transaction
from modules.audit.service import record as audit_record


def _map_read_row(row: dict) -> dict:
    """Expose database fields in the API's existing camelCase convention."""
    return {
        key.split('_')[0] + ''.join(part.title() for part in key.split('_')[1:]): value
        for key, value in row.items()
    }


def resolve_content_organization(cur, user_id: int, org_id) -> int | None:
    """Validate the optional publication organization against current membership."""
    if org_id is None:
        return None
    normalized_org_id = int(org_id)
    assert_active_membership(cur, user_id, normalized_org_id)
    return normalized_org_id


_ORDER_BY_ID = "a.id"
_ORDER_BY_CREATED_DESC = "a.created_at DESC, a.id DESC"


def _read_page(cur, select_sql: str, from_sql: str, params: list, page: int, page_size: int,
               order_by=_ORDER_BY_ID) -> dict:
    if order_by not in {_ORDER_BY_ID, _ORDER_BY_CREATED_DESC}:
        raise ValueError("unsupported order")
    cur.execute(f"SELECT COUNT(*) AS total {from_sql}", params)
    total = cur.fetchone()["total"]
    cur.execute(
        f"SELECT {select_sql} {from_sql} ORDER BY {order_by} LIMIT %s OFFSET %s",
        [*params, page_size, (page - 1) * page_size],
    )
    return {"list": [_map_read_row(row) for row in cur.fetchall()],
            "total": total, "page": page, "pageSize": page_size}


def list_my_memberships(user: dict, page: int, page_size: int) -> dict:
    with get_cursor() as cur:
        return _read_page(
            cur, "a.*, o.name AS org_name, o.kind AS org_type",
            "FROM organization_membership a JOIN institution o ON o.id = a.org_id WHERE a.user_id = %s",
            [user["userId"]], page, page_size,
        )


def list_my_membership_applications(user: dict, status, page: int, page_size: int) -> dict:
    """GET /me/organization-membership-applications —— 本人提交的加入机构申请。"""
    with get_cursor() as cur:
        sql = (
            "FROM organization_membership_application a "
            "JOIN institution o ON o.id = a.org_id WHERE a.user_id = %s"
        )
        params = [user["userId"]]
        if status is not None:
            sql += " AND a.status = %s"
            params.append(status)
        return _read_page(
            cur, "a.*, o.name AS org_name, o.kind AS org_type", sql, params, page, page_size,
            order_by=_ORDER_BY_CREATED_DESC,
        )


def get_my_organization_certification(user: dict) -> dict:
    """Return the caller's current certification and pending-application state."""
    user_id = int(user["userId"])
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT m.id, m.org_id, o.name AS org_name, m.role, m.status, m.version
            FROM organization_membership m
            JOIN institution o ON o.id = m.org_id
            WHERE m.user_id = %s AND m.status = 'active'
            ORDER BY CASE WHEN m.role = 'admin' THEN 0 ELSE 1 END, m.id
            """,
            (user_id,),
        )
        memberships = [
            {"id": row["id"], "orgId": row["org_id"], "orgName": row["org_name"],
             "role": row["role"], "status": row["status"], "version": row["version"]}
            for row in (cur.fetchall() or [])
        ]

        cur.execute(
            """
            SELECT a.id, a.org_id, o.name AS org_name, a.status, a.version, a.review_reason
            FROM organization_membership_application a
            JOIN institution o ON o.id = a.org_id
            WHERE a.user_id = %s AND a.status = 'pending'
            ORDER BY a.id DESC LIMIT 1
            """,
            (user_id,),
        )
        membership_application_row = cur.fetchone()
        membership_application = None if not membership_application_row else {
            "id": membership_application_row["id"],
            "orgId": membership_application_row["org_id"],
            "orgName": membership_application_row["org_name"],
            "status": membership_application_row["status"],
            "version": membership_application_row["version"],
            "reviewReason": membership_application_row.get("review_reason"),
        }

        cur.execute(
            """
            SELECT a.id, a.requested_name, a.status, a.version, a.review_reason
            FROM organization_application a
            WHERE a.applicant_user_id = %s AND a.status = 'pending'
            ORDER BY a.id DESC LIMIT 1
            """,
            (user_id,),
        )
        organization_application_row = cur.fetchone()
        organization_application = None if not organization_application_row else {
            "id": organization_application_row["id"],
            "requestedName": organization_application_row["requested_name"],
            "status": organization_application_row["status"],
            "version": organization_application_row["version"],
            "reviewReason": organization_application_row.get("review_reason"),
        }

    if any(item["role"] == "admin" for item in memberships):
        status = "certified_admin"
    elif memberships:
        status = "certified_member"
    elif membership_application:
        status = "membership_pending"
    elif organization_application:
        status = "organization_pending"
    else:
        status = "unverified"
    return {
        "status": status,
        "memberships": memberships,
        "membershipApplication": membership_application,
        "organizationApplication": organization_application,
    }


def list_org_members(admin: dict, org_id: int, status, page: int, page_size: int) -> dict:
    return _list_org_records(admin, org_id, "organization_membership", status, page, page_size)


def list_membership_applications(admin: dict, org_id: int, status, page: int, page_size: int) -> dict:
    return _list_org_records(admin, org_id, "organization_membership_application", status, page, page_size)


def list_organization_membership_applications(admin: dict, status, page: int, page_size: int) -> dict:
    """System-admin queue for member-certification applications across organizations."""
    with get_cursor() as cur:
        _assert_system_admin(cur, admin)
        sql = (
            "FROM organization_membership_application a "
            "JOIN app_user u ON u.id = a.user_id "
            "JOIN institution o ON o.id = a.org_id"
        )
        params = []
        if status is not None:
            sql += " WHERE a.status = %s"
            params.append(status)
        return _read_page(
            cur, "a.*, u.user_no, o.name AS org_name", sql, params, page, page_size,
            order_by=_ORDER_BY_CREATED_DESC,
        )


def _list_org_records(admin, org_id, table, status, page, page_size):
    if table not in {"organization_membership", "organization_membership_application"}:
        raise ValueError("unsupported membership table")
    with get_cursor() as cur:
        assert_org_admin_for(cur, admin, org_id)
        sql = f"FROM {table} a JOIN app_user u ON u.id = a.user_id JOIN institution o ON o.id = a.org_id WHERE a.org_id = %s"
        params = [org_id]
        if status is not None:
            sql += " AND a.status = %s"
            params.append(status)
        return _read_page(cur, "a.*, u.user_no, o.name AS org_name", sql, params, page, page_size)


def list_organization_applications(admin: dict, status, page: int, page_size: int) -> dict:
    return _list_system_applications(admin, "organization_application", status, page, page_size)


def list_organization_admin_applications(admin: dict, status, page: int, page_size: int) -> dict:
    return _list_system_applications(admin, "organization_admin_application", status, page, page_size)


def _list_system_applications(admin, table, status, page, page_size):
    if table not in {"organization_application", "organization_admin_application"}:
        raise ValueError("unsupported application table")
    user_column = "applicant_user_id" if table == "organization_application" else "user_id"
    with get_cursor() as cur:
        _assert_system_admin(cur, admin)
        sql = f"FROM {table} a JOIN app_user u ON u.id = a.{user_column}"
        columns = "a.*, u.user_no"
        if table == "organization_admin_application":
            sql += " JOIN institution o ON o.id = a.org_id"
            columns += ", o.name AS org_name"
        params = []
        if status is not None:
            sql += " WHERE a.status = %s"
            params.append(status)
        return _read_page(
            cur, columns, sql, params, page, page_size, order_by=_ORDER_BY_CREATED_DESC,
        )


def list_all_certification_applications(admin: dict, status, page: int, page_size: int) -> dict:
    """System-admin queue mixing organization, org-admin and member applications."""
    status_sql = " WHERE a.status = %s" if status is not None else ""
    params = [status, status, status] if status is not None else []
    from_sql = f"""
        FROM (
            SELECT a.id, a.status, a.version, a.created_at, a.updated_at,
                   a.reviewed_by_user_id, a.reviewed_at, a.review_reason, a.proof_material,
                   u.user_no, 'organization'::text AS application_kind,
                   a.requested_name AS org_name, a.requested_name, a.requested_type,
                   a.credit_code, a.website, a.region, a.address,
                   a.contact_name, a.contact_phone, a.contact_email,
                   NULL::bigint AS org_id, a.contact_name AS real_name,
                   NULL::varchar AS department, NULL::varchar AS title,
                   NULL::varchar AS work_email, NULL::text AS apply_note,
                   NULL::text AS reason, a.applicant_user_id AS user_id
            FROM organization_application a
            JOIN app_user u ON u.id = a.applicant_user_id
            {status_sql}
            UNION ALL
            SELECT a.id, a.status, a.version, a.created_at, a.updated_at,
                   a.reviewed_by_user_id, a.reviewed_at, a.review_reason, a.proof_material,
                   u.user_no, 'org-admin'::text AS application_kind,
                   o.name AS org_name, NULL, NULL, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL, a.org_id, a.real_name, a.department, a.title,
                   a.work_email, NULL, a.reason, a.user_id
            FROM organization_admin_application a
            JOIN app_user u ON u.id = a.user_id
            JOIN institution o ON o.id = a.org_id
            {status_sql}
            UNION ALL
            SELECT a.id, a.status, a.version, a.created_at, a.updated_at,
                   a.reviewed_by_user_id, a.reviewed_at, a.review_reason, a.proof_material,
                   u.user_no, 'member'::text AS application_kind,
                   o.name AS org_name, NULL, NULL, NULL, NULL, NULL, NULL,
                   NULL, NULL, NULL, a.org_id, a.real_name, a.department, a.title,
                   a.work_email, a.apply_note, NULL, a.user_id
            FROM organization_membership_application a
            JOIN app_user u ON u.id = a.user_id
            JOIN institution o ON o.id = a.org_id
            {status_sql}
        ) a
    """
    with get_cursor() as cur:
        _assert_system_admin(cur, admin)
        return _read_page(
            cur, "a.*", from_sql, params, page, page_size, order_by=_ORDER_BY_CREATED_DESC,
        )


def cancel_membership_application(user: dict, application_id: int, version: int, request_id=None) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM organization_membership_application WHERE id = %s AND user_id = %s FOR UPDATE",
                (application_id, user["userId"]),
            )
            if not cur.fetchone():
                raise not_found("成员申请不存在")
            cur.execute(
                """UPDATE organization_membership_application
                   SET status = 'cancelled', version = version + 1
                   WHERE id = %s AND user_id = %s AND version = %s AND status = 'pending'
                   RETURNING id, user_id, org_id, status, version""",
                (application_id, user["userId"], version),
            )
            cancelled = cur.fetchone()
            if not cancelled:
                raise conflict("申请状态或版本已变更")
            audit_record(
                "organization_membership_application.cancel", "membership_application", application_id,
                user["userId"], user.get("userNo", ""),
                {"orgId": cancelled["org_id"], "userId": cancelled["user_id"], "from": "pending", "to": "cancelled"},
                request_id=request_id, cur=cur,
            )
            return _map_application(cancelled)


def active_membership_org_ids(user_id: int) -> set[int]:
    """Return canonical organization ids from current active memberships."""
    with get_cursor() as cur:
        cur.execute(
            """
            SELECT org_id
            FROM organization_membership
            WHERE user_id = %s AND status = 'active'
            """,
            (user_id,),
        )
        return {int(row["org_id"]) for row in (cur.fetchall() or [])}


def assert_active_membership(cur, user_id: int, org_id: int) -> None:
    """Require an active membership for this user and exact organization."""
    cur.execute(
        """
        SELECT 1
        FROM organization_membership
        WHERE user_id = %s AND org_id = %s AND status = 'active'
        """,
        (user_id, org_id),
    )
    if not cur.fetchone():
        raise forbidden("无权关联该认证机构")


def _is_system_admin(cur, user_id: int) -> bool:
    cur.execute(
        "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
        (user_id,),
    )
    return bool(cur.fetchone())


def _assert_system_admin(cur, admin: dict) -> None:
    if not _is_system_admin(cur, int(admin["userId"])):
        raise forbidden("仅系统管理员可执行该操作")


def assert_org_admin_for(cur, admin: dict, org_id: int) -> None:
    """Require current org-admin authority for the exact org, or System Admin."""
    user_id = int(admin["userId"])
    cur.execute(
        """
        SELECT 1
        FROM organization_membership
        WHERE user_id = %s AND org_id = %s
          AND role = 'admin' AND status = 'active'
        """,
        (user_id, org_id),
    )
    if not cur.fetchone() and not _is_system_admin(cur, user_id):
        raise forbidden("无权管理该机构")


def _map_application(row: dict) -> dict:
    result = {
        "id": row["id"],
        "status": row["status"],
        "version": row["version"],
    }
    if row.get("user_id") is not None:
        result["userId"] = row["user_id"]
    if row.get("applicant_user_id") is not None:
        result["applicantUserId"] = row["applicant_user_id"]
    if row.get("org_id") is not None:
        result["orgId"] = row["org_id"]
    return result


def _map_membership(row: dict) -> dict:
    return {
        "id": row["id"],
        "userId": row["user_id"],
        "orgId": row["org_id"],
        "role": row["role"],
        "status": row["status"],
        "version": row["version"],
    }


def _duplicate_conflict(exc: psycopg2.IntegrityError, message: str):
    if exc.pgcode == "23505":
        raise conflict(message) from exc
    raise exc


def apply_membership(user: dict, body: dict) -> dict:
    """Apply to join an existing active canonical organization."""
    user_id = int(user["userId"])
    org_id = int(body["orgId"])
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM institution WHERE id = %s AND status = 'active'",
                    (org_id,),
                )
                if not cur.fetchone():
                    raise not_found("机构不存在或未启用")
                cur.execute(
                    """
                    SELECT 1 FROM organization_membership
                    WHERE user_id = %s AND org_id = %s AND status = 'active'
                    """,
                    (user_id, org_id),
                )
                if cur.fetchone():
                    raise conflict("已是该机构的有效成员")
                cur.execute(
                    """
                    SELECT 1 FROM organization_membership_application
                    WHERE user_id = %s AND org_id = %s AND status = 'pending'
                    """,
                    (user_id, org_id),
                )
                if cur.fetchone():
                    raise conflict("已有待审核的成员申请")
                cur.execute(
                    """
                    INSERT INTO organization_membership_application
                        (user_id, org_id, real_name, department, title, work_email,
                         proof_material, apply_note)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, org_id, status, version
                    """,
                    (
                        user_id, org_id, body.get("realName"), body.get("department"),
                        body.get("title"), body.get("workEmail"),
                        body.get("proofMaterial"), body.get("applyNote"),
                    ),
                )
                application = cur.fetchone()
                audit_record(
                    "membership.apply", "organization_membership_application", application["id"],
                    user_id, user.get("userNo", ""),
                    {"orgId": org_id, "userId": user_id}, cur=cur,
                )
                return _map_application(application)
    except psycopg2.IntegrityError as exc:
        _duplicate_conflict(exc, "已有待审核的成员申请")


def _activate_membership(cur, user_id: int, org_id: int, role: str, actor_id: int,
                         department=None, title=None) -> dict:
    cur.execute(
        """
        SELECT id, user_id, org_id, role, status, version
        FROM organization_membership
        WHERE user_id = %s AND org_id = %s
        ORDER BY CASE WHEN status = 'active' THEN 0 ELSE 1 END, id DESC
        FOR UPDATE
        """,
        (user_id, org_id),
    )
    existing = cur.fetchone()
    if existing and existing["status"] == "active":
        # Membership-application approval must never rewrite an existing active
        # identity (especially admin -> member). Only the System Admin flows
        # request role='admin', where promoting an active member is intentional.
        if role == "member" or existing["role"] == role:
            raise conflict("该用户已有有效机构身份")
        cur.execute(
            """
            UPDATE organization_membership
            SET role = %s, department = COALESCE(%s, department),
                title = COALESCE(%s, title), verified_by_user_id = %s,
                verified_at = CURRENT_TIMESTAMP, version = version + 1
            WHERE id = %s AND version = %s AND status = 'active'
            RETURNING id, user_id, org_id, role, status, version
            """,
            (role, department, title, actor_id, existing["id"], existing["version"]),
        )
        row = cur.fetchone()
        if not row:
            raise conflict("成员身份已变更，请刷新后重试")
        return row
    if existing:
        cur.execute(
            """
            UPDATE organization_membership
            SET role = %s, status = 'active', department = %s, title = %s,
                verified_by_user_id = %s, verified_at = CURRENT_TIMESTAMP,
                revoked_by_user_id = NULL, revoked_at = NULL, revoke_reason = NULL,
                version = version + 1
            WHERE id = %s AND version = %s AND status = 'revoked'
            RETURNING id, user_id, org_id, role, status, version
            """,
            (role, department, title, actor_id, existing["id"], existing["version"]),
        )
    else:
        cur.execute(
            """
            INSERT INTO organization_membership
                (user_id, org_id, role, status, department, title,
                 verified_by_user_id, verified_at)
            VALUES (%s, %s, %s, 'active', %s, %s, %s, CURRENT_TIMESTAMP)
            RETURNING id, user_id, org_id, role, status, version
            """,
            (user_id, org_id, role, department, title, actor_id),
        )
    row = cur.fetchone()
    if not row:
        raise conflict("成员身份已变更，请刷新后重试")
    return row


def approve_membership_application(admin: dict, application_id: int, version: int,
                                   request_id=None) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, user_id, org_id, department, title
                FROM organization_membership_application WHERE id = %s
                FOR UPDATE
                """,
                (application_id,),
            )
            application = cur.fetchone()
            if not application:
                raise not_found("成员申请不存在")
            assert_org_admin_for(cur, admin, application["org_id"])
            cur.execute(
                """
                UPDATE organization_membership_application
                SET status = 'approved', reviewed_by_user_id = %s,
                    reviewed_at = CURRENT_TIMESTAMP, review_reason = NULL,
                    version = version + 1
                WHERE id = %s AND version = %s AND status = 'pending'
                RETURNING id, user_id, org_id, status, version
                """,
                (admin["userId"], application_id, version),
            )
            reviewed = cur.fetchone()
            if not reviewed:
                raise conflict("申请状态或版本已变更")
            membership = _activate_membership(
                cur, application["user_id"], application["org_id"], "member",
                int(admin["userId"]), application.get("department"), application.get("title"),
            )
            audit_record(
                "organization_membership_application.approve", "membership_application",
                application_id, admin["userId"], admin.get("userNo", ""),
                {"orgId": application["org_id"], "userId": application["user_id"],
                 "membershipId": membership["id"], "from": "pending", "to": "approved"},
                request_id=request_id, cur=cur,
            )
            result = _map_application(reviewed)
            result["membership"] = _map_membership(membership)
            return result


def reject_membership_application(admin: dict, application_id: int, version: int,
                                  reason: str, request_id=None) -> dict:
    reason = (reason or "").strip()
    if not reason:
        raise bad_request("审核驳回必须填写原因")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, org_id FROM organization_membership_application WHERE id = %s FOR UPDATE",
                (application_id,),
            )
            application = cur.fetchone()
            if not application:
                raise not_found("成员申请不存在")
            assert_org_admin_for(cur, admin, application["org_id"])
            cur.execute(
                """
                UPDATE organization_membership_application
                SET status = 'rejected', reviewed_by_user_id = %s,
                    reviewed_at = CURRENT_TIMESTAMP, review_reason = %s,
                    version = version + 1
                WHERE id = %s AND version = %s AND status = 'pending'
                RETURNING id, user_id, org_id, status, version
                """,
                (admin["userId"], reason, application_id, version),
            )
            reviewed = cur.fetchone()
            if not reviewed:
                raise conflict("申请状态或版本已变更")
            audit_record(
                "organization_membership_application.reject", "membership_application",
                application_id, admin["userId"], admin.get("userNo", ""),
                {"orgId": application["org_id"], "userId": application["user_id"],
                 "from": "pending", "to": "rejected", "reason": reason},
                request_id=request_id, cur=cur,
            )
            return _map_application(reviewed)

def revoke_membership(admin: dict, membership_id: int, version: int, reason: str,
                      request_id=None) -> dict:
    """Org admins can revoke ordinary members in their own organization only."""
    reason = (reason or "").strip()
    if not reason:
        raise bad_request("撤销成员必须填写原因")
    with transaction() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, user_id, org_id, role FROM organization_membership WHERE id = %s FOR UPDATE",
                (membership_id,),
            )
            membership = cur.fetchone()
            if not membership:
                raise not_found("成员身份不存在")
            assert_org_admin_for(cur, admin, membership["org_id"])
            cur.execute(
                """
                UPDATE organization_membership
                SET status = 'revoked', revoked_by_user_id = %s,
                    revoked_at = CURRENT_TIMESTAMP, revoke_reason = %s,
                    version = version + 1
                WHERE id = %s AND version = %s
                  AND status = 'active' AND role = 'member'
                RETURNING id, user_id, org_id, role, status, version
                """,
                (admin["userId"], reason, membership_id, version),
            )
            revoked = cur.fetchone()
            if not revoked:
                raise conflict("仅可撤销当前有效的普通成员，或版本已变更")
            audit_record(
                "organization_membership.revoke", "organization_membership", membership_id,
                admin["userId"], admin.get("userNo", ""),
                {"orgId": membership["org_id"], "userId": membership["user_id"],
                 "role": "member", "from": "active", "to": "revoked", "reason": reason},
                request_id=request_id, cur=cur,
            )
            return _map_membership(revoked)


def apply_organization_admin(user: dict, body: dict) -> dict:
    user_id = int(user["userId"])
    org_id = int(body["orgId"])
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT 1 FROM institution WHERE id = %s AND status = 'active'",
                    (org_id,),
                )
                if not cur.fetchone():
                    raise not_found("机构不存在或未启用")
                cur.execute(
                    """
                    SELECT 1 FROM organization_membership
                    WHERE user_id = %s AND org_id = %s
                      AND role = 'admin' AND status = 'active'
                    """,
                    (user_id, org_id),
                )
                if cur.fetchone():
                    raise conflict("已是该机构管理员")
                cur.execute(
                    """
                    SELECT 1 FROM organization_admin_application
                    WHERE user_id = %s AND org_id = %s AND status = 'pending'
                    """,
                    (user_id, org_id),
                )
                if cur.fetchone():
                    raise conflict("已有待审核的机构管理员申请")
                cur.execute(
                    """
                    INSERT INTO organization_admin_application
                        (user_id, org_id, real_name, department, title, work_email,
                         proof_material, reason)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, user_id, org_id, status, version
                    """,
                    (
                        user_id, org_id, body.get("realName"), body.get("department"),
                        body.get("title"), body.get("workEmail"),
                        body.get("proofMaterial"), body.get("reason"),
                    ),
                )
                application = cur.fetchone()
                audit_record(
                    "membership.apply_org_admin", "organization_admin_application", application["id"],
                    user_id, user.get("userNo", ""),
                    {"orgId": org_id, "userId": user_id}, cur=cur,
                )
                return _map_application(application)
    except psycopg2.IntegrityError as exc:
        _duplicate_conflict(exc, "已有待审核的机构管理员申请")


def approve_organization_admin_application(admin: dict, application_id: int, version: int,
                                           request_id=None) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            _assert_system_admin(cur, admin)
            cur.execute(
                """
                SELECT id, user_id, org_id, department, title
                FROM organization_admin_application WHERE id = %s FOR UPDATE
                """,
                (application_id,),
            )
            application = cur.fetchone()
            if not application:
                raise not_found("机构管理员申请不存在")
            cur.execute(
                """
                UPDATE organization_admin_application
                SET status = 'approved', reviewed_by_user_id = %s,
                    reviewed_at = CURRENT_TIMESTAMP, review_reason = NULL,
                    version = version + 1
                WHERE id = %s AND version = %s AND status = 'pending'
                RETURNING id, user_id, org_id, status, version
                """,
                (admin["userId"], application_id, version),
            )
            reviewed = cur.fetchone()
            if not reviewed:
                raise conflict("申请状态或版本已变更")
            membership = _activate_membership(
                cur, application["user_id"], application["org_id"], "admin",
                int(admin["userId"]), application.get("department"), application.get("title"),
            )
            audit_record(
                "organization_admin_application.approve", "organization_admin_application",
                application_id, admin["userId"], admin.get("userNo", ""),
                {"orgId": application["org_id"], "userId": application["user_id"],
                 "membershipId": membership["id"], "from": "pending", "to": "approved"},
                request_id=request_id, cur=cur,
            )
            result = _map_application(reviewed)
            result["membership"] = _map_membership(membership)
            return result


def reject_organization_admin_application(admin: dict, application_id: int, version: int,
                                          reason: str, request_id=None) -> dict:
    return _reject_system_application(
        admin, "organization_admin_application", application_id, version, reason,
        "机构管理员申请不存在", "organization_admin_application.reject", request_id,
    )


def grant_organization_admin(admin: dict, membership_id: int, version: int,
                             request_id=None) -> dict:
    with transaction() as conn:
        with conn.cursor() as cur:
            _assert_system_admin(cur, admin)
            cur.execute(
                """
                UPDATE organization_membership
                SET role = 'admin', verified_by_user_id = %s,
                    verified_at = CURRENT_TIMESTAMP, version = version + 1
                WHERE id = %s AND version = %s
                  AND status = 'active' AND role = 'member'
                RETURNING id, user_id, org_id, role, status, version
                """,
                (admin["userId"], membership_id, version),
            )
            granted = cur.fetchone()
            if not granted:
                raise conflict("仅可授予当前有效普通成员管理员权限，或版本已变更")
            audit_record(
                "organization_admin.grant", "organization_membership", membership_id,
                admin["userId"], admin.get("userNo", ""),
                {"orgId": granted["org_id"], "userId": granted["user_id"],
                 "from": "member", "to": "admin"}, request_id=request_id, cur=cur,
            )
            return _map_membership(granted)


def revoke_organization_admin(admin: dict, membership_id: int, version: int, reason: str,
                              request_id=None) -> dict:
    reason = (reason or "").strip()
    if not reason:
        raise bad_request("撤销机构管理员必须填写原因")
    with transaction() as conn:
        with conn.cursor() as cur:
            _assert_system_admin(cur, admin)
            cur.execute(
                """
                UPDATE organization_membership
                SET status = 'revoked', revoked_by_user_id = %s,
                    revoked_at = CURRENT_TIMESTAMP, revoke_reason = %s,
                    version = version + 1
                WHERE id = %s AND version = %s
                  AND status = 'active' AND role = 'admin'
                RETURNING id, user_id, org_id, role, status, version
                """,
                (admin["userId"], reason, membership_id, version),
            )
            revoked = cur.fetchone()
            if not revoked:
                raise conflict("仅可撤销当前有效管理员身份，或版本已变更")
            audit_record(
                "organization_admin.revoke", "organization_membership", membership_id,
                admin["userId"], admin.get("userNo", ""),
                {"orgId": revoked["org_id"], "userId": revoked["user_id"],
                 "role": "admin", "from": "active", "to": "revoked", "reason": reason},
                request_id=request_id, cur=cur,
            )
            return _map_membership(revoked)


def apply_organization(user: dict, body: dict) -> dict:
    user_id = int(user["userId"])
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1 FROM organization_application
                    WHERE applicant_user_id = %s AND status = 'pending'
                    """,
                    (user_id,),
                )
                if cur.fetchone():
                    raise conflict("已有待审核的机构入驻申请")
                requested_name = body["requestedName"].strip()
                cur.execute("SELECT 1 FROM institution WHERE name = %s", (requested_name,))
                if cur.fetchone():
                    raise conflict("同名机构已存在，请改为申请加入该机构")
                contact_phone = validate_phone(body.get("contactPhone"), required=True, field_name="联系电话")
                contact_email = validate_email(body.get("contactEmail"), required=False, field_name="联系邮箱")
                cur.execute(
                    """
                    INSERT INTO organization_application
                        (applicant_user_id, requested_name, requested_type, credit_code,
                         website, region, address, contact_name, contact_phone,
                         contact_email, proof_material)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    RETURNING id, applicant_user_id, status, version
                    """,
                    (
                        user_id, requested_name, body.get("requestedType"),
                        body.get("creditCode"), body.get("website"), body.get("region"),
                        body.get("address"), body.get("contactName"), contact_phone,
                        contact_email, body.get("proofMaterial"),
                    ),
                )
                application = cur.fetchone()
                audit_record(
                    "membership.apply_org", "organization_application", application["id"],
                    user_id, user.get("userNo", ""),
                    {"orgId": None, "userId": user_id, "requestedName": requested_name}, cur=cur,
                )
                return _map_application(application)
    except psycopg2.IntegrityError as exc:
        _duplicate_conflict(exc, "已有待审核的机构入驻申请")


def approve_organization_application(admin: dict, application_id: int, version: int,
                                     request_id=None) -> dict:
    try:
        with transaction() as conn:
            with conn.cursor() as cur:
                _assert_system_admin(cur, admin)
                cur.execute(
                    """
                    SELECT id, applicant_user_id, requested_name, requested_type,
                           region, credit_code
                    FROM organization_application WHERE id = %s FOR UPDATE
                    """,
                    (application_id,),
                )
                application = cur.fetchone()
                if not application:
                    raise not_found("机构入驻申请不存在")
                cur.execute(
                    """
                    UPDATE organization_application
                    SET status = 'approved', reviewed_by_user_id = %s,
                        reviewed_at = CURRENT_TIMESTAMP, review_reason = NULL,
                        version = version + 1
                    WHERE id = %s AND version = %s AND status = 'pending'
                    RETURNING id, applicant_user_id, status, version
                    """,
                    (admin["userId"], application_id, version),
                )
                reviewed = cur.fetchone()
                if not reviewed:
                    raise conflict("申请状态或版本已变更")
                cur.execute(
                    "SELECT 1 FROM institution WHERE name = %s",
                    (application["requested_name"],),
                )
                if cur.fetchone():
                    raise conflict("同名机构已存在")
                kind = (application.get("requested_type") or "").strip().lower()
                if kind not in ("university", "institute", "enterprise", "service", "invest", "other"):
                    kind = "enterprise"
                cur.execute(
                    """
                    INSERT INTO institution
                        (kind, name, region, credit_code, status, user_type, source_site,
                         registration_status, registered_by_user_id, registration_applied_at)
                    VALUES (%s, %s, %s, %s, 'active', %s, 'self_registration',
                            'approved', %s, CURRENT_TIMESTAMP)
                    RETURNING id
                    """,
                    (kind, application["requested_name"], application.get("region"),
                     application.get("credit_code"), kind,
                     application["applicant_user_id"]),
                )
                org_id = cur.fetchone()["id"]
                membership = _activate_membership(
                    cur, application["applicant_user_id"], org_id, "admin", int(admin["userId"]),
                )
                audit_record(
                    "organization_application.approve", "organization_application", application_id,
                    admin["userId"], admin.get("userNo", ""),
                    {"orgId": org_id, "userId": application["applicant_user_id"],
                     "membershipId": membership["id"], "from": "pending", "to": "approved"},
                    request_id=request_id, cur=cur,
                )
                result = _map_application(reviewed)
                result["orgId"] = org_id
                result["membership"] = _map_membership(membership)
                return result
    except psycopg2.IntegrityError as exc:
        _duplicate_conflict(exc, "同名有效机构已存在")


def reject_organization_application(admin: dict, application_id: int, version: int,
                                    reason: str, request_id=None) -> dict:
    return _reject_system_application(
        admin, "organization_application", application_id, version, reason,
        "机构入驻申请不存在", "organization_application.reject", request_id,
    )


def _reject_system_application(admin: dict, table: str, application_id: int, version: int,
                               reason: str, missing_message: str, action: str,
                               request_id=None) -> dict:
    reason = (reason or "").strip()
    if not reason:
        raise bad_request("审核驳回必须填写原因")
    if table not in {"organization_admin_application", "organization_application"}:
        raise ValueError("unsupported application table")
    user_column = "user_id" if table == "organization_admin_application" else "applicant_user_id"
    org_column = ", org_id" if table == "organization_admin_application" else ""
    with transaction() as conn:
        with conn.cursor() as cur:
            _assert_system_admin(cur, admin)
            cur.execute(
                f"SELECT id, {user_column}{org_column} FROM {table} WHERE id = %s FOR UPDATE",
                (application_id,),
            )
            application = cur.fetchone()
            if not application:
                raise not_found(missing_message)
            cur.execute(
                f"""
                UPDATE {table}
                SET status = 'rejected', reviewed_by_user_id = %s,
                    reviewed_at = CURRENT_TIMESTAMP, review_reason = %s,
                    version = version + 1
                WHERE id = %s AND version = %s AND status = 'pending'
                RETURNING id, {user_column}{org_column}, status, version
                """,
                (admin["userId"], reason, application_id, version),
            )
            reviewed = cur.fetchone()
            if not reviewed:
                raise conflict("申请状态或版本已变更")
            details = {
                "userId": application[user_column],
                "from": "pending",
                "to": "rejected",
                "reason": reason,
            }
            if table == "organization_admin_application":
                details["orgId"] = application["org_id"]
            audit_record(
                action, table, application_id, admin["userId"], admin.get("userNo", ""),
                details, request_id=request_id, cur=cur,
            )
            return _map_application(reviewed)
