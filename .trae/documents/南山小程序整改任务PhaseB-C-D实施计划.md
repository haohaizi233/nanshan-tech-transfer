# 南山小程序整改任务 Phase B/C/D 实施计划

> 生成时间：2026-09-08
> 依据：docs/architecture/03（双宿主设计）、05（数据模型 §7）、06（API 设计 §AI）、08（上级依赖清单）、12（实施计划 Phase B/C/D 表）、13（阻塞项 B-01/B-02/B-04）、16（Phase B 变更报告）+ 代码现状全量探查
> 用户已确认的三个范围决策：**前端全量一步到位迁移**、**AI 完整链路**、**AiNanshanAdapter 以 example 骨架 + 契约测试交付**

---

## 一、Summary（目标与交付物）

收口 Phase B 遗留架构问题（搜索统一、资本路径、主包 HostBridge、分包依赖边界），完成 Phase C AI 非模型基础设施（evaluation-tasks + ai_evaluation 表，不接真模型，任务保持 queued 禁假数据），清除前端全部 AI/成果发布 Mock，按 doc 03 目标态完成业务分包全量迁移（消灭 `common/` 与 packageA），并以 example 骨架 + 契约测试形式建立 AiNanshanAdapter 边界（Phase D）。全程保证既有业务功能回归通过。

交付物清单：
1. 后端：`GET /search` 统一搜索（双类型聚合）、`POST/GET /ai/evaluation-tasks`、migration 013（ai_evaluation 表）、openapi.yaml 契约同步（/institutions、/search、/ai/evaluation-tasks）
2. 前端：业务分包 `subpackages/tech-transfer` 完全自包含（16 页 + api/ 层全部经 HostBridge）、主包只剩 dev-home + mine-home 壳 + 宿主层（host/、config/、static/）、TabBar 精简为 2 项
3. 前端：AI 链路真实接入（ai-match 任务式、ai-eval-detail 任务轮询、post-result 真实发布+评估触发、my-list 评估入口）；删除 ai-chat.js / ai-eval.js / mock-data.js / capital-demo-data.js / packageA / common/ 全部
4. Phase D：`host/ainanshan-adapter.example.js` 注释级骨架 + `南山/tests/host-bridge.test.mjs` 契约测试
5. 文档：docs/architecture/17-phase-bcd-change-report.md + doc 12 状态表更新

---

## 二、Current State Analysis（现状，全部经代码核实）

### 2.1 后端（tech-transfer-service，FastAPI + PostgreSQL）

| 域 | 现状 | 缺口 |
|----|------|------|
| AI | `routes/ai.py` 仅 match-tasks 两端点；`modules/ai/service.py` 已实现创建（去重 10min 窗口 / 用户限流 5 次每小时（进程内）/ 快照固化 / queued 落库）与查询（succeeded 才组装 results） | 无 evaluation-tasks 端点；`migrations/pg/004_ai_domain.sql` 只有 ai_task + ai_match_result，**缺 ai_evaluation 表**（05 §7.2 已定义四维评分模型）；无 ai_model_version 表（本轮不建，见决策 D4） |
| search | `modules/search/service.py` 是 `# NOT IMPLEMENTED` stub；`GET /search` 挂在 `routes/achievement.py` L92（仅 type=achievement，其余返回空）；需求搜索实际由前端走 `getDemands({keyword})` 单独请求 | 未按 openapi 契约实现双类型聚合 `{achievements, demands}`；search 模块空壳 |
| capital | 数据源已切 PG institution 表（P0-1 完成）；`routes/institution.py` 已有 `/institutions` + `/institutions/{id}`（kind 统一参数）；legacy 路由 `/api/platform-base`、`/api/invest-orgs`、`/api/service-orgs` 保留在 `routes/capital.py` | openapi.yaml 仍是 `/capital/*` 5 端点（与实现脱节）；前端 `common/capital.js` 仍调 legacy 路径且带 `USE_CAPITAL_DEMO` 开关 + 58KB capital-demo-data.js |
| 成果 | `POST /achievements`（draft）+ submit/offline + admin 审核全链路已存在 | 前端 post-result.vue 未接入（仍写本地存储） |

### 2.2 前端（南山/，uni-app，微信小程序 + H5 双编译）

**主包页面**（5）：dev-home（导航壳，已存在且已跳子包 mine）、index（tab，真实 API，19.9KB）、ai-match（tab，**buildDemoReply 假 AI 回复**，5.3KB）、mine（tab，真实认证 + 资料 + 计数 + 机构成员，27.2KB，最完整版本）、capital-list（legacy capital 路径，11.9KB）。

**packageA**（10 页，全部 import 主包 `common/*.js`）：search、dock-detail（28.9KB）、post-demand、post-result（**mock addResult 本地存储**）、fee-detail（patent-fee.js 演示费率）、my-list、ai-eval-detail（**mock 假评分孤页，全工程无任何跳转入口**）、org-join、org-apply、org-manage。

**subpackages/tech-transfer**（3 页）：achievement-list、achievement-detail、mine（10.5KB 旧简版，功能落后于主包 mine.vue）。

**关键架构违规（本轮要消灭的）**：
- 子包页面 import 主包 `../../../../common/*.js`（achievement-list/detail/mine 三页）
- 子包 `api/client.js` 与 `api/me.js` import 主包 `host/local-adapter.js`（saveSession 等实现细节）——违反「业务分包只依赖 HostBridge 接口」硬约束
- `subpackages/tech-transfer/runtime/host-bridge.js` 是无引用死代码（0 引用，与主包副本同大小）
- 子包 `api/client.js` 只有 mock bootstrap 旧逻辑，落后于主包 `common/api-core.js` 的完整认证（account 登录/注册/刷新/mock 兜底）
- 主包 `common/api-core.js` 用 `uni.request` 直连（阻塞项 B-01，绕过 HostBridge）
- TabBar 3 项指向主包业务页（index/ai-match/mine），阻止这些页迁入子包

**App.vue**：onLaunch 注册 LocalAdapter 到主包 `host/host-bridge.js` ✓（环境断言 ✓）。

**前端测试**：`南山/tests/` 下 3 个 node:test 风格 .mjs（api-base/request-retry/review-status，均 import `../common/*`，common 删除后需同步处理）。

### 2.3 上级依赖（Phase D 前置，均「已索取未确认」）

C-01 宿主凭证格式、C-03 网关身份传递、C-07 部署资源、C-08 分包合并方式 → 真实 AiNanshanAdapter 无法落地，只能交付 example 骨架 + 契约测试（doc 08 §0：期间按默认方案推进，确认后仅调整 adapter 与网关配置）。

---

## 三、Assumptions & Decisions（关键决策，已定案）

| # | 决策 | 理由 |
|---|------|------|
| D1 | **HostBridge 单例必须由主包持有**：子包一律 `import HostBridge from '../../../host/host-bridge.js'`（主包路径）；删除 `subpackages/tech-transfer/runtime/host-bridge.js` 死代码 | App.vue（主包）注册与子包页面使用必须是**同一模块实例**，微信以文件路径为模块 key，物理上只能单份主包文件。合并上级时契约文件随注册点拷入上级工程主包同路径（在 example 骨架中注明） |
| D2 | **鉴权注入职责归 Adapter**：子包 `api/client.js` 不注入 Authorization（只管 path/query/body/幂等键/解包/401 刷新重试）；LocalAdapter._request 已实现从 storage 读 token 注入 Bearer，AiNanshanAdapter 将来注入上级 Token | 上级宿主的凭证只能由宿主侧注入（C-01/C-03 语义）；现状 LocalAdapter 已如此，零改动 |
| D3 | **session 读写经 HostBridge.getStorage/_setStorage**：子包 client.js 的 saveSession/clearSession/isTokenValid/getRefreshToken 全部走 HostBridge（不再 import local-adapter.js）；storage key 沿用 `tt_access_token` 等（与现网缓存兼容） | 宿主能力（storage）收敛进契约；本地行为不变（LocalAdapter 落 uni storage） |
| D4 | **不建 ai_model_version 表**；`ai_evaluation.model_version_id` 允许 NULL（偏离 05 §7.2 非空约束，在迁移文件注释中说明） | 模型版本登记机制属于 worker/Provider 接入范畴；无 worker 时永远无写入，先收紧非空会导致将来无值可插。worker 接入时补表并收紧 |
| D5 | **evaluation-tasks 与 match 同为 P0-2 边界模式**：创建成功 202 queued、去重命中 200、**不做 TT_AI_50301**（该码留给 Provider 熔断场景，当前无 Provider 调用点） | 与既有 match 实现一致；openapi 中 503 语义是「AI 能力未配置或熔断」，任务排队制下创建边界不触发 |
| D6 | **统一搜索按 openapi 契约实现**：`GET /search?q=&type=achievement|demand|all&categoryCode=&maturityLevel=&page=&pageSize=`，响应 `{achievements:{total,page,pageSize,totalPages,list}, demands:{...}}`；`routes/achievement.py` 的 `/search` 端点删除；前端 search.vue 同轮切换 | 前后端同轮改，不留兼容层 |
| D7 | **资本前端切 `/institutions`**（kind=platform/invest/service 参数），不切 openapi 里的 `/capital/*` 5 端点；openapi.yaml 同步改为 `/institutions` 契约（对齐实现）；legacy 路由保留（admin/爬虫兼容期），`routes/capital.py` 加 deprecated 注释 | /institutions 已实现且统一；capital.py legacy 层零改动继续服务 |
| D8 | **TabBar 精简为 2 项**：`pages/dev-home/dev-home`（入口工作台）+ `pages/mine-home/mine-home`（新建轻壳：直读 tt_* storage 显示登录态卡片 + 功能入口 grid，经 HostBridge.navigate 跳子包）。微信 tabBar 最少 2 项，tab 页必须在主包 | doc 03 §6 方案；壳页属宿主层，直读 storage 展示（页面禁令只针对 uni.request，storage 无禁令） |
| D9 | **「我的」页以主包 pages/mine/mine.vue（27.2KB 完整版）为准迁入子包**，覆盖子包旧 mine.vue（10.5KB 旧简版）；`common/me-api.js`（旧模块）废弃不迁 | 主包版含真实认证/资料编辑/计数/机构成员，功能最新最全 |
| D10 | **patent/fee-detail 不接后端**（patent 域不在 Phase C 4 端点内）：`patent-fee.js` 原样迁入子包 `api/patent-fee.js`（纯前端费率表 + 演示数据保留，标注 patent 模块接入后替换）；fee-detail 页正常迁移 | 控制范围；patent Provider 属后续阶段 |
| D11 | **external-miniprogram.js 保留并迁入子包**（doc 03 §3.3：C-08 确认前保留，检索 Tab 指向分包内搜索页） | 上级合并方式未确认 |
| D12 | **AI 页面产品形态**：ai-match.vue 由对话式改为**任务式**（选我的需求 → 创建匹配任务 → 轮询状态 → succeeded 展示成果匹配列表；无 worker 时显示「任务已排队·AI 服务接入中」）；ai-eval-detail.vue 参数改为 `taskId`（+achievementId），轮询展示 queued/running/failed/succeeded 四态 | openapi 契约只接受 demandId/achievementId，无自由文本通道 |
| D13 | **评估入口**：post-result.vue 发布成功后提供「发起 AI 评估」按钮；my-list.vue 我发布的成果卡片提供「AI 评估」入口（显示最近任务状态，跳 ai-eval-detail）。评估触发权限 = 成果 owner（不限 published 状态，未删除即可） | 06 §496 页面归属；评估结果公开可见属 worker 接入后范畴（本轮无结果可公开） |
| D14 | **git 分两批提交**（后端一批、前端一批），commit message 用临时文件 `git commit -F`（toolhost 崩溃教训）；全程不改 `config/local.env.js`（启动器会备份恢复的文件不动） | 工程惯例 + memory 教训 |
| D15 | **H5 端同步验证**：子包 import 主包模块在 H5 编译下同样合法（H5 无分包物理隔离），`start_dev.py --h5` 验证 | 双编译目标 |

---

## 四、Proposed Changes（按执行顺序，6 个阶段 12 个任务）

### 阶段一：后端基础设施（前端切换的前提）

#### T1. migration 013：ai_evaluation 表

新建 `tech-transfer-service/migrations/pg/013_ai_evaluation.sql`（幂等，可重跑）：

```sql
CREATE TABLE IF NOT EXISTS public.ai_evaluation (
    id                  BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    task_id             BIGINT       NOT NULL,
    achievement_id      BIGINT       NOT NULL,
    score_tech          NUMERIC(5,1) NOT NULL,
    score_application   NUMERIC(5,1) NOT NULL,
    score_maturity      NUMERIC(5,1) NOT NULL,
    score_feasibility   NUMERIC(5,1) NOT NULL,
    total_score         NUMERIC(5,1) NOT NULL,
    summary             TEXT,
    suggestions         JSONB,
    model_version_id    BIGINT,                       -- 暂可空：ai_model_version 登记未建，worker 接入时补表收紧（决策 D4）
    input_data_version  VARCHAR(32)  NOT NULL,
    created_at          TIMESTAMPTZ  NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uk_ai_eval_task UNIQUE (task_id)       -- 一任务一结果（05 §7.2）
);
CREATE INDEX IF NOT EXISTS idx_ai_eval_ach ON public.ai_evaluation (achievement_id, id);
COMMENT ON COLUMN public.ai_evaluation.model_version_id IS '暂允许 NULL：模型版本登记机制随 worker 接入补齐';
```

风格对齐 004_ai_domain.sql（无 FK、纯列 + 唯一约束）。执行方式：沿用 `run_migration.py` 或 psql 手工执行（与既有迁移一致）。

#### T2. modules/ai/service.py：evaluation 任务

在现有文件追加（复用既有 `_check_user_rate`、审计、`_task_view` 模式）：

- `SNAPSHOT_FIELDS_EVAL`：成果快照字段——**实现时对齐 `modules/achievement/service.py` 详情查询的列**（预计 id/title/tech_intro/maturity/source_org_name/category_name/status/version，按实际列名调整）
- `create_evaluation_task(user_id, user_no, achievement_id, request_id=None) -> tuple[dict, bool]`：
  1. 查 achievement（`deleted_at IS NULL`，按实际软删列），不存在 → `TT_ACH_40401`；非 owner → `TT_ACH_40301`（确认 `core/errors.py` 已有这两个码，缺则补 add-only）
  2. 去重：`task_type='evaluation' AND target_id=%s AND status IN ('queued','running') AND created_at > NOW()-INTERVAL '10 minutes'` → 命中返回 `(task_view, False)`
  3. 限流 `_check_user_rate(user_id)`（与 match 共享每小时额度）
  4. 快照固化（sha256 前 16 位 input_data_version）
  5. `INSERT INTO ai_task (task_type='evaluation', status='queued', target_type='achievement', ...)` + 审计 `ai.task.create`
- `get_evaluation_task(user_id, task_id) -> dict`：仅创建者可查（TT_AI_40401/40301）；视图 camelCase 对齐前端 ai-eval-detail：
  ```json
  {
    "taskId", "status", "evaluation": null,
    "failReason", "createdAt", "finishedAt",
    "modelVersionLabel": null, "inputDataVersion"
  }
  ```
  succeeded 时 `evaluation` 读 ai_evaluation 组装：`{achievementId, achievementTitle, scores: {techFeature, applyScope, maturity, cooperation}, totalScore, conclusion: summary, highlights: suggestions 数组, modelVersionLabel: null}`（四维 key 用前端展示名，映射 score_tech→techFeature、score_application→applyScope、score_maturity→maturity、score_feasibility→cooperation）
- queued/running 时 `evaluation=null`，**禁止任何假评分回填**（正式模式禁假评分，06 §496）

#### T3. routes/ai.py：evaluation 端点

- `POST /ai/evaluation-tasks`（status_code=202）：body `{achievementId}`，正整数校验（与 match 的 demandId 同模式）；新建 `success(task, "任务已受理")`、去重命中 200 `success(task, "任务进行中")`；X-Idempotency-Key 打日志（同 match 现状）
- `GET /ai/evaluation-tasks/{task_id}`：`Depends(identity)`，返回 get_evaluation_task

#### T4. search 域统一

- `modules/search/service.py`（替换 stub）：`def search(q, search_type, category_code, maturity_level, page, page_size) -> dict`——聚合调用 `modules/achievement/service.py` 的成果列表函数与 `modules/demand/service.py` 的需求列表函数（传 keyword=q；分类/成熟度过滤按两域 service 已支持的参数透传，**实现时读两个 service 的函数签名确定透传方式**）。返回 `{"achievements": {...分页+list}, "demands": {...分页+list}}`；`search_type` 为 `achievement` 时 demands 返回空分页结构、反之亦然
- 新建 `routes/search.py`：`GET /search`，prefix `/api/tech-transfer/v1`，参数校验（q 必填 maxLength 64、type 枚举、page/pageSize 经 `core/pagination.parse_page_args`），`Depends(identity)`
- `routes/achievement.py`：删除 L92-98 `/search` 端点（前端同轮切换，不留兼容）
- `app.py`：注册 search_router

#### T5. openapi.yaml 契约同步

- `/capital/platforms`、`/capital/platforms/{id}`、`/capital/investment-organizations`、`/capital/financial-organizations`、`/capital/service-organizations` 5 端点 → 替换为 `/institutions`、`/institutions/{id}`（对齐 `routes/institution.py` 实现：kind=platform/invest/service + type=poc/pilot/other/all + keyword + 分页；响应结构对齐 `modules/institution/service.list_institutions` 实际返回，**实现时以该函数返回为准写 schema**）
- 核对 `/search` 描述（去掉「一期 MySQL FULLTEXT」字样，标注双类型聚合已实现）
- `/ai/evaluation-tasks` 两端点描述补「创建边界不做 503（任务排队制）；Provider 熔断场景保留 TT_AI_50301」
- `routes/capital.py` 文件头注释追加 `DEPRECATED since 2026-09-08: 前端已切 /institutions，保留供兼容期`

#### T6. 后端测试

新建 `tech-transfer-service/test_ai_evaluation_api.py` + `test_search_api.py`（参照 `test_demand_api.py`/`test_interaction_api.py` 的既有模式：固定测试手机号注册/登录、requests 直打 8787、finally 清理）：

- evaluation：非 owner 403、不存在 404、去重（10min 内二次创建 200 同 taskId）、限流（6 次/小时第 6 次 429，注意与 match 共享额度——测试顺序敏感，单独进程或先造 match 额度场景）、GET 仅创建者可见（他人 403）、queued 时 evaluation=null、幂等键日志不炸
- search：q 必填 400、type=achievement/demand/all 三态、分页字段、双类型列表形状（achievements/demands 键）、需登录（无 token 401）
- **测试数据纪律**（memory 教训）：测试造的 achievement 用后经 admin API 驳回/下线清理，避免污染 `test_admin_api.py` 审核队列计数；固定手机号重跑前先清 favorite/user_credential/user_role/user_profile/app_user 五表

---

### 阶段二：前端子包 api/ 层建设（核心重构，先于页面迁移）

#### T7. 重写 `subpackages/tech-transfer/api/client.js`（合并 api-core.js 完整认证 + HostBridge 通道）

以 `common/api-core.js` 的认证逻辑为蓝本、通道换 HostBridge（决策 D2/D3）：

- import：`HostBridge from '../../../host/host-bridge.js'`（**删除对 local-adapter.js 的 import**）
- session helpers（saveSession/clearSession/isTokenValid/getRefreshToken/getCurrentUser/setCurrentUser）：读写 `tt_access_token`/`tt_refresh_token`/`tt_token_expires_at`/`tt_current_user`/`tt_auth_mode`，全部经 `HostBridge.getStorage(key)`/`HostBridge.setStorage(key, value)`（LocalAdapter 落 uni storage，行为不变）
- `ensureToken()`：valid → 放行；有 refreshToken → `HostBridge.request POST /auth/refresh`（body 携带 refreshToken）；DEV 环境（`HostBridge.getEnvironment().appEnv ∈ {local, development, test}`）→ mockBootstrap（`HostBridge.getIdentityCredential()` 作 hostCredential 打 `/auth/bootstrap`，mode='mock'）；否则抛「未登录，请先登录」
- `apiRequest(method, path, query, body)`：POST/PATCH 自动生成 `X-Idempotency-Key`（经 options.headers 传给 HostBridge.request，LocalAdapter._request 已支持 headers 合并）；`res.code===0` 返回 `res.data`；`TT_COMMON_40102/TT_AUTH_40104` → 刷新一次重试；其余抛 `Error(.code/.message/.requestId/.details)`
- 导出：`request`（=apiRequest 别名，保持子包现有页面兼容）、`apiRequest`、`authRegister`、`authLogin`、`authLogout`、`getCurrentUser`、`setCurrentUser`、`ensureSession`
- **不注入 Authorization**（决策 D2，LocalAdapter 负责）；APP_ENV 判断改用 `HostBridge.getEnvironment()`（不再 import common/config.js）

#### T8. common/ 业务模块收编进子包 api/（逐文件映射）

| common/ 源文件 | 子包目标 | 改造要点 |
|---|---|---|
| achievement-api.js | `api/achievement.js` | import client.js；`searchAchievements` 改调统一 `/search`（q=keyword, type=achievement, 取 `res.achievements`）；删除 demo fallback（若有） |
| demand-api.js | `api/demand.js` | import client.js；`DEMAND_STATUS_META`/`toDemandCard` 随迁 |
| interaction-api.js | `api/interaction.js` | import client.js；收藏/意向全套随迁 |
| membership-api.js | `api/membership.js` | import client.js |
| user.js | `api/user.js` | authLogin/authRegister 调 client.js 导出；`SUBJECT_TYPE_OPTIONS`/`CAPABILITY_OPTIONS`/资料读写/`ensureLoginForDock` 随迁；**`ensureLoginForDock` 的 `uni.switchTab('/pages/mine/mine')` 改为 `HostBridge.navigate('pages/mine/mine')`** |
| capital.js | `api/capital.js` + `constants/capital-modules.js` | `fetchPlatformList(type)` → `GET /institutions?kind=platform&type=...&keyword=...&page=...`；`fetchOrgList(kind)` → `GET /institutions?kind=invest|service&...`（bank→service 映射保留在调用侧）；**删除 USE_CAPITAL_DEMO 分支与 capital-demo-data.js import**；CAPITAL_MODULES 纯配置进 constants/ |
| search.js | `api/search.js` | 搜索历史本地存储逻辑随迁（纯 UI 状态）；新增 `searchAll(q, type, page, pageSize)` 调统一 `/search` 返回双类型 |
| patent-fee.js | `api/patent-fee.js` | 原样随迁（决策 D10），文件头标注「patent 模块接入后替换」 |
| external-miniprogram.js | `api/external-miniprogram.js` | 原样随迁（决策 D11） |
| review-status.js | `constants/review-status.js` | 纯常量 |
| request-retry.js | `api/request-retry.js` | 原样随迁（或并入 client.js，实现时看引用面） |
| me-api.js | **删除** | 旧模块（决策 D9，功能在 api/user.js + api/me.js） |
| api-core.js / api-base.js / config.js / mock-data.js / ai-chat.js / ai-eval.js / capital-demo-data.js | **删除** | 逻辑已并入 client.js；mock 全清 |

子包既有 `api/achievement.js`、`api/me.js`：以主包 common 版本为准重写覆盖（me.js 重写为经 client.js 的 `/me` 系列：getCurrentUser/updateMyProfile/logout，删除对 local-adapter 的 import）。

**验收门（阶段二末）**：`rg "common/|local-adapter" subpackages/` 零命中（除注释）；子包内任何文件不 import 主包除 `host/host-bridge.js` 外的任何模块。

---

### 阶段三：页面全量迁移 + 业务改造

#### T9. packageA 10 页迁入 `subpackages/tech-transfer/pages/`

search、dock-detail、post-demand、post-result、fee-detail、my-list、ai-eval-detail、org-join、org-apply、org-manage → 子包 `pages/<name>/<name>.vue`。

每页统一改造模式：
1. import 路径 `../../common/xxx.js` → `../../api/xxx.js`（子包内相对路径）
2. 页面间跳转 `uni.navigateTo({url: '/packageA/dock-detail/dock-detail?type=...'})` → `HostBridge.navigate('pages/dock-detail/dock-detail', {type, id})`（LocalAdapter 自动补 `/subpackages/tech-transfer/` 前缀，已实现）
3. `uni.switchTab` 全部消灭（rg 验证）

#### T10. 主包 4 业务页迁入子包 + TabBar/壳页改造

- `pages/index/index.vue` → `subpackages/tech-transfer/pages/home/home.vue`（doc 03 §3.2 映射；import 改子包 api/；TabBar 依赖移除；检索 Tab 跳子包 search 页）
- `pages/ai-match/ai-match.vue` → 子包 `pages/ai-match/ai-match.vue` + **任务式改造**（决策 D12）：
  - 移除 ai-chat.js import 与 buildDemoReply/setTimeout 假回复
  - 新结构：onShow 拉取我的需求列表（getMyDemands，活跃状态）→ 每项「发起 AI 匹配」→ `api/ai.js::createMatchTask(demandId)` → 任务卡片轮询 `getMatchTask(taskId)`（3s 间隔、上限 120s）→ queued/running 显示状态徽标 + 「AI 服务接入中，任务已排队」文案；succeeded 渲染 results（achievementTitle/orgName/score/matchReasons）；failed 显示 failReason
  - 新建 `api/ai.js`：createMatchTask/getMatchTask/createEvaluationTask/getEvaluationTask（POST/GET 四函数，经 client.js）
  - 无需求空态引导跳 post-demand
- `pages/mine/mine.vue` → 子包 `pages/mine/mine.vue`（**覆盖旧版**，决策 D9）
- `pages/capital-list/capital-list.vue` → 子包 `pages/capital-list/capital-list.vue`（fetch 函数已切 /institutions，页面逻辑基本不动）
- **新建主包 `pages/mine-home/mine-home.vue`**（决策 D8，~100 行）：登录态卡片（直读 `uni.getStorageSync('tt_current_user')`/`tt_auth_mode`，仅展示）+ 功能入口 grid（我的资料/我的需求/我的成果/收藏/意向/机构管理/资本对接 → HostBridge.navigate）+ 未登录引导跳子包 mine
- **pages.json**：主包 pages 只留 dev-home + mine-home；tabBar list 改这两项（图标复用 static/tab/ 现有资源，缺「工作台」图标则用 home 图标）；子包注册 16 页（home/ai-match/mine/capital-list/achievement-list/achievement-detail/search/dock-detail/post-demand/post-result/fee-detail/my-list/ai-eval-detail/org-join/org-apply/org-manage）；preloadRule 保留 dev-home → subpackages/tech-transfer
- **dev-home.vue**：三卡片跳转改子包路径（`/subpackages/tech-transfer/pages/home/home` 等），goTo 的 switchTab fallback 可留（dev-home 属宿主层，允许直用 uni API）

#### T11. AI 评估链路页面改造（决策 D12/D13）

- `post-result.vue`：删除 `mock-data.js` import（addResult/createId）；表单 → `api/achievement.js::createAchievement(body)`（**字段映射以 `modules/achievement/service.py` create_achievement 与 `test_achievement_write_api.py` 为准**，实现时先读这两个文件；预计 title/techIntro/maturity/categoryName/orgName 等便捷字段）→ `submitAchievement(id)` → 成功页提供「发起 AI 评估」按钮 → `createEvaluationTask(achievementId)` → 跳 ai-eval-detail?taskId=
- `my-list.vue`（result 页签）：成果卡片追加「AI 评估」入口——记录最近任务（页面级 state：进入页签时对成果调 GET 任务列表？**无列表接口**——简化：入口仅创建/跳转：点击 → createEvaluationTask（去重命中返回既有任务）→ 跳 ai-eval-detail?taskId=）
- `ai-eval-detail.vue`：onLoad 参数 `taskId`；`getEvaluationTask(taskId)` 单次拉取 + 轮询（queued/running 时 3s 间隔、上限 120s）；四态视图：queued（排队中·AI 服务接入中）、running（处理中）、failed（failReason + 重试按钮=重新创建）、succeeded（四维评分条/总分/结论/亮点——数据形状对齐 T2 视图）；删除 `getAiEvalByResultId`；「查看成果对接详情」改 `HostBridge.navigate('pages/dock-detail/dock-detail', {type:'result', id: achievementId})`

---

### 阶段四：清理（删除全部遗留）

#### T12. 物理删除清单（每项删除后 rg 验证零残留引用）

1. `common/` 整目录（17 文件，含 mock-data.js、ai-chat.js、ai-eval.js、capital-demo-data.js、me-api.js、api-core.js、api-base.js、config.js）
2. `packageA/` 整目录
3. `pages/index/`、`pages/ai-match/`、`pages/mine/`、`pages/capital-list/`
4. `subpackages/tech-transfer/runtime/host-bridge.js`（死代码，决策 D1）
5. `南山/tests/api-base.test.mjs`、`request-retry.test.mjs`、`review-status.test.mjs` → import 路径改指子包模块（`../subpackages/tech-transfer/api/...`）后保留
6. **符号残留检查**（对 `unpackage/dist/dev/mp-weixin` 编译产物 + 源码双侧）：`buildDemoReply`、`getAiEvalByResultId`、`listAiEvalSummaries`、`addResult`、`getAllResults`、`USE_CAPITAL_DEMO`、`capital-demo-data`、`/api/platform-base`、`/api/invest-orgs`、`/api/service-orgs`、`uni.switchTab`（dev-home 除外）、`common/`、`packageA` 全部零命中
   - **编译产物验证时序**（memory 教训）：HBuilderX watch 渐进写盘，须等产物 mtime 稳定（无新增写入）后再做符号检查；必要时关开发者工具删 `unpackage/dist/dev/mp-weixin` 重编译

---

### 阶段五：Phase D — AiNanshanAdapter 边界

#### T13. `host/ainanshan-adapter.example.js`（注释级骨架，不可运行）

按 doc 03 §4.2/§4.3 逐方法写接口骨架 + 待确认协议标注：
- `_getEnvironment()` → 返回上级网关 apiBase（C-08 合并方式确认后定前缀语义）
- `_getIdentityCredential()` → **[C-01 待确认]** 上级 Token/一次性票据格式；默认方案占位 `{hostCredential: <上级登录态>}`
- `_request(options)` → **[C-03 待确认]** 网关身份传递（透传原 token / X-User-Id 可信头 / 网关签发内部 token）；默认方案 Bearer 直传打网关；注入 Authorization（决策 D2：鉴权注入在本层）
- `_upload(file, options)` → **[08 #10 待确认]** 上级统一上传；返回值收敛 `{fileId, url}`
- `_navigate(path, params)` → 分包内相对路径补全上级分包根前缀（`/subpackages/tech-transfer/` 按上级实际注册路径调整，**[C-08 待确认]**）
- `_showMessage/_reportError` → **[08 #11/#13 待确认]** 上级消息/埋点通道
- `_getStorage/_setStorage` → 上级存储通道（会话 key 沿用 tt_* 或映射上级会话，**[C-01 待确认]**）
- 文件头注明：合并步骤 = 契约文件 host/host-bridge.js 拷入上级工程主包同路径 + 上级 App.vue 注册本 adapter（决策 D1 的合并含义）

#### T14. `南山/tests/host-bridge.test.mjs`（node:test 契约测试）

参照现有 tests/*.mjs 的 globalThis.uni mock 模式：
1. **契约校验组**：registerAdapter 缺方法抛错（9 方法逐一缺省）、重复注册抛错、未注册时 getEnvironment/_require 抛错
2. **LocalAdapter 行为组**（import `../host/local-adapter.js`，mock uni.request/uni.getStorageSync 等）：_getEnvironment 返回 env 快照五字段；_request URL 组装（apiBase+prefix+query 编码）+ tt_access_token 存在时注入 Bearer + X-Request-Id 透传；_navigate 补 `/subpackages/tech-transfer/` 前缀与参数编码；_getStorage/_setStorage 读写；_showMessage 调 uni.showToast
3. **Mock AiNanshan 适配器同组用例**：构造一个最小 Mock 适配器（_request 返回固定 SuccessEnvelope、_navigate 记录调用），跑与 LocalAdapter 相同的断言组（URL 组装改断言网关前缀）——证明「换宿主行为一致」（07 §契约测试要求，为 C-01/03 确认后的真实 adapter 兜底）

---

### 阶段六：验证与文档

#### T15. 验证（全量）

**后端**：
1. `test_ai_evaluation_api.py` + `test_search_api.py` 新套件全绿
2. 全量回归：既有全部测试套件（test_auth_register 重跑前清五表固定手机号 13911111111/13922222222；admin 套件队列计数敏感——本轮测试造的成果须 admin 驳回清理）
3. smoke 脚本 + `python -m compileall` 门禁
4. 启动验证：`python start_dev.py`（8787 三分支健康、DB 连接池日志、外网隧道三入口 200）

**前端**：
1. HBuilderX 编译 mp-weixin 零错误；产物 mtime 稳定后符号检查（T12.6 清单）
2. 微信开发者工具（打开 `unpackage/dist/dev/mp-weixin`，AppID wxa65993c6516305c7）人工冒烟清单：
   - dev-home 三入口 + tabBar 两项可达
   - 注册/登录（account）→ 资料 → 发布需求 → 发布成果（真实 API，出现在列表）→ 详情 → 收藏 → 发起对接 → my-list 三页签 → 意向操作
   - 搜索页（统一 /search 双类型）→ 资本列表（/institutions 三 tab）→ 专利年费页
   - AI：ai-match 选需求创建任务（排队态展示）→ post-result 发布后发起评估 → ai-eval-detail 排队态展示
   - 机构：org-join/org-apply/org-manage 回归
3. H5：`start_dev.py --h5` 编译拉起 + 外网 8077 入口 200 + 首页数据加载（vite 冷编译 502 重试即恢复，勿误判）
4. node tests/*.test.mjs 全绿（含新 host-bridge 契约测试）

**架构门（最终验收）**：
- `rg "from '\.\./\.\./\.\./" subpackages/` 仅命中 `host/host-bridge.js`
- 子包内零 `uni.request`（api 层经 HostBridge；dev-home 除外属主包）
- 主包仅 dev-home/mine-home/host/config/static，无业务页无 common/

#### T16. 文档

1. 新建 `docs/architecture/17-phase-bcd-change-report.md`（Added/Changed/Preserved/Deferred/Risks/验证 六段，格式对齐 doc 16）
2. `docs/architecture/12-implementation-plan.md` Phase B 表全部置 ✅、Phase C 置 ✅（注明非模型边界）、Phase D 置「example + 契约测试已交付，真实 adapter 待 C-01/03/07/08」
3. git 两批提交（`git commit -F <临时文件>`；push 用 `git -c http.proxy=http://127.0.0.1:7890 push`）

---

## 五、执行顺序与依赖

```
T1 → T2 → T3（AI 后端）──┐
T4（search 后端）────────┼→ T6（后端测试+回归）→ git commit ①
T5（openapi）───────────┘
         ↓
T7（client.js 重写）→ T8（api/ 收编，验收门：子包零主包依赖）
         ↓
T9（packageA 迁移）→ T10（主包 4 页迁移+TabBar）→ T11（AI 链路页面）
         ↓
T12（清理+符号检查）→ git commit ②
         ↓
T13/T14（AiNanshan example + 契约测试）
         ↓
T15（全量验证）→ T16（文档+提交）
```

## 六、风险与缓解

| 风险 | 缓解 |
|------|------|
| 全量迁移回归面大（16 页 + TabBar + 跳转） | 分两批 git 提交可回退；冒烟清单逐页过；迁移以「搬文件 + 改 import + 改跳转」机械变换为先，逻辑改造（AI 页面）单独任务隔离 |
| 微信 tabBar 页必须在主包 | 壳页方案（决策 D8）；switchTab 残留 rg 门禁 |
| 子包体积超限（2MB/分包） | 无大图迁入（static 留主包）；编译后核对产物大小 |
| HBuilderX watch 渐进写盘误判旧码残留 | 产物 mtime 稳定后再验符号（memory 教训） |
| 删 common/ 后 tests/*.mjs 与隐藏引用断裂 | 删除前先 rg 全工程引用面（含 manifest/App.vue/unpackage 产物） |
| 后端测试污染 admin 审核队列 / 固定手机号重复注册 | 测试纪律见 T6（admin 驳回清理 + 五表清理） |
| ai_task 限流进程内计数在测试间共享导致 429 误判 | 测试用独立用户或顺序设计（match/evaluation 共享 5 次/小时额度） |
| start_dev.py 复用旧后端导致新端点 404 | backend_is_stale 已自动检测；手动验证 `/api/tech-transfer/v1/ai/evaluation-tasks` 路由存在 |
