# 南山科转通 Phase R-Final：安全不变量收敛与异常路径工程加固报告

> 仓库：`haohaizi233/nanshan-tech-transfer`  
> 分支：`feat/phase-r-final-security`（基于 `main` 基线提交 `5f0d00aee3a3a869f52b790a72e74bf26908672c`）  
> 历史增量迁移 `033`–`037`：**零改动**；新增增量迁移：`migrations/pg/038_phase_r_final_security.sql`

---

## 1. 基线与设计原则

Phase R-Final 不新建外围业务体系，专注确保既有认证与投递安全基础设施在 **数据库异常、进程崩溃、并发竞争、权限变化、请求重试与部分成功** 路径下严格满足形式化安全不变量（`INV-01`–`INV-15`）：

1. **彻底 Fail-Closed**：不再将数据库缺行、连接中断、查询超时或 Schema 异常隐式降级为“旧版本 Token”或“有效会话”。
2. **持久执行权门禁**：调用外部邮件/短信 Provider 之前，必须在独立已提交 PostgreSQL 事务中原子赢得 `claim_send_execution_right()`（`status = 'pending_send' AND expires_at > NOW() AND send_state = 'reserved' -> 'sending'` 并绑定 `send_owner`）。
3. **单一全局锁序治理**：所有高风险身份/安全写事务统一按 `app_user -> user_credential -> auth_challenge -> recovery_grant -> step_up_grant -> auth_session` 获取行锁，彻底消弭环形等待与陈旧密码哈希竞态。
4. **生命周期状态完整性**：`idem_pending` / `pre_provider` / `send_claimed` / `provider_called` / `response_persisted` / `provider_unknown` / `provider_rejected` 持久化阶段严格区分可安全释放与不可重放边界；`cleanup_delivery_tasks()` 保护合法执行中任务并在 TTL 到期后幂等清除终态/超期键占与 PII。
5. **消除隐式 `SAVEPOINT` 降级**：启动期引入 `modules/security/schema_gate.py` 强制 038 Schema 门禁（生产环境缺列/缺约束阻断启动），清除认证与安全核心模块中所有以 `SAVEPOINT` 绕过字段校验的旧路径。

---

## 2. 缺陷收敛关闭矩阵（RF01–RF13）

| 编号 | 缺陷描述 | 根因定位与收敛实现 | 状态 | 验证证据 |
|---|---|---|---|---|
| **RF01** | 会话有效性检查存在 Fail-Open | 新增 [session_guard.py](tech-transfer-service/modules/security/session_guard.py)（`SessionValidationState`：`ACTIVE/REVOKED/EXPIRED/NOT_FOUND/INVALID/LEGACY/UNAVAILABLE`）；重写 [middleware.py](tech-transfer-service/core/middleware.py) `_session_is_active` / `_user_session_version` / `identity` 与 [step_up.py](tech-transfer-service/modules/security/step_up.py) `_session_revoked_in_db`，SID 不存在严格 401，DB 故障严格 503，UUID 格式前置校验不触发 DB | **已关闭** | [test_session_validation_fail_closed.py](tech-transfer-service/tests/test_session_validation_fail_closed.py) (`F01`–`F16`) |
| **RF02** | Provider 调用前 CAS 失败仍可能继续发送 | 重写 [state_machine.py](tech-transfer-service/modules/security/state_machine.py) `transition_delivery_state` 与 `claim_send_execution_right`（独立提交、联合条件 + `expected_owner`）；接入 [email_gateway.py](tech-transfer-service/modules/security/email_gateway.py) `_send_email`、[sms_gateway.py](tech-transfer-service/modules/security/sms_gateway.py) `_send` 与 [step_up.py](tech-transfer-service/modules/security/step_up.py) `start_step_up_challenge`（仅 `outcome == "transitioned"` 方准调用 Provider） | **已关闭** | [test_security_provider_execution_right.py](tech-transfer-service/tests/test_security_provider_execution_right.py) (`S01`–`S15`) |
| **RF03** | Refresh、Logout 与其他安全事务锁顺序不统一 | 统一 [modules/identity/service.py](tech-transfer-service/modules/identity/service.py)（`bootstrap_session` / `_issue_session` / `_verify_login_and_issue` 锁内二次核对 `password_hash` / `refresh_session` 锁 `app_user`→`user_credential` 并持久化禁用状态 / `logout_session` 锁 `app_user` 并按逻辑 `(user_id, sid)` 吊销所有活跃会期与 Grant / `change_password` 锁外算哈希、锁内递增 `session_version`、提交后清理缓存）、[wechat.py](tech-transfer-service/modules/identity/wechat.py) 与 [modules/security/service.py](tech-transfer-service/modules/security/service.py) | **已关闭** | [test_security_session_transaction_postgres.py](tech-transfer-service/tests/test_security_session_transaction_postgres.py) (`TX01`–`TX14`) |
| **RF04** | 密码修改或重置后旧恢复凭证撤销不完整 | `change_password()` 与 `complete_password_recovery()` 在同一事务内锁定并取消所有历史 `password_recovery`/`step_up_auth` 活跃 Challenge，撤销全部 `recovery_grant` / `step_up_grant` / `auth_session`，并将 `auth_cache.invalidate_user` 严格置于提交之后；手机换绑同步撤回短信恢复凭据 | **已关闭** | [test_security_credential_revocation.py](tech-transfer-service/tests/test_security_credential_revocation.py) |
| **RF05** | Step-up Challenge 上下文校验仍存在可选字段 | `038` 增加 `auth_challenge.{session_version, source_contact_fingerprint}` 及 CHECK 约束 `chk_auth_challenge_stepup_context`；[step_up.py](tech-transfer-service/modules/security/step_up.py) 强制校验 `session_id` / `session_version` / `sub_purpose` / `target_fingerprint` / `channel` 与 `can_verify_challenge()`，彻底移除 `if ... is not None` 可选绕过；`bind_email`/`rebind_email` 禁止缺失 SID 的旧 Token | **已关闭** | [test_step_up_challenge_context.py](tech-transfer-service/tests/test_step_up_challenge_context.py) (`SU01`–`SU18`) |
| **RF06** | 安全关键数据库操作存在宽泛异常回退 | 新增 [schema_gate.py](tech-transfer-service/modules/security/schema_gate.py) 并挂接 [app.py](tech-transfer-service/app.py) `lifespan`；移除 `state_machine.py`、`identity/service.py`、`security/service.py`、`email_gateway.py`、`sms_gateway.py`、`step_up.py` 全部 `SAVEPOINT` 字段异常降级；认证/投递关键异常严格 503/阶段收敛 | **已关闭** | [test_security_delivery_fault_injection.py](tech-transfer-service/tests/test_security_delivery_fault_injection.py) |
| **RF07** | 幂等占位中间状态缺少完整生命周期 | `038` 为 `security_delivery_request` 增加 `execution_owner`、`execution_stage`（CHECK `chk_sdr_execution_stage`）、`challenge_id`、`idem_claimed_at`；[idempotency.py](tech-transfer-service/modules/security/idempotency.py) 实现 `advance_idempotency_stage()`、`wait_for_idempotency_settlement()`（并发 `/recovery/start` 命中 `idem_pending` 有界等结不误伤 `409`）、活跃态与 `unknown` 禁止 TTL 到期抢占；前端/小程序识别 `status === 409 && details?.inFlight === true` | **已关闭** | [test_security_idempotency_crash_recovery.py](tech-transfer-service/tests/test_security_idempotency_crash_recovery.py) (`ID01`–`ID15`) |
| **RF08** | 外部发送成功但响应持久化失败时可能错误释放幂等键 | `finalize_http_idempotency()` / `release_http_idempotency_on_pre_provider_failure()` 增加 `execution_owner` 与 `execution_stage == 'pre_provider' AND provider_called = false` 门禁；[routes/me.py](tech-transfer-service/routes/me.py) 修复 `DeliveryStageError` 非法传参并独立捕获响应落盘异常，调用 `mark_http_idempotency_unknown()` 返回 503 且永久保留同键锁定（在 TTL 到期清理前） | **已关闭** | [test_security_idempotency_crash_recovery.py](tech-transfer-service/tests/test_security_idempotency_crash_recovery.py) (`ID03`–`ID05`, `ID14`) |
| **RF09** | PII 清理可能误伤正在执行的 `idem_pending` 任务 | [sms_gateway.py](tech-transfer-service/modules/security/sms_gateway.py) `cleanup_delivery_tasks()` 明确区分 `ACTIVE_TASK_STATES`、`TERMINAL_TASK_STATES` 与 `RECOVERY_REQUIRED_STATES`：活跃 `idem_pending`/`queued`/`processing` 绝不脱敏；超时 `idem_pending` 按阶段收敛（`pre_provider -> expired` 释放键；`provider_called -> unknown` 保留键）；过期幂等键仅在非活跃且 `idempotency_expires_at <= NOW()` 时清理 | **已关闭** | [test_security_idempotency_crash_recovery.py](tech-transfer-service/tests/test_security_idempotency_crash_recovery.py) (`ID09`–`ID11`) & [test_delivery_pii_retention.py](tech-transfer-service/tests/test_delivery_pii_retention.py) |
| **RF10** | PostgreSQL、Redis 与 Provider 状态协调仍有缺口 | 新增 [delivery_models.py](tech-transfer-service/modules/security/delivery_models.py) `transition_risk_checked()`，显式检查 Redis `engine.transition()` 布尔返回与异常，记录结构化告警并递增 `risk_transition_failed_total` 指标；`reconcile_email_delivery()` / `reconcile_sms_delivery()` 校验 `res.updated` CAS 结果 | **已关闭** | [test_security_delivery_fault_injection.py](tech-transfer-service/tests/test_security_delivery_fault_injection.py) & [test_email_provider_reconciliation.py](tech-transfer-service/tests/test_email_provider_reconciliation.py) |
| **RF11** | 原始 `A01`–`A30` 与 `R-A01`–`R-A32` 编号未真正恢复 | 创建机器可读清单 [acceptance-manifest.yaml](docs/auth/email-gateway/acceptance-manifest.yaml)（完整冻结 `A01`–`A30`、`R-A01`–`R-A32`、`RF-A01`–`RF-A42`、`EXT-EMAIL-01`–`03`）与自动化完整性门禁 [test_security_acceptance_manifest.py](tech-transfer-service/tests/test_security_acceptance_manifest.py) | **已关闭** | [test_security_acceptance_manifest.py](tech-transfer-service/tests/test_security_acceptance_manifest.py) |
| **RF12** | 跨事务并发与故障注入测试尚不充分 | 新增 7 套真实 PG/Redis 与故障注入测试并全部并入 `.github/workflows/ci.yml`；在 [db.py](tech-transfer-service/db.py) 提供可插拔 `concurrency_retry_observer` 透明暴露任何 40P01/40001 | **已关闭** | 见第 4、5 节实测记录 |
| **RF13** | 新版 SID 每请求数据库校验的性能与多实例一致性 | 单条联合查询合并 `app_user + auth_session` 检查使每请求仅 **1 次 SQL**（PG 18.6 实测 p50=`0.481ms`, p99=`1.110ms`），彻底不依赖进程内缓存判定现代 SID 失效，保证多 Worker 注销/改密/禁用 **0ms 跨实例同步延迟**；将 `core/middleware.py` 加入阻断式 `mypy` 门禁 | **已关闭** | 第 7 节实测基准 & [ci.yml](.github/workflows/ci.yml) |

---

## 3. 安全不变量与实现/数据库/测试映射（INV-01–INV-15）

| 不变量 | 源码控制点 | 数据库约束 / 索引 | 自动化测试证据 |
|---|---|---|---|
| **INV-01** 不存在/已撤销现代 SID 必拒 | `session_guard.validate_session_state`, `middleware.identity` | `auth_session(user_id, sid, status)`, `idx_auth_session_user_sid_status` | `test_session_validation_fail_closed.py` (`F01`–`F06`) |
| **INV-02** 状态不明时高风险 Fail-Closed | `session_guard.raise_for_session_state`, `schema_gate.assert_required_security_schema` | `app_user.session_version` NOT NULL | `test_session_validation_fail_closed.py` (`F08`–`F11`), `test_security_delivery_fault_injection.py` |
| **INV-03** 未获持久化发送权不得调 Provider | `state_machine.claim_send_execution_right`, `email_gateway._send_email`, `sms_gateway._send`, `step_up.start_step_up_challenge` | `auth_challenge(status, send_state, send_owner, expires_at)` | `test_security_provider_execution_right.py` (`S01`–`S08`, `S13`–`S14`) |
| **INV-04** 同发信任务不因并发/崩溃重放 | `claim_send_execution_right`, `run_queued_recovery_task (SKIP LOCKED)`, `idempotency` | `idx_auth_challenge_sending_claimed`, `uk_sdr_idempotency` | `test_security_provider_execution_right.py` (`S04`, `S15`), `test_security_idempotency_crash_recovery.py` |
| **INV-05** 已终止 Challenge 不被回执重激活 | `transition_delivery_state` (`status != 'cancelled'` / 终态保护), `can_verify_challenge` | `chk_auth_challenge_status`, `chk_auth_challenge_send_state` | `test_security_provider_execution_right.py` (`S09`–`S11`), `test_delivery_state_cas.py` |
| **INV-06** 改密/重置/注销后旧凭证永不生效 | `identity.service.(change_password, logout_session, refresh_session)`, `security.service.complete_password_recovery` | `app_user.session_version`, `recovery_grant.status`, `step_up_grant.status` | `test_security_credential_revocation.py`, `test_security_session_transaction_postgres.py` (`TX02`–`TX10`) |
| **INV-07** Step-up Challenge 绑定完整上下文 | `step_up.(start_step_up_challenge, issue_step_up_grant)` | `chk_auth_challenge_stepup_context` | `test_step_up_challenge_context.py` (`SU01`–`SU12`, `RF-A20`) |
| **INV-08** Step-up Grant 禁跨用户/会话/用途/目标 | `step_up.(issue_step_up_grant, validate_step_up_grant)` | `chk_step_up_grant_email_target` | `test_step_up_challenge_context.py` (`SU13`–`SU18`) |
| **INV-09** 安全关键 DB 异常不触发弱化回退 | `session_guard.py`, `state_machine.py`, `schema_gate.py` | 移除全量 `SAVEPOINT` 降级 | `test_session_validation_fail_closed.py` (`F08`–`F11`), `test_security_delivery_fault_injection.py` |
| **INV-10** 有效幂等键不产生多个发送任务 | `idempotency.claim_http_idempotency`, `wait_for_idempotency_settlement` | `security_delivery_request` 唯一部分索引 + `execution_owner` | `test_security_http_idempotency.py`, `test_security_idempotency_crash_recovery.py` (`ID01`–`ID02`, `ID07`–`ID08`) |
| **INV-11** PII 清理不破坏合法执行中任务 | `sms_gateway.cleanup_delivery_tasks`, `ACTIVE_TASK_STATES` | `idx_sdr_state_created` | `test_security_idempotency_crash_recovery.py` (`ID09`–`ID11`), `test_delivery_pii_retention.py` |
| **INV-12** 外部副作用未知时不假定未发信 | `idempotency.mark_http_idempotency_unknown`, `delivery_models.transition_risk_checked` | `chk_sdr_execution_stage`, `outcome_unknown` | `test_security_idempotency_crash_recovery.py` (`ID03`–`ID05`, `ID14`), `test_security_delivery_fault_injection.py` |
| **INV-13** 数据库锁顺序全链路一致 | `app_user -> user_credential -> auth_challenge -> recovery_grant -> step_up_grant -> auth_session` | 行级 `FOR UPDATE` 顺序治理 + `db.run_with_deadlock_retry` | `test_security_session_transaction_postgres.py` (`TX01`–`TX14`) |
| **INV-14** 关键转换由真实 PG+Redis 测试验证 | 9 套存量 + 7 套新增 PG/Redis 实库测试 | 实时建 Schema 执行 `033`–`038` 全量 DDL 与约束 | CI 实库门禁 (`SMS_TEST_POSTGRES=1`) |
| **INV-15** 验收编号与证据可机器追溯 | `docs/auth/email-gateway/acceptance-manifest.yaml` | — | `test_security_acceptance_manifest.py` |

---

## 4. 真实 PostgreSQL 并发事务测试矩阵（TX01–TX14）

所有用例均在本地真实 **PostgreSQL 18.6 + Redis 3.0.504** 环境运行，`db.set_concurrency_retry_observer` 透明监听并统计真实 `40P01`（死锁）与 `40001`（序列化冲突）：

| 编号 | 并发场景 | 并发度 | `success_count` | `business_rejected_count` | `deadlock_count` | `handled_retries` | `serialization_failure_count` | `timeout_count` | `unexpected_error_count` | 最终状态与结论 |
|---|---|---|---|---|---|---|---|---|---|---|
| **TX01** | Refresh vs Refresh（同 `refreshToken`） | 8 线程 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 仅 1 线程轮换成功，其余 401，零异常 |
| **TX02** | Refresh vs Logout（3 轮同逻辑 SID） | 2 线程 × 3 轮 | 每轮 1 | 每轮 1 | 0 | 0 | 0 | 0 | 0 | 无论先后，最终 `(user_id, sid)` 活跃会话数为 0 |
| **TX03** | Refresh vs `change_password` | 2 线程 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | `session_version=2`，活跃 `auth_session` 数为 0 |
| **TX04** | Refresh vs `complete_password_recovery` | 2 线程 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | `session_version=2`，活跃 `auth_session` 数为 0 |
| **TX05** | Logout vs `issue_step_up_grant`（同 SID） | 2 线程 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 最终活跃 `step_up_grant` 数为 0 |
| **TX06** | Logout vs `validate_step_up_grant` | 2 线程 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 注销吊销生效，最终活跃 `step_up_grant` 数为 0 |
| **TX07** | `change_password` vs `complete_password_recovery` | 2 线程 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 胜出方撤回另一方凭证，严格互斥成功 1 次 |
| **TX08** | `start_email_binding` vs `change_password` | 2 线程 | 2 | 0 | 0 | 0 | 0 | 0 | 0 | 按全局锁序序列化，无死锁 |
| **TX09** | `verify_and_bind_contact` vs `complete_password_recovery` | 2 线程 | 1 | 1 | 0 | 0 | 0 | 0 | 0 | 最终活跃 `recovery_grant` 数为 0 |
| **TX10** | `password_login_session`(旧密码) vs `change_password` | 确定性阻塞交错 | 改密胜 | 登录拒 (`BizError`) | 0 | 0 | 0 | 0 | 0 | 锁外旧密码通过但锁内二次核验截断，活跃会话 0 |
| **TX11** | `verify_recovery_challenge` 同 Challenge | 8 线程 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 仅 1 线程签出 `recoveryGrant` |
| **TX12** | `complete_password_recovery` 同 Grant | 8 线程 | 1 | 7 | 0 | 0 | 0 | 0 | 0 | 仅 1 线程成功重置并置 `session_version=2` |
| **TX13** | 双用户并发绑定同一邮箱 | 2 线程 | 1 | 1 (409) | 0 | 0 | 0 | 0 | 0 | DB 唯一索引与行锁确保仅 1 用户成功 |
| **TX14** | 4 方并发风暴（登录/刷新/Step-up/全吊销） | 4 线程 | 2 | 2 | 0 | 0 | 0 | 0 | 0 | 统一锁序治理下零死锁、零未捕获异常 |

---

## 5. 异常与故障注入测试矩阵

| 注入点 | 模拟故障 | 系统实测安全行为 | 外部副作用 / 残留检查 | 验证用例 |
|---|---|---|---|---|
| **Auth DB 查询异常** | 连接失败 / 语句超时 (`57014`) / 缺表 (`42P01`) / 缺列 (`42703`) | 全部映射为 `UNAVAILABLE` → HTTP `503 TT_COMMON_50301` | 绝不降级 `LEGACY` 或放行 `ACTIVE` | `F08`–`F11` |
| **Schema 版本落后** | 仅迁移到 `037` 时执行 `schema_gate.assert_required_security_schema` | 生产模式 `APP_ENV=production` 直接抛 `RuntimeError` 阻断启动 | 缺失列/约束完整上报告警 | `test_security_delivery_fault_injection.py` |
| **Challenge 写库提交失败** | `_send_email` 创建阶段 DB `OperationalError` | 回滚 DB 事务、调用 `transition_risk_checked(..., "rejected")` 释放风控额度 | **Provider 调用次数 = 0** | `test_security_delivery_fault_injection.py` |
| **CAS 执行权争夺失败/DB 异常** | `claim_send_execution_right` 冲突/过期/取消/DB 抛错 | 抛出 `DeliveryStageError("send_claim", ..., provider_called=False)` | **Provider Spy 调用次数 = 0** | `S02`–`S08`, `S13`–`S14` |
| **Redis 风控状态回调异常** | `engine.transition` 返回 `False` 或抛 `ConnectionError` | 记录结构化诊断日志并递增 `risk_transition_failed_total` | 不覆盖或推翻 PG 已提交发送状态 | `test_security_delivery_fault_injection.py` |
| **Provider 发送超时未知** | `ProviderError(..., outcome_unknown=True)` | `send_state='unknown'`, 保持 `status='pending'` 原码不覆盖 | 同幂等键锁定，禁止自动重发 | `test_security_delivery_fault_injection.py` |
| **发送后回执持久化失败** | `sending -> accepted` 提交抛异常 | 抛出 `DeliveryStageError("receipt_persist", outcome_unknown=True)` | Provider 严格只调用 1 次，无重试 | `S12` |
| **发送后幂等响应落盘失败** | `routes.me.finalize_http_idempotency` 抛 `RuntimeError` | `mark_http_idempotency_unknown()` 返回 HTTP `503` | 同 `Idempotency-Key` 重试继续返回 `503` 且无二次发信 | `ID03`–`ID05`, `ID14` |
| **重置密码审计写失败回滚** | `complete_password_recovery` 提交前抛 `RuntimeError` | 完整回滚密码与吊销状态，`auth_cache.invalidate_user` 触发次数 **= 0** | 事务提交前绝不提前污染缓存 | `test_security_credential_revocation.py` |

---

## 6. 数据库增量迁移（038）与回滚方案

### 6.1 `038_phase_r_final_security.sql` 变更内容

1. **`auth_challenge`**：
   - 新增列：`session_version INT`、`source_contact_fingerprint VARCHAR(64)`、`send_owner VARCHAR(64)`、`send_claimed_at TIMESTAMPTZ`。
   - 历史脏数据收敛：将缺失 `session_id` / `sub_purpose` /（对邮箱绑定/换绑缺失 `target_fingerprint`）的未终结 `step_up_auth` 记录收敛为 `status = 'cancelled'`。
   - 新增检查约束：`chk_auth_challenge_stepup_context` 与部分索引 `idx_auth_challenge_sending_claimed`。
2. **`security_delivery_request`**：
   - 新增列：`execution_owner VARCHAR(64)`、`execution_stage VARCHAR(32) NOT NULL DEFAULT 'pre_provider'`、`challenge_id UUID`、`idem_claimed_at TIMESTAMPTZ DEFAULT NULL`。
   - 历史脏数据收敛：历史行未在 `038` 中回填 `execution_stage`（历史阶段 provenance 分类与 `legacy_unknown` 保守降级由 `039_phase_r_hotfix.sql` 补全）；`038` 收敛了超过 5 分钟未结算的 `idem_pending` 占位记录并剥离遗留明文 PII 字段。
   - 新增检查约束：`chk_sdr_execution_stage`（限定 `pre_provider` / `send_claimed` / `provider_called` / `provider_accepted` / `provider_rejected` / `provider_unknown` / `response_persisted`，`039` 扩展 `legacy_unknown`）与索引 `idx_sdr_state_created`。
3. **`step_up_grant`**：吊销历史缺少 `session_id` 的活跃 `bind_email` / `rebind_email` Grant（保留 `session_id` 可空以兼容历史过期审计记录）。
4. **`auth_session`**：新增复合部分索引 `idx_auth_session_user_sid_status (user_id, sid, status) WHERE sid IS NOT NULL`。

### 6.2 升级与回滚指引

- **升级步骤**：
  1. 备份核心安全表（`auth_challenge`, `security_delivery_request`, `step_up_grant`, `auth_session`）。
  2. 执行 `038_phase_r_final_security.sql`（全脚本幂等可重复执行）。
  3. 启动期由 `schema_gate.assert_required_security_schema()` 校验 `038` 列与约束全量就绪。
- **回滚策略（仅在代码回退至上一版本时使用）**：
  - `038` 新增列均为独立扩展字段且不影响旧列读写，如需回滚代码，建议采用**向前兼容保留列**（仅撤销 `DROP CONSTRAINT chk_auth_challenge_stepup_context` / `chk_sdr_execution_stage`）以避免锁表删除列导致生产停顿；切勿直接修改历史迁移文件 `033`–`037`。

---

## 7. 性能与多实例一致性实测数据（PG 18.6 + Redis 3.0.504）

由本地实测基准脚本采集（错误率均为 `0.0000`）：

| 测试项目 | 样本量 (`N`) | SQL/次 | P50 (ms) | P95 (ms) | P99 (ms) | Mean (ms) | 锁持有 P95 (ms) |
|---|---|---|---|---|---|---|---|
| `sid_validation`（单 SQL `app_user+auth_session`） | 300 | 1.0 | 0.481 | 0.912 | 1.110 | 0.554 | — |
| `step_up_grant_issue_recent_auth` | 200 | 5.0 | 1.309 | 2.183 | 2.481 | 1.352 | 1.938 |
| `step_up_grant_issue_password`（含口令哈希验证） | 40 | 5.0 | 25.497 | 27.399 | 27.566 | 25.773 | 26.960 |
| `challenge_create`（`_send_email` + Redis Reserve/Transition） | 200 | 7.0 | 2.201 | 3.385 | 5.163 | 2.455 | 1.113 |
| `challenge_verify`（`verify_recovery_challenge`） | 200 | 7.0 | 1.110 | 1.836 | 2.184 | 1.234 | 1.492 |
| `http_idempotency_new_and_finalize` | 200 | 3.0 | 0.667 | 1.442 | 1.610 | 0.764 | — |
| `http_idempotency_replay`（`FOR UPDATE` 命中缓存） | 200 | 3.0 | 0.441 | 0.822 | 1.021 | 0.502 | 0.332 |
| `cas_claim_and_accept`（发送权认领+回执落盘） | 200 | 2.0 | 0.804 | 1.477 | 1.909 | 0.900 | — |
| `refresh_token_rotation`（单链 200 次旋转） | 200 | 12.0 | 1.343 | 2.662 | 2.960 | 1.508 | 1.935 |

**结论**：现代 SID 每请求单 SQL 校验配合 `idx_auth_session_user_sid_status` 索引在 PG 18.6 下 P99 仅为 `1.110ms`，在无需共享本地失效通知总线的前提下保证多 Worker/多实例零延迟会话撤销一致性。已知工程观察：`issue_step_up_grant(method="password")` 的 `verify_password` 目前仍在 `FOR UPDATE` 行锁内执行（锁持有 P95=`26.960ms`），可作为后续微优化项但未见实测并发死锁或超时影响。

---

## 8. 残余风险与最终未运行外部条款说明

1. **`EXT-EMAIL-01` / `EXT-EMAIL-02` / `EXT-EMAIL-03` 保持 `NOT RUN`**：受真实公网 SMTP / 腾讯云 SES 凭据与禁止向真实外部发送邮件策略约束，本轮严守禁令未执行外部真发信，所有发信由 Spy / Mock Provider 严格替代并核对调用次数及状态转换。
2. **线上 `/admin/users` 账号禁用写接口**：当前仓库 `modules/admin/service.py` `/admin/users` 为只读视图，账号禁用对会话及恢复凭据的阻断已在真实 PG 测试 `test_rebind_contact_and_user_disable_revoke_old_credentials` 中通过 SQL `UPDATE app_user SET status='disabled'` 完整覆盖。
3. **`issue_step_up_grant` 口令验证持锁时长**：当前密码学口令验证置于行锁内部（实测 40 次 P95=`26.960ms`），若高并发场景需要更短行锁，后续可拆分为同 `login` 类似的“锁外初筛 + 锁内复核”。
