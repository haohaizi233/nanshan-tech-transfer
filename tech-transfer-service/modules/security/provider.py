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
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from typing import Any

from config import settings
from core.contact_validation import is_valid_phone
from modules.security.delivery_models import (
    DeliveryProviderError,
    DeliveryReceipt,
    ProviderCapabilities,
    ProviderError,
)
from modules.security.email_providers import (
    EmailProvider,
    MockEmailProvider,
    SmtpEmailProvider,
    TencentSesProvider,
)

logger = logging.getLogger("nanshan.security.provider")


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
                return str(msg["code"])
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

    def _tc3_request(self, host: str, service: str, action: str, version: str, payload: dict) -> dict[str, Any]:
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
            data = json.loads(resp.read().decode("utf-8"))
            return dict(data) if isinstance(data, dict) else {}


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
            raise ProviderError("SendCloud 短信配置不完整，缺少 SMS_USER 或 SMS_KEY", reason_code="config_error")
        if not self.template_id:
            raise ProviderError("SendCloud 短信配置不完整，缺少 SENDCLOUD_SMS_TEMPLATE_ID", reason_code="config_error")

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
                    self._send_error("invalid_response", unknown=True, attempted=True)
                if (
                    not isinstance(resp_data, dict)
                    or type(resp_data.get("result")) is not bool
                    or type(resp_data.get("statusCode")) is not int
                ):
                    self._send_error("invalid_response", unknown=True, attempted=True)
                if resp_data["result"] is not True or resp_data["statusCode"] != 200:
                    status = resp_data["statusCode"]
                    category = self._classify_status(status)
                    self._send_error(
                        category,
                        status=status,
                        unknown=status in {311, 400},
                        attempted=True,
                        retryable=status in {501, 502},
                    )
                if not isinstance(resp_data.get("info", {}), dict):
                    self._send_error("invalid_response", unknown=True, attempted=True)
                ids = resp_data.get("info", {}).get("smsIds", [])
                if isinstance(ids, str):
                    ids = [ids]
                if not isinstance(ids, list) or any(not isinstance(item, str) for item in ids):
                    self._send_error("invalid_response", unknown=True, attempted=True)
                return SmsReceipt(True, tuple(ids), send_request_id)
            except ProviderError:
                raise
            except urllib.error.HTTPError as exc:
                self._send_error(
                    "http_5xx" if exc.code >= 500 else "http_4xx",
                    status=exc.code,
                    unknown=exc.code >= 500,
                    attempted=True,
                    retryable=exc.code >= 500,
                )
            except (TimeoutError, urllib.error.URLError, OSError) as exc:
                timed_out = isinstance(exc, TimeoutError) or isinstance(getattr(exc, "reason", None), TimeoutError)
                category = phase + "_timeout" if timed_out else "connection"
                logger.warning("SendCloud transport error", extra={"error_type": category, "outcome_unknown": True})
                if attempt + 1 == self.max_attempts:
                    raise ProviderError(
                        "短信发送状态待核对，请勿重复发起",
                        outcome_unknown=True,
                        reason_code="network_timeout" if timed_out else "network_error",
                        retryable=False,
                        request_attempted=True,
                    ) from None
                time.sleep(min(0.25 * (2**attempt) + random.random() * 0.1, 1.0))
        raise ProviderError("短信发送状态待核对，请勿重复发起", outcome_unknown=True)

    @staticmethod
    def _classify_status(status: int) -> str:
        if status in {421, 422, 4722}:
            return "signature"
        if status == 432:
            return "template_not_approved"
        if status in {441, 442, 443}:
            return "invalid_parameters"
        if status in {*range(431, 441), 4340}:
            return "template"
        if status in {471, 472, 4721, 4723, 474}:
            return "config_error"
        if status in {473, 602}:
            return "permission"
        if status == 499:
            return "insufficient_balance"
        if status == 601:
            return "ip_restricted"
        if status == 400:
            return "duplicate_request"
        if status == 311:
            return "partial_acceptance"
        if status in {*range(401, 418), *range(451, 486), 491, 496, 497, 498}:
            return "invalid_parameters"
        return "provider_rejected"

    @staticmethod
    def _send_error(
        category: str,
        *,
        status: int | None = None,
        unknown: bool = False,
        attempted: bool = False,
        retryable: bool = False,
    ):
        allow = {
            "signature",
            "template_not_approved",
            "template",
            "permission",
            "insufficient_balance",
            "ip_restricted",
            "invalid_parameters",
            "provider_rejected",
            "duplicate_request",
            "partial_acceptance",
            "invalid_response",
            "network_timeout",
            "config_error",
            "http_4xx",
            "http_5xx",
        }
        reason = category if category in allow else "provider_rejected"
        logger.warning(
            "SendCloud request error",
            extra={"error_type": reason, "provider_status": status, "outcome_unknown": unknown},
        )
        raise ProviderError(
            "短信发送状态待核对，请勿重复发起" if unknown else "短信服务暂时不可用，请稍后重试",
            outcome_unknown=unknown,
            reason_code=reason,
            provider_status=status,
            retryable=retryable,
            request_attempted=attempted,
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


# ── Email Provider（定义于 modules/security/email_providers.py）──
# 保留模块导出兼容：EmailProvider, MockEmailProvider, SmtpEmailProvider,
# TencentSesProvider, DeliveryReceipt, ProviderCapabilities, DeliveryProviderError.


# ── Provider 单例工厂 ─────────────────────────────────────────

_ALLOWED_EMAIL_PROVIDERS = frozenset({"mock", "smtp", "tencent"})

_sms_provider_injected = False
_sms_provider_instance: SmsProvider | None = None
_email_provider_injected = False
_email_provider_instance: EmailProvider | None = None
_email_provider_fingerprint: tuple[Any, ...] | None = None


def _email_config_fingerprint(provider_type: str) -> tuple[Any, ...]:
    return (
        settings.APP_ENV,
        provider_type,
        settings.SMTP_HOST,
        settings.SMTP_PORT,
        settings.SMTP_USER,
        settings.SMTP_PASSWORD,
        settings.SMTP_FROM_EMAIL,
        settings.SMTP_FROM_NAME,
        settings.SMTP_USE_SSL,
        settings.SMTP_TIMEOUT_SECONDS,
        settings.SMTP_MAX_ATTEMPTS,
        settings.TENCENT_SES_SECRET_ID,
        settings.TENCENT_SES_SECRET_KEY,
        settings.TENCENT_SES_FROM_EMAIL,
        settings.TENCENT_SES_REGION,
        settings.TENCENT_SES_ENDPOINT,
        settings.TENCENT_SES_TIMEOUT_SECONDS,
        settings.TENCENT_SES_TEMPLATE_ID_OTP,
        settings.TENCENT_SES_TEMPLATE_ID_RESET,
    )


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
    """严格注册邮件服务商，绝不静默回退 Mock 或绕过 EMAIL_ENABLED。

    校验顺序：
    1. 运行环境校验（staging/production 禁止 Mock 或测试注入）
    2. EMAIL_ENABLED 开关校验（false 时即使已缓存也拒绝）
    3. 非生产测试注入边界校验
    4. Provider 白名单校验（mock / smtp / tencent）
    5. 配置完整性与缓存合法性校验
    6. 获取或初始化 Provider
    """
    global _email_provider_instance, _email_provider_fingerprint

    provider_type = (settings.EMAIL_PROVIDER or "").strip().lower()

    # 1. 运行环境校验（最高优先级：staging/production 严禁 Mock 或测试注入实例）
    if settings.is_production_like:
        if provider_type == "mock" or isinstance(_email_provider_instance, MockEmailProvider):
            raise ProviderError("生产环境禁止使用模拟邮件服务", reason_code="CONFIG_ERROR")
        if _email_provider_injected:
            raise ProviderError("生产环境禁止使用测试注入邮件服务", reason_code="CONFIG_ERROR")

    # 2. EMAIL_ENABLED 开关校验（防止已缓存实例或 mock 绕过开关）
    if not settings.EMAIL_ENABLED:
        raise ProviderError("邮箱安全验证功能暂未开放", reason_code="CHANNEL_DISABLED")

    # 3. 显式非生产测试注入边界
    if not settings.is_production_like and _email_provider_injected and _email_provider_instance is not None:
        return _email_provider_instance

    # 4. Provider 白名单校验（严禁未知名称静默回退 Mock）
    if provider_type not in _ALLOWED_EMAIL_PROVIDERS:
        raise ProviderError("邮件服务商配置无效", reason_code="CONFIG_ERROR")
    if provider_type == "mock" and settings.APP_ENV not in {"local", "development"}:
        raise ProviderError("非本地开发环境禁止使用模拟邮件服务", reason_code="CONFIG_ERROR")

    # 5. 缓存合法性校验（配置变化或 Mock 残留立即失效重建）
    fingerprint = _email_config_fingerprint(provider_type)
    if _email_provider_instance is not None and _email_provider_fingerprint == fingerprint:
        return _email_provider_instance

    # 6. 配置完整性校验与初始化（绝不捕获异常后静默回退 Mock）
    if provider_type == "tencent":
        instance: EmailProvider = TencentSesProvider(
            secret_id=settings.TENCENT_SES_SECRET_ID,
            secret_key=settings.TENCENT_SES_SECRET_KEY,
            from_email=settings.TENCENT_SES_FROM_EMAIL,
            region=settings.TENCENT_SES_REGION,
            endpoint=settings.TENCENT_SES_ENDPOINT,
            timeout=settings.TENCENT_SES_TIMEOUT_SECONDS,
            otp_template_id=settings.TENCENT_SES_TEMPLATE_ID_OTP,
            reset_template_id=settings.TENCENT_SES_TEMPLATE_ID_RESET,
        )
    elif provider_type == "smtp":
        instance = SmtpEmailProvider(
            host=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            user=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_ssl=settings.SMTP_USE_SSL,
            timeout=settings.SMTP_TIMEOUT_SECONDS,
            from_email=settings.SMTP_FROM_EMAIL,
            from_name=settings.SMTP_FROM_NAME,
            max_attempts=settings.SMTP_MAX_ATTEMPTS,
        )
    else:
        instance = MockEmailProvider()

    _email_provider_instance = instance
    _email_provider_fingerprint = fingerprint
    return _email_provider_instance


def reset_providers_for_test(sms: SmsProvider | None = None, email: EmailProvider | None = None):
    """测试用注入/重置 Provider。"""
    global _sms_provider_instance, _email_provider_instance, _sms_provider_injected
    global _email_provider_injected, _email_provider_fingerprint
    _sms_provider_injected = sms is not None
    _sms_provider_instance = sms
    _email_provider_injected = email is not None
    _email_provider_instance = email
    _email_provider_fingerprint = None


__all__ = [
    "DeliveryProviderError",
    "DeliveryReceipt",
    "EmailProvider",
    "MockEmailProvider",
    "MockSmsProvider",
    "ProviderCapabilities",
    "ProviderError",
    "SendCloudSmsProvider",
    "SmsProvider",
    "SmsReceipt",
    "SmtpEmailProvider",
    "TencentSesProvider",
    "TencentSmsProvider",
    "get_email_provider",
    "get_sms_provider",
    "reset_providers_for_test",
    "sign_sendcloud_params",
]
