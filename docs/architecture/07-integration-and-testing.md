# 07 · 联调设计与实施顺序（Integration & Testing）

> 文档状态：基线版
> 阅读前提：`03`（分包结构与 HostBridge）、`06`（接口契约）
> 本文内容：页面级联调矩阵、上级到位前后两种联调模式、切换检查项、回归范围、阶段 A–E 实施顺序

---

## 1. 联调总原则

1. **本地联调即正式联调的预演**：本地模式与正式模式使用同一份页面、同一套 API 路径与模型，联调发现的 bug 一次修复两环境生效（ADR-001）。
2. **验收以数据落库为准**：任何"提交成功"必须能以对应 `audit_log` 记录和业务表行验证，不接受 Toast 即通过的验收。
3. **每个链路先过"未认证/越权"负向用例**，再过正向用例。

## 2. 完整联调矩阵（页面 → 前端 API 函数 → HTTP → 模块 → 表）

前端 API 函数位于 `subpackages/tech-transfer/api/`（03 §5），命名 `fetchXxx / createXxx / updateXxx`。

| 页面 | 前端 API 函数 | HTTP 接口 | 后端模块 | 数据表 | 外部依赖 | 验收条件 |
|------|--------------|-----------|----------|--------|----------|----------|
| index（首页-需求Tab） | fetchDemandList | GET /demands | demand | demand(+category/tag) | 无 | 分页/关键词/分类过滤正确；仅见 published（includeMine=false） |
| index（首页-成果Tab） | fetchAchievementList | GET /achievements | achievement | achievement(+...) | 无 | 同上 |
| index（收藏切换） | putFavorite / deleteFavorite | PUT/DELETE /favorites/{type}/{id} | favorite | favorite | 无 | 刷新后状态保持；未登录引导登录 |
| ai-match（AI匹配） | createMatchTask / getMatchTask | POST/GET /ai/match-tasks | ai | ai_task, ai_match_result, ai_model_version | AiProvider | 任务 202 受理→轮询 succeeded→结果含 score/reasons/modelVersion；Provider 停机时任务 failed + TT_AI_50201 |
| ai-match（需求上下文） | fetchMyDemands | GET /me/demands | demand | demand | 无 | 仅本人需求 |
| mine（登录初始化） | bootstrap / getMe | POST /auth/bootstrap, GET /me | identity/profile | app_user, external_identity, user_profile | IdentityProvider | 首次 bootstrap 建档（isNewUser=true）；displayName 空显示"未填写" |
| mine（资料编辑） | updateMyProfile | PATCH /me/profile | profile | user_profile | 无 | version 冲突返回 409 且前端可恢复 |
| capital-list（4类列表） | fetchPlatforms / fetchInvestOrgs / fetchFinancialOrgs / fetchServiceOrgs | GET /capital/* | capital | capital_platform, capital_organization | Logo 回源 | 分页/关键词与现网一致；`msg`→`message` 迁移后前端解析正常 |
| search（搜索） | search | GET /search | search | （读 achievement/demand） | 无 | 成果+需求双结果；本地搜索历史保留 |
| dock-detail（需求详情） | fetchDemandDetail | GET /demands/{id} | demand | demand | 无 | 非本人手机号掩码；404 覆盖"不存在/不可见" |
| dock-detail（成果详情） | fetchAchievementDetail | GET /achievements/{id} | achievement | achievement+inventor+media | 无 | 完成人列表结构化；专利区块降级可用 |
| dock-detail（发起意向） | createCooperation | POST /cooperations | cooperation | cooperation_intent, cooperation_event | 无 | 对自己内容 400；重复意向 409；成功落 event(created) |
| dock-detail（意向操作） | accept/reject/confirm/cancel/completeCooperation | POST /cooperations/{id}/* | cooperation | intent+event | 无 | 状态机非法流转全部 409；accept 触发竞对 auto_rejected |
| dock-detail（时间线） | fetchCooperationEvents | GET /cooperations/{id}/events | cooperation | cooperation_event | 无 | 事件正序完整；operator 仅角色 |
| post-demand（附件） | presignUpload / completeUpload | POST /uploads/presign, /uploads/{id}/complete | file | file_object | UploadProvider | complete 后 fileId 可被创建接口引用 |
| post-demand（发布/编辑/提交） | createDemand / updateDemand / submitDemand | POST/PATCH /demands, POST /demands/{id}/submit | demand | demand+关联 | 无 | 幂等键防双击；状态 draft→pending_review |
| post-result（附件） | 同上 | 同上 | file | file_object | UploadProvider | 同上 |
| post-result（发布/编辑/提交） | createAchievement / updateAchievement / submitAchievement | POST/PATCH /achievements, POST /achievements/{id}/submit | achievement | achievement+inventor+media+tag | 无 | 完成人结构化提交；owner 不可由前端指定 |
| post-result（专利挂接） | searchPatents / linkPatent / unlinkPatent | GET /patents, POST/DELETE /achievements/{id}/patents | patent | patent, achievement_patent | PatentProvider | 挂接幂等；Provider 停机时搜索退化为本地命中 |
| post-result（发起评估） | createEvaluationTask | POST /ai/evaluation-tasks | ai | ai_task, ai_evaluation | AiProvider | 202→轮询；正式模式无假分回退 |
| fee-detail（年费） | fetchPatentDetail | GET /patents/{id} | patent | patent | 无（本地费率规则） | 年费表与申请日推算结果与现 patent-fee.js 规则一致 |
| my-list（我的需求） | fetchMyDemands / cancelDemand / closeDemand | GET /me/demands, POST /demands/{id}/cancel|close | demand | demand | 无 | 状态过滤正确；matched 不可 cancel（409） |
| my-list（我的成果） | fetchMyAchievements / offlineAchievement | GET /me/achievements, POST /achievements/{id}/offline | achievement | achievement | 无 | 同上 |
| my-list（我的收藏） | fetchMyFavorites | GET /me/favorites | favorite | favorite+目标表 | 无 | 已下线目标带状态标注 |
| my-list（我的意向） | fetchMyCooperations | GET /me/cooperations | cooperation | cooperation_intent | 无 | initiator/target 视角过滤正确 |
| ai-eval-detail（评估结果） | fetchEvaluationTask / fetchAchievementEvaluations | GET /ai/evaluation-tasks/{taskId}, GET /achievements/{id}/evaluations | ai | ai_evaluation | 无 | 四维分+模型版本+inputDataVersion 展示 |
| 管理审核（一期工具） | — | GET /admin/*, POST /admin/{type}/{id}/approve|reject | admin | achievement/demand+audit_log | 无 | approve/reject 驱动状态机；驳回 reason 必填 |

**负责人列**：一期实际为"前端负责人 / 后端负责人 / 数据负责人"三个角色（姓名由项目组指派后补记于本表表头下方）：
- 前端负责人：页面与 API 函数列；
- 后端负责人：模块、表、外部依赖列；
- 数据负责人：种子数据与阶段 C 清洗。

## 3. 上级源码到位前：本地联调方案

### 3.1 环境

```text
微信开发者工具 ← HBuilderX 编译（本地宿主 + subpackages/tech-transfer）
LocalAdapter → http://127.0.0.1:8787（tech-transfer-service, AUTH_PROVIDER=mock）
MockIdentityProvider → 固定身份 dev-user-001（可切换 dev-user-002 模拟第二用户）
MySQL tech_transfer schema（种子数据：字典表 + 演示 3 需求 + 3 成果 + 223 条成果【阶段C后】）
```

### 3.2 双用户联调技巧

本地宿主 dev-home 提供"切换测试身份"开关（仅 local 构建可见）：切换即清会话重走 bootstrap，模拟 A 发起意向 / B 接受的完整双端流程。**该开关属于本地宿主文件，不进业务分包**（03 §3.1）。

### 3.3 本地联调必须验证的负向用例

| 用例 | 预期 |
|------|------|
| 未带 token 访问 /me | 401 TT_COMMON_40101 |
| A 用户 PATCH B 用户成果 | 403 TT_ACH_40301 |
| 请求体携带 ownerUserId=他人 | 字段被忽略，归属仍为当前用户 |
| published 成果执行 submit | 409 TT_ACH_40901 |
| 对自己成果发起意向 | 400 TT_COOP_40001 |
| 重复 X-Idempotency-Key 不同请求体 | 409 TT_IDEM_40901 |
| pageSize=100 | 400 TT_COMMON_40001（上限 50） |

## 4. 上级源码到位后：正式联调方案

```text
Ai南山小程序（含合并后的 subpackages/tech-transfer 分包）
AiNanshanAdapter → HTTPS → Ai南山 API 网关
    ├─ 网关验签/注入可信身份头 → tech-transfer-service (AUTH_PROVIDER=ainanshan)
    └─ AiNanshanIdentityProvider 解析网关身份头 → external_identity 映射
```

正式联调新增验证点（在 §5 检查项基础上）：

1. 网关路由 `/api/tech-transfer/v1/*` 全量透传（Header 不被网关剥离——重点验证 X-Request-ID / X-Idempotency-Key）；
2. 上级真实用户首登建档（isNewUser=true 一次性）后二次登录稳定命中同一 app_user；
3. 上级消息通道收到对接/审核通知（NotifyProvider 真实实现）；
4. 上级统一上传通道的 presign→complete 链路（UploadProvider 真实实现）；
5. 网关限流与科转通限流叠加后的行为（429 透传与 Retry-After）。

## 5. 切换检查项清单

### 5.1 LocalAdapter → AiNanshanAdapter

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 业务分包零改动 | git diff 确认 `subpackages/tech-transfer/` 无变更 |
| 2 | HostBridge.registerAdapter 由宿主调用 | 分包内无注册代码 |
| 3 | request 通道 | 抓包确认经网关域名、HTTPS、带 Authorization |
| 4 | 401 处理 | 网关 401 与科转通 401 均触发静默 bootstrap 重试 |
| 5 | navigate | 分包内无 `uni.switchTab`（上级 TabBar 路径不同）；统一走 HostBridge.navigate |
| 6 | showMessage / reportError | 接上级 Toast/埋点通道，无本地 console-only 残留 |

### 5.2 MockIdentityProvider → AiNanshanIdentityProvider

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 启动保护 | staging/production + AUTH_PROVIDER=mock 服务拒绝启动（02 §8.3） |
| 2 | issuer 值 | external_identity 落库 issuer=上级约定值（08 C-01 确认后） |
| 3 | tenant_id | 非 NULL；多租户场景按上级租户字段填充 |
| 4 | 首登幂等 | 并发首登不产生重复 app_user（唯一约束验证） |
| 5 | 机器标识隔离 | 任何页面/日志无 external_subject 显示为姓名 |
| 6 | displayName 空值 | 上级未提供姓名时页面显示"未填写" |

### 5.3 API_BASE 切换网关

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 构建保护 | staging/production + API_BASE 含 127.0.0.1/localhost 构建失败 |
| 2 | 路径一致性 | 网关域名 + /api/tech-transfer/v1 与本地路径逐字符一致 |
| 3 | 响应包 | 网关不二次包装响应体（保持 {code,message,data,requestId} 原样） |
| 4 | 错误码透传 | 网关自身错误（如 502）不覆盖科转通业务错误码 |

### 5.4 文件上传切换

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | presign 结构不变 | UploadPresignResult 字段在两种 Provider 下一致 |
| 2 | fileId 稳定 | complete 返回的 fileId 在成果/需求创建中可引用 |
| 3 | 回显 URL | 业务页图片经统一代理 URL 展示，不直连对象存储域名 |
| 4 | 类型/大小白名单 | 两种通道下校验一致（≤20MB + MIME 白名单） |

### 5.5 消息通知切换

| # | 检查项 | 通过标准 |
|---|--------|----------|
| 1 | 通知不丢 | NotifyProvider 失败时 notification 表留 pending/failed 记录可补偿 |
| 2 | 业务不回滚 | 通知失败不影响意向/审核主流程返回成功 |
| 3 | 上级通道 | 对接状态变化、审核结果均送达上级消息中心 |

## 6. 回归测试范围（切换后必跑）

| 层级 | 范围 | 依据 |
|------|------|------|
| P0 冒烟 | bootstrap→浏览列表→详情→发布→提交审核→审核→发布可见→发起意向→接受→确认→完成 | 主链路（§2 矩阵加粗链路） |
| P1 状态机 | 3 个状态机全部非法流转负向用例（06 §5.5 矩阵逐行） | 防越权改状态 |
| P1 权限 | §3.3 全部负向用例 + admin 接口非 admin 访问 | 防越权 |
| P2 幂等 | 全部写接口重复提交（同键同体/同键异体） | 防重复数据 |
| P2 降级 | AiProvider/PatentProvider 停机：AI 任务 failed、专利区块降级、详情主体可用 | 02 §10 |
| P2 分页 | pageSize 边界（1/50/51）、深翻页（page>total） | 06 §2.3 |
| P3 兼容 | 旧资本三接口 301 跳转（迁移期） | 06 §16 |

## 7. 阶段 A–E 实施顺序

### 阶段 A：架构冻结（当前已完成，本文档集即产出）

| 任务 | 产出 | 责任 |
|------|------|------|
| 源码盘点 | 01 | 架构 |
| 双宿主边界 + HostBridge 契约 | 02/03 + ADR-001 | 架构 |
| 身份协议 | ADR-002 + 02 §6 | 架构 + 后端 |
| 数据模型 | 05 | 后端 |
| OpenAPI 契约 | 06 + openapi.yaml | 后端 |
| 冻结评审 | 项目组过会，错误码/路径此后只增不改 | 全体 |

### 阶段 B：本地主链路（前端分包化 + 后端服务骨架）

顺序：① 分包迁移（03 §7 步骤 1–4）→ ② tech-transfer-service 骨架（identity+profile+file）→ ③ bootstrap/GET /me/PATCH /me/profile → ④ achievement+demand 全生命周期 + admin 审核 → ⑤ favorite + cooperation（含事件表）→ ⑥ capital 平移（切换新前缀）→ ⑦ §2 矩阵逐行联调 + §3.3 负向用例 → ⑧ mock-data.js / user.js 退役（03 §3.3）。

里程碑：**本地删除全部业务 Mock 后主链路全绿**。

### 阶段 C：数据与 AI

① 223 条成果数据获取与清洗（字段映射按 05 §12；完成人拆分；成熟度归一）→ ② 分类/标签字典定稿 → ③ 导入开发库 + FULLTEXT 调优 → ④ AiProvider 接入（评估+匹配，含 ai_model_version 登记）→ ⑤ PatentProvider 接入（检索+落库）→ ⑥ 年费规则服务端化迁移验证。

里程碑：**搜索/AI/专利均为真实数据与真实能力，模型版本与输入版本可追溯**。

### 阶段 D：上级系统集成

① 取得 Ai南山源码 → ② 按 03 §7 合并分包 → ③ AiNanshanAdapter 实现 → ④ 身份/网关/上传/消息四项切换（§5.1–5.5 逐项检查）→ ⑤ §6 回归全量 → ⑥ 旧资本接口下线。

里程碑：**staging 环境双宿主各自全绿，生产硬保护生效**。

### 阶段 E：安全与验收

① 权限矩阵测试（§3.3 + P1）→ ② 安全测试（注入/越权/敏感日志扫描，对照 01 §10 S1–S9 逐项确认修复）→ ③ 状态机测试 → ④ 压测（目标：50 并发在线，P95 < 800ms——按一期试点规模设定）→ ⑤ 监控接入（/health/ready + external_api_log 告警）→ ⑥ 回滚预案（分包回退 = 上级主包回退到上一发布分支；服务回退 = 上一镜像）→ ⑦ 试点用户培训与验收。

## 8. 缺陷记录口径

联调期缺陷按"页面/API 函数/接口码/错误码"四元组登记，禁止只写页面名（无法定位责任层）。错误码缺失时先补 06 错误码总表再修 bug——**契约先行**。

## 9. 环境保护断言的测试（对应 02 §8.3）

三组硬保护必须各有一条自动化测试：

1. `APP_ENV=production, HOST_MODE=local` → 构建脚本退出码非 0；
2. `APP_ENV=production, AUTH_PROVIDER=mock` → 服务工厂抛异常、端口未监听；
3. `APP_ENV=staging, API_BASE=http://127.0.0.1:8787` → 构建脚本退出码非 0。

测试随阶段 B 后端骨架一并落地（CI 中常驻）。
