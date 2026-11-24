# Email Security Gateway 生产部署与上线运维手册 (10-deployment-runbook)

## 1. 部署前检查与安全前提

1. **前置数据库迁移**：确认已在 PostgreSQL 执行完整链路：
   `033_unified_account_security.sql` -> `034_sms_security_gateway.sql` -> `035_sms_delivery_diagnostics.sql` -> `036_email_security_gateway.sql`。
2. **Redis 强制就绪**：在 `staging`/`production` 环境必须启用 `REDIS_ENABLED=true` 且保障 `EVALSHA` Lua 脚本支持；生产限流器与邮箱风控引擎在 Redis 不可用时采用 **Fail-Closed**（503 拒绝服务），绝不降级内存。
3. **重置前端基地址校验**：`FRONTEND_URL` 在 `staging`/`production` 必须为非本地回环的可信 `https://` 域名（无 Query/Fragment/内嵌凭据）。

---

## 2. 生产环境变量清单 (`.env` / ConfigMap / Secret)

> [!CAUTION]
> 切勿将真实密钥、授权密码写入版本库或 `.env.example`；`staging`/`production` 下严禁使用 `EMAIL_PROVIDER=mock`。

```ini
# ── 基础开关与前端基地址 ──
APP_ENV=production
FRONTEND_URL=https://tech.nanshan.gov.cn

EMAIL_ENABLED=true
EMAIL_PROVIDER=tencent        # 仅支持: smtp | tencent (非生产环境额外支持 mock)
EMAIL_CODE_TTL_SECONDS=300
EMAIL_LINK_TTL_SECONDS=300
EMAIL_CODE_MAX_ATTEMPTS=5
EMAIL_SECURITY_NOTIFICATION_ENABLED=true

# ── 密钥隔离（推荐均使用 ≥32 字节随机高熵密钥）──
SECURITY_OTP_HMAC_SECRET=<32+ random hex>
SECURITY_CONTACT_HMAC_SECRET=<32+ random hex>
EMAIL_RISK_HMAC_SECRET=<32+ random hex>
STEP_UP_GRANT_TTL_SECONDS=300
STEP_UP_RECENT_AUTH_SECONDS=300

# ── 方案 A：腾讯云 SES（EMAIL_PROVIDER=tencent）──
TENCENT_SES_SECRET_ID=<AKID...>
TENCENT_SES_SECRET_KEY=<SecretKey>
TENCENT_SES_FROM_EMAIL=no-reply@mail.nanshan-tech.com
TENCENT_SES_REGION=ap-hongkong
TENCENT_SES_ENDPOINT=ses.tencentcloudapi.com
TENCENT_SES_TIMEOUT_SECONDS=10
TENCENT_SES_TEMPLATE_ID_OTP=0
TENCENT_SES_TEMPLATE_ID_RESET=0

# ── 方案 B：标准企业 SMTP（EMAIL_PROVIDER=smtp）──
SMTP_HOST=smtp.exmail.qq.com
SMTP_PORT=465
SMTP_USER=service@mail.nanshan-tech.com
SMTP_PASSWORD=<app-specific-password>
SMTP_FROM_EMAIL=no-reply@mail.nanshan-tech.com
SMTP_FROM_NAME=南山科转通
SMTP_USE_SSL=true
SMTP_TIMEOUT_SECONDS=10
SMTP_MAX_ATTEMPTS=2
```

---

## 3. 企业邮箱 DNS 与投递到达率核查 (SPF / DKIM / DMARC)

正式对外启用安全邮箱前，需在发信域（如 `mail.nanshan-tech.com`）完成以下 DNS 认证配置：
1. **SPF (`TXT`)**：明确授权实际使用的 SMTP 出站出口 IP 或腾讯云 SES SPF Include，并在结尾收敛，防止他人伪造发件域；
2. **DKIM (`TXT`)**：在企业邮箱 / 腾讯云 SES 控制台生成 RSA 2048-bit 公钥并发布对应 Selector DNS 记录；
3. **DMARC (`TXT _dmarc`)**：建议上线初期 `p=quarantine` 或 `p=none; rua=...` 观察退信报告，域对齐稳定后切换 `p=reject`；
4. **事务发信与营销隔离**：验证码、密码重置与二次认证通知使用独立子域名及独立发信身份（`TriggerType=1`），避免被营销退信污染信誉。

---

## 4. 邮件投递状态阶段语义（Accepted vs Delivered）

| 阶段 | 状态值 (`send_state`) | 含义 | 运维关注重点 |
| :--- | :--- | :--- | :--- |
| 1. 事务落库 | `reserved` | 已获取行锁并写 `auth_challenge(pending_send)` 与 Redis 配额 | 若停留此态通常表示 DB 或风控中断 |
| 2. 网关受理 | `accepted` | SMTP `250 OK` 或 SES返回 `MessageId`（**不保证已进入收件箱**） | 用户反馈收不到邮件需核对退信或 SPF/DMARC |
| 3. 未知结果 | `unknown` | SMTP `DATA` 后断连或 SES 超时/5xx | **严禁自动重发**，等待用户使用原码或过期重申 |
| 4. 最终送达 | `delivered` | 通过 SES `GetSendEmailStatus` (`SendStatus=0`) 核实送达 | 仅限支持查询能力的服务商可确认 |
| 5. 拒绝/退信 | `rejected` / `bounced` / `delivery_failed` | 上游明确拒收或退信，`auth_challenge.status` 自动闭环为 `failed` | 按失败分类码排查发信身份或目标邮箱有效性 |

---

## 5. 上线检查与回滚步骤

### 5.1 启用前只读自检
```bash
cd tech-transfer-service
python tools/email_gateway_ops.py check-config
python tools/email_gateway_ops.py check-redis
python tools/email_gateway_ops.py check-provider
```
确认 `migration_036_ready: true`、`redis.lua: true`、`smtp_contract_ok: true`、`ses_contract_ok: true`。

### 5.2 紧急关闭与回滚方案
- **即时止血关闭通道**：设置 `EMAIL_ENABLED=false` 并重启/滚动刷新 API 服务。所有邮箱找回/绑定入口立即返回 503，`/auth/recovery/capabilities` 自动向 H5 与小程序下发 `emailOtp=false, emailLink=false`，已绑邮箱展示不受影响，短信找回不受影响。
- **保留历史数据**：`036_email_security_gateway.sql` 全为增量加列与新增表，禁止生产盲目 DROP 字段；如需临时回滚版本，旧版代码仅忽略新加可空列。
