# 11 · 实施差距分析 (Implementation Gap Analysis)

> 生成时间：2026-09-02  
> 方法：Current State → Frozen Architecture → Required Change

---

## 1. Frontend Gap Analysis

### 1.1 Host Boundary

| 检查项 | 现状 | Gap | 优先级 |
|--------|------|-----|--------|
| HostAdapter 契约 | `host/host-bridge.js` 9 方法完整 | 无 | P0 ✅ |
| LocalAdapter 实现 | `host/local-adapter.js` 全部方法实现 | 无 | P0 ✅ |
| MockIdentityProvider | `host/mock-identity.js` 生成 local-dev-ticket | 无 | P0 ✅ |
| AiNanshanAdapter | 不存在 | 缺失（Phase D） | P2 |
| 主包页面直接 uni.request | index.vue 通过 achievement-api.js 直接 uni.request | 违反 HostBridge 禁令 | P1 |
| if (isLocal) 分支 | 不存在 | 无 | P0 ✅ |
| 硬编码 API URL | `common/config.js` API_BASE = 127.0.0.1:8787 | 仅配置层, 未侵入业务 | P1 |

### 1.2 Auth Boundary

| 检查项 | 现状 | Gap | 优先级 |
|--------|------|-----|--------|
| AuthAdapter (前端) | common/me-api.js + achievement-api.js 内联 token 管理 | 重复逻辑, 未抽象为 AuthAdapter | P1 |
| 旧本地认证 | common/user.js (617L) — uni.getStorageSync 伪账户 | 仍在 pages/mine/mine.vue 引用 | P1 |
| token 过期刷新 | achievement-api.js 有 ensureToken + bootstrap | me-api.js 也有重复逻辑 | P1 |

### 1.3 API Client

| 检查项 | 现状 | Gap | 优先级 |
|--------|------|-----|--------|
| 分包 API 客户端 | `subpackages/tech-transfer/api/client.js` (118L) | 通过 HostBridge, 已正确 | P0 ✅ |
| 主包 API 客户端 | common/achievement-api.js + common/me-api.js | 直接 uni.request, 绕过 HostBridge | P1 |
| 统一 API 客户端 | 不存在 | 主包和分包有两套 API 调用逻辑 | P1 |

### 1.4 Runtime Config

| 检查项 | 现状 | Gap | 优先级 |
|--------|------|-----|--------|
| 环境配置 | `config/local.env.js` (APP_ENV/HOST_MODE/AUTH_PROVIDER) | 完整 | P0 ✅ |
| 构建期校验 | `config/env-check.js` (staging/prod 硬校验) | 完整 | P0 ✅ |
| 前端配置入口 | `common/config.js` (API_BASE + USE_CAPITAL_DEMO) | 存在但与 config/ 分离 | P1 |

### 1.5 Mock 数据侵入

| 文件 | 类型 | 侵入位置 | 清除阶段 |
|------|------|---------|---------|
| `common/mock-data.js` (209L) | 需求列表 Mock | index.vue demandList | Phase B |
| `common/user.js` (617L) | 本地认证 + 收藏 + 对接 | mine.vue, index.vue, dock-detail.vue | Phase B |
| `common/ai-chat.js` (55L) | AI 对话 Mock | ai-match.vue | Phase C |
| `common/ai-eval.js` (125L) | AI 评估 Mock | ai-eval-detail.vue | Phase C |
| `common/capital-demo-data.js` (651L) | 资本演示数据 | capital-list.vue | Phase B |

### 1.6 硬编码/侵入式代码扫描

| 关键词 | 出现位置 | 严重性 |
|--------|---------|--------|
| `uni.request` 在业务代码 | common/achievement-api.js, me-api.js, capital.js | P1 (主包绕过 HostBridge) |
| `uni.getStorageSync` 在业务代码 | common/user.js, common/me-api.js, local-adapter.js | P1 |
| `uni.navigateTo` 在业务代码 | pages/index/index.vue, packageA/*.vue | P2 (03 文档要求 HostBridge.navigate) |
| `wx.login` | 不存在 | ✅ |
| `openid` | 不存在 | ✅ |
| `mock score` | common/ai-eval.js 生成随机评分 | P1 (Phase C 替换) |
| `hardcoded API URL` | config.js API_BASE = 'http://127.0.0.1:8787' | P0 ✅ (仅配置层) |

---

## 2. Backend Gap Analysis

### 2.1 模块结构

| 目标模块 | 层级 | 目录存在 | service.py | router.py | 表存在 | 状态 |
|---------|------|---------|-----------|-----------|--------|------|
| identity | Base | ✅ | ✅ (244L) | ✅ auth.py (46L) | ✅ 5 tables | REUSE |
| profile | Domain | ✅ | ✅ (77L) | ✅ me.py (23L) | ✅ | REUSE |
| achievement | Domain | ✅ | ✅ (193L) | ✅ achievement.py (47L) | ✅ 5 tables | REUSE |
| file | Base | ❌ | ❌ | ❌ (内联 app.py) | ❌ | MISSING |
| audit | Base | ❌ | ❌ | ❌ | ❌ | MISSING |
| organization | Domain | ❌ | ❌ | ❌ | ✅ (空表) | MISSING |
| inventor | Domain | ❌ | ❌ | ❌ | ✅ (314 rows) | MISSING |
| demand | Domain | ❌ | ❌ | ❌ | ❌ | MISSING |
| favorite | Domain | ❌ | ❌ | ❌ | ❌ | MISSING |
| cooperation | Domain | ❌ | ❌ | ❌ | ❌ | MISSING |
| patent | Domain | ❌ | ❌ | ❌ | ❌ | MISSING |
| capital | Domain | ❌ | ❌ | ❌ (内联 app.py) | ✅ (nanshan_capital) | REFACTOR |
| search | Orchestration | ❌ | ❌ | ❌ (achievement.py 内搜索) | — | MISSING |
| ai | Orchestration | ❌ | ❌ | ❌ | ❌ | MISSING |
| notification | Orchestration | ❌ | ❌ | ❌ | ❌ | MISSING |
| admin | Orchestration | ❌ | ❌ | ❌ | ❌ | MISSING |

### 2.2 API 基础设施

| 检查项 | 现状 | Gap |
|--------|------|-----|
| 统一响应格式 | core/response.py (success/error) | ✅ 符合 OpenAPI envelope |
| 错误码体系 | core/errors.py (5 个错误码) | 需扩充至 36 个 (OpenAPI 定义) |
| 异常处理 | app.py errorhandler(BizError/404/500) | ✅ |
| 认证中间件 | core/middleware.py @auth_required | ✅ |
| 请求上下文 | g.request_id + g.identity | ✅ |
| 分页工具 | _parse_page_args() 内联在 app.py | 需提取到 core/ |
| 幂等键处理 | 不存在 | OpenAPI 要求 6 个接口, 需实现 |
| 限流 | 不存在 | OpenAPI 要求 60/20/5 |

### 2.3 Controller/Service/Repository 分层

| 层次 | 现状 | Gap |
|------|------|-----|
| Router 层 | routes/*.py — 仅参数解析 + 调用 service | ✅ 职责正确 |
| Service 层 | modules/*/service.py — 业务逻辑 + SQL | ⚠️ SQL 直接写在 service, 无 repository 层 |
| Repository 层 | 不存在 | 04 文档要求 repository.py, 当前缺失 |
| DTO/Schema | 不存在 | 06 文档要求 request/response schema |

---

## 3. Database Gap Analysis

| 目标实体 | 当前表 | 数据库 | Gap | 迁移需求 |
|---------|--------|--------|-----|---------|
| app_user | app_user (3 rows) | tech_transfer | ✅ MATCH | — |
| external_identity | external_identity (3 rows) | tech_transfer | ✅ MATCH | — |
| user_profile | user_profile (3 rows) | tech_transfer | ✅ MATCH | — |
| user_role | user_role (3 rows) | tech_transfer | ✅ MATCH | — |
| auth_session | auth_session (0 rows) | tech_transfer | ✅ MATCH | — |
| organization | organization (0 rows) | tech_transfer | ✅ MATCH | — |
| achievement | achievement (223 rows) | tech_transfer | ✅ MATCH | — |
| achievement_category | achievement_category (10 rows) | tech_transfer | ✅ MATCH | — |
| inventor | inventor (314 rows) | tech_transfer | ✅ MATCH | — |
| achievement_inventor | achievement_inventor (446 rows) | tech_transfer | ✅ MATCH | — |
| demand | 不存在 | — | MISSING | Phase B 建表 |
| cooperation_intent | 不存在 | — | MISSING | Phase B 建表 |
| cooperation_event | 不存在 | — | MISSING | Phase B 建表 |
| favorite | 不存在 | — | MISSING | Phase B 建表 |
| ai_task | 不存在 | — | MISSING | Phase C 建表 |
| ai_evaluation | 不存在 | — | MISSING | Phase C 建表 |
| ai_match_result | 不存在 | — | MISSING | Phase C 建表 |
| file_object | 不存在 | — | MISSING | Phase A/B 建表 |
| notification | 不存在 | — | MISSING | Phase B/C 建表 |
| audit_log | 不存在 | — | MISSING | Phase A 建表 |
| platform_base | platform_base (100 rows) | nanshan_capital | MISMATCH | 需迁移到 tech_transfer |
| featured_invest_org | featured_invest_org (21 rows) | nanshan_capital | MISMATCH | 需迁移到 tech_transfer |
| ip_service_org | ip_service_org (16 rows) | nanshan_capital | MISMATCH | 需迁移到 tech_transfer |

---

## 4. API Gap Analysis

### 4.1 OpenAPI vs Backend Implementation

| OpenAPI Path | Method | 后端实现 | 状态 |
|-------------|--------|---------|------|
| `/auth/bootstrap` | POST | routes/auth.py | MATCH ✅ |
| `/auth/refresh` | POST | routes/auth.py | MATCH ✅ |
| `/auth/logout` | POST | routes/auth.py | MATCH ✅ |
| `/me` | GET | routes/me.py | MATCH ✅ |
| `/me/profile` | PATCH | routes/me.py | MATCH ✅ |
| `/me/demands` | GET | — | MISSING |
| `/me/achievements` | GET | — | MISSING |
| `/me/favorites` | GET | — | MISSING |
| `/me/cooperations` | GET | — | MISSING |
| `/achievements` | GET | routes/achievement.py | MATCH ✅ |
| `/achievements` | POST | — | MISSING |
| `/achievements/{id}` | GET | routes/achievement.py | MATCH ✅ |
| `/achievements/{id}` | PATCH | — | MISSING |
| `/achievements/{id}/submit` | POST | — | MISSING |
| `/achievements/{id}/offline` | POST | — | MISSING |
| `/achievements/{id}/evaluations` | GET | — | MISSING |
| `/achievements/categories` | GET | routes/achievement.py | MATCH ✅ |
| `/demands` | GET | — | MISSING |
| `/demands` | POST | — | MISSING |
| `/demands/{id}` | GET | — | MISSING |
| `/demands/{id}` | PATCH | — | MISSING |
| `/demands/{id}/submit` | POST | — | MISSING |
| `/demands/{id}/cancel` | POST | — | MISSING |
| `/demands/{id}/matches` | GET | — | MISSING |
| `/favorites/{type}/{id}` | PUT | — | MISSING |
| `/favorites/{type}/{id}` | DELETE | — | MISSING |
| `/cooperations` | GET | — | MISSING |
| `/cooperations` | POST | — | MISSING |
| `/cooperations/{id}` | GET | — | MISSING |
| `/cooperations/{id}/accept` | POST | — | MISSING |
| `/cooperations/{id}/reject` | POST | — | MISSING |
| `/cooperations/{id}/confirm` | POST | — | MISSING |
| `/cooperations/{id}/cancel` | POST | — | MISSING |
| `/cooperations/{id}/complete` | POST | — | MISSING |
| `/cooperations/{id}/events` | GET | — | MISSING |
| `/search` | GET | routes/achievement.py (仅 achievement) | PARTIAL |
| `/ai/match-tasks` | POST | — | MISSING |
| `/ai/match-tasks/{taskId}` | GET | — | MISSING |
| `/ai/evaluation-tasks` | POST | — | MISSING |
| `/ai/evaluation-tasks/{taskId}` | GET | — | MISSING |
| `/capital/platforms` | GET | app.py `/api/platform-base` | MISMATCH (路径不统一) |
| `/capital/platforms/{id}` | GET | — | MISSING |
| `/capital/investment-orgs` | GET | app.py `/api/invest-orgs` | MISMATCH |
| `/capital/financial-orgs` | GET | — | MISSING |
| `/capital/service-orgs` | GET | app.py `/api/service-orgs` | MISMATCH |
| `/patents` | GET | — | MISSING |
| `/patents/{id}` | GET | — | MISSING |
| `/uploads/presign` | POST | — | MISSING |
| `/uploads/complete` | POST | — | MISSING |
| `/admin/review-queue` | GET | — | MISSING |
| `/admin/achievements/{id}/approve` | POST | — | MISSING |
| `/admin/achievements/{id}/reject` | POST | — | MISSING |
| `/admin/demands/{id}/approve` | POST | — | MISSING |
| `/admin/demands/{id}/reject` | POST | — | MISSING |
| `/admin/audit-logs` | GET | — | MISSING |

### 4.2 Summary

| 状态 | 数量 | 占比 |
|------|------|------|
| MATCH | 8 | 14% |
| PARTIAL | 1 | 2% |
| MISMATCH | 3 | 5% |
| MISSING | 46 | 79% |
| **Total** | **58** | 100% |

---

## 5. Gap Priority Summary

### P0 — Phase A 必须解决

1. 后端 12 个模块目录缺失 → 创建骨架目录
2. 资本接口内联在 app.py → 提取为 capital 模块
3. 文件代理内联在 app.py → 提取为 file 模块
4. 错误码仅 5 个 → 补充至覆盖全部已有路径

### P1 — Phase B 解决

1. 前端主包页面直接 uni.request → 通过 HostBridge 或统一 ApiClient
2. common/user.js 旧认证 → 替换为后端 API
3. common/mock-data.js 需求 Mock → 替换为 demand API
4. capital 数据在 nanshan_capital 库 → 迁移到 tech_transfer
5. 资本 API 路径不统一 → 迁移到 /capital/* 前缀

### P2 — Phase C/D 解决

1. AI 模块 + AI Mock 替换
2. 上级平台 Adapter 集成
3. 专利模块对接
4. 审计/通知/管理模块
