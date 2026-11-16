"""PC 微信开放平台网页扫码登录与 OAuth2 服务。

实现：
1. OAuth state 安全生成与一次性消费（防 CSRF 攻击）
2. 网页扫码授权链接生成（open.weixin.qq.com/connect/qrconnect）
3. Code 换取 OpenID / UnionID
4. 本地 external_identity 匹配与已绑定账号会话签发
5. 未绑定微信的安全引导与可信绑定
"""

from __future__ import annotations

import json
import logging
import secrets
import time
import urllib.parse
import urllib.request

from config import settings
from core import auth_cache
from core.errors import TT_AUTH_40103, TT_AUTH_40106, BizError, bad_request, forbidden
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.identity.service import _get_roles, _issue_session, build_user_response

logger = logging.getLogger("nanshan.identity.wechat_web")

_oauth_states: dict[str, float] = {}
_STATE_TTL_SECONDS = 600  # 10 分钟


def wechat_web_enabled() -> bool:
    return bool(settings.WECHAT_OPEN_ENABLED and settings.WECHAT_OPEN_APPID and settings.WECHAT_OPEN_APP_SECRET)


def create_oauth_state() -> str:
    """生成具备时效性与一次性消费语义的 OAuth state。"""
    now = time.time()
    # 清理过期 state
    expired = [k for k, exp in _oauth_states.items() if exp < now]
    for k in expired:
        _oauth_states.pop(k, None)

    state = secrets.token_urlsafe(24)
    _oauth_states[state] = now + _STATE_TTL_SECONDS
    return state


def verify_and_consume_state(state: str) -> bool:
    """核销 state，单次使用。"""
    if not state:
        return False
    now = time.time()
    exp = _oauth_states.pop(state, None)
    return exp is not None and exp >= now


def get_web_authorize_url(redirect_uri: str) -> dict:
    """生成微信开放平台扫码登录 URL。"""
    state = create_oauth_state()
    encoded_redirect = urllib.parse.quote(redirect_uri, safe="")
    appid = settings.WECHAT_OPEN_APPID or "wx_mock_open_appid"
    url = (
        f"https://open.weixin.qq.com/connect/qrconnect?"
        f"appid={appid}&redirect_uri={encoded_redirect}&response_type=code"
        f"&scope=snsapi_login&state={state}#wechat_redirect"
    )
    return {
        "authorizeUrl": url,
        "state": state,
        "enabled": wechat_web_enabled(),
    }


def exchange_web_code(code: str) -> dict:
    """通过 code 向微信换取 access_token, openid, unionid。"""
    if not wechat_web_enabled():
        # 本地开发与单元测试 mock 行为
        if code.startswith("mock_code_"):
            mock_id = code.replace("mock_code_", "")
            return {
                "openid": f"mock_web_openid_{mock_id}",
                "unionid": f"mock_unionid_{mock_id}",
            }
        raise BizError("TT_COMMON_50301", "PC 微信登录尚未配置开放平台凭据", 503)

    query = {
        "appid": settings.WECHAT_OPEN_APPID,
        "secret": settings.WECHAT_OPEN_APP_SECRET,
        "code": code,
        "grant_type": "authorization_code",
    }
    url = "https://api.weixin.qq.com/sns/oauth2/access_token?" + urllib.parse.urlencode(query)
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        logger.error("微信开放平台换取 Token 网络异常: %s", e)
        raise BizError("TT_COMMON_50301", "微信开放平台服务暂时不可用，请稍后重试", 503) from None

    if "errcode" in data and data["errcode"] != 0:
        logger.warning("微信换取 Token 失败: %s", data)
        raise BizError(TT_AUTH_40103[0], f"微信授权失败: {data.get('errmsg', '无效的 code')}", 401)

    return {
        "openid": data.get("openid"),
        "unionid": data.get("unionid"),
    }


def handle_web_callback(code: str, state: str) -> dict:
    """处理扫码回调，验证 state，兑换身份并查找绑定。"""
    if not verify_and_consume_state(state):
        raise BizError("TT_AUTH_40103", "微信授权请求已过期或 state 无效，请重新扫码", 401)

    wx_identity = exchange_web_code(code)
    openid = wx_identity.get("openid")
    unionid = wx_identity.get("unionid")
    if not openid:
        raise BizError(TT_AUTH_40103[0], "未能获取有效的微信用户标识", 401)

    appid = settings.WECHAT_OPEN_APPID or "default"

    with get_cursor(commit=True) as cur:
        # 1. 首先按 openid 查找已绑定的 web 身份
        cur.execute(
            """
            SELECT ei.user_id, ei.unlinked_at, au.status AS user_status, uc.status AS cred_status
            FROM external_identity ei
            JOIN app_user au ON au.id = ei.user_id
            LEFT JOIN user_credential uc ON uc.user_id = ei.user_id
            WHERE ei.issuer = 'wechat-web' AND ei.tenant_id = %s AND ei.external_subject = %s
              AND au.deleted_at IS NULL
            """,
            (appid, openid),
        )
        linked = cur.fetchone()

        # 2. 若未直接命中，且有官方返回的 unionid，尝试跨应用匹配同一开放平台用户
        if not linked and unionid:
            cur.execute(
                """
                SELECT ei.user_id, ei.unlinked_at, au.status AS user_status, uc.status AS cred_status
                FROM external_identity ei
                JOIN app_user au ON au.id = ei.user_id
                LEFT JOIN user_credential uc ON uc.user_id = ei.user_id
                WHERE ei.display_name_snapshot = %s AND au.deleted_at IS NULL
                LIMIT 1
                """,
                (f"unionid:{unionid}",),
            )
            linked = cur.fetchone()

        if linked:
            if linked.get("unlinked_at") is not None:
                raise forbidden("微信绑定已解除，请联系管理员")
            if linked.get("user_status") != "active" or linked.get("cred_status") != "active":
                raise BizError(*TT_AUTH_40106)

            user_id = linked["user_id"]
            roles = _get_roles(cur, user_id)
            result = _issue_session(cur, user_id, roles)
            result["user"] = build_user_response(cur, user_id)
            result["isNewUser"] = False
            return result

    # 未绑定用户：签发短期绑定票据
    ticket = secrets.token_urlsafe(32)
    masked_openid = openid[:4] + "****" + openid[-4:] if len(openid) > 8 else "****"
    auth_cache.cached(("wechat_web_bind_ticket", ticket), lambda: {"openid": openid, "unionid": unionid})

    return {
        "isBound": False,
        "bindingTicket": ticket,
        "maskedOpenId": masked_openid,
        "message": "该微信尚未绑定科转通账号，请先登录已有账号或注册新账号完成绑定",
    }


def bind_web_wechat(user_id: int, binding_ticket: str) -> dict:
    """将扫码获取的微信身份与当前已登录用户进行安全绑定。"""
    ticket = (binding_ticket or "").strip()
    if not ticket:
        raise bad_request("缺少绑定票据")

    payload = auth_cache.cached(("wechat_web_bind_ticket", ticket), lambda: None)
    if not payload:
        raise bad_request("绑定票据无效或已过期，请重新扫码")

    openid = payload["openid"]
    unionid = payload.get("unionid")
    appid = settings.WECHAT_OPEN_APPID or "default"

    with get_cursor(commit=True) as cur:
        # 检查是否已被其他账号绑定
        cur.execute(
            """
            SELECT user_id FROM external_identity
            WHERE issuer = 'wechat-web' AND tenant_id = %s AND external_subject = %s
              AND unlinked_at IS NULL
            """,
            (appid, openid),
        )
        existing = cur.fetchone()
        if existing:
            if existing["user_id"] != user_id:
                raise forbidden("该微信已绑定其他账号，不可重复绑定")
            return {"ok": True, "message": "该微信已与当前账号绑定"}

        display_snapshot = f"unionid:{unionid}" if unionid else None
        cur.execute(
            """
            INSERT INTO external_identity (user_id, issuer, tenant_id, external_subject, display_name_snapshot)
            VALUES (%s, 'wechat-web', %s, %s, %s)
            """,
            (user_id, appid, openid, display_snapshot),
        )
        audit_record("user.bind_wechat_web", "app_user", resource_id=user_id, actor_user_id=user_id, cur=cur)

    return {"ok": True, "message": "PC 微信绑定成功"}
