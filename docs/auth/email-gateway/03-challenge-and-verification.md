# 邮箱验证码、重置链接、HMAC 绑定与并发状态机 (03-challenge-and-verification)

## 1. 凭据强度与格式规范

- **6 位数字 OTP 验证码**（`email_otp` 找回 / 绑定 / 二次认证）：由 `secrets.randbelow(1_000_000):06d`（CSPRNG）生成，前后端严格保留前导零并作为 ASCII 字符串处理（前端 `sanitizeOtpCode` 仅剔除非数字字符并截断前 6 位，绝不调用 `Number(...)`）。
- **256 位密码重置令牌**（`email_link`）：由 `secrets.token_urlsafe(32)` 生成（至少 43 个 URL 安全字符），并通过 **URL Fragment** 拼接至前端受信任重置域名：
  ```text
  {FRONTEND_URL}/reset-password#challengeId=<uuid>&token=<urlsafe_token>
  ```
- **防链接扫描器 / Referer / 代理日志泄露设计**：
  1. Fragment (`#...`) 默认不随 HTTP 请求发往服务端，也不会写入 Nginx / Uvicorn / CDN URL 查询日志；
  2. `/reset-password` 响应注入 `Referrer-Policy: no-referrer` 与 `Cache-Control: no-store`；
  3. 前端 `ResetPasswordView.vue` 加载时**不自动调用任何核验 API**，而是解析凭证后立即调用 `window.history.replaceState` 清洗地址栏，仅在用户手动填写新密码并点击提交按钮后才触发 `verify -> complete`；
  4. `_DropNotFoundAccessLog` 额外对兼容降级到 Query 参数的场景（`token=`、`recoveryGrant=`、`stepUpGrant=`、`code=`、`grant=`）在访问日志写入前脱敏为 `[REDACTED]`。

---

## 2. HMAC 上下文绑定与密钥轮换兼容 (`modules/security/service.py`)

数据库 `auth_challenge.code_hash` 禁止存明文或无盐散列，统一使用独立密钥（`SECURITY_OTP_HMAC_SECRET`，未设置时兼容回退 `JWT_SECRET`）：

- **v2 无歧义规范化签名**（`code_hash_version = 2`，前缀 `v2$`）：
  ```python
  canonical = json.dumps(
      ["v2", str(challenge_id), str(purpose), str(channel), destination.strip().lower(), code.strip()],
      ensure_ascii=False,
      separators=(",", ":"),
  )
  code_hash = "v2$" + hmac.new(_otp_secret(), canonical.encode("utf-8"), hashlib.sha256).hexdigest()
  ```
- **密钥轮换与存量平滑兼容**：`_verify_challenge_code_match()` 对带 `v2$` 前缀的挑战校验 v2 摘要，对历史 `v1` 记录兼容使用 `SECURITY_OTP_HMAC_SECRET` 及存量窗口内的 `JWT_SECRET` 进行恒定时间比对 (`hmac.compare_digest`)。联系方式检索盲索引（`destination_fingerprint`）亦支持 `_verify_destination_fingerprint()` 的新旧密钥双匹配。
- **跨用途/跨接触方式/跨用户隔离**：`verify_recovery_challenge()` 检查 `purpose == "password_recovery"`、`EMAIL_ELIGIBLE_SQL` 与 `destination_fingerprint`；`verify_and_bind_contact()` 检查 `purpose == f"bind_{contact_type}"`、`user_id` 与目标邮箱规范值。

---

## 3. 并发串行化、短事务隔离与闭环收敛

1. **行级锁串行创建 (`_send_email`)**：
   - 在调用外部 SMTP/SES 前开启短事务：对 `app_user` 执行 `SELECT id FROM app_user WHERE id=%s FOR UPDATE`；
   - 将同用户同用途的历史未决挑战（`status IN ('pending','pending_send')`）统一置为 `cancelled`，随后配合 `036` 新增部分唯一索引 `uk_auth_challenge_active_user_purpose_channel` 确保同用户、同用途、同渠道不存在并发激活挑战；
   - 插入新记录初始为 `status='pending_send'`、`send_state='reserved'`，事务立即提交并释放数据库行锁后再执行网络 I/O，防止慢 SMTP/SES 阻塞数据库连接池。
2. **发送结果闭环**：
   - **服务商受理** (`accepted=True`)：`send_state -> 'accepted'`，`status -> 'pending'`；
   - **服务商明确拒绝** (`accepted=False` 或确定未送达异常)：`send_state -> 'rejected'`，`status -> 'failed'`，`delivery_failure_reason` 落库，消除“发送失败后 Challenge 仍为 `pending`”的幽灵状态；
   - **发送结果未知** (`PROVIDER_OUTCOME_UNKNOWN` / 网络断连于 `DATA` 后 / SES 5xx/超时)：`send_state -> 'unknown'`，`status -> 'pending'`，同时保留 Redis 未知结果抑制锁，绝不自动生成新 OTP 重发。
3. **显式状态机 (`modules/security/state_machine.py`)**：
   - `can_verify_challenge(status, send_state)` 仅允许 `status == 'pending'` 且 `send_state in {'accepted', 'delivered', 'unknown', None}` 参与核验；明确拒绝 `rejected`、`bounced`、`delivery_failed`、`reserved`、`sending`。
   - 禁止逆向或越界跳转（如 `consumed -> pending`、`expired -> verified`）。
4. **挑战核验事务安全 (`_challenge_transaction`)**：
   - 核验阶段发生验证码错误、过期或超限锁定时，提交 `attempt_count + 1` / `expired` / `locked` 持久化更新后再抛出 `BizError`（防止错误计数被 rollback 导致可无限暴破）；
   - 一旦进入 `tx["business_writes_started"] = True` 阶段（`verified`、签发 Grant、改绑邮箱等），任何后续异常（包括 `BizError` 409 冲突或权限拒绝）立即触发完整事务回滚，不留半写入脏状态。
