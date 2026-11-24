"""工程化邮件模板渲染器（text/html + text/plain，严格 HTML 转义）。"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from urllib.parse import urlsplit

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates" / "email"
_SAFE_CODE_RE = re.compile(r"^[0-9]{6}$")


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html_body: str
    text_body: str


@lru_cache(maxsize=16)
def _load_template(name: str) -> str:
    path = _TEMPLATE_DIR / name
    return path.read_text(encoding="utf-8")


def _format_ttl(expires_in_seconds: int) -> str:
    if expires_in_seconds < 60:
        return f"{expires_in_seconds} 秒"
    minutes, rem = divmod(expires_in_seconds, 60)
    if rem == 0:
        return f"{minutes} 分钟"
    return f"{minutes} 分 {rem} 秒"


def _render_layout(*, title: str, subtitle: str, body_html: str) -> str:
    base = _load_template("base.html")
    return (
        base.replace("{{TITLE}}", html.escape(title, quote=True))
        .replace("{{SUBTITLE}}", html.escape(subtitle, quote=True))
        .replace("{{BODY_HTML}}", body_html)
    )


def _validate_reset_url(reset_url: str) -> str:
    text = str(reset_url or "").strip()
    if not text or any(ord(ch) < 32 or ord(ch) == 127 or ch.isspace() for ch in text):
        raise ValueError("重置链接格式无效")
    parsed = urlsplit(text)
    if (parsed.scheme or "").lower() not in {"http", "https"} or not parsed.netloc:
        raise ValueError("重置链接必须使用 http/https 协议")
    return text


def render_otp_email(purpose: str, code: str, expires_in_seconds: int = 300) -> RenderedEmail:
    """渲染邮箱验证码邮件（Subject 绝不嵌入验证码）。"""
    if not _SAFE_CODE_RE.fullmatch(str(code or "")):
        raise ValueError("验证码须为 6 位数字字符串")
    ttl_text = _format_ttl(int(expires_in_seconds))
    safe_code = html.escape(code, quote=True)
    safe_ttl = html.escape(ttl_text, quote=True)

    if purpose in {"bind_email", "rebind_email"}:
        action_label = "更换绑定" if purpose == "rebind_email" else "绑定"
        subject = f"【南山科转通】安全邮箱{action_label}验证码"
        subtitle = "安全联系方式确权验证"
        body = (
            _load_template("email_binding.html")
            .replace("{{ACTION_LABEL}}", html.escape(action_label, quote=True))
            .replace("{{CODE}}", safe_code)
            .replace("{{TTL_TEXT}}", safe_ttl)
        )
        text_body = (
            f"南山科转通 · 统一安全中心\n\n"
            f"您正在{action_label}南山科转通账号的安全邮箱，本次一次性验证码为：{code}\n"
            f"验证码有效期为 {ttl_text}。请勿向任何人透露此验证码。\n"
            f"如非本人操作，请忽略本邮件并尽快修改登录密码。"
        )
    else:
        purpose_label = {
            "password_recovery": "密码找回",
            "reset_password": "密码找回",
            "step_up_auth": "高风险操作二次身份验证",
        }.get(purpose, "身份安全验证")
        subject = "【南山科转通】身份安全验证码"
        subtitle = "账号安全与身份核验"
        body = (
            _load_template("verification_code.html")
            .replace("{{PURPOSE_LABEL}}", html.escape(purpose_label, quote=True))
            .replace("{{CODE}}", safe_code)
            .replace("{{TTL_TEXT}}", safe_ttl)
        )
        text_body = (
            f"南山科转通 · 统一安全中心\n\n"
            f"您正在进行{purpose_label}安全验证，本次 6 位一次性验证码为：{code}\n"
            f"该验证码将在 {ttl_text} 后失效，且仅可使用一次。\n"
            f"如非本人操作，请忽略本邮件并建议检查账号安全状态。"
        )

    html_body = _render_layout(title=subject, subtitle=subtitle, body_html=body)
    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)


def render_password_recovery_link_email(reset_url: str, expires_in_seconds: int = 300) -> RenderedEmail:
    """渲染密码重置链接邮件（严格转义 URL，不包含追踪像素或 JS）。"""
    clean_url = _validate_reset_url(reset_url)
    ttl_text = _format_ttl(int(expires_in_seconds))
    safe_url = html.escape(clean_url, quote=True)
    safe_ttl = html.escape(ttl_text, quote=True)

    subject = "【南山科转通】密码找回与安全重置"
    subtitle = "密码重置验证"
    body = _load_template("password_recovery.html").replace("{{RESET_URL}}", safe_url).replace("{{TTL_TEXT}}", safe_ttl)
    text_body = (
        f"南山科转通 · 统一安全中心\n\n"
        f"我们收到了您重置南山科转通账号密码的申请。请在浏览器中打开以下链接完成确认并设置新密码：\n"
        f"{clean_url}\n\n"
        f"该链接将在 {ttl_text} 后失效，仅在您手动确认提交后核销。\n"
        f"如非本人操作，请忽略本邮件，切勿转发该链接。"
    )
    html_body = _render_layout(title=subject, subtitle=subtitle, body_html=body)
    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)


def render_security_notification_email(event_type: str, occurred_at: str) -> RenderedEmail:
    """渲染账号安全变更通知邮件（换绑通知、密码重置完成通知）。"""
    summary_map = {
        "email_rebound": "您的账号已更换并确权新的安全邮箱地址。",
        "email_bound": "您的账号已首次绑定并确权安全邮箱地址。",
        "password_reset": "您的账号已完成密码重置，所有历史设备登录会话已自动失效。",
    }
    event_summary = summary_map.get(event_type, "您的账号刚刚完成了一项重要安全配置变更。")
    subject = "【南山科转通】账号安全变更通知"
    subtitle = "安全事件提醒"
    body = (
        _load_template("security_notification.html")
        .replace("{{OCCURRED_AT}}", html.escape(str(occurred_at), quote=True))
        .replace("{{EVENT_SUMMARY}}", html.escape(event_summary, quote=True))
    )
    text_body = (
        f"南山科转通 · 统一安全中心\n\n"
        f"您的账号于 {occurred_at} 完成了一项安全变更操作：{event_summary}\n"
        f"如非本人操作，请立即登录平台修改密码并吊销全部设备会话，或联系系统管理员。"
    )
    html_body = _render_layout(title=subject, subtitle=subtitle, body_html=body)
    return RenderedEmail(subject=subject, html_body=html_body, text_body=text_body)
