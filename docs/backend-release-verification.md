# 后端发布验证报告（backend-release-verification）

> 验证时间：2026-09-04（Release Closure 增验：Admin 运营域 + File proxy 正向冒烟）
> 被验证服务：tech-transfer-service @ http://127.0.0.1:8787（APP_ENV=local, AUTH_PROVIDER=mock, PostgreSQL 17）
> 验证方式：**全部为真实执行**（HTTP 请求打运行中服务 + SQL 直查数据库断言），输出均为实际运行结果，非静态代码审查

## 1. 验证矩阵总览

| 验证域 | 工具/脚本 | 检查点 | 结果 |
|--------|-----------|--------|------|
| 存量回归：用户隔离 | test_isolation.py | 全套 | ✅ ALL VERIFICATION TESTS PASSED |
| 存量回归：成果读 | test_achievement_api.py | 37 | ✅ 37/37 |
| 存量回归：链路 | test_chain.py | 全套 | ✅ All tests passed |
| 存量回归：需求域 | test_demand_api.py | 88 | ✅ 88/88 |
| 存量回归：交互域 | test_interaction_api.py | 78 | ✅ 78/78 |
| 新增：机构域 | test_institution_api.py | 43 | ✅ 43/43 |
| 新增：AI 域 | test_ai_api.py | 30 | ✅ 30/30 |
| 新增：Admin 域（审核+运营） | test_admin_api.py | 118 | ✅ 118/118 |
| 新增：成果写域 | test_achievement_write_api.py | 51 | ✅ 51/51 |
| legacy 资本 diff | tools/verify_capital_diff.py | 11 场景 | ✅ 11/11 零差异 |
| 发布冒烟 | tools/smoke_release.py | 68 | ✅ 68/68 |
| File proxy 正向冒烟 | 真实 logoFileId（1873991012200878517） | 1 | ✅ 200 image/jpeg 59,972B（JPEG magic ffd8ffe0） |
| OpenAPI 结构 | /openapi.json 实时校验 | 54 路径/16 组 | ✅ |
| **合计** | | **500+** | **全绿** |

## 2. 五项重点审查结论（对应上线前审查要求）

### 2.1 有没有偷偷重构现有 34 个接口？—— 无

- 存量 34 接口路由文件（auth/me/demand/favorite/cooperation/file）本轮仅加 `tags` 参数，业务逻辑零改动
- legacy 资本三接口唯一改动是数据源（MySQL→PG institution 适配层），响应经 11/11 场景逐字段 diff 与 MySQL 基线**零差异**（分页/类型/关键词全覆盖，含 `tools_baseline_capture.py` 捕获的基线）
- 错误码 add-only：仅新增 TT_ACH_40301/40401，既有码未动（errors.py 头部冻结声明保持）

### 2.2 Admin 是不是真的有鉴权？—— 是（user_role 实时查库）

验证证据（test_admin_api.py 真实执行）：
- 无 Token → 401
- 普通用户 Token（test-admin-c，bootstrap 真实签发）→ **403 + code=TT_ADMIN_40301**（依赖内实时 `SELECT 1 FROM user_role WHERE user_id=? AND role_code='admin'`，非 JWT roles 快照）
- admin Token（dev-user-001，005 种子）→ 200
- Admin 全部 16 路径 / 18 方法都挂 `Depends(admin_identity)`：审核组 `routes/admin.py` 7 个 + 运营组 `routes/admin_ops.py` 11 个（逐路由核验）
- 运营域四组（dashboard/institutions/cooperations/users）每组均有「无 Token 401 / 普通用户 403 TT_ADMIN_40301 / admin 200」三连断言

### 2.3 Institution 是否复用旧资本数据？—— 是（ETL 迁移，非空表）

- `tools/etl_institutions.py` 真实执行：MySQL 资本三表 137 行（platform_base 100 + featured_invest_org 21 + ip_service_org 16）→ PG institution
- SQL 断言 institution 行数 = 137，legacy 三接口 diff 零差异即数据等价的端到端证明
- `ON CONFLICT (kind, source_pk) DO UPDATE` 幂等，可重跑不重复

### 2.4 AI Router 是否只是稳定边界，没有假 AI？—— 是

- GET /ai/match-tasks/{id} 对 queued/running 任务返回 `results: null`（test_ai_api.py 断言），无任何模拟分数/匹配结果
- ai_match_result 表仅 worker 写入路径（服务层无写调用）
- 快照固化后任务创建即返回，无同步执行假等待

### 2.5 有没有真实跑测试？—— 是（本会话全部真实执行，输出见上）

- 9 套件 + diff + 冒烟在本会话 Shell 中真实运行，exit code 0
- 后端为真实运行进程（8787 监听，/api/health 200）

## 3. 发布冒烟明细（tools/smoke_release.py，68 检查点）

| 检查项 | 结果 |
|--------|------|
| GET /api/health = 200, code=0, status=ok, database=ok | ✅ |
| GET /docs、/openapi.json（仅 local） | ✅ 200 |
| auth/bootstrap 真实签发 token | ✅ 200 |
| **61 个接口方法全扫描**（openapi.json 枚举）：GET 断言无 500；写方法断言 200/201/400/401/403/404/409/422/429（业务可预期） | ✅ 全通过 |
| /api/file/{id} 代理语义（400/404/502 合法，502=源站拉取失败） | ✅ |
| CORS 预检 OPTIONS（Origin=localhost:5173） | ✅ 200 |
| 带 Origin 实际请求（H5 dev server 同源策略模拟） | ✅ 200 |

**File proxy 正向冒烟（Release Closure 补充）**：取库里真实 logoFileId `1873991012200878517`（深圳市创新投资集团）GET `/api/file/1873991012200878517` → 200 `image/jpeg` 59,972 字节，magic bytes `ffd8ffe0`（JPEG SOI）确认二进制完整，非占位/空响应。

## 4. 状态机端到端验证（真实 HTTP 流）

**成果全生命周期**（test_achievement_write_api.py）：
```
POST /achievements（201, draft, version=1）
  → PATCH（owner+乐观锁, version→2, inventorRefs 整体替换）
  → POST submit（200, pending_review）
  → 重复 submit（409 TT_ACH_40901）
  → pending_review 编辑（409）
  → admin approve（200, published, published_at 落库 SQL 断言）
  → owner offline（200, offline, reason 记录）
  → 重复 offline（409）
admin reject 分支：reject（200, rejected, reject_reason 落库）
  → rejected 可编辑（200）→ 重新 submit（200）
```

**非 owner 防护**：D 用户对 C 的成果 PATCH→403 TT_ACH_40301、submit→403、GET 详情（draft）→data=null（防探测）

**审计日志**（SQL 断言 audit_log）：achievement.create/update/submit/offline/approve 全部落库，requestId 贯穿

## 5. 数据完整性验证

| 项 | 方法 | 结果 |
|----|------|------|
| MySQL→PG 迁移行数 | 迁移脚本输出逐表比对 | 18 表 1503 行 ✅ |
| 自增序列 | setval 重置后新插入无冲突（本轮测试多次创建 id 连续递增） | ✅ |
| 中文数据 | psql Unicode 转义字面量比对（绕过控制台 GBK 显示问题） | ✅ |
| capital 数据等价 | 11 场景逐字段 diff | ✅ 零差异 |
| 测试数据清理 | 每套件清理 owner>3 的测试数据，演示数据（223 成果）不受影响 | ✅（test_achievement_api 断言 total 仍=223） |

## 6. 环境与运行时快照

| 项 | 值 |
|----|-----|
| 服务 | FastAPI/uvicorn @ 0.0.0.0:8787 |
| 数据库 | PostgreSQL 17.11 @ 127.0.0.1:5432，库 tech_transfer（21+4 表） |
| Python | 3.13（系统，start_dev.py 同环境）；psycopg2 2.9.12 |
| 健康检查 | /api/health → code=0, status=ok, database=ok, appUsers=22 |
| 文档 | /docs /redoc /openapi.json（54 路径，16 tag 分组，health tag 无 default 残留） |

## 7. Admin 运营域闭环验证（Release Closure 增验）

**机构可见性闭环**（test_admin_api.py 真实 HTTP 流）：
```
admin POST /admin/institutions（201, active）
  → 公开 GET /institutions/{id} 可见 + 列表命中（闭环 1/1b）
admin POST offline（200, status=disabled）
  → 公开详情 data=null + 列表不含（闭环 2/2b）
  → 管理端仍可见（disabled + keyword 可检索）（闭环 3）
  → 重复 offline → 409 TT_INST_40901
admin POST online（200, active）
  → 公开恢复可见（闭环 4）
admin PATCH（intro/label/sortOrder 更新生效，status 不变，空 body 400，不存在 404）
审计 SQL 断言：institution.create/offline/online/update 全部落库
```

**Dashboard 数字与 SQL 直查一致**：users/demands/cooperations 三项与手工 COUNT 比对相等；pendingTotal = pendingAchievements + pendingDemands；无趋势假字段。

**Cooperation / Users 只读性**：GET 详情前后 status 不变；用户 roles 数组实时聚合（详情 roles 含 admin）。

**本轮发现并修复**：list_users_admin COUNT SQL 拼接缺陷 + 子查询别名笔误（详见 change-report §3.6 修复清单）；修复后 Admin 套件 118/118。

## 8. 发布结论

**通过。** 增量补齐 27 个新接口方法（机构 2 / AI 2 / Admin 审核 7 / 成果写 5 / Admin 运营 11）+ MySQL→PG 数据底座切换，存量 34 接口零契约变更。500+ 检查点、legacy diff 11/11、发布冒烟 68/68、File proxy 正向冒烟全部真实执行且全绿。

已知非阻断项（详见 change-report §6）：幂等键回放保护、AI worker、限流 Redis 化——均已记录排期，不影响本轮上线。
