# 南山科转通统一身份数据库迁移与兼容方案 (03-database-migration)

## 1. 迁移概述

- **迁移脚本**：`tech-transfer-service/migrations/pg/033_unified_account_security.sql`
- **上一个迁移版本**：`032_ai_task_progress_stage.sql`
- **当前迁移版本**：`033_unified_account_security.sql`
- **原则**：纯增量（Additive Only）、幂等可重复执行（`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`）、无锁阻塞风险、严禁物理破坏存量字段。

---

## 2. 变更内容详单

### 2.1 修改现有表
- `app_user`：
  - 新增列 `session_version INT NOT NULL DEFAULT 1`。
  - 用途：跟踪用户会话版本。用户修改密码、管理员重置或封禁时 `session_version = session_version + 1`，中间件校验比对使存量 JWT 即刻失效。

### 2.2 新建核心表
1. **`account_contact`（确权安全联系方式）**：
   - 字段：`id`, `user_id`, `contact_type` (`phone`/`email`), `normalized_value`, `verified_at`, `status`, `created_at`, `updated_at`, `revoked_at`。
   - 索引与约束：
     - `uk_account_contact_verified_phone`：部分唯一索引，仅对 `verified_at IS NOT NULL` 且 `status='active'` 的手机号去重。
     - `uk_account_contact_verified_email`：部分唯一索引，仅对 `verified_at IS NOT NULL` 且 `status='active'` 的邮箱去重。
     - `uk_account_contact_user_active_type`：每个用户每种联系方式仅允许保留 1 条激活状态记录。

2. **`auth_challenge`（认证挑战）**：
   - 字段：`id` (UUID), `user_id`, `purpose`, `channel`, `destination_fingerprint`, `destination_masked`, `code_hash`, `status`, `attempt_count`, `max_attempts`, `expires_at`, `consumed_at`, `created_at`, `updated_at`。
   - 约束：`destination_fingerprint` 为联系方式不可逆 HMAC 摘要；`code_hash` 为服务端私钥加盐的验证码哈希。

3. **`recovery_grant`（密码重置一次性授权）**：
   - 字段：`id` (UUID), `user_id`, `challenge_id`, `grant_hash`, `status`, `expires_at`, `consumed_at`, `created_at`, `updated_at`。
   - 约束：`grant_hash` 唯一索引，单次使用，默认 300 秒有效期。

---

## 3. 存量数据兼容与初始化策略

### 3.1 存量数据分析
- 存量小程序注册用户在 `user_credential.phone` 中已具备合法的 11 位手机号。
- 存量用户的 `user_profile.phone/email` 为自由编辑字段，**坚决不自动提升为 verified**。
- 脚本中仅将 `user_credential` 中有效、唯一的 11 位手机号安全初始化写入 `account_contact`，作为初始确权手机号，避免老用户在上线后无法通过手机找回密码。

### 3.2 离线检查与冲突扫描脚本
提供数据校验工具 `tools/audit_contact_conflicts.py`，用于上线前扫描存量异常：
- 检测 `user_profile.phone` 与 `user_credential.phone` 不一致的账号；
- 检测多账号绑定相同手机号或邮箱的存量数据；
- 输出异常清单供运营确认，绝不硬性破坏数据库。

---

## 4. 回滚方案与应急措施

1. **结构回滚**：
   ```sql
   BEGIN;
   DROP TABLE IF EXISTS public.recovery_grant CASCADE;
   DROP TABLE IF EXISTS public.auth_challenge CASCADE;
   DROP TABLE IF EXISTS public.account_contact CASCADE;
   ALTER TABLE public.app_user DROP COLUMN IF EXISTS session_version;
   COMMIT;
   ```
2. **数据保护承诺**：
   - 回滚仅移去新建立的联系方式确权及验证码表，原有 `app_user`、`user_credential`、`user_profile`、`external_identity` 的业务数据完好无损。
   - 所有回滚操作前必须执行 `pg_dump` 全量物理备份。
