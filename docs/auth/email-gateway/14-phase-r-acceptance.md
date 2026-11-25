# Phase R 安全边界收敛与生产可靠性加固验收报告 (14-phase-r-acceptance)

> **[HISTORICAL SNAPSHOT / 历史快照说明]** 本文档为 Phase R 阶段的历史验收快照，已被 [17-phase-r-hotfix-acceptance.md](./17-phase-r-hotfix-acceptance.md) 与动态证据清单 [acceptance-manifest.yaml](./acceptance-manifest.yaml) 取代；最新实时核验结果以 CI 执行与证据门禁输出为准。

## 1. 基线与提交信息

- **上轮验收基准 SHA**：`f4af46f39e1a73b904939d98989d61ed88c0d0ba`
- **Phase R 后端与迁移提交 SHA**：`9e31107`（迁移 `037_phase_r_security_hardening.sql`、`auth_time`/`sid`、全局锁顺序、`TT_AUTH_RECOVERY_INVALID`、目标邮箱强制绑定、持久幂等、`state_machine` CAS、`DeliverStatus` 对账、`mypy` 类型标注收敛）
- **Phase R 前端提交 SHA**：`2c9b24f`（H5 管理端与微信小程序首次绑定安全授权、目标邮箱前置确认与 `Idempotency-Key` 生命周期收敛）
- **外部实发状态说明**：未授权真实 SMTP / 腾讯云 SES 外部发信账号与收件箱，**`EXT-EMAIL-01`**、**`EXT-EMAIL-02`** 及 [12-final-acceptance.md](12-final-acceptance.md) 中的 **`A30`** 严格保持 **`NOT RUN`**。

---

## 2. 实际执行验证流水账

| 验证项 | 实测命令 / 范围 | 实际输出结果 | 结果 |
| :--- | :--- | :--- | :---: |
| **PG + Redis 专项集成套** | `pytest -p no:cacheprovider test_sms_gateway_postgres.py test_sms_risk.py test_email_gateway_postgres.py test_email_risk.py test_security_auth_time.py test_email_first_binding.py test_recovery_anti_enumeration.py test_security_cross_transaction_postgres.py test_security_http_idempotency.py test_delivery_state_cas.py test_delivery_pii_retention.py test_email_provider_reconciliation.py -v`（本地 PostgreSQL 18 + Redis 7） | **`64 passed`**（76.76s，0 failed，0 skipped） | **PASSED** |
| **后端全量测试 + PG/Redis** | `pytest -p no:cacheprovider --cov=. --cov-report=term-missing --cov-fail-under=75 -q`（启用 `SMS_TEST_POSTGRES=1` 与 `SMS_TEST_REDIS_URL`） | **`2555 passed, 31 skipped`**（96.84s；31 skipped 均为需 `MEMBER_TEST_DSN` 的 `test_ai_chat_runs_pg.py`）；覆盖率 **`89.38%`** | **PASSED** |
| **后端全量测试（默认单元口径）** | `pytest -p no:cacheprovider --cov=. --cov-report=term-missing --cov-fail-under=75 -q`（未设置 `SMS_TEST_POSTGRES`） | **`2497 passed, 89 skipped`**（40.24s）；覆盖率 **`86.78%`** | **PASSED** |
| **Ruff 代码检查与格式化** | `ruff check .`、`ruff format --check .` | `All checks passed!`、`272 files already formatted` | **PASSED** |
| **Mypy 阻塞类型检查** | `mypy modules/security core/jwt_utils.py --ignore-missing-imports --no-strict-optional --show-error-codes` | `Success: no issues found in 20 source files` | **PASSED** |
| **H5 管理端测试与构建** | `nanshan-frontend`: `node --test src/utils/*.test.mjs tests/*.test.mjs`、`npm run build` | **`53 passed, 0 failed`**；`vite build` 成功 | **PASSED** |
| **微信小程序测试与双端构建** | `南山小程序/南山`: `node --test tests/*.test.mjs`、`npm run build:h5`、`npm run build:mp-weixin` | **`418 passed, 0 failed`**；H5 与微信小程序编译均通过 | **PASSED** |
| **外部真实 SMTP/SES 实盘发送** | `EXT-EMAIL-01` / `EXT-EMAIL-02` / `A30` | 遵守红线未执行外部真实投递 | **`NOT RUN`** |

> 注：本机 Windows 环境未安装 `flake8` 可执行命令；`ruff check .` 已覆盖含 `E` / `F` 语法与未定义符号在内的全部静态检查且全部通过；GitHub Actions 工作流 `.github/workflows/ci.yml` 保留 `flake8` 检查步骤。

---

## 3. R-A01–R-A32 逐项验收矩阵

| 验收项 | 对应要求 | 关键实现与约束 | 自动化验证证据 | 状态 |
| :--- | :--- | :--- | :--- | :---: |
| **R-A01** | R01 | 密码账号及管理员首次绑定安全邮箱无 `step_up_grant` 必拒 `403`，禁止以 `recent_auth` 绕过 | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py) | **PASSED** |
| **R-A02** | R01/R02 | 纯微信无密码账号在可信 `auth_time` 窗口内可通过 `recent_auth` 完成首次绑定；超窗即拒 | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py) | **PASSED** |
| **R-A03** | R02 | `refresh_session` 延续原 `sid` 与原 `auth_time`，绝不因刷新推进 `auth_time`，历史 `NULL` 不伪造 | [test_security_auth_time.py](../../../tech-transfer-service/tests/test_security_auth_time.py) | **PASSED** |
| **R-A04** | R02 | 未来伪造 `auth_time`、仅含 `iat` 无 `auth_time`、缺失 `sid` 的 Token 均拒绝 `recent_auth` | [test_security_auth_time.py](../../../tech-transfer-service/tests/test_security_auth_time.py) | **PASSED** |
| **R-A05** | R01/R05 | 已绑邮箱后复用 `bind_email` Grant 换绑及先起挑再提权等升级路径被 `403` 阻断 | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py) | **PASSED** |
| **R-A06** | R02 | `Step-up Grant` 在单端 `logout`、跨设备会话、`session_version` 递增、账号禁用后立即失效 | [test_security_auth_time.py](../../../tech-transfer-service/tests/test_security_auth_time.py) | **PASSED** |
| **R-A07** | R03 | 统一锁顺序 `app_user -> user_credential -> auth_challenge -> account_contact -> recovery_grant -> step_up_grant -> auth_session` | [test_security_cross_transaction_postgres.py](../../../tech-transfer-service/tests/test_security_cross_transaction_postgres.py) | **PASSED** |
| **R-A08** | R03 | 同 Grant 8 线程并发重置仅 1 次成功、0 死锁；有界重试 helper 覆盖 `40P01`/`40001` | [test_security_cross_transaction_postgres.py](../../../tech-transfer-service/tests/test_security_cross_transaction_postgres.py) | **PASSED** |
| **R-A09** | R03 | 换绑与跨渠道找回（SMS + Email）并发屏障压测 0 死锁且最终最多保留 1 个有效 Grant | [test_security_cross_transaction_postgres.py](../../../tech-transfer-service/tests/test_security_cross_transaction_postgres.py) | **PASSED** |
| **R-A10** | R03 | `verify_and_bind_contact`、`complete_password_recovery`、`change_password`、`revoke_all_user_sessions` 交错并发零部分残留状态 | [test_security_cross_transaction_postgres.py](../../../tech-transfer-service/tests/test_security_cross_transaction_postgres.py) | **PASSED** |
| **R-A11** | R04 | `/auth/recovery/verify` 10 种失败场景对外返回完全一致的 HTTP 400 / `TT_AUTH_RECOVERY_INVALID` / 文案与键集合 | [test_recovery_anti_enumeration.py](../../../tech-transfer-service/tests/test_recovery_anti_enumeration.py) | **PASSED** |
| **R-A12** | R04 | 错误试错独立提交递增 `attempt_count` 并达限锁定；不存在 Challenge 零 DB 写入；内部脱敏日志保留原因码 | [test_recovery_anti_enumeration.py](../../../tech-transfer-service/tests/test_recovery_anti_enumeration.py) | **PASSED** |
| **R-A13** | R05 | `bind_email`/`rebind_email` 缺失/空白目标邮箱拒签 `400`；challenge 与 verify 或最终绑定地址不一致必拒 `403`；规范化等价邮箱放行 | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py) | **PASSED** |
| **R-A14** | R05/R07 | `step_up_grant` / `auth_challenge` 持久化上下文绑定列与服务端状态机一致性约束通过真实 PG 校验 | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py)、[test_delivery_state_cas.py](../../../tech-transfer-service/tests/test_delivery_state_cas.py) | **PASSED** |
| **R-A15** | R06 | 32 并发相同 `Idempotency-Key` 仅产生 1 条入队记录、发送 1 封邮件并返回相同 `challengeId` | [test_security_http_idempotency.py](../../../tech-transfer-service/tests/test_security_http_idempotency.py) | **PASSED** |
| **R-A16** | R06 | 同 Key 不同参数返回 `409 TT_COMMON_40901`；调用前失败释放锁允许合法重试；`unknown` 结果拒绝盲目重发（503） | [test_security_http_idempotency.py](../../../tech-transfer-service/tests/test_security_http_idempotency.py) | **PASSED** |
| **R-A17** | R06 | 不同用户/IP/端点作用域隔离互不串扰；过期后可安全轮转；无 `Idempotency-Key` 旧客户端完全兼容 | [test_security_http_idempotency.py](../../../tech-transfer-service/tests/test_security_http_idempotency.py) | **PASSED** |
| **R-A18** | R07 | `reserved -> sending -> accepted/rejected/unknown` 参数化 CAS 迁移；重复回执幂等返回 `already_target` | [test_delivery_state_cas.py](../../../tech-transfer-service/tests/test_delivery_state_cas.py) | **PASSED** |
| **R-A19** | R07 | 并发 `accepted` vs `rejected` 竞争仅一侧胜出；`consumed`/`cancelled`/`expired` 终态收到迟到回执绝不复活为 `pending` | [test_delivery_state_cas.py](../../../tech-transfer-service/tests/test_delivery_state_cas.py) | **PASSED** |
| **R-A20** | R07 | 双 Worker `run_queued_recovery_task` 并发屏障抢占仅 1 个执行且只发 1 封邮件 | [test_delivery_state_cas.py](../../../tech-transfer-service/tests/test_delivery_state_cas.py) | **PASSED** |
| **R-A21** | R08 | 排队超时、处理崩溃、已完成回写与历史滞留非运行态均剥离 `account`/`ip`/`device_id`/`destination`，活跃任务不误伤且清理幂等 | [test_delivery_pii_retention.py](../../../tech-transfer-service/tests/test_delivery_pii_retention.py) | **PASSED** |
| **R-A22** | R09 | 切仓 (`smtp` vs `tencent`)、配置实例指纹 `provider_config_id` 变更、Provider 不可用与非匹配 `MessageId` 均拒绝误更新并转人工复核 | [test_email_provider_reconciliation.py](../../../tech-transfer-service/tests/test_email_provider_reconciliation.py) | **PASSED** |
| **R-A23** | R09 | 腾讯云 SES `DeliverStatus` (`0/1/2/3/8` 与未知码)、多记录取最大 `DeliverTime`、`Asia/Shanghai` 默认日期、`Offset` 透传及严禁持久化 `DeliverMessage` | [test_email_provider_reconciliation.py](../../../tech-transfer-service/tests/test_email_provider_reconciliation.py) | **PASSED** |
| **R-A24** | R01/R05 | H5 `AccountSecurityView.vue` 首次绑定与换绑统一先输入目标邮箱并完成 Step-up 授权，支持切换目标重认证 | [unified-auth-views.test.mjs](../../../nanshan-frontend/tests/unified-auth-views.test.mjs) | **PASSED** |
| **R-A25** | R06 | H5 `client.js` 透传并在 401 刷新重试保留请求头；`ForgotPasswordView.vue` 与 `AccountSecurityView.vue` 按规则管理不透明 `Idempotency-Key` | [emailSecurity.test.mjs](../../../nanshan-frontend/src/utils/emailSecurity.test.mjs)、[unified-auth-views.test.mjs](../../../nanshan-frontend/tests/unified-auth-views.test.mjs) | **PASSED** |
| **R-A26** | R01/R05/R06 | 微信小程序 `mine.vue` 与 `api/user.js`、`api/client.js` 同步落实首次绑邮 Step-up、目标绑定及不透明 `Idempotency-Key` | [unified-auth-security.test.mjs](../../../%E5%8D%97%E5%B1%B1%E5%B0%8F%E7%A8%8B%E5%BA%8F/%E5%8D%97%E5%B1%B1/tests/unified-auth-security.test.mjs) | **PASSED** |
| **R-A27** | R01/R05/R06 | H5 53 项测试与 Vite 构建全通过；微信小程序 418 项测试及 H5/MP-Weixin 双端编译全通过 | `nanshan-frontend` / `南山小程序/南山` 实测命令 | **PASSED** |
| **R-A28** | R02/R05/R06 | `037_phase_r_security_hardening.sql` 支持幂等重跑，撤销存量无目标绑定活跃邮件授权，强制约束并拓宽 `state VARCHAR(32)` | [test_email_first_binding.py](../../../tech-transfer-service/tests/test_email_first_binding.py)、[test_email_gateway_postgres.py](../../../tech-transfer-service/tests/test_email_gateway_postgres.py) | **PASSED** |
| **R-A29** | R10 | `.github/workflows/ci.yml` 集成全部 12 个 PG/Redis 测试套并新增阻塞式 `mypy` 类型检查与前端全量单测 | [ci.yml](../../../.github/workflows/ci.yml) | **PASSED** |
| **R-A30** | R10 | 全量后端覆盖率（PG/Redis 全开）达 `89.38%`（标准单元模式 `86.78%`），`ruff check` / `ruff format` / `mypy` 0 错误 | 上述第 2 节完整命令输出 | **PASSED** |
| **R-A31** | R11 | 保留 [12-final-acceptance.md](12-final-acceptance.md) 原始 A01–A30 矩阵语义及相对路径文档链接 | [12-final-acceptance.md](12-final-acceptance.md)、[13-phase-r-hardening.md](13-phase-r-hardening.md) | **PASSED** |
| **R-A32** | R11 | 外部实发邮件测试 (`EXT-EMAIL-01`、`EXT-EMAIL-02`、`A30`) 严格不触发外发，诚实标为 `NOT RUN` | 代码静态核查 + 测试环境 `MockEmailProvider` | **`NOT RUN`** |
