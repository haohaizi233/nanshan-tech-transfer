# 数据库迁移方案与收敛规范 (`036_email_security_gateway.sql`) (08-database-migration)

## 1. 迁移文件与兼容性设计

迁移脚本位于：`tech-transfer-service/migrations/pg/036_email_security_gateway.sql`（增量前置依赖：`033_unified_account_security.sql` -> `034_sms_security_gateway.sql` -> `035_sms_delivery_diagnostics.sql`）。

设计严格遵循**零停机、全幂等、保留历史数据、支持安全重跑**四项要求。

---

## 2. 核心 DDL 变更明细

### 2.1 `public.auth_challenge` 扩展与历史脏数据收敛
1. **新增诊断与摘要版本列**：
   - `code_hash_version SMALLINT NOT NULL DEFAULT 1`（`1=legacy HMAC`；`2=v2$ 上下文绑定 HMAC`）；
   - `provider_name VARCHAR(32)`（投递使用的 `smtp` / `tencent` / `sendcloud` / `mock`）；
   - `delivery_failure_reason VARCHAR(64)`（脱敏失败分类码）。
2. **历史未决记录安全收敛（创建唯一索引前必须执行）**：
   - 将所有已超过有效期但仍停留在 `('pending_send', 'pending')` 的历史挑战标记为 `'expired'`；
   - 按 `(user_id, purpose, channel)` 分区保留最新一条激活记录（`rn = 1`），其余旧残留挑战统一收敛为 `'cancelled'`。
3. **显式 CHECK 约束与部分唯一索引**：
   - `chk_auth_challenge_status`：限定 `'pending_send'`, `'pending'`, `'verified'`, `'consumed'`, `'expired'`, `'locked'`, `'failed'`, `'cancelled'`；
   - `chk_auth_challenge_send_state`：限定 `NULL` 或 `'reserved'`, `'sending'`, `'accepted'`, `'rejected'`, `'unknown'`, `'delivered'`, `'bounced'`, `'delivery_failed'`；
   - `uk_auth_challenge_active_user_purpose_channel`：部分唯一索引，保证同一用户在同用途同渠道下任意时刻至多 1 条活跃激活挑战；
   - `idx_auth_challenge_email_send_state` 与 `idx_auth_challenge_cleanup`：加速邮件状态核对与定期过期清理。

### 2.2 `public.security_delivery_request` 诊断字段补全
- 新增 `channel VARCHAR(16)`、`purpose VARCHAR(32)`、`provider VARCHAR(32)`；
- 回填存量 `payload->>'channel'` 至 `channel` 列（截断至 16 字符）；
- 建立 `idx_security_delivery_request_channel_state` 与 `idx_security_delivery_request_cleanup`。

### 2.3 新增 `public.step_up_grant` 表（二次认证短期单次授权）
- 字段：`id (UUID PK)`, `user_id (FK -> app_user)`, `purpose`, `method`, `session_fingerprint`, `target_fingerprint`, `grant_hash (UNIQUE)`, `status CHECK ('active','consumed','revoked','expired')`, `expires_at`, `consumed_at`, `created_at`, `updated_at`；
- 索引：`uk_step_up_grant_hash`、`idx_step_up_grant_user_purpose_status`、`idx_step_up_grant_cleanup`；
- 触发器：`trg_step_up_grant_updated_at` 自动维护 `updated_at`。

### 2.4 `public.recovery_grant` 清理索引
- 新增 `idx_recovery_grant_cleanup ON recovery_grant(expires_at, status) WHERE status='active'`。

---

## 3. 执行与迁移后核验 SQL

```bash
psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -v ON_ERROR_STOP=1 -f tech-transfer-service/migrations/pg/036_email_security_gateway.sql
```

迁移后校验查询：
```sql
SELECT column_name FROM information_schema.columns
WHERE table_schema = 'public' AND table_name = 'auth_challenge'
  AND column_name IN ('code_hash_version', 'provider_name', 'delivery_failure_reason');

SELECT indexname FROM pg_indexes
WHERE schemaname = 'public'
  AND indexname IN (
    'uk_auth_challenge_active_user_purpose_channel',
    'uk_step_up_grant_hash',
    'idx_security_delivery_request_channel_state'
  );
```
