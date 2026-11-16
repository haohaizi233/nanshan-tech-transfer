# 南山科转通统一身份安全架构目标设计 (02-target-architecture)

## 1. 架构核心原则

1. **单一用户主体**：
   - 全平台业务体系（成果、需求、对接、收藏、机构成员、管理员权限）始终且唯一以 `app_user.id` 作为外键主体。
   - 所有登录认证渠道（账号密码、手机号密码、短信OTP、邮箱重置、微信小程序、PC微信OAuth2）统一解析并映射到唯一的 `app_user.id`。
   - 严禁因引入新认证方式为同一自然人分流创建独立业务用户。

2. **凭证、资料与安全联系方式的三层物理隔离**：
   - **基础资料层 (`user_profile`)**：存放展示昵称、企业/机构抬头、合作画像等弱安全属性。用户可自主维护，字段变更不改变认证资格。
   - **登录凭证层 (`user_credential` / `external_identity`)**：存放登录用户名、密码哈希（Argon2id / PBKDF2）、微信 OpenID/UnionID 绑定。
   - **确权安全联系方式层 (`account_contact`)**：存放通过双向挑战（OTP / 邮件确认）验证过的手机号与邮箱。只有满足 `status='active' AND verified_at IS NOT NULL` 的联系方式才具备密码恢复和敏感操作核验资格。

3. **双重时效与即时会话失效**：
   - JWT Access Token 携带用户会话版本号 `ver` (`app_user.session_version`)。
   - 发生密码重置、密码修改或强制下线时：
     1. 单事务递增 `app_user.session_version`；
     2. 将用户所有活跃 `auth_session` 标记为 `revoked`；
     3. 立即清理内存/分布式鉴权缓存；
     4. 旧 Access Token 在下一次任何 API 调用时因版本不匹配立即被拒绝 (401)，杜绝传统 JWT“签发即不可撤销”的安全缺陷。

---

## 2. 身份认证与安全架构拓扑图

```
                         ┌──────────────────────────────────────────────┐
                         │                  多端交互入口                  │
                         │   PC Vue 3 后台  /  uni-app 微信小程序  /  H5   │
                         └──────────────────────┬───────────────────────┘
                                                │ (HTTPS / Bearer JWT)
                                                ▼
                         ┌──────────────────────────────────────────────┐
                         │          API 网关 / 路由接入层                │
                         │    routes/auth.py  /  routes/me.py           │
                         └──────┬───────────────────────────────┬───────┘
                                │                               │
                     (限流拦截 / CSRF)                     (Token 解析)
                                ▼                               ▼
                ┌───────────────────────────────┐ ┌───────────────────────────────┐
                │     分布式原子限流器           │ │     身份鉴权与会话版本校验      │
                │  Redis (Lua) + 进程内存滑动窗口 │ │  core/middleware.py (identity)│
                └───────────────────────────────┘ └──────────────┬────────────────┘
                                                                 │
                                ┌────────────────────────────────┘
                                ▼
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                   业务与安全服务核心层                                   │
│                                                                                        │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌────────────────────────────┐  │
│  │ modules/identity/     │  │ modules/security/     │  │ modules/security/provider/ │  │
│  │   service.py          │  │   service.py          │  │   SmsProvider              │  │
│  │   - 账号密码登录       │  │   - 联系方式确权绑定   │  │   - TencentSmsProvider     │  │
│  │   - PBKDF2 / Argon2id │  │   - 短信/邮件挑战发起  │  │   - MockSmsProvider        │  │
│  │   - 会话签发与轮转     │  │   - HMAC 挑战原子消费  │  │   EmailProvider            │  │
│  │   - 微信小程序登录绑定 │  │   - Recovery Grant签发│  │   - TencentSesProvider     │  │
│  │   - PC 微信 OAuth2    │  │   - 密码重置与会话吊销 │  │   - MockEmailProvider      │  │
│  └───────────────────────┘  └───────────────────────┘  └────────────────────────────┘  │
└───────────────────────────────────────────┬────────────────────────────────────────────┘
                                            │
                                            ▼ (单个原子事务)
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                              PostgreSQL 统一身份存储引擎                                │
│                                                                                        │
│   app_user           ── (1:1) ──► user_credential (密码哈希/用户名)                      │
│      │               ── (1:1) ──► user_profile (个人展示资料)                           │
│      │               ── (1:N) ──► external_identity (wechat-mini / wechat-web)         │
│      │               ── (1:N) ──► account_contact (已确权安全手机/邮箱)                  │
│      │               ── (1:N) ──► auth_challenge (短信/邮件验证码挑战)                  │
│      │               ── (1:N) ──► recovery_grant (短期单次恢复授权)                     │
│      └───────────────── (1:N) ──► auth_session (RefreshToken 活跃会话)                 │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 密码找回与重置时序规范

```mermaid
sequenceDiagram
    autonumber
    actor User as 用户 (PC / 小程序)
    participant Route as routes/auth.py
    participant Sec as modules/security/service.py
    participant Limiter as Redis/Memory 限流器
    participant Provider as SMS / Email Provider
    participant DB as PostgreSQL 事务

    User->>Route: POST /auth/recovery/start (account, channel)
    Route->>Limiter: 检查 IP 限频 & 目标限额
    Limiter-->>Route: 放行
    Route->>Sec: start_recovery(account, channel)
    Sec->>DB: 查询已确权 contact (保持常数响应防枚举)
    alt 账号存在且有对应 channel 确权联系方式
        Sec->>Sec: 生成高强随机验证码 / 一次性重置 Token
        Sec->>DB: 插入 auth_challenge (保存 HMAC 摘要，pending)
        Sec->>Provider: 发送验证短信 / 重置邮件
    else 不存在或无联系方式
        Sec->>Sec: 模拟哈希耗时，防时间侧信道
    end
    Sec-->>User: 统一返回：验证码已发送至预留联系方式（回显脱敏目标）

    User->>Route: POST /auth/recovery/verify (challengeId, code)
    Route->>Limiter: 检查单挑验证频次
    Route->>Sec: verify_recovery(challengeId, code)
    Sec->>DB: 原子更新 auth_challenge (status='verified', 检查 attempt_count <= 5)
    Sec->>DB: 签发 5 分钟有效 recovery_grant (高熵随机数 SHA256 摘要)
    Sec-->>User: 返回 recoveryGrant

    User->>Route: POST /auth/recovery/complete (recoveryGrant, newPassword)
    Route->>Sec: complete_recovery(grant, newPassword)
    critical 单数据库事务
        Sec->>DB: 锁定并核销 recovery_grant (status='consumed')
        Sec->>DB: 验证新密码强度，计算 Argon2id/PBKDF2 哈希
        Sec->>DB: 更新 user_credential.password_hash & password_configured=true
        Sec->>DB: 递增 app_user.session_version = session_version + 1
        Sec->>DB: 吊销全部活跃 auth_session (status='revoked')
        Sec->>DB: 记录 audit_log ('auth.password_recovery')
    end
    Sec-->>User: 重置成功，要求重新登录
```

---

## 4. 微信多端统一身份模型

- **小程序端**：`issuer = 'wechat-mini'`, `tenant_id = settings.WECHAT_APPID`, `external_subject = openid`。
- **PC 网页端**：`issuer = 'wechat-web'`, `tenant_id = settings.WECHAT_OPEN_APPID`, `external_subject = web_openid`。
- **跨端打通保障**：微信开放平台返回 `unionid` 时，`external_identity` 将在凭证中保存 `unionid`；仅在 UnionID 经过官方微信接口证实且在同一开放平台主体下时，才允许安全识别为同一自然人，严禁基于昵称或普通手机号自动合流。
