# 机构认证与组织成员体系（organization-membership）

> 落地时间：2026-09-07
> 迁移：`migrations/pg/011_organization_membership.sql`（幂等，可重跑）
> 代码：`modules/membership/`（service + schemas）+ `routes/membership.py`
> 测试：`test_organization_membership.py`（218 项，全过）

## 1. 解决的问题

| 旧问题                                  | 新方案                                                            |
| ------------------------------------ | -------------------------------------------------------------- |
| 用户自由填写公司/高校名称，无法可靠匹配 canonical 机构主数据 | 成员归属改为 `organization_membership` 表关联 `institution.id`，名称只做展示快照 |
| 机构归属不明确（profile 自填字段即可伪装）            | 认证成员身份只能由机构管理员/系统管理员审核产生，带 `verified_by/verified_at` 留痕        |
| 身份刚性（旧 user\_type 卡权限）               | 三态身份仅作画像与展示，发布/对接权限不受影响（身份柔性化规则冻结）                             |

## 2. 三态用户模型

| 状态             | 判定                                                                | 能力                              |
| -------------- | ----------------------------------------------------------------- | ------------------------------- |
| 普通未认证用户        | 无 active membership                                               | 全部基础业务（发布需求/成果、对接），仅不能以机构名义关联内容 |
| 机构认证成员（member） | `organization_membership` 中存在 `status='active' AND role='member'` | 上述全部 + 发布内容时可关联所属认证机构（orgId）    |
| 机构管理员（admin）   | 同上但 `role='admin'`                                                | 上述全部 + 管理本机构：审核成员申请、撤销普通成员      |

关键规则：

- `user_role.role_code='admin'` 是**系统管理员**（后台全局权限），与机构管理员完全独立，二者互不授予。

- 机构管理员权限只能由系统管理员授予/撤销（grant-admin / revoke-admin），或经机构管理员申请审批产生。

- 机构管理员仅能管理本机构（`org_admin_identity` 每请求实时查库校验 org 范围），不获得任何系统级后台权限。

## 3. 数据模型（迁移 011）

canonical 机构表复用 `institution`（合并自原 organization，见迁移 009）。

```
organization_membership                 成员身份（当前态）
├─ org_id        → institution.id      FK
├─ user_id       → app_user.id         FK
├─ role          member | admin
├─ status        active | revoked
├─ department / title                  展示用
├─ verified_by_user_id / verified_at   审核留痕
├─ revoked_by_user_id / revoked_at / revoke_reason
└─ version                             乐观锁
UNIQUE (org_id, user_id)  —— 一人一机构一行，重入走 UPDATE

organization_membership_application     加入已有机构申请
├─ user_id / org_id / real_name / department / title
├─ work_email / proof_material / apply_note
├─ status  pending | approved | rejected | cancelled
├─ reviewed_by_user_id / reviewed_at / review_reason
└─ version 乐观锁
UNIQUE partial: (user_id, org_id) WHERE status='pending'  防重复提交

organization_admin_application          机构管理员申请（系统管理员审核）
├─ user_id / org_id / real_name / department / title
├─ work_email / proof_material / reason
└─ 同上状态机

organization_application               机构入驻申请（新机构，系统管理员审核）
├─ applicant_user_id / requested_name / requested_type
├─ credit_code / website / region / address
├─ contact_name / contact_phone / contact_email / proof_material
└─ 同上状态机
```

审计：全部写操作落 `audit_log`（action 形如 `organization_membership_application.approve`、`organization_admin.grant` 等），并携带 HTTP requestId。

## 3A. 权限矩阵

| Ability             | 未认证 | 认证成员 | 机构管理员 | 系统管理员 |
| ------------------- | --: | ---: | ----: | ----: |
| 发布需求                |   ✅ |    ✅ |     ✅ |     ✅ |
| 发布成果                |   ✅ |    ✅ |     ✅ |     ✅ |
| 发起/申请对接             |   ✅ |    ✅ |     ✅ |     ✅ |
| 收藏/维护资料             |   ✅ |    ✅ |     ✅ |     ✅ |
| 发布内容关联认证机构（orgId）   |   ❌ |    ✅ |     ✅ |     ✅ |
| 申请加入已有机构            |   ✅ |  ✅\* |   ✅\* |     ✅ |
| 申请新机构入驻             |   ✅ |    ✅ |     ✅ |     ✅ |
| 申请成为机构管理员           |   ✅ |    ✅ |     ✅ |     ✅ |
| 审核本机构成员申请           |   ❌ |    ❌ |     ✅ |     ✅ |
| 撤销本机构普通 member      |   ❌ |    ❌ |     ✅ |     ✅ |
| 撤销机构管理员（role=admin） |   ❌ |    ❌ |     ❌ |     ✅ |
| 授予机构管理员             |   ❌ |    ❌ |     ❌ |     ✅ |
| 审核新机构入驻 / 机构管理员申请   |   ❌ |    ❌ |     ❌ |     ✅ |
| 新增 canonical 机构     |   ❌ |    ❌ |     ❌ |     ✅ |
| 查看全局用户 / 系统后台       |   ❌ |    ❌ |     ❌ |     ✅ |

`*` 多机构模型：用户可同时持有多机构 membership；对同一机构存在 active membership 或 pending 申请时再次申请返回 409，对其他机构申请不受影响。

机构管理员的"本机构成果/需求/合作对接"查看能力：当前 MVP 通过 org\_id 关联实现（机构管理页 org-manage 以 orgId 过滤成员与申请）；机构维度的成果/需求/对接列表页为后续增强，不在本轮范围。

## 3B. 与 Assisted Cooperation（平台协助对接）的衔接

沿用现有「管理员代发布 / 平台协助对接」模型（1ded23c），本轮保持兼容：

- Admin 代机构发布时 `org_id = canonical institution.id`，`org_name_snapshot` 为展示快照。

- 若真实机构已有平台负责人（该机构存在 membership 关联用户）：`owner_user_id = user_id` → direct cooperation。

- 若机构无平台负责人：`owner_user_id = NULL` → assisted cooperation，Admin 不自动作为 owner。

- membership 体系不改变 assisted cooperation 状态机；机构管理员撤销/成员变更不影响已存在的 cooperation\_intent 记录。

## 3C. Reapply 规则（重复申请与复活）

| 当前状态                 | 同一 (user\_id, org\_id) 再次申请  | 行为                                                                                      |
| -------------------- | ---------------------------- | --------------------------------------------------------------------------------------- |
| pending 申请存在         | 409（partial unique index 拦截） | —                                                                                       |
| active membership 存在 | 409                          | —                                                                                       |
| 申请 rejected          | 允许重新提交新申请                    | 新 pending 记录，旧记录保留审计                                                                    |
| membership revoked   | 允许重新提交新申请                    | approve 时复活原 membership 行（UPDATE status→active, version+1，重写 verified\_by/verified\_at） |
| 申请 cancelled         | 允许重新提交                       | 同 rejected                                                                              |

revoked → 复活：`organization_membership` 一人一机构一行（UNIQUE(org\_id,user\_id)），重入不 INSERT 新行，改为 UPDATE，保留首次创建时间与历史撤销记录的审计痕迹。

## 4. 业务流程

### 4.1 加入已有机构（搜索式，禁止名称绑定）

```
小程序 org-join：keyword 搜索 GET /institutions?keyword= （active 机构）
  → 用户从候选列表选择（拿到 orgId）
  → POST /me/organization-membership-applications {orgId, realName, ...}
  → 机构有 active admin → 该 org_admin 在小程序 org-manage 审核
    机构无 admin        → fallback 系统管理员经后台/接口审核
  → approve：_activate_membership(user, org, role='member')
     已有 active 同机构身份 → 409（不改写既有身份）
     revoked 同机构身份    → 复活该行（UPDATE，版本+1）
     无记录                → INSERT
```

### 4.2 机构入驻（新机构）

```
小程序 org-apply：POST /me/organization-applications {requestedName, requestedType, ...}
  → 系统管理员审核 POST /admin/organization-applications/{id}/approve
  → 事务内：INSERT institution（status=active, source_site='self_registration'）
            + 申请人直接成为该机构 admin（_activate_membership role='admin'）
  → 同名机构已存在 → 409
```

### 4.3 机构管理员申请

```
POST /me/organization-admin-applications {orgId, ...}
  → 仅系统管理员审核（/admin/organization-admin-applications/{id}/approve）
  → 通过后该用户 membership role → admin
```

### 4.4 系统管理员直改

```
POST /admin/organization-memberships/{membershipId}/grant-admin   member → admin
POST /admin/organization-memberships/{membershipId}/revoke-admin  admin → revoked（reason 必填）
```

### 4.5 撤销成员

```
POST /org-admin/members/{membershipId}/revoke {version, reason}
  仅可撤销本机构、active、role='member'（admin 身份只能系统管理员撤）
```

## 5. API 清单

### 用户端（identity）

| Method | Path                                                   | 说明                          |
| ------ | ------------------------------------------------------ | --------------------------- |
| GET    | `/me/organization-memberships`                         | 我的认证机构列表（含 orgName/orgType） |
| GET    | `/me/organization-membership-applications`             | 我提交的加入机构申请列表（可按 status 过滤） |
| POST   | `/me/organization-membership-applications`             | 申请加入已有机构（必须带后端返回的 orgId）    |
| POST   | `/me/organization-membership-applications/{id}/cancel` | 撤回待审申请                      |
| POST   | `/me/organization-admin-applications`                  | 申请成为机构管理员                   |
| POST   | `/me/organization-applications`                        | 申请新机构入驻                     |

机构搜索复用公开接口 `GET /institutions?keyword=`，无独立搜索端点。`GET /me` 返回体也含 `organizationMemberships`（供前端 mine 页直接渲染）。

### 机构管理员端（org\_admin\_identity）

| Method | Path                                                | 说明                      |
| ------ | --------------------------------------------------- | ----------------------- |
| GET    | `/org-admin/members?orgId=&status=`                 | 本机构成员列表                 |
| GET    | `/org-admin/membership-applications?orgId=&status=` | 本机构待审申请                 |
| POST   | `/org-admin/membership-applications/{id}/approve`   | 通过（带 version）           |
| POST   | `/org-admin/membership-applications/{id}/reject`    | 驳回（version + reason 必填） |
| POST   | `/org-admin/members/{membershipId}/revoke`          | 撤销普通成员                  |

### 系统管理员端（admin\_identity）

| Method | Path                                                             | 说明                 |
| ------ | ---------------------------------------------------------------- | ------------------ |
| GET    | `/admin/organization-applications?status=`                       | 机构入驻申请队列           |
| POST   | `/admin/organization-applications/{id}/approve` / `reject`       | 审核                 |
| GET    | `/admin/organization-admin-applications?status=`                 | 机构管理员申请队列          |
| POST   | `/admin/organization-admin-applications/{id}/approve` / `reject` | 审核                 |
| POST   | `/admin/organization-memberships/{id}/grant-admin`               | 授予机构管理员            |
| POST   | `/admin/organization-memberships/{id}/revoke-admin`              | 撤销机构管理员（reason 必填） |

### 错误码

| code | 场景                                                     |
| ---- | ------------------------------------------------------ |
| 409  | 重复申请 / 已是成员 / 同名机构 / version 乐观锁不匹配（TT\_COMMON\_40902） |
| 403  | 非本机构管理员操作 / 非系统管理员                                     |
| 400  | reject/revoke 未填 reason                                |

## 6. 内容发布的机构关联

成果/需求发布（`achievement` / `demand` service）：

- 传 `orgId` 时后端调 `membership.assert_active_membership(cur, user_id, org_id)` 实时校验，非该机构 active 成员 → 403「无权关联该认证机构」。

- `org_name_snapshot` 仅作展示快照，不参与匹配。

- 用户端 pick 机构时从 `/me/organization-memberships` 取，天然只能选到自己认证的机构。

## 7. 前端接入

### 小程序（uni-app）

| 文件                                   | 作用                           |
| ------------------------------------ | ---------------------------- |
| `common/membership-api.js`           | 机构认证 API 封装（走主包 api-core.js） |
| `pages/mine/mine.vue`                | 机构认证卡片：未认证入口 / 认证状态 / 机构管理入口 |
| `packageA/org-join/org-join.vue`     | 搜索选择机构 + 提交加入申请              |
| `packageA/org-apply/org-apply.vue`   | 新机构入驻申请表单                    |
| `packageA/org-manage/org-manage.vue` | 机构管理员：成员列表 + 申请审核 + 撤销成员     |

pages.json 已注册三个 packageA 页面。

### 管理后台（nanshan-frontend）

| 页面                         | 改动                                                                                              |
| -------------------------- | ----------------------------------------------------------------------------------------------- |
| `UserView.vue`             | 列表新增「认证机构」列（tag 展示，admin 橙色）；详情模态框新增机构认证区（设为/撤销机构管理员，走 grant-admin / revoke-admin）；CSV 导出含认证机构列 |
| `MembershipReviewView.vue` | 新页面：机构入驻申请 + 机构管理员申请双 Tab 审核（默认过滤 pending），路由 `/admin/membership-review`，侧边栏「机构认证审核」            |
| `InstitutionView.vue`      | 不变（canonical 机构 CRUD 仍走原 /admin/institutions）                                                   |

后台字段：用户列表/详情 `organizationMemberships[] = {id, orgId, orgName, role, status, version}`（version 供 grant/revoke 乐观锁；已 e2e 实测：grant 后 role=member→admin、version+1，revoke 后 status=revoked）。

## 8. 测试与运维

- 主套件：`python test_organization_membership.py`（218 项：状态机、权限边界、乐观锁、审计、fallback 审核链）。

- 全量回归（2026-09-07）：17 个测试套件 + `tools/smoke_release.py` 103 项 + compileall 全部通过。

- 申请列表接口（`/admin/organization-applications` 等）返回 camelCase 字段（`_map_read_row` 做下划线→camelCase 转换，`a.*` 全量透出，含 `requestedName/realName/reviewReason` 等供后台详情页渲染）。

- `test_auth_register.py` 用固定手机号 13911111111/13922222222，重跑前先跑 `cleanup_auth_register_fixture.py` 清残留（favorite/user\_credential/user\_role/user\_profile/app\_user + membership 相关四表）。

- 用户编号生成：`_generate_user_no` 取存量编号数值最大值+1（MAX+1），不再用 COUNT+1（COUNT 在清理测试用户后会回落，与存量编号撞唯一约束报 40903）。
