# 南山科转通统一身份认证系统安全威胁模型与防御架构

## 1. 概述与威胁分析方法

本威胁模型遵循 STRIDE 与 OWASP ASVS (Application Security Verification Standard) 4.0 认证与会话管理标准，针对南山科转通统一身份认证系统涉及的身份确权、密码重置、多端会话控制、微信 OAuth 及服务商通道进行系统性安全建模。

```mermaid
flowchart TD
    subgraph Untrusted["外部未受信环境"]
        Attacker["攻击者 / 恶意客户端"]
        UserBrowser["用户浏览器 / 微信客户端"]
    end

    subgraph DefensePerimeter["边界防御层"]
        WAF["速率限制与防刷中间件 (SecurityRateLimiter)"]
        AntiEnum["防枚举与恒定延时网关"]
    end

    subgraph CoreAuth["认证与安全核心层"]
        ChallengeSvc["验证挑战引擎 (HMAC加盐/原子尝试)"]
        GrantSvc["恢复授权签发 (Recovery Grant 256位)"]
        SessionVer["会话版本中心 (Session Version / Cache)"]
    end

    subgraph StorageLayer["持久化与安全存储"]
        PG[(PostgreSQL 18 - 事务隔离与部分唯一索引)]
        Redis[(Redis 缓存与滑动窗口)]
    end

    Attacker -->|探测 / 碰撞 / 重放| WAF
    UserBrowser -->|合法请求| WAF
    WAF --> AntiEnum
    AntiEnum --> ChallengeSvc
    ChallengeSvc --> GrantSvc
    GrantSvc --> SessionVer
    SessionVer --> PG
    WAF -.-> Redis
```

---

## 2. 威胁矩阵与防御机制 (STRIDE 分析)

| STRIDE 威胁分类 | 具体攻击场景 | 严重级别 | 平台防御机制 | 实现位置 |
| :--- | :--- | :--- | :--- | :--- |
| **S - 仿冒 (Spoofing)** | 1. 伪造已验证手机号/邮箱重置他人密码<br>2. 伪造微信 OAuth 回调 code/state<br>3. 冒用他人过期或旧 Access Token | **CRITICAL** | 1. 仅限 `account_contact` 中 `verified_at IS NOT NULL` 的联系方式具备重置资格；资料字段 (`user_profile`) 零特权。<br>2. OAuth2 state 采用 256 位 CSPRNG，10 分钟单次使用验证；回调必须通过微信开放平台后端 code exchange。<br>3. JWT payload 携带 `ver` (session_version)，网关与中间件毫秒级版本校验，版本不一致立即拒止 (401)。 | `modules/security/service.py`<br>`modules/identity/wechat_web.py`<br>`core/middleware.py` |
| **T - 篡改 (Tampering)** | 1. 并发请求多次消费同一验证码<br>2. 篡改 Recovery Grant 关联的 userId<br>3. 数据库内明文验证码被内网侧信道窃取 | **HIGH** | 1. 数据库行锁 `FOR UPDATE` + 原子状态迁移 `UPDATE ... SET status='consumed' WHERE status='pending'`。<br>2. Recovery Grant 随机密文字符串不承载明文 payload，服务端仅存 SHA256 摘要，与指定 user_id 严格关联。<br>3. 验证码在数据库存储为 `HMAC-SHA256(secret, challenge_id:purpose:code)`，加盐且不可逆。 | `modules/security/service.py`<br>`migrations/pg/033_unified_account_security.sql` |
| **R - 抵赖 (Repudiation)** | 1. 恶意用户重置他人密码后否认操作<br>2. 冒用他人已注销手机号发起登录 | **MEDIUM** | 1. 全生命周期安全审计日志：每次验证码申请、验证成功、密码重置、会话吊销均记录 `actor_user_id`、`client_ip`、`user_agent`、`destination_fingerprint` 与时间戳。<br>2. 联系方式撤销时记录 `revoked_at`，并在审计日志保留历史证据。 | `routes/auth.py`<br>`routes/me.py`<br>`modules/security/service.py` |
| **I - 信息泄露 (Information Disclosure)** | 1. 账号探测：根据找回密码返回推断用户是否存在<br>2. 手机/邮箱脱敏不规范泄漏用户真实隐私<br>3. 邮件重置链接在 Referer 或历史记录中泄露 Token | **HIGH** | 1. **全链路防枚举 (Anti-Enumeration)**：账号不存在或未绑定有效联系方式时，系统模拟固定范围耗时延时，并返回完全一致的成功响应格式 (`sent: true`)，不泄露任何存在性线索。<br>2. 脱敏策略：手机号保留前 3 后 4 (`138****1234`)，邮箱仅保留首字符与域名 (`a***@example.com`)。<br>3. 前端 ResetPasswordView 页面加载后立即执行 `window.history.replaceState` 清除 URL 中的 Token 参数。 | `modules/security/service.py`<br>`nanshan-frontend/src/views/auth/ResetPasswordView.vue` |
| **D - 拒绝服务 (Denial of Service)** | 1. 恶意轰炸短信/邮件接口消耗企业资费<br>2. 并发爆破 6 位数字验证码 (100万可能)<br>3. Redis 宕机引起认证网关雪崩 | **HIGH** | 1. 三级滑动窗口速率限制：单目标 60 秒冷静期，单 IP 每分钟上限，单联系方式日上限；配置限流保护。<br>2. 每个 Challenge 严格限制最多 5 次失败尝试，第 5 次失败后 Challenge 立即标记为失效；5 分钟硬超时。<br>3. 内存与 Redis 双模限流器无缝降级，生产环境下支持 Fail-Closed 严格保护资费安全。 | `modules/security/rate_limiter.py`<br>`modules/security/service.py` |
| **E - 提权 (Elevation of Privilege)** | 1. 普通用户通过找回密码直接将账号提升为管理员<br>2. 修改密码后旧设备会话仍可继续访问管理接口 | **CRITICAL** | 1. 密码重置仅更新凭证 (`user_credential`)，完全不影响 `user_role` 与机构权限表。<br>2. 密码重置成功立即在单一数据库事务内完成：更新 `password_hash`、递增 `session_version`、吊销全部活动 `auth_session`，旧 Access Token 与 Refresh Token 秒级失效。 | `modules/security/service.py`<br>`core/middleware.py` |

---

## 3. 核心密码学与安全机制深度剖析

### 3.1 挑战验证码 HMAC 存储算法
针对传统系统直接存储 6 位数字验证码明文或使用无盐 SHA256 导致可使用彩虹表秒级破解的问题，本项目设计并实现了加盐加上下文的 HMAC-SHA256 存储规范：

$$\text{code\_hash} = \text{HMAC-SHA256}\Big(\text{SECRET\_KEY},\; \text{challenge\_id} \parallel \text{":"} \parallel \text{purpose} \parallel \text{":"} \parallel \text{code}\Big)$$

- **防彩虹表破解**：引入包含 UUID 与全局秘钥的双重盐；
- **防跨用途重放**：`purpose` 绑定（如 `password_recovery` 的摘要不能通过 `contact_binding` 的校验）；
- **防跨记录重用**：绑定单一 `challenge_id`。

### 3.2 恒定时间比较与定时攻击防御
验证过程采用 Python 标准库 `hmac.compare_digest(computed_hash, stored_hash)`，杜绝基于字符逐字节比对时间的侧信道探测。

在找回密码入口 (`start_password_recovery`)，当查询用户不存在或目标联系方式未绑定时，采用 `time.sleep(random.uniform(0.08, 0.15))` 模拟真实的数据库加盐哈希计算耗时，消除了因快速返回而暴露的账号枚举漏洞。

### 3.3 Recovery Grant 单次授权凭证
恢复授权凭证通过 `secrets.token_urlsafe(32)` 生成（256 位熵）。
- 凭证在服务端仅存储其 SHA256 摘要：
  $$\text{grant\_hash} = \text{SHA-256}(\text{token})$$
- 客户端提交明文 `token`，服务端计算摘要并在事务中执行原子核验与标记：
  ```sql
  UPDATE recovery_grant
  SET used_at = CURRENT_TIMESTAMP
  WHERE grant_hash = $1 AND user_id = $2 AND used_at IS NULL AND expires_at > CURRENT_TIMESTAMP
  RETURNING id;
  ```
- 任何并发提交均保证最多 1 个成功，且绝不赋予通用业务 API 访问权限。

---

## 4. 会话失效与全端实时撤销保障

```mermaid
sequenceDiagram
    autonumber
    actor Alice as 用户 (重置密码设备)
    actor Bob as 攻击者 / 丢失旧设备
    participant Gateway as API 网关 / 中间件
    participant Cache as auth_cache / Redis
    participant DB as PostgreSQL

    Alice->>Gateway: POST /auth/recovery/complete (提交新密码与 grant)
    Gateway->>DB: 开启数据库事务
    DB->>DB: 消耗 grant
    DB->>DB: 更新 user_credential.password_hash
    DB->>DB: UPDATE app_user SET session_version = session_version + 1
    DB->>DB: UPDATE auth_session SET is_revoked = true (吊销所有 RefreshToken)
    DB-->>Gateway: 事务提交成功
    Gateway->>Cache: auth_cache.invalidate_user(user_id)
    Gateway-->>Alice: 200 OK (签发新版本 Token ver=N+1)

    par 旧设备发起请求
        Bob->>Gateway: GET /me/profile (携带旧 Token ver=N)
        Gateway->>Cache: 查询 user_id 会话版本
        Cache-->>Gateway: 返回最新 session_version = N+1
        Gateway-->>Bob: 401 Unauthorized (会话已失效，请重新登录)
    and 旧设备刷新 Token
        Bob->>Gateway: POST /auth/refresh (携带旧 RefreshToken)
        Gateway->>DB: 查询 auth_session
        DB-->>Gateway: is_revoked = true
        Gateway-->>Bob: 401 Unauthorized (RefreshToken 已吊销)
    end
```

该机制保证在不增加普通高频只读请求数据库负担的前提下（内存缓存 30 秒 TTL，写路径立即淘汰），实现秒级全端会话失效。
