# 南山科转通统一身份认证系统自动化测试报告

## 1. 测试综述与执行环境

- **测试执行时间**：2026-11-16
- **代码分支**：`feat/unified-auth-recovery`
- **审查基准 SHA**：`e53d8fbb37cd18c4b1a5a84bbaae52f4048c16a1`
- **实际远端 HEAD SHA**：`7efffea12eb59a30137cde6633b7cfa9ed1c7ec1`
- **操作系统**：Windows 11 / Windows Server
- **Python 环境**：Python 3.13.17 (`.venv/Scripts/python.exe`), Pytest 9.1.1, Coverage 7.1.0
- **Node.js 环境**：Node v22+, Vite 8.2.2

---

## 2. 测试执行汇总表

| 测试工程 / 模块 | 测试套件 / 命令 | 用例总数 | 通过数 | 跳过数 | 失败数 | 耗时 | 状态 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **后端核心认证与业务服务** (`tech-transfer-service`) | `pytest -q` | 2305 | 2274 | 31 (需PG真实连接) | 0 | 17.06s | **PASSED** |
| **新增统一身份与安全专用测试** (`tech-transfer-service`) | `pytest tests/test_unified_auth_recovery.py` | 15 | 15 | 0 | 0 | 0.57s | **PASSED** |
| **前端 Vue 3 单元测试** (`nanshan-frontend`) | `node --test tests/*.test.mjs` | 10 | 10 | 0 | 0 | 0.28s | **PASSED** |
| **前端生产环境构建** (`nanshan-frontend`) | `npm run build` | 100 模块 | 100 | 0 | 0 | 0.44s | **PASSED** |
| **小程序认证与安全测试** (`南山小程序/南山`) | `node --test tests/unified-auth-security.test.mjs ...` | 14 | 14 | 0 | 0 | 0.33s | **PASSED** |

---

## 3. 详细测试用例清单与验证点

### 3.1 后端专项安全测试 (`test_unified_auth_recovery.py`)

1. `test_mock_sms_provider_and_registry`
   - 验证服务商工厂模式与 MockSmsProvider 发送、捕获与验证码提取。
2. `test_mock_email_provider`
   - 验证邮件服务商抽象与 MockEmailProvider 发送结果。
3. `test_rate_limiter_memory_fallback`
   - 验证滑动窗口限流器在无 Redis 时平滑降级至内存滑动窗口，超出阈值精确拒止。
4. `test_start_password_recovery_anti_enumeration`
   - 验证账号不存在或未绑定有效安全联系方式时，接口模拟恒定耗时并返回完全一致的成功消息，零账号枚举泄露。
5. `test_verify_recovery_challenge_failure_cap`
   - 验证验证码连续 5 次输入错误后 Challenge 立即标记为失败，第 6 次即使输入正确也被拒绝。
6. `test_verify_recovery_challenge_success_issues_grant`
   - 验证 6 位 HMAC 验证码核验通过后签发高强度单次 Recovery Grant。
7. `test_complete_password_recovery_single_tx`
   - 验证密码重置在单一事务内消耗 grant、更新哈希、递增 `session_version`、吊销所有 Refresh Token。
8. `test_session_version_invalidation_in_middleware`
   - 验证修改密码后携带旧版本 `ver` 的 JWT 访问受保护接口立即返回 401 Unauthorized。
9. `test_wechat_web_authorize_url_and_state`
   - 验证 PC 端微信扫码授权地址生成、256位 state 生成及 10 分钟单次校验。
10. `test_wechat_web_callback_bind_flow`
    - 验证未绑定系统的微信账号返回 bindingTicket，且通过绑定接口完成首次账号关联。
11. `test_security_summary_and_contact_binding`
    - 验证用户个人安全中心获取脱敏信息、发起绑定挑战并成功绑定的完整闭环。
12. `test_revoke_all_sessions_endpoint`
    - 验证 `/me/security/revoke-sessions` 端点递增 `session_version` 并吊销旧会话。
13. `test_recovery_email_reset_link_dispatch`
    - 验证邮件渠道找回密码派发包含安全 Token 的一次性重置链接。
14. `test_hash_password_argon2_and_pbkdf2_compat`
    - 验证密码哈希自动探测 Argon2id 与 PBKDF2-SHA256，旧哈希平滑升级验证。
15. `test_concurrent_grant_consumption_race_condition`
    - 验证 Recovery Grant 并发请求仅允许一个请求重置成功，杜绝重放与竞态。

### 3.2 前端测试与多端覆盖

- **Vue 3 页面集成**：
  - `LoginView.vue`：“忘记密码？”链接正确导航至 `/forgot-password`；Tab 切换支持密码登录与微信扫码登录；支持监听 OAuth 回调 code 与 state。
  - `ForgotPasswordView.vue`：标准 4 步向导流程（输入账号/选择通道 -> 60秒倒计时核验 -> 设置新密码 -> 成功反馈）。
  - `ResetPasswordView.vue`：邮件重置链接直接访问，加载即执行 `replaceState` 剔除 URL 敏感 Token。
  - `AccountSecurityView.vue`：后台安全中心支持安全手机/邮箱绑定弹窗、修改密码、微信状态与一键踢下线。
- **小程序集成**：
  - `mine.vue`：登录卡片加入“忘记密码？”弹窗；个人中心卡片集成“账号与安全”面板，支持查看脱敏手机/邮箱、获取验证码绑定、设置/修改登录密码与全端会话吊销。

---

## 4. 自动化测试复现指南

```bash
# 1. 激活虚拟环境
.\.venv\Scripts\activate

# 2. 运行后端全部测试
cd tech-transfer-service
python -m pytest -q

# 3. 运行后端安全专项测试
python -m pytest tests/test_unified_auth_recovery.py -v

# 4. 运行前端 Vue 3 测试与打包构建
cd ../nanshan-frontend
node --test tests/*.test.mjs
npm run build

# 5. 运行小程序测试
cd ../南山小程序/南山
node --test tests/unified-auth-security.test.mjs tests/account-auth-registration.test.mjs tests/wechat-login.test.mjs
```
