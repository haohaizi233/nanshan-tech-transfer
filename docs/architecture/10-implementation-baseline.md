# 10 · 实施基线 (Implementation Baseline)

> 生成时间：2026-09-02  
> 状态：Phase A 基线  
> 依据：真实代码仓库扫描，非假设

---

## 1. Repository Inventory

```text
nanshan-tech-transfer/
├── docs/
│   └── architecture/
│       ├── 01-current-state-audit.md
│       ├── 02-target-architecture.md
│       ├── 03-frontend-dual-host-design.md
│       ├── 04-backend-domain-design.md
│       ├── 05-data-model-design.md
│       ├── 06-api-design.md
│       ├── 07-integration-and-testing.md
│       ├── 08-upper-platform-checklist.md
│       ├── 09-risk-register.md
│       ├── 10-freeze-review.md
│       ├── adr/
│       │   ├── ADR-001-dual-host-single-source.md
│       │   ├── ADR-002-local-user-external-identity.md
│       │   └── ADR-003-modular-monolith.md
│       └── openapi.yaml (2841 lines, 52 paths, 58 operations)
├── tech-transfer-service/          # 后端模块化单体
│   ├── app.py                      # 311 lines — Flask 入口 + 资本接口 + 文件代理
│   ├── config.py                   # 45 lines — 环境配置 + 生产保护
│   ├── db.py                       # 53 lines — 连接池
│   ├── etl_achievements.py          # 363 lines — 成果 ETL
│   ├── inspect_excel.py            # 30 lines — 调试工具
│   ├── requirements.txt            # flask, flask-cors, pymysql, pyjwt
│   ├── core/
│   │   ├── errors.py               # 37 lines — BizError + 错误码常量
│   │   ├── jwt_utils.py             # 44 lines — JWT 签发/验证
│   │   ├── middleware.py            # 30 lines — @auth_required 装饰器
│   │   └── response.py              # 29 lines — success/error 统一响应
│   ├── migrations/
│   │   ├── 001_identity_domain.sql  # 5 tables
│   │   └── 002_achievement_domain.sql # 5 tables
│   ├── modules/
│   │   ├── identity/                # service.py(244) provider.py(59) context.py(22)
│   │   ├── profile/                 # service.py(77)
│   │   └── achievement/             # service.py(193)
│   ├── routes/
│   │   ├── auth.py                  # 46 lines — bootstrap/refresh/logout
│   │   ├── me.py                    # 23 lines — GET/PATCH /me
│   │   └── achievement.py           # 47 lines — list/detail/search/categories
│   └── test files: test_chain.py(60) test_isolation.py(117) test_achievement_api.py(128)
├── tools/
│   ├── api-server/                 # 旧 Flask API (352 lines, 已被 tech-transfer-service 接管)
│   ├── platform-crawler/           # 平台数据爬虫
│   ├── szte-crawler/               # 机构数据爬虫
│   ├── import_data.py              # 数据导入脚本
│   ├── nanshan_capital_backup_utf8.sql
│   └── export_db_to_excel.py
├── 南山小程序/
│   ├── start_dev.py                # 245 lines — 一键启动器
│   ├── tools/                      # (同上, 实际开发版)
│   └── 南山/                        # uni-app 源码
│       ├── App.vue                  # 57 lines
│       ├── main.js                  # 24 lines
│       ├── manifest.json            # 70 lines (appid: wxa65993c6516305c7)
│       ├── pages.json               # tabBar: 首页/AI匹配/我的
│       ├── common/                  # 11 JS modules
│       │   ├── config.js            # API_BASE + USE_CAPITAL_DEMO
│       │   ├── mock-data.js         # 需求 Mock 数据 (209 lines)
│       │   ├── user.js              # 旧本地认证 (617 lines, 待替换)
│       │   ├── capital.js           # 资本对接 (239 lines)
│       │   ├── capital-demo-data.js # 资本演示数据 (651 lines)
│       │   ├── achievement-api.js   # 成果 API 主包版 (110 lines)
│       │   ├── me-api.js            # 用户 API 主包版 (124 lines)
│       │   ├── ai-chat.js           # AI 对话 Mock (55 lines)
│       │   ├── ai-eval.js           # AI 评估 Mock (125 lines)
│       │   ├── patent-fee.js        # 专利年费 (205 lines)
│       │   ├── search.js            # 搜索 (87 lines)
│       │   └── external-miniprogram.js # 外部小程序跳转 (62 lines)
│       ├── config/
│       │   ├── local.env.js         # 环境变量 (APP_ENV/HOST_MODE/AUTH_PROVIDER/API_BASE)
│       │   └── env-check.js         # 构建期环境硬校验
│       ├── host/
│       │   ├── host-bridge.js        # HostBridge 契约 (9 methods, 89 lines)
│       │   ├── local-adapter.js     # LocalAdapter 实现 (170 lines)
│       │   └── mock-identity.js      # MockIdentityProvider (28 lines)
│       ├── pages/                   # 主包页面
│       │   ├── dev-home/            # 宿主入口 (3 路由卡片)
│       │   ├── index/               # 首页 (782 lines, Banner/搜索/需求/成果/检索/资本)
│       │   ├── ai-match/            # AI 匹配 (265 lines)
│       │   ├── mine/                # 我的 (874 lines, 旧本地认证)
│       │   └── capital-list/        # 资本对接列表 (530 lines)
│       ├── packageA/               # 旧演示分包 (7 pages, Mock 数据)
│       │   ├── search/              # 搜索页 (443 lines)
│       │   ├── dock-detail/        # 对接详情 (764 lines)
│       │   ├── post-demand/        # 发布需求 (267 lines)
│       │   ├── post-result/        # 发布成果 (279 lines)
│       │   ├── fee-detail/         # 年费详情 (219 lines)
│       │   ├── my-list/            # 我的内容 (438 lines)
│       │   └── ai-eval-detail/     # AI 评估结果 (258 lines)
│       ├── subpackages/tech-transfer/  # 业务分包
│       │   ├── api/
│       │   │   ├── client.js       # API 客户端 (118 lines, HostBridge 集成)
│       │   │   ├── achievement.js  # 成果 API (33 lines)
│       │   │   └── me.js            # 用户 API (39 lines)
│       │   ├── constants/
│       │   │   └── error-codes.js   # 错误码常量 (18 lines)
│       │   ├── pages/
│       │   │   ├── mine/            # 身份引导/资料 (311 lines)
│       │   │   ├── achievement-list/  # 成果列表 (414 lines)
│       │   │   └── achievement-detail/ # 成果详情 (380 lines)
│       │   └── runtime/
│       │       └── host-bridge.js   # (已移至主包 host/)
│       └── static/                 # 图标 + Banner
└── .gitignore, .cursorrules, .editorconfig
```

---

## 2. Current Technology Stack

| 维度 | 技术 | 备注 |
|------|------|------|
| 小程序框架 | uni-app (Vue 3) | 编译到微信小程序 |
| 语言 | JavaScript | 无 TypeScript |
| UI 框架 | 无 | 自定义 CSS (rpx 单位) |
| 状态管理 | Vue data + uni.getStorageSync | 无 Vuex/Pinia |
| 网络请求 | uni.request | 主包 common/ 直接调用；分包通过 HostBridge |
| 后端语言 | Python 3 | |
| 后端框架 | Flask 3.0 | 模块化单体 |
| 数据库 | MySQL 8.x | 两个库: `tech_transfer`(业务) + `nanshan_capital`(爬虫数据) |
| ORM | 无 | 原生 SQL via pymysql + DictCursor |
| 身份认证 | JWT (HS256) | accessToken 2h + refreshToken 14d (jti 吊销) |
| 文件上传 | 代理下载到本地缓存 | szte.com 图片代理, 非 HostBridge upload |
| AI 调用 | Mock | ai-chat.js / ai-eval.js 全部为前端假数据 |
| 部署方式 | 本地开发 | start_dev.py 一键启动, 无 CI/CD |

---

## 3. Existing Modules Mapping

### 3.1 Backend Modules

| 当前代码 | 目标模块 | 层级 | 状态 | 说明 |
|----------|---------|------|------|------|
| `modules/identity/service.py` (244L) | identity | Base | REUSE | bootstrap/refresh/logout 完整 |
| `modules/identity/provider.py` (59L) | identity | Base | REUSE | MockIdentityProvider 实现 |
| `modules/identity/context.py` (22L) | identity | Base | REUSE | IdentityContext 数据类 |
| `modules/profile/service.py` (77L) | profile | Domain | REUSE | GET/PATCH /me + 乐观锁 |
| `modules/achievement/service.py` (193L) | achievement | Domain | REUSE | list/detail/search/categories |
| `app.py` 资本接口 (L93-268) | capital | Domain | REFACTOR | 内联在 app.py, 需提取为模块 |
| `app.py` 文件代理 (L271-302) | file | Base | REFACTOR | 内联在 app.py, 需提取为模块 |
| — | organization | Domain | MISSING | 表已建, 无 service 代码 |
| — | inventor | Domain | MISSING | 表已建, 无 service 代码 |
| — | demand | Domain | MISSING | 无表, 无代码 |
| — | favorite | Domain | MISSING | 无表, 无代码 |
| — | cooperation | Domain | MISSING | 无表, 无代码 |
| — | patent | Domain | MISSING | 无表, 前端有 patent-fee.js |
| — | search | Orchestration | MISSING | 仅 achievement 内搜索, 无统一搜索模块 |
| — | ai | Orchestration | MISSING | 无表, 前端全 Mock |
| — | notification | Orchestration | MISSING | 无表, 无代码 |
| — | audit | Base | MISSING | 表在设计中, 无代码 |
| — | admin | Orchestration | MISSING | 无表, 无代码 |

### 3.2 Frontend Modules

| 当前代码 | 目标 | 状态 | 说明 |
|----------|------|------|------|
| `host/host-bridge.js` (89L) | HostBridge 契约 | REUSE | 9 方法接口完整 |
| `host/local-adapter.js` (170L) | LocalAdapter | REUSE | 实现 HostBridge 全部方法 |
| `host/mock-identity.js` (28L) | MockIdentityProvider | REUSE | 生成 local-dev-ticket |
| `config/local.env.js` | RuntimeConfig | REUSE | APP_ENV/HOST_MODE/AUTH_PROVIDER/API_BASE |
| `config/env-check.js` | EnvironmentGuard | REUSE | staging/prod 硬校验 |
| `common/config.js` | ApiConfig | REUSE | API_BASE + USE_CAPITAL_DEMO |
| `common/achievement-api.js` | ApiClient (成果) | REUSE | 主包轻量版, uni.request |
| `common/me-api.js` | ApiClient (用户) | REUSE | 主包轻量版, 绕过 HostBridge |
| `common/mock-data.js` (209L) | demand Mock | REPLACE | 需求列表 Mock 数据, 待替换为 API |
| `common/user.js` (617L) | 旧本地认证 | REPLACE | 本地缓存伪账户, 待替换 |
| `common/ai-chat.js` (55L) | AI Mock | REPLACE | 假 AI 对话, 待替换 |
| `common/ai-eval.js` (125L) | AI Mock | REPLACE | 假 AI 评分, 待替换 |
| `common/capital.js` (239L) | capital (前端) | REFACTOR | 混合 Mock + API, 需清理 |
| `common/patent-fee.js` (205L) | patent (前端) | REFACTOR | 硬编码费用表, 需对接后端 |
| `packageA/` (7 pages) | 旧演示页面 | REPLACE | 全部使用 Mock, 需迁移到 tech-transfer 分包 |
| `subpackages/tech-transfer/` | 业务分包 | REUSE | 3 页面已对接后端 API |

### 3.3 Database Tables

| 数据库 | 表名 | 行数 | 目标模块 | 状态 |
|--------|------|------|---------|------|
| tech_transfer | app_user | 3 | identity | REUSE |
| tech_transfer | external_identity | 3 | identity | REUSE |
| tech_transfer | user_profile | 3 | profile | REUSE |
| tech_transfer | user_role | 3 | identity | REUSE |
| tech_transfer | auth_session | 0 | identity | REUSE |
| tech_transfer | organization | 0 | organization | REUSE (表已建, 无数据) |
| tech_transfer | achievement | 223 | achievement | REUSE |
| tech_transfer | achievement_category | 10 | achievement | REUSE |
| tech_transfer | inventor | 314 | inventor | REUSE (表已建, 无独立 service) |
| tech_transfer | achievement_inventor | 446 | achievement | REUSE |
| nanshan_capital | platform_base | 100 | capital | REFACTOR (需迁移到 tech_transfer) |
| nanshan_capital | featured_invest_org | 21 | capital | REFACTOR |
| nanshan_capital | ip_service_org | 16 | capital | REFACTOR |
| — | demand (目标) | — | demand | MISSING (表未建) |
| — | cooperation_intent (目标) | — | cooperation | MISSING |
| — | ai_task (目标) | — | ai | MISSING |
| — | file_object (目标) | — | file | MISSING |
| — | notification (目标) | — | notification | MISSING |
| — | audit_log (目标) | — | audit | MISSING |

---

## 4. Git History Summary

| Commit | 类型 | 内容 |
|--------|------|------|
| `1fa190c` | fix | 恢复首页并重构 tabBar 为 首页/AI匹配/我的 |
| `fd4c31a` | fix | 分包页面改用主包 common/ API，绕过 HostBridge |
| `7bf4061` | refactor | 科转通 tab 直接跳转分包成果列表页 |
| `08f8237` | fix | move host-bridge.js to main package |
| `3f2739f` | fix | resolve blank screen - main package cannot require subpackage |
| `c5e58ba` | feat | complete achievement read-only vertical slice |
| `d56a396` | feat | complete local identity vertical slice + 全部架构文档 |

---

## 5. Key Findings

1. **身份链路完整可用**：bootstrap → app_user → user_profile → /me，3 个用户，乐观锁，JWT 双令牌，环境保护全部就绪
2. **成果只读链路完整可用**：223 条数据，分页/搜索/分类/详情 API + 前端页面全部对接后端
3. **12 个后端模块缺失**：organization/inventor/demand/favorite/cooperation/patent/capital/search/ai/notification/audit/admin — 需创建骨架
4. **资本接口内联在 app.py**：3 个资本 API + 1 个文件代理直接写在 app.py，违反模块化单体边界
5. **前端 Mock 数据未清除**：mock-data.js(需求)、user.js(旧认证)、ai-chat.js/ai-eval.js(AI Mock) 仍在使用
6. **packageA 7 个旧页面待迁移**：全部使用 Mock，需逐步迁移到 tech-transfer 分包
7. **两个数据库并存**：tech_transfer(业务) 和 nanshan_capital(爬虫)，资本数据需迁移
8. **HostBridge 契约完整**：9 方法接口 + LocalAdapter 实现就绪，但主包页面仍直接使用 uni.request
