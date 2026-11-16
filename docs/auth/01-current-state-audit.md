# 南山科转通统一身份认证系统：现状代码审计报告 (01-current-state-audit)

**审查基准提交**：`7efffea12eb59a30137cde6633b7cfa9ed1c7ec1`  
**功能分支**：`feat/unified-auth-recovery`  
**审计时间**：2026-11-16  

---

## 1. 真实代码路径与关键函数审查

### 1.1 后端服务 (`tech-transfer-service`)

| 代码路径 | 关键函数/类 | 核心职责与实现机制 |
|---|---|---|
| `routes/auth.py` | `login`, `register`, `refresh`, `logout`, `wechat_login`, `wechat_bind`, `bootstrap` | 认证路由入口：基于 Pydantic 声明请求体；调用 `core.rate_limit` 进行 IP 级滑动窗口限流；调用 `modules.identity.service` 与 `wechat.py` 执行业务认证。 |
| `routes/me.py` | `get_me`, `patch_my_profile`, `post_my_password` | 当前登录用户个人中心路由：`post_my_password` 处理登录后修改密码，依赖 `core.middleware.identity` 提取 `userId`。 |
| `modules/identity/service.py` | `password_login_session`, `login_phone_session`, `register_password_user`, `register_user`, `refresh_session`, `logout_session`, `change_password`, `_issue_session`, `build_user_response` | 核心认证服务：管理账号密码校验、手机号校验、JWT 签发、RefreshToken 轮转、密码变更及用户信息组装。 |
| `modules/identity/wechat.py` | `wechat_login_session`, `exchange_login_code`, `exchange_phone_code`, `_access_token` | 微信小程序认证：通过 `sns/jscode2session` 换取 OpenID，通过 `wxa/business/getuserphonenumber` 获取手机号，加 advisory 锁防止并发绑定竞争。 |
| `modules/identity/provider.py` | `IdentityProvider`, `LocalDevIdentityProvider`, `get_identity_provider` | 宿主身份提供方抽象：本地开发提供 mock 身份，生产环境禁止 mock。 |
| `core/password.py` | `hash_password`, `verify_password` | 密码哈希：当前采用 `pbkdf2_sha256$200000$<salt_hex>$<hash_hex>`，仅依赖 Python 标准库 `hashlib`。 |
| `core/jwt_utils.py` | `sign_access_token`, `sign_refresh_token`, `decode_token`, `decode_no_verify_exp` | JWT 工具库：签发 Access Token（默认 7200 秒）与 Refresh Token（默认 14 天），生成 `jti`。载荷未包含会话版本 `session_version`。 |
| `core/middleware.py` | `identity`, `_user_is_active`, `_is_admin_role`, `_org_admin_info`, `optional_identity` | FastAPI 鉴权依赖：解析 Bearer Token，利用 `core.auth_cache` 30 秒缓存校验用户活跃状态；未校验 token 签发时的用户会话版本。 |
| `core/rate_limit.py` | `_check`, `_client_ip`, `check_login_rate`, `check_register_rate`, `check_ip_rate` | 内存限流器：基于进程内 `collections.deque` 滑动窗口与可信代理检测，多 worker 部署下进程间状态不共享。 |
| `core/auth_cache.py` | `cached`, `invalidate_user`, `clear` | 鉴权内存短缓存：30 秒 TTL，支持写路径主动失效指定用户的鉴权缓存。 |
| `modules/profile/service.py` | `get_my_profile`, `update_my_profile` | 用户资料服务：基于乐观锁 `version` 更新 `user_profile`（包括 `phone`、`email` 等字段）。 |
| `config.py` | `Settings`, `assert_environment` | 统一配置管理与生产环境安全断言（拦截弱密码、弱 JWT 密钥与 mock 身份）。 |
| `db.py` | `get_cursor`, `transaction`, `init_pool`, `close_pool` | 基于 `psycopg2.pool.ThreadedConnectionPool` 的数据库连接池与事务上下文。 |

### 1.2 前端与客户端

| 代码路径 | 核心组件/方法 | 审查现状与缺陷 |
|---|---|---|
| `nanshan-frontend/src/views/auth/LoginView.vue` | `handleLogin`, `form.remember` | PC 登录页：仅支持账号密码登录；“记住密码”复选框实际仅持久化 `username`；“忘记密码？”按钮目前为死按钮（无点击事件）。 |
| `nanshan-frontend/src/views/auth/RegisterView.vue` | `handleRegister` | PC 注册页：输入用户名、密码、手机号、邮箱，提交至 `/auth/register`。 |
| `nanshan-frontend/src/stores/auth.js` | `login`, `logout`, `setUser`, `refreshUser`, `storage` 监听 | Pinia 状态管理：支持跨标签页 storage 监听与自动同步。 |
| `nanshan-frontend/src/api/client.js` | `api`, `doRequest`, `refreshAccessToken`, `saveSession` | 统一 API 客户端：维护 `nanshan_admin_token`、`nanshan_admin_refresh_token`；支持 401 自动并发刷新重试。 |
| `南山小程序/南山/subpackages/tech-transfer/api/client.js` | `saveSession`, `clearSession`, `doRefreshToken`, `ensureSession` | 小程序端 API 客户端：基于 `HostBridge` 封装 storage 与网络请求；维护 `tt_access_token` 与 `tt_refresh_token`。 |
| `南山小程序/南山/subpackages/tech-transfer/api/user.js` | `loginAccount`, `registerAccount`, `loginWithWechat`, `setInitialPassword`, `saveUserProfile`, `logout` | 小程序端用户业务门面：支持微信快捷登录、首次设置密码、登出缓存深度清扫。 |
| `南山小程序/南山/subpackages/tech-transfer/pages/mine/mine.vue` | `onAuthSubmit`, `onWechatLogin`, `onSetInitialPassword`, `onLogout` | 小程序“我的”页面：集成了登录/注册卡片、微信手机号授权、首次设置密码弹窗，但缺少专门的“账号与安全”二级管理界面。 |

---

## 2. 现有能力与新增能力的差距对比

| 维度 | 现有能力 (Baseline) | 目标新增能力 (Target) | 差距分析 |
|---|---|---|---|
| **身份主体** | `app_user.id` 统一为主体，关联 `user_credential` 与 `external_identity` | 保持 `app_user.id` 唯一核心，扩展统一认证联系方式 `account_contact` | 现有手机号散落在 `user_credential.phone` 和 `user_profile.phone`，无联系方式确权体系。 |
| **联系方式确权** | 注册时输入或编辑资料随意填写，无验证机制 | 严格的 `account_contact` 模型，必须通过短信/邮件挑战验证 (`verified_at IS NOT NULL`) | 现有 `user_profile.phone/email` 不具备恢复密码资格。 |
| **密码找回** | **完全无找回功能**。PC 端点击无响应，小程序端无入口 | 完备的短信 OTP 与邮箱一次性重置链接，防账号枚举，原子消费 | 需构建 Challenge、Recovery Grant、SmsProvider、EmailProvider 全流程。 |
| **会话失效机制** | 仅支持 Refresh Token 轮转与主动 logout，修改密码不会使旧 Access Token 失效 | `app_user.session_version` 全局会话版本控制，密码重置即时失效所有旧 Access Token 和 Refresh Token | 需在 JWT payload 注入版本号并在中间件校验。 |
| **密码哈希算法** | 仅标准库 PBKDF2-SHA256 (200,000 次) | 升级支持 Argon2id，并兼容历史 PBKDF2，登录成功平滑升级 | 需兼顾环境依赖与向下兼容性。 |
| **限流防刷** | 单机内存滑动窗口限流 | 分布式 Redis 限流 (Lua 原子脚本) + 内存 Fallback 兜底 | 需防止暴力破解、短信/邮件轰炸和跨进程穿透。 |
| **微信认证** | 仅微信小程序 `code2Session` + 手机号授权 | 保留小程序能力，新增 PC 网页微信扫码 OAuth2 (`wechat-web`) | 需实现 OAuth state 管理、防 CSRF、一次性 code 兑换及绑定保护。 |
| **多端前端** | PC 仅简单登录/注册；小程序仅在“我的”页面内嵌简单卡片 | PC 新增忘记密码/重置密码/安全中心；小程序新增“账号与安全”设置 | 补齐全链路交互、倒计时、状态同步与安全审计展示。 |

---

## 3. 账号、密码与会话生命周期分析

### 3.1 账号生命周期
```
[外部访问]
   ├─► 小程序手机号注册 ──► 创建 app_user(Uxxxx) + user_profile + user_credential(username=phone, phone=phone) + user_role('user') ──► 签发首期会话
   ├─► 后台账号注册 ─────► 创建 app_user(Uxxxx) + user_profile + user_credential(username, phone) + user_role('user') ──► 重定向登录
   ├─► 微信首次登录 ─────► 授权手机号 ──► 创建 app_user + external_identity('wechat-mini') + user_credential(password_configured=false) ──► 签发首期会话
   └─► 状态流转 ────────► active ──(管理员封禁)──► disabled ──(软删除)──► deleted_at IS NOT NULL
```

### 3.2 密码生命周期
1. **生成与配置**：
   - 普通注册用户：注册时直接输入明文，经 `hash_password()` 存储为 PBKDF2-SHA256 哈希，`password_configured=true`。
   - 微信新用户：系统自动生成随机随机密码，`password_configured=false`。
2. **校验**：
   - 登录时提取哈希串，解析算法与盐值，通过 `hmac.compare_digest` 比较。
3. **变更 (现有)**：
   - `POST /me/password`：仅在已登录态下校验 `currentPassword`（若已配置），更新 `password_hash`。
   - **重大漏洞**：修改密码未吊销历史会话，旧 Access Token 在剩余有效期（最长 2 小时）内仍可正常调用 API。

### 3.3 会话生命周期
1. **签发**：`_issue_session` 签发 Access Token（2小时）和 Refresh Token（14天，写入 `auth_session` 表，状态 `active`）。
2. **刷新**：客户端 401 或即将过期时调用 `/auth/refresh`，原子更新旧 `auth_session` 状态为 `consumed`，签发新的一对 Token。
3. **中间件校验**：`core.middleware.identity` 校验 JWT 签名与有效期，并通过 `auth_cache` 检查 `app_user.status == 'active'`。
4. **失效漏洞**：中间件未校验会话版本，旧 Access Token 只要未过期且用户 `status=='active'`，即使密码被篡改或用户被管理员强制重置也无法立即拦截。

---

## 4. 数据库演进与迁移风险

### 4.1 存量数据状况
- `app_user`: 存量用户编号形如 `U1`、`U2`。
- `user_credential`:
  - 部分用户 `username` 为纯 11 位手机号（小程序注册）。
  - 部分用户 `username` 为英文字符串，`phone` 为 11 位数字或 NULL（后台注册）。
  - 迁移 `012_user_credential_phone.sql` 已引入部分唯一索引 `uk_user_credential_phone` (`WHERE phone IS NOT NULL`)。
- `user_profile`:
  - 含有非受约束的 `phone` 和 `email`。用户可在个人中心随意编辑，可能存在多个用户填写相同手机号或邮箱的情况。
- `external_identity`:
  - 存储 `wechat-mini` 的 OpenID，且在 `027_profile_avatar_wechat_login.sql` 中建立了 `(tenant_id, user_id) WHERE issuer='wechat-mini' AND unlinked_at IS NULL` 唯一约束。

### 4.2 迁移风险与应对策略
1. **存量联系方式冲突**：
   - 风险：若将 `user_profile.phone/email` 自动视作已确权安全凭证，存量重复手机号会导致唯一索引构建失败，并产生跨账号密码找回严重漏洞。
   - 策略：坚决执行**资料与安全凭证物理分离**原则。新增 `account_contact` 表，存量 `user_profile` 数据绝不自动确权。提供离线扫描脚本识别冲突。
2. **会话版本号平滑过渡**：
   - 风险：在 `app_user` 增加 `session_version INT NOT NULL DEFAULT 1` 后，历史存量 JWT 中无 `ver` 载荷。
   - 策略：设计兼容验证逻辑——若 JWT 无 `ver`，则当 `app_user.session_version == 1` 时予以兼容放行；一旦发生密码重置或安全事件，`session_version` 递增至 2 以上，无版本的旧 JWT 立即失效被拒。
3. **迁移文件编号**：
   - 当前最新 PostgreSQL 迁移为 `migrations/pg/032_ai_task_progress_stage.sql`。
   - 新迁移定义为 `migrations/pg/033_unified_account_security.sql`。

---

## 5. 安全隐患深度排查

1. **会话吊销盲区**：
   - 当前 `change_password` 仅执行 `UPDATE user_credential`，未变更用户会话版本，未将 `auth_session` 置为 `revoked`。黑客若窃取了 access_token，受害者即便修改密码，黑客仍可在有效窗口内持续操作。
2. **防账号枚举缺失**：
   - 现有登录接口已注意防枚举，但尚未建立找回密码流程。找回密码第一步如果提示“该手机号未注册”或“该邮箱不存在”，将成为全站用户枚举接口。
3. **验证码重放与跨用途利用**：
   - 若验证码仅哈希后比对，未与 `challenge_id`、`purpose`（例如 `password_recovery` 对比 `bind_phone`）以及目标联系方式强绑定，可能发生跨接口盗用。
4. **单机限流防线脆弱**：
   - `core/rate_limit.py` 为进程内内存存储。在多进程（`UVICORN_WORKERS > 1`）部署下，攻击者通过轮询 worker 可获得成倍的尝试机会；重启服务后限流计数清零，容易被利用进行短信轰炸或撞库。
5. **微信 OAuth CSRF 风险**：
   - PC 扫码登录需要经过浏览器重定向，若 `state` 参数可预测或未与发起端会话单向强校验，易遭受 OAuth 登录 CSRF 攻击，导致受害者绑定攻击者的微信。

---

## 6. 改造范围与不可破坏的兼容性要求

### 6.1 改造范围
1. **数据模型与迁移**：
   - 编写 `033_unified_account_security.sql`，创建 `account_contact`、`auth_challenge`、`recovery_grant`，并为 `app_user` 增加 `session_version`。
2. **安全核心基础设施**：
   - 增强 `core/password.py`：支持 Argon2id 与 PBKDF2 双向解析与平滑升级。
   - 增强 `core/jwt_utils.py` 与 `core/middleware.py`：签发与校验 `session_version`。
   - 引入 `modules/security/provider.py`：构建 `SmsProvider`、`EmailProvider` 接口与 Tencent / Mock 适配器。
   - 引入 `modules/security/rate_limiter.py`：构建 Redis 分布式滑动窗口限流器及内存兜底。
3. **密码恢复与联系方式业务服务**：
   - 编写 `modules/security/service.py`：确权绑定、发起挑战、原子核验、签发短期 Recovery Grant、单事务密码重置并失效全部会话。
   - 开放标准化 API：`/auth/recovery/start`、`/auth/recovery/verify`、`/auth/recovery/complete` 及联系方式安全管理接口。
4. **微信体系扩展**：
   - 新增 PC 扫码 OAuth2 流程 (`wechat-web`)，安全比对 UnionID 与 state。
5. **多端前端升级**：
   - Vue 3 后台：改造 `LoginView.vue`，新增 `ForgotPasswordView.vue`、`ResetPasswordView.vue`、`AccountSecurityView.vue`。
   - 小程序：在 `pages/mine/mine.vue` 中接入“账号与安全”设置，支持手机号/邮箱确权绑定与密码管理。

### 6.2 不可破坏的兼容性红线
- 现有 `POST /auth/login` 请求格式（支持 `username` 与 `phone`）及响应包装绝对不可破坏。
- 现有微信小程序登录 `/auth/wechat/login` 与绑定 `/auth/wechat/bind` 接口与字段完全向下兼容。
- 现有业务权限与角色判断（系统 `admin`、机构 `org_admin`）全部基于 `app_user.id`，不受新增认证模式影响。
- 存量用户的 PBKDF2 密码必须能正常登录，并在登录验证通过后静默升级。
- 当外部 SMS、Email、Redis 服务未配置密钥时，系统必须降级为测试替身或安全关闭对应恢复渠道，严禁启动崩溃或放行未经验证的重置请求。
