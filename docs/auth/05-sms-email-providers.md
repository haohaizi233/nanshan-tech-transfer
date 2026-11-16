# 南山科转通短信与邮件服务商接入规范 (05-sms-email-providers)

## 1. 架构定位与设计原则

- **业务与服务商强解耦**：业务代码（找回密码、绑定安全手机、安全邮箱确权）只依赖抽象接口 `SmsProvider` 与 `EmailProvider`，严禁直接在路由或业务模块中硬编码腾讯云或 SMTP 接口。
- **配置驱动与动态降级**：
  - 测试与本地环境：默认使用 `MockSmsProvider` / `MockEmailProvider`，在内存中追踪验证码和重置链接，绝不向真实用户派发。
  - 生产环境：支持腾讯云 SMS、腾讯云 SES 及标准 SMTP。
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
    def send_code(self, phone: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        """发送短信验证码。成功返回 True，失败抛出 ProviderError。"""
```

### 2.2 腾讯云短信 (TencentSmsProvider) 配置清单
- `SMS_ENABLED=true`
- `SMS_PROVIDER=tencent`
- `TENCENT_SMS_SECRET_ID`：腾讯云 API 访问密钥 ID
- `TENCENT_SMS_SECRET_KEY`：腾讯云 API 访问密钥 Key
- `TENCENT_SMS_SDK_APP_ID`：短信应用 SDK AppID
- `TENCENT_SMS_SIGN_NAME`：短信签名名称（需工信部与腾讯云报备审核通过，例如 `南山科转通`）
- `TENCENT_SMS_TEMPLATE_ID`：正文模板 ID（例如：`您的验证码为{1}，请在{2}分钟内完成操作`）

---

## 3. 邮件服务商 (EmailProvider)

### 3.1 接口契约
```python
class EmailProvider(abc.ABC):
    @abc.abstractmethod
    def send_code(self, email: str, code: str, purpose: str, expires_in_seconds: int = 300) -> bool:
        """发送邮件 6 位 OTP 验证码。"""

    @abc.abstractmethod
    def send_reset_link(self, email: str, reset_url: str, expires_in_seconds: int = 300) -> bool:
        """发送一次性密码重置链接。"""
```

### 3.2 支持的服务商实现
1. **腾讯云 SES (TencentSesProvider)**：
   - `EMAIL_ENABLED=true`
   - `EMAIL_PROVIDER=tencent`
   - `TENCENT_SES_SECRET_ID` / `TENCENT_SES_SECRET_KEY`
   - `TENCENT_SES_FROM_EMAIL`：经过腾讯云验证的企业发信域名（如 `service@notice.nanshan-tech.com`）
2. **标准 SMTP (SmtpEmailProvider)**：
   - `EMAIL_ENABLED=true`
   - `EMAIL_PROVIDER=smtp`
   - `SMTP_HOST`、`SMTP_PORT` (默认 465 SSL)、`SMTP_USER`、`SMTP_PASSWORD`、`SMTP_USE_SSL=true`

---

## 4. 异常处理与可重试机制

- 外部网络超时：Provider 默认设置 5 秒超时保护，超时后触发统一错误包装 `TT_COMMON_50301`，防止请求长阻塞耗尽 Gunicorn/Uvicorn 线程。
- 业务幂等与防重试风暴：业务层对每个联系方式设有 60 秒重发冷却期，同一目标 1 小时内限制 5 次，即便用户频繁点击也不会对服务商网关产生轰炸。
