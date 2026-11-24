# Email Security Gateway 自动化测试、集成验证与性能基准报告 (09-test-report)

## 1. 测试综述与真实依赖覆盖说明

- **分支**：`feat/email-security-gateway`（基于远端 `github/main` 审查基准 `ef95927431ae101063eae9b3a4bcec24ffd42a27`）
- **运行环境**：Windows + Python 3.13.17 (`.venv/Scripts/python.exe`)、PostgreSQL 18 (`127.0.0.1:5432`, `SMS_TEST_POSTGRES=1`)、Redis (`127.0.0.1:6379/15`, `SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15`)、Node.js / Vite 8.2.2
- **真实外部邮箱投递边界声明**：未向公网真实 SMTP 服务器或腾讯云 SES 生产接口执行外网发送，相关**真实公网邮箱实发与收件箱送达验证严格标记为 `NOT RUN`**；SMTP 传输握手失败逻辑通过本地环回 Socket (`socket.socket` on `127.0.0.1`) 验证，SES 请求签名/响应解析/状态查询通过 Mock `urllib.request.urlopen` 验证。

---

## 2. 全量验证命令与实际观测汇总

| 验证项 | 实际执行命令 | 结果计数 / 输出 | 退出码 | 状态 |
| :--- | :--- | :--- | :---: | :--- |
| Email Gateway 专项套件（含真实 PG + Redis） | `SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest -p no:cacheprovider tests/test_email_*.py -v` | 45 passed, 0 failed, 0 skipped (11.14s) | 0 | **PASSED** |
| 安全与认证回归套件（含真实 PG + Redis） | `SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest -p no:cacheprovider tests/test_email_*.py tests/test_sms_*.py tests/test_sendcloud_security.py tests/test_unified_auth_recovery.py tests/test_wechat_login.py tests/test_middleware_exception.py tests/test_core_comprehensive.py -q` | 373 passed, 0 failed (30.22s) | 0 | **PASSED** |
| 后端全量测试 + 覆盖率门禁 (≥75%) | `SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 pytest -p no:cacheprovider --cov=. --cov-report=term-missing --cov-fail-under=75 -q` | 2537 passed, 31 skipped (`test_ai_chat_runs_pg.py` 需 `AI_CHAT_TEST_DATABASE_URL`), 0 failed (44.72s); 覆盖率 **89.11%** (12470 stmts, 1358 miss) | 0 | **PASSED** |
| 联系方式格式兼容独立脚本 | `python test_contact_validation.py` | `PASS: contact validation` | 0 | **PASSED** |
| Ruff 代码扫描与格式检查 | `ruff check .` & `ruff format --check .` | All checks passed / 263 files already formatted | 0 | **PASSED** |
| Flake8 语法错误扫描 | `flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics` | `0` error | 0 | **PASSED** |
| 静态类型检查 (`mypy`) | `mypy . --ignore-missing-imports ...` / 指定模块 `--explicit-package-bases` | `mypy .` 因存量 `tools/run_ai_chat_worker.py` 重复模块路径报 exit 2（CI 配 `continue-on-error: true`）；26 模块检查报 121 条既有/新增标注提示（含 `email_providers.py` 3 处） | 2 / 1 | **KNOWN WARNINGS** |
| 离线运维契约工具 | `python tools/email_gateway_ops.py check-provider` & `explain-failure --code PROVIDER_OUTCOME_UNKNOWN` | `real_send_attempted: false`, `smtp_contract_ok: true`, `ses_contract_ok: true` | 0 | **PASSED** |
| Vue 3 管理端单元测试 | `cd nanshan-frontend && node --test src/utils/*.test.mjs` | 38 passed, 0 failed (429.56ms) | 0 | **PASSED** |
| Vue 3 管理端生产构建 | `cd nanshan-frontend && npm run build` | `built in 391ms` | 0 | **PASSED** |
| 微信小程序自动化测试与双端编译 | `cd 南山小程序/南山 && node --test tests/*.test.mjs && npm run build:h5 && npm run build:mp-weixin` | 416 passed, 0 failed; `build:h5` DONE; `build:mp-weixin` DONE | 0 | **PASSED** |
| 真实外部 HTTP 注册脚本 (`test_auth_register.py`) | `python test_auth_register.py` | 需本地 `127.0.0.1:8787` 在线 HTTP 服务，拒绝连接 exit 1 | 1 | **NOT APPLICABLE (需在线 API)** |
| 真实外部公网 SMTP / SES 发送与收件箱送达 | — | 未执行公网外发与收件箱确认 | — | **NOT RUN** |

---

## 3. 10 个新增邮箱安全测试模块清单

1. `tests/test_email_provider.py`（5 项）：`get_email_provider()` 6 步严格注册校验链、production/staging 禁用 `mock` 与测试注入、`EMAIL_ENABLED=false` 阻断缓存实例、未知厂商拒绝静默回退、`MockEmailProvider` 无明文 PII 日志、`validate_frontend_reset_base_url()` 与 `assert_environment()`、邮箱规范化及模板 XSS/头部安全。
2. `tests/test_email_smtp.py`（5 项）：TLS 1.2 + `CERT_REQUIRED` 强制证书校验、头注入过滤、SSL 成功回执、`4xx/5xx/535/SMTPRecipientsRefused` 错误映射、`DATA` 阶段断连/超时标记 `PROVIDER_OUTCOME_UNKNOWN` 且零自动重试、真实本地环回 Socket 服务缺失 `STARTTLS` 拒降级。
3. `tests/test_email_ses.py`（8 项参数化/功能测试）：`SendEmail` (2020-10-02) 请求体/Base64 正文/`X-TC-Region`/TC3-HMAC-SHA256 签名、`Template` 模板模式、SES 5 类业务错误精确分类、HTTP 5xx/缺失 `MessageId` 保守标记 `outcome_unknown`、`GetSendEmailStatus` 查询及日志无密钥泄漏。
4. `tests/test_email_risk.py`（4 项）：真实 Redis Lua 全盲索引键无 PII、`PUBLIC_EMAIL_DOMAINS`（`qq.com`/`163.com`/`outlook.com`/`gmail.com`）免误伤 vs 非公共域名 `email.domain.anomaly_10m`、`email.pending_outcome` -> `email.cooldown`、IP 不同目标邮箱 `CHALLENGE`、`NoScriptError` 脚本清理后自动重载、24 并发线程 `reserve()` 竞态（严格仅 1 线程获批）、风控与 `SecurityRateLimiter` 在生产/`REDIS_ENABLED=true` 下的严格 Fail-Closed (503)。
5. `tests/test_email_challenge.py`（6 项）：状态机转换拦截与 `unknown` 保守核验、`v2$` 上下文 HMAC 与 `v1` 轮换兼容 + 前导零保留、绑定发送失败立即闭环 `failed`（无残留 `pending`）、`_challenge_transaction()` 错误次数提交 vs `business_writes_started` 全量回滚、256-bit `email_link` URL Fragment 格式校验。
6. `tests/test_email_delivery_results.py`（3 项）：`DeliveryReceipt`、`DeliveryTaskResult.queue_state`、`DeliveryStageError` 退避秒数、低基数 `DeliveryMetrics` 过滤、日志 `safe_id` 散列脱敏及 `security.delivery.result` 事件格式。
7. `tests/test_email_diagnostics.py`（4 项）：全部 20 个 `FAILURE_EXPLANATIONS` 错误码核验、`email_provider_check()` 零网络外呼确认、秘钥字段脱敏、`email_inspect_delivery`/`cleanup_expired` 与 `tools/email_gateway_ops.py` CLI 安全门禁验证。
8. `tests/test_email_binding_security.py`（3 项）：不同账号 `stepUpMethods` 探测、Step-up Grant 会话指纹/用户/目的/重放/过期校验、无 Grant 拒绝换绑、换绑成功原子消费 Grant 并吊销旧 `recovery_grant` 与历史邮件挑战、冲突 `IntegrityError` -> 409 及最佳努力变更通知。
9. `tests/test_email_recovery_e2e.py`（4 项）：FastAPI HTTP 端到端 `/auth/recovery/capabilities`、`/recovery/start` 防枚举与 `EMAIL_ENABLED=false` 503、限流响应头 `Retry-After`、OTP 重置、`/reset-password` 响应头 `Referrer-Policy: no-referrer` + `Cache-Control: no-store`、`_DropNotFoundAccessLog` 查询参数脱敏、`/me/security` 与 Step-up HTTP 流程。
10. `tests/test_email_gateway_postgres.py`（3 项真实 PG + Redis 集成测试）：从 `033~035` 带历史过期/重复脏数据升级到 `036` 并幂等重跑、16 线程并行核验同一 OTP 严格仅 1 线程签发 Grant、双用户并发抢绑同一邮箱冲突处理（1 成功 1 报 409）、队列 PII 清理、Worker 卡死恢复与过期 `step_up_grant` 收敛。

---

## 4. 本地真实 PostgreSQL + Redis 可复现性能基准

执行命令（30 轮完整端到端迭代，测试环境隔离随机 Schema，每轮 PostgreSQL 查询使用非连接池独立连接 `_schema_cursor` 以隔离并行干扰；Redis 复用客户端连接）：

```bash
cd tech-transfer-service
SMS_TEST_POSTGRES=1 SMS_TEST_REDIS_URL=redis://127.0.0.1:6379/15 ..\.venv\Scripts\python.exe -c "import json; from tests.test_email_gateway_postgres import run_pg_redis_benchmark; print(json.dumps(run_pg_redis_benchmark(30), ensure_ascii=False))"
```

实测基准数据：

| 指标 | 样本数 | p50 (ms) | p95 (ms) | mean (ms) | 说明 |
| :--- | :---: | :---: | :---: | :---: | :--- |
| `redis_lua_check_ms` | 30 | **0.815** | **2.467** | **1.179** | 真实 Redis `EmailRiskEngine.check_request` (`EVALSHA` 15 维规则原子脚本) |
| `challenge_create_ms` | 30 | **140.200** | **255.273** | **162.750** | 含 Redis `reserve` + 行锁/建挑战 + `MockEmailProvider` + 回执写入及 3 次独立无池 PG TCP 握手 |
| `challenge_verify_ms` | 30 | **48.065** | **152.550** | **60.449** | 含单事务校验 `auth_challenge` / 吊销旧 `recovery_grant` / 签发新 Grant |
| `queue_claim_ms` | 30 | **44.671** | **152.718** | **57.064** | `UPDATE security_delivery_request SET state='processing'`（非池化测试连接） |
| 并发竞态精度 | 24 / 16 线程 | — | — | — | 24 线程 Redis `reserve` 严格 **1 ALLOW / 23 THROTTLE**；16 线程 PG `verify_recovery_challenge` 严格 **1 GRANT / 15 REJECT** |
