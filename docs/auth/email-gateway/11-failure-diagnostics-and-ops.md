# Email Security Gateway 故障诊断分类与内部运维手册 (11-failure-diagnostics-and-ops)

## 1. 运维工具安全边界 (`tools/email_gateway_ops.py`)

- `modules/security/email_diagnostics.py` 与 `tools/email_gateway_ops.py` **严格定位为内部只读运维工具**，严禁被任何公开 HTTP 接口导入或暴露。
- **零敏感泄露原则**：输出永远剔除明文邮箱、验证码、重置链接、`stepUpGrant`、`recoveryGrant`、SMTP 密码、SES 密钥及含密码的 Redis 连接串。
- `check-provider` 仅做离线协议与签名合约验证，**不发起真实网络连接，不发送任何真实邮件**。
- `risk-check` 仅使用 Redis 只读命令（`GET`、`TTL`、`ZCOUNT`），绝不消耗任何限流配额或修改计数器。

---

## 2. 内部运维 CLI 命令清单 (`tools/email_gateway_ops.py`)

```bash
cd tech-transfer-service

# 1. 环境配置与 036 表结构健康检查（只读）
python tools/email_gateway_ops.py check-config

# 2. Redis 连通性与 Lua 脚本支持检查（只读）
python tools/email_gateway_ops.py check-redis

# 3. 离线 Provider 协议合约自检（零发信）
python tools/email_gateway_ops.py check-provider

# 4. 标准化失败原因码诊断解释
python tools/email_gateway_ops.py explain-failure --code PROVIDER_OUTCOME_UNKNOWN

# 5. 按 challenge_id 或 request_id 脱敏排查投递与状态链
python tools/email_gateway_ops.py inspect-delivery --challenge-id <uuid>

# 6. 按账号或 challenge_id 排查准入资格与挑战状态
python tools/email_gateway_ops.py inspect-challenge --account <username_or_email>

# 7. 只读风控配额与剩余 TTL 快照（zero mutation）
python tools/email_gateway_ops.py risk-check --account <acct> --email <target> --ip <ip>

# 8. 邮件队列堆积与卡死检查
python tools/email_gateway_ops.py queue-check

# 9. 调用上游 API（仅支持 SES）核对投递终态
python tools/email_gateway_ops.py reconcile --challenge-id <uuid>

# 10. 过期挑战/授权清理（默认 dry-run；--apply 执行物理收敛）
python tools/email_gateway_ops.py cleanup-expired
python tools/email_gateway_ops.py cleanup-expired --apply

# 11. 受严格双重门禁保护的受控真实发信验证（默认禁用）
# 必须同时满足：EMAIL_LIVE_TEST_ENABLED=true、EMAIL_ENABLED=true、--send、--confirm-recipient 精确匹配库内已确权邮箱
python tools/email_gateway_ops.py live-test --account <acct> --email <mail> --confirm-recipient <mail> --channel email_otp --send
```

---

## 3. 20 项标准化故障原因码索引与处置手册 (`FAILURE_EXPLANATIONS`)

| 原因码 | 分类 | 可安全重试 | 根因摘要与排查动作 |
| :--- | :--- | :---: | :--- |
| `CONFIG_ERROR` | configuration | 否 | `EMAIL_PROVIDER` 未知、`FRONTEND_URL` 非法或认证参数缺失；核查 env 配置 (`check-config`) |
| `CHANNEL_DISABLED` | policy | 否 | `EMAIL_ENABLED=false`；在确认凭证与 Redis 就绪后再开启开关 |
| `INELIGIBLE_ACCOUNT` | eligibility | 否 | 目标账号不存在、已禁用/删除、未设密码或为管理员受限账号；核验账号状态 |
| `CONTACT_NOT_VERIFIED` | eligibility | 否 | 目标用户未完成安全邮箱确权（普通资料 `user_profile.email` 不具备找回资格） |
| `RISK_BLOCKED` | risk_control | 否 | 命中冷却/IP/设备/账号/邮箱/日预算/异常域规则；使用 `risk-check` 查看 TTL |
| `REDIS_UNAVAILABLE` | dependency | 是 | Redis 异常或 Lua 不可用，网关 Fail-Closed 返回 503；恢复 Redis 连通性 |
| `CHALLENGE_CREATE_FAILED` | database | 是 | 写 `auth_challenge` 事务失败，系统已自动释放风控预占配额；排查 PG 锁与连接池 |
| `SMTP_CONNECTION_FAILED` | provider_transport | 是 | SMTP 建连失败或握手前网络中断；排查主机、端口、防火墙与 DNS |
| `SMTP_TLS_FAILED` | provider_tls | 否 | SSL/STARTTLS 证书链或主机名校验失败；核对 TLS 证书与端口匹配 |
| `SMTP_AUTH_FAILED` | provider_auth | 否 | SMTP 账号授权密码被拒（534/535）；轮换发信授权码 |
| `SMTP_RECIPIENT_REJECTED` | provider_recipient | 否 | 收件地址被拒（账号不存在或策略退信）；核查地址与 MX 记录 |
| `SMTP_TEMPORARY_FAILURE` | provider_temporary | 是 | SMTP 返回 4xx 临时拒绝（灰名单/并发限频）；遵循退避策略勿连续刷发 |
| `SMTP_PERMANENT_FAILURE` | provider_permanent | 否 | SMTP 5xx 永久拒收；检查 SPF/DKIM/DMARC 与发信人对齐策略 |
| `SES_SIGNATURE_ERROR` | provider_auth | 否 | SES TC3 签名或 SecretId/SecretKey 失效；核对系统 NTP 时钟与密钥 |
| `SES_PERMISSION_ERROR` | provider_auth | 否 | SES CAM 权限不足或发信邮箱未完成控制台域名认证 |
| `SES_QUOTA_EXCEEDED` | provider_quota | 否 | 腾讯云 SES 配额耗尽或触发发信频率/收件黑名单限制 |
| `SES_INVALID_RESPONSE` | provider_protocol | 否 | SES 响应非 JSON 或缺少 `MessageId`，保守按未知处理，**禁止盲目重发** |
| `PROVIDER_OUTCOME_UNKNOWN` | provider_unknown | 否 | `DATA` 后断连、超时或上游 5xx，无法确认是否已入队；等待用户使用原码或自然过期 |
| `RECEIPT_PERSIST_FAILED` | database | 否 | 调用上游后回写 `auth_challenge` 失败，保留未知态防重复派发；排查 PG 状态并核对挑战 |
| `DELIVERY_TASK_EXPIRED` | queue | 是 | 持久化队列超 5 分钟未被领取，已安全作废（未实际发信）；排查 Worker 调度延迟 |
