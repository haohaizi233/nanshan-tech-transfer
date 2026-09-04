# API 发布清单（api-release-inventory）

> 生成时间：2026-09-04（Release Closure 增补：Admin 运营域 11 方法）
> 服务：tech-transfer-service（FastAPI，模块化单体）
> 运行时：http://127.0.0.1:8787（local），APP_ENV=local
> 来源：运行中服务的 `/openapi.json` 实时导出（`tools/export_api_inventory.py`）

## 1. 总览

| 维度 | 值 |
|------|-----|
| 接口方法总数 | **61**（54 路径） |
| 分组（tags） | 16 组 |
| 统一前缀 | `/api/tech-transfer/v1`（存量资本三接口与文件代理除外，见 §4） |
| 认证 | JWT Bearer（`Authorization: Bearer <token>`）；写操作全部强制 `Depends(identity)`，管理端为 `Depends(admin_identity)` |
| 响应契约 | `{code:0(int), message, data, requestId}`；错误 `{code:"TT_*", message, requestId, details?}` |
| 文档端点 | `/docs`、`/redoc`、`/openapi.json`（**仅 local 环境启用**，staging/production 自动关闭） |

## 2. 本轮发布范围（相对 34 接口基线的增量）

| # | 接口 | 组 | 类型 | 说明 |
|---|------|----|------|------|
| 1 | POST `/achievements` | achievement | 新增 | 创建成果（draft，owner 服务端注入） |
| 2 | PATCH `/achievements/{id}` | achievement | 新增 | 编辑（owner + 乐观锁 + 仅 draft/rejected） |
| 3 | POST `/achievements/{id}/submit` | achievement | 新增 | 提交审核 → pending_review |
| 4 | POST `/achievements/{id}/offline` | achievement | 新增 | 下线（published → offline，可带 reason） |
| 5 | GET `/me/achievements` | me | 新增 | 本人成果全状态列表（status 过滤） |
| 6 | GET `/institutions` | institution | 新增 | 统一机构库列表（kind/type/keyword/分页） |
| 7 | GET `/institutions/{id}` | institution | 新增 | 统一机构详情 |
| 8 | POST `/ai/match-tasks` | ai | 新增 | 创建匹配任务（去重/限流/快照固化） |
| 9 | GET `/ai/match-tasks/{taskId}` | ai | 新增 | 任务详情（queued/running 无结果回填） |
| 10-16 | admin 组 7 个 | admin | 新增 | 审核队列 ×2、approve/reject ×4、audit-logs |
| 17 | GET `/admin/dashboard/summary` | admin-dashboard | 新增 | 运营概览（8 项真实 COUNT，无趋势假数据） |
| 18 | GET `/admin/institutions` | admin-institutions | 新增 | 机构管理列表（含 disabled，kind/status/keyword） |
| 19 | POST `/admin/institutions` | admin-institutions | 新增 | 创建机构（201，Pydantic Schema） |
| 20 | GET `/admin/institutions/{id}` | admin-institutions | 新增 | 管理端机构详情（含溯源字段） |
| 21 | PATCH `/admin/institutions/{id}` | admin-institutions | 新增 | 编辑机构（部分更新） |
| 22 | POST `/admin/institutions/{id}/online` | admin-institutions | 新增 | 上架（disabled→active） |
| 23 | POST `/admin/institutions/{id}/offline` | admin-institutions | 新增 | 下架（active→disabled，公开侧不可见） |
| 24 | GET `/admin/cooperations` | admin-cooperations | 新增 | 对接意向管理端列表（只读，status/keyword） |
| 25 | GET `/admin/cooperations/{id}` | admin-cooperations | 新增 | 管理端意向详情 + events（只读） |
| 26 | GET `/admin/users` | admin-users | 新增 | 用户列表（只读，keyword/status） |
| 27 | GET `/admin/users/{id}` | admin-users | 新增 | 用户详情 + 低成本统计（只读） |

存量 34 接口**零契约变更**（legacy 资本三接口经 11/11 场景逐字段 diff 验证零差异）。
Admin 审核域 + 运营域共 16 路径 / 18 方法，全部挂 `admin_identity`（user_role 实时查库）。

## 3. 完整接口清单（61 方法）

| 方法 | 路径 | 分组 | 认证 | 说明 |
|------|------|------|------|------|
| GET | `/api/health` | health | 无 | 健康检查（DB 连通 + 运行环境） |
| GET | `/api/file/{file_id}` | file | 无 | 源站文件代理（502=源站拉取失败，合法降级） |
| GET | `/api/platform-base` | capital | 无 | 平台库列表（legacy 适配层） |
| GET | `/api/invest-orgs` | capital | 无 | 投资机构列表（legacy 适配层） |
| GET | `/api/service-orgs` | capital | 无 | 服务机构列表（legacy 适配层） |
| GET | `/api/tech-transfer/v1/achievements` | achievement | 需登录 | 成果列表（仅 published） |
| POST | `/api/tech-transfer/v1/achievements` | achievement | 需登录 | 创建成果（201，draft） |
| GET | `/api/tech-transfer/v1/achievements/categories` | achievement | 需登录 | 成果分类字典 |
| GET | `/api/tech-transfer/v1/achievements/{ach_id}` | achievement | 需登录 | 成果详情（防探测：非 owner 访问非 published → data=null） |
| PATCH | `/api/tech-transfer/v1/achievements/{ach_id}` | achievement | owner | 编辑成果（version 必填） |
| POST | `/api/tech-transfer/v1/achievements/{ach_id}/submit` | achievement | owner | 提交审核 |
| POST | `/api/tech-transfer/v1/achievements/{ach_id}/offline` | achievement | owner | 下线成果（可带 reason） |
| GET | `/api/tech-transfer/v1/admin/achievements/review-queue` | admin | **admin** | 待审成果队列 |
| POST | `/api/tech-transfer/v1/admin/achievements/{ach_id}/approve` | admin | **admin** | 成果审核通过（version+乐观锁） |
| POST | `/api/tech-transfer/v1/admin/achievements/{ach_id}/reject` | admin | **admin** | 成果驳回（reason 必填） |
| GET | `/api/tech-transfer/v1/admin/audit-logs` | admin | **admin** | 审计日志查询（过滤/分页） |
| GET | `/api/tech-transfer/v1/admin/demands/review-queue` | admin | **admin** | 待审需求队列 |
| POST | `/api/tech-transfer/v1/admin/demands/{demand_id}/approve` | admin | **admin** | 需求审核通过 |
| POST | `/api/tech-transfer/v1/admin/demands/{demand_id}/reject` | admin | **admin** | 需求驳回（reason 必填） |
| GET | `/api/tech-transfer/v1/admin/cooperations` | admin-cooperations | **admin** | 对接意向管理端列表（只读） |
| GET | `/api/tech-transfer/v1/admin/cooperations/{intent_id}` | admin-cooperations | **admin** | 意向详情 + events（只读，无参与方过滤） |
| GET | `/api/tech-transfer/v1/admin/dashboard/summary` | admin-dashboard | **admin** | 运营概览（8 项真实 COUNT） |
| GET | `/api/tech-transfer/v1/admin/institutions` | admin-institutions | **admin** | 机构管理列表（含 disabled） |
| POST | `/api/tech-transfer/v1/admin/institutions` | admin-institutions | **admin** | 创建机构（201） |
| GET | `/api/tech-transfer/v1/admin/institutions/{institution_id}` | admin-institutions | **admin** | 管理端机构详情 |
| PATCH | `/api/tech-transfer/v1/admin/institutions/{institution_id}` | admin-institutions | **admin** | 编辑机构（部分更新） |
| POST | `/api/tech-transfer/v1/admin/institutions/{institution_id}/offline` | admin-institutions | **admin** | 下架（公开侧不可见） |
| POST | `/api/tech-transfer/v1/admin/institutions/{institution_id}/online` | admin-institutions | **admin** | 上架 |
| GET | `/api/tech-transfer/v1/admin/users` | admin-users | **admin** | 用户列表（只读） |
| GET | `/api/tech-transfer/v1/admin/users/{user_id}` | admin-users | **admin** | 用户详情 + 统计（只读） |
| POST | `/api/tech-transfer/v1/ai/match-tasks` | ai | 需登录 | 创建匹配任务（202 新建 / 200 去重复用） |
| GET | `/api/tech-transfer/v1/ai/match-tasks/{task_id}` | ai | owner | 任务详情（queued/running → results=null） |
| POST | `/api/tech-transfer/v1/auth/bootstrap` | auth | 无 | 宿主凭证换 token（local=mock ticket） |
| POST | `/api/tech-transfer/v1/auth/refresh` | auth | 需登录 | 刷新 token |
| POST | `/api/tech-transfer/v1/auth/logout` | auth | 需登录 | 注销 session |
| POST | `/api/tech-transfer/v1/cooperations` | cooperation | 需登录 | 发起对接意向（403 自我对接/409 重复） |
| GET | `/api/tech-transfer/v1/cooperations/{intent_id}` | cooperation | 参与方 | 意向详情 |
| POST | `/api/tech-transfer/v1/cooperations/{intent_id}/accept` | cooperation | 目标方 | 接受 |
| POST | `/api/tech-transfer/v1/cooperations/{intent_id}/cancel` | cooperation | 参与方 | 取消 |
| POST | `/api/tech-transfer/v1/cooperations/{intent_id}/complete` | cooperation | 参与方 | 完成 |
| POST | `/api/tech-transfer/v1/cooperations/{intent_id}/confirm` | cooperation | 参与方 | 确认（首个 confirm → 需求 matched） |
| GET | `/api/tech-transfer/v1/cooperations/{intent_id}/events` | cooperation | 参与方 | 事件流 |
| POST | `/api/tech-transfer/v1/cooperations/{intent_id}/reject` | cooperation | 目标方 | 拒绝 |
| GET | `/api/tech-transfer/v1/demands` | demand | 需登录 | 需求列表（published） |
| POST | `/api/tech-transfer/v1/demands` | demand | 需登录 | 创建需求（201，draft） |
| GET | `/api/tech-transfer/v1/demands/{demand_id}` | demand | 需登录 | 详情（防探测） |
| PATCH | `/api/tech-transfer/v1/demands/{demand_id}` | demand | owner | 编辑（version 必填） |
| POST | `/api/tech-transfer/v1/demands/{demand_id}/cancel` | demand | owner | 取消（published → cancelled） |
| POST | `/api/tech-transfer/v1/demands/{demand_id}/close` | demand | owner | 关闭 |
| POST | `/api/tech-transfer/v1/demands/{demand_id}/submit` | demand | owner | 提交审核 |
| PUT | `/api/tech-transfer/v1/favorites/{target_type}/{target_id}` | favorite | 需登录 | 收藏（achievement/demand） |
| DELETE | `/api/tech-transfer/v1/favorites/{target_type}/{target_id}` | favorite | 需登录 | 取消收藏 |
| GET | `/api/tech-transfer/v1/institutions` | institution | 需登录 | 统一机构库列表 |
| GET | `/api/tech-transfer/v1/institutions/{inst_id}` | institution | 需登录 | 机构详情 |
| GET | `/api/tech-transfer/v1/me` | me | 需登录 | 我的资料 |
| GET | `/api/tech-transfer/v1/me/achievements` | me | 需登录 | 本人成果（全状态） |
| GET | `/api/tech-transfer/v1/me/cooperations` | me | 需登录 | 本人对接 |
| GET | `/api/tech-transfer/v1/me/demands` | me | 需登录 | 本人需求 |
| GET | `/api/tech-transfer/v1/me/favorites` | me | 需登录 | 本人收藏 |
| PATCH | `/api/tech-transfer/v1/me/profile` | me | 需登录 | 更新资料 |
| GET | `/api/tech-transfer/v1/search` | achievement | 需登录 | 统一搜索（type=achievement） |

## 4. 存量无前缀接口（不迁移原因）

| 接口 | 状态 |
|------|------|
| `/api/platform-base`、`/api/invest-orgs`、`/api/service-orgs` | 小程序已上线的资本页直接调用（H5/小程序存量路径）；数据源已统一切换至 PG `institution` 表，路径保留以兼容存量前端，待前端统一切 `/institutions` 后下线 |
| `/api/file/{file_id}` | 存量文件代理，前端 `<image>` 直链依赖 |
| `/api/health` | 部署探活路径 |

## 5. 明确不在本期范围（冻结 06 文档界定）

- Admin 用户禁用/启用（P1；当前 `/admin/users` 为只读）
- Admin 侧合作意向写操作（状态机归参与方，管理端只读 + 审计）
- `/ai/evaluation-tasks`（AI 评估，Phase C）
- 专利组 `/patents`（外部 Provider 未接入）
- 上传组 `/uploads/presign|complete`（file_object 未建）
- `X-Idempotency-Key` 真实回放保护（当前接收并打印告警，幂等由去重/唯一约束/乐观锁兜底）
- 需求 `GET /demands/{id}/matches`（依赖 AI worker）
