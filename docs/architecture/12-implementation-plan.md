# 12 · 实施计划 (Implementation Plan)

> 生成时间：2026-09-02  
> 依据：冻结架构 + Gap Analysis (文档 11)  
> 原则：Inspect → Map → Plan → Implement minimally → Run → Verify → Document

---

## Phase A — Foundation（本轮执行）

### A1. Backend Module Skeleton

**目标**：为 04 文档定义的全部 15 模块创建目录和最小 stub。

**已存在**：identity, profile, achievement（3 个）

**需创建**：organization, inventor, demand, favorite, cooperation, patent, capital, search, ai, notification, audit, admin, file（12 个）

**规则**：
- 每个模块目录: `modules/<name>/__init__.py`
- stub service: `modules/<name>/service.py` — 含 `# NOT IMPLEMENTED` 标注
- 不创建 router（避免注册空路由）
- 不建表（仅骨架）

### A2. Unified API Infrastructure

**目标**：补全 core/ 层缺失的基础设施。

**已存在**：
- `core/response.py` — success/error 统一响应 ✅
- `core/errors.py` — BizError + 5 个错误码 ✅
- `core/jwt_utils.py` — JWT 签发/验证 ✅
- `core/middleware.py` — @auth_required ✅

**需补全**：
- `core/pagination.py` — 分页工具函数（从 app.py 提取 _parse_page_args）
- `core/errors.py` — 补充 OpenAPI 定义的错误码常量
- `core/idempotent.py` — 幂等键校验工具（Phase A 仅框架, 不强制）

### A3. Capital Module Extraction

**目标**：将 app.py 内联的资本接口提取为独立模块。

**当前**：app.py L93-302 内联 3 个资本 API + 1 个文件代理

**变更**：
- 创建 `modules/capital/service.py` — 迁移查询逻辑
- 创建 `routes/capital.py` — 迁移路由定义（保留旧路径兼容）
- app.py 注册 capital_bp, 删除内联代码
- 保留 `/api/platform-base`, `/api/invest-orgs`, `/api/service-orgs` 旧路径（兼容）
- Phase B 迁移到 `/api/tech-transfer/v1/capital/*` 新路径

### A4. File Module Extraction

**目标**：将 app.py 内联的文件代理提取为独立模块。

**当前**：app.py L271-302 内联 `/api/file/<file_id>`

**变更**：
- 创建 `modules/file/service.py` — 迁移文件代理逻辑
- 创建 `routes/file.py` — 迁移路由
- app.py 注册 file_bp, 删除内联代码

### A5. Frontend Host Boundary Verification

**目标**：确认 HostBridge 契约完整，标记需改进项。

**现状**：
- `host/host-bridge.js` — 9 方法契约 ✅
- `host/local-adapter.js` — 全部实现 ✅
- `host/mock-identity.js` — MockIdentityProvider ✅
- `config/local.env.js` — 环境配置 ✅
- `config/env-check.js` — 构建期校验 ✅

**Phase A 不改动前端代码**（边界已存在，主包绕过 HostBridge 的问题留给 Phase B）

### A6. Configuration Verification

**目标**：确认环境配置和环境保护机制完整。

**后端 config.py**：
- APP_ENV / HOST_MODE / AUTH_PROVIDER / API_BASE / DB_* ✅
- assert_environment() 生产环境保护 ✅

**前端 config/local.env.js**：
- APP_ENV / HOST_MODE / AUTH_PROVIDER / API_BASE / API_PREFIX ✅
- env-check.js 构建期校验 ✅

**Phase A 无需改动配置代码**

### A7. Database Migration — audit_log

**目标**：为 Phase A 新增的 audit 模块创建表。

- 创建 `migrations/003_audit_log.sql` — 仅 CREATE TABLE, additive

---

## Phase B — Core Domain Migration（✅ 已完成 2026-09-08，收口报告见文档 17）

| 链路 | 模块 | 前置 | 工作量 | 状态 |
|------|------|------|--------|------|
| 需求 CRUD | demand | 建表 + service + router + 前端迁移 | 大 | ✅ 已完成（2026-09-03，见文档 16） |
| 收藏 | favorite | 建表 + service + router | 小 | ✅ 已完成（2026-09-03，迁移 005 + /me/favorites + 幂等 PUT/DELETE，前端 index/dock-detail/my-list/mine 已接入） |
| 对接 | cooperation | 建表 + 状态机 + 四角色权限 | 大 | ✅ 已完成（2026-09-03，迁移 005 + 五操作状态机 + 乐观锁 + accept 自动拒绝/confirm 需求转 matched 副作用，前端 dock-detail/my-list/mine 已接入，78 项断言 + 成果目标冒烟 13/13） |
| 搜索统一 | search | 抽离 achievement 搜索 | 中 | ✅ 已完成（2026-09-08，GET /search 双类型聚合 + test_search_api 32 项，见文档 17） |
| Mock 清除 | — | 删除 mock-data.js, user.js | 中 | ✅ 已完成（2026-09-08，common/ 全目录 12 文件删除，AI 假回复/假评分/成果本地写入全清，见文档 17） |
| 资本迁移 | capital | nanshan_capital → tech_transfer | 中 | ✅ 已完成（2026-09-08，统一 /institutions（kind=platform/invest/service），legacy 三组接口与演示数据分支废弃，见文档 17） |
| 主包 HostBridge | — | common/*.js 改用 HostBridge | 中 | ✅ 已完成（2026-09-08，分包 api/client.js 全量经 HostBridge.request，主包 common/ 删除，架构门 12 处越包引用全为 host-bridge.js，见文档 17） |
| packageA 迁移 | — | 7 页迁移到 tech-transfer | 大 | ✅ 已完成（2026-09-08，packageA 10 页 + 主包 4 业务页全量迁入分包 16 页，packageA 目录删除，主包仅剩 dev-home + mine-home 壳页，见文档 17） |

---

## Phase C — AI Capability（✅ 非模型边界已交付 2026-09-08，见文档 17）

| 接口 | 模块 | 依赖 | 状态 |
|------|------|------|------|
| POST /ai/match-tasks | ai | demand + achievement 数据 | ✅ 已交付 |
| GET /ai/match-tasks/{id} | ai | 任务状态机 | ✅ 已交付 |
| POST /ai/evaluation-tasks | ai | achievement 数据 | ✅ 已交付（迁移 013 + owner/状态校验 + 10 分钟去重 + 限流共享，36 项断言） |
| GET /ai/evaluation-tasks/{id} | ai | 任务状态机 | ✅ 已交付（类型隔离 + 内嵌 evaluation） |

**关键约束**：AiProvider 未配置时返回 `TT_AI_50301`，禁止假数据。  
**非模型边界（2026-09-08）**：任务基础设施（状态机 queued/running/succeeded/failed、去重、限流、审计）+ 前端全链路（ai-match 任务制、ai-eval-detail 轮询展示、post-result 发起评估）已交付；**AI worker（真实模型调用）待 AiProvider 配置**，无 worker 时任务保持 queued、ai_evaluation 表恒空（测试显式断言零假数据）。

---

## Phase D — Host Integration（example + 契约测试已交付 2026-09-08，真实 adapter 待协议确认）

| 依赖项 | 来源 | 状态 |
|--------|------|------|
| C-01 上级认证协议 | 08 文档 | 已索取未确认 |
| C-03 上级路由协议 | 08 文档 | 已索取未确认 |
| C-07 包合并方式 | 08 文档 | 待确认 |
| C-08 网关部署 | 08 文档 | 已索取未确认 |
| AiNanshanAdapter | 03 文档 | ✅ example 骨架 + 契约测试已交付（`host/ainanshan-adapter.example.js` 9 方法签名 + 未确认协议标注；`tests/host-bridge.test.mjs` 23 项含 Mock AiNanshan 同组断言）；真实 adapter 待 C-01/03/07/08 |
| AiNanshanIdentityProvider | ADR-002 | 待实现（随真实 adapter） |

---

## Phase E — Integration & Acceptance（本轮仅规划）

| 验收项 | 标准 |
|--------|------|
| 本地联调 | 全部 25 页面 OpenAPI → Backend → Frontend 一致 |
| 正向测试 | 主链路全绿 |
| 负向测试 | 401/403/409/503 全覆盖 |
| 双宿主测试 | local + AiNanshan adapter 均通过 |
| 性能 | 50 并发 P95 < 800ms |
| 安全 | 9 项 S1-S9 全部解决 |

---

## 执行顺序

```
A1 后端模块骨架 (12 个 stub)
    ↓
A2 API 基础设施补全 (pagination + errors 扩充)
    ↓
A3 Capital 模块提取
    ↓
A4 File 模块提取
    ↓
A5/A6 前端/配置验证 (无改动)
    ↓
A7 audit_log 建表
    ↓
验证：后端启动 + 前端编译 + 回归测试
    ↓
文档：change-report + verification
    ↓
Git commit + push
```
