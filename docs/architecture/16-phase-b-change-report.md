# 16 · Phase B 变更报告 (Change Report) — 需求域 + 交互域

> 生成时间：2026-09-03（第一批：需求域；第二批：交互域）  
> Phase: B (Core Domain Migration — Demand + Interaction)
> 范围：需求 CRUD + 状态机 + 前端 6 页接入 + 需求 Mock 清除；收藏 + 对接意向 + 前端 4 页接入 + 本地意向/收藏存储清除

---

## Added

### Backend — 数据库

| 文件 | 说明 |
|------|------|
| `migrations/004_demand_domain.sql` | 需求域 4 张表：`demand`（含乐观锁 version、状态机 status、owner 外键）、`demand_category`、`demand_tag`、`demand_tag_relation`。additive，可回滚 |
| `migrations/005_interaction_domain.sql` | 交互域 3 张表：`favorite`（user+target 唯一键）、`cooperation_intent`（状态机 status、乐观锁 version、生成列 active_flag + 唯一键实现"仅活跃意向唯一"）、`cooperation_event`（状态流转审计）。additive，可回滚 |
| `run_migration.py` | 独立迁移执行脚本（规避应用连接持有元数据锁问题） |

### Backend — 模块与路由

| 文件 | 行数 | 说明 |
|------|------|------|
| `modules/demand/service.py` | 464 | 完整需求域逻辑：列表（关键词/分类/分页）、详情（非 owner 联系方式脱敏）、创建/编辑（乐观锁 + version 递增）、状态机 submit/cancel/close、标签同步、审计日志、过渡期 orgName/orgIntro/categoryName get-or-create |
| `routes/demand.py` | 85 | 7 个端点：GET/POST `/demands`、GET/PATCH `/demands/{id}`、POST `/demands/{id}/submit|cancel|close` |
| `modules/favorite/service.py` | 180 | 收藏逻辑：幂等 PUT/DELETE（已收藏返回已有记录）、列表内嵌目标摘要（demand/achievement 双类型）、失效目标自动跳过 |
| `routes/favorite.py` | 40 | 4 个端点：PUT/DELETE `/favorites/{targetType}/{targetId}`、GET `/me/favorites` |
| `modules/cooperation/service.py` | 420 | 对接意向状态机：pending→accepted→confirmed→completed + rejected/cancelled 五操作；乐观锁 version；accept 事务内自动拒绝同目标其他 pending；confirm 将 demand 置 matched（副作用）；权限隔离（仅 initiator/target_owner 可见，非相关方 404 防探测） |
| `routes/cooperation.py` | 95 | 8 个端点：POST `/cooperations`、GET `/cooperations/{id}`、POST `/cooperations/{id}/accept|reject|confirm|complete|cancel`、GET `/cooperations/{id}/events` |
| `etl_demands.py` | 155 | 演示需求数据导入（3 条，owner 为 dev-user-002） |
| `etl_achievements.py` | 230 | 成果归属修正：223 条演示成果改归 dev-user-002（原 ETL 全归 user 1，导致默认用户无法对接他人成果） |
| `test_demand_api.py` | 303 | 88 项断言：CRUD、权限隔离、乐观锁、状态机、脱敏、便捷字段 |
| `test_interaction_api.py` | 310 | 78 项断言：收藏幂等/列表/可见性、对接五操作全状态机、乐观锁冲突、自动拒绝副作用、需求转 matched、权限隔离与 404 防探测、成果目标冒烟 13 项 |

### Backend — 路由扩展

| 文件 | 说明 |
|------|------|
| `routes/me.py` | 新增 GET `/me/demands`（当前用户需求列表，支持 status 过滤）、GET `/me/favorites`（收藏列表，支持 targetType 过滤，内嵌目标摘要）、GET `/me/cooperations`（意向列表，支持 role=initiator/target/both 与 status 过滤） |

### Frontend

| 文件 | 行数 | 说明 |
|------|------|------|
| `common/demand-api.js` | 158 | 需求 API 封装（与 achievement-api 同模式：uni.request + token 自动 bootstrap）；`DEMAND_STATUS_META` 状态标签；`toDemandCard()` 统一卡片模型转换 |
| `common/api-core.js` | 95 | 共享请求基础设施：token 自动 bootstrap、buildURL 手工拼 query（小程序无 URLSearchParams）、X-Idempotency-Key 自动生成、统一 code!==0 抛错。为后续 HostBridge 切换收敛唯一入口 |
| `common/interaction-api.js` | 165 | 收藏/意向 API 封装：addFavorite/removeFavorite/getFavoriteIdSet/getMyFavorites、createCooperation/getCooperationDetail/五操作/getMyCooperations/getCooperationEvents；`COOP_STATUS_META` 状态标签 |

---

## Changed

### Backend

| 文件 | 变更 |
|------|------|
| `app.py` | 注册 `demand_bp`、`favorite_bp`、`cooperation_bp` |
| `core/errors.py` | 新增 `TT_DMD_40301/40401/40901`（非 owner / 不存在 / 状态不允许）及 `TT_CP_40901`（重复意向）、`TT_CP_40902`（乐观锁冲突）等交互域错误码与构造器 |
| `modules/audit/service.py` | 实现审计日志落库（此前 NOT IMPLEMENTED stub） |
| `docs/architecture/openapi.yaml` | `DemandUpsertRequest` 增加过渡期便捷字段 `orgName`/`orgIntro`/`categoryName` |

### Frontend — 6 页接入真实 API（需求链路）

| 页面 | 变更 |
|------|------|
| `pages/index/index.vue` | 首页需求 Tab：`getDemands()` + `toDemandCard()`，移除 Mock |
| `packageA/search/search.vue` | 需求搜索：`getDemands({keyword})`，服务端关键词检索 |
| `packageA/dock-detail/dock-detail.vue` | 需求详情：`getDemandDetail(id)`；预取我的需求改走 API |
| `packageA/my-list/my-list.vue` | 我的需求：`getMyDemands()`（含状态标签）；收藏中需求改走 `getDemandDetail()`（失效收藏自动跳过） |
| `packageA/post-demand/post-demand.vue` | 发布需求：`createDemand()` → `submitDemand()`（draft → pending_review） |
| `pages/mine/mine.vue` | 我的需求计数：`getMyDemands({pageSize:1}).total`（异步，未登录为 0） |

### Frontend — 交互域 4 页接入真实 API

| 页面 | 变更 |
|------|------|
| `pages/index/index.vue` | 收藏按钮：`addFavorite()/removeFavorite()` + `getFavoriteIdSet()` 回显状态（乐观 UI，失败回滚），移除本地收藏读写 |
| `packageA/dock-detail/dock-detail.vue` | 收藏开关 + 发起对接：`createCooperation()`（成功后本地回填 intention）；重新发起走 `/cooperations`（终态后可再发）；意向详情/操作按钮按 API 状态渲染 |
| `packageA/my-list/my-list.vue` | 我的收藏（demand/result 双类型并拉取，失效项自动跳过）+ 我的意向（`getMyCooperations`，initiator/target 双角色，状态标签 + 确认/取消操作按钮），移除本地存储读写 |
| `pages/mine/mine.vue` | 收藏/意向计数：`getMyFavorites({pageSize:1}).total`、`getMyCooperations({role:'both',pageSize:1}).total`（异步，未登录为 0） |

### Frontend — 本地存储清除

| 文件 | 变更 |
|------|------|
| `common/mock-data.js` | 删除全部需求相关导出：`demandList`、`getUserDemands`、`getMyDemands`、`getAllDemands`、`addDemand`、`getDemandById`；仅保留成果部分（Phase C 迁移） |
| `common/user.js` | 删除本地收藏/意向函数（`addFavorite`/`removeFavorite`/`toggleFavorite`/收藏读写、意向保存/查询、对接记录本地存储）；保留登录、身份、资料等纯逻辑与 `canDockContentType`/`canProposeDock`/`getDockBlockMessage` 对接规则函数 |
| `common/demand-api.js`、`common/achievement-api.js` | 重构为复用 `api-core.js` 共享基础设施（消除三份重复的 token/bootstrap/请求样板） |

---

## Preserved

| 行为 | 保留方式 | 原因 |
|------|---------|------|
| 成果链路 Mock（发布/详情） | mock-data.js 保留成果函数 | Phase C 迁移成果域（成果收藏已切换真实 API，仅剩发布/详情 Mock） |
| 对接规则函数 `canDockContentType`/`canProposeDock`/`getDockBlockMessage` | 保留在 user.js | 纯前端展示规则（按内容类型/状态判断可否发起），与数据存储无关 |
| `addDemandSearchHistory` 等搜索历史函数 | common/search.js 不动 | 与需求数据无关，属本地搜索历史 |
| 演示数据 owner = dev-user-002 | etl_demands.py / etl_achievements.py 固定 | 本地演示同时覆盖"浏览他人需求/成果并发起对接"（user 1 视角）与"我发布的需求/成果"（user 2 视角）两条链路 |
| 需求/意向创建幂等键 | api-core.js apiRequest 自动生成 X-Idempotency-Key | 沿用统一基础设施 |

---

## Deferred

| 问题 | 延迟到 | 说明 |
|------|--------|------|
| 成果发布页 post-result 接入 API | Phase C | 成果域 owner 体系待定 |
| mock-data.js / user.js 全量删除 | Phase C | 待成果发布/详情迁移后（收藏、意向、需求部分已清除） |
| 需求软删除 | Phase C | 当前仅状态机，无 deleted_at |
| 管理端需求审核接口 | Phase C | published 前置审核流（当前 pending_review 无人审核，演示环境直接演示） |
| cooperation_event 推送通知 | Phase C | 状态流转事件已落库，notification 模块尚未接入 |
| 意向消息协商（多轮沟通） | Phase C | 当前仅创建时单条 message + 事件流，无站内信/评论 |

---

## Risks

| 风险 | 严重性 | 说明 |
|------|--------|------|
| 过渡期便捷字段 orgName get-or-create 可能产生重复组织 | 低 | 按名称精确匹配；组织主数据治理在 Phase C organization 模块完善 |
| 联系方式脱敏仅处理 phone | 低 | email/wechat 对非 owner 暂未脱敏，Phase C 统一脱敏策略 |
| 演示需求 pending_review 无审核入口 | 低 | 演示环境通过 ETL 直接导入 published 状态数据 |
| 意向唯一约束依赖生成列 active_flag | 低 | MySQL 5.7+ 生成列 + 唯一键实现"仅活跃意向唯一"；ORM 侧不感知该列，由 SQL 层保证 |
| accept 自动拒绝为事务内批量 UPDATE | 中 | 当前无逐条事件记录（仅汇总事件）；意向量大时改为逐条生成 rejected 事件 |
| confirm 副作用仅覆盖 demand 目标 | 低 | achievement 目标 confirm 无状态副作用（成果无 matched 状态），Phase C 成果域定稿后复核 |
| 并发冲突依赖前端正确回传 version | 中 | 前端意向卡片已携带 version；复杂并发场景（双端同时操作）需用户刷新重试 |

---

## 验证

### 后端测试

- `test_demand_api.py` 88/88 断言通过（CRUD / 权限 / 乐观锁 / 状态机 / 脱敏 / 便捷字段）
- `test_interaction_api.py` 78/78 断言通过（收藏幂等与可见性 / 对接五操作状态机 / 乐观锁冲突 / accept 自动拒绝 / confirm 需求转 matched / 权限隔离与 404 防探测 / 成果目标冒烟 13 项）
- 回归：需求域 88 项在交互域合入后重跑通过；成果、资本、身份既有接口未改动

### 前端验证

- HBuilderX 差量编译通过（最后一次编译涵盖全部前端改动）；微信开发者工具正常拉起
- 编译产物无需求 Mock 残留（`getAllDemands`/`getDemandById`/`addDemand`/`getUserDemands` 零引用）
- user.js 无本地收藏/意向残留导出

### 冒烟（Mock 票据身份）

- `/demands` 3 条演示数据（user 1 视角 isMine=false）；`/me/demands` dev-user-002 返回 3 条
- user 1 对 dev-user-002 的成果发起对接成功（223 条成果归属已修正为 dev-user-002）
- 收藏 PUT 幂等：重复收藏返回同一 id；DELETE 后再 PUT 生成新记录
