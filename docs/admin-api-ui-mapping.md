# Admin 控制台 UI ↔ API 映射（admin-api-ui-mapping）

> 生成时间：2026-09-04（Release Closure）
> 服务：tech-transfer-service @ `/api/tech-transfer/v1`
> 用途：Admin 后台前端（待建）与后端 16 个 admin 接口的对接契约；字段名/错误码均以运行中服务实测为准

## 0. 通用契约（所有 Admin 页面共用）

| 项 | 约定 |
|----|------|
| Base | `http://<host>:8787/api/tech-transfer/v1` |
| 认证 | `Authorization: Bearer <token>`；后端每请求查 `user_role` 表实时校验 admin 角色 |
| 未登录 | HTTP 401 |
| 已登录非 admin | HTTP 403 + `code: "TT_ADMIN_40301"`（角色被撤销后旧 token 立即失效，前端应跳登录页） |
| 成功响应 | `{code: 0, message: "ok", data, requestId}` |
| 分页请求 | `?page=1&pageSize=10`（pageSize 上限 50，超出自动收敛） |
| 分页响应 | `data = {total, page, pageSize, totalPages, list}` |
| 列表排序 | 一律按 id DESC（最新在前）；platform 类机构列表走 serial_no ASC |
| 本地联调 token | `POST /auth/bootstrap` body `{"hostCredential": "local-dev-ticket-dev-user-001"}`（dev-user-001 为 005 种子 admin） |

### 错误码速查（Admin 域）

| code | HTTP | 场景 |
|------|------|------|
| `TT_ADMIN_40301` | 403 | 非管理员访问 admin 接口 |
| `TT_ADMIN_40001` | 400 | reject 未携带 reason |
| `TT_ACH_40901` / `TT_DMD_40901` | 409 | 非待审状态（重复审核/状态机拦截） |
| `TT_COMMON_40902` | 409 | version 乐观锁不匹配（并发审核，提示刷新） |
| `TT_INST_40001` | 400 | 机构 kind/platformTypeKey 非法 |
| `TT_INST_40401` | 404 | 机构不存在 |
| `TT_INST_40901` | 409 | 重复 online/offline（状态未变化） |
| `TT_COOP_40401` | 404 | 合作意向不存在 |
| `TT_COMMON_40402` | 404 | 用户不存在 |
| `TT_COMMON_40401` | 404 | 路径参数类型不匹配（既有全局约定，RequestValidation 映射） |

## 1. 仪表盘（Dashboard）

`GET /admin/dashboard/summary` → `data`：

| 字段 | 类型 | 说明 |
|------|------|------|
| users | int | 活跃用户数（status=active 且未删除） |
| achievements | int | 成果总数（未删除，全状态） |
| demands | int | 需求总数（未删除，全状态） |
| cooperations | int | 对接意向总数 |
| institutions | int | 上架机构数（status=active） |
| pendingAchievements | int | 待审成果数 |
| pendingDemands | int | 待审需求数 |
| pendingTotal | int | 前两项之和（待办角标） |

实现为单条 COUNT SQL，无趋势图假数据；趋势类需求属 P1+。

## 2. 审核中心

### 2.1 待审队列

| UI 页 | API | 过滤参数 |
|-------|-----|---------|
| 成果待审列表 | `GET /admin/achievements/review-queue` | keyword |
| 需求待审列表 | `GET /admin/demands/review-queue` | keyword |

列表项字段（两队列同构）：`id`、`title`、`status`、`version`、`categoryName`、`categoryCode`、`orgName`、`submitterUserNo`、`submitterName`、`submittedAt`。

### 2.2 审核操作

| 按钮 | API | 请求体 | 语义 |
|------|-----|--------|------|
| 通过 | `POST /admin/achievements/{id}/approve` | `{version}` | pending_review → published，published_at 落库 |
| 驳回 | `POST /admin/achievements/{id}/reject` | `{version, reason}`（reason 必填） | → rejected，reject_reason 落库，owner 可见 |
| 通过 | `POST /admin/demands/{id}/approve` | `{version}` | 同上（需求） |
| 驳回 | `POST /admin/demands/{id}/reject` | `{version, reason}` | 同上（需求） |

`version` 来自列表项，后端乐观锁校验；不匹配 → 409 `TT_COMMON_40902`，前端提示"数据已变更，请刷新"。
所有审核动作写审计日志（`achievement.approve/reject`、`demand.approve/reject`）。

## 3. 机构管理

| UI 操作 | API | 说明 |
|---------|-----|------|
| 列表（含下架） | `GET /admin/institutions?kind=&status=&keyword=&page=&pageSize=` | 管理端可见 disabled；status 默认全量 |
| 详情 | `GET /admin/institutions/{id}` | |
| 新建 | `POST /admin/institutions`（201） | Pydantic Schema 校验 |
| 编辑 | `PATCH /admin/institutions/{id}` | 部分更新（exclude_unset），空 body 400 |
| 下架 | `POST /admin/institutions/{id}/offline` | active → disabled |
| 上架 | `POST /admin/institutions/{id}/online` | disabled → active |

### 可见性闭环（前后端共同遵守）

```
admin 创建（active） → 小程序/H5 公开列表可见
admin offline        → 公开列表/详情不可见（detail 返回 data=null）
                      → 管理端仍可见（status=disabled，可检索）
admin online         → 公开恢复可见
```

机构项字段：`id`、`kind`（platform/invest/service）、`name`、`intro`、`detailInfo`、`label`、`logoFileId`、`logoUrl`（`/api/file/{id}` 直链）、`sortOrder`、`status`、`userType`、`sourcePk`、`sourceSite`、`fetchedAt`、`createdAt`、`updatedAt`；platform 类额外：`serialNo`、`platformType`、`platformTypeKey`（poc/pilot/other）、`unit`、`functionText`、`contact`、`phone`。

创建/编辑请求体字段（camelCase）：`kind`（必填，创建时）、`name`（必填）、`intro`、`detailInfo`、`label`、`logoFileId`、`sortOrder`、`userType`、`detailActivityId`、`platformType`、`platformTypeKey`、`unit`、`functionText`、`contact`、`phone`、`serialNo`。kind/source 溯源字段/id 不可编辑。写操作审计：`institution.create/update/online/offline`。

## 4. 对接管理

### 4.1 意向列表与详情

| UI 页 | API | 过滤参数 |
|-------|-----|---------|
| 意向列表 | `GET /admin/cooperations?status=&keyword=&handlingMode=&assistStatus=&targetType=&targetOrgId=` | status=状态机值；keyword 命中双方姓名/目标标题/留言；handlingMode=direct/assisted；assistStatus=平台协助阶段；targetType=achievement/demand；targetOrgId=目标机构 |
| 意向详情 | `GET /admin/cooperations/{id}` | 含 events 事件流 |

列表项字段：`id`、`initiatorUserId/UserNo/Name`、`targetOwnerUserId/UserNo/Name`、`targetType`、`targetId`、`targetTitle`、`targetOrgId/Name`、`message`、`status`、`handlingMode`、`assistStatus`、`acceptMode`、`handledByUserId/Name`、`version`、`createdAt/acceptedAt/confirmedAt/completedAt/closedAt`、`initiatorContact`（快照摘要）、`assistNote`、`contactShareConsentAt`。

详情额外 `events[]`：`id`、`eventType`、`fromStatus`、`toStatus`、`operatorUserId`、`operatorRole`、`remark`、`createdAt`。

### 4.2 管理员代发布

| UI 操作 | API | 说明 |
|---------|-----|------|
| 代录成果 | `POST /admin/achievements` | `ownerUserId` 可为空（NULL = 真实机构无平台账号，走 assisted）；必填 `orgId` |
| 代录需求 | `POST /admin/demands` | 同上 |
| 代提交审核 | `POST /admin/achievements/{id}/submit` | 代录入内容提交审核（有归属用户的内容不能代 submit，返回 400） |
| 代提交审核 | `POST /admin/demands/{id}/submit` | 同上 |

**重要：** Admin 是录入人（`created_by_user_id = admin`），不自动成为业务归属人。`ownerUserId = NULL` 表示真实机构尚无平台绑定账号，后续对接进入平台协助流程。

### 4.3 平台协助对接（Assisted Cooperation）

仅 `handlingMode = assisted` 的意向可执行以下操作。所有操作均需 `version` 乐观锁，状态冲突返回 409 `TT_COMMON_40902`。

| 按钮 / 操作 | API | 请求体 | 前置条件 | 效果 |
|------------|-----|--------|---------|------|
| 开始联系 | `POST /admin/cooperations/{id}/assist/start-contact` | `{version}` | status=pending，assist_status ∈ (queued, unreachable) | assist_status → contacting，handled_by = 当前 admin |
| 等待回复 | `POST /admin/cooperations/{id}/assist/waiting-reply` | `{version}` | status=pending，assist_status = contacting | assist_status → waiting_reply |
| 标记联系不上 | `POST /admin/cooperations/{id}/assist/mark-unreachable` | `{version}` | status=pending | assist_status → unreachable（**主状态仍为 pending**，联系不上≠拒绝） |
| 代接受 | `POST /admin/cooperations/{id}/assist/accept` | `{version, confirmationNote}`（confirmationNote 必填） | status=pending，assist_status ∈ (contacting, waiting_reply, unreachable)；**必须先线下获得机构明确同意** | status → accepted，assist_status → target_agreed，accept_mode → platform_assisted，accepted_at 落库 |
| 代拒绝 | `POST /admin/cooperations/{id}/assist/reject` | `{version, reason}`（reason 必填） | status=pending | status → rejected，assist_status → target_rejected，closed_at 落库 |

**代接受（assist/accept）是高风险操作：**
- `confirmationNote` 必须填写，记录确认依据（如"2026-09-07 电话联系李老师，对方确认愿意进一步对接"）
- 必须真实机构明确同意后才能点击，禁止看到申请就直接 accept
- 操作人、确认依据、事件、审计日志全部留痕，同一事务原子提交

### 4.4 联系方式与快照

- `initiatorContactSnapshot`（详情返回）：申请方联系方式快照（创建时服务端生成，防止申请人事后改资料导致历史申请联系人漂移）
- Admin 通过电话/邮件/微信将申请人意向和联系方式提供给目标机构（平台撮合）
- `assistNote`：运营内部记录，不对普通用户返回
- accepted 后，申请人侧自动解锁目标方联系方式（与 direct 流程一致）

### 4.5 审计

所有 Admin 协助操作均写审计日志：

| 操作 | audit action key |
|------|-----------------|
| 协助阶段变更 | `cooperation.assist_status` |
| 代接受 | `cooperation.admin_accept` |
| 代拒绝 | `cooperation.admin_reject` |
| 代发布创建 | `achievement.admin_create` / `demand.admin_create` |
| 代提交审核 | `achievement.admin_submit` / `demand.admin_submit` |

## 5. 用户管理（只读）

| UI 页 | API | 过滤参数 |
|-------|-----|---------|
| 用户列表 | `GET /admin/users?keyword=&status=&page=&pageSize=` | keyword 命中 userNo/displayName/orgName |
| 用户详情 | `GET /admin/users/{id}` | |

列表项字段：`userId`、`userNo`、`status`、`displayName`、`userType`、`phone`、`email`、`orgName`、`orgTitle`、`roles`（数组，如 `["admin"]`）、`organizationMemberships`（2026-09-07 新增，见 §5.1）、`createdAt`。

详情额外 `statistics`：`achievementCount`、`demandCount`、`cooperationCount`、`favoriteCount`（均 int）。
禁用/启用账号为 P1（当前 READ ONLY）。

### 5.1 机构认证信息（2026-09-07 起）

列表与详情均返回 `organizationMemberships[]`（仅 active）：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | int | membership 主键（grant/revoke-admin 用） |
| orgId | int | 机构 ID |
| orgName | string | 机构名称 |
| role | string | member / admin |
| status | string | active |
| version | int | 乐观锁（写操作必带） |

用户详情模态框提供两个系统管理员操作（均带 version 乐观锁，409 时重新拉详情）：

| 按钮 | API | 请求体 |
|------|-----|--------|
| 设为机构管理员 | `POST /admin/organization-memberships/{id}/grant-admin` | `{version}` |
| 撤销机构管理员 | `POST /admin/organization-memberships/{id}/revoke-admin` | `{version, reason}`（reason 必填） |

## 5A. 机构认证审核（MembershipReviewView，2026-09-07 新增）

UI 路由 `/admin/membership-review`（侧边栏「机构认证审核」），双 Tab 结构，默认过滤 `status=pending`。

### 5A.1 机构入驻申请 Tab

| UI 操作 | API | 说明 |
|---------|-----|------|
| 列表 | `GET /admin/organization-applications?status=&page=&pageSize=` | 全量字段 camelCase 透出 |
| 详情/通过 | `POST /admin/organization-applications/{id}/approve` | `{version}`；事务内创建 institution（active）+ 申请人成为该机构 admin |
| 驳回 | `POST /admin/organization-applications/{id}/reject` | `{version, reason}`（reason 必填） |

列表/详情字段：`id`、`applicantUserId`、`userNo`（申请人）、`requestedName`、`requestedType`（university/institute/enterprise/service/invest）、`creditCode`、`website`、`region`、`address`、`contactName`、`contactPhone`、`contactEmail`、`proofMaterial`、`status`（pending/approved/rejected/cancelled）、`reviewReason`、`reviewedAt`、`version`、`createdAt`。

### 5A.2 机构管理员申请 Tab

| UI 操作 | API | 说明 |
|---------|-----|------|
| 列表 | `GET /admin/organization-admin-applications?status=&page=&pageSize=` | |
| 通过 | `POST /admin/organization-admin-applications/{id}/approve` | `{version}`；通过后该用户 membership role → admin |
| 驳回 | `POST /admin/organization-admin-applications/{id}/reject` | `{version, reason}` |

列表/详情字段：`id`、`userId`、`userNo`、`orgId`、`orgName`、`realName`、`department`、`title`、`workEmail`、`reason`、`proofMaterial`、`status`、`reviewReason`、`reviewedAt`、`version`、`createdAt`。

完整业务规则（三态模型、机构管理员权限边界、成员申请 fallback 审核链）见 `tech-transfer-service/docs/organization-membership.md`。

## 6. 审计日志

`GET /admin/audit-logs?actorUserId=&targetType=&requestId=&page=&pageSize=`

列表项字段：`id`、`actorUserId`、`actorUserNo`、`action`、`resourceType`、`resourceId`、`details`、`requestId`、`createdAt`。

action 全集（当前落库动作）：`achievement.create/update/submit/offline/approve/reject`、`demand.create/update/submit/cancel/close/approve/reject`、`cooperation.*`、`ai.task.create`、`institution.create/update/online/offline`。

## 7. 前端接入建议

1. **登录态**：复用 `/auth/bootstrap`（生产换正式宿主凭证）；token 过期 401 时静默重登。
2. **403 处理**：收到 `TT_ADMIN_40301` 一律视为"非管理员"，退回登录页，不要重试。
3. **乐观锁**：所有审核/编辑请求带列表返回的 `version`；409 时重新拉队列。
4. **轮询**：Dashboard pendingTotal 建议轮询间隔 ≥30s（单 COUNT 查询，压力可控）。
5. **机构 logo**：直接用 `logoUrl` 相对路径（同源 `/api/file/{id}`），失败时展示占位图（502=源站拉取失败属合法降级）。
