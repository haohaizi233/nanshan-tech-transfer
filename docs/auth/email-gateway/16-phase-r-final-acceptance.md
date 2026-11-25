# 南山科转通 Phase R-Final 最终上线验收报告

> **[HISTORICAL SNAPSHOT / 历史快照说明]** 本文档为 Phase R-Final 阶段的历史验收快照（仅反映基线提交时点结论），已被 [17-phase-r-hotfix-acceptance.md](./17-phase-r-hotfix-acceptance.md) 与动态证据清单 [acceptance-manifest.yaml](./acceptance-manifest.yaml) 取代；最新上线门禁与实测证据以 `17-phase-r-hotfix-acceptance.md` 及 `scripts/verify_acceptance_evidence.py` 为准。

> 仓库：`haohaizi233/nanshan-tech-transfer`  
> 分支：`feat/phase-r-final-security`（基线提交 `5f0d00aee3a3a869f52b790a72e74bf26908672c`）  
> 数据库增量：`migrations/pg/038_phase_r_final_security.sql`（历史 `033`–`037` 未变更）  
> **最终验收结论：`CODE_ACCEPTED`（暂不标记 `PRODUCTION_READY`；待真实生产配置完成 `EXT-EMAIL-01`–`03` 外部投递检查与 Staging 实库 `038` 演练后方可放行全量上线）**

---

## 1. 全量实测检验结果汇总

| 检验维度 | 执行范围 / 命令 | 实测结果 | 备注 |
|---|---|---|---|
| **后端全量单元测试 + PG/Redis 实库集成** | `pytest -p no:cacheprovider --cov=. --cov-report=term-missing --cov-fail-under=75 -q`（`SMS_TEST_POSTGRES=1`, `SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15`） | **2570 passed, 31 skipped；总覆盖率 89.49% (110.00s)** | 31 项 skipped 全部为非安全模块 `test_ai_chat_runs_pg.py`（未配置 `AI_TEST_POSTGRES`） |
| **安全网关 PG 18.6 + Redis 3.0.504 专项** | CI 指定 20 个安全与契约专项测试文件（12 存量 + 7 新增实库 + Manifest 校验） | **79 passed, 0 failed, 0 skipped (86.09s)** | `TX01`–`TX14` 零死锁、零序列化异常、零未捕获错误 |
| **安全核心阻断式 `mypy`** | `mypy modules/security core/jwt_utils.py core/middleware.py --ignore-missing-imports --no-strict-optional --show-error-codes` | **0 errors（23 个源文件通过）** | `core/middleware.py` 已纳入 CI 阻断检查 |
| **代码规范 `ruff check` & `ruff format`** | `ruff check .` & `ruff format --check .` | **All checks passed / 282 files formatted** | CI lint & format 双门禁通过 |
| **AI Agent 服务测试** | `nanshan-ai-agent`: `python -m pytest -p no:cacheprovider -q` | **157 passed, 67 subtests passed** | — |
| **管理端 H5 (`nanshan-frontend`)** | `node --test src/utils/*.test.mjs tests/*.test.mjs` + `npm run build` | **53 passed, 0 failed；Vite build 成功 (449ms)** | 包含 `inFlight: true` 幂等重用回归 |
| **用户端 / 微信小程序 (`南山小程序/南山`)** | `node --test tests/*.test.mjs` + `npm run build:h5` + `npm run build:mp-weixin` | **418 passed, 0 failed；H5 与微信小程序双端编译通过** | 包含 `inFlight: true` 幂等重用回归 |

---

## 2. 全量可追溯验收矩阵（`A01`–`A30`、`R-A01`–`R-A32`、`RF-A01`–`RF-A42`、`EXT-EMAIL-01`–`03`）

全部 107 项条目亦由机器可读清单 [acceptance-manifest.yaml](docs/auth/email-gateway/acceptance-manifest.yaml) 锁定，并经 [test_security_acceptance_manifest.py](tech-transfer-service/tests/test_security_acceptance_manifest.py) 校验编号不可篡改、非外部条目全部具备真实源码及测试证据且 `EXT-EMAIL-01`–`03` 严格维持 `NOT RUN`：

### 2.1 原始 `A01`–`A30`（30/30 恢复并通过）

| 编号 | 条款名称 | 状态 | 核心证据测试 |
|---|---|---|---|
| `A01` | 生产环境无法使用 Mock Email | PASS | `test_email_provider.py` |
| `A02` | `EMAIL_ENABLED=false` 时无法真实发信 | PASS | `test_email_recovery_e2e.py` |
| `A03` | 未知 Provider 不会静默回退 | PASS | `test_email_provider.py` |
| `A04` | OTP、Token、Grant 不进入日志 | PASS | `test_email_recovery_e2e.py`, `test_email_diagnostics.py` |
| `A05` | Redis 异常时生产发送 Fail-Closed | PASS | `test_email_risk.py` |
| `A06` | 未确权邮箱无法用于账号恢复 | PASS | `test_recovery_anti_enumeration.py`, `test_email_gateway_postgres.py` |
| `A07` | 安全邮箱换绑具备二次认证 | PASS | `test_email_binding_security.py` |
| `A08` | Challenge 与 Grant 不可重复消费 | PASS | `test_email_gateway_postgres.py`, `test_email_binding_security.py` |
| `A09` | 邮件发送失败不会残留错误有效挑战 | PASS | `test_email_challenge.py` |
| `A10` | 真实数据库并发核验通过 | PASS | `test_email_gateway_postgres.py` |
| `A11` | 邮件链接 GET 无不可逆副作用 | PASS | `test_email_recovery_e2e.py` |
| `A12` | 密码重置后旧会话失效 | PASS | `test_security_credential_revocation.py` |
| `A13` | SMTP 错误分类完整 | PASS | `test_email_smtp.py` |
| `A14` | SES 请求与响应契约测试通过 | PASS | `test_email_ses.py` |
| `A15` | 多维原子风控完整 | PASS | `test_email_risk.py` |
| `A16` | 投递任务具备应用内部幂等性 | PASS | `test_sms_gateway_postgres.py` |
| `A17` | 供应商结果未知时不会盲目重发 | PASS | `test_email_challenge.py`, `test_security_idempotency_crash_recovery.py` |
| `A18` | 邮件结构化投递 Receipt | PASS | `test_email_delivery_results.py` |
| `A19` | 邮件故障诊断工具可用 | PASS | `test_email_diagnostics.py` |
| `A20` | 邮件模板工程化 | PASS | `test_email_provider.py`, `test_email_ses.py` |
| `A21` | H5 邮箱流程正常 | PASS | `nanshan-frontend/src/utils/emailSecurity.test.mjs`, `nanshan-frontend/tests/adminViews.test.mjs` |
| `A22` | 微信小程序邮箱流程正常 | PASS | `南山小程序/南山/tests/unified-auth-security.test.mjs` |
| `A23` | 数据库增量迁移兼容 | PASS | `test_email_gateway_postgres.py`, `test_security_delivery_fault_injection.py` |
| `A24` | 原有 SMS Gateway 全量回归 | PASS | `test_sms_gateway_postgres.py` |
| `A25` | 微信登录及注册流程无回归 | PASS | `test_wechat_login.py` |
| `A26` | 邮箱专项测试进入 CI | PASS | `test_security_acceptance_manifest.py` |
| `A27` | 部署及送达验收文档完整 | PASS | `10-deployment-runbook.md`, `15-phase-r-final-hardening.md`, `16-phase-r-final-acceptance.md` |
| `A28` | 密码找回接口防账号枚举 | PASS | `test_recovery_anti_enumeration.py`, `test_email_recovery_e2e.py` |
| `A29` | 风控及投递日志完成脱敏 | PASS | `test_email_diagnostics.py`, `test_email_risk.py` |
| `A30` | 代码及文档实际行为一致 | PASS | `test_security_acceptance_manifest.py` |

### 2.2 Phase R `R-A01`–`R-A32`（32/32 恢复并通过）

| 编号 | 条款名称 | 状态 | 核心证据测试 |
|---|---|---|---|
| `R-A01` | 首次绑定安全邮箱必须满足敏感操作授权策略 | PASS | `test_email_first_binding.py` |
| `R-A02` | 已绑定邮箱换绑必须通过 Step-up | PASS | `test_email_binding_security.py`, `test_email_first_binding.py` |
| `R-A03` | JWT 刷新不会推进真实 `auth_time` | PASS | `test_security_auth_time.py` |
| `R-A04` | 旧 Token 不会自动获得近期认证资格 | PASS | `test_security_auth_time.py`, `test_session_validation_fail_closed.py` |
| `R-A05` | Step-up Grant 强制绑定用途及目标 | PASS | `test_email_first_binding.py`, `test_step_up_challenge_context.py` |
| `R-A06` | Grant 不可跨账号、跨会话消费 | PASS | `test_security_auth_time.py`, `test_step_up_challenge_context.py` |
| `R-A07` | 密码重置、邮箱绑定锁顺序统一 | PASS | `test_security_cross_transaction_postgres.py`, `test_security_session_transaction_postgres.py` |
| `R-A08` | 真实交叉事务并发测试无未处理死锁 | PASS | `test_security_cross_transaction_postgres.py`, `test_security_session_transaction_postgres.py` |
| `R-A09` | 同一 Challenge 并发核验仅成功一次 | PASS | `test_security_cross_transaction_postgres.py`, `test_step_up_challenge_context.py` |
| `R-A10` | 同一 Grant 并发消费仅成功一次 | PASS | `test_security_cross_transaction_postgres.py` |
| `R-A11` | 匿名恢复核验失败公开语义一致 | PASS | `test_recovery_anti_enumeration.py` |
| `R-A12` | 防枚举改造不影响真实失败次数累加 | PASS | `test_recovery_anti_enumeration.py` |
| `R-A13` | 高权限账号不会通过弱认证建立恢复渠道 | PASS | `test_email_first_binding.py` |
| `R-A14` | 已关闭认证状态不可被投递回执重新激活 | PASS | `test_delivery_state_cas.py` |
| `R-A15` | 同一 HTTP 幂等请求不会重复创建任务 | PASS | `test_security_http_idempotency.py` |
| `R-A16` | 同一幂等请求不会重复消耗真实发送额度 | PASS | `test_security_http_idempotency.py`, `test_security_idempotency_crash_recovery.py` |
| `R-A17` | 幂等冲突能够正确识别 | PASS | `test_security_http_idempotency.py`, `test_security_idempotency_crash_recovery.py` |
| `R-A18` | Provider unknown 不会盲目重发 | PASS | `test_delivery_state_cas.py`, `test_security_idempotency_crash_recovery.py` |
| `R-A19` | 投递状态转换采用真实状态 CAS | PASS | `test_delivery_state_cas.py`, `test_security_provider_execution_right.py` |
| `R-A20` | Worker 崩溃恢复具备明确安全边界 | PASS | `test_delivery_pii_retention.py`, `test_security_idempotency_crash_recovery.py` |
| `R-A21` | 所有异常终止路径执行必要 PII 清理 | PASS | `test_delivery_pii_retention.py`, `test_security_idempotency_crash_recovery.py` |
| `R-A22` | Provider 切换后历史回执不会错误查询 | PASS | `test_email_provider_reconciliation.py` |
| `R-A23` | 供应商日志与诊断数据完成脱敏 | PASS | `test_email_diagnostics.py`, `test_email_provider_reconciliation.py` |
| `R-A24` | H5 首次绑定和换绑正常 | PASS | `nanshan-frontend/tests/adminViews.test.mjs` |
| `R-A25` | 微信小程序首次绑定和换绑正常 | PASS | `南山小程序/南山/tests/unified-auth-security.test.mjs` |
| `R-A26` | 原 SMS Gateway 不发生安全回归 | PASS | `test_sms_gateway_postgres.py` |
| `R-A27` | 微信登录、刷新、注销无回归 | PASS | `test_wechat_login.py`, `test_security_session_transaction_postgres.py` |
| `R-A28` | 数据库迁移支持历史数据升级 | PASS | `test_email_gateway_postgres.py`, `test_security_delivery_fault_injection.py` |
| `R-A29` | 新增安全测试实际进入 CI | PASS | `test_security_acceptance_manifest.py` |
| `R-A30` | 原始 A01–A30 验收编号完整恢复 | PASS | `test_security_acceptance_manifest.py` |
| `R-A31` | 本轮新增安全模块无未解释类型问题 | PASS | `test_security_acceptance_manifest.py` |
| `R-A32` | 真实外部投递验收未执行时明确 NOT RUN | PASS | `test_security_acceptance_manifest.py` |

### 2.3 Phase R-Final `RF-A01`–`RF-A42` 与外部条款 `EXT-EMAIL-01`–`03`

- **`RF-A01`–`RF-A42`（42/42 PASS）**：完整覆盖不存在/异常 SID Fail-Closed（`RF-A01`–`RF-A04`）、发送执行权门禁与零幽灵发送（`RF-A05`–`RF-A09`）、跨事务锁序与全量撤销（`RF-A10`–`RF-A15`）、Step-up 全上下文与防绕过（`RF-A16`–`RF-A20`）、`SAVEPOINT` 消除与 038 Schema Gate（`RF-A21`–`RF-A22`）、HTTP 幂等全生命周期/503 防重放/PII 保护（`RF-A23`–`RF-A28`）、PG/Redis 状态协同与抗断（`RF-A29`–`RF-A30`）、验收清单不可变门禁与全端/迁移/类型/`mypy`/CI/实测性能证据与诚实结论标记（`RF-A31`–`RF-A42`）。
- **`EXT-EMAIL-01`–`03`（3/3 `NOT RUN`）**：真实 SMTP 投递、真实腾讯云 SES 投递、以及生产域名 SPF/DKIM/DMARC 核查未授权真实外发，明确记为 `NOT RUN`。

---

## 3. 上线前人工必检清单

1. **生产 / Staging PostgreSQL 迁移**：执行 `migrations/pg/038_phase_r_final_security.sql`，确认 `schema_gate.check_required_security_schema()` 返回 `{"ok": true}`。
2. **外部真发信与域名验收（关闭 `EXT-EMAIL-01`–`03`）**：使用受控测试收件箱与正式 SMTP/SES 凭据完成送达、链接恢复、Receipt 回查及 SPF/DKIM/DMARC 核验。
3. **CI 流水线验证**：推送 `feat/phase-r-final-security` 并确认 GitHub Actions `test`（含 PostgreSQL 16 + Redis 7 全量 20 项安全实库套件）、`lint`（含阻塞式 `mypy`）、`ruff-format` 与 `frontend` 全部绿灯。
