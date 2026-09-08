# 17 · Phase B/C/D 变更报告 (Change Report) — 分包收口 + AI 非模型链路 + 宿主骨架

> 生成时间：2026-09-08  
> Phase: B 收口（搜索统一/Mock 全清/资本统一/主包 HostBridge/packageA 全量迁移）+ C（AI 任务基础设施与前端链路，非模型）+ D（AiNanshanAdapter example + 契约测试）  
> 提交：后端 `fddd580`、前端 `7b6347e`、D 骨架与文档另批提交  
> 范围：后端 evaluation-tasks + 统一搜索 + 机构契约同步；前端全量分包迁移（packageA 10 页 + 主包 4 业务页）、AI Mock 全清、HostBridge 唯一依赖收敛

---

## Added

### Backend — 数据库

| 文件 | 说明 |
|------|------|
| `migrations/pg/013_ai_evaluation.sql` | `ai_evaluation` 表：四维评分（tech_innovation/maturity/value/market）+ 总分 + 模型元信息（provider/model_version）+ 建议文本，供 worker 落结果。**本轮无 worker，表恒空 = 零假数据**（测试显式断言）。additive，幂等可重跑 |

### Backend — 模块与路由

| 文件 | 说明 |
|------|------|
| `modules/ai/service.py`（扩展） | `create_evaluation_task`：成果 owner 校验（403）/成果存在（404）/仅已提交成果可评估（400）；**10 分钟去重窗口**（同成果未终态任务直接返回同 taskId，200）；与 match 共享**用户级 5 次/小时限流**（429，进程内计数）；审计 `ai.task.create`（taskType=evaluation）。`get_evaluation_task`：仅创建者可见（403）、任务类型隔离（match 任务经 evaluation 端点查 404）、内嵌 evaluation（无 worker 时恒 null） |
| `routes/ai.py`（扩展） | POST `/ai/evaluation-tasks`（202）、GET `/ai/evaluation-tasks/{id}` |
| `modules/search/service.py`（扩展） | 统一搜索域聚合：achievement + demand 双类型（type=achievement/demand/all）、keyword/categoryCode/分页，单一入口收敛 |
| `routes/search.py` | GET `/search`（需登录） |
| `test_evaluation_api.py` | 36 项断言：创建 202/403/404/400、去重同 taskId、查询可见性/类型隔离/404、限流 429、审计落库、**无 worker 时 queued + ai_evaluation 零行** |
| `test_search_api.py` | 32 项断言：双类型过滤、keyword/categoryCode/分页、type=all 混排、越权与参数边界 |

### Frontend — 分包 API 层（唯一通道 HostBridge）

| 文件 | 说明 |
|------|------|
| `subpackages/tech-transfer/api/client.js`（重写，328 行） | 全部请求经 `HostBridge.request`：登录 token 注入（tt_auth_mode=account）、401 自动刷新重试一次、公开接口 `publicRequest`（无 token）、X-Idempotency-Key 自动生成、X-Request-Id 透传、统一 code!==0 抛错与错误码映射 |
| `api/ai.js` | match/evaluation 任务创建与查询、`POLL_INTERVAL_MS=3000`/`POLL_MAX_MS=120000` 轮询常量、终态判断 |
| `api/search.js` | 统一搜索（双类型）+ 卡片模型转换 |
| `api/capital.js` | 统一机构接口 `/institutions`（kind=platform/invest/service + type），logoUrl 相对路径补全 |
| `constants/capital-modules.js` | 资本子模块展示配置（从原主包 common/capital.js 演示数据分支剥离） |
| `constants/error-codes.js` | 分包错误码常量（含 TT_AI_*） |

### Frontend — AI 链路页面（Mock 全清）

| 页面 | 说明 |
|------|------|
| `pages/ai-match/ai-match.vue`（404 行，新） | 任务制匹配：选需求创建 match 任务（去重命中直接跳详情）、排队态展示、状态轮询；**删除本地假回复 buildDemoReply** |
| `pages/ai-eval-detail/ai-eval-detail.vue`（510 行，新） | 评估任务详情：3s 轮询（上限 120s）、四维评分雷达/进度条展示、失败重试（重新 createEvaluationTask）、succeeded 后对接入口；**替换原假评分孤页** |
| `pages/post-result/post-result.vue`（459 行，新） | 真实发布：`createAchievement` → `submitAchievement`（draft→pending_review）→ 发起 AI 评估跳 ai-eval-detail；**删除 mock-data.js 本地写入** |
| `pages/my-list/my-list.vue`（扩展） | 成果卡新增「AI 评估」入口（createEvaluationTask 去重跳转） |

### Frontend — 主包壳页与宿主骨架

| 文件 | 说明 |
|------|------|
| `pages/mine-home/mine-home.vue`（新） | tabBar「我的」壳页：登录态判断 → 跳分包 mine 或登录页；主包仅 2 页（dev-home + mine-home） |
| `host/ainanshan-adapter.example.js`（新，T13） | AiNanshanAdapter 骨架：9 方法全部实现签名 + `throw` 标注未确认协议（C-01 凭证/C-03 网关身份/C-08 合并根路径 + 08 #10 上传/#11 消息/#13 监控），注释内含实现步骤与 SuccessEnvelope 透传约定 |
| `tests/host-bridge.test.mjs`（新，T14） | 23 项契约测试：未注册抛错、9 方法缺失校验（缺一即拒）、LocalAdapter URL 组装（base+prefix+query 编码）/Bearer 注入/X-Request-Id 生成、Mock AiNanshan 适配器同组断言（换宿主行为一致） |

---

## Changed

### Backend

| 文件 | 变更 |
|------|------|
| `routes/capital.py` | legacy 三组并行接口（`/platform-base`、`/invest-orgs`、`/service-orgs`）与演示数据分支废弃，统一 `/institutions` 契约 |
| `routes/achievement.py` | 移除内联搜索逻辑（收敛到 search 域，-9 行） |
| `app.py` | 注册 search 路由 |
| `test_achievement_api.py` | 适配搜索收敛（断言迁至 test_search_api.py） |
| `docs/architecture/openapi.yaml` | 同步 evaluation-tasks、/search、机构契约（-180 行冗余） |

### Frontend — 全量分包迁移

| 变更 | 说明 |
|------|------|
| packageA 10 页 → `subpackages/tech-transfer/pages/` | post-result、ai-eval-detail、org-apply、org-join、org-manage、achievement-detail 等；**packageA 目录删除** |
| 主包 4 业务页 → 分包 | index→home、ai-match、mine（1108 行重写为 1468 行真实 API 版）、capital-list；主包仅剩 dev-home + mine-home |
| `pages.json` 重构（-149 行） | tabBar 2 项（dev-home、mine-home 壳页）；分包 16 页注册 |
| `host/local-adapter.js` | 移除主包 common 依赖，HostBridge 装配主包化 |
| 分包页面 import 路径 | 全部改经分包自有 `api/`（原 `../common/`、`../../api/` 错误相对路径批量修正） |

## Deleted

| 目标 | 说明 |
|------|------|
| `common/` 全目录（12 文件，-2672 行） | api-core、mock-data、achievement-api、ai-chat、ai-eval、capital-demo-data、capital、config、search、me-api、api-base 等——Mock 数据与主包请求栈彻底清除 |
| `pages/index`、`pages/ai-match`、`pages/mine` | 主包业务页（已迁分包） |
| `subpackages/tech-transfer/runtime/host-bridge.js` | 分包内重复 HostBridge 实现，统一 import 主包 `host/host-bridge.js` |

---

## Preserved

| 行为 | 保留方式 | 原因 |
|------|---------|------|
| 全部既有 API 契约 | /demands、/achievements、/favorites、/cooperations、/me/*、/admin/*、/institutions 路径与响应结构不变 | 前端迁移零后端破坏性变更 |
| 19 个后端测试套件 | 本轮全量回归全绿（见验证段） | 回归门禁 |
| MockIdentityProvider | 本地开发身份不变（AUTH_PROVIDER=mock） | 硬约束：staging/production 禁用 |
| `/api/tech-transfer/v1` 统一前缀 | client.js 组装 base+prefix | 架构约定 |
| 演示数据 ETL 与归属 | etl_achievements.py / etl_demands.py 不动 | 本地演示双视角链路 |
| 统一响应/错误契约 | TT_* 错误码 add-only，X-Request-Id 全链路 | T008 契约 |

---

## Deferred

| 问题 | 延迟到 | 说明 |
|------|--------|------|
| AI worker（真实模型调用） | AiProvider 配置后 | 任务保持 queued、ai_evaluation 恒空是**设计边界而非缺陷**；TT_AI_50301 边界已在错误码注册 |
| AiNanshanAdapter 真实实现 | C-01/03/07/08 协议确认 | example 骨架 + 契约测试已交付，确认后按注释步骤填充 |
| 微信开发者工具人工冒烟 | 用户执行 | 清单见实施计划 T15（注册→发布→对接→AI→资本→机构全链路） |
| H5 端 tabBar 表现真机验证 | Phase E | mine-home 壳页跳分包首次有按需加载延迟 |
| phone 登录未提交改动 | 独立任务 | 工作区 identity/auth/012 迁移为早前会话遗留，不属本轮范围 |

---

## Risks

| 风险 | 严重性 | 说明 |
|------|--------|------|
| 限流 5 次/小时共享（match+evaluation） | 中 | 进程内计数，重启清零；真实用户连发 5 次即 429，前端已提示；多 worker 部署时需换共享存储 |
| 去重窗口 10 分钟内无法主动重评 | 低 | 失败任务不受窗口限制可重试；窗口内重复点击返回同任务 |
| 分包首次加载延迟 | 低 | tabBar 壳页跳分包按需加载（约几百 KB），微信分包机制预期行为 |
| legacy capital 路径删除 | 低 | 若有外部调用方依赖 /platform-base 等旧路径需迁移到 /institutions（OpenAPI 已同步） |
| ai_evaluation 评分展示为固定四维 | 低 | 模型接入后若维度变化需同步前端 SCORE_DIMENSIONS |
| 轮询 120s 上限后停止 | 低 | 用户手动刷新或重试可恢复；终态到达即停 |

---

## 验证

### 后端（2026-09-08 实测）

- **19 套件全绿**：ai 30/30、evaluation 36/36、search 32/32、institution 43/43、achievement 37/37、achievement_write 55/55、demand 96/96、interaction 82/82、chain 全过、assisted_cooperation 93/93、view_count 全过、organization_membership 213/213、auth_register 35/35（前置 cleanup_auth_register_fixture.py 清五表固定手机号）、identity_flexibility 28/28、admin 118/118（评估套件未污染审核队列计数）、error_contract 32/32、isolation 全过、db_session 16/16、db_hardening 19/19
- `python -m compileall` exit 0
- `tools/smoke_release.py` 109/109（扫描 102 方法）
- 运行中后端实测：`/search` 401（路由存在需登录，符合预期）、`/institutions` code=0 total=100

### 前端（2026-09-08 实测）

- `node --test tests/*.test.mjs` **32/32**（含 host-bridge 契约 23 项）
- HBuilderX 编译产物：主包 2 页（dev-home/mine-home）+ 分包 16 页；产物 mtime（12:45:09）新于业务源码（12:44:49）
- 符号检查：`buildDemoReply` 零残留、`mock-data.js` 已移除、`packageA` 仅命中 uni-app 框架内部符号 `createSubpackageApp`（非旧目录引用）

### 架构门（最终验收）

- 分包 3 层以上相对引用 **12 处全部指向 `host/host-bridge.js`**，零违规
- 子包内 `uni.request` **零命中**（api 层全经 HostBridge）
- 主包 `pages/` 仅 dev-home + mine-home，`common/` 目录不存在
- 主包对分包仅导航 URL 字符串（dev-home 三入口），无模块 require
