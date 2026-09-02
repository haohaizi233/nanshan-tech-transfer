# 13 · 架构阻塞 (Architecture Blockers)

> 生成时间：2026-09-02  
> 本轮 Phase A 扫描结果

---

## 扫描结论

**本轮未发现架构级阻塞。** 冻结架构可在当前代码基线上落地。

以下为需关注但非阻塞的架构约束：

---

## B-01: 主包页面绕过 HostBridge

```text
SOURCE: 03-frontend-dual-host-design.md §4 (ban list)
CODE EVIDENCE: common/achievement-api.js, common/me-api.js 直接使用 uni.request
IMPACT: 主包页面（index.vue, search.vue）未通过 HostBridge 调用 API，违反"业务代码不得直接 uni.request"禁令
PROPOSED: 不修改冻结文档。Phase B 将 common/ 下的 API 模块改为通过 HostBridge.request()
```

**非阻塞原因**：HostBridge 契约本身完整，LocalAdapter 已实现。主包绕过是历史代码遗留，Phase B 可渐进修复。

---

## B-02: app.py 内联资本接口路径不统一

```text
SOURCE: 06-api-design.md (OpenAPI paths: /capital/*)
CODE EVIDENCE: app.py 定义 /api/platform-base, /api/invest-orgs, /api/service-orgs
IMPACT: 资本接口路径与 OpenAPI 契约不一致
PROPOSED: Phase A 提取为 capital 模块时保留旧路径兼容；Phase B 迁移到 /capital/* 新路径
```

**非阻塞原因**：旧路径可与新路径并存，前端可同时兼容。

---

## B-03: service.py 直接写 SQL 无 repository 层

```text
SOURCE: 04-backend-domain-design.md (modules/<name>/{router.py, service.py, repository.py, schemas.py})
CODE EVIDENCE: modules/identity/service.py, modules/achievement/service.py 直接执行 SQL
IMPACT: 04 文档要求 repository.py 层，当前缺失
PROPOSED: Phase A 不强制拆分。Phase B/C 逐步引入 repository 层
```

**非阻塞原因**：当前规模下 service 直接写 SQL 不影响模块边界。04 文档的目录结构为推荐结构，不是硬约束。

---

## B-04: 两个数据库并存

```text
SOURCE: 05-data-model-design.md (统一 schema: tech_transfer)
CODE EVIDENCE: tech_transfer(业务表) + nanshan_capital(爬虫数据表)
IMPACT: 资本模块需跨库查询，违反单 schema 原则
PROPOSED: Phase B 将 nanshan_capital 表迁移到 tech_transfer 库
```

**非阻塞原因**：app.py 已通过 _get_capital_conn() 实现跨库连接，功能正常。迁移在 Phase B 执行。
