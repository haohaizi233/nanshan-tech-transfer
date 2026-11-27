# Phase P3-A：AI 全链路数据隐私治理、异步发送可靠性与 Schema Gate

## 1. P3-1：AI 全链路数据隐私治理

### 1.1 数据分级策略与统一脱敏契约
- 在 [nanshan-ai-agent/app/privacy.py](file:///d:/Users/Administrator/Desktop/南山小程序/nanshan-ai-agent/app/privacy.py) 定义六级数据分类：`PUBLIC`、`AUTHENTICATED`、`OWNER_ONLY`、`COOPERATION_AUTHORIZED`、`ADMIN_ONLY`、`SECRET`。
- 升级 [tech-transfer-service/modules/achievement/extract.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/achievement/extract.py) 的 `strip_private_contact_text()` 并与 `nanshan-ai-agent/app/privacy.py` 保持一致契约：
  - 剥离明文手机号、座机号、邮箱、微信号、带联系标签行；
  - 剥离 JWT、Bearer Token、URL 中的账密凭据与敏感查询参数（`token`、`access_token`、`code`、`secret`、`password` 等），同时保留公开官网、专利号、技术指标与金额区间。
- 全链路接入点：
  - LLM 输入：`reranker.py`（`_achievement_for_llm`、`_demand_for_llm`、`user_query`）、`main.py`（路由前消息清洗）、`modules/ai/provider.py`（`evaluate_achievement` 快照清洗）。
  - AI 输出与持久化：`formatters.py`（成果/需求卡片字段清洗）、`advisor.py`（`grounded_explanation` 与 `_source_text` 清洗）、`modules/ai/chat_store.py`（入库及历史读取二次清洗）。
  - 权限二次校验：`main.py` 的 `get_visible_records`、`get_reference_records`、`_final_records`、`_reference_visible` 确保未发布/已下架/已删除资源不进入新推荐或历史引用。

### 1.2 专项验收结果（PRIV-01 ~ PRIV-15）
- `nanshan-ai-agent/tests/test_privacy_governance.py`：**6 passed**（含 Mock LLM 捕获实际发送载荷断言无明文联系方式外发）。
- `tech-transfer-service/tests/test_privacy_contract.py`：**10 passed**（跨服务脱敏向量一致 + `evaluate_achievement` 快照清洗 + `chat_store` 历史卡片清洗）。

## 2. P3-2：异步找回执行权与 Redis 风控协调

- **异步密码找回执行权**（[sms_gateway.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/security/sms_gateway.py)、[email_gateway.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/security/email_gateway.py)）：
  - `run_queued_recovery_task()` 领取时生成唯一 `worker_owner` 并写入 `execution_owner`，将 `worker_owner` 与 `IdempotencyClaim` 透传至 `_send()` / `_send_email()`。
  - `_verify_worker_execution_right()` / `_verify_email_worker_ownership()` 在外呼前及创建 `auth_challenge` 事务内校验 `state='processing' AND execution_owner=%s`；`_persist_task_result()` 增加 `execution_owner` 条件防护。
- **迟到风控协调结果治理**（[delivery_models.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/security/delivery_models.py)）：
  - `_persist_risk_sync_outcome()` 全部分支强制校验 `risk_sync_target`、终态 `risk_sync_state <> 'synced'` 与 `expected_claimed_at` 租约。
- **后台协调调度**（[maintenance.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/security/maintenance.py)、[app.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/app.py)）：
  - `run_security_maintenance_tick()` 有界调用 `reconcile_pending_risk_syncs(limit=50)` 与 `cleanup_delivery_tasks()`，零 Provider 调用，暴露 `pendingRiskSyncCount` 与 `lastSuccessAt`。

## 3. P3-3：Schema Gate、版本信息与真实业务闭环说明

- [schema_gate.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/security/schema_gate.py) 升级 `REQUIRED_SECURITY_SCHEMA_VERSION = "040"`（含 `auth_challenge.user_id` 可空、`ck_auth_challenge_registration_owner`、`uk_auth_challenge_active_registration_phone`），新增 `REQUIRED_APPLICATION_SCHEMA_VERSION = "042"`。
- [app.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/app.py) 新增 `/health/version` 与 `/api/health/version` 脱敏版本接口。
- PostgreSQL 18.6 实库测试：`test_security_delivery_fault_injection.py`（4 passed）、`test_p3_async_security_and_schema.py`（3 passed）。
- 真实邮箱/短信验证码业务闭环（`19-live-otp-verification-acceptance.md`）：代码门禁与实库并发已验证（PASS）；**真实外发验证码及用户页面输入闭环标记为 `BLOCKED / NOT RUN（需用户授权并在真实页面输入验证码）`**。
