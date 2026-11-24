# 南山科转通统一身份认证系统自动化测试报告

> [!NOTE]
> **Email Security Gateway 最新全量测试、真实 PostgreSQL/Redis 并发集成与性能基准报告已更新至独立文档**：[docs/auth/email-gateway/09-test-report.md](./email-gateway/09-test-report.md)。以下同步更新最新分支 `feat/email-security-gateway` 实测摘要，并修正历史文档中不再适用的内存限流降级描述（生产/`REDIS_ENABLED=true` 现已强制 Fail-Closed）。

## 1. 测试综述与最新实测执行环境

- **最新验证日期**：2026-11-24
- **代码分支**：`feat/email-security-gateway`
- **远端 `main` 基准 SHA**：`ef95927431ae101063eae9b3a4bcec24ffd42a27`
- **操作系统与依赖**：Windows + Python 3.13.17 (`pytest 9.1.1`, `pytest-cov 7.1.0`), PostgreSQL (`SMS_TEST_POSTGRES=1`), Redis (`SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15`), Node.js / Vite 8.2.2

---

## 2. 最新测试执行汇总表

| 测试工程 / 模块 | 测试套件 / 命令 | 用例总数 | 通过数 | 跳过 / 说明 | 失败数 | 耗时 / 覆盖率 | 状态 |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **后端全量测试 + 覆盖率** (`tech-transfer-service`) | `SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=... pytest -p no:cacheprovider --cov=. --cov-fail-under=75 -q` | 2568 | **2537** | 31 (`test_ai_chat_runs_pg.py` 需 `AI_CHAT_TEST_DATABASE_URL`) | 0 | 44.72s / **89.11%** | **PASSED** |
| **安全网关 PG/Redis 联合回归** (`tech-transfer-service`) | `tests/test_email_*.py` + `test_sms_*.py` + `test_sendcloud_security.py` + `test_unified_auth_recovery.py` + `test_wechat_login.py` + `test_middleware_exception.py` + `test_core_comprehensive.py` | 373 | **373** | 0 | 0 | 30.22s | **PASSED** |
| **新增 Email Gateway 专项套件** (`tech-transfer-service`) | `tests/test_email_*.py` (10 个测试模块，含真实 PG + Redis) | 45 | **45** | 0 | 0 | 11.14s | **PASSED** |
| **前端 Vue 3 单元测试与构建** (`nanshan-frontend`) | `node --test src/utils/*.test.mjs` + `npm run build` | 38 | **38** | 0 | 0 | 429.56ms / 391ms build | **PASSED** |
| **小程序回归测试与双端编译** (`南山小程序/南山`) | `node --test tests/*.test.mjs` + `build:h5` + `build:mp-weixin` | 416 | **416** | 0 | 0 | 2213.77ms + 双端 build DONE | **PASSED** |
| **真实外部公网 SMTP/SES 投递** | — | — | — | 未授权外发（遵循安全规范未触发） | — | — | **`NOT RUN`** |

---

## 3. 历史测试条目演进说明 (`test_unified_auth_recovery.py`)

原报告第 3 节条目 `3. test_rate_limiter_memory_fallback` 已随 `SecurityRateLimiter` 生产 **Fail-Closed** 安全加固演进：
- 在 `APP_ENV in ("staging", "production")` 或 `REDIS_ENABLED=true` 时，Redis 异常不再静默降级至进程内存 `_mem_buckets`，而是显式返回 HTTP 503 `TT_COMMON_50301`（由 `tests/test_email_risk.py::test_email_risk_and_rate_limiter_fail_closed_on_redis_failure` 验证）；
- 邮件重置链接回归测试 `test_recovery_start_valid_account_email_link` 已更新为校验 URL Fragment (`reset-password#challengeId=...&token=...`) 与 `email_gateway` 统一资格/风控流程。

1. `test_mock_sms_provider_and_registry`
   - 验证服务商工厂模式与 MockSmsProvider 发送、捕获与验证码提取。
2. `test_mock_email_provider`
   - 验证邮件服务商抽象与 MockEmailProvider 发送结果。
3. `test_email_risk_and_rate_limiter_fail_closed_on_redis_failure`（替代原内存静默降级预期）
   - 仅当非生产且 `REDIS_ENABLED=false` 时允许内存窗口；生产环境或启用 Redis 时强制 Fail-Closed 返回 503 (`TT_COMMON_50301`)。
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

# 3. 运行后端 Email + 统一安全专项测试（含真实 PostgreSQL 与 Redis）
SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 python -m pytest -p no:cacheprovider tests/test_email_*.py tests/test_unified_auth_recovery.py -v

# 4. 运行前端 Vue 3 测试与打包构建
cd ../nanshan-frontend
node --test src/utils/*.test.mjs
npm run build

# 5. 运行小程序测试
cd ../南山小程序/南山
node --test tests/unified-auth-security.test.mjs tests/account-auth-registration.test.mjs tests/wechat-login.test.mjs
```
