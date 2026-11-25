# Phase R-Hotfix 最终安全收敛验收报告

> **状态声明**：本报告反映 **Phase R-Hotfix** 在本地全量验证与可执行证据门禁下的代码级验收结论。真实外部邮件投递与域名鉴权检查（`EXT-EMAIL-01`–`EXT-EMAIL-03`）严格保持 **`NOT RUN`**，因此最终结论为 **`CODE_ACCEPTED`**，不宣称 **`PRODUCTION_READY`**。

---

## 1. 基线与变更元数据

| 项目 | 值 |
|---|---|
| Repository | `haohaizi233/nanshan-tech-transfer` |
| Development Branch | `fix/phase-r-final-hotfix` |
| Base Commit SHA | `a68d5a367ee8007f33b1e227b83683860a068597` (`a68d5a3 docs(memory): 记录 Phase R 收尾 PR #2 合入`) |
| Added Database Migration | `tech-transfer-service/migrations/pg/039_phase_r_hotfix.sql` |
| Schema Gate Version | `REQUIRED_SECURITY_SCHEMA_VERSION = "039"` (`tech-transfer-service/modules/security/schema_gate.py`) |
| Historical Migrations (`033`–`038`) | **零修改**（已通过 `git diff` 核实） |
| Acceptance Manifest | `docs/auth/email-gateway/acceptance-manifest.yaml`（共 132 项：129 项动态门禁 + 3 项 `NOT RUN` 外部烟雾测试） |
| Verdict | **`CODE_ACCEPTED`**（非 `PRODUCTION_READY`） |

---

## 2. HF01–HF05 缺陷修复摘要

### HF01：跨状态机双执行权与幂等阶段 CAS 门禁（P0/P1 阻断）
- 在 `tech-transfer-service/modules/security/idempotency.py` 中收敛状态/阶段常量，新增 `read_http_idempotency_record()`，移除 `advance_idempotency_stage()` 等关键 CAS 中 `execution_owner IS NULL OR` 越权通配绕过，严格绑定 `execution_owner`、`scope`、`idempotency_key` 与活跃态。
- 在 `tech-transfer-service/modules/security/state_machine.py` 的 `claim_send_execution_right()` 中引入同一事务联合 CAS（锁序严格遵循 `security_delivery_request -> auth_challenge`）：HTTP 幂等发送路径要求同时持有合法幂等执行权与 Challenge 发送权；任一失败或冲突整笔事务原子回滚（`0` 次外部 Provider 调用）。
- 在 `email_gateway.py`、`sms_gateway.py`、`step_up.py`、`routes/auth.py`、`routes/me.py` 中严格消费 `advance_idempotency_stage()` 与 `finalize_http_idempotency()` 返回值：CAS 失败或数据库异常时立即 Fail-Closed（返回 `503`），严禁继续调用外部 Provider、禁止返还伪成功响应、禁止在 `/auth/recovery/start` 调度后台投递任务、禁止错误释放幂等键；无 `Idempotency-Key` 历史兼容请求仍严格受 `auth_challenge` CAS 保护。

### HF02：`unknown` / `legacy_unknown` 保留窗口一致性与状态收敛（P0/P1 阻断）
- 在 `tech-transfer-service/config.py` 中统一配置 `IDEMPOTENCY_REQUEST_TTL_SECONDS`、`IDEMPOTENCY_EXECUTION_OWNERSHIP_SECONDS`、`IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS` 及边界校验。
- 统一 `idempotency.py` 认领/释放策略与 `sms_gateway.py::cleanup_delivery_tasks()` PII 清理保留期：`unknown` 与 `legacy_unknown` 不因常规 300s `idempotency_expires_at` 到期而提前释放或清除重放锁，统一保留至 `IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS` 期满。
- `pre_provider` 释放严格校验显式阶段、`stage_provenance` 与关联 `auth_challenge` 非外呼状态；`email_gateway.py::reconcile_email_delivery()` 与 `sms_gateway.py::reconcile_sms_delivery()` 联动收敛关联 `challenge_id` 的未知幂等任务状态。

### HF03：039 增量迁移与历史阶段保守推断（P1）
- 新增严格增量且可幂等重入的数据库迁移脚本 `tech-transfer-service/migrations/pg/039_phase_r_hotfix.sql`：
  - 新增 `security_delivery_request.stage_provenance` 及约束 `chk_sdr_stage_provenance`；扩展 `chk_sdr_execution_stage` 以显式容纳 `'legacy_unknown'`。
  - 仅在具备明确审计证据时回填 `legacy_proven_sent` 与 `legacy_proven_not_sent`；对于 `038` 默认 `pre_provider` 模糊行及退化过期行保守收敛为 `legacy_unknown`，不伪造已清理键、不触发自动补发。
- 将 `schema_gate.py::REQUIRED_SECURITY_SCHEMA_VERSION` 升级至 `"039"`，强制校验新增字段与约束存在性。
- 全量更新 16 个 PostgreSQL 集成测试固件以应用 `039_phase_r_hotfix.sql`，验证 `033–037 -> 038 -> 039`、`038 -> 039` 及全量建表均可幂等收敛，且 **未修改任何历史迁移文件 `033`–`038`**。

### HF04：Redis 风控协调持久化状态与后台补偿（P2）
- 在 `039_phase_r_hotfix.sql` 中为 `auth_challenge` 增加 `risk_sync_*` 持久化字段、约束及部分索引 `idx_auth_challenge_risk_sync_pending`；在 `config.py` 新增 `RISK_SYNC_MAX_ATTEMPTS`、`RISK_SYNC_RETRY_BASE_SECONDS`、`RISK_SYNC_RETRY_MAX_SECONDS`。
- `state_machine.py::transition_delivery_state()` 在同事务内原子持久化 `risk_sync_state = 'sync_pending'` 与 `risk_sync_target`；`email_gateway.py`、`sms_gateway.py`、`step_up.py` 在提交数据库投递终态后驱动 Redis 协调。
- `delivery_models.py::transition_risk_checked()` 在 Redis 异常时落盘 `retryable_failure` 及有界指数退避下次重试窗口；`delivery_models.py::reconcile_pending_risk_syncs()` 基于 `FOR UPDATE SKIP LOCKED` 短租约在事务锁外扫描并在不调用 Provider、不篡改 Challenge `status` / `send_state` 的前提下补偿至 `synced`，并将键缺失、状态冲突与超限失败分别精准收敛为 `reservation_missing`、`conflict`、`manual_review_required`。

### HF05：可执行验收 Manifest、历史文档校正与 CI 证据门禁（P2）
- 为 `12-final-acceptance.md`、`14-phase-r-acceptance.md`、`16-phase-r-final-acceptance.md` 添加 `HISTORICAL SNAPSHOT` 声明横幅；修正 `15-phase-r-final-hardening.md` 中 `038` 迁移表结构的历史表述偏差。
- 重构 `docs/auth/email-gateway/acceptance-manifest.yaml`（共 132 项：`A01–A30`、`R-A01–R-A32`、`RF-A01–RF-A42`、`HF-A01–HF-A25`、`EXT-EMAIL-01–03`），清除所有自动化条目静态 `status: PASS`。
- 新增 `tech-transfer-service/scripts/verify_acceptance_evidence.py`，强制校验不可变编号、源文件存在性、Python 测试 AST / JS 测试标题及真实 JUnit XML 通过状态（支持类作用域方法 `classname` 精确匹配）；同步接入 `.github/workflows/ci.yml` 与 `tests/test_security_acceptance_manifest.py` 回归测试。

---

## 3. 历史迁移零改动证明（`033`–`038`）

针对基线提交 `a68d5a367ee8007f33b1e227b83683860a068597` 执行迁移文件范围差异比对：

```powershell
git diff -- a68d5a367ee8007f33b1e227b83683860a068597 -- `
  tech-transfer-service/migrations/pg/033* `
  tech-transfer-service/migrations/pg/034* `
  tech-transfer-service/migrations/pg/035* `
  tech-transfer-service/migrations/pg/036* `
  tech-transfer-service/migrations/pg/037* `
  tech-transfer-service/migrations/pg/038*
```

- **结果**：命令退出码 `0`，输出为空（0 字符差异），确认 `033`–`038` 历史迁移文件未作任何修改。
- 数据库 Schema 演进完全由新增文件 `tech-transfer-service/migrations/pg/039_phase_r_hotfix.sql` 增量完成。

---

## 4. HF-A01–HF-A25 验收映射清单

所有条目在 `acceptance-manifest.yaml` 中均以 `evidence_type: pg_redis_integration` 与 `expected_outcome: PASS` 受 JUnit XML + AST 门禁实时核验（无静态 `PASS`）：

| 编号 | 验证主题 | 对应测试文件（节点详见 Manifest） |
|---|---|---|
| `HF-A01` | `advance_idempotency_stage` 返回 `False` 时严禁 Mail/SMS/Step-up 调用外部 Provider（0 次外呼） | `tests/test_security_provider_execution_right.py` |
| `HF-A02` | `advance_idempotency_stage` 数据库异常时 Fail-Closed 且不触发外呼 | `tests/test_security_provider_execution_right.py` |
| `HF-A03` | `advance_idempotency_stage` 绑定 `execution_owner`、`scope`、`key` 与活跃态，禁止 `NULL` 越权 | `tests/test_security_idempotency_crash_recovery.py` |
| `HF-A04` | 双重执行权（`security_delivery_request -> auth_challenge`）同事务联合 CAS 获取 | `tests/test_security_provider_execution_right.py` |
| `HF-A05` | `auth_challenge` CAS 失败或过期时整笔联合事务原子回滚，0 次发信 | `tests/test_security_provider_execution_right.py` |
| `HF-A06` | 幂等所有权或阶段冲突时立即拒绝发送权，Challenge 保持 `reserved` | `tests/test_security_provider_execution_right.py` |
| `HF-A07` | `finalize_http_idempotency` 返回 `False` 或冲突时 Fail-Closed（`503`），不返回伪成功/不重发/不释放键 | `tests/test_security_provider_execution_right.py` |
| `HF-A08` | `/auth/recovery/start` 在 `finalize_http_idempotency` 失败时禁止调度后台投递任务 | `tests/test_security_provider_execution_right.py` |
| `HF-A09` | 无 `Idempotency-Key` 历史兼容请求仍严格执行单次提交 Challenge 发送权 CAS | `tests/test_security_provider_execution_right.py` |
| `HF-A10` | `unknown` / `legacy_unknown` 幂等键不因常规 300s `idempotency_expires_at` 到期而提前释放 | `tests/test_security_idempotency_crash_recovery.py`, `tests/test_delivery_pii_retention.py` |
| `HF-A11` | `claim_http_idempotency` 与 `cleanup_delivery_tasks` 统一遵守 `IDEMPOTENCY_UNKNOWN_RETENTION_SECONDS` | `tests/test_security_idempotency_crash_recovery.py` |
| `HF-A12` | 确定终态（非 unknown）按常规 `IDEMPOTENCY_REQUEST_TTL_SECONDS` 安全轮转 | `tests/test_security_idempotency_crash_recovery.py` |
| `HF-A13` | `pre_provider` 释放与 PII 清理校验显式阶段、`stage_provenance` 与非外呼态 | `tests/test_security_idempotency_crash_recovery.py` |
| `HF-A14` | `reconcile_email_delivery` / `reconcile_sms_delivery` 按 `challenge_id` 联动收敛未知幂等任务 | `tests/test_security_idempotency_crash_recovery.py` |
| `HF-A15` | `039_phase_r_hotfix.sql` 增量幂等，支持 `033–037->038->039`、`038->039` 与全量新建（零改动 `033–038`） | `tests/test_security_delivery_fault_injection.py` |
| `HF-A16` | `039` 仅在具备明确证据时回填 `legacy_proven_sent` 与 `legacy_proven_not_sent` | `tests/test_security_delivery_fault_injection.py` |
| `HF-A17` | `039` 将模糊/退化行保守降级为 `legacy_unknown`，不伪造清理键且不补发 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A18` | `schema_gate.py` 升级至 `039` 并阻断缺列数据库启动 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A19` | `transition_delivery_state` 同事务原子写入 `risk_sync_state='sync_pending'` 与目标态 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A20` | Redis 异常时 `transition_risk_checked` 落盘 `retryable_failure` 及有界指数退避时间窗 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A21` | Redis 恢复后 `reconcile_pending_risk_syncs` 锁外补偿至 `synced`，0 次外呼且不改认证状态 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A22` | Redis 键缺失、状态冲突与超限失败分别收敛为 `reservation_missing` / `conflict` / `manual_review_required` | `tests/test_security_delivery_fault_injection.py` |
| `HF-A23` | 多 Worker 并发执行 `reconcile_pending_risk_syncs` 基于 `SKIP LOCKED` 无冲突无死锁 | `tests/test_security_delivery_fault_injection.py` |
| `HF-A24` | 清单取消静态 `PASS`、历史文档标注 `Historical Snapshot` 且 `15` 文档修正为真实 Schema | `tests/test_security_acceptance_manifest.py` |
| `HF-A25` | `verify_acceptance_evidence.py` 与 CI 按 AST 及 JUnit XML 执行证据阻断校验通过 | `tests/test_security_acceptance_manifest.py` |

---

## 5. 本轮实测验证汇总（最终代码编辑之后执行）

> 以下结果均为最终 `.py` 代码定稿后实测直接观测输出；本地测试环境连接 PostgreSQL (`postgresql://mac:test@127.0.0.1:5432/tech_transfer_test`) 与 Redis (`redis://127.0.0.1:6379/15`)。

| 检查项 | 执行命令 / 范围 | 实测结果 | 备注 |
|---|---|---|---|
| **Security PG/Redis 20-File CI Integration** | `pytest -p no:cacheprovider <20 security test files> --junit-xml=security-junit.xml -q` | **`86 passed in 98.96s (0:01:38)`** | 0 failed, 0 skipped；`security-junit.xml` 用作门禁输入 |
| **Full Backend Suite & Coverage** | `pytest --cov=. --cov-report=term-missing --cov-fail-under=75 --junit-xml=junit.xml -q` | **`2577 passed, 31 skipped, 1 warning in 121.81s (0:02:01)`**；覆盖率 **`88.95%`**（`13924` stmts, `1539` missed） | 31 skipped 均为 `tests/test_ai_chat_runs_pg.py`（未设置 `AI_CHAT_TEST_DATABASE_URL`）；`24 empty files skipped` |
| **Executable Acceptance Evidence Gate** | `python scripts/verify_acceptance_evidence.py --junit-xml security-junit.xml --junit-xml junit.xml` | **`[OK] Verified 132 manifest requirements (junit_nodes_verified=177, scope=all)`** | 定稿本报告后追加 `--require-report-doc` 全量复核 |
| **Ruff Lint & Format** | `ruff check .`；`ruff format --check .` | **`All checks passed!`**；**`283 files already formatted`** | 0 issues |
| **Blocking Security Mypy** | `mypy modules/security core/jwt_utils.py core/middleware.py --ignore-missing-imports --no-strict-optional --show-error-codes` | **`Success: no issues found in 23 source files`** | 另 `mypy scripts/verify_acceptance_evidence.py`: `Success: no issues found in 1 source file` |
| **Full Repo Mypy (CI Non-blocking)** | `mypy . --ignore-missing-imports --no-strict-optional --show-error-codes` | 退出码 `1`（既有配置问题：`tools\run_ai_chat_worker.py` 模块双路径映射报错） | 非本次改动引入；安全阻断门禁以行内 Blocking Gate 为准 |
| **flake8 / gh CLI** | `Get-Command flake8` / `gh run list` | **未安装 / 未执行** | 本地环境未安装 `flake8` 与 `gh` CLI；待推送后由 GitHub CI 运行 |
| **AI Agent Suite** | `cd nanshan-ai-agent; python -m pytest -q` | **`157 passed, 67 subtests passed in 56.48s`** | 0 failed, 0 skipped |
| **Admin Frontend (H5/Admin)** | `cd nanshan-frontend; node --test src/utils/*.test.mjs tests/*.test.mjs; npm run build` | **`tests 53, pass 53, fail 0, skipped 0 (671.1941ms)`**；`vite v8.2.2` 构建 `103 modules transformed` | 0 failed |
| **Mini Program & H5** | `cd 南山小程序/南山; node --test tests/*.test.mjs; npm run build:h5; npm run build:mp-weixin` | **`tests 418, pass 418, fail 0, skipped 0 (3120.8072ms)`**；`build:h5` 与 `build:mp-weixin` 均 `DONE Build complete.` | 0 failed |

---

## 6. 外部实网邮件烟雾验证声明（`EXT-EMAIL-01`–`EXT-EMAIL-03`）

本轮遵循严禁发送真实外部 SMTP/SES 邮件的边界约束，以下三项外部实网验收条目**严格未执行**：

| 编号 | 验证内容 | 状态 | 说明 |
|---|---|---|---|
| `EXT-EMAIL-01` | 真实 SMTP 投递及受控收件箱确认 | **`NOT RUN`** | 禁止触发真实 SMTP 外发，仅通过全量 Mock/PG/Redis 集成测试覆盖状态机与失败补偿 |
| `EXT-EMAIL-02` | 真实腾讯云 SES 投递及受控收件箱确认 | **`NOT RUN`** | 禁止触发真实腾讯云 SES 外发，仅核验配置身份核对与发送前/后状态机契约 |
| `EXT-EMAIL-03` | SPF / DKIM / DMARC 与发信域名配置检查 | **`NOT RUN`** | 需在生产域名与实际发信通道启用后由运维与发布变更窗口核验 |

---

## 7. 最终验收结论

- **架构与安全不变量收敛结论**：Phase R-Hotfix 针对 `HF01`–`HF05` 的所有代码改动、增量迁移 `039_phase_r_hotfix.sql`、测试增强及可执行证据门禁脚本均已通过本地 PostgreSQL / Redis 真库联调、全量单测、静态类型门禁与三端回归验证。
- **发布准入结论**：**`CODE_ACCEPTED`**（未执行 `EXT-EMAIL-01`–`EXT-EMAIL-03` 与线上灰度放量前，严格不标注 **`PRODUCTION_READY`**）。
