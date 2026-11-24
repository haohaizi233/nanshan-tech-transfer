"""安全邮件服务商抽象与生产级适配器（Mock / SMTP / Tencent SES）。

关键安全规范：
1. 所有发送任务返回结构化 `DeliveryReceipt`（accepted 不等于 delivered）；
2. SMTP 显式启用严格 SSLContext 证书校验，防止头注入与 DATA 后未知结果重发；
3. Tencent SES 使用独立 TC3-HMAC-SHA256 签名（带 X-TC-Region 与 Base64 正文），
   严格映射业务错误码，禁止将未脱敏响应或用户数据写入日志/异常消息；
4. MockEmailProvider 绝不打印明文邮箱、验证码或重置链接。
"""

from __future__ import annotations

import abc
import base64
import datetime
import hashlib
import hmac
import json
import logging
import random
import re
import smtplib
import ssl
import time
import urllib.error
import urllib.request
import uuid
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr, make_msgid, parseaddr
from typing import Any

from core.contact_validation import email_domain, normalize_email
from core.errors import BizError
from modules.security.delivery_models import (
    DeliveryReceipt,
    ProviderCapabilities,
    ProviderError,
    safe_id,
)
from modules.security.email_templates import (
    RenderedEmail,
    render_otp_email,
    render_password_recovery_link_email,
    render_security_notification_email,
)

logger = logging.getLogger("nanshan.security.email_provider")

_CONTROL_CHAR_RE = re.compile(r"[\r\n\x00-\x1f\x7f]")
_ALLOWED_EMAIL_PURPOSES = frozenset(
    {"password_recovery", "reset_password", "bind_email", "rebind_email", "step_up_auth"}
)
_SES_ENDPOINT_RE = re.compile(r"^ses(?:\.[a-z0-9-]+)*\.tencentcloudapi\.com$")
_SES_REGION_RE = re.compile(r"^[a-z]{2}-[a-z0-9-]+$")


def _assert_no_header_injection(value: str, field_name: str) -> str:
    text = str(value or "")
    if _CONTROL_CHAR_RE.search(text):
        raise ProviderError(
            f"邮件头字段包含非法控制字符: {field_name}",
            code="TT_COMMON_40001",
            status=400,
            reason_code="header_injection_rejected",
        )
    return text


def _validate_send_inputs(
    email: str,
    expires_in_seconds: int,
    send_request_id: str,
    *,
    code: str | None = None,
    purpose: str | None = None,
    reset_url: str | None = None,
) -> str:
    if (
        not isinstance(send_request_id, str)
        or not 1 <= len(send_request_id) <= 128
        or _CONTROL_CHAR_RE.search(send_request_id)
    ):
        raise ProviderError("邮件请求 ID 格式无效", reason_code="invalid_parameters")
    if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= 3600:
        raise ProviderError("验证码有效期须为 1 至 3600 秒的整数", reason_code="invalid_parameters")
    if purpose is not None and purpose not in _ALLOWED_EMAIL_PURPOSES:
        raise ProviderError("不支持的邮件安全用途", reason_code="invalid_parameters")
    if code is not None and (not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None):
        raise ProviderError("邮件验证码须为 6 位数字字符串", reason_code="invalid_parameters")
    if reset_url is not None and (not isinstance(reset_url, str) or _CONTROL_CHAR_RE.search(reset_url)):
        raise ProviderError("邮件重置链接格式无效", reason_code="invalid_parameters")
    try:
        return normalize_email(email)
    except BizError:
        raise ProviderError("收件人邮箱格式不正确", reason_code="invalid_parameters") from None


class EmailProvider(abc.ABC):
    provider_name: str = "base"
    capabilities: ProviderCapabilities = ProviderCapabilities()

    @abc.abstractmethod
    def send_code(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        """发送邮件验证码。返回 True 仅代表服务商接受请求。"""

    @abc.abstractmethod
    def send_reset_link(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        """发送一次性密码重置链接。返回 True 仅代表服务商接受请求。"""

    def send_code_task(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        accepted = self.send_code(email, code, purpose, expires_in_seconds, request_id=send_request_id)
        return DeliveryReceipt(
            accepted=bool(accepted),
            provider=self.provider_name,
            channel="email_otp",
            request_id=send_request_id,
            provider_message_ids=(),
        )

    def send_reset_link_task(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        accepted = self.send_reset_link(email, reset_url, expires_in_seconds, request_id=send_request_id)
        return DeliveryReceipt(
            accepted=bool(accepted),
            provider=self.provider_name,
            channel="email_link",
            request_id=send_request_id,
            provider_message_ids=(),
        )

    def send_notification_task(
        self,
        email: str,
        event_type: str,
        occurred_at: str,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        raise ProviderError(
            "该邮件服务商未启用安全通知发送",
            reason_code="unsupported_capability",
            retryable=False,
            outcome_unknown=False,
        )

    def query_status(self, provider_ids: list[str], *, request_date: str | None = None) -> dict[str, Any]:
        raise ProviderError(
            "当前邮件服务商不支持通用投递状态查询",
            reason_code="unsupported_capability",
            retryable=False,
            outcome_unknown=False,
        )


class MockEmailProvider(EmailProvider):
    """测试/开发用内存邮件服务商；仅在内存保留记录供断言，绝不输出敏感明文日志。"""

    provider_name = "mock"
    capabilities = ProviderCapabilities(
        send_otp=True,
        send_reset_link=True,
        provider_message_id=True,
        idempotency=False,
        delivery_status_query=False,
        delivery_webhook=False,
    )

    def __init__(self):
        self.sent_emails: list[dict[str, Any]] = []
        self.should_fail: bool = False
        self.failure_error: ProviderError | None = None

    def clear(self):
        self.sent_emails.clear()
        self.should_fail = False
        self.failure_error = None

    def get_last_code(self, email: str) -> str | None:
        target = (email or "").strip().lower()
        for item in reversed(self.sent_emails):
            if item["email"] == target and "code" in item:
                return item["code"]
        return None

    def get_last_link(self, email: str) -> str | None:
        target = (email or "").strip().lower()
        for item in reversed(self.sent_emails):
            if item["email"] == target and "reset_url" in item:
                return item["reset_url"]
        return None

    def send_code(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_code_task(
            email,
            code,
            purpose,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_reset_link(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_reset_link_task(
            email,
            reset_url,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_code_task(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            code=code,
            purpose=purpose,
        )
        if self.failure_error is not None:
            raise self.failure_error
        if self.should_fail:
            raise ProviderError("模拟邮件服务发送失败", reason_code="provider_rejected", request_attempted=True)
        msg_id = f"mock-msg-{uuid.uuid4().hex[:16]}"
        self.sent_emails.append(
            {
                "email": norm_email,
                "code": code,
                "purpose": purpose,
                "type": "code",
                "expires_in_seconds": expires_in_seconds,
                "request_id": send_request_id,
                "message_id": msg_id,
                "sent_at": time.time(),
            }
        )
        logger.info(
            "[MockEmailProvider] 邮件验证码已记录 (purpose=%s, request_id=%s)",
            purpose,
            safe_id(send_request_id),
        )
        return DeliveryReceipt(
            accepted=True,
            provider=self.provider_name,
            channel="email_otp",
            request_id=send_request_id,
            provider_message_ids=(msg_id,),
        )

    def send_reset_link_task(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            reset_url=reset_url,
        )
        if self.failure_error is not None:
            raise self.failure_error
        if self.should_fail:
            raise ProviderError("模拟邮件服务发送失败", reason_code="provider_rejected", request_attempted=True)
        msg_id = f"mock-msg-{uuid.uuid4().hex[:16]}"
        self.sent_emails.append(
            {
                "email": norm_email,
                "reset_url": reset_url,
                "type": "link",
                "expires_in_seconds": expires_in_seconds,
                "request_id": send_request_id,
                "message_id": msg_id,
                "sent_at": time.time(),
            }
        )
        logger.info(
            "[MockEmailProvider] 邮件重置链接已记录 (type=link, request_id=%s)",
            safe_id(send_request_id),
        )
        return DeliveryReceipt(
            accepted=True,
            provider=self.provider_name,
            channel="email_link",
            request_id=send_request_id,
            provider_message_ids=(msg_id,),
        )

    def send_notification_task(
        self,
        email: str,
        event_type: str,
        occurred_at: str,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(email, 300, send_request_id)
        if self.failure_error is not None:
            raise self.failure_error
        if self.should_fail:
            raise ProviderError("模拟邮件通知发送失败", reason_code="provider_rejected", request_attempted=True)
        msg_id = f"mock-notify-{uuid.uuid4().hex[:16]}"
        self.sent_emails.append(
            {
                "email": norm_email,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "type": "notification",
                "request_id": send_request_id,
                "message_id": msg_id,
                "sent_at": time.time(),
            }
        )
        logger.info(
            "[MockEmailProvider] 安全通知邮件已记录 (event_type=%s, request_id=%s)",
            event_type,
            safe_id(send_request_id),
        )
        return DeliveryReceipt(
            accepted=True,
            provider=self.provider_name,
            channel="email_notification",
            request_id=send_request_id,
            provider_message_ids=(msg_id,),
        )


def build_strict_ssl_context() -> ssl.SSLContext:
    """构造强制验证主机名与证书链的 TLS 1.2+ SSLContext。"""
    ctx = ssl.create_default_context()
    ctx.check_hostname = True
    ctx.verify_mode = ssl.CERT_REQUIRED
    if hasattr(ssl, "TLSVersion"):
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    return ctx


class SmtpEmailProvider(EmailProvider):
    """生产级标准 SMTP 邮件适配器（强制 TLS 校验证书、头注入防护与错误分类）。"""

    provider_name = "smtp"
    capabilities = ProviderCapabilities(
        send_otp=True,
        send_reset_link=True,
        provider_message_id=True,
        idempotency=False,
        delivery_status_query=False,
        delivery_webhook=False,
    )

    def __init__(
        self,
        host: str,
        port: int = 465,
        user: str = "",
        password: str = "",
        use_ssl: bool = True,
        timeout: int = 10,
        *,
        from_email: str = "",
        from_name: str = "南山科转通",
        max_attempts: int = 2,
        ssl_context: ssl.SSLContext | None = None,
    ):
        self.host = str(host or "").strip()
        self.port = int(port)
        self.user = str(user or "").strip()
        self.password = str(password or "")
        self.use_ssl = bool(use_ssl)
        self.timeout = int(timeout)
        self.from_name = _assert_no_header_injection(str(from_name or "南山科转通").strip(), "from_name")
        self.max_attempts = min(3, max(1, int(max_attempts)))
        self.ssl_context = ssl_context or build_strict_ssl_context()

        if not self.host or _CONTROL_CHAR_RE.search(self.host) or any(ch.isspace() for ch in self.host):
            raise ProviderError("SMTP_HOST 配置无效", reason_code="CONFIG_ERROR")
        if not 1 <= self.port <= 65535:
            raise ProviderError("SMTP_PORT 端口配置无效", reason_code="CONFIG_ERROR")
        if self.timeout < 1:
            raise ProviderError("SMTP_TIMEOUT_SECONDS 配置无效", reason_code="CONFIG_ERROR")
        if bool(self.user) != bool(self.password):
            raise ProviderError("SMTP 认证账号与密码必须同时配置或同时留空", reason_code="CONFIG_ERROR")

        candidate_from = (from_email or self.user).strip()
        try:
            self.from_email = normalize_email(candidate_from, field_name="发件人邮箱")
        except BizError:
            raise ProviderError("SMTP 发件人邮箱配置无效", reason_code="CONFIG_ERROR") from None
        _assert_no_header_injection(self.from_email, "from_email")

    def _build_mime(
        self,
        to_email: str,
        rendered: RenderedEmail,
        send_request_id: str,
    ) -> tuple[MIMEMultipart, str]:
        _assert_no_header_injection(to_email, "to_email")
        subject = _assert_no_header_injection(rendered.subject, "subject")
        req_header = _assert_no_header_injection(send_request_id, "request_id")

        domain = email_domain(self.from_email) or "nanshan.local"
        message_id = make_msgid(domain=domain)
        _assert_no_header_injection(message_id, "message_id")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = str(Header(subject, "utf-8"))
        msg["From"] = formataddr((str(Header(self.from_name, "utf-8")), self.from_email))
        msg["To"] = to_email
        msg["Message-ID"] = message_id
        msg["X-Security-Request-ID"] = req_header
        msg.attach(MIMEText(rendered.text_body, "plain", "utf-8"))
        msg.attach(MIMEText(rendered.html_body, "html", "utf-8"))
        return msg, message_id

    @staticmethod
    def _classify_smtp_code(code: int, default_perm: str = "SMTP_PERMANENT_FAILURE") -> tuple[str, bool]:
        if code in {534, 535}:
            return "SMTP_AUTH_FAILED", False
        if 400 <= code < 500:
            return "SMTP_TEMPORARY_FAILURE", True
        return default_perm, False

    def _deliver_once(
        self,
        to_email: str,
        msg: MIMEMultipart,
        message_id: str,
        channel: str,
        send_request_id: str,
    ) -> DeliveryReceipt:
        phase = "connect"
        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(
                    self.host,
                    self.port,
                    timeout=self.timeout,
                    context=self.ssl_context,
                )
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                phase = "tls"
                server.ehlo()
                server.starttls(context=self.ssl_context)
                server.ehlo()
            with server:
                if self.user and self.password:
                    phase = "auth"
                    server.login(self.user, self.password)
                phase = "data"
                refused = server.sendmail(self.from_email, [to_email], msg.as_string())
                if isinstance(refused, dict) and refused:
                    refusal = refused.get(to_email) or next(iter(refused.values()))
                    code = int(refusal[0]) if isinstance(refusal, tuple) and refusal else 550
                    reason, retryable = self._classify_smtp_code(code, default_perm="SMTP_RECIPIENT_REJECTED")
                    raise ProviderError(
                        "邮件投递被收件服务拒绝",
                        reason_code=reason,
                        provider_status=code,
                        retryable=retryable,
                        outcome_unknown=False,
                        request_attempted=True,
                    )
            return DeliveryReceipt(
                accepted=True,
                provider=self.provider_name,
                channel=channel,
                request_id=send_request_id,
                provider_message_ids=(message_id,),
            )
        except ProviderError:
            raise
        except ssl.SSLError as exc:
            logger.warning("SMTP TLS handshake/certificate failure: %s", type(exc).__name__)
            raise ProviderError(
                "邮件服务 TLS 安全校验失败",
                reason_code="SMTP_TLS_FAILED",
                outcome_unknown=(phase == "data"),
                retryable=False,
                request_attempted=True,
            ) from None
        except smtplib.SMTPAuthenticationError as exc:
            logger.warning("SMTP authentication failed: status=%s", exc.smtp_code)
            raise ProviderError(
                "邮件服务认证失败",
                reason_code="SMTP_AUTH_FAILED",
                provider_status=exc.smtp_code,
                outcome_unknown=False,
                retryable=False,
                request_attempted=True,
            ) from None
        except smtplib.SMTPRecipientsRefused as exc:
            first = next(iter(exc.recipients.values()), (550, b""))
            code = int(first[0]) if isinstance(first, tuple) and first else 550
            reason, retryable = self._classify_smtp_code(code, default_perm="SMTP_RECIPIENT_REJECTED")
            logger.warning("SMTP recipient rejected: status=%s reason=%s", code, reason)
            raise ProviderError(
                "邮件服务拒绝收件地址",
                reason_code=reason,
                provider_status=code,
                outcome_unknown=False,
                retryable=retryable,
                request_attempted=True,
            ) from None
        except smtplib.SMTPSenderRefused as exc:
            reason, retryable = self._classify_smtp_code(exc.smtp_code, default_perm="SMTP_PERMANENT_FAILURE")
            logger.warning("SMTP sender refused: status=%s", exc.smtp_code)
            raise ProviderError(
                "邮件发件身份被拒绝",
                reason_code=reason,
                provider_status=exc.smtp_code,
                outcome_unknown=False,
                retryable=retryable,
                request_attempted=True,
            ) from None
        except smtplib.SMTPDataError as exc:
            reason, retryable = self._classify_smtp_code(exc.smtp_code, default_perm="SMTP_PERMANENT_FAILURE")
            logger.warning("SMTP data rejected: status=%s reason=%s", exc.smtp_code, reason)
            raise ProviderError(
                "邮件服务拒绝本次投递",
                reason_code=reason,
                provider_status=exc.smtp_code,
                outcome_unknown=False,
                retryable=retryable,
                request_attempted=True,
            ) from None
        except smtplib.SMTPResponseException as exc:
            reason, retryable = self._classify_smtp_code(exc.smtp_code)
            logger.warning("SMTP protocol error: phase=%s status=%s", phase, exc.smtp_code)
            raise ProviderError(
                "邮件服务返回错误状态",
                reason_code=reason,
                provider_status=exc.smtp_code,
                outcome_unknown=False,
                retryable=retryable,
                request_attempted=True,
            ) from None
        except (smtplib.SMTPServerDisconnected, TimeoutError, OSError, smtplib.SMTPException) as exc:
            # DATA 阶段断开或超时无法确认服务器是否已完成入队接收，必须标记 outcome_unknown 且严禁自动重试。
            unknown = phase == "data"
            reason = "PROVIDER_OUTCOME_UNKNOWN" if unknown else "SMTP_CONNECTION_FAILED"
            logger.warning(
                "SMTP transport error: phase=%s exc=%s outcome_unknown=%s",
                phase,
                type(exc).__name__,
                unknown,
            )
            raise ProviderError(
                "邮件发送结果待核对，请勿重复提交" if unknown else "邮件服务连接失败，请稍后重试",
                reason_code=reason,
                outcome_unknown=unknown,
                retryable=not unknown and phase == "connect",
                request_attempted=True,
            ) from None

    def _send_with_bounded_retry(
        self,
        to_email: str,
        rendered: RenderedEmail,
        channel: str,
        send_request_id: str,
    ) -> DeliveryReceipt:
        msg, message_id = self._build_mime(to_email, rendered, send_request_id)
        for attempt in range(self.max_attempts):
            try:
                return self._deliver_once(to_email, msg, message_id, channel, send_request_id)
            except ProviderError as exc:
                if exc.outcome_unknown or not exc.retryable or attempt + 1 >= self.max_attempts:
                    raise
                time.sleep(min(0.2 * (2**attempt) + random.random() * 0.1, 1.0))
        raise ProviderError(
            "邮件发送结果待核对",
            reason_code="PROVIDER_OUTCOME_UNKNOWN",
            outcome_unknown=True,
            request_attempted=True,
        )

    def send_code(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_code_task(
            email,
            code,
            purpose,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_reset_link(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_reset_link_task(
            email,
            reset_url,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_code_task(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            code=code,
            purpose=purpose,
        )
        rendered = render_otp_email(purpose, code, expires_in_seconds)
        return self._send_with_bounded_retry(norm_email, rendered, "email_otp", send_request_id)

    def send_reset_link_task(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            reset_url=reset_url,
        )
        rendered = render_password_recovery_link_email(reset_url, expires_in_seconds)
        return self._send_with_bounded_retry(norm_email, rendered, "email_link", send_request_id)

    def send_notification_task(
        self,
        email: str,
        event_type: str,
        occurred_at: str,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(email, 300, send_request_id)
        rendered = render_security_notification_email(event_type, occurred_at)
        return self._send_with_bounded_retry(norm_email, rendered, "email_notification", send_request_id)


class TencentSesProvider(EmailProvider):
    """腾讯云 SES 邮件推送服务商（TC3-HMAC-SHA256 签名，SendEmail 2020-10-02）。"""

    provider_name = "tencent"
    capabilities = ProviderCapabilities(
        send_otp=True,
        send_reset_link=True,
        provider_message_id=True,
        idempotency=False,
        delivery_status_query=True,
        delivery_webhook=True,
    )

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        from_email: str,
        region: str = "ap-hongkong",
        endpoint: str = "ses.tencentcloudapi.com",
        timeout: int = 10,
        otp_template_id: int = 0,
        reset_template_id: int = 0,
    ):
        self.secret_id = str(secret_id or "").strip()
        self.secret_key = str(secret_key or "").strip()
        self.from_email = _assert_no_header_injection(str(from_email or "").strip(), "from_email")
        self.region = str(region or "").strip().lower()
        self.endpoint = str(endpoint or "ses.tencentcloudapi.com").strip().lower()
        self.timeout = int(timeout)
        self.otp_template_id = int(otp_template_id or 0)
        self.reset_template_id = int(reset_template_id or 0)

        if not (self.secret_id and self.secret_key and self.from_email and self.region):
            raise ProviderError("腾讯云 SES 配置不完整，缺少密钥、发信地址或 Region", reason_code="CONFIG_ERROR")
        if not _SES_REGION_RE.fullmatch(self.region):
            raise ProviderError("腾讯云 SES Region 配置无效", reason_code="CONFIG_ERROR")
        if not _SES_ENDPOINT_RE.fullmatch(self.endpoint):
            raise ProviderError("腾讯云 SES Endpoint 配置无效", reason_code="CONFIG_ERROR")
        if self.timeout < 1:
            raise ProviderError("腾讯云 SES 超时配置无效", reason_code="CONFIG_ERROR")
        _, parsed_addr = parseaddr(self.from_email)
        try:
            normalize_email(parsed_addr or self.from_email, field_name="发信地址")
        except BizError:
            raise ProviderError("腾讯云 SES 发信邮箱格式无效", reason_code="CONFIG_ERROR") from None

    def _tc3_request(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        service = "ses"
        version = "2020-10-02"
        canonical_uri = "/"
        canonical_querystring = ""
        canonical_headers = (
            f"content-type:application/json; charset=utf-8\nhost:{self.endpoint}\nx-tc-action:{action.lower()}\n"
        )
        signed_headers = "content-type;host;x-tc-action"
        payload_bytes = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        hashed_payload = hashlib.sha256(payload_bytes).hexdigest()
        canonical_request = (
            f"POST\n{canonical_uri}\n{canonical_querystring}\n{canonical_headers}\n{signed_headers}\n{hashed_payload}"
        )

        now = datetime.datetime.now(datetime.UTC)
        date = now.strftime("%Y-%m-%d")
        timestamp = int(now.timestamp())
        credential_scope = f"{date}/{service}/tc3_request"
        hashed_canonical_request = hashlib.sha256(canonical_request.encode("utf-8")).hexdigest()
        string_to_sign = f"TC3-HMAC-SHA256\n{timestamp}\n{credential_scope}\n{hashed_canonical_request}"

        def _hmac_sha256(key: bytes, msg: str) -> bytes:
            return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

        secret_date = _hmac_sha256(("TC3" + self.secret_key).encode("utf-8"), date)
        secret_service = _hmac_sha256(secret_date, service)
        secret_signing = _hmac_sha256(secret_service, "tc3_request")
        signature = hmac.new(secret_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

        authorization = (
            f"TC3-HMAC-SHA256 Credential={self.secret_id}/{credential_scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Host": self.endpoint,
            "Authorization": authorization,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
            "X-TC-Region": self.region,
        }

        req = urllib.request.Request(f"https://{self.endpoint}/", data=payload_bytes, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            unknown = exc.code >= 500
            logger.warning("Tencent SES HTTP error: action=%s status=%s", action, exc.code)
            raise ProviderError(
                "邮件服务请求失败，请稍后重试",
                reason_code="PROVIDER_OUTCOME_UNKNOWN" if unknown else "SES_PERMISSION_ERROR",
                provider_status=exc.code,
                outcome_unknown=unknown,
                retryable=False,
                request_attempted=True,
            ) from None
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            logger.warning("Tencent SES transport error: action=%s exc=%s", action, type(exc).__name__)
            raise ProviderError(
                "邮件发送结果待核对，请勿重复提交",
                reason_code="PROVIDER_OUTCOME_UNKNOWN",
                outcome_unknown=True,
                retryable=False,
                request_attempted=True,
            ) from None

        try:
            data = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeError):
            logger.warning("Tencent SES invalid JSON response: action=%s", action)
            raise ProviderError(
                "邮件服务响应异常，请勿重复发起",
                reason_code="SES_INVALID_RESPONSE",
                outcome_unknown=True,
                retryable=False,
                request_attempted=True,
            ) from None

        if not isinstance(data, dict) or not isinstance(data.get("Response"), dict):
            logger.warning("Tencent SES malformed response structure: action=%s", action)
            raise ProviderError(
                "邮件服务响应异常，请勿重复发起",
                reason_code="SES_INVALID_RESPONSE",
                outcome_unknown=True,
                retryable=False,
                request_attempted=True,
            )
        return data

    @staticmethod
    def _classify_ses_error(err_code: str) -> tuple[str, bool]:
        if err_code.startswith("AuthFailure.Signature") or err_code in {
            "AuthFailure.InvalidSecretId",
            "AuthFailure.SecretIdNotFound",
        }:
            return "SES_SIGNATURE_ERROR", False
        if (
            err_code.startswith("AuthFailure.")
            or err_code.startswith("UnauthorizedOperation")
            or err_code
            in {
                "FailedOperation.NotAuthenticatedSender",
                "FailedOperation.InvalidAttachName",
            }
        ):
            return "SES_PERMISSION_ERROR", False
        if err_code.startswith(("LimitExceeded", "RequestLimitExceeded")) or err_code in {
            "FailedOperation.ExceedSendLimit",
            "FailedOperation.InsufficientQuota",
            "FailedOperation.FrequencyLimit",
        }:
            return "SES_QUOTA_EXCEEDED", False
        if err_code.startswith("InternalError"):
            return "PROVIDER_OUTCOME_UNKNOWN", True
        if err_code.startswith(("InvalidParameter", "MissingParameter")):
            return "CONFIG_ERROR", False
        return "SES_INVALID_RESPONSE", False

    def _send_ses_payload(
        self,
        to_email: str,
        subject: str,
        channel: str,
        send_request_id: str,
        *,
        rendered: RenderedEmail | None = None,
        template_id: int = 0,
        template_data: dict[str, Any] | None = None,
    ) -> DeliveryReceipt:
        payload: dict[str, Any] = {
            "FromEmailAddress": self.from_email,
            "Destination": [to_email],
            "Subject": _assert_no_header_injection(subject, "subject"),
            "TriggerType": 1,
        }
        if template_id > 0 and template_data is not None:
            payload["Template"] = {
                "TemplateID": template_id,
                "TemplateData": json.dumps(template_data, ensure_ascii=False, separators=(",", ":")),
            }
        else:
            assert rendered is not None
            payload["Simple"] = {
                "Html": base64.b64encode(rendered.html_body.encode("utf-8")).decode("ascii"),
                "Text": base64.b64encode(rendered.text_body.encode("utf-8")).decode("ascii"),
            }

        data = self._tc3_request("SendEmail", payload)
        resp = data["Response"]
        if "Error" in resp:
            err = resp.get("Error") or {}
            err_code = str(err.get("Code") or "UnknownError")
            reason, unknown = self._classify_ses_error(err_code)
            logger.warning("Tencent SES rejected SendEmail: code=%s reason=%s", err_code, reason)
            raise ProviderError(
                "邮件发送结果待核对，请勿重复提交" if unknown else "邮件服务暂时不可用，请稍后重试",
                reason_code=reason,
                outcome_unknown=unknown,
                retryable=False,
                request_attempted=True,
            )

        message_id = resp.get("MessageId")
        request_id = resp.get("RequestId")
        if not isinstance(message_id, str) or not message_id.strip():
            logger.warning("Tencent SES missing MessageId in SendEmail response")
            raise ProviderError(
                "邮件服务响应异常，请勿重复发起",
                reason_code="SES_INVALID_RESPONSE",
                outcome_unknown=True,
                retryable=False,
                request_attempted=True,
            )

        return DeliveryReceipt(
            accepted=True,
            provider=self.provider_name,
            channel=channel,
            request_id=str(request_id or send_request_id),
            provider_message_ids=(message_id.strip(),),
        )

    def send_code(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_code_task(
            email,
            code,
            purpose,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_reset_link(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        request_id: str | None = None,
    ) -> bool:
        receipt = self.send_reset_link_task(
            email,
            reset_url,
            expires_in_seconds,
            send_request_id=request_id or str(uuid.uuid4()),
        )
        return receipt.accepted

    def send_code_task(
        self,
        email: str,
        code: str,
        purpose: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            code=code,
            purpose=purpose,
        )
        rendered = render_otp_email(purpose, code, expires_in_seconds)
        if self.otp_template_id > 0:
            minutes = max(1, expires_in_seconds // 60)
            return self._send_ses_payload(
                norm_email,
                rendered.subject,
                "email_otp",
                send_request_id,
                template_id=self.otp_template_id,
                template_data={"code": code, "minutes": str(minutes)},
            )
        return self._send_ses_payload(
            norm_email,
            rendered.subject,
            "email_otp",
            send_request_id,
            rendered=rendered,
        )

    def send_reset_link_task(
        self,
        email: str,
        reset_url: str,
        expires_in_seconds: int = 300,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(
            email,
            expires_in_seconds,
            send_request_id,
            reset_url=reset_url,
        )
        rendered = render_password_recovery_link_email(reset_url, expires_in_seconds)
        if self.reset_template_id > 0:
            minutes = max(1, expires_in_seconds // 60)
            return self._send_ses_payload(
                norm_email,
                rendered.subject,
                "email_link",
                send_request_id,
                template_id=self.reset_template_id,
                template_data={"resetUrl": reset_url, "minutes": str(minutes)},
            )
        return self._send_ses_payload(
            norm_email,
            rendered.subject,
            "email_link",
            send_request_id,
            rendered=rendered,
        )

    def send_notification_task(
        self,
        email: str,
        event_type: str,
        occurred_at: str,
        *,
        send_request_id: str,
    ) -> DeliveryReceipt:
        norm_email = _validate_send_inputs(email, 300, send_request_id)
        rendered = render_security_notification_email(event_type, occurred_at)
        return self._send_ses_payload(
            norm_email,
            rendered.subject,
            "email_notification",
            send_request_id,
            rendered=rendered,
        )

    def query_status(self, provider_ids: list[str], *, request_date: str | None = None) -> dict[str, Any]:
        """查询腾讯云 SES 发送状态（GetSendEmailStatus 2020-10-02）。"""
        if not provider_ids or any(not str(item).strip() for item in provider_ids):
            raise ProviderError("缺少服务商邮件 MessageId", reason_code="invalid_parameters")
        query_date = request_date or datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%d")
        payload = {
            "RequestDate": query_date,
            "Offset": 0,
            "Limit": 100,
            "MessageId": str(provider_ids[0]).strip(),
        }
        data = self._tc3_request("GetSendEmailStatus", payload)
        resp = data["Response"]
        if "Error" in resp:
            err_code = str((resp.get("Error") or {}).get("Code") or "UnknownError")
            reason, unknown = self._classify_ses_error(err_code)
            raise ProviderError("邮件状态查询失败", reason_code=reason, outcome_unknown=unknown)
        status_list = resp.get("EmailStatusList") or []
        if not isinstance(status_list, list):
            raise ProviderError("邮件状态查询响应格式无效", reason_code="SES_INVALID_RESPONSE", outcome_unknown=True)
        return {
            "accepted": True,
            "request_id": resp.get("RequestId"),
            "records": status_list,
        }
