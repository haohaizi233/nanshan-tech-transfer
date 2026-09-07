from psycopg2.extras import Json

from db import get_cursor
from modules.identity.service import build_user_response
from core.errors import BizError, TT_COMMON_40902, bad_request


def get_my_profile(user_id: int) -> dict:
    with get_cursor() as cur:
        return build_user_response(cur, user_id)


# 主体类型：相对稳定的属性，仅画像/推荐用，不作权限门禁
SUBJECT_TYPES = (
    "enterprise",
    "university",
    "research_institute",
    "team",
    "service_org",
    "investment_org",
    "individual",
    "other",
)

# 合作方向：可多选的画像标签，仅用于推荐与首页内容排序
CAPABILITY_TYPES = (
    "seek_technology",
    "publish_demand",
    "provide_achievement",
    "joint_rnd",
    "provide_service",
    "investment",
)

FIELD_MAP = {
    "displayName": "display_name",
    "userType": "user_type",
    "subjectType": "subject_type",
    "phone": "phone",
    "email": "email",
    "wechat": "wechat",
    "orgId": "org_id",
    "orgTitle": "org_title",
}


def _normalize_capabilities(raw):
    if raw is None:
        return None
    if isinstance(raw, str):
        raise bad_request("businessCapabilities 必须是数组")
    if not isinstance(raw, list):
        raise bad_request("businessCapabilities 必须是数组")
    vals = []
    for v in raw:
        v = str(v).strip()
        if not v:
            continue
        if v not in CAPABILITY_TYPES:
            raise bad_request(
                f"businessCapabilities 仅允许: {', '.join(CAPABILITY_TYPES)}"
            )
        if v not in vals:
            vals.append(v)
    return vals


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

    if "subject_type" in fields and fields["subject_type"] is not None:
        if fields["subject_type"] not in SUBJECT_TYPES:
            raise bad_request(
                f"subjectType 必须为: {', '.join(SUBJECT_TYPES)}"
            )

    if "businessCapabilities" in body:
        capabilities = _normalize_capabilities(body.get("businessCapabilities"))
        if capabilities:
            fields["business_capabilities"] = Json(capabilities)
        else:
            fields["business_capabilities"] = None

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
