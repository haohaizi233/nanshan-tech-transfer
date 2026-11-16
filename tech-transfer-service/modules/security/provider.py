"""安全服务商抽象与适配器（SMS / Email）。

提供：
1. SmsProvider / EmailProvider 抽象基类
2. MockSmsProvider / MockEmailProvider（用于开发与自动化测试，支持断言检查）
3. TencentSmsProvider（腾讯云短信 API，纯标准库 TC3-HMAC-SHA256 签名）
4. TencentSesProvider（腾讯云邮件推送 SES API）
5. SmtpEmailProvider（标准 SMTP 邮件发送）
6. 服务商工厂与配置校验
"""

from __future__ import annotations

import abc
import datetime
import hashlib
import hmac
import json
import logging
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from config import settings
from core.errors import BizError

logger = logging.getLogger("nanshan.security.provider")


class ProviderError(BizError):
    def __init__(self, message: str, code: str = "TT_COMMON_50301", status: int = 503):
        super().__init__(code, message, status)


# ── SMS Provider ─────────────────────────────────────────────


class SmsProvider(abc.ABC):
    @abc.abstractmethod
    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        """发送短信验证码。返回 True 表示投递成功，失败抛出 ProviderError。"""
        pass


class MockSmsProvider(SmsProvider):
    """测试/开发用内存短信服务商。记录发送历史供测试断言。"""

    def __init__(self):
        self.sent_messages: list[dict[str, Any]] = []
        self.should_fail: bool = False

    def clear(self):
        self.sent_messages.clear()
        self.should_fail = False

    def get_last_code(self, phone: str) -> str | None:
        for msg in reversed(self.sent_messages):
            if msg["phone"] == phone:
                return msg["code"]
        return None

    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        if self.should_fail:
            raise ProviderError("模拟短信网关发送失败")
        self.sent_messages.append(
            {
                "phone": phone,
                "code": code,
                "purpose": purpose,
                "expires_in_seconds": expires_in_seconds,
                "sent_at": time.time(),
            }
        )
        logger.info("[MockSmsProvider] 发送验证码至 %s: %s (purpose=%s)", phone, code, purpose)
        return True


class TencentSmsProvider(SmsProvider):
    """腾讯云短信发送适配器（TC3-HMAC-SHA256 签名，stdlib 实现，零第三方库依赖）。"""

    def __init__(
        self,
        secret_id: str,
        secret_key: str,
        sdk_app_id: str,
        sign_name: str,
        template_id: str,
        timeout: int = 5,
    ):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.sdk_app_id = sdk_app_id
        self.sign_name = sign_name
        self.template_id = template_id
        self.timeout = timeout
        if not (self.secret_id and self.secret_key and self.sdk_app_id and self.sign_name):
            raise ProviderError("腾讯云短信配置不完整，缺少密钥或签名配置")

    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        # 手机号规范化为 E.164 格式（大陆加 +86）
        formatted_phone = phone if phone.startswith("+") else f"+86{phone}"
        minutes = max(1, expires_in_seconds // 60)
        payload = {
            "PhoneNumberSet": [formatted_phone],
            "SmsSdkAppId": self.sdk_app_id,
            "SignName": self.sign_name,
            "TemplateId": self.template_id,
            "TemplateParamSet": [code, str(minutes)],
        }
        try:
            resp = self._tc3_request("sms.tencentcloudapi.com", "sms", "SendSms", "2021-01-11", payload)
            status_list = resp.get("Response", {}).get("SendStatusSet", [])
            if not status_list or status_list[0].get("Code") != "Ok":
                err_msg = status_list[0].get("Message") if status_list else "未知错误"
                logger.error("腾讯云短信发送失败: %s", err_msg)
                raise ProviderError(f"短信发送失败: {err_msg}")
            return True
        except ProviderError:
            raise
        except Exception as e:
            logger.error("腾讯云短信接口请求异常: %s", e)
            raise ProviderError("短信服务暂时不可用，请稍后重试") from None

    def _tc3_request(self, host: str, service: str, action: str, version: str, payload: dict) -> dict:
        canonical_uri = "/"
        canonical_querystring = ""
        canonical_headers = f"content-type:application/json; charset=utf-8\nhost:{host}\nx-tc-action:{action.lower()}\n"
        signed_headers = "content-type;host;x-tc-action"
        payload_bytes = json.dumps(payload).encode("utf-8")
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
            "Host": host,
            "Authorization": authorization,
            "X-TC-Action": action,
            "X-TC-Timestamp": str(timestamp),
            "X-TC-Version": version,
        }

        req = urllib.request.Request(f"https://{host}", data=payload_bytes, headers=headers, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


class SendCloudSmsProvider(SmsProvider):
    """SendCloud 短信发送适配器（SHA256 签名，stdlib 实现，零第三方库依赖）。"""

    API_URL = "https://api.sendcloud.net/smsapi/send"

    def __init__(
        self,
        sms_user: str,
        sms_key: str,
        template_id: int | str,
        timeout: int = 5,
    ):
        self.sms_user = str(sms_user or "").strip()
        self.sms_key = str(sms_key or "").strip()
        self.template_id = str(template_id or "").strip()
        self.timeout = timeout
        if not (self.sms_user and self.sms_key):
            raise ProviderError("SendCloud 短信配置不完整，缺少 SMS_USER 或 SMS_KEY")
        if not self.template_id:
            raise ProviderError("SendCloud 短信配置不完整，缺少 SENDCLOUD_SMS_TEMPLATE_ID")

    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        clean_phone = phone.replace("+86", "").replace("-", "").strip()
        minutes = max(1, expires_in_seconds // 60)
        vars_payload = json.dumps({"%code%": code, "%time%": str(minutes), "code": code})
        payload = {
            "smsUser": self.sms_user,
            "templateId": self.template_id,
            "phone": clean_phone,
            "vars": vars_payload,
        }
        sorted_keys = sorted(payload.keys())
        param_str = "&".join(f"{key}={payload[key]}" for key in sorted_keys)
        sign_str = f"{self.sms_key}&{param_str}&{self.sms_key}"
        signature = hashlib.sha256(sign_str.encode("utf-8")).hexdigest()
        payload["signature"] = signature

        try:
            data_bytes = urllib.parse.urlencode(payload).encode("utf-8")
            req = urllib.request.Request(
                self.API_URL,
                data=data_bytes,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
            if not resp_data.get("result") or resp_data.get("statusCode") != 200:
                err_msg = resp_data.get("message") or "未知错误"
                logger.error("SendCloud 短信发送失败: %s (resp=%s)", err_msg, resp_data)
                raise ProviderError(f"短信发送失败: {err_msg}")
            return True
        except ProviderError:
            raise
        except Exception as e:
            logger.error("SendCloud 短信接口请求异常: %s", e)
            raise ProviderError("短信服务暂时不可用，请稍后重试") from None


# ── Email Provider ───────────────────────────────────────────


class EmailProvider(abc.ABC):
    @abc.abstractmethod
    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        """发送邮件验证码。"""
        pass

    @abc.abstractmethod
    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300) -> bool:
        """发送一次性密码重置链接。"""
        pass


class MockEmailProvider(EmailProvider):
    """测试/开发用内存邮件服务商。"""

    def __init__(self):
        self.sent_emails: list[dict[str, Any]] = []
        self.should_fail: bool = False

    def clear(self):
        self.sent_emails.clear()
        self.should_fail = False

    def get_last_code(self, email: str) -> str | None:
        for item in reversed(self.sent_emails):
            if item["email"] == email and "code" in item:
                return item["code"]
        return None

    def get_last_link(self, email: str) -> str | None:
        for item in reversed(self.sent_emails):
            if item["email"] == email and "reset_url" in item:
                return item["reset_url"]
        return None

    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        if self.should_fail:
            raise ProviderError("模拟邮件服务发送失败")
        self.sent_emails.append(
            {
                "email": email,
                "code": code,
                "purpose": purpose,
                "type": "code",
                "expires_in_seconds": expires_in_seconds,
                "sent_at": time.time(),
            }
        )
        logger.info("[MockEmailProvider] 发送验证码至 %s: %s", email, code)
        return True

    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300) -> bool:
        if self.should_fail:
            raise ProviderError("模拟邮件服务发送失败")
        self.sent_emails.append(
            {
                "email": email,
                "reset_url": reset_url,
                "type": "link",
                "expires_in_seconds": expires_in_seconds,
                "sent_at": time.time(),
            }
        )
        logger.info("[MockEmailProvider] 发送重置链接至 %s: %s", email, reset_url)
        return True


class SmtpEmailProvider(EmailProvider):
    """基于标准 SMTP 发送邮件。"""

    def __init__(
        self,
        host: str,
        port: int,
        user: str,
        password: str,
        use_ssl: bool = True,
        timeout: int = 10,
    ):
        self.host = host
        self.port = port
        self.user = user
        self.password = password
        self.use_ssl = use_ssl
        self.timeout = timeout

    def _send(self, to_email: str, subject: str, html_content: str):
        msg = MIMEMultipart("alternative")
        msg["Subject"] = Header(subject, "utf-8")
        msg["From"] = Header(f"南山科转通 <{self.user}>", "utf-8")
        msg["To"] = Header(to_email, "utf-8")
        msg.attach(MIMEText(html_content, "html", "utf-8"))

        try:
            if self.use_ssl:
                server = smtplib.SMTP_SSL(self.host, self.port, timeout=self.timeout)
            else:
                server = smtplib.SMTP(self.host, self.port, timeout=self.timeout)
                server.starttls()
            with server:
                if self.user and self.password:
                    server.login(self.user, self.password)
                server.sendmail(self.user, [to_email], msg.as_string())
            return True
        except Exception as e:
            logger.error("SMTP 发送邮件失败: %s", e)
            raise ProviderError("邮件发送失败，请稍后重试") from None

    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        minutes = max(1, expires_in_seconds // 60)
        subject = "【南山科转通】身份安全验证码"
        html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2>南山科转通 · 身份验证</h2>
            <p>您好，您正在进行身份验证操作，验证码为：</p>
            <p style="font-size: 24px; font-weight: bold; color: #0256FF; letter-spacing: 4px;">{code}</p>
            <p style="color: #666; font-size: 13px;">该验证码 {minutes} 分钟内有效。如非本人操作，请忽略此邮件。</p>
        </div>
        """
        return self._send(email, subject, html)

    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300) -> bool:
        minutes = max(1, expires_in_seconds // 60)
        subject = "【南山科转通】密码找回与重置"
        html = f"""
        <div style="font-family: Arial, sans-serif; padding: 20px; color: #333;">
            <h2>南山科转通 · 密码重置</h2>
            <p>您好，您申请了重置南山科转通账号密码。请点击下方链接完成设置：</p>
            <p><a href="{reset_url}" style="display: inline-block; padding: 10px 20px; background: #0256FF; color: #fff; text-decoration: none; border-radius: 4px;">立即重置密码</a></p>
            <p style="color: #888; font-size: 12px;">若按钮无法点击，请复制以下链接到浏览器地址栏打开：<br>{reset_url}</p>
            <p style="color: #666; font-size: 13px;">该链接 {minutes} 分钟内有效且仅可使用一次。如非本人操作，请尽快登录检查账号安全。</p>
        </div>
        """
        return self._send(email, subject, html)


class TencentSesProvider(EmailProvider):
    """腾讯云 SES 邮件推送服务商（TC3-HMAC-SHA256 签名）。"""

    def __init__(self, secret_id: str, secret_key: str, from_email: str, timeout: int = 5):
        self.secret_id = secret_id
        self.secret_key = secret_key
        self.from_email = from_email
        self.timeout = timeout
        if not (self.secret_id and self.secret_key and self.from_email):
            raise ProviderError("腾讯云 SES 配置不完整")

    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        minutes = max(1, expires_in_seconds // 60)
        subject = "【南山科转通】身份安全验证码"
        html = f"<p>您的南山科转通安全验证码为 <b>{code}</b>，{minutes}分钟内有效。</p>"
        return self._send_ses(email, subject, html)

    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300) -> bool:
        minutes = max(1, expires_in_seconds // 60)
        subject = "【南山科转通】密码重置链接"
        html = f'<p>请点击以下链接完成密码重置（{minutes}分钟内有效）：<a href="{reset_url}">{reset_url}</a></p>'
        return self._send_ses(email, subject, html)

    def _send_ses(self, to_email: str, subject: str, html_content: str) -> bool:
        payload = {
            "FromEmailAddress": self.from_email,
            "Destination": [to_email],
            "Subject": subject,
            "Simple": {"Html": html_content},
        }
        # 复用 Tencent TC3 签名请求
        helper = TencentSmsProvider(
            secret_id=self.secret_id,
            secret_key=self.secret_key,
            sdk_app_id="dummy",
            sign_name="dummy",
            template_id="dummy",
        )
        try:
            resp = helper._tc3_request("ses.tencentcloudapi.com", "ses", "SendEmail", "2020-10-02", payload)
            if "Response" in resp and "MessageId" in resp["Response"]:
                return True
            raise ProviderError(f"SES 邮件发送响应异常: {resp}")
        except ProviderError:
            raise
        except Exception as e:
            logger.error("腾讯云 SES 发送失败: %s", e)
            raise ProviderError("邮件服务暂时不可用，请稍后重试") from None


# ── Provider 单例工厂 ─────────────────────────────────────────

_sms_provider_instance: SmsProvider | None = None
_email_provider_instance: EmailProvider | None = None


def get_sms_provider() -> SmsProvider:
    global _sms_provider_instance
    if _sms_provider_instance is not None:
        return _sms_provider_instance

    if not settings.SMS_ENABLED and settings.SMS_PROVIDER != "mock":
        raise ProviderError("短信找回功能暂未开放")

    provider_type = (settings.SMS_PROVIDER or "mock").lower()
    if provider_type == "sendcloud":
        _sms_provider_instance = SendCloudSmsProvider(
            sms_user=settings.SENDCLOUD_SMS_USER or settings.SMS_USER,
            sms_key=settings.SENDCLOUD_SMS_KEY or settings.SMS_KEY,
            template_id=settings.SENDCLOUD_SMS_TEMPLATE_ID,
        )
    elif provider_type == "tencent":
        _sms_provider_instance = TencentSmsProvider(
            secret_id=settings.TENCENT_SMS_SECRET_ID,
            secret_key=settings.TENCENT_SMS_SECRET_KEY,
            sdk_app_id=settings.TENCENT_SMS_SDK_APP_ID,
            sign_name=settings.TENCENT_SMS_SIGN_NAME,
            template_id=settings.TENCENT_SMS_TEMPLATE_ID,
        )
    else:
        _sms_provider_instance = MockSmsProvider()

    return _sms_provider_instance


def get_email_provider() -> EmailProvider:
    global _email_provider_instance
    if _email_provider_instance is not None:
        return _email_provider_instance

    if not settings.EMAIL_ENABLED and settings.EMAIL_PROVIDER != "mock":
        raise ProviderError("邮箱找回功能暂未开放")

    provider_type = (settings.EMAIL_PROVIDER or "mock").lower()
    if provider_type == "tencent":
        _email_provider_instance = TencentSesProvider(
            secret_id=settings.TENCENT_SES_SECRET_ID,
            secret_key=settings.TENCENT_SES_SECRET_KEY,
            from_email=settings.TENCENT_SES_FROM_EMAIL,
        )
    elif provider_type == "smtp":
        _email_provider_instance = SmtpEmailProvider(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_ssl=settings.SMTP_USE_SSL,
        )
    else:
        _email_provider_instance = MockEmailProvider()

    return _email_provider_instance


def reset_providers_for_test(sms: SmsProvider | None = None, email: EmailProvider | None = None):
    """测试用注入/重置 Provider。"""
    global _sms_provider_instance, _email_provider_instance
    _sms_provider_instance = sms
    _email_provider_instance = email
