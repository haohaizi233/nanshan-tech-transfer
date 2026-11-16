# 南山科转通统一身份与账号安全 API 契约规范 (04-api-contracts)

**API 前缀**：`/api/tech-transfer/v1`  
**全局响应包装**：`{ "code": 0, "message": "...", "data": {...}, "requestId": "..." }`

---

## 1. 密码找回与重置接口

### 1.1 `POST /auth/recovery/start`
- **说明**：发起密码找回流程，向预留安全联系方式发送短信/邮件验证码或重置链接。
- **登录状态**：无需登录
- **防枚举策略**：账号不存在或未绑定该渠道联系方式时，外部响应同样返回 `sent: true`，不泄露账号存在性。
- **限流规则**：IP 15 次 / 60 秒；目标账号 5 次 / 300 秒。
- **请求体 (JSON)**：
  ```json
  {
    "account": "admin_or_phone_or_email",
    "channel": "sms" // 可选: "sms" | "email_otp" | "email_link"
  }
  ```
- **成功响应 (200 OK)**：
  ```json
  {
    "code": 0,
    "message": "验证信息已发送至 138****1234",
    "data": {
      "challengeId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
      "channel": "sms",
      "maskedDestination": "138****1234",
      "sent": true,
      "message": "验证信息已发送至 138****1234"
    },
    "requestId": "req-xxx"
  }
  ```

### 1.2 `POST /auth/recovery/verify`
- **说明**：核验验证码或邮件 Token，核验通过后签发短期一次性 `recoveryGrant`。
- **登录状态**：无需登录
- **防暴力破解**：单个挑战最多允许错误 5 次，超限后挑战状态变为 `failed`，需重新发起。
- **请求体 (JSON)**：
  ```json
  {
    "challengeId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
    "code": "123456"
  }
  ```
- **成功响应 (200 OK)**：
  ```json
  {
    "code": 0,
    "message": "ok",
    "data": {
      "recoveryGrant": "rg_sec_9f8e7d6c5b4a3...",
      "expiresIn": 300
    },
    "requestId": "req-xxx"
  }
  ```

### 1.3 `POST /auth/recovery/complete`
- **说明**：基于 `recoveryGrant` 完成密码重置。单事务提交：更新密码哈希、递增 `session_version`、吊销所有存量 RefreshToken 并即时失效旧 Access Token。
- **登录状态**：无需登录
- **请求体 (JSON)**：
  ```json
  {
    "recoveryGrant": "rg_sec_9f8e7d6c5b4a3...",
    "newPassword": "NewStrongPassword@2026"
  }
  ```
- **成功响应 (200 OK)**：
  ```json
  {
    "code": 0,
    "message": "密码重置成功，请重新登录",
    "data": {
      "ok": true,
      "message": "密码重置成功，请重新登录"
    },
    "requestId": "req-xxx"
  }
  ```

---

## 2. PC 微信扫码 OAuth2 接口

### 2.1 `GET /auth/wechat/web/config`
- **说明**：获取 PC 微信扫码功能开关及 AppID。
- **成功响应**：
  ```json
  {
    "code": 0,
    "data": {
      "enabled": true,
      "appid": "wx1234567890abcdef"
    }
  }
  ```

### 2.2 `GET /auth/wechat/web/authorize?redirectUri=...`
- **说明**：生成包含一次性 `state`（10 分钟有效）的微信开放平台扫码登录重定向 URL。
- **成功响应**：
  ```json
  {
    "code": 0,
    "data": {
      "authorizeUrl": "https://open.weixin.qq.com/connect/qrconnect?appid=...&state=...",
      "state": "state_token_xxx",
      "enabled": true
    }
  }
  ```

### 2.3 `POST /auth/wechat/web/callback`
- **说明**：前端接收微信回调的 code 与 state，向后端提交以换取业务 Token 或绑定凭据。
- **请求体**：
  ```json
  {
    "code": "wx_code_xxx",
    "state": "state_token_xxx"
  }
  ```
- **已绑定用户响应 (直接签发登录态)**：
  ```json
  {
    "code": 0,
    "data": {
      "accessToken": "eyJhbGciOi...",
      "refreshToken": "eyJhbGciOi...",
      "expiresIn": 7200,
      "user": { "userId": 1, ... },
      "isNewUser": false
    }
  }
  ```
- **未绑定用户响应**：
  ```json
  {
    "code": 0,
    "data": {
      "isBound": false,
      "bindingTicket": "ticket_xxx",
      "maskedOpenId": "oWx****1234",
      "message": "该微信尚未绑定科转通账号，请先登录已有账号或注册新账号完成绑定"
    }
  }
  ```

### 2.4 `POST /auth/wechat/web/bind`
- **说明**：已登录用户携带 `bindingTicket` 完成 PC 微信扫码绑定。
- **认证要求**：Bearer Authorization

---

## 3. 个人安全中心与联系方式管理接口

### 3.1 `GET /me/security`
- **说明**：查询当前用户安全配置状况（脱敏手机、脱敏邮箱、微信绑定状态、密码配置状态、最近安全日志）。
- **认证要求**：Bearer Authorization

### 3.2 `POST /me/security/contact/challenge`
- **说明**：发起安全手机号或安全邮箱绑定验证码。
- **请求体**：`{ "contactType": "phone", "contactValue": "13800138000" }`

### 3.3 `POST /me/security/contact/verify`
- **说明**：核验验证码并确权入库 `account_contact`。
- **请求体**：`{ "challengeId": "...", "code": "123456", "contactValue": "13800138000" }`

### 3.4 `POST /me/security/revoke-sessions`
- **说明**：强制注销其他所有设备上的活跃会话。
