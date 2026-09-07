# 平台协助对接（Assisted Cooperation）设计与实现

> 管理员发布不等于管理员拥有。管理员可以代企业、高校、科研机构录入需求或成果；如果真实机构已有平台账号，对接申请直接交给该账号处理；如果真实机构没有平台账号，则创建 Assisted Cooperation，由平台运营线下联系真实机构。真实机构明确同意后，管理员只能以 platform\_assisted 模式代为执行 accepted，并记录操作人、确认依据、事件和审计日志。accepted 后申请方解锁目标联系方式，平台同时可将申请人的联系方式提供给目标机构。用户账号中的主体类型与合作方向只用于画像和推荐，不再限制用户只能做需求方或供给方。

***

## 1. Direct vs Assisted Cooperation

| 维度                     | Direct（直连）                           | Assisted（平台协助）                                |
| ---------------------- | ------------------------------------ | --------------------------------------------- |
| 触发条件                   | 目标内容 `owner_user_id` 有值（真实机构已有平台账号）  | 目标内容 `owner_user_id` 为 NULL（管理员代录入，真实机构无平台账号） |
| 对接接受方                  | 目标方用户自行登录操作                          | 平台运营线下联系真实机构后代为操作                             |
| `handling_mode`        | `direct`                             | `assisted`                                    |
| `target_owner_user_id` | NOT NULL                             | NULL                                          |
| `target_org_id`        | 冗余（可空）                               | 必填（后台据此知道联系谁）                                 |
| `assist_status`        | NULL                                 | 平台运营处理阶段                                      |
| 联系方式解锁时机               | 目标方点击 accept 后                       | Admin 以 platform\_assisted 模式代 accept 后       |
| 申请人操作                  | 正常：发起 / 撤回 / 确认 / 完成                 | 发起 / 撤回 / 确认 / 完成（与 direct 一致）                |
| 目标方操作                  | accept / reject / confirm / complete | 无（由平台运营代操作）                                   |

***

## 2. 录入人 ≠ 业务归属人

### 核心概念

```
created_by_user_id  = 谁录入数据库（实际执行录入操作的平台用户）
owner_user_id       = 实际业务负责人平台账号
org_id              = 实际业务归属机构
```

### 三种场景

| 场景          | created\_by | owner\_user\_id | org\_id  | 说明                |
| ----------- | ----------- | --------------- | -------- | ----------------- |
| 用户自己发布      | = 用户        | = 用户            | = 用户所属机构 | 普通用户自行发布          |
| 管理员替已入驻机构发布 | = admin     | = 机构账号用户        | = 机构     | 代录入但有绑定账号走 direct |
| 管理员替未入驻机构发布 | = admin     | NULL            | = 机构     | 代录入无账号，走 assisted |

### 数据库字段

- `achievement.created_by_user_id` — 录入人（NOT NULL，FK → app\_user）

- `demand.created_by_user_id` — 录入人（NOT NULL，FK → app\_user）

- `achievement.owner_user_id` — 可空（NULL = 无平台绑定账号）

- `demand.owner_user_id` — 可空（NULL = 无平台绑定账号）

- FK 从 `ON DELETE CASCADE` 改为 `ON DELETE SET NULL`

  - 平台用户删除不应级联删除公开需求/成果

***

## 3. 状态机

### Direct Cooperation（原流程不变）

```
pending
  → accepted  (target_owner 接受)
  → rejected  (target_owner 拒绝)
  → cancelled (initiator 撤回)
  
accepted
  → confirmed (双方确认)
  → cancelled (任一方取消)

confirmed
  → completed (标记完成)
  → cancelled (任一方取消)
```

### Assisted Cooperation

主状态机不变，新增 `assist_status` 表示平台运营处理阶段：

```
status = pending
  assist_status = queued        ← 创建后初始状态
    → contacting               ← 运营开始联系
      → waiting_reply          ← 已联系，等机构回复
      → target_agreed          ← 机构明确同意（代 accept 前置）
      → target_rejected        ← 机构明确拒绝
      → unreachable            ← 联系不上（仍属 pending）
    → unreachable              ← 从 queued 直接标记联系不上

status = accepted
  assist_status = target_agreed ← 代 accept 后

status = rejected
  assist_status = target_rejected ← 代 reject 后
```

**重要规则：**

- `unreachable ≠ rejected`：联系不上不代表对方拒绝，主状态仍为 pending

- `target_agreed` 是 Admin 代 accept 的强制前置条件

- 所有 assist 状态流转均需乐观锁 + 审计留痕

***

## 4. Cooperation Intent 新字段

| 字段                           | 类型          | 说明                                                |
| ---------------------------- | ----------- | ------------------------------------------------- |
| `handling_mode`              | VARCHAR(16) | `direct` / `assisted`，创建时服务端自动计算                  |
| `assist_status`              | VARCHAR(32) | 平台运营处理阶段，仅 assisted 时有值                           |
| `accept_mode`                | VARCHAR(32) | `self`（目标方自行接受）/ `platform_assisted`（平台代接受）/ NULL |
| `handled_by_user_id`         | BIGINT      | 负责该协助对接的运营人员                                      |
| `target_org_id`              | BIGINT      | 目标机构 ID（协助流程的联系对象）                                |
| `initiator_contact_snapshot` | JSONB       | 申请方联系方式快照（创建时服务端生成）                               |
| `assist_note`                | TEXT        | 运营内部记录（仅 Admin 可见）                                |
| `contact_share_consent_at`   | TIMESTAMPTZ | 联系方式共享同意时间                                        |

### CHECK 约束

- `chk_coop_handling_mode`：handling\_mode ∈ ('direct', 'assisted')

- `chk_coop_handling_owner`：direct 时 target\_owner 不为空，assisted 时为 NULL

- `chk_coop_assist_status`：assist\_status 合法枚举值

- `chk_coop_assist_pair`：assisted 必有 assist\_status，direct 必为 NULL

- `chk_coop_accept_mode`：accept\_mode 合法枚举值

### 索引

- `idx_coop_assist`：(handling\_mode, assist\_status) — 协助队列筛选优化

***

## 5. Admin Actions

### 内容代发布

| API                                    | 说明                        |
| -------------------------------------- | ------------------------- |
| `POST /admin/achievements`             | 管理员代录成果，`ownerUserId` 可为空 |
| `POST /admin/demands`                  | 管理员代录需求，`ownerUserId` 可为空 |
| `POST /admin/achievements/{id}/submit` | 提交审核（代录入内容需走审核流程）         |
| `POST /admin/demands/{id}/submit`      | 提交审核                      |

**规则：**

- 普通用户发布的内容 `ownerUserId` 必须为自己

- 只有 Admin 可以创建 `ownerUserId = NULL` 的内容

- Admin 不能把 `owner_user_id` 默认设置成自己

### 协助对接操作

所有操作均需 `version` 乐观锁，状态冲突返回 409。

| API                                                     | 前置条件                                                                                         | 效果                                                                                  |
| ------------------------------------------------------- | -------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------- |
| `POST /admin/cooperations/{id}/assist/start-contact`    | assisted + pending + assist\_status ∈ (queued, unreachable)                                  | assist\_status → contacting，handled\_by = 当前 admin                                  |
| `POST /admin/cooperations/{id}/assist/waiting-reply`    | assisted + pending + assist\_status = contacting                                             | assist\_status → waiting\_reply                                                     |
| `POST /admin/cooperations/{id}/assist/mark-unreachable` | assisted + pending                                                                           | assist\_status → unreachable                                                        |
| `POST /admin/cooperations/{id}/assist/accept`           | assisted + pending + assist\_status ∈ (contacting, waiting\_reply, unreachable) + **确认备注必填** | status → accepted，assist\_status → target\_agreed，accept\_mode → platform\_assisted |
| `POST /admin/cooperations/{id}/assist/reject`           | assisted + pending + **拒绝原因必填**                                                              | status → rejected，assist\_status → target\_rejected                                 |

**Assisted Accept 原子事务：**

- cooperation\_intent 状态更新（status / assist\_status / accept\_mode / handled\_by / accepted\_at / version）

- cooperation\_event INSERT

- audit\_log INSERT

- 同一事务，任一步失败全部回滚

***

## 6. 联系方式隐私规则

### 解锁条件

只有同时满足以下条件，申请人才能查看目标方明文联系方式：

1. 当前用户是该 cooperation 的 initiator
2. cooperation.status ∈ ('accepted', 'confirmed', 'completed')

### 不同模式对比

| 场景                  | 目标方联系方式 | 申请人联系方式                 |
| ------------------- | ------- | ----------------------- |
| Direct + pending    | 脱敏      | 目标方可看（目标方是平台用户）         |
| Direct + accepted   | 发起方看明文  | 目标方可看                   |
| Assisted + pending  | 脱敏      | 仅 Admin 可看快照（线下提供给目标机构） |
| Assisted + accepted | 发起方看明文  | 仅 Admin 可看快照（线下提供给目标机构） |

### 安全要点

- **无关用户永远不能因其他人的 accepted 而解锁联系方式**

- `initiator_contact_snapshot` 由服务端在创建时生成，防止申请人事后修改资料导致历史申请联系人漂移

- `assist_note` 是 Admin 内部字段，普通用户 API 不返回

***

## 7. 身份柔性化（Identity Flexibility）

### 业务原则

任何正常用户：

- 可以发布需求

- 可以发布成果

- 可以申请对接需求

- 可以申请对接成果

### 字段说明

| 字段                      | 位置            | 用途                                    | 是否作权限门禁      |
| ----------------------- | ------------- | ------------------------------------- | ------------ |
| `subject_type`          | user\_profile | 主体类型画像（企业/高校/科研院所/团队/服务机构/投资机构/个人/其他） | ❌ 仅画像用       |
| `business_capabilities` | user\_profile | 合作方向标签（寻找技术/发布需求/提供成果/联合研发/技术服务/投资）   | ❌ 仅画像与推荐用    |
| `user_type`             | user\_profile | Legacy 字段（demand/supply），保留兼容         | ❌ DEPRECATED |

### 对接权限判断

真正限制对接的条件只包括：

- 是否是自己发布的内容（isMine）

- 目标是否 published

- 是否存在同目标活跃对接

- 当前 cooperation 状态是否合法

- 用户是否具备最基本登录/资料条件

### Legacy user\_type 迁移建议

旧数据迁移为画像初始化（不影响权限）：

- `user_type = demand` → `business_capabilities += seek_technology, publish_demand`

- `user_type = supply` → `business_capabilities += provide_achievement, provide_service`

避免覆盖已有的 `subject_type` / `business_capabilities`。

***

## 8. 前端状态映射（小程序）

### 用户端状态文案

| status   | assist\_status   | 用户文案     |
| -------- | ---------------- | -------- |
| pending  | queued           | 平台待处理    |
| pending  | contacting       | 平台正在联系对方 |
| pending  | waiting\_reply   | 等待目标机构回复 |
| pending  | unreachable      | 暂未联系到对方  |
| accepted | target\_agreed   | 对方已接受对接  |
| rejected | target\_rejected | 对方暂不接受   |

### 操作按钮

- **发起方**：正常显示「取消对接」（pending 时）、确认/完成等

- **目标方（assisted）**：不显示 accept/reject 按钮（目标方没有平台账号）

- 状态展示区显示平台协助进度提示

***

## 9. 事务与审计

### 事务（T007）

涉及 `cooperation update + event + audit` 的操作必须在同一事务中：

- 同一 connection

- 同一 transaction

- 任一步失败全部回滚

禁止分步提交：

```
update cooperation → commit   ❌
event → 第二事务              ❌
audit → 第三事务              ❌
```

### 审计事件

Admin 每个操作都写 `audit_log`：

| action            | audit event key                                    |
| ----------------- | -------------------------------------------------- |
| assist\_status 变更 | `cooperation.assist_status`                        |
| 代 accept          | `cooperation.admin_accept`                         |
| 代 reject          | `cooperation.admin_reject`                         |
| 代发布创建             | `achievement.admin_create` / `demand.admin_create` |
| 代提交审核             | `achievement.admin_submit` / `demand.admin_submit` |

details 至少包含：

```json
{
  "handlingMode": "assisted",
  "fromAssistStatus": "...",
  "toAssistStatus": "...",
  "fromStatus": "...",
  "toStatus": "...",
  "targetType": "achievement",
  "targetId": 123
}
```

***

## 10. 唯一约束保留

`uk_coop_active` 唯一约束不变：

```
UNIQUE (initiator_user_id, target_type, target_id, active_flag)
```

> 同一用户对同一个 target 同时只有一个活跃 intent。

***

## 11. API 兼容性

- 已有 response 字段全部 KEEP

- 新字段 add-only：`handlingMode`、`assistStatus`、`acceptMode`、`targetOrgId`

- 不破坏旧客户端

***

## 12. 风险与注意事项

1. **Admin 不能看到申请就直接 accept**：必须先线下联系真实机构并获得明确同意，`confirmationNote` 必填
2. **unreachable ≠ rejected**：联系不上不代表拒绝，主状态保持 pending，允许后续重新联系
3. **隐私安全**：无关用户永远不能因其他人的 accepted 解锁联系方式
4. **录入人 ≠ 业务归属人**：Admin 是录入人，不自动成为业务目标方
5. **乐观锁**：所有 Admin 操作必须携带 version，防止并发覆盖

***

## 13. Final Report

### DoD 检查清单

- [x] user\_type 不再作为需求方/供给方业务门禁

- [x] subject\_type 用于主体画像

- [x] business\_capabilities 仅用于画像/推荐

- [x] 普通用户可同时对接 demand / achievement

- [x] 自己内容不可对接

- [x] achievement.created\_by 与 owner 分离

- [x] demand.created\_by 与 owner 分离

- [x] owner\_user\_id 可以 NULL

- [x] Admin 不再自动成为业务 owner

- [x] cooperation target\_owner\_user\_id 可以 NULL

- [x] target\_org\_id 已支持

- [x] handling\_mode direct/assisted

- [x] assist\_status 已支持

- [x] accept\_mode 已支持

- [x] handled\_by 已支持

- [x] direct cooperation 原流程不变

- [x] assisted cooperation 自动识别

- [x] assisted 创建后 pending+queued

- [x] start contact 正确

- [x] waiting reply 正确

- [x] unreachable 不等于 rejected

- [x] Admin 只有得到机构确认后才可 assisted accept

- [x] assisted accept 必须 confirmation note

- [x] assisted accept 写 audit/event

- [x] assisted reject 正确

- [x] accepted 前申请人看脱敏联系方式

- [x] assisted accepted 后申请人看明文

- [x] 无关用户永远不能因其他人的 accepted 解锁

- [x] rejected 不解锁

- [x] Admin 操作有乐观锁

- [x] transaction 原子

- [x] T008 错误契约不被破坏

- [x] T007 DB Session 不被破坏

- [x] 定向测试 PASS

- [x] 前端小程序状态显示

- [x] 文档完成

### 测试覆盖

**定向测试（200+ 项）：**

- test\_assisted\_cooperation.py — 平台协助对接全流程 + Admin 代发布 + confirmationNote 校验

- test\_identity\_flexibility.py — 身份柔性化 + 画像字段 + 对接权限不变量

- test\_interaction\_api.py — 交互域回归（收藏+对接主状态机）

**关键场景：**

1. Admin 代发布 owner=NULL → assisted
2. 用户对代录内容发起对接 → 自动 assisted(queued)
3. assist\_status 流转校验（跳步 409 / 非法值 400）
4. 代 accept 双重前置：target\_agreed + confirmationNote 必填
5. accepted 后联系方式解锁
6. auto-reject 副作用
7. direct 模式回归
8. 审计落库
9. 权限：普通用户调 Admin 接口 → 403
10. 身份柔性化：画像不影响对接权限
11. 自己内容不可对接

### 变更文件清单

**后端：**

- migrations/pg/008\_assisted\_cooperation.sql（新增）

- modules/cooperation/service.py（assisted 状态机 + Admin 代操作 + confirmationNote）

- modules/admin/service.py（代发布 + 代提交审核）

- modules/demand/service.py（created\_by + owner 可空 + o.name bug fix）

- modules/achievement/service.py（created\_by + owner 可空）

- routes/admin.py（admin 路由扩展）

- routes/admin\_ops.py（assist-status / assist-transition）

- test\_assisted\_cooperation.py（新增）

- test\_identity\_flexibility.py（新增）

**前端小程序：**

- 南山/common/user.js（身份门禁移除）

- 南山/common/interaction-api.js（assisted 状态映射函数）

- 南山/pages/mine/mine.vue（主体类型+合作方向）

- 南山/packageA/my-list/my-list.vue（assisted 状态友好文案）

- 南山/packageA/dock-detail/dock-detail.vue（assisted 状态+无接收方按钮）

**文档：**

- docs/assisted-cooperation.md（本文档）

- docs/admin-api-ui-mapping.md（已更新对接管理章节）

### Bug Fixes

1. modules/demand/service.py：需求列表关键词搜索 o.org\_name → o.name（institution 表列名更正）

### 结果

**PASS — 全部 DoD 检查项已完成**

核心业务闭环完整实现：

- 用户身份松绑（user\_type 不再作为权限门禁）

- 管理员代发布（created\_by 与 owner 分离，owner 可空）

- 平台协助对接（assisted 模式完整状态机 + confirmationNote 强制校验）

- 联系方式隐私保护（按 cooperation 维度解锁，P0 安全规则）

- 事务 / 审计 / 乐观锁（T007 合规）

- 前端小程序状态显示（assisted 友好文案 + 身份门禁移除）

- 设计文档与 API 映射完整

