# Phase R 安全边界收敛与生产可靠性加固架构说明 (13-phase-r-hardening)

## 1. 加固目标与设计原则

在不推倒重做既有 Email/SMS Security Gateway 主干的前提下，针对多阶段边界、跨事务并发、HTTP 重试幂等、投递状态机与外部对账中的 11 项高优先隐患 (**R01–R11**) 执行结构化收敛：

| 编号 | 加固项 | 核心改动模块 |
| :--- | :--- | :--- |
| **R01** | 安全邮箱首次绑定强制会话级安全授权 | [step_up.py](../../../tech-transfer-service/modules/security/step_up.py)、[email_gateway.py](../../../tech-transfer-service/modules/security/email_gateway.py)、[service.py](../../../tech-transfer-service/modules/security/service.py)、[AccountSecurityView.vue](../../../nanshan-frontend/src/views/admin/AccountSecurityView.vue)、[mine.vue](../../../%E5%8D%97%E5%B1%B1%E5%B0%8F%E7%A8%8B%E5%BA%8F/%E5%8D%97%E5%B1%B1/subpackages/tech-transfer/pages/mine/mine.vue) |
| **R02** | 真实初次认证时间戳 `auth_time` 与稳定逻辑会话 `sid` | [037_phase_r_security_hardening.sql](../../../tech-transfer-service/migrations/pg/037_phase_r_security_hardening.sql)、[jwt_utils.py](../../../tech-transfer-service/core/jwt_utils.py)、[middleware.py](../../../tech-transfer-service/core/middleware.py)、[modules/identity/service.py](../../../tech-transfer-service/modules/identity/service.py) |
| **R03** | 全链路统一数据库行锁顺序 + 有界重试 | [modules/security/service.py](../../../tech-transfer-service/modules/security/service.py)、[step_up.py](../../../tech-transfer-service/modules/security/step_up.py)、[modules/identity/service.py](../../../tech-transfer-service/modules/identity/service.py) |
| **R04** | 匿名找回核验统一防枚举错误语义 `TT_AUTH_RECOVERY_INVALID` | [core/errors.py](../../../tech-transfer-service/core/errors.py)、[modules/security/service.py](../../../tech-transfer-service/modules/security/service.py) |
| **R05** | `bind_email` / `rebind_email` 目标地址强制端到端绑定 | [037_phase_r_security_hardening.sql](../../../tech-transfer-service/migrations/pg/037_phase_r_security_hardening.sql)、[step_up.py](../../../tech-transfer-service/modules/security/step_up.py)、[AccountSecurityView.vue](../../../nanshan-frontend/src/views/admin/AccountSecurityView.vue)、[mine.vue](../../../%E5%8D%97%E5%B1%B1%E5%B0%8F%E7%A8%8B%E5%BA%8F/%E5%8D%97%E5%B1%B1/subpackages/tech-transfer/pages/mine/mine.vue) |
| **R06** | PostgreSQL 作用域隔离的 HTTP 请求级持久幂等 | [idempotency.py](../../../tech-transfer-service/modules/security/idempotency.py)、[routes/auth.py](../../../tech-transfer-service/routes/auth.py)、[routes/me.py](../../../tech-transfer-service/routes/me.py)、[emailSecurity.js](../../../nanshan-frontend/src/utils/emailSecurity.js) |
| **R07** | 投递状态参数化 CAS 原子更新与终态防复活 | [state_machine.py](../../../tech-transfer-service/modules/security/state_machine.py)、[email_gateway.py](../../../tech-transfer-service/modules/security/email_gateway.py)、[sms_gateway.py](../../../tech-transfer-service/modules/security/sms_gateway.py) |
| **R08** | 全非活跃/失败/崩溃路径明文 PII 剥离与幂等清理 | [sms_gateway.py](../../../tech-transfer-service/modules/security/sms_gateway.py)、[idempotency.py](../../../tech-transfer-service/modules/security/idempotency.py) |
| **R09** | 历史 Provider/配置实例校验与腾讯云 SES 官方 `DeliverStatus` 对齐 | [email_providers.py](../../../tech-transfer-service/modules/security/email_providers.py)、[email_gateway.py](../../../tech-transfer-service/modules/security/email_gateway.py) |
| **R10** | 类型安全门禁闭环 (`mypy` 0 errors 阻断 CI) | [rate_limit.py](../../../tech-transfer-service/core/rate_limit.py)、[ci.yml](../../../.github/workflows/ci.yml) |
| **R11** | 外部实发基线诚实留白与文档链接仓库化校准 | [12-final-acceptance.md](12-final-acceptance.md)、[14-phase-r-acceptance.md](14-phase-r-acceptance.md) |

---

## 2. 关键安全边界详述

### 2.1 会话真实认证时间 (`auth_time`) 与逻辑会话 (`sid`)

- **登录即落库**：`password_login_session` 与 `bootstrap_session` 在创建 `auth_session` 时生成 UUID `sid` 与实时整数时间戳 `auth_time`，写入 `auth_session` 与首对 Access/Refresh Token。
- **Refresh Rotation 严禁推进**：`refresh_session` 通过单条 `UPDATE ... WHERE refresh_jti=%s AND status='active' RETURNING sid, auth_time` 原子消费旧 Refresh 并沿用原 `sid` 与原 `auth_time`；历史 `NULL` 会话绝不伪造为当前时间。
- **集中式 `SecurityOperationPolicy`**：仅非高权限、未设置密码账号且同时满足有效 `sid` + 非未来有效 `auth_time`（在 `STEP_UP_RECENT_AUTH_SECONDS` 窗口内）时允许 `recent_auth`；有密码用户及管理员账号仅允许强验证方式。
- **前端首次绑定强制流程**：H5 与微信小程序端选择绑定安全邮箱时，无论首次绑定（`bind_email`）还是更换邮箱（`rebind_email`），均先确认目标邮箱并完成 Step-up 授权，然后携绑定同一逻辑会话的 `stepUpGrant` 发起邮箱验证码与绑定确认。

### 2.2 全局规范锁顺序 (`R03`)

全部核心写事务严格遵从全序加锁路径，杜绝跨路径 `AB-BA` 死锁：

```text
app_user
  -> user_credential
  -> auth_challenge
  -> account_contact
  -> recovery_grant
  -> step_up_grant
  -> auth_session
```

- `verify_recovery_challenge` 与 `complete_password_recovery` 通过无锁预查询获取 `user_id`，在写事务首位即加锁 `app_user FOR UPDATE`；密码 `hash_password` 昂贵计算统一移至事务行锁之外，并用 `_run_with_deadlock_retry` 兜底有界重试（最多 3 次）。

### 2.3 三层幂等语义 (`R06` / `R07`)

1. **HTTP 请求级幂等**：请求限流后，基于 HMAC 隔离作用域 `(endpoint, user_id[:sid] | client_ip)` 与请求参数摘要持久化占位 `security_delivery_request`；同 Key 并发重放返回原响应，参数不一致返回 `409 TT_COMMON_40901`，调用外部服务商前的校验失败自动释放键值；当发生 `outcome_unknown=True` 时收敛为 `unknown`，阻断盲目重发（`503`）。
2. **Worker 任务级幂等**：`UPDATE ... WHERE id=%s AND state='queued' ... RETURNING payload` 原子抢占。
3. **投递状态机 CAS 幂等**：`transition_delivery_state()` 以 `WHERE id=%s AND send_state = ANY(%s) RETURNING status, send_state` 执行受控状态迁移，终态 Challenge (`consumed`/`expired`/`locked`/`failed`/`cancelled`) 面对迟到状态回执绝不复活为 `pending`。

### 2.4 异步对账与官方 SES 状态语义 (`R09`)

依据腾讯云 SES `GetSendEmailStatus`（`2020-10-02`）官方契约：
- 默认查询日期按 `Asia/Shanghai` (`UTC+8`) 计算，支持 `Offset` 分页及按 `MessageId` 精确匹配后取最大 `DeliverTime`；
- `DeliverStatus`: `0` 队列排队中 / `8` 延迟投递（不提前终态化）、`1` 已送达 (`delivered`)、`2` 丢弃 (`delivery_failed`)、`3` 对端拒收退信 (`bounced`)；
- 校验 `provider_name` 与非敏感 `provider_config_id` 指纹一致性，切仓/改配自动终止核对并转 `provider_configuration_changed` 人工复核；绝不落库原始 `DeliverMessage`。
