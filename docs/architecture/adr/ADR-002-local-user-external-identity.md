# ADR-002 · 本地用户与外部身份映射（Local User + External Identity）

> 状态：已冻结（Frozen，2026-09-02 冻结评审通过，决议见 10-freeze-review.md；此后只增不改）
> 日期：2026-09-02
> 决策人：科转通架构组
> 影响范围：用户表设计、认证流程、所有业务表外键、前端身份获取方式

---

## 1. 背景与问题

科转通嵌入 Ai南山后，用户在上级平台登录，科转通看到的只是"上级给的某个用户标识"。工程上有两种直觉做法，都已被否决：

1. **直接把上级 `user_id` 当科转通业务主键**：上级 ID 的格式、稳定性、唯一范围（是否分租户）都不受科转通控制。一旦上级 ID 体系变更（换 OpenID、加租户维度、ID 回收重发），科转通所有业务表的外键全部污染，且无法修复。
2. **复制上级账号密码到科转通库**：违反"不复制上级账号密码"的强制约束，制造第二个密码权威源，安全与合规均不可接受。

另一个现状问题：本地演示代码 `common/user.js` 把**手机号当主键、密码明文存小程序缓存**（`ns_user_accounts`，见 `01-current-state-audit.md` §10 S1/S2），这套逻辑绝不能带进正式设计。

## 2. 决策

科转通维护**自己的本地用户体系**，与上级身份通过映射表关联：

```text
上级认证（Ai南山 Token / 本地 Mock 票据）
    → external_identity（issuer + tenant_id + external_subject 唯一定位一条映射）
    → app_user（科转通本地用户，主键为 bigint 自增 id）
    → user_profile（业务资料：姓名、手机、邮箱、身份类型等）
    → 业务表（achievement / demand / favorite / cooperation_* 统一关联 app_user.id）
```

### 2.1 核心规则（不可违反）

1. `app_user.id` 是科转通一切业务表的唯一用户外键；
2. `external_identity` 唯一约束：`UNIQUE (issuer, tenant_id, external_subject)`，**`tenant_id` 不可为 NULL**（MySQL 的 UNIQUE 索引中多个 NULL 互不冲突，会破坏唯一性；默认填 `'default'`）；
3. 上级机器身份标识（external_subject，形如 `ou_xxxx` 的 open_id/union_id）**永远不得**显示为用户姓名；姓名取 `user_profile.display_name`，为空时前端显示"未填写"；
4. 手机号、邮箱、姓名都是**资料字段**，不是身份主键，允许变更，变更不影响任何业务数据归属；
5. 创建需求/成果/收藏/对接时，前端**不传** `ownerUserId`；后端从认证中间件解析出的 `IdentityContext` 中取当前用户；
6. 一个 `app_user` 可以有多条 `external_identity`（本地测试身份 + 未来上级正式身份可共存于开发库），映射表支持软解绑。

### 2.2 身份提供者（IdentityProvider）双实现

| 实现 | issuer | 适用环境 | 说明 |
|------|--------|----------|------|
| `MockIdentityProvider` | `local-dev` | 仅 `local` / `development` / `testing` | 返回固定开发身份（subject=`dev-user-001`），票据本地签发；**在 staging/production 环境服务启动时直接拒绝启动**（硬保护，见 02 §8.3） |
| `AiNanshanIdentityProvider` | `ainanshan`（待上级确认实际值） | `staging` / `production` | 验证上级网关传入的身份凭证（Token 格式待上级确认，见 `08-upper-platform-checklist.md` C-01） |

两者必须产出**同一个 `IdentityContext` 结构**：

```json
{
  "userId": 10001,            // app_user.id，后端内部填充，前端不可提交
  "issuer": "local-dev",
  "externalSubject": "dev-user-001",
  "tenantId": "default",
  "displayName": "本地测试用户",
  "roles": ["user"]
}
```

前端永远不解析上级 user_id，只通过 `POST /auth/bootstrap` 用宿主凭证换取科转通侧会话（流程见 02 §6）。

## 3. 备选方案与否决理由

| 备选方案 | 否决理由 |
|----------|----------|
| 上级 user_id 直接作主键 | 上级 ID 体系不受本方控制；无法支持多 issuer（本地测试 + 上级正式）；违背强制约束 #2 |
| 无本地用户表，业务表直接存 external_subject 字符串 | 同上，且所有业务表都要冗余字符串外键，无法加数据库级外键约束 |
| OAuth 全量代理（科转通替用户向上级换取资料） | 上级规范未定，过度设计；映射表方案不排斥未来补充资料拉取 |

## 4. 后果

**正面：**
- 上级 ID 体系任何变化只需改映射表数据，不动业务表；
- 本地开发与正式环境共用同一套业务表结构与权限逻辑；
- 机器 ID 与显示名彻底解耦，杜绝"把 open_id 当姓名显示"的事故。

**负面与代价：**
- 每个请求多一次映射解析（一期用进程内缓存 + JOIN，成本可忽略）；
- 首次登录需要"查找或创建"映射的幂等处理（并发首登用 `UNIQUE` 约束兜底，冲突后重查）；
- 上级身份字段（如手机号）同步策略需要与上级确认（默认：科转通只在自己表里存用户主动填写的资料，不自动同步，见 08 C-02）。

## 5. 合规检查项

1. 所有业务表用户外键是否均为 `app_user.id`（bigint）？
2. `external_identity` 是否有 `UNIQUE (issuer, tenant_id, external_subject)` 且 `tenant_id NOT NULL DEFAULT 'default'`？
3. 是否存在任何接口允许前端提交 `ownerUserId` / `user_id` 并被后端采信？
4. staging/production 启动时 `AUTH_PROVIDER=mock` 是否直接失败？
5. 前端是否存在把 external_subject / open_id 渲染为姓名的代码路径？

## 6. 关联

- 数据模型：`05-data-model-design.md` §2（身份域表）
- 认证时序：`02-target-architecture.md` §6
- 上级待确认项：`08-upper-platform-checklist.md`（C-01 Token 格式、C-02 用户字段、C-03 网关身份头）
