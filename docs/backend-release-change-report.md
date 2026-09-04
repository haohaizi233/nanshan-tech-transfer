# 后端发布变更报告（backend-release-change-report）

> 交付时间：2026-09-04（Release Closure 增补：Admin 运营域 11 方法）
> 基线：FastAPI 版 34 接口（Flask→FastAPI 迁移完成，203 API 测试通过，commit be47d0c）
> 本轮目标：增量补齐上线必需接口（MySQL→PostgreSQL 切换 + 机构/AI/Admin/成果写域），**禁止重构已验证主链路**
> 范围裁决：所有改动 add-only；存量 34 接口零契约变更（11/11 场景 diff 零差异验证）

## 1. 变更总览

| 阶段 | 内容 | 规模 | 验证 |
|------|------|------|------|
| P0-0 | 数据库 MySQL→PostgreSQL 17 切换 | 18 表 / 1503 行迁移 + 序列重置 + 方言适配 | 存量 219 检查点全绿 |
| P0-1 | 统一机构域（institution） | 表 + ETL 137 行 + service + 2 新接口 + legacy 适配层 | 43 检查点 + diff 11/11 零差异 |
| P0-2 | AI 任务边界 | ai_task/ai_match_result 表 + 2 接口（去重/限流/快照/审计） | 30 检查点 |
| P0-3/4 | Admin 审核域 | admin_identity（user_role 实时查库）+ 7 接口 + 角色种子 | （并入 Admin 套件 118 检查点） |
| P0-5 | 成果用户写域 | 5 接口（POST/PATCH/submit/offline/me）+ 状态机 | 51 检查点 |
| Release Closure | Admin 运营域（P0-1~P0-4 递补） | Dashboard + Institution 写 + Cooperation/Users 只读 = 11 方法 | Admin 套件扩至 118 检查点 |
| — | OpenAPI 启用 | /docs /redoc /openapi.json（仅 local）+ 16 tags | 54 路径校验 |

**最终状态：61 接口方法（54 路径），9 个测试套件 500+ 检查点全绿，legacy diff 11/11 零差异，发布冒烟 68 检查点全绿。**

## 2. 数据库变更（P0-0）

### 2.1 迁移内容

- `migrations/pg/001_tech_transfer_schema.sql`：21 表完整 DDL（幂等可重跑）+ 10 个 `set_updated_at()` 触发器 + GIN 全文索引
- MySQL→PG 数据迁移：18 业务表 1503 行（app_user/external_identity/user_profile/user_role/achievement/achievement_category/inventor/achievement_inventor/organization/demand/demand_category/demand_tag/demand_tag_relation/favorite/cooperation_intent/cooperation_event/audit_log 等含数据表），`information_schema` 自动检测 boolean/generated 列并适配
- 序列重置：含 `id` 列的表执行 `setval(pg_get_serial_sequence(...))`，避免主键冲突
- **MySQL 侧 `nanshan_capital` 库数据（资本三表 137 行）已 ETL 进 PG `institution` 表**；PG 侧单库 `tech_transfer`，MySQL 库 `nanshan_capital` 已 DROP

### 2.2 连接层切换

- `db.py`：pymysql → psycopg2（RealDictCursor），保持 `get_conn`/`get_cursor` 公共 API 不变，线程本地连接
- 方言修复：`INSERT IGNORE`→`ON CONFLICT DO NOTHING`、`lastrowid`→`RETURNING id`、`DATE_ADD`→`NOW() + INTERVAL`、`%%` 转义

## 3. 接口变更明细

### 3.1 统一机构域（P0-1）

- 新表 `institution`（`migrations/pg/002_institution.sql`）：`kind`（platform/invest/service）+ `platform_type_key`（poc/pilot/other）+ 溯源字段（source_pk/site/page/api/fetched_at），`UNIQUE (kind, source_pk)` 支持幂等 ETL
- `tools/etl_institutions.py`：MySQL 资本三表（platform_base 100 / featured_invest_org 21 / ip_service_org 16 = 137 行）→ PG institution，`ON CONFLICT DO UPDATE` 幂等重跑
- `modules/institution/service.py`：统一查询（kind/type/keyword 过滤 + keyword 字段按 kind 定制）
- 新接口：`GET /institutions`、`GET /institutions/{id}`
- **legacy 适配层**：`modules/capital/service.py` 数据源从 MySQL 直查改为 PG institution 表，三接口响应经 `tools/verify_capital_diff.py` 与 MySQL 基线（`legacy_capital_baseline.json`）逐字段比对 **11/11 场景零差异**（含分页、类型过滤、关键词搜索）

### 3.2 AI 任务边界（P0-2）

- 新表（`migrations/pg/004_ai_domain.sql`）：`ai_task`（状态机 queued→running→succeeded/failed + input_snapshot JSONB + input_data_version 哈希）、`ai_match_result`（仅 worker 写入）
- `modules/ai/service.py` 边界原则：**只交付任务边界，不实现 AI 执行**——POST 做校验/去重/限流/快照固化/落库 queued/审计；GET 对 queued/running 返回 results=null，禁止假 AI 结果回填
- 去重：同需求活跃任务（queued/running）10 分钟窗口直接返回既有任务（200 而非 202）
- 限流：用户级 5 次/小时，进程内计数（仅真正新建消耗额度，去重命中/参数错误不计）
- 快照：创建时刻固化需求数据版本（SHA-256 前 16 位），防任务执行时数据漂移
- 新接口：`POST /ai/match-tasks`（202 新建/200 复用）、`GET /ai/match-tasks/{taskId}`（owner only）

### 3.3 Admin 审核域（P0-3/P0-4）

- `core/middleware.py` 新增 `admin_identity`：**登录 + `user_role` 表实时查库校验**，不信任 JWT 内 roles 快照（角色变更旧 token 立即失效），非管理员 `TT_ADMIN_40301`
- `migrations/pg/005_admin_seed.sql`：dev-user-001 种子 admin 角色
- `modules/admin/service.py`：成果/需求审核队列（含提交人）、approve（published_at 落库）、reject（reason 必填 `TT_ADMIN_40001` + reject_reason 落库）、审计日志查询（action/资源/时间过滤 + 分页）
- 7 个接口全部走 `admin_identity`；状态机前置校验（要求 pending_review，非该状态 `TT_ACH_40901`/`TT_DMD_40901`）+ version 乐观锁
- 审计动作：`achievement.approve/reject`、`demand.approve/reject`

### 3.4 成果用户写域（P0-5）

- 错误码 add-only 新增：`TT_ACH_40301`（非成果所有者）、`TT_ACH_40401`（成果不存在）；**未修改任何既有错误码**
- `modules/achievement/service.py` 新增写操作：
  - `create_achievement`：AchievementUpsertRequest 校验（title/maturityLevel/pricingMode 必填 + 枚举白名单 + 长度限制 + priceMin≤priceMax）、owner 服务端注入（body 传 ownerUserId 打印告警并忽略）、JSONB 数组字段、inventorRefs 结构化完成人（name 必填 + personType 枚举 + 同名同机构去重防唯一约束冲突）、创建即 draft、审计 `achievement.create`
  - `update_achievement`：owner only + version 乐观锁 + 仅 draft/rejected 可编辑（pending_review/published 编辑 → `TT_ACH_40901`）、inventorRefs 整体替换（get-or-create）、审计 `achievement.update`
  - `submit_achievement`：draft/rejected → pending_review，审计 `achievement.submit`
  - `offline_achievement`：published → offline（可带 reason），审计 `achievement.offline`
  - `list_my_achievements`：本人全状态 + status 过滤 + isMine/version
- tags/mediaFileIds：一期冻结 schema 无对应表，接受但打印告警忽略（同 openapi 处理方式，不静默落库）
- 路由：`routes/achievement.py` +4、`routes/me.py` +1

### 3.5 OpenAPI 启用

- `app.py`：`/docs`、`/redoc`、`/openapi.json` **仅 APP_ENV=local 启用**（staging/production 自动 None，避免暴露接口面）
- 11 个 router 全部打 tags（achievement/admin/ai/auth/capital/cooperation/demand/favorite/file/institution/me/health），成果组补中文 summary
- 校验：45 路径、12 分组、health tag 无 default 分组残留

### 3.6 Admin 运营域（Release Closure）

- 新增 `routes/admin_ops.py`（与已冻结的审核组 `routes/admin.py` 分文件注册，互不影响），全部挂同一 `admin_identity`
- **Dashboard**（P0-1）：`GET /admin/dashboard/summary` —— 单条 SQL 7 个 COUNT 子查询 + 派生 pendingTotal，无趋势图假数据
- **Institution 管理**（P0-2）：list（含 disabled + kind/status/keyword 过滤）/ detail（含溯源字段）/ create（201，`modules/admin/schemas.py` Pydantic v2 校验）/ update（PATCH 部分更新，kind/source/id 不可改）/ online/offline（状态机 + 重复操作 409 `TT_INST_40901`）
  - 可见性闭环：offline 后公开侧 `/institutions` 列表与详情不可见（data=null），管理端仍可见可检索；online 恢复
  - 写操作同事务审计：`institution.create/update/online/offline`
- **Cooperation 管理**（P0-3，READ ONLY）：list（status/keyword，keyword 命中双方姓名/目标标题/留言）+ detail（含 events 事件流）；管理端视角无参与方权限过滤，GET 不改变状态，**不提供任何写接口**（状态机归参与方）
- **Users 管理**（P0-4，READ ONLY）：list（keyword 命中 userNo/displayName/orgName + status 过滤，roles 数组实时聚合）+ detail（4 个 COUNT 低成本统计）；禁用/启用为 P1
- 修复（本轮验证发现，均只影响新增接口，未触碰存量）：
  - `list_users_admin` COUNT SQL 用 `index(" FROM ")` 切片误取子查询的 FROM，拼出非法 SQL → 改为直接拼 `_USER_FROM`
  - roles 关联子查询别名笔误 `u.user_id` → `ur.user_id`
  - test_admin_api.py「用户列表含admin自身」断言改为末页断言（列表按 id DESC，admin 恒在末页，不受测试新增用户影响）

## 4. 关键设计决策

| 决策 | 理由 |
|------|------|
| legacy 资本三接口走 institution 适配层而非改路径 | 存量小程序直接调用原路径；改路径会破坏已上线前端；diff 零差异证明数据等价 |
| admin 权限每请求查库（非 JWT roles） | 角色变更（撤销管理员）需立即生效，不能等 token 过期 |
| AI 任务保持 queued 不回填结果 | 无假数据原则；worker 接入后由 worker 写 ai_match_result |
| 成果编辑仅 draft/rejected | 冻结 06 文档 §5.1：published 编辑需先 offline（一期不允许） |
| inventorRefs 去重 | uk_ach_inv 唯一约束在重复提交时产生 500，解析期去重转为正常 201 |

## 5. 文件变更清单

| 文件 | 变更 |
|------|------|
| `db.py`、`config.py` | pymysql→psycopg2，PG 连接参数 |
| `core/errors.py` | +TT_ACH_40301/40401（add-only）+ 3 个便捷构造器 |
| `core/middleware.py` | +admin_identity |
| `modules/achievement/service.py` | +写操作 6 函数（约 480 行） |
| `modules/capital/service.py` | 数据源改 institution 适配层 |
| `modules/institution/*`、`modules/ai/service.py`、`modules/admin/service.py`、`modules/admin/schemas.py` | 新建 |
| `routes/achievement.py`、`routes/me.py` | +5 端点 |
| `routes/admin_ops.py` | 新建（Admin 运营域 11 方法，独立于审核组 admin.py） |
| `routes/*.py`（12 个） | +tags（新增 4 组：admin-dashboard/institutions/cooperations/users） |
| `app.py` | OpenAPI local 启用 + health tag + admin_ops_router 挂载 |
| `migrations/pg/002,004,005` | institution/AI/admin 种子 DDL |
| `tools/` | etl_institutions.py、verify_capital_diff.py、smoke_release.py、export_api_inventory.py |
| 测试 | test_institution_api.py（43）、test_ai_api.py（30）、test_admin_api.py（118，含运营域）、test_achievement_write_api.py（51） |

## 6. 遗留事项（不阻断发布，需排期）

1. `X-Idempotency-Key` 真实回放保护（当前 24h 缓存未实现，双击防重由去重窗口/唯一约束/乐观锁兜底）
2. AI worker 未接入（任务长期 queued；前端需按 results=null 处理）
3. 前端主包 capital 页仍调 legacy 路径（可继续用，统一切 /institutions 后下线）
4. 限流计数在进程内（多实例部署需迁 Redis）
5. patent / uploads / ai-evaluation 域（Phase C+）
