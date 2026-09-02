# 04 · 后端领域设计（Backend Domain Design）

> 文档状态：基线版
> 服务名称：`tech-transfer-service`（模块化单体，见 ADR-003）
> 阅读前提：已读 `02-target-architecture.md`（模块依赖图 §7）与 ADR-002（身份模型）
> 本文范围：模块职责、实体、接口归属、权限/事务/降级边界。数据库字段级设计见 `05`，HTTP 契约见 `06` + `openapi.yaml`

---

## 1. 模块总览

15 个模块按依赖方向分三层。**依赖规则：上层可依赖下层，同层模块禁止互相依赖**（唯一例外：cooperation 编排 demand/achievement 的只读校验门面，属跨层向下调用）。

| 层 | 模块 | 一句话职责 |
|----|------|-----------|
| 基础层 | identity、file、audit | 不依赖任何业务模块的通用能力 |
| 领域层 | profile、organization、achievement、demand、favorite、cooperation、patent、capital | 业务事实的唯一拥有者 |
| 编排层 | search、ai、notification、admin | 组合多个领域模块或对接外部能力 |

```text
编排层：search  ai  notification  admin
          │      │
领域层：profile organization achievement demand favorite cooperation patent capital
          │      │            │         │
基础层：identity ──────────── file ── audit
```

与 02 §7 依赖图完全一致；任何新增依赖必须先更新 02 的图再落代码。

## 2. 技术形态

- **进程**：单一 Python Web 进程（一期沿用 Flask 技术栈起步，框架不是架构约束——模块边界与接口契约才是；若后续切换 FastAPI，本设计不变）。
- **分层**：`modules/<name>/{router.py, service.py, repository.py, schemas.py}`；router 只做参数校验与鉴权声明，service 承载业务规则与事务，repository 只碰 SQL。
- **跨模块调用**：只允许 import 对方 `service.py` 的门面函数；CI 静态扫描禁止跨模块 import repository/models（ADR-003 §5）。
- **配置**：环境变量（APP_ENV/HOST_MODE/AUTH_PROVIDER/API_BASE 等），启动期硬保护（02 §8.3）。

---

## 3. 基础层模块

### 3.1 identity —— 身份与用户

| 项 | 内容 |
|----|------|
| 职责 | 维护 `app_user`、`external_identity`、`user_role`；实现 `MockIdentityProvider` / `AiNanshanIdentityProvider`；签发与校验科转通侧会话凭证；提供 `POST /auth/bootstrap` 交换逻辑 |
| 核心实体 | app_user、external_identity、user_role |
| 对外接口 | `POST /auth/bootstrap`；向其他模块提供 `resolve_identity(token) -> IdentityContext` 门面 |
| 依赖模块 | 无（被全部模块依赖） |
| 权限边界 | 唯一有权读取/写入身份映射的模块；**不提供按 external_subject 查询用户资料的公开接口**（防枚举）；不持有业务资料（归 profile） |
| 事务边界 | bootstrap 首登"查或建"：单事务内 SELECT → INSERT，并发冲突由 `UNIQUE(issuer, tenant_id, external_subject)` 兜底，捕获 1062 后重查 |
| 失败/降级 | AiNanshan 验签失败 → 401 `TT_AUTH_40101`；上级网关不可达（本地模式不存在）不适用。MockProvider 在 staging/production **启动即失败**，无降级 |

### 3.2 file —— 文件对象

| 项 | 内容 |
|----|------|
| 职责 | 上传凭证签发（presign）、文件元数据登记（`file_object`）、下载授权。**不承载业务语义**（"成果附件"由 achievement 持关联，file 只管字节与元数据） |
| 核心实体 | file_object |
| 对外接口 | `POST /uploads/presign`、`POST /uploads/{uploadId}/complete`；`GET /files/{fileId}/url`（内部） |
| 依赖模块 | identity（记录上传者）；外部 UploadProvider |
| 权限边界 | 下载 URL 签发必须校验调用者对该文件业务关联的可见性（回调 achievement/demand 的可见性门面）；文件哈希与大小校验防伪造 complete |
| 事务边界 | presign 无事务；complete 单事务写 file_object 状态 `pending → uploaded` |
| 失败/降级 | 本地模式 UploadProvider = 本地磁盘目录 + 后端直传接口；正式模式 = 上级统一上传（规范待确认，见 08 C-04）。Provider 失败 → `TT_FILE_50301`，不阻断表单其他字段提交 |

### 3.3 audit —— 审计

| 项 | 内容 |
|----|------|
| 职责 | 记录管理操作、状态流转、敏感资料访问、外部 AI/专利调用日志（`audit_log`、`external_api_log`）；只写不改 |
| 核心实体 | audit_log、external_api_log |
| 对外接口 | `GET /admin/audit-logs`（admin 模块路由）；向其他模块提供 `record(actor, action, target, before, after)` 门面 |
| 依赖模块 | 无（操作者信息由调用方传入 IdentityContext 摘要） |
| 权限边界 | **操作者一律取自服务端 IdentityContext，不信任前端声明**；Token/密码字段进入审计前强制脱敏（见 05 §10） |
| 事务边界 | 审计写入与业务事务**同库不同策略**：关键状态流转（审核、对接状态）与业务同事务提交（保证不丢）；通知类/外部调用日志允许异步落盘，失败不回滚业务 |
| 失败/降级 | 审计落库失败：关键审计（同事务）→ 整个业务操作失败（宁可拒绝也不无审计放行）；非关键日志 → 进程内重试队列 + 告警 |

---

## 4. 领域层模块

### 4.1 profile —— 用户业务资料

| 项 | 内容 |
|----|------|
| 职责 | 维护 `user_profile`（姓名、手机、邮箱、身份类型、机构归属意愿）；提供"我的"页资料读写 |
| 核心实体 | user_profile |
| 对外接口 | `GET /me`、`PATCH /me/profile` |
| 依赖模块 | identity（校验当前用户、读取 displayName） |
| 权限边界 | 仅本人可读写；手机/邮箱变更记审计；**姓名空值由前端显示"未填写"，后端不做默认值填充**（ADR-002 规则 3） |
| 事务边界 | PATCH 单行更新 + 乐观锁（version 字段，见 06 §2.6） |
| 失败/降级 | 无外部依赖，不降级 |

### 4.2 organization —— 企业/机构

| 项 | 内容 |
|----|------|
| 职责 | 维护 `organization`（企业/机构主数据）；成果归属机构、需求发布方机构的唯一来源 |
| 核心实体 | organization |
| 对外接口 | 内部门面（按 ID/名称解析机构）；`GET /organizations`（admin/搜索用）；一期无公开管理接口 |
| 依赖模块 | identity（创建者） |
| 权限绑定 | 机构与用户的关系存 user_profile.org_id 与 achievement/demand.org_id；**一期不做"企业认证+成员绑定"体系**（见 08 C-05，若上级有企业体系再对接） |
| 事务边界 | 名称查重（唯一索引 org_name + 软删标志组合）后插入，单事务 |
| 失败/降级 | 无外部依赖 |

### 4.3 achievement —— 成果

| 项 | 内容 |
|----|------|
| 职责 | 成果全生命周期：草稿→提交→审核→发布→下线；成果与标签、分类、媒体附件、完成人、专利的关联；成果可见性与数据权限 |
| 核心实体 | achievement、achievement_category、achievement_tag、achievement_tag_relation、achievement_media |
| 对外接口 | `GET/POST /achievements`、`GET/PATCH /achievements/{id}`、`POST /achievements/{id}/submit|offline`、`GET /achievements/{id}/evaluations|patents` |
| 依赖模块 | identity、organization（归属）、inventor、file（媒体）、patent（专利关联，见 §4.4 归属说明）、audit |
| 权限边界 | 草稿/驳回仅 owner 可见；published 对全部登录用户可见；下线后列表不可见、已收藏者详情页可见但标注"已下线"；PATCH/submit/offline 仅 owner（或 admin 强制下线） |
| 事务边界 | 创建/更新含关联（tags、media、inventors）单事务批量重写（先删后插，靠事务保证原子）；submit 时乐观锁校验 status=draft/rejected |
| 失败/降级 | 无外部依赖。**owner 由 IdentityContext 注入，请求体中的 ownerUserId 字段即使传入也被忽略并告警** |

### 4.4 inventor —— 成果完成人

| 项 | 内容 |
|----|------|
| 职责 | `inventor`（完成人主数据：姓名、单位、类型）与 `achievement_inventor`（成果—完成人多对多，含排序与贡献角色） |
| 核心实体 | inventor、achievement_inventor |
| 对外接口 | 无独立路由，随 achievement 详情/创建一并读写 |
| 依赖模块 | achievement（被其拥有；本模块仅提供主数据复用：同名完成人按姓名+单位去重复用） |
| 权限边界 | 完成人不是登录用户，无自主权限；其姓名/单位为公开展示字段 |
| 事务边界 | 与 achievement 同事务 |
| 失败/降级 | **禁止"姓名1、姓名2、姓名3"三列设计**（数据教训：223 条成果的完成人需拆分为记录，见 05 §5） |

### 4.5 patent —— 专利

| 项 | 内容 |
|----|------|
| 职责 | `patent` 主数据（公开号、名称、申请日、法律状态、年费计算）；`achievement_patent` 成果—专利关联；对接外部专利 SaaS（PatentProvider）检索与详情 |
| 核心实体 | patent、achievement_patent |
| 对外接口 | `GET /patents`（检索）、`GET /patents/{id}`、`GET/POST/DELETE /achievements/{id}/patents`；年费规则服务化（沿用现 `patent-fee.js` 真实费率表与 `calcLatestPayDate` 算法，迁到服务端） |
| 依赖模块 | identity（关联操作者）、achievement（关联校验：仅成果 owner 可挂/摘专利）、外部 PatentProvider |
| 权限边界 | 挂接/解除关联仅成果 owner；专利公开数据全部登录用户可查 |
| 事务边界 | 关联操作单事务（防重复挂接：唯一约束 achievement_id+patent_id） |
| 失败/降级 | **专利是可降级能力**（02 §10）：SaaS 超时/失败 → 返回空列表 + `TT_PATENT_50301`，成果详情主体照常返回；调用全过程写 external_api_log |

### 4.6 demand —— 需求

| 项 | 内容 |
|----|------|
| 职责 | 需求全生命周期：draft→pending_review→published→matched→closed，含 rejected、cancelled；需求分类、标签、附件 |
| 核心实体 | demand、demand_category、demand_tag、demand_tag_relation、demand_attachment |
| 对外接口 | `GET/POST /demands`、`GET/PATCH /demands/{id}`、`POST /demands/{id}/submit|cancel|close`、`GET /demands/{id}/matches` |
| 依赖模块 | identity、organization、file、audit |
| 权限边界 | 同 achievement（draft 仅本人可见；published 全员可见）；cancel/close 仅 owner 且状态合法 |
| 事务边界 | 同 achievement（关联批量重写 + 状态机乐观锁） |
| 失败/降级 | 无外部依赖；owner 服务端注入 |

### 4.7 favorite —— 收藏

| 项 | 内容 |
|----|------|
| 职责 | `favorite`：用户对 achievement/demand 的收藏（target_type + target_id 多态） |
| 核心实体 | favorite |
| 对外接口 | `PUT/DELETE /favorites/{targetType}/{targetId}`、`GET /me/favorites` |
| 依赖模块 | identity；读时校验目标存在性与可见性（调 achievement/demand 门面） |
| 权限边界 | 仅本人可读写自己的收藏 |
| 事务边界 | PUT 幂等（唯一约束 user_id+target_type+target_id，重复 PUT 直接 200 返回既有记录） |
| 失败/降级 | 目标不存在 → `TT_FAVORITE_40401`；目标已下线 → 允许保留收藏但列表标注状态 |

### 4.8 cooperation —— 对接意向与事件

| 项 | 内容 |
|----|------|
| 职责 | `cooperation_intent`（需求方 ↔ 成果方对接意向，状态机见 06 §5）与 `cooperation_event`（每次状态流转的事件记录，含操作者、时间、备注）；意向去重（同一用户对同一目标仅一条活跃意向）；接受后自动拒绝同目标其他 pending 意向（沿用现演示逻辑 `user.js` 的竞对自动拒绝语义，服务端实现） |
| 核心实体 | cooperation_intent、cooperation_event |
| 对外接口 | `POST /cooperations`、`GET /cooperations/{id}`、`POST /cooperations/{id}/accept|reject|confirm|cancel|complete`、`GET /cooperations/{id}/events`、`GET /me/cooperations` |
| 依赖模块 | identity（双方身份）、demand（目标需求状态校验）、achievement（目标成果状态校验）、notification（状态变化通知）、audit |
| 权限边界 | **四方视角权限**：意向发起人、目标发布人、admin 可见；accept/reject 仅目标发布人；confirm/cancel/complete 按状态机 + 双方角色矩阵（见 06 §5.5 表）；**发起人不能对自己发布的成果/需求发起对接**（服务端校验，替代现前端校验） |
| 事务边界 | 状态流转单事务：UPDATE intent（乐观锁 + 状态机校验）→ INSERT event → 触发通知入队 → 提交；竞对自动拒绝在同一事务内批量 UPDATE + 逐条 INSERT event |
| 失败/降级 | 目标已下线/关闭 → `TT_COOP_40901`；通知失败不回滚（进 notification 补偿表）；**事件表是状态事实源，意向表当前状态仅为投影** |

### 4.9 capital —— 资本资源

| 项 | 内容 |
|----|------|
| 职责 | 承接现有 Flask 三表只读域：概念验证/中试平台（platform_base）、投资机构（featured_invest_org）、银行融资机构（ip_service_org）；Logo 代理 |
| 核心实体 | capital_platform（含 platform_type=poc/pilot）、capital_organization（invest/financial/service 三类，一表+kind 或三表并集视图，见 05 §8） |
| 对外接口 | `GET /capital/platforms`、`GET /capital/platforms/{id}`、`GET /capital/investment-organizations`、`GET /capital/financial-organizations`、`GET /capital/service-organizations`；Logo 走 `GET /files/{fileId}/url` 统一代理 |
| 依赖模块 | file（Logo）；**不依赖 identity/favorite（公开只读域，可匿名访问）** |
| 权限边界 | 公开只读（现状即无鉴权，公开数据可接受）；后台数据更新走运维脚本（爬虫→import_data.py），一期不做管理界面 |
| 事务边界 | 纯读 |
| 失败/降级 | 现有 `/api/platform-base` 等三接口**平移**到新前缀下并统一响应包（`msg`→`message`，见 01 §6 备注）；Logo 回源失败返回占位图 URL；迁移期旧路径保留 301（见 06 §16） |

---

## 5. 编排层模块

### 5.1 search —— 统一搜索

| 项 | 内容 |
|----|------|
| 职责 | `GET /search`：跨成果/需求的关键词 + 分类 + 成熟度筛选，合并分页返回；一期实现 = MySQL FULLTEXT/LIKE + 标签过滤（223 条数据量足够，ES 触发条件见 02 §9） |
| 核心实体 | 无自有表（读 achievement/demand）；搜索历史留在前端本地（纯 UI 状态，`ns_search_history_*` 键保留） |
| 对外接口 | `GET /search?q=&type=&category=&maturity=&page=&pageSize=` |
| 依赖模块 | achievement、demand（只读门面） |
| 权限边界 | 结果集只含对当前用户可见的记录（published + 本人草稿可选参数 includeMine） |
| 事务边界 | 纯读 |
| 失败/降级 | 无外部依赖 |

### 5.2 ai —— AI 评估与匹配

| 项 | 内容 |
|----|------|
| 职责 | AI 任务编排：`ai_task`（任务队列：queued→running→succeeded/failed）+ `ai_evaluation`（评估结果：四维评分，对齐现 `ai-eval.js` 的技术特点/应用范围/成熟度/合作可行性模型）+ `ai_match_result`（需求—成果匹配结果）+ `ai_model_version`（模型与输入数据版本登记）；替代现前端哈希假分（`buildFallbackEval`）与话术假答（`buildDemoReply`） |
| 核心实体 | ai_task、ai_evaluation、ai_match_result、ai_model_version |
| 对外接口 | `POST /ai/match-tasks`、`GET /ai/match-tasks/{taskId}`、`POST /ai/evaluation-tasks`、`GET /ai/evaluation-tasks/{taskId}` |
| 依赖模块 | achievement、demand（取输入数据快照）、identity、audit；外部 AiProvider |
| 权限边界 | 创建任务需登录；任务与结果仅创建者（评估详情对成果详情页只读公开——评估是成果的公开属性，同现 `ai-eval-detail` 从成果进入的逻辑）；**模型 Key 只存服务端配置，前端不可见** |
| 事务边界 | 创建任务单事务（INSERT ai_task queued + 输入快照 JSON）；执行为异步：进程内工作线程拉取 queued 任务 → 调 AiProvider → 单事务写结果 + 置 succeeded/failed；**任务不允许无限 running**（超时阈值置 failed，见 02 §10） |
| 失败/降级 | AiProvider 失败 → 任务 failed + `TT_AI_50201` + 可重试（重新创建任务）；**一期允许的降级**：若 AiProvider 未签约，evaluation-tasks 返回 `TT_AI_50301`（服务未配置），**禁止**退回前端假分——宁可不可用，不给假数据（区别于演示期） |

### 5.3 notification —— 通知

| 项 | 内容 |
|----|------|
| 职责 | 站内通知 `notification` 的生成与已读管理；对接上级消息通道（NotifyProvider，规范待上级确认，见 08 C-06） |
| 核心实体 | notification（含状态 pending→sent/read、补偿重试计数） |
| 对外接口 | 内部门面 `notify(user, template, context)`；通知读取接口（`GET /me/notifications`、`PUT /me/notifications/{id}/read`）为**二期范围**，一期 notification 表只写不读——通知一律经 NotifyProvider 推送到上级消息中心；二期开放读取时在 06 与 openapi.yaml 补契约 |
| 依赖模块 | identity；被 cooperation/admin/ai 调用 |
| 权限边界 | 仅收件人可读/标记已读 |
| 事务边界 | **通知写入与业务事务解耦**：业务事务内只写 notification 行（pending），提交后进程内尝试发送；失败递增 retry_count，定时器重试，超过 5 次标记 failed + 告警。**业务事务永不因通知失败回滚**（02 §7 规则） |
| 失败/降级 | 上级消息通道不可用 → 降级仅站内信；全部失败 → 补偿表，不阻断主链路 |

### 5.4 admin —— 管理审核

| 项 | 内容 |
|----|------|
| 职责 | 成果/需求审核队列与通过/驳回；审计日志查询；admin 角色判定的唯一入口 |
| 核心实体 | 无自有表（操作 achievement/demand 状态 + 写 audit_log） |
| 对外接口 | `GET /admin/achievements/review-queue`、`POST /admin/achievements/{id}/approve|reject`、`GET /admin/demands/review-queue`、`POST /admin/demands/{id}/approve|reject`、`GET /admin/audit-logs` |
| 依赖模块 | achievement、demand、audit、notification（审核结果通知提交人） |
| 权限边界 | 仅 `admin` 角色（user_role 表）；一期 admin 角色由 DBA 种子数据分配（本地 dev-user-001 可预置 admin 便于联调）；approve/reject 必须带 reason（驳回时必填） |
| 事务边界 | 审核单事务：校验 pending_review → 置 published/rejected + 写审计 + 通知入队 |
| 失败/降级 | 无外部依赖 |

---

## 6. 模块 × 状态机 × 事务汇总表

| 模块 | 状态机归属 | 状态流转事务 | 外部依赖 | 降级等级 |
|------|-----------|-------------|----------|----------|
| achievement | draft→pending_review→published→offline；pending_review→rejected | 单事务+乐观锁 | 无 | 不可降级 |
| demand | draft→pending_review→published→matched→closed；rejected；cancelled | 单事务+乐观锁 | 无 | 不可降级 |
| cooperation | pending→accepted→confirmed→completed；rejected；cancelled | 单事务（含事件+竞对拒绝） | 无 | 不可降级 |
| ai_task | queued→running→succeeded/failed | 异步两段事务 | AiProvider | 可降级 |
| patent | 无（关联操作幂等） | 单事务 | PatentProvider | 可降级 |
| notification | pending→sent→read | 补偿事务 | NotifyProvider | 可降级 |
| file | pending→uploaded | 单事务 | UploadProvider | 可降级 |
| capital | 无（只读） | — | Logo 回源 | 可降级 |

## 7. 现有代码的复用与退役对照

| 现有实现 | 去向 |
|----------|------|
| `tools/api-server/app.py` 三表查询 + 分页/关键词逻辑 | 平移入 capital 模块 repository；响应包改 `{code,message,data}`；异常不再泄漏 str(e) |
| `app.py` `/api/file/<id>` 代理 + 磁盘缓存 | 收编入 file 模块 Logo 代理；增加 referer/频控（修 S9） |
| `patent-fee.js` 费率表 + `calcLatestPayDate` + `getAnnualFees` | **真实业务规则，迁为 patent 模块服务端实现**（前端仅展示） |
| `ai-eval.js` 四维评分模型定义 | 评估维度结构沿用，评分计算移服务端并记录模型版本 |
| `user.js` 意向状态机 + 竞对自动拒绝 | 状态语义移入 cooperation 模块（前端状态机文案保留） |
| `ai-chat.js buildDemoReply` / `buildFallbackEval` 哈希假分 | **退役**，正式模式禁止假数据 |
| `mock-data.js` / `capital-demo-data.js` | 阶段 B 结束后退役（演示模式开关仅保留到阶段 C 前，见 03 §3.3） |
| `search.js` 客户端过滤 | 退役（改服务端搜索；搜索历史仍留前端本地） |
| `user.js` 本地账号/密码/会话 | **立即退役**（安全 S1/S2/S3，见 01 §10） |

## 8. 与其他文档的对应

- 表结构字段级设计：`05-data-model-design.md`
- HTTP 接口/错误码/幂等/状态机细节：`06-api-design.md` + `openapi.yaml`
- 联调矩阵与回归：`07-integration-and-testing.md`
