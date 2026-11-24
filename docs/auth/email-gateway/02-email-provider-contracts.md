# Email Provider 注册机制、协议适配器与模板安全规范 (02-email-provider-contracts)

## 1. 严格 Provider 注册校验链 (`get_email_provider`)

`modules/security/provider.py::get_email_provider()` 彻底移除了未知配置或初始化异常静默回退到 `MockEmailProvider` 的风险，严格按以下不可越过顺序执行校验：

1. **运行环境校验（最高优先级）**：若 `settings.is_production_like`（`staging` / `production`），只要配置了 `mock`、当前缓存实例属于 `MockEmailProvider` 或存在 `_email_provider_injected` 测试注入标记，立即抛出 `ProviderError(..., reason_code="CONFIG_ERROR")`。
2. **`EMAIL_ENABLED` 功能开关校验**：若 `settings.EMAIL_ENABLED` 为 `False`，即使此前已缓存真实 Provider 实例或非生产注入实例，均立即拒绝并抛出 `ProviderError(..., reason_code="CHANNEL_DISABLED")`。
3. **显式非生产测试注入边界**：仅当 `not settings.is_production_like` 且通过 `reset_providers_for_test(email=...)` 显式注入时，返回测试双份实例。
4. **Provider 白名单校验**：`EMAIL_PROVIDER` 仅允许 `{"mock", "smtp", "tencent"}`。未知名称（包括旧文档错误提及的 `tencent_ses` / `sendgrid`）直接失败，绝不回退 `mock`；`mock` 仅允许 `APP_ENV in {"local", "development"}`。
5. **配置指纹缓存校验**：根据当前 `EMAIL_PROVIDER` 与关键连接字段计算 `_email_config_fingerprint()`，任何配置变更自动使旧缓存失效并重建实例。
6. **配置完整性校验与初始化**：若 `smtp` 或 `tencent` 缺少必要参数或参数格式非法，立即抛出 `ProviderError(..., reason_code="CONFIG_ERROR")`。

---

## 2. 结构化投递结果与能力模型

所有邮件服务商实现 `modules/security/email_providers.py::EmailProvider`，向网关输出：

- **`DeliveryReceipt`**（`modules/security/delivery_models.py`）：
  - `accepted: bool` — **仅代表服务商已受理投递请求，不代表用户邮箱已最终送达（Delivered）**；
  - `provider: str` — 服务商标识（`smtp` / `tencent` / `mock`）；
  - `channel: str` — 投递渠道（`email_otp` / `email_link` / `email_notification`）；
  - `request_id: str` — 关联服务端发送请求 / 腾讯云 `RequestId`；
  - `provider_message_ids: tuple[str, ...]` — SMTP 构造并追踪的 RFC 5322 `Message-ID` 或 SES 返回的 `MessageId`。
- **`DeliveryProviderError` (`ProviderError`)**：
  - `reason_code: str` — 标准化分类错误码（例如 `SMTP_AUTH_FAILED`、`SMTP_TLS_FAILED`、`SMTP_TEMPORARY_FAILURE`、`SMTP_RECIPIENT_REJECTED`、`SES_SIGNATURE_ERROR`、`PROVIDER_OUTCOME_UNKNOWN`）；
  - `retryable: bool` — 是否允许有界重试；
  - `outcome_unknown: bool` — 结果未知标记（`True` 时严禁自动重试或重建新验证码）；
  - `request_attempted: bool` — 是否已尝试向上游发出网络请求；
  - `provider_status: int | None` — 上游 HTTP/SMTP 数字响应码。
- **`ProviderCapabilities`**：显式声明各渠道及异步能力：
  - `SmtpEmailProvider`: `send_otp=True`, `send_reset_link=True`, `provider_message_id=True`, `idempotency=False`, `delivery_status_query=False`, `delivery_webhook=False`。
  - `TencentSesProvider`: `send_otp=True`, `send_reset_link=True`, `provider_message_id=True`, `idempotency=False`, `delivery_status_query=True`, `delivery_webhook=True`。

---

## 3. SMTP 服务商加固 (`SmtpEmailProvider`)

1. **TLS/SSL 证书强制校验**：`build_strict_ssl_context()` 创建 `ssl.create_default_context()`，显式固定 `check_hostname = True`、`verify_mode = ssl.CERT_REQUIRED` 及 `minimum_version = ssl.TLSv1_2`。非 465 SSL 端口模式先 `ehlo()` 再执行 `starttls(context=self.ssl_context)` 与二次 `ehlo()`，无法协商 TLS 的服务端直接失败。
2. **头注入与地址安全检查**：对 `from_name`、`from_email`、`to_email`、`Subject` 及 `send_request_id` 执行 `_assert_no_header_injection()`，拒绝任何 `\r`、`\n` 及 ASCII 控制字符（`0x00–0x1f`, `0x7f`）；支持发件身份 `SMTP_FROM_EMAIL` 与 SMTP 认证账号 `SMTP_USER` 分离。
3. **阶段感知错误分类与 `DATA` 保守语义**：
   - 将传输过程划分为 `connect` -> `tls` -> `auth` -> `data` 阶段；
   - `SMTP 4xx` 归类 `SMTP_TEMPORARY_FAILURE` (`retryable=True`)，最多在 `max_attempts`（1–3）有界退避重试；
   - `534/535` 归类 `SMTP_AUTH_FAILED`，收件拒绝归类 `SMTP_RECIPIENT_REJECTED`，`5xx` 归类 `SMTP_PERMANENT_FAILURE`（均 `retryable=False`）；
   - **若 `phase == "data"` 时发生 `SMTPServerDisconnected` / `TimeoutError` / `OSError`**，因为 SMTP 协议本身未提供幂等投递承诺（`Message-ID` 仅为链路追踪标识），立即抛出 `PROVIDER_OUTCOME_UNKNOWN` (`outcome_unknown=True, retryable=False`)，绝不重试！
4. **能力查询声明**：`query_status()` 显式抛出 `reason_code="unsupported_capability"`。

---

## 4. 腾讯云 SES 服务商加固 (`TencentSesProvider`)

1. **官方 `SendEmail` (2020-10-02) 规范对齐**：
   - 请求头固定包含 `X-TC-Action: SendEmail`、`X-TC-Version: 2020-10-02` 及必填区域头 `X-TC-Region`（默认 `ap-hongkong`，校验正则 `^[a-z]{2}-[a-z0-9-]+$`）；
   - 使用零第三方 SDK 依赖的独立 `TC3-HMAC-SHA256` 签名器；
   - 发送文本/网页正文采用 UTF-8 编码后的 Base64 字符串封装于 `Simple.Html` 与 `Simple.Text`，固定 `TriggerType: 1`（触发类事务邮件）；若配置了 `TENCENT_SES_TEMPLATE_ID_OTP` / `TENCENT_SES_TEMPLATE_ID_RESET` 则切换 `Template` 传参模式。
2. **响应与错误码严格映射**：
   - `AuthFailure.Signature*` / `InvalidSecretId` / `SecretIdNotFound` -> `SES_SIGNATURE_ERROR`；
   - `AuthFailure.*` / `UnauthorizedOperation*` / `FailedOperation.NotAuthenticatedSender` -> `SES_PERMISSION_ERROR`；
   - `LimitExceeded*` / `FailedOperation.ExceedSendLimit` / `InsufficientQuota` / `FrequencyLimit` -> `SES_QUOTA_EXCEEDED`；
   - `InternalError*`、HTTP 5xx、网络超时、非法 JSON 或缺失 `Response.MessageId` -> `outcome_unknown=True` (`PROVIDER_OUTCOME_UNKNOWN` / `SES_INVALID_RESPONSE`)；
   - 日志仅输出 `action`、数字状态码和错误代码，严禁记录 `SecretKey`、明文邮箱、验证码或上游未脱敏响应体。
3. **投递状态查询 (`GetSendEmailStatus`)**：实现 `query_status(provider_ids, request_date=...)` 供内部运维 `reconcile` 工具核对 `SendStatus`（`0=delivered`, `2=bounced`, `3/4=delivery_failed`）。

---

## 5. 邮件模板与 Mock 隐私红线

- **品牌化 HTML + 纯文本模板**：`render_otp_email()`、`render_password_recovery_link_email()`、`render_security_notification_email()` 对全部动态占位符执行 `html.escape(..., quote=True)`；Subject 仅描述操作类型，绝不泄露 6 位验证码；模板正文不含 `<script>` 或外链追踪像素。
- **`MockEmailProvider` 隐私约束**：仅在内存列表保留测试记录供自动化断言，日志输出中绝不打印明文收件地址、验证码或重置链接。
