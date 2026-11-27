# Phase P3-0 全项目基线审计与问题清单

- 审计日期：2026-11-27
- 基线 Commit：`7bbeb1e7917cc066c4264361853b042f3b3d3ca7` (`github/main` == `HEAD`)
- 工作分支：`feat/phase-p3-engineering-hardening`
- 本地验证环境：Windows / Python 3.13.17 / Node v26.13.0 / PostgreSQL 18.6 / Redis

## 1. 代码规模与工程基线（排除构建产物、依赖与第三方库）

| 目录 | 生产文件 | 生产代码行 | 测试文件 | 测试代码行 | 最大生产源码文件 |
|---|---:|---:|---:|---:|---|
| `tech-transfer-service/` | 205 | 43,680 | 123 | 45,779 | `modules/admin/service.py` (131.7 KB / 3,415 lines) |
| `nanshan-ai-agent/` | 27 | 6,582 | 15 | 2,049 | `app/router.py` (28.6 KB / 936 lines) |
| `nanshan-frontend/` | 43 | 20,262 | 13 | 705 | `src/views/admin/AchievementView.vue` (62.4 KB / 2,267 lines) |
| `南山小程序/南山/` | 166 | 50,298 | 59 | 6,401 | `subpackages/tech-transfer/pages/mine/mine.vue` (109.8 KB / 3,338 lines) |
| `tools/` | 6 | 418 | 0 | 0 | `tools/add_operation_ids.py` (5.8 KB / 132 lines) |
| `.github/workflows/` | 1 | 238 | 0 | 0 | `ci.yml` (8.3 KB / 238 lines) |

- 排除项：`node_modules`、`dist`、`unpackage`、`__pycache__`、`.venv`、第三方静态脚本 `vue.global.prod.js`、历史 SQL 备份 `tools/codex_membership_task4_20260907_backup.sql`。
- 测试收集基线：
  - `tech-transfer-service` pytest 收集：**2,621** tests
  - `nanshan-ai-agent` pytest 收集：**157** tests
  - `南山小程序/南山` Node 测试文件：**59** files (`tests/*.test.mjs`)
  - `nanshan-frontend` Node 测试文件：**13** files (`tests/*.test.mjs`, `src/utils/*.test.mjs`)
- OpenAPI 路由规模：`162` paths / `182` operations。
- PostgreSQL 迁移最新版本：`042_capital_institution_icons.sql`。
- `TODO` / `FIXME` 统计：生产源码中 `0` 处。
- AST 导入扫描（`tech-transfer-service/modules/`）：
  - 跨模块边：`34` 条；2-节点循环依赖：`1` 组 (`achievement` ↔ `admin`)。
  - 跨模块私有函数导入：`10` 处（全部位于 `modules/admin/service.py` 导入 `achievement`/`cooperation`/`demand` 内部 `_` 辅助函数）。
- 安全模块（`modules/security/`）宽泛 `except Exception`：65 处（多为诊断/日志降级与失败兜底，需重点核查异步所有权与状态持久化路径）。

## 2. 问题清单（Issue Register）

### 已确认缺陷（Confirmed Defects）

- **P3-ISS-001** | Severity: **High (P0)** | `tech-transfer-service/modules/security/sms_gateway.py:754-872`
  - **Root Cause**: `run_queued_recovery_task()` 仅将 `state` 置为 `processing`，未生成和校验 `execution_owner`；`_persist_task_result()` 仅检查 `WHERE id=%s AND state='processing'`，且 `run_recovery_task` → `_send()` 未校验 Worker 执行权。
  - **Impact**: 若 Worker A 领取后卡顿、被清理/超时回收后由 Worker B 接管，Worker A 恢复后仍可能创建新 challenge 或推进状态。
  - **Reproduction**: Worker A 领取 `queued` 任务并暂停 → 清理/新 Worker 接管 → Worker A 恢复继续执行 `_send`。
  - **Proposed Fix**: 领取时写入唯一 `execution_owner`，在 `_send()` 外呼前及 `_persist_task_result()` 中强制校验 `execution_owner` CAS。
  - **Acceptance Test**: PostgreSQL 并发测试验证旧 Worker 恢复后无法获得发送权且 Provider 调用次数为 0。

- **P3-ISS-002** | Severity: **High (P0)** | `tech-transfer-service/modules/security/delivery_models.py:335-439`
  - **Root Cause**: `_persist_risk_sync_outcome()` 在 `reservation_missing` / `conflict` / `retryable_failure` 分支更新 `auth_challenge` 时未校验 `risk_sync_target`、终态 `risk_sync_state <> 'synced'` 及 `risk_sync_claimed_at` 租约。
  - **Impact**: 迟到或旧目标的协调失败结果可能覆盖新目标已落盘的 `synced` 状态。
  - **Reproduction**: 目标 A 协调失败延迟写回，期间目标 B 已成功写入 `synced`。
  - **Proposed Fix**: 传入 `expected_claimed_at` 并在全部分支增加 `WHERE id=%s AND (risk_sync_target IS NULL OR risk_sync_target=%s) AND risk_sync_state <> 'synced'`。
  - **Acceptance Test**: PostgreSQL 测试验证旧目标/旧租约写回不能覆盖 `synced`。

- **P3-ISS-003** | Severity: **Medium (P1)** | `tech-transfer-service/modules/security/delivery_models.py:539`
  - **Root Cause**: `reconcile_pending_risk_syncs()` 已实现但未接入应用生命周期或后台维护定时调度，仅靠手工运维脚本触发。
  - **Impact**: Redis 短时故障导致的 `sync_pending` / `retryable_failure` 记录无法自动补偿。
  - **Reproduction**: 检查 `reconcile_pending_risk_syncs` 全仓引用，仅在定义和单测中出现。
  - **Proposed Fix**: 接入轻量受控的后台维护调度器，记录积压数与最近成功时间，零 Provider 调用。
  - **Acceptance Test**: 集成测试验证调度器自动推进待协调记录且可观测指标更新。

- **P3-ISS-004** | Severity: **High (P0)** | `tech-transfer-service/modules/security/schema_gate.py:14`
  - **Root Cause**: `REQUIRED_SECURITY_SCHEMA_VERSION` 仍停留在 `"039"`，未覆盖 `040_registration_sms.sql` 的注册确权约束（`ck_auth_challenge_registration_owner`、`uk_auth_challenge_active_registration_phone`）及后续应用表结构（041/042）。
  - **Impact**: 数据库停留在 039 时启动门禁放行，但注册短信确权与新字段在运行时失败。
  - **Proposed Fix**: 升级安全门禁至 `040` 并增加应用 Schema 门禁 `042`。
  - **Acceptance Test**: 缺失 040 约束或 042 字段时 `assert_required_*` 拒绝启动。

- **P3-ISS-005** | Severity: **Medium (P1)** | `tech-transfer-service/modules/ai/eval_stream.py:19,90-200`
  - **Root Cause**: `eval_stream.py` 使用进程内 `_channels` / `threading.Lock` / `queue.Queue`。
  - **Impact**: 独立 AI Worker 进程与 API 进程分离时，SSE 无法实时推送 token 增量，只能退化到 DB 轮询。
  - **Proposed Fix**: 接入 Redis Streams（有界、TTL、带 `execution_id` 围栏与序号），Redis 不可用时平滑回退。
  - **Acceptance Test**: 真实双进程（Worker 进程 + 订阅进程）集成测试验证实时增量与断线重连。

- **P3-ISS-006** | Severity: **Medium (P1)** | `watchdog.sh:4-45`, `install_watchdog.sh`, `com.nanshan.watchdog.plist`
  - **Root Cause**: 部署脚本硬编码 `/Users/mac/...` 路径、混入 unrelated `stock-api` 服务，并按端口 `lsof -i :$port` 强杀进程。
  - **Impact**: 不可移植至其他主机/Linux，且存在误杀同机其他服务风险。
  - **Proposed Fix**: 路径与配置外置环境变量，移除无关项目服务，改用 PID 文件管理进程。
  - **Acceptance Test**: 配置化检查与脚本语法/路径校验通过。

### 潜在风险（Potential Risks）

- **P3-RSK-001** | Severity: **High (P0)** | `nanshan-ai-agent/app/reranker.py:123-190`, `tech-transfer-service/modules/achievement/extract.py:87-127`
  - **Root Cause**: `nanshan-ai-agent` 直接读取 PG `tech_intro`、`description`、`innovation_points` 送入 LLM 且未做正文联系方式脱敏；`strip_private_contact_text` 对带敏感 query 参数（`token`、`secret`、`password` 等）的 URL 整体放行。
  - **Impact**: 自由文本若含手机号/邮箱/微信号或带凭据 URL，可能进入第三方 LLM 请求或 AI 卡片响应。
  - **Proposed Fix**: 统一隐私分级与脱敏契约（含敏感 URL 参数剥离），在 LLM 输入前、输出格式化前、持久化前全链路清洗，并用 Mock LLM 载荷测试验证。
  - **Acceptance Test**: `PRIV-01` ~ `PRIV-15` 参数化测试与跨服务契约测试全部通过。

- **P3-RSK-002** | Severity: **Medium (P1)** | `nanshan-ai-agent/app/services/retrieval.py`
  - **Root Cause**: 检索目前为加权 `ILIKE` 关键词匹配，尚无版本化离线评测集（dev/test 分离）与定量 IR 指标基线。
  - **Proposed Fix**: 先建立评测集与指标体系，再对照实验优化关键词权重、字段召回与硬条件重校验。

- **P3-RSK-003** | Severity: **Medium (P1)** | `tech-transfer-service/modules/admin/service.py` (3,415 lines), `mine.vue` (3,338 lines), `ai-match.vue` (2,544 lines)
  - **Root Cause**: 单文件职责高度集中，且 `admin/service.py` 存在 10 处跨模块 `_` 私有函数导入及与 `achievement` 的双向依赖。
  - **Proposed Fix**: 渐进式拆分并保留兼容门面，配合 AST 导入棘轮防止新增违规依赖。

### 尚未完成的验收（Incomplete Acceptances）

- **P3-INC-001** | `docs/auth/email-gateway/19-live-otp-verification-acceptance.md`
  - 状态：`DELIVERY_ONLY_VERIFIED`。真实邮箱/短信验证码业务闭环需用户本人在业务页面输入验证码完成，代码阶段不可伪造替代。

### 正常架构权衡与不值得修复项（Trade-offs / Won't Fix）

- **P3-TRD-001 (Normal Trade-off)**: 模块化单体架构 + PostgreSQL 持久化 AI 任务队列（`SKIP LOCKED` + Lease + CAS），避免引入 Kafka/K8s/独立向量数据库，符合当前团队与运维规模。
- **P3-TRD-002 (Normal Trade-off)**: `ci.yml` 中全仓 `mypy .` 配置为 `continue-on-error: true` 而安全核心为阻断门禁，后续采用类型债务棘轮（不新增错误）而非一次性清零全仓历史注解。
- **P3-WNF-001 (Won't Fix)**: 不重写已稳定的 `Session Guard`、`Step-up`、`OTP HMAC`、`Redis Risk Engine`、Challenge 状态机及历史迁移 `001`–`042`。
