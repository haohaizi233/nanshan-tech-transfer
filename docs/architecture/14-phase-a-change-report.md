# 14 · Phase A 变更报告 (Change Report)

> 生成时间：2026-09-02  
> Phase: A (Foundation)

---

## Added

### Backend — 模块骨架 (12 个)

| 模块 | 路径 | 层级 | 内容 |
|------|------|------|------|
| organization | `modules/organization/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| inventor | `modules/inventor/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| demand | `modules/demand/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| favorite | `modules/favorite/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| cooperation | `modules/cooperation/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| patent | `modules/patent/` | Domain | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| capital | `modules/capital/` | Domain | `__init__.py` + `service.py` (从 app.py 提取) |
| search | `modules/search/` | Orchestration | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| ai | `modules/ai/` | Orchestration | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| notification | `modules/notification/` | Orchestration | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| audit | `modules/audit/` | Base | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| admin | `modules/admin/` | Orchestration | `__init__.py` + `service.py` (NOT IMPLEMENTED) |
| file | `modules/file/` | Base | `__init__.py` + `service.py` (从 app.py 提取) |

### Backend — 基础设施

| 文件 | 说明 |
|------|------|
| `core/pagination.py` | 分页工具函数，从 app.py `_parse_page_args` 提取 |
| `migrations/003_audit_log.sql` | 审计日志表 (additive, 可回滚) |

### Backend — 路由

| 文件 | 说明 |
|------|------|
| `routes/capital.py` | 资本接口路由 (3 个端点，保留旧路径) |
| `routes/file.py` | 文件代理路由 (1 个端点) |

### 文档

| 文件 | 说明 |
|------|------|
| `docs/architecture/10-implementation-baseline.md` | 仓库清单、技术栈、模块映射 |
| `docs/architecture/11-implementation-gap-analysis.md` | 前端/后端/数据库/API 差距分析 |
| `docs/architecture/12-implementation-plan.md` | Phase A-E 实施计划 |
| `docs/architecture/13-architecture-blockers.md` | 架构阻塞分析 (无阻塞) |
| `docs/architecture/14-phase-a-change-report.md` | 本文件 |
| `docs/architecture/15-phase-a-verification.md` | 验证报告 |

---

## Changed

### `app.py` (311L → 78L)

| 变更 | 说明 |
|------|------|
| 删除内联资本接口 (L93-268) | 迁移到 `modules/capital/service.py` + `routes/capital.py` |
| 删除内联文件代理 (L271-302) | 迁移到 `modules/file/service.py` + `routes/file.py` |
| 删除 `CAPITAL_DB_CONFIG`, `LOGO_CACHE`, `SZTE_FILE_URL` | 迁移到各自模块 |
| 删除 `_get_capital_conn`, `_map_type_key`, `_row_to_*`, `_parse_page_args`, `_query_org_list` | 迁移到模块/工具 |
| 新增 `from routes.capital import bp as capital_bp` | 注册资本蓝图 |
| 新增 `from routes.file import bp as file_bp` | 注册文件蓝图 |
| 新增 `app.register_blueprint(capital_bp)` | 蓝图注册 |
| 新增 `app.register_blueprint(file_bp)` | 蓝图注册 |

### `core/errors.py` (37L → 95L)

| 变更 | 说明 |
|------|------|
| 新增 13 个错误码常量 | 从 OpenAPI 36 个错误码中补全已有路径相关码 |
| 新增 `not_found()`, `forbidden()`, `ai_unavailable()` | 便捷构造器 |

### `modules/capital/service.py` (新增 138L)

- 从 app.py 提取全部资本查询逻辑
- 函数: `list_platforms()`, `list_orgs()`
- 保留跨库连接 (`nanshan_capital` 数据库)

### `modules/file/service.py` (新增 57L)

- 从 app.py 提取文件代理逻辑
- 函数: `proxy_file()`
- 保留 szte.com 图片代理 + 本地缓存

### `routes/capital.py` (新增 31L)

- 3 个路由: `/api/platform-base`, `/api/invest-orgs`, `/api/service-orgs`
- 使用 `core/pagination.parse_page_args()` 替代内联 `_parse_page_args`
- 返回统一 `success()` 格式

### `routes/file.py` (新增 13L)

- 1 个路由: `/api/file/<file_id>`

---

## Preserved

| 行为 | 保留方式 | 原因 |
|------|---------|------|
| 资本接口旧路径 `/api/platform-base` 等 | routes/capital.py 保留原路径 | 前端 capital.js 已对接此路径，Phase B 迁移到新路径 |
| 文件代理路径 `/api/file/<file_id>` | routes/file.py 保留原路径 | 前端 capital.js logoUrl 引用此路径 |
| 健康检查 `/api/health` | 保留在 app.py | 不属于业务模块，属于基础设施 |
| 资本接口使用 `nanshan_capital` 数据库 | capital/service.py 保留跨库连接 | Phase B 迁移表到 tech_transfer |
| 成果 API 返回 `code:0` 格式 (非统一 envelope) | 保留 routes/achievement.py 原逻辑 | 兼容现有前端，Phase B 统一 |
| 身份/成果/用户 全部已有 API | 不改动 | 回归测试验证无破坏 |

---

## Deferred

| 问题 | 延迟到 | 说明 |
|------|--------|------|
| 主包页面绕过 HostBridge | Phase B | common/*.js 直接 uni.request |
| 删除 mock-data.js / user.js | Phase B | 需先完成 demand API |
| 资本表迁移到 tech_transfer | Phase B | nanshan_capital → tech_transfer |
| 资本路径迁移到 /capital/* | Phase B | 兼容期结束后切换 |
| repository 层引入 | Phase B/C | 04 文档推荐结构 |
| DTO/Schema 引入 | Phase B/C | 06 文档要求 |
| 幂等键实现 | Phase B | 仅 6 个创建类接口需要 |
| 限流实现 | Phase E | 60/20/5 per OpenAPI |
| AI 模块实现 | Phase C | 需 AiProvider 配置 |
| packageA 7 页迁移 | Phase B | 使用 Mock 的旧页面 |
| AiNanshanAdapter | Phase D | 待上级平台协议确认 |

---

## Risks

| 风险 | 严重性 | 说明 |
|------|--------|------|
| app.py 大幅缩减后可能有遗漏的引用 | 低 | 已通过全部回归测试验证 |
| capital 模块跨库连接无连接池 | 中 | 沿用旧逻辑，Phase B 改进 |
| stub 模块的 `service.py` 可能被误认为已实现 | 低 | 文件头标注 `NOT IMPLEMENTED` |
| 错误码扩充可能与 OpenAPI 不完全对齐 | 低 | OpenAPI 定义 36 个，已补 18 个，覆盖已有路径 |
