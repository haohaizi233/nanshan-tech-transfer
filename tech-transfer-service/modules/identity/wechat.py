import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from threading import Lock

from psycopg2 import IntegrityError

from config import settings
from core.contact_validation import validate_phone
from core.errors import (
    TT_AUTH_40106, TT_AUTH_40902, TT_AUTH_40903, BizError, bad_request, forbidden,
)
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.identity.service import (
    _get_roles, _issue_session, build_user_response, create_password_account,
)


_token_lock = Lock()
_token_cache = {}


def wechat_login_enabled() -> bool:
    return bool(settings.WECHAT_LOGIN_ENABLED and settings.WECHAT_APPID and settings.WECHAT_APP_SECRET)


def _require_enabled():
    if not wechat_login_enabled():
        raise BizError("TT_COMMON_50301", "微信登录暂未配置，请使用手机号密码登录", 503)


def _wechat_json(path: str, *, query=None, body=None) -> dict:
    url = "https://api.weixin.qq.com/" + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    request = urllib.request.Request(
        url, data=json.dumps(body).encode() if body is not None else None,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            data = json.loads(response.read(65537))
    except (urllib.error.URLError, OSError, ValueError):
        raise BizError("TT_COMMON_50301", "微信服务暂不可用，请稍后重试", 503) from None
    if not isinstance(data, dict) or data.get("errcode", 0) != 0:
        raise BizError("TT_AUTH_40103", "微信授权无效或已过期，请重新授权", 401)
    return data


def exchange_login_code(code: str) -> str:
    data = _wechat_json("sns/jscode2session", query={
        "appid": settings.WECHAT_APPID, "secret": settings.WECHAT_APP_SECRET,
        "js_code": code, "grant_type": "authorization_code",
    })
    openid = data.get("openid")
    if not isinstance(openid, str) or not openid or len(openid) > 128:
        raise BizError("TT_AUTH_40103", "微信身份校验失败，请重试", 401)
    return openid


def _access_token() -> str:
    key = (settings.WECHAT_APPID, settings.WECHAT_APP_SECRET)
    with _token_lock:
        cached = _token_cache.get(key)
        if cached and cached[1] > time.monotonic():
            return cached[0]
        data = _wechat_json("cgi-bin/stable_token", body={
            "grant_type": "client_credential", "appid": key[0], "secret": key[1],
        })
        token = data.get("access_token")
        expires = data.get("expires_in")
        if not isinstance(token, str) or not token or type(expires) is not int or expires <= 0:
            raise BizError("TT_COMMON_50301", "微信服务凭证暂不可用", 503)
        _token_cache.clear()
        _token_cache[key] = (token, time.monotonic() + max(0, expires - 120))
        return token


def exchange_phone_code(code: str, openid: str) -> str:
    data = _wechat_json("wxa/business/getuserphonenumber", query={"access_token": _access_token()},
                        body={"code": code, "openid": openid})
    info = data.get("phone_info")
    if not isinstance(info, dict) or not isinstance(info.get("watermark"), dict):
        raise bad_request("微信手机号校验失败，请重新授权")
    if info["watermark"].get("appid") != settings.WECHAT_APPID or str(info.get("countryCode")) != "86":
        raise bad_request("请授权当前小程序可用的中国大陆手机号")
    return validate_phone(info.get("purePhoneNumber"), required=True)


def _check_account(account):
    if account.get("user_status") != "active" or account.get("cred_status") != "active":
        raise BizError(*TT_AUTH_40106)


def wechat_login_session(login_code: str, phone_code: str | None = None, *, bind_user_id: int | None = None) -> dict:
    _require_enabled()
    openid = exchange_login_code(login_code)
    phone = exchange_phone_code(phone_code, openid) if phone_code else None
    if bind_user_id is not None and not phone:
        raise bad_request("绑定微信需要授权核验手机号")
    is_new = False
    try:
        with get_cursor(commit=True) as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", ("wechat:" + settings.WECHAT_APPID,))
            cursor.execute(
                "SELECT ei.user_id, ei.unlinked_at, au.status AS user_status, uc.status AS cred_status, uc.phone "
                "FROM external_identity ei JOIN app_user au ON au.id=ei.user_id "
                "LEFT JOIN user_credential uc ON uc.user_id=ei.user_id "
                "WHERE ei.issuer='wechat-mini' AND ei.tenant_id=%s AND ei.external_subject=%s "
                "AND au.deleted_at IS NULL",
                (settings.WECHAT_APPID, openid),
            )
            linked = cursor.fetchone()
            if linked:
                _check_account(linked)
                if linked.get("unlinked_at") is not None:
                    raise forbidden("微信绑定已失效，请联系管理员")
                user_id = linked["user_id"]
                if bind_user_id is not None and bind_user_id != user_id:
                    raise forbidden("该微信已绑定其他账号，不能合并")
                if phone and phone != linked.get("phone"):
                    raise forbidden("授权手机号与账号绑定手机号不一致")
            else:
                if not phone:
                    raise BizError(*TT_AUTH_40902)
                cursor.execute(
                    "SELECT uc.user_id, uc.phone, uc.status AS cred_status, au.status AS user_status "
                    "FROM user_credential uc JOIN app_user au ON au.id=uc.user_id "
                    "WHERE uc.phone=%s OR (uc.phone IS NULL AND uc.username=%s)",
                    (phone, phone),
                )
                account = cursor.fetchone()
                if account:
                    _check_account(account)
                    if bind_user_id is None:
                        raise BizError(*TT_AUTH_40903)
                    if bind_user_id != account["user_id"]:
                        raise forbidden("只能绑定当前账号的登录手机号")
                    user_id = account["user_id"]
                    if not account.get("phone"):
                        cursor.execute("UPDATE user_credential SET phone=%s WHERE user_id=%s", (phone, user_id))
                else:
                    if bind_user_id is not None:
                        raise forbidden("授权手机号与当前账号登录手机号不一致")
                    user_id, _ = create_password_account(cursor, phone, secrets.token_urlsafe(48), phone=phone)
                    cursor.execute("UPDATE user_credential SET password_configured=false WHERE user_id=%s", (user_id,))
                    is_new = True
                cursor.execute(
                    "INSERT INTO external_identity (user_id, issuer, tenant_id, external_subject) "
                    "VALUES (%s, 'wechat-mini', %s, %s)",
                    (user_id, settings.WECHAT_APPID, openid),
                )
                audit_record("user.bind_wechat", "app_user", resource_id=user_id, actor_user_id=user_id, cur=cursor)
            result = _issue_session(cursor, user_id, _get_roles(cursor, user_id))
            result["user"] = build_user_response(cursor, user_id)
            result["isNewUser"] = is_new
            return result
    except IntegrityError:
        raise BizError("TT_COMMON_40903", "账号或微信已绑定，请重新登录后重试", 409) from None
