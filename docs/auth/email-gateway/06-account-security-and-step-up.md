# 安全邮箱绑定、二次身份认证 (Step-up) 与换绑原子保护 (06-account-security-and-step-up)

## 1. 首次绑定 vs 更换绑定安全边界

- **首次绑定（无活跃已确权安全邮箱）**：已登录用户可直接通过 `POST /me/security/contact/challenge`（向目标邮箱发送 6 位 OTP）+ `POST /me/security/contact/verify` 完成首次确权绑定，兼容密码账号与微信快捷登录无密码账号。
- **更换已确权安全邮箱（高风险敏感操作）**：
  一旦账号已存在 `status='active' AND verified_at IS NOT NULL` 的 `email` 联系方式，系统拒绝仅凭新邮箱验证码直接覆盖旧邮箱。无论在发起换绑挑战（`start_email_binding`）还是最终确认替换（`verify_and_bind_contact`）时，均强制校验有效的 **`stepUpGrant`**！

---

## 2. 二次认证 (Step-up Authentication) 机制 (`modules/security/step_up.py`)

### 2.1 可用验证方式 (`get_available_step_up_methods`)
根据当前账号凭证配置与已确权联系方式动态返回：
- **已设置密码账号 / 管理员账号**：`password`（当前登录密码复核）、`old_email_otp`（原安全邮箱 OTP，当 `EMAIL_ENABLED=true`）、`old_phone_otp`（原安全手机 OTP，当 `SMS_ENABLED=true`）；
- **无密码纯微信快捷登录账号（且非管理员）**：除原邮箱/原手机 OTP 外，若当前 JWT `iat` 签发距今未超过 `STEP_UP_RECENT_AUTH_SECONDS`（默认 300s），额外允许 `recent_auth` 完成二次确认。

### 2.2 `step_up_grant` 强绑定模型与生命周期
1. **发起二次验证码**（仅 `old_email_otp` / `old_phone_otp`）：`POST /me/security/step-up/challenge` 向数据库内已确权的原邮箱/原手机发送 `purpose='step_up_auth'` 的 OTP；
2. **核验签发授权 (`issue_step_up_grant`)**：
   - 使用行锁 `SELECT ... FROM app_user au LEFT JOIN user_credential uc ... WHERE au.id = %s FOR UPDATE OF au` 防止外连接锁异常；
   - 核验通过后先将该用户同用途旧 `active` `step_up_grant` 标记为 `revoked`，再生成 256 位随机 Token，仅将 SHA-256 摘要 `grant_hash` 持久化至 `step_up_grant` 表（TTL 默认 `STEP_UP_GRANT_TTL_SECONDS=300`）；
   - 严格绑定以下四个上下文维度：
     - `user_id`（必须匹配发起操作的用户）；
     - `purpose`（`rebind_email`）；
     - `session_fingerprint`（基于当前 Bearer Access Token 提取的签名会话摘要 `HMAC(secret, "sess:{uid}:{ver}:{iat}:{token_hash}")`，防止跨设备或重放旧会话窃用）；
     - `target_fingerprint`（可选绑定的目标新邮箱 HMAC 盲索引，提交挑战与换绑的目标不一致立即拒绝）。
3. **原子消费 (`validate_step_up_grant(..., consume=True)`)**：在最终换绑事务中执行 `FOR UPDATE` 行锁校验并在同一事务内将 `status` 置为 `consumed`，彻底杜绝同一 Grant 重复用于二次换绑或并发重放。

---

## 3. 原子换绑、并发冲突保护与关联凭证吊销 (`verify_and_bind_contact`)

1. **统一加锁顺序防死锁**：事务按固定顺序加锁：`app_user` -> `auth_challenge` -> 已有 `account_contact` -> `step_up_grant` -> 目标唯一性检查。
2. **并发抢注防护**：在业务校验及 `INSERT INTO account_contact` 时捕获数据库 `psycopg2.IntegrityError`，统一映射为 HTTP 409 (`TT_COMMON_40903`)，并在 `_challenge_transaction()` 的 `business_writes_started=True` 保护下完整回滚旧邮箱撤销等中间状态。
3. **关联恢复凭据即时清理**：更换安全邮箱成功后，同一事务内立即将受旧邮箱影响的所有活跃 `recovery_grant` 置为 `revoked`，并将历史未终结的邮箱找回 `auth_challenge`（`email_otp`/`email_link`）统一标记为 `cancelled`，防止攻击者在换绑前拦截旧邮箱重置链接或 OTP。
4. **可配置安全变更通知（事务提交后最佳实践）**：当 `EMAIL_SECURITY_NOTIFICATION_ENABLED=true` 且 `EMAIL_ENABLED=true` 时，换绑事务提交后向**原安全邮箱**（`old_email_to_notify`）Best-Effort 发送“安全邮箱已更换通知”邮件，即使通知送信异常也绝不回滚或阻塞已完成的主事务。
5. **退出全部其他设备同步吊销**：`/me/security/revoke-sessions`（`revoke_all_user_sessions`）除递增 `session_version` 与吊销 `auth_session` 外，同时吊销当前活跃 `step_up_grant`。
