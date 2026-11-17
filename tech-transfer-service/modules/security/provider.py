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
import random
import re
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from config import settings
from core.contact_validation import is_valid_phone
from core.errors import BizError

logger = logging.getLogger("nanshan.security.provider")


class ProviderError(BizError):
    def __init__(
        self, message: str, code: str = "TT_COMMON_50301", status: int = 503, *, outcome_unknown: bool = False
    ):
        super().__init__(code, message, status)
        self.outcome_unknown = outcome_unknown


@dataclass(frozen=True)
class SmsReceipt:
    accepted: bool
    provider_ids: tuple[str, ...]
    request_id: str


# ── SMS Provider ─────────────────────────────────────────────


class SmsProvider(abc.ABC):
    @abc.abstractmethod
    def send_code(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None
    ) -> bool:
        """发送短信验证码。返回 True 表示服务商接受请求（不代表最终送达），失败抛出 ProviderError。"""
        pass

    def send_task(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, send_request_id: str
    ) -> SmsReceipt:
        accepted = self.send_code(phone, code, purpose, expires_in_seconds)
        return SmsReceipt(bool(accepted), (), send_request_id)


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

    def send_code(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None
    ) -> bool:
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
        logger.info("[MockSmsProvider] 验证码已记录 (purpose=%s)", purpose)
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

    def send_code(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None
    ) -> bool:
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


def sign_sendcloud_params(params: dict[str, Any], sms_key: str) -> str:
    """Sign raw values before form encoding; never include credentials in params."""
    raw = "&".join(f"{key}={params[key]}" for key in sorted(params) if key not in {"signature", "smsKey"})
    return hashlib.sha256(f"{sms_key}&{raw}&{sms_key}".encode()).hexdigest()


class SendCloudSmsProvider(SmsProvider):
    """SendCloud 短信发送适配器（SHA256 签名，stdlib 实现，零第三方库依赖）。"""

    API_URL = "https://api.sendcloud.net/smsapi/send"
    STATUS_URL = "https://api.sendcloud.net/smsapi/status/query"

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
        self.max_attempts = min(3, max(1, int(getattr(settings, "SENDCLOUD_SMS_MAX_ATTEMPTS", 3))))
        if not (self.sms_user and self.sms_key):
            raise ProviderError("SendCloud 短信配置不完整，缺少 SMS_USER 或 SMS_KEY")
        if not self.template_id:
            raise ProviderError("SendCloud 短信配置不完整，缺少 SENDCLOUD_SMS_TEMPLATE_ID")

    def send_code(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None
    ) -> bool:
        self.send_task(
            phone,
            code,
            purpose,
            expires_in_seconds,
            send_request_id=str(uuid.uuid4()) if request_id is None else request_id,
        )
        return True

    def send_task(
        self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, send_request_id: str
    ) -> SmsReceipt:
        if purpose not in {"password_recovery", "reset_password", "bind_phone"}:
            raise ProviderError("不支持的短信用途")
        if (
            not isinstance(send_request_id, str)
            or not 1 <= len(send_request_id) <= 128
            or any(ord(c) < 32 or ord(c) == 127 for c in send_request_id)
        ):
            raise ProviderError("短信请求 ID 格式错误")
        if not isinstance(phone, str) or any(ord(c) < 32 or ord(c) == 127 for c in phone):
            raise ProviderError("手机号格式错误")
        clean_phone = phone.strip()
        if clean_phone.startswith("+86"):
            clean_phone = clean_phone[3:]
        if (
            not is_valid_phone(clean_phone)
            or not clean_phone.isascii()
            or not clean_phone.startswith(tuple("1" + str(i) for i in range(3, 10)))
        ):
            raise ProviderError("仅支持中国大陆手机号")
        if not isinstance(code, str) or re.fullmatch(r"[0-9]{6}", code) is None:
            raise ProviderError("验证码须为六位数字字符串")
        if type(expires_in_seconds) is not int or not 1 <= expires_in_seconds <= 3600:
            raise ProviderError("验证码有效期须为 1 至 3600 秒的整数")
        # Template 942819 has a fixed five-minute message and only %code%.
        # Challenge Service remains authoritative for actual expiration.
        vars_payload = json.dumps({"%code%": code}, ensure_ascii=False, separators=(",", ":"))
        payload = {
            "smsUser": self.sms_user,
            "templateId": self.template_id,
            "phone": clean_phone,
            "vars": vars_payload,
            "sendRequestId": send_request_id,
        }
        payload["signature"] = sign_sendcloud_params(payload, self.sms_key)

        for attempt in range(self.max_attempts):
            phase = "connect"
            try:
                data_bytes = urllib.parse.urlencode(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.API_URL,
                    data=data_bytes,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    phase = "read"
                    raw_response = resp.read()
                try:
                    resp_data = json.loads(raw_response.decode("utf-8"))
                except (ValueError, UnicodeError):
                    self._send_error("invalid_json", unknown=True)
                if (
                    not isinstance(resp_data, dict)
                    or type(resp_data.get("result")) is not bool
                    or type(resp_data.get("statusCode")) is not int
                ):
                    self._send_error("invalid_structure", unknown=True)
                if resp_data["result"] is not True or resp_data["statusCode"] != 200:
                    status = resp_data["statusCode"]
                    category = (
                        "signature"
                        if status in {421, 422, 4722}
                        else "template"
                        if status in set(range(431, 444))
                        else "quota"
                        if status == 499
                        else "business"
                    )
                    self._send_error(category, status=status, unknown=status == 400)
                if not isinstance(resp_data.get("info", {}), dict):
                    self._send_error("invalid_structure", unknown=True)
                ids = resp_data.get("info", {}).get("smsIds", [])
                if isinstance(ids, str):
                    ids = [ids]
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    self._send_error("invalid_structure", unknown=True)
                return SmsReceipt(True, tuple(ids), send_request_id)
            except ProviderError:
                raise
            except urllib.error.HTTPError as exc:
                self._send_error(
                    "http_4xx" if 400 <= exc.code < 500 else "http_5xx", status=exc.code, unknown=exc.code >= 500
                )
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
                category = phase + "_timeout" if timed_out else "connection"
                logger.warning("SendCloud transport error", extra={"error_type": category, "outcome_unknown": True})
                if attempt + 1 == self.max_attempts:
                    raise ProviderError("短信发送状态待核对，请勿重复发起", outcome_unknown=True) from None
                time.sleep(min(0.25 * (2**attempt) + random.random() * 0.1, 1.0))
        raise ProviderError("短信发送状态待核对，请勿重复发起", outcome_unknown=True)

    @staticmethod
    def _send_error(category: str, *, status: int | None = None, unknown: bool = False):
        logger.warning(
            "SendCloud request error",
            extra={"error_type": category, "provider_status": status, "outcome_unknown": unknown},
        )
        raise ProviderError(
            "短信发送状态待核对，请勿重复发起" if unknown else "短信服务暂时不可用，请稍后重试", outcome_unknown=unknown
        ) from None

    def query_status(
        self, provider_ids: list[str], *, days: int = 1, start: int = 0, limit: int = 100
    ) -> dict[str, Any]:
        """Internal SendCloud status query; callers must keep this off public endpoints."""
        if not provider_ids or any(not str(item) for item in provider_ids):
            raise ProviderError("缺少服务商短信 ID")
        payload: dict[str, Any] = {
            "smsUser": self.sms_user,
            "smsIds": ";".join(map(str, provider_ids)),
            "days": str(days),
            "start": str(start),
            "limit": str(limit),
        }
        keys = sorted(payload)
        sign = f"{self.sms_key}&" + "&".join(f"{key}={payload[key]}" for key in keys) + f"&{self.sms_key}"
        payload["signature"] = hashlib.sha256(sign.encode()).hexdigest()
        req = urllib.request.Request(
            self.STATUS_URL,
            data=urllib.parse.urlencode(payload).encode(),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = json.loads(resp.read().decode())
            if not body.get("result") or body.get("statusCode") != 200:
                raise ProviderError("短信状态查询失败", outcome_unknown=False)
            info = body.get("info", {})
            return {"accepted": True, "records": info.get("voList", []) if isinstance(info, dict) else []}
        except ProviderError:
            raise
        except Exception:
            raise ProviderError("短信状态暂时不可用", outcome_unknown=True) from None


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

_sms_provider_injected = False
_sms_provider_instance: SmsProvider | None = None
_email_provider_instance: EmailProvider | None = None


def get_sms_provider() -> SmsProvider:
    global _sms_provider_instance
    provider_type = (settings.SMS_PROVIDER or "").lower()
    # Explicit dependency injection is allowed only outside production-like environments.
    if settings.is_production_like and (provider_type == "mock" or isinstance(_sms_provider_instance, MockSmsProvider)):
        raise ProviderError("生产环境禁止使用模拟短信服务")
    if not settings.is_production_like and _sms_provider_injected and _sms_provider_instance is not None:
        return _sms_provider_instance
    if not settings.SMS_ENABLED:
        raise ProviderError("短信找回功能暂未开放")
    if _sms_provider_instance is not None:
        return _sms_provider_instance

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
    elif provider_type == "mock" and settings.APP_ENV in {"local", "development"}:
        _sms_provider_instance = MockSmsProvider()
    else:
        raise ProviderError("短信服务商配置无效")

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
    global _sms_provider_instance, _email_provider_instance, _sms_provider_injected
    _sms_provider_injected = sms is not None
    _sms_provider_instance = sms
    _email_provider_instance = email
