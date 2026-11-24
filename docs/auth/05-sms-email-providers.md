# 南山科转通短信与邮件服务商接入规范 (05-sms-email-providers)

## 1. 架构定位与设计原则

- **业务与服务商强解耦**：业务代码（找回密码、绑定安全手机、安全邮箱确权）只依赖抽象接口 `SmsProvider` 与 `EmailProvider`，严禁直接在路由或业务模块中硬编码腾讯云或 SMTP 接口。
- **配置驱动与动态降级**：
  - 测试显式注入或本地 SMS_ENABLED=true 时可使用 `MockSmsProvider` / `MockEmailProvider`，在内存中追踪验证码和重置链接，绝不向真实用户派发。
  - 生产环境：支持 SendCloud / 腾讯云 SMS、腾讯云 SES 及标准 SMTP。
  - 缺少凭证时：通过 `SMS_ENABLED=false` / `EMAIL_ENABLED=false` 优雅降级并关闭对应找回入口，严禁暴露 Mock 入口至生产。
- **安全加固**：
  - 严禁在日志中打印未脱敏的 6 位数字验证码或 256 位重置 Token；
  - 签名算法采用零依赖的 Python 标准库实现腾讯云 TC3-HMAC-SHA256 签名，避免引入庞大的第三方 SDK。

---

## 2. 短信服务商 (SmsProvider)

### 2.1 接口契约
```python
class SmsProvider(abc.ABC):
    @abc.abstractmethod
    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None) -> bool:
        """发送短信验证码。True 仅表示服务商接受请求，不代表最终送达。"""
```

### 2.2 腾讯云短信 (TencentSmsProvider) 配置清单
- `SMS_ENABLED=true`
- `SMS_PROVIDER=tencent`
- `TENCENT_SMS_SECRET_ID`：腾讯云 API 访问密钥 ID
- `TENCENT_SMS_SECRET_KEY`：腾讯云 API 访问密钥 Key
- `TENCENT_SMS_SDK_APP_ID`：短信应用 SDK AppID
- `TENCENT_SMS_SIGN_NAME`：短信签名名称（需工信部与腾讯云报备审核通过，例如 `南山科转通`）
- `TENCENT_SMS_TEMPLATE_ID`：正文模板 ID（例如：`您的验证码为{1}，请在{2}分钟内完成操作`）

### 2.3 SendCloud 短信 (SendCloudSmsProvider) 配置清单
- `SMS_ENABLED=true`
- `SMS_PROVIDER=sendcloud`
- `SMS_USER` / `SENDCLOUD_SMS_USER`：SendCloud 短信发信账号（如 `nanshan`）
- `SMS_KEY` / `SENDCLOUD_SMS_KEY`：SendCloud API Key（通过 SHA256 签名校验，传输使用 HTTPS）
- `SENDCLOUD_SMS_TEMPLATE_ID`：SendCloud 审核通过的短信模板 ID（当前 `942819`，正文仅包含 `%code%`，有效期文案固定为 5 分钟）

---

## 3. 邮件服务商 (EmailProvider)

### 3.1 接口契约 (`EmailProvider`)
完整 Email Security Gateway 规范与结构化回执模型详见：[docs/auth/email-gateway/02-email-provider-contracts.md](./email-gateway/02-email-provider-contracts.md)。

```python
class EmailProvider(abc.ABC):
    provider_name: str = "base"
    capabilities: ProviderCapabilities

    @abc.abstractmethod
    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300, *, request_id: str | None = None) -> bool:
        """发送邮件 6 位 OTP 验证码。True 仅表示服务商受理请求，不代表最终送达。"""

    @abc.abstractmethod
    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300, *, request_id: str | None = None) -> bool:
        """发送一次性密码重置链接（URL Fragment）。"""

    def send_code_task(...) -> DeliveryReceipt: ...
    def send_reset_link_task(...) -> DeliveryReceipt: ...
    def send_notification_task(...) -> DeliveryReceipt: ...
    def query_status(...) -> dict[str, Any]: ...
```

### 3.2 支持的服务商实现与严格注册 (`get_email_provider()`)
`EMAIL_PROVIDER` 仅允许 `mock`（仅非生产环境）、`smtp`、`tencent`，任何未知名称、初始化异常或配置缺失**绝不静默回退 Mock**；`EMAIL_ENABLED=false` 时即使存在已缓存实例也强制拒绝发信：
1. **腾讯云 SES (`TencentSesProvider`)**：
   - `EMAIL_ENABLED=true`
   - `EMAIL_PROVIDER=tencent`
   - `TENCENT_SES_SECRET_ID` / `TENCENT_SES_SECRET_KEY`
   - `TENCENT_SES_FROM_EMAIL`：经过腾讯云验证的企业发信域名（如 `service@notice.nanshan-tech.com`）
   - `TENCENT_SES_REGION`（必填请求头 `X-TC-Region`，默认 `ap-hongkong`）、`TENCENT_SES_ENDPOINT=ses.tencentcloudapi.com`
   - 使用 `SendEmail` (2020-10-02) 与 `TC3-HMAC-SHA256` 签名；支持 `GetSendEmailStatus` 状态核对（需 `capabilities.delivery_status_query=True`）。
2. **标准 SMTP (`SmtpEmailProvider`)**：
   - `EMAIL_ENABLED=true`
   - `EMAIL_PROVIDER=smtp`
   - `SMTP_HOST`、`SMTP_PORT` (默认 465 SSL)、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_FROM_EMAIL`、`SMTP_USE_SSL=true`
   - 强制 TLS ≥ 1.2 + 证书/主机名校验、头注入阻断，且 `DATA` 提交后断连/超时标记 `PROVIDER_OUTCOME_UNKNOWN` 并禁止自动重发。

---

## 4. 异常处理与可重试机制

- 外部网络超时：Provider 默认设置 5 秒超时保护，超时后触发统一错误包装 `TT_COMMON_50301`，防止请求长阻塞耗尽 Gunicorn/Uvicorn 线程。
- 业务幂等与防重试风暴：业务层对每个联系方式设有 60 秒重发冷却期，同一目标 1 小时内限制 5 次，即便用户频繁点击也不会对服务商网关产生轰炸。


## 5. SendCloud 请求精确性与上线检查

使用审核通过的模板和 `/smsapi/send`，不使用免模板接口。用户提供的模板 942819 正文为：`【恒程创新知识产权】您的验证码为%code%，5分钟内有效，请勿泄露给他人。`。因此只传 `%code%`，不传 `%time%` 或冗余 `code`。此依据为用户提供的模板正文，尚未独立核查控制台审核状态。后续模板变更应经过受控变更和测试，不得追加同义字段。

`vars` 使用 `ensure_ascii=False, separators=(",", ":")` 确定性序列化，例如 `{"%code%":"001234"}`。验证码保持六位 ASCII 数字字符串，保留前导零。仅支持大陆手机号，可带单个 `+86` 前缀。有效期参数须为 1–3600 秒整数，拒绝布尔值；当前模板文案固定为 5 分钟，业务配置应使用 300 秒以保持一致。Provider 不会根据短信文案改写实际有效期，Challenge Service 决定真实失效时间。

完整参数（包括 `sendRequestId`）先按键升序排列，排除 `signature` 和 `smsKey`，连接为 `key=value&...`，构造 `SMS_KEY&参数串&SMS_KEY` 后取 UTF-8 SHA256 十六进制值。添加签名之后才 Form URL 编码。[官方签名协议](https://www.sendcloud.net/doc/sms/)。

`send_code` 保留四个位置参数，新增可选关键字 `request_id`；`send_task` 兼容现有网关的 `send_request_id`。同一逻辑任务必须复用 ID 和相同参数，新挑战使用新 ID。未传 ID 时仅为本次调用生成 UUID，不提供跨调用幂等保障。ID 长度 1–128 字符；服务商仅在一小时内对同 ID 去重，不能在一小时后盲目重放。现有网关传入挑战 ID，并保留未知状态防止创建替代 OTP。[官方参数说明](https://www.sendcloud.net/doc/sms/api/)。

网络失败/连接超时/读取超时分别记录安全分类，传输错误最多尝试 `SENDCLOUD_SMS_MAX_ATTEMPTS` 次（硬上限 3），全部尝试复用完全相同的请求。HTTP 4xx 视为拒绝，5xx 为结果未知；非法 JSON/响应结构也为结果未知且不重试。业务拒绝不自动重试；重复请求业务码 400 不能证明首次发送失败，按未知处理。签名错误 421/422/4722、模板错误 431–443、额度不足 499 分类记录。日志只含错误类型、数字状态码和未知状态标记，不记录密钥、验证码、手机号、请求 ID 或服务商响应正文。用户得到通用安全提示，超时不表示一定未发送。

工厂在 `SMS_ENABLED=false` 时拒绝发送；生产和 staging 禁止 Mock（包括已缓存/注入实例），未知服务商名也拒绝。测试可在非生产环境显式注入 Mock；本地开发使用配置 Mock 需显式启用短信。SendCloud 优先读取 `SENDCLOUD_SMS_USER/KEY`，否则使用 `SMS_USER/KEY`；缺失凭证或模板直接报错，不回退 Mock。已有生产启动断言继续生效。

实际联调：核对审核模板、变量和备案；在受控测试环境配置凭证与功能开关；取得指定测试手机及发送次数的明确授权后，执行单次挑战发送并记录脱敏结果；用相同任务 ID 验证去重，再通过控制台或投递回执核查送达。`True` 只代表请求被接受。此次仅 Mock HTTP，未进行真实发送、控制台模板核验或送达验收。
