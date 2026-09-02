from db import get_cursor
from modules.identity.service import build_user_response
from core.errors import BizError, TT_COMMON_40902, bad_request


def get_my_profile(user_id: int) -> dict:
    with get_cursor() as cur:
        return build_user_response(cur, user_id)


FIELD_MAP = {
    "displayName": "display_name",
    "userType": "user_type",
    "phone": "phone",
    "email": "email",
    "orgId": "org_id",
    "orgTitle": "org_title",
}


def update_my_profile(user_id: int, body: dict) -> dict:
    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        raise bad_request("version 必须为正整数")

    fields = {}
    for camel_key, db_col in FIELD_MAP.items():
        if camel_key in body:
            val = body[camel_key]
            if db_col in ("org_id",):
                if val is not None:
                    val = int(val)
            else:
                if val is not None:
                    val = str(val).strip()
                    if not val:
                        val = None
            fields[db_col] = val

    allowed_types = {"enterprise_staff", "researcher", "investor", "service_org", "other"}
    if "user_type" in fields and fields["user_type"] is not None:
        if fields["user_type"] not in allowed_types:
            raise bad_request(
                f"userType 必须为: {', '.join(sorted(allowed_types))}"
            )

    if not fields:
        raise bad_request("没有可更新的字段")

    set_clauses = [f"{k}=%s" for k in fields]
    set_clauses.append("version=version+1")
    params = list(fields.values())
    params.append(user_id)
    params.append(version)

    sql = (
        f"UPDATE user_profile SET {', '.join(set_clauses)} "
        f"WHERE user_id=%s AND version=%s"
    )

    with get_cursor(commit=True) as cur:
        cur.execute(sql, params)
        if cur.rowcount == 0:
            cur.execute(
                "SELECT version FROM user_profile WHERE user_id=%s", (user_id,)
            )
            row = cur.fetchone()
            current_version = row["version"] if row else 0
            code, message, status = TT_COMMON_40902
            raise BizError(
                code,
                "资料版本冲突，请刷新后重试",
                status,
                {"currentVersion": current_version},
            )

        return build_user_response(cur, user_id)
