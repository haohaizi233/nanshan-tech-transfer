# 16 · Phase B 变更报告 (Change Report) — 需求域

> 生成时间：2026-09-03  
> Phase: B (Core Domain Migration — Demand)
> 范围：需求 CRUD + 状态机 + 前端 6 页接入 + 需求 Mock 清除

---

## Added

### Backend — 数据库

| 文件 | 说明 |
|------|------|
| `migrations/004_demand_domain.sql` | 需求域 4 张表：`demand`（含乐观锁 version、状态机 status、owner 外键）、`demand_category`、`demand_tag`、`demand_tag_relation`。additive，可回滚 |
| `run_migration.py` | 独立迁移执行脚本（规避应用连接持有元数据锁问题） |

### Backend — 模块与路由

| 文件 | 行数 | 说明 |
|------|------|------|
| `modules/demand/service.py` | 464 | 完整需求域逻辑：列表（关键词/分类/分页）、详情（非 owner 联系方式脱敏）、创建/编辑（乐观锁 + version 递增）、状态机 submit/cancel/close、标签同步、审计日志、过渡期 orgName/orgIntro/categoryName get-or-create |
| `routes/demand.py` | 85 | 7 个端点：GET/POST `/demands`、GET/PATCH `/demands/{id}`、POST `/demands/{id}/submit|cancel|close` |
| `etl_demands.py` | 155 | 演示需求数据导入（3 条，owner 为 dev-user-002） |
| `test_demand_api.py` | 303 | 88 项断言：CRUD、权限隔离、乐观锁、状态机、脱敏、便捷字段 |

### Backend — 路由扩展

| 文件 | 说明 |
|------|------|
| `routes/me.py` | 新增 GET `/me/demands`（当前用户需求列表，支持 status 过滤） |

### Frontend

| 文件 | 行数 | 说明 |
|------|------|------|
| `common/demand-api.js` | 158 | 需求 API 封装（与 achievement-api 同模式：uni.request + token 自动 bootstrap）；`DEMAND_STATUS_META` 状态标签；`toDemandCard()` 统一卡片模型转换 |

---

## Changed

### Backend

| 文件 | 变更 |
|------|------|
| `app.py` | 注册 `demand_bp` |
| `core/errors.py` | 新增 `TT_DMD_40301/40401/40901` 及构造器（非 owner / 不存在 / 状态不允许） |
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

### Frontend — Mock 清除

| 文件 | 变更 |
|------|------|
| `common/mock-data.js` | 删除全部需求相关导出：`demandList`、`getUserDemands`、`getMyDemands`、`getAllDemands`、`addDemand`、`getDemandById`；仅保留成果部分（Phase C 迁移） |

---

## Preserved

| 行为 | 保留方式 | 原因 |
|------|---------|------|
| 成果链路 Mock（发布/详情/收藏） | mock-data.js 保留成果函数 | Phase C 迁移成果域 |
| 意向/收藏本地存储（user.js） | 不改动 | Phase B 仅迁移需求；cooperation/favorite 模块后续 Phase |
| `addDemandSearchHistory` 等搜索历史函数 | common/search.js 不动 | 与需求数据无关，属本地搜索历史 |
| 演示数据 owner = dev-user-002 | etl_demands.py 固定 | 本地演示同时覆盖"浏览他人需求并发起对接"（user 1 视角）与"我发布的需求"（user 2 视角）两条链路 |
| 需求创建幂等键 | apiRequest 自动生成 X-Idempotency-Key | 沿用统一基础设施 |

---

## Deferred

| 问题 | 延迟到 | 说明 |
|------|--------|------|
| 收藏 favorite 模块 | Phase B 后续 | 建表 + service + 路由，替换 user.js 本地收藏 |
| 对接 cooperation 模块 | Phase B 后续 | 状态机 + 四角色权限，替换本地意向存储 |
| 成果发布页 post-result 接入 API | Phase C | 成果域 owner 体系待定 |
| mock-data.js / user.js 全量删除 | Phase C | 待成果、意向、收藏全部迁移后 |
| 需求软删除 | Phase C | 当前仅状态机，无 deleted_at |
| 管理端需求审核接口 | Phase C | published 前置审核流（当前 pending_review 无人审核，演示环境直接演示） |

---

## Risks

| 风险 | 严重性 | 说明 |
|------|--------|------|
| 过渡期便捷字段 orgName get-or-create 可能产生重复组织 | 低 | 按名称精确匹配；组织主数据治理在 Phase C organization 模块完善 |
| 联系方式脱敏仅处理 phone | 低 | email/wechat 对非 owner 暂未脱敏，Phase C 统一脱敏策略 |
| 演示需求 pending_review 无审核入口 | 低 | 演示环境通过 ETL 直接导入 published 状态数据 |
| my-list 收藏需求逐条拉详情 | 中 | 数据量小可接受；favorite 模块上线后改为列表接口 |

---

## 验证

- 后端：`test_demand_api.py` 88/88 断言通过（CRUD / 权限 / 乐观锁 / 状态机 / 脱敏 / 便捷字段）
- 前端：HBuilderX 差量编译通过；编译产物无需求 Mock 残留（`getAllDemands`/`getDemandById`/`addDemand`/`getUserDemands` 零引用）
- 冒烟：`/demands` 3 条演示数据（user 1 视角 isMine=false）；`/me/demands` dev-user-002 返回 3 条
- 回归：成果、资本、身份既有接口未改动
