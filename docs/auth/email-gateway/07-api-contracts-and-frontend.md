# 前后端接口契约、H5 与微信小程序找回/换绑协同规范 (07-api-contracts-and-frontend)

## 1. 后端安全与找回 API 契约

### 1.1 找回能力探测接口（新增）
- **Endpoint**：`GET /api/tech-transfer/v1/auth/recovery/capabilities`（公开只读，不泄露任何密钥或配置明细）
- **响应**：
  ```json
  {
    "code": "TT_SUCCESS_20000",
    "data": {
      "sms": true,
      "emailOtp": false,
      "emailLink": false,
      "codeTtlSeconds": 300,
      "cooldownSeconds": 60
    }
  }
  ```

### 1.2 密码找回三步接口（增强防枚举、门禁与退避头）
- `POST /api/tech-transfer/v1/auth/recovery/start`
  - 当 `channel in {"email_otp", "email_link"}` 且 `EMAIL_ENABLED=false` 时，直接返回 **503 `TT_COMMON_50301`**（不放行、不伪造成功）；
  - 当命中邮箱风控引擎限制返回 HTTP 429 (`TT_COMMON_42901`) 时，通过响应头 `Retry-After: <seconds>` 与 `details.retryAfter` 同步传递剩余等待秒数；
  - 对不存在账号、未确权邮箱或未激活账号统一返回与成功一致的 200 防枚举响应（`sent: true`、`challengeId` 不暴露目标是否发送、`maskedDestination: null`）。
- `POST /api/tech-transfer/v1/auth/recovery/verify` & `/complete`：维持统一契约，新增对 `email_link` 256 位随机 Token 与 `send_state='unknown'` 的状态机校验，并在重置成功后原子递增 `session_version` 与吊销全部活跃刷新令牌。

### 1.3 安全中心与二次认证接口（新增与增强）
- `GET /api/tech-transfer/v1/me/security`：
  新增返回 `capabilities: { smsEnabled, emailEnabled }` 与 `stepUpMethods: [...]`（如 `["password", "old_email_otp"]`）。
- `POST /api/tech-transfer/v1/me/security/step-up/challenge`（新增，已挂载 `SmsBodyLimitMiddleware` 与 `validate_sms_request`）：
  入参 `{ purpose: "rebind_email", method: "old_email_otp" | "old_phone_otp" }`，返回 `{ challengeId, method, maskedDestination, message }`。
- `POST /api/tech-transfer/v1/me/security/step-up/verify`（新增）：
  入参 `{ purpose, method, currentPassword?, challengeId?, code?, targetContact? }`，返回 `{ stepUpGrant, expiresIn, method }`。
- `POST /api/tech-transfer/v1/me/security/contact/challenge` & `/verify`：
  新增可选字段 `stepUpGrant`；若当前账号已有已确权安全邮箱，缺少合法 `stepUpGrant` 时服务端强制返回 403。

---

## 2. Vue 3 H5 / 管理端改造要点

1. **邮件重置页面防自动核销与泄露 (`nanshan-frontend/src/views/auth/ResetPasswordView.vue`)**：
   - 借助 `src/utils/emailSecurity.js::parseResetCredentialsFromLocation` 优先解析 URL Fragment（`#challengeId=...&token=...`），向后兼容 Query；
   - `onMounted()` 中**零 API 请求**，仅读取并立即通过 `window.history.replaceState` 剥离 URL 凭据（防止邮件网关安全扫描器预抓取导致一次性链接失效）；
   - 仅当用户输入并确认新密码、点击提交后依次调用 `verifyPasswordRecovery` 与 `completePasswordRecovery`；`onUnmounted()` 清空组件内存敏感字段。
   - 服务端 `app.py` 对 `/forgot-password` 与 `/reset-password` SPA 页面下发 `Referrer-Policy: no-referrer` 与 `Cache-Control: no-store`。
2. **找回向导与能力感知 (`ForgotPasswordView.vue`)**：
   - 加载即拉取 `/auth/recovery/capabilities`，按服务端开关禁用未开通通道；
   - 切换通道或修改账号时自动作废旧 `challengeId`/`code`/`recoveryGrant`；
   - 使用 `sanitizeOtpCode()` 完整保留 `0` 开头 6 位验证码；借助请求序列号与 `Retry-After` 响应头同步倒计时与并发竞态保护。
3. **后台安全中心 Step-up 换绑 (`AccountSecurityView.vue`)**：
   - 若 `securityInfo.email.verified === true`，打开邮箱弹窗先进入 `"stepUp"` 认证步骤（支持当前密码或原邮箱/原手机 OTP / 近期安全会话），取得 `stepUpGrant` 后再进入 `"bind"` 填写新邮箱与验证码。

---

## 3. 微信小程序 (`南山小程序/南山`) 改造要点

- **API 客户端 (`subpackages/tech-transfer/api/client.js` & `user.js`)**：
  - 将 `/me/security/step-up/challenge` 加入 `X-Device-Id` 与 `X-Client-Source: mini` 注入白名单；
  - 统一提取服务端返回的 `Retry-After` 响应头与 `details.retryAfter` 并挂载至 `error.retryAfter`；
  - 导出 `getRecoveryCapabilities`、`startSecurityStepUpChallenge`、`verifySecurityStepUp`，`sendSecurityContactChallenge` 与 `verifySecurityContact` 支持传入 `stepUpGrant`。
- **个人中心页 (`pages/mine/mine.vue`)**：
  - 修复历史已知 Bug：邮箱找回渠道选择器及请求参数全面统一使用 `'email_otp'`，消除误传 `'email'` 导致的 400 失败（已补充 `unified-auth-security.test.mjs` 正则回归守卫）；
  - 集成找回通道可用性展示、账号/渠道变更重置状态、非数字剔除保留前导零输入、`onUnload`/`beforeUnmount` 定时器清理，以及与 H5 端一致的邮箱换绑 Step-up 二次认证弹层。
