# SendCloud SMTP 正式接入与阶段验收报告

> **状态声明**：本次已完成基于代码仓库与本机环境的 SendCloud SMTP 参数安全注入、DNS 核验、TCP 587 连通性测试、严格 TLS 1.3 `STARTTLS` + `SMTP AUTH` 认证、Redis Lua 风控检查、离线单元测试回归，以及用户授权的受控单次 OTP 发送受理（`SMTP ACCEPTED`）。因远程 PostgreSQL（`183.36.37.85:19258`）当前不可达，完整业务流（`PostgreSQL Challenge + CAS + Step-up`）与真实收件箱投递/邮件头认证回执尚未闭环，本报告结论维持 **`SMTP_AUTHENTICATED`**（严格区分 `SMTP ACCEPTED` 与 `PROVIDER DELIVERED` / `INBOX RECEIVED`）。

---

## 1. 接入摘要（脱敏）

```text
SendCloud Integration

Repository Commit SHA: ac3af7ea714a4f2fbffc1602bb240cf6dd8b9241
APP_ENV: local
Provider: smtp (SmtpEmailProvider, provider_config_id=bb5cfb590b141d2f)
SMTP Host: smtp.sendcloud.net
SMTP Port: 587
TLS Mode: STARTTLS (SMTP_USE_SSL=false, strict SSLContext TLSv1.3)
API_USER: nanshan_security
API_KEY Configured: true
Sender Address: noreply@cxniu.cn
Sender Name: 南山科转通
DNS Verification: PASS (SPF/DKIM/DMARC via 223.5.5.5, MX via default & public DNS)
SMTP TCP: PASS (106.75.106.125:587 TcpTestSucceeded=True)
TLS Handshake: PASS (STARTTLS 220, TLSv1.3 TLS_AES_128_GCM_SHA256, CN=*.sendcloud.net)
SMTP Authentication: PASS (SMTP AUTH 235)
PostgreSQL Schema: BLOCKED (OperationalError: 183.36.37.85:19258 closed connection unexpectedly)
Redis Risk Engine: PASS (127.0.0.1:6379/0, ping=true, lua=true)
Email Binding: NOT RUN (requires PG Challenge + Step-up flow)
Email OTP: SMTP ACCEPTED via SmtpEmailProvider.send_code_task (request_id=sc-live-98ad5ff2d9b8; PG Challenge/CAS & OTP verify NOT RUN)
Password Recovery: NOT RUN (requires PG Challenge + CAS flow)
Reset Link: NOT RUN (code route & fragment parser verified; FRONTEND_URL=http://localhost:5173)
Actual Inbox Receipt: PENDING USER VERIFICATION (haohaizi554@gmail.com receipt not yet confirmed by user)
SPF Authentication: PENDING INBOX HEADER CHECK (DNS PASS; actual inbox header authentication awaits user receipt inspection)
DKIM Authentication: PENDING INBOX HEADER CHECK (DNS PASS; actual inbox header authentication awaits user receipt inspection)
DMARC Authentication: PENDING INBOX HEADER CHECK (DNS PASS; actual inbox header authentication awaits user receipt inspection)
SendCloud Delivery Status: PENDING CONSOLE CHECK (request_id=sc-live-98ad5ff2d9b8; requires SendCloud console delivery log verification)
SMS Regression: PASS (SMS_ENABLED=true, SMS_PROVIDER=sendcloud, SENDCLOUD_SMS_USER=nanshan intact; test_sendcloud_security.py 10 passed)
Known Remaining Risks: 1) Remote PostgreSQL 183.36.37.85:19258 unreachable for Schema Gate 039 verification; 2) Local HMAC secrets (SECURITY_OTP_HMAC_SECRET / SECURITY_CONTACT_HMAC_SECRET / EMAIL_RISK_HMAC_SECRET) and custom JWT_SECRET unset in local .env; 3) FRONTEND_URL defaults to http://localhost:5173 (must switch to HTTPS domain before external/prod reset link testing); 4) SendCloud console tracking options (open/click tracking off for nanshan_security) require manual operator verification; 5) Historical async worker ownership & Redis coordination hardening residual notes remain as documented in prior Phase R reports.
```

---

## 2. Phase SC0 脱敏环境审计

```text
APP_ENV: local
Python Interpreter: D:\Users\Administrator\Desktop\南山小程序\.venv\Scripts\python.exe (Python 3.13.17)
Effective Environment Source: tech-transfer-service/.env (overlaid by empty-email tech-transfer-service/.env.local containing only AI_AGENT_URL; no process env overrides)
Email Provider: smtp
SMTP Host: smtp.sendcloud.net
SMTP Port: 587
SMTP Credentials Configured: true
Database Schema Version: BLOCKED (target 183.36.37.85:19258/tech_transfer unreachable; codebase requires Schema Gate "039")
Redis Enabled: true
Redis Connected: true (redis://127.0.0.1:6379/0, lua=true)
Frontend Reset URL: http://localhost:5173 (H5 route /reset-password parses URL Fragment without GET consumption)
```

补充审计说明：
- 进程检查未发现运行中的 `tech-transfer-service` `uvicorn` 进程。
- `.gitignore` 已忽略 `.env` 与 `.env.local`；`git ls-files "*env*"` 确认真实环境文件未被 Git 跟踪。
- 已有短信配置保持原样：`SMS_ENABLED=true`、`SMS_PROVIDER=sendcloud`、`SENDCLOUD_SMS_USER=nanshan`（与邮件账号 `nanshan_security` 相互独立），`SENDCLOUD_SMS_KEY`、数据库、Redis 与微信配置均未改动。

---

## 3. 配置变更（SC1 & SC2）

仅更新 `tech-transfer-service/.env`（未改 `.env.local`、`.env.example` 与历史迁移），注入且保持脱敏：

- SMTP 通道：`EMAIL_ENABLED=true`、`EMAIL_PROVIDER=smtp`、`SMTP_HOST=smtp.sendcloud.net`、`SMTP_PORT=587`、`SMTP_USER=nanshan_security`、`SMTP_PASSWORD=[REDACTED]`、`SMTP_FROM_EMAIL=noreply@cxniu.cn`、`SMTP_FROM_NAME=南山科转通`、`SMTP_USE_SSL=false`、`SMTP_TIMEOUT_SECONDS=10`、`SMTP_MAX_ATTEMPTS=2`。
- 邮件安全风控与门禁：`EMAIL_RISK_ENGINE_ENABLED=true`、`EMAIL_REQUIRE_VERIFIED_CONTACT=true`、`EMAIL_CODE_TTL_SECONDS=300`、`EMAIL_LINK_TTL_SECONDS=300`、`EMAIL_CODE_MAX_ATTEMPTS=5`、`EMAIL_COOLDOWN_SECONDS=60`、`EMAIL_GLOBAL_DAILY_BUDGET=5000`、`EMAIL_SECURITY_NOTIFICATION_ENABLED=false`、`EMAIL_LIVE_TEST_ENABLED=false`。

> **安全密钥提示**：当前本地 `.env` 未单独配置 `SECURITY_OTP_HMAC_SECRET`、`SECURITY_CONTACT_HMAC_SECRET`、`EMAIL_RISK_HMAC_SECRET`，且 `JWT_SECRET` 仍为开发默认值。进入 `staging` / `production` 部署前必须按环境配置强随机密钥并严禁上线后随意轮换。另因 `API_KEY` 曾通过对话窗口传入，建议完成联调验收后在 SendCloud 控制台评估是否轮换。

---

## 4. 实测验证结果（SC3 / SC4 / SC5 / SC6 / SC9）

### 4.1 公网 DNS 与网络连通性
- `Resolve-DnsName smtp.sendcloud.net`：解析出多个 A 记录（含 `106.75.106.125`、`106.75.81.75` 等）。
- `Test-NetConnection smtp.sendcloud.net -Port 587`：`RemoteAddress=106.75.106.125`，`TcpTestSucceeded=True`。
- `Resolve-DnsName cxniu.cn -Type MX`：`mx.sendcloud.org`（Preference `1`）。
- 公共 DNS（`223.5.5.5`）核查 `cxniu.cn` TXT：
  - **SPF**：`v=spf1 include:spf.sendcloud.org -all`
  - **DKIM (`mail._domainkey.cxniu.cn`)**：`k=rsa;p=MIGfMA0GCSqGSIb3...IDAQAB`
  - **DMARC (`_dmarc.cxniu.cn`)**：`v=DMARC1;p=reject;ruf=mailto:dmarc@cxniu.cn;rua=mailto:dmarc_report@cxniu.cn`
- 未修改公司原有 `centips.com` 企业邮箱配置。

### 4.2 严格 TLS 握手与 SMTP AUTH（零发信）
使用 `.venv\Scripts\python.exe` 通过 `config.settings` 与 `build_strict_ssl_context()`（`CERT_REQUIRED` + `check_hostname=True` + TLSv1.2+）连接 `smtp.sendcloud.net:587`（未调用 `sendmail`/`send_message`、未开启 `debuglevel`）：
- `EHLO`: `250`
- `STARTTLS`: `220`
- `TLS`: `TLSv1.3`（`TLS_AES_128_GCM_SHA256`）
- 证书校验通过：`CN=*.sendcloud.net`，`SAN=['*.sendcloud.net', 'sendcloud.net']`
- `SMTP AUTH`: `235`（`SMTP AUTH SUCCESS`）

### 4.3 邮件诊断 CLI（`tools/email_gateway_ops.py`）
- `check-config`：`EMAIL_ENABLED=true`、`EMAIL_PROVIDER=smtp`、`SMTP_HOST/USER/PASSWORD/FROM_EMAIL=true`、`EMAIL_LIVE_TEST_ENABLED=false`、`redis.connected=true` (`lua=true`)、`postgres.connected=false` (`OperationalError`)。
- `check-redis`：`connected=true`、`ping=true`、`lua=true`、`latency_ms=78.28`。
- `check-provider`：`real_send_attempted=false`、`smtp_contract_ok=true`、`active_provider="smtp"`、`email_enabled=true`、`credentials_configured=true`。
- 独立 `check_required_security_schema()`：因 `183.36.37.85:19258` 连接被对端关闭，返回 `OperationalError`（`BLOCKED`）。

### 4.4 密码重置页面与离线单元测试回归
- 前端代码核查：[router/index.js](file:///D:/Users/Administrator/Desktop/南山小程序/nanshan-frontend/src/router/index.js)、[emailSecurity.js](file:///D:/Users/Administrator/Desktop/南山小程序/nanshan-frontend/src/utils/emailSecurity.js) 与 [ResetPasswordView.vue](file:///D:/Users/Administrator/Desktop/南山小程序/nanshan-frontend/src/views/auth/ResetPasswordView.vue) 确认 `/reset-password` 存在，仅在 `onMounted` 提取 URL Fragment（`#challengeId=...&token=...`）并调用 `history.replaceState` 清理地址栏，不在 GET 加载时消费凭据，仅在用户主动提交新密码时调用 `/auth/recovery/verify`。
- 离线回归测试结果：
  - `pytest tests/test_email_provider.py tests/test_email_smtp.py tests/test_email_diagnostics.py tests/test_sendcloud_security.py -q`：**24 passed in 5.13s**
  - `pytest tests/test_security_acceptance_manifest.py -q`：**4 passed in 1.13s**

### 4.5 用户授权单次 OTP 投递受理记录（`SMTP ACCEPTED`）
在用户明确授权向 `haohaizi554@gmail.com` 发送验证码后，由于远程 PostgreSQL（`183.36.37.85:19258`）仍处于不可达状态（`OperationalError`），通过现有生产适配器 `get_email_provider().send_code_task(...)`（`SmtpEmailProvider` + 生产 OTP 模板，不打印明文验证码）执行了单次受控发送：
- `accepted`: `true`（`SMTP ACCEPTED`，不等同于收件箱送达）
- `provider`: `"smtp"`
- `channel`: `"email_otp"`
- `request_id`: `"sc-live-98ad5ff2d9b8"`
- `provider_message_ids`: `["<179565639568.35564.3662979829561733292@cxniu.cn>"]`
- 发件人 / 收件人：`南山科转通 <noreply@cxniu.cn>` -> `haohaizi554@gmail.com`
- 说明：完整业务链路（`PG Challenge + CAS + Step-up` 及 OTP 核验入库）仍待数据库连通后联调。

---

## 5. 本轮验收矩阵（SC-A01 – SC-A28）

| 编号 | 验收内容 | 状态 | 实测说明 |
|---|---|---|---|
| SC-A01 | SendCloud 发信域名配置正确 | PASS | `cxniu.cn`、`noreply@cxniu.cn` 与控制台参数一致 |
| SC-A02 | SPF DNS 验证通过 | PASS | `223.5.5.5` 返回 `v=spf1 include:spf.sendcloud.org -all` |
| SC-A03 | DKIM DNS 验证通过 | PASS | `mail._domainkey.cxniu.cn` 返回 RSA 公钥记录 |
| SC-A04 | DMARC DNS 验证通过 | PASS | `_dmarc.cxniu.cn` 返回 `v=DMARC1;p=reject;...` |
| SC-A05 | MX DNS 验证通过 | PASS | `cxniu.cn` MX 指向 `mx.sendcloud.org` |
| SC-A06 | API_USER 正确配置 | PASS | `SMTP_USER=nanshan_security`（未覆盖短信 `nanshan`） |
| SC-A07 | API_KEY 安全注入 | PASS | 已写入未跟踪的 `tech-transfer-service/.env` |
| SC-A08 | Git 未泄露真实密钥 | PASS | `git ls-files "*env*"` 与 `git status -s` 均不含 `.env` |
| SC-A09 | SMTP TCP 连接成功 | PASS | `smtp.sendcloud.net:587` TCP 连通 |
| SC-A10 | STARTTLS 握手成功 | PASS | `STARTTLS` 返回 `220` |
| SC-A11 | TLS 证书及主机名校验成功 | PASS | `TLSv1.3`，校验证书 `CN=*.sendcloud.net` 通过 |
| SC-A12 | SMTP AUTH 成功 | PASS | `server.login()` 返回 `235` |
| SC-A13 | PostgreSQL 最新安全 Schema 就绪 | BLOCKED | 远程 DB `183.36.37.85:19258` 连接被对端关闭 |
| SC-A14 | Redis Lua 风控正常 | PASS | `check-redis`：`ping=true`、`lua=true` |
| SC-A15 | 安全邮箱绑定邮件真实送达 | BLOCKED | `SmtpEmailProvider` 已获 `SMTP ACCEPTED`（`request_id=sc-live-98ad5ff2d9b8`），待用户确认收件箱送达及 PG 绑定全链路 |
| SC-A16 | 邮箱 OTP 核验正常 | NOT RUN | 需 PG Challenge 持久化后验证单次核验 |
| SC-A17 | 邮箱首次绑定及 Step-up 正常 | NOT RUN | 需 PG 连通并走完完整业务接口 |
| SC-A18 | 邮箱验证码找回密码正常 | NOT RUN | 需 PG 连通并走完完整业务接口 |
| SC-A19 | 邮件链接找回密码正常 | NOT RUN | 待公网 HTTPS `FRONTEND_URL` 与 PG 全链路联调 |
| SC-A20 | 密码重置后旧会话撤销 | NOT RUN | 待全链路联调 |
| SC-A21 | 邮件追踪不会破坏恢复链接 | BLOCKED | 需用户在 SendCloud 控制台手动核实关闭打开/点击追踪 |
| SC-A22 | 实际收件邮件 SPF/DKIM/DMARC 认证 | NOT RUN | 需在 `haohaizi554@gmail.com` 查看已发出邮件的原始邮件头确认 `spf/dkim/dmarc=pass` |
| SC-A23 | SendCloud 投递结果可核对 | NOT RUN | 需在 SendCloud 控制台「数据中心/投递记录」核对 `sc-live-98ad5ff2d9b8` 对应状态 |
| SC-A24 | 原有短信服务无回归 | PASS | 短信凭证保留未动；`test_sendcloud_security.py` 10 项全过 |
| SC-A25 | 未授权真实发送被禁止 | PASS | 仅在用户明确授权后向 `haohaizi554@gmail.com` 发送 1 封受控测试验证码，`LIVE_TEST` 仍关闭 |
| SC-A26 | 测试完成后关闭 LIVE_TEST | PASS | `.env` 中 `EMAIL_LIVE_TEST_ENABLED=false` |
| SC-A27 | 原有认证安全保护保持启用 | PASS | Risk Engine、Verified Contact、Step-up、CAS 均保持启用 |
| SC-A28 | 紧急停用及回滚方案明确 | PASS | 见第 7 节紧急回滚方案 |

---

## 6. 历史外部验收状态（EXT-EMAIL-01 – EXT-EMAIL-03）

根据 `docs/auth/email-gateway/acceptance-manifest.yaml`（本轮未修改 Manifest 既有门禁条目与 `test_security_acceptance_manifest.py`）：

- **EXT-EMAIL-01（真实 SMTP 投递及受控收件箱确认）**：保持 **`NOT RUN`**，待 Phase SC7–SC8 受控真实投递及收件箱查验完成后方可更新。
- **EXT-EMAIL-02（真实腾讯云 SES 投递及受控收件箱确认）**：保持 **`NOT RUN`**，当前正式启用通道为 SendCloud SMTP，腾讯云 SES 未参与本轮接入。
- **EXT-EMAIL-03（SPF / DKIM / DMARC 与发信域名配置检查）**：公网 DNS 记录已查验通过，但需在真实收件箱中核验原始邮件头认证结果后再最终关闭，目前在 Manifest 中仍保持 **`NOT RUN`**。

---

## 7. 紧急回滚方案

若 SendCloud 通道出现异常，仅需将当前生效的 `tech-transfer-service/.env` 中的邮件开关置为关闭：

```dotenv
EMAIL_ENABLED=false
```

随后按授权范围重载或重启后端服务，完整保留用户账号、已绑定邮箱、PostgreSQL 迁移、安全审计记录、短信通道（`SMS_ENABLED=true`）、JWT 与 HMAC 密钥及 Redis 其他业务数据。

---

## 8. 下一阶段前提与最终结论

- **当前结论**：**`SMTP_AUTHENTICATED`**
- 进入 Phase SC7–SC8（真实投递与业务全链路验收）前需用户确认或提供：
  1. 恢复或接入目标 **PostgreSQL（`183.36.37.85:19258` 或实际部署库）** 以完成 Schema Gate `039` 验证。
  2. 提供 **受控测试账号** 与 **受控收件邮箱**，并明确授权单次/联调真实外发。
  3. 在 SendCloud 控制台确认针对 `nanshan_security` 已将 **「打开追踪：关闭」「点击追踪：关闭」**。
  4. 如需外部测试「邮件链接找回密码」，提供公网可访问的有效 HTTPS `FRONTEND_URL`。
