# 南山科转通统一身份认证系统生产部署与运维操作手册 (Runbook)

## 1. 部署前检查与准备 (Pre-deployment Checklist)

### 1.1 数据冲突审计
在执行数据库变更前，必须运行随系统提供的历史数据冲突审计工具，探测现有数据库中是否存在异常格式、重复手机号或未确权冲突：

```bash
cd tech-transfer-service
# 设置生产数据库连接环境变量后执行
python tools/audit_contact_conflicts.py
```

- 若脚本输出 `[OK] 数据库内未发现历史手机号/邮箱唯一性冲突`，可安全继续；
- 若报告存在重复手机号，依据审计报告中的 `user_id` 与 `user_credential.phone` 进行人工核实与合并处理。

### 1.2 生产数据库备份
执行全库快照备份，确保具备一键还原能力：

```bash
pg_dump -h $DB_HOST -p $DB_PORT -U $DB_USER -Fc -d $DB_NAME > /backup/nanshan_pre_033_$(date +%Y%m%d%H%M%S).dump
```

---

## 2. 数据库迁移执行 (Database Migration)

按顺序执行增量幂等迁移（`033`–`036`，包含 `IF NOT EXISTS`、历史未决挑战收敛与冲突保护）：
1. `tech-transfer-service/migrations/pg/033_unified_account_security.sql`
2. `tech-transfer-service/migrations/pg/034_sms_security_gateway.sql`
3. `tech-transfer-service/migrations/pg/035_sms_delivery_diagnostics.sql`
4. `tech-transfer-service/migrations/pg/036_email_security_gateway.sql`

> 完整 Email Security Gateway 部署、DNS (SPF/DKIM/DMARC) 与回滚详情见：[docs/auth/email-gateway/10-deployment-runbook.md](./email-gateway/10-deployment-runbook.md)。

### 2.1 执行迁移
```bash
for f in 033_unified_account_security.sql 034_sms_security_gateway.sql 035_sms_delivery_diagnostics.sql 036_email_security_gateway.sql; do
  psql -h $DB_HOST -p $DB_PORT -U $DB_USER -d $DB_NAME -v ON_ERROR_STOP=1 -f "migrations/pg/$f"
done
```

### 2.2 迁移后校验
连接数据库执行以下核对 SQL：

```sql
-- 1. 验证 app_user.session_version 字段已添加
SELECT column_name, data_type, column_default 
FROM information_schema.columns 
WHERE table_name = 'app_user' AND column_name = 'session_version';

-- 2. 验证核心安全表已就绪
SELECT table_name FROM information_schema.tables 
WHERE table_name IN ('account_contact', 'auth_challenge', 'recovery_grant')
ORDER BY table_name;

-- 3. 验证历史凭证手机号回填数量
SELECT count(*) AS active_phone_contacts FROM account_contact WHERE contact_type = 'phone' AND status = 'active';

-- 4. 验证部分唯一索引
SELECT indexname, indexdef FROM pg_indexes 
WHERE tablename = 'account_contact' AND indexname LIKE '%uniq%';
```

---

## 3. 生产环境变量配置 (Production Configuration)

在生产环境管理机（或 Docker / K8s ConfigMap / Secret）中配置以下环境变量：

### 3.1 短信与邮件服务商 (外部依赖)
```ini
# --- 短信服务 (腾讯云 SMS) ---
SMS_ENABLED=true
SMS_PROVIDER=tencent
TENCENTCLOUD_SECRET_ID=AKIDxxxxxxxxxxxxxxxxxxxx
TENCENTCLOUD_SECRET_KEY=yyyyyyyyyyyyyyyyyyyyyyyy
TENCENTCLOUD_SMS_SDK_APP_ID=1400000000
TENCENTCLOUD_SMS_SIGN_NAME=南山科转通
TENCENTCLOUD_SMS_TEMPLATE_ID=1234567
SMS_OTP_EXPIRY_SECONDS=300

# --- 邮件服务 (腾讯云 SES 或 SMTP；EMAIL_PROVIDER 仅支持 tencent / smtp / non-prod mock) ---
EMAIL_ENABLED=true
EMAIL_PROVIDER=tencent
TENCENT_SES_SECRET_ID=AKIDxxxxxxxxxxxxxxxxxxxx
TENCENT_SES_SECRET_KEY=yyyyyyyyyyyyyyyyyyyyyyyy
TENCENT_SES_FROM_EMAIL=service@mail.nanshan-tech.com
TENCENT_SES_REGION=ap-hongkong
TENCENT_SES_ENDPOINT=ses.tencentcloudapi.com
EMAIL_CODE_TTL_SECONDS=300
EMAIL_LINK_TTL_SECONDS=300
EMAIL_CODE_MAX_ATTEMPTS=5

# 或使用标准企业 SMTP：
# EMAIL_PROVIDER=smtp
# SMTP_HOST=smtp.exmail.qq.com
# SMTP_PORT=465
# SMTP_USER=service@mail.nanshan-tech.com
# SMTP_PASSWORD=xxxxxxxxxxxx
# SMTP_FROM_EMAIL=service@mail.nanshan-tech.com
# SMTP_USE_SSL=true
# SMTP_TIMEOUT_SECONDS=10
```

### 3.2 微信开放平台 PC 扫码登录 (外部依赖)
```ini
WECHAT_OPEN_ENABLED=true
WECHAT_OPEN_APPID=wx0123456789abcdef
WECHAT_OPEN_APP_SECRET=0123456789abcdef0123456789abcdef
FRONTEND_URL=https://tech.nanshan.gov.cn
```

### 3.3 缓存与限流 (Redis)
```ini
REDIS_ENABLED=true
REDIS_URL=redis://:YourStrongPassword@10.0.0.12:6379/0
AUTH_CACHE_TTL_SECONDS=30
```

> [!WARNING]
> 生产环境启动时，`config.assert_environment()` 会执行严格校验。若 `APP_ENV=production` / `staging` 下启用了 `mock` 服务商、`REDIS_ENABLED=false`、`FRONTEND_URL` 非受信任 `https://`（如 `localhost`）或缺少必要服务商凭证/强秘钥，服务将直接拒绝启动；同时 `SecurityRateLimiter` 与风控引擎严格 Fail-Closed。

---

## 4. 服务上线与滚动发布 (Rolling Update)

### 4.1 后端服务更新
```bash
# 构建镜像并执行无损滚动重启
docker build -t nanshan-tech-transfer:v1.2.0 -f Dockerfile .
docker service update --image nanshan-tech-transfer:v1.2.0 --update-parallelism 1 --update-delay 10s nanshan_api
```

### 4.2 前端 Vue 3 静态资源发布
```bash
cd nanshan-frontend
npm ci
npm run build
# 同步 dist 产物至 CDN / Nginx 静态目录
rsync -avz --delete dist/ /var/www/nanshan-frontend/
```

### 4.3 微信小程序更新发布
1. 使用微信开发者工具打开 `南山小程序/南山`；
2. 检查 `project.config.json` AppID 并在本地或体验版进行真机预览测试；
3. 上传代码至微信公众平台发布体验版；
4. 提交微信审核并发布正式版。

---

## 5. 冒烟测试与拨测脚本 (Smoke Testing)

执行自动化生产冒烟探针：

```bash
# 1. 验证微信网页授权配置接口
curl -sS https://tech.nanshan.gov.cn/api/auth/wechat/web/config | jq .

# 2. 验证找回密码入口防探测与脱敏
curl -sS -X POST https://tech.nanshan.gov.cn/api/auth/recovery/start \
  -H "Content-Type: application/json" \
  -d '{"account": "probe_test_nonexist", "channel": "sms"}' | jq .

# 预期返回: {"sent": true, "challengeId": null, "message": "若该账号已绑定有效联系方式，验证信息已发送"}

# 3. 验证未授权访问会话版本受控接口
curl -sS -I https://tech.nanshan.gov.cn/api/me/security | head -n 1
# 预期返回: HTTP/1.1 401 Unauthorized
```

---

## 6. 应急回滚预案 (Rollback Plan)

若上线后遇到严重不可预见故障，执行以下步骤回滚：

### 6.1 代码与容器版本回退
```bash
docker service rollback nanshan_api
```

### 6.2 数据库安全降级 (若需物理回滚)
```sql
BEGIN;

-- 1. 撤销新增安全表
DROP TABLE IF EXISTS recovery_grant CASCADE;
DROP TABLE IF EXISTS auth_challenge CASCADE;
DROP TABLE IF EXISTS account_contact CASCADE;

-- 2. 移除 session_version（若必要）
-- ALTER TABLE app_user DROP COLUMN IF EXISTS session_version;

COMMIT;
```
> [!NOTE]
> `app_user.session_version` 具有向下兼容性（即使不删除该列，旧版本代码也能正常运行），通常建议保留该列与已迁移表，仅回退服务镜像即可。
