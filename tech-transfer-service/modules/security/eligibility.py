"""统一账号准入资格判定策略（SMS / Email 共享基础）。

严格遵守：
1. 仅 active、未删除、有效密码凭证、已确权且无冲突绑定的账号允许自助恢复；
2. 管理员、平台管理员、机构管理员均不允许通过单因素自助渠道恢复密码；
3. `user_profile.phone` / `user_profile.email` 零恢复特权；
4. 内部诊断结果绝不直接暴露给未认证公开接口。
"""

from __future__ import annotations

from core.contact_validation import normalize_email
from core.errors import BizError
from db import get_cursor

SMS_ELIGIBLE_SQL = """
SELECT au.id AS user_id, ac.normalized_value
FROM app_user au
JOIN user_credential uc ON uc.user_id = au.id AND uc.status = 'active'
JOIN account_contact ac ON ac.user_id = au.id AND ac.contact_type = 'phone'
    AND ac.status = 'active' AND ac.verified_at IS NOT NULL
    AND ac.verification_method IN ('sms','wechat','manual')
WHERE au.deleted_at IS NULL AND au.status = 'active'
  AND uc.password_configured = true AND uc.password_hash IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id = au.id
                  AND ur.role_code IN ('admin','platform_admin','org_admin'))
  AND NOT EXISTS (SELECT 1 FROM organization_membership om WHERE om.user_id = au.id
                  AND om.role = 'admin' AND om.status = 'active')
  AND NOT EXISTS (SELECT 1 FROM account_contact other WHERE other.contact_type = 'phone'
                  AND other.status = 'active' AND other.verified_at IS NOT NULL
                  AND other.normalized_value = ac.normalized_value AND other.user_id <> au.id)
  AND (uc.username = %s OR ac.normalized_value = %s)
LIMIT 2
"""

EMAIL_ELIGIBLE_SQL = """
SELECT au.id AS user_id, ac.normalized_value
FROM app_user au
JOIN user_credential uc ON uc.user_id = au.id AND uc.status = 'active'
JOIN account_contact ac ON ac.user_id = au.id AND ac.contact_type = 'email'
    AND ac.status = 'active' AND ac.verified_at IS NOT NULL
    AND ac.verification_method IN ('email','manual')
WHERE au.deleted_at IS NULL AND au.status = 'active'
  AND uc.password_configured = true AND uc.password_hash IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM user_role ur WHERE ur.user_id = au.id
                  AND ur.role_code IN ('admin','platform_admin','org_admin'))
  AND NOT EXISTS (SELECT 1 FROM organization_membership om WHERE om.user_id = au.id
                  AND om.role = 'admin' AND om.status = 'active')
  AND NOT EXISTS (SELECT 1 FROM account_contact other WHERE other.contact_type = 'email'
                  AND other.status = 'active' AND other.verified_at IS NOT NULL
                  AND other.normalized_value = ac.normalized_value AND other.user_id <> au.id)
  AND (
      uc.username = %s
      OR ac.normalized_value = %s
      OR EXISTS (
          SELECT 1 FROM account_contact ac_phone
          WHERE ac_phone.user_id = au.id
            AND ac_phone.contact_type = 'phone'
            AND ac_phone.status = 'active'
            AND ac_phone.verified_at IS NOT NULL
            AND ac_phone.verification_method IN ('sms','wechat','manual')
            AND ac_phone.normalized_value = %s
      )
  )
LIMIT 2
"""


def _normalize_lookup_account(account: str, contact_type: str) -> str:
    raw = (account or "").strip()
    if "@" in raw:
        try:
            return normalize_email(raw)
        except BizError:
            return raw.lower()
    return raw


def eligibility_reason(account: str, *, contact_type: str = "phone", cursor_factory=None) -> str:
    """内部只读资格诊断。绝不可向公开路由直接返回诊断结论。"""
    lookup = _normalize_lookup_account(account, contact_type)
    allowed_methods = {"sms", "wechat", "manual"} if contact_type == "phone" else {"email", "manual"}
    use_cursor = cursor_factory or get_cursor

    with use_cursor() as cur:
        cur.execute(
            """SELECT au.id,au.status,au.deleted_at,uc.status AS credential_status,
            uc.password_configured,uc.password_hash IS NOT NULL AS has_password,
            EXISTS(SELECT 1 FROM user_role ur WHERE ur.user_id=au.id
                AND ur.role_code IN ('admin','platform_admin','org_admin')) OR
            EXISTS(SELECT 1 FROM organization_membership om WHERE om.user_id=au.id
                AND om.role='admin' AND om.status='active') AS privileged
            FROM app_user au LEFT JOIN user_credential uc ON uc.user_id=au.id
            WHERE uc.username=%s OR uc.phone=%s OR EXISTS(SELECT 1 FROM account_contact ac
                WHERE ac.user_id=au.id AND ac.normalized_value=%s) LIMIT 2""",
            (lookup, lookup, lookup),
        )
        rows = cur.fetchall()
        if not rows:
            return "account_not_found"
        if len(rows) > 1:
            return "contact_conflict"
        user = rows[0]
        if user["deleted_at"] is not None:
            return "account_deleted"
        if user["status"] != "active":
            return "account_disabled"
        if user["privileged"]:
            return "privileged_account_restricted"
        if user["credential_status"] != "active" or not user["password_configured"] or not user["has_password"]:
            return "credential_not_configured"
        cur.execute(
            """SELECT normalized_value,status,verified_at,verification_method
            FROM account_contact WHERE user_id=%s AND contact_type=%s""",
            (user["id"], contact_type),
        )
        trusted = [
            c
            for c in cur.fetchall()
            if c["status"] == "active" and c["verified_at"] is not None and c["verification_method"] in allowed_methods
        ]
        if not trusted:
            return "contact_not_verified"
        if len(trusted) != 1:
            return "contact_conflict"
        cur.execute(
            """SELECT user_id FROM account_contact WHERE contact_type=%s AND normalized_value=%s
            AND status='active' AND verified_at IS NOT NULL AND user_id<>%s LIMIT 1""",
            (contact_type, trusted[0]["normalized_value"], user["id"]),
        )
        return "contact_conflict" if cur.fetchone() else "eligible"


def email_eligibility_reason(account: str, cursor_factory=None) -> str:
    return eligibility_reason(account, contact_type="email", cursor_factory=cursor_factory)


def sms_eligibility_reason(account: str, cursor_factory=None) -> str:
    return eligibility_reason(account, contact_type="phone", cursor_factory=cursor_factory)
