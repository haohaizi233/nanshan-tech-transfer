# 南山科转通 · API 接口文档

> 自动生成自源码：`tech-transfer-service/routes/*.py`（147 个接口）+ `nanshan-ai-agent/app/main.py`（3 个接口），共 **150 个接口**。
> 生成日期：2026-10-19

---

## 1. 通用约定

### 1.1 服务地址与前缀

| 服务 | 前缀 | 说明 |
|---|---|---|
| tech-transfer-service（主后端） | `/api/tech-transfer/v1` | 业务 API（另有 legacy 路径 `/api/...` 见 §14） |
| nanshan-ai-agent（AI Agent） | `/api/ai`（另有 `/health`） | 独立 AI 服务，由主后端转发调用 |

### 1.2 通用响应格式

成功响应（`core/response.py::success`）：

```json
{ "code": 0, "message": "ok", "data": { ... } }
```

错误响应（`core/errors.py::BizError`，走全局异常处理器）：

```json
{ "code": "TT_XXX_XXXXX", "message": "错误描述", "details": { ... } }
```

HTTP 状态码语义保持正确（400 参数错误 / 401 未认证 / 403 无权限 / 404 不存在 / 409 状态机冲突 / 429 限流 / 5xx 服务异常）。

### 1.3 认证方式

请求头 `Authorization: Bearer <accessToken>`（JWT）。认证级别说明：

| 标记 | 依赖 | 含义 |
|---|---|---|
| 公开 | 无 | 无需登录 |
| 可选登录 | `optional_identity` | 游客可访问；带 token 时返回个性化数据（如收藏状态） |
| 需登录 | `identity` | 必须携带有效 Bearer JWT |
| 需登录·管理员 | `admin_identity` | 登录 + `user_role` 表实时校验 `admin` 角色（403 TT_ADMIN_40301） |
| 需登录·后台 | `backend_identity` | 平台管理员（全平台）或机构管理员（限本机构范围） |
| 需登录·机构管理员 | `org_admin_identity` | 机构管理员（`organization_admin` 记录实时校验） |

### 1.4 通用请求参数

- **分页**：`page`（默认 1）、`pageSize`（默认 20）、`keyword`（部分列表接口）
- **乐观锁**：所有状态流转接口请求体必须携带 `version: int (≥1)`，版本不匹配返回 409
- **幂等**：创建类接口支持请求头 `X-Idempotency-Key`（TTL 10 分钟，重复请求回放缓存响应）
- **限流**：登录/注册/refresh/AI/上传等接口内置 IP/用户级限流，超限返回 429（TT_COMMON_42901）

---

## 2. 目录（按模块）

| 模块 | 章节 | 接口数 |
|---|---|---|
| 认证 | §3 | 5 |
| 用户中心（我） | §4 | 7 |
| 成果 | §5 | 8 |
| 需求 | §6 | 7 |
| 合作对接 | §7 | 8 |
| 收藏 | §8 | 2 |
| 搜索 | §9 | 1 |
| AI 助手 | §10 | 7 |
| 通知 | §11 | 5 |
| 专利 | §12 | 8 |
| 文件 | §13 | 5 |
| 机构（统一机构库） | §14 | 2 |
| 机构注册 | §15 | 1 |
| 资本对接（legacy） | §16 | 3 |
| 管理后台·内容审核 | §17 | 31 |
| 管理后台·平台运营 | §18 | 23 |
| 会员/组织认证 | §19 | 24 |
| AI Agent 服务（独立） | §20 | 3 |
| **合计** | | **150** |

---

## 3. 认证（auth）— 5 个接口

Base：`/api/tech-transfer/v1/auth`（全部公开，自带限流）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 1 | POST | `/auth/login` | 登录（小程序传 phone / 后台传 username） | 公开 | Body：`username` 或 `phone`（二选一）、`password`；IP 限流 20 次/60s，失败计账号限流 5 次/300s | `data`：用户信息 + accessToken/refreshToken 会话 |
| 2 | POST | `/auth/register` | 注册（username 用户名模式 / phone 手机号模式） | 公开 | Body：`username` 或 `phone`、`password`、`displayName?`、`email?`；IP 注册限频 | username 模式返回注册结果（再登录）；phone 模式直接签发会话（免登录） |
| 3 | POST | `/auth/bootstrap` | 宿主身份凭证引导会话 | 公开 | Body：`hostCredential`（必填，宿主签发的身份凭证） | `data`：引导会话（用户 + token） |
| 4 | POST | `/auth/refresh` | 刷新 accessToken | 公开 | Body：`refreshToken`（必填）；IP 限流 10 次/60s | `data`：新会话 token |
| 5 | POST | `/auth/logout` | 退出登录（吊销 refreshToken） | 公开 | Body：`refreshToken`（必填）；与 /refresh 同限流桶 | `data`：登出结果 |

---

## 4. 用户中心（me）— 7 个接口

Base：`/api/tech-transfer/v1/me`（全部需登录）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 6 | GET | `/me` | 获取当前用户资料 | 需登录 | — | `data`：个人资料 |
| 7 | PATCH | `/me/profile` | 更新个人资料 | 需登录 | Body：`version`（必填）、`displayName`、`userType`（enterprise_staff/researcher/investor/service_org/other）、`subjectType`、`phone`、`email`、`wechat`、`companyText`、`orgTitle`、`businessCapabilities[]` | `data`：更新后资料 |
| 8 | POST | `/me/password` | 修改密码 | 需登录 | Body：`currentPassword`、`newPassword`（均必填） | `data`：空，message=“密码已更新” |
| 9 | GET | `/me/demands` | 我的需求列表 | 需登录 | Query：分页 + 状态等过滤 | `data`：需求列表 |
| 10 | GET | `/me/achievements` | 我的成果列表 | 需登录 | Query：分页 + 状态等过滤 | `data`：成果列表 |
| 11 | GET | `/me/favorites` | 我的收藏列表 | 需登录 | Query：分页等 | `data`：收藏列表 |
| 12 | GET | `/me/cooperations` | 我的对接意向列表 | 需登录 | Query：分页等 | `data`：意向列表 |

---

## 5. 成果（achievement）— 8 个接口

Base：`/api/tech-transfer/v1`

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 13 | GET | `/achievements` | 成果列表（仅 published） | 可选登录 | Query：分页、分类/成熟度/关键词等过滤 | `data`：分页成果列表（登录时含个性化字段） |
| 14 | GET | `/achievements/categories` | 成果分类字典 | 可选登录 | — | `data`：分类字典 |
| 15 | GET | `/achievements/industries` | 成果产业目录 | 可选登录 | — | `data`：产业目录 |
| 16 | GET | `/achievements/{ach_id}` | 成果详情（防探测：非 published 且非 owner 返回 null） | 可选登录 | Path：`ach_id` | `data`：成果详情或 null（message=“成果不存在或未发布”） |
| 17 | POST | `/achievements` | 创建成果（draft，201） | 需登录 | Body（AchievementCreateRequest）：`title`（必填，≤200）、`titleEn`、`maturityLevel`（01_idea~06_mass_done）、`pricingMode`、`techIntro`、`techRoute`、`maturityDesc`、`sourceOrgName`、`achievementKind`、`applicationFields[]`、`innovationPoints[]`、`priceMinWan`、`priceMaxWan`、`categoryId`、`orgId`、`saveAction`（draft/submit/publish）、联系人字段、`inventorRefs[]`、`sections[]`、`patents[]`、媒体等；支持 `X-Idempotency-Key` | `data`：成果详情；message=“创建成功” |
| 18 | PATCH | `/achievements/{ach_id}` | 编辑成果（owner + 乐观锁 + draft/rejected 状态） | 需登录 | Path：`ach_id`；Body（AchievementUpdateRequest）：`version`（必填）+ 同上可编辑字段 | `data`：更新后成果详情 |
| 19 | POST | `/achievements/{ach_id}/submit` | 提交审核（draft/rejected/offline → pending_review） | 需登录 | Path：`ach_id`；Body：`version`（必填，乐观锁） | `data`：流转后成果状态 |
| 20 | POST | `/achievements/{ach_id}/offline` | 下线成果（published → offline） | 需登录 | Path：`ach_id`；Body：`version`（必填）、`reason?`、`reasonCode?` | `data`：流转后成果状态 |

---

## 6. 需求（demand）— 7 个接口

Base：`/api/tech-transfer/v1`

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 21 | GET | `/demands` | 需求列表 | 可选登录 | Query：分页、分类/区域/合作方式/关键词等过滤 | `data`：分页需求列表 |
| 22 | POST | `/demands` | 创建需求（201） | 需登录 | Body（DemandCreateRequest）：`title`（必填，≤200）、`description`（必填）、`region`、`deadlineDesc`、联系人字段、`coopMode[]`、`budgetMinWan`、`budgetMaxWan`、`budgetNegotiable`、`expectDeadline`（YYYY-MM-DD）、`categoryId`/`categoryName`、`orgId`/`orgName`/`orgIntro`、`saveAction`、`tags[]`、`attachments[]`；支持 `X-Idempotency-Key` | `data`：需求详情；message=“创建成功” |
| 23 | GET | `/demands/{demand_id}` | 需求详情 | 可选登录 | Path：`demand_id` | `data`：需求详情 |
| 24 | PATCH | `/demands/{demand_id}` | 编辑需求（owner + 乐观锁） | 需登录 | Path：`demand_id`；Body（DemandUpdateRequest）：`version`（必填）+ 可编辑字段同上 | `data`：更新后需求详情 |
| 25 | POST | `/demands/{demand_id}/submit` | 提交审核 | 需登录 | Path：`demand_id`；Body：`version`（必填） | `data`：流转后状态 |
| 26 | POST | `/demands/{demand_id}/cancel` | 取消需求 | 需登录 | Path：`demand_id`；Body：`version`（必填）、`reason?`、`reasonCode?`、`reasonNote?` | `data`：流转后状态 |
| 27 | POST | `/demands/{demand_id}/close` | 关闭需求 | 需登录 | Path：`demand_id`；Body：`version`（必填）、`reason?`、`reasonCode?`、`reasonNote?` | `data`：流转后状态 |

---

## 7. 合作对接（cooperation）— 8 个接口

Base：`/api/tech-transfer/v1`（全部需登录；状态机操作均需 `version` 乐观锁）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 28 | POST | `/cooperations` | 创建对接意向（201） | 需登录 | Body：`targetType`（achievement/demand，必填）、`targetId`（必填）、`intentType?`、`message?`、`contactShareConsent`（必填，须为 true）；支持 `X-Idempotency-Key` | `data`：意向详情；message=“意向已创建” |
| 29 | GET | `/cooperations/{intent_id}` | 意向详情 | 需登录 | Path：`intent_id` | `data`：意向详情 |
| 30 | POST | `/cooperations/{intent_id}/accept` | 接受意向 | 需登录 | Path：`intent_id`；Body：`version` | `data`：流转后状态 |
| 31 | POST | `/cooperations/{intent_id}/reject` | 拒绝意向 | 需登录 | Path：`intent_id`；Body：`version`、`reason?` | `data`：流转后状态 |
| 32 | POST | `/cooperations/{intent_id}/confirm` | 确认意向 | 需登录 | Path：`intent_id`；Body：`version` | `data`：流转后状态 |
| 33 | POST | `/cooperations/{intent_id}/cancel` | 取消意向 | 需登录 | Path：`intent_id`；Body：`version`、`reason?` | `data`：流转后状态 |
| 34 | POST | `/cooperations/{intent_id}/complete` | 完成对接 | 需登录 | Path：`intent_id`；Body：`version`、`remark?`、`outcome?` | `data`：流转后状态 |
| 35 | GET | `/cooperations/{intent_id}/events` | 意向事件时间线 | 需登录 | Path：`intent_id`；Query：分页 | `data`：事件列表 |

---

## 8. 收藏（favorite）— 2 个接口

Base：`/api/tech-transfer/v1`（全部需登录，幂等操作）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 36 | PUT | `/favorites/{target_type}/{target_id}` | 添加收藏（幂等） | 需登录 | Path：`target_type`（如 achievement/demand）、`target_id` | `data`：收藏结果 |
| 37 | DELETE | `/favorites/{target_type}/{target_id}` | 取消收藏（幂等） | 需登录 | Path：`target_type`、`target_id` | `data`：null；message=“已取消收藏” |

---

## 9. 搜索（search）— 1 个接口

Base：`/api/tech-transfer/v1`

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 38 | GET | `/search` | 统一搜索（achievement/demand/all 双类型聚合） | 需登录 | Query：`q`（必填，≤64）、`type`（achievement/demand/all，默认 all）、`page`、`pageSize`、`categoryCode?`、`maturityLevel?` | `data`：聚合搜索结果（成果/需求卡片） |

---

## 10. AI 助手（ai）— 7 个接口

Base：`/api/tech-transfer/v1`（全部需登录；整组受 `AI_FEATURE_ENABLED` 开关控制，关闭时返回 503 “该功能即将开放”）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 39 | POST | `/ai/evaluation-tasks` | 创建成果评估异步任务（202） | 需登录 | Body：`achievementId`（必填正整数）；`X-Idempotency-Key` 幂等去重 | 202：`data`=任务对象（message=“任务已受理”）；进行中的重复请求返回 200（message=“任务进行中”） |
| 40 | GET | `/ai/evaluation-tasks/{task_id}` | 查询评估任务状态/结果 | 需登录 | Path：`task_id` | `data`：任务详情（状态/评估报告） |
| 41 | POST | `/ai/chat` | AI 自然语言对话（转发 nanshan-ai-agent） | 需登录 | Body：`message`（必填非空）、`turnId?`（客户端幂等轮次 ID，≤64，`^[A-Za-z0-9][A-Za-z0-9._:-]{0,63}$`）；用户频控 30 次/5min | `data`：`{success, intent, message, data:[成果\|需求卡片]}`；带 turnId 时支持断线续查：生成中返回 202 `{turnId, status:"running"}`，完成后重复请求直接回放结果 |
| 42 | POST | `/ai/match` | 需求-成果智能匹配（同步） | 需登录 | Body：`demandId`（必填正整数）；频控 10 次/5min；仅需求所有者且需求状态为 published/matched 可发起 | `data`：`{demandId, demandTitle, intent, agentMessage, cards:[成果卡+matchReason 匹配理由]}`；message 含命中数量 |
| 43 | GET | `/ai/chat/messages` | 获取我的聊天记录（切页/重登后历史不丢） | 需登录 | — | `data`：`{messages:[...]}` |
| 44 | GET | `/ai/chat/turns/{turn_id}` | 查询单个问答轮次 | 需登录 | Path：`turn_id`（字符串） | `data`：轮次详情（状态/回复/卡片）；不存在 404（TT_AI_40401） |
| 45 | DELETE | `/ai/chat/messages` | 清空我的聊天记录 | 需登录 | — | `data`：`{deleted: n}`；message=“聊天记录已清空” |

---

## 11. 通知（notification）— 5 个接口

Base：`/api/tech-transfer/v1/me/notifications`（全部需登录）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 46 | GET | `/me/notifications/summary` | 通知角标汇总（未读数） | 需登录 | — | `data`：未读汇总 |
| 47 | GET | `/me/notifications` | 通知列表 | 需登录 | Query：分页、`category?` 等过滤 | `data`：分页通知列表 |
| 48 | POST | `/me/notifications/read` | 按分类标记已读 | 需登录 | Body：`category?`（如 cooperation，缺省为全部分类） | `data`：标记结果 |
| 49 | POST | `/me/notifications/{notification_id}/read` | 标记单条已读 | 需登录 | Path：`notification_id` | `data`：标记结果 |
| 50 | POST | `/me/notifications/read-all` | 全部标记已读 | 需登录 | — | `data`：标记结果 |

---

## 12. 专利（patents）— 8 个接口

Base：`/api/tech-transfer/v1`（全部需登录；上游 PDF/源站地址不出现在 JSON 响应中）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 51 | GET | `/patents` | 专利检索 | 需登录 | Query：`keyword`、`assignee?`、`page`、`pageSize` | `data`：分页专利列表 |
| 52 | GET | `/patents/search-history` | 获取搜索历史 | 需登录 | Query：`mode`（keyword/assignee，默认 keyword） | `data`：历史记录列表 |
| 53 | POST | `/patents/search-history` | 记录一条搜索历史 | 需登录 | Body：`mode`（必填，keyword/assignee）、`keyword`（必填，≤128） | `data`：记录结果 |
| 54 | DELETE | `/patents/search-history` | 清空搜索历史 | 需登录 | Query：`mode`（默认 keyword） | `data`：清空结果；message=“搜索记录已清空” |
| 55 | GET | `/patents/{publication_no}/pdf` | 下载/在线阅读专利 PDF（流式） | 需登录 | Path：`publication_no`（公开号） | `StreamingResponse`，`application/pdf`，inline，Cache-Control: private, max-age=3600；无 PDF 抛 404 |
| 56 | GET | `/patents/{publication_no}/pdf/pages` | PDF 分页元信息 | 需登录 | Path：`publication_no` | `data`：页数等元信息 |
| 57 | GET | `/patents/{publication_no}/pdf/pages/{page}` | 渲染 PDF 单页为 PNG | 需登录 | Path：`publication_no`、`page`（页码） | `image/png` 二进制（Cache-Control: private, max-age=3600） |
| 58 | GET | `/patents/{publication_no}` | 专利详情 | 需登录 | Path：`publication_no`；Query：`language?`（≤8 字符） | `data`：专利详情 |

---

## 13. 文件（file）— 5 个接口

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 59 | GET | `/api/file/{file_id}` | 【legacy 已废弃】文件代理读取 | 公开 | Path：`file_id` | `FileResponse`（媒体文件）；响应带 `Deprecation: true` 头，新地址为 `/api/tech-transfer/v1/files/{file_id}` |
| 60 | POST | `/api/tech-transfer/v1/files` | 上传成果/需求媒体（201） | 需登录 | Body（multipart）：`file`（必填）；Content-Type 白名单（图片/PDF/Office/音视频/文本）；大小 ≤ MAX_UPLOAD_BYTES；频控 20 次/5min + 日配额 50 个/天 | `data`：`{fileId, ...}`；message=“上传成功” |
| 61 | GET | `/api/tech-transfer/v1/files/{file_id}` | 读取已授权上传文件（支持缩略图） | 可选登录 | Path：`file_id`；Query：`variant?`（仅支持 `thumbnail`）、`file_token?`（5 分钟 HMAC 短时效 token）、`access_token?`（旧版兼容，已废弃）；admin 实时校验可看导入媒体 | `FileResponse` inline（Cache-Control: no-store）；非本人/无权限 403 |
| 62 | DELETE | `/api/tech-transfer/v1/files/{file_id}` | 删除未被引用的上传文件 | 需登录 | Path：`file_id`（须为本人文件且未被引用） | `data`：null；message=“已删除” |
| 63 | POST | `/api/tech-transfer/v1/files/{file_id}/token` | 生成短时效文件访问 token（L3） | 需登录 | Path：`file_id` | `data`：`{fileToken, expiresIn: 300}`（HMAC 签名，5 分钟有效） |

---

## 14. 机构（institution，统一机构库）— 2 个接口

Base：`/api/tech-transfer/v1`（公开数据，无需登录）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 64 | GET | `/institutions` | 机构列表（按 kind 统一） | 公开 | Query：`page`、`pageSize`、`keyword?`、`kind?`（platform/invest/service/university/institute/enterprise/other/all，默认 all）、`type?`（kind=platform 时为 poc/pilot/other/all） | `data`：分页机构列表 |
| 65 | GET | `/institutions/{inst_id}` | 机构详情 | 公开 | Path：`inst_id` | `data`：机构详情；不存在/已下架返回 null（message=“机构不存在或已下架”） |

---

## 15. 机构注册（institution-registrations）— 1 个接口

Base：`/api/tech-transfer/v1`

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 66 | POST | `/institution-registrations` | 公开提交机构注册申请（201） | 公开 | Body：`kind`（必填：university/institute/enterprise/invest/service/other）、`name`（必填，≤128）、`contactName`（必填，≤64）、`contactPhone`、`username`、`password`（均必填）、`region?`、`creditCode?`、`email?`、`intro?`；按 IP 注册限频 | 201：`data`=申请单；message=“机构注册申请已提交，请等待平台审核” |

---

## 16. 资本对接（capital，legacy 兼容）— 3 个接口

> DEPRECATED（2026-09-08 起）：请改用 §14 统一机构接口 `/api/tech-transfer/v1/institutions`。以下路径响应带 `Deprecation: true` 与 `Link: </api/tech-transfer/v1/institutions>; rel="successor-version"` 头，格式零差异。

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 67 | GET | `/api/platform-base` | 平台载体列表（legacy） | 公开 | Query：`page`、`pageSize`、`keyword?`、`type?`（poc/pilot/other/all） | `data`：分页平台列表 |
| 68 | GET | `/api/invest-orgs` | 投资机构列表（legacy） | 公开 | Query：`page`、`pageSize`、`keyword?` | `data`：分页机构列表 |
| 69 | GET | `/api/service-orgs` | 服务机构/银行列表（legacy） | 公开 | Query：`page`、`pageSize`、`keyword?` | `data`：分页机构列表 |

---

## 17. 管理后台·内容审核（admin）— 31 个接口

Base：`/api/tech-transfer/v1/admin`。认证：`admin_identity`（管理员）或 `backend_identity`（平台/机构管理员，标注为「后台」）。写操作幂等由状态机校验保证（重复审核 409），全部记审计。

### 17.1 成果导入（PPTX/PDF 解析暂存）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 70 | GET | `/admin/achievement-imports` | 导入批次列表 | 需登录·管理员 | Query：`page`、`pageSize` | `data`：批次列表 |
| 71 | POST | `/admin/achievement-imports` | 上传 PPTX/PDF 解析入暂存（不自动发布） | 需登录·管理员 | Body（multipart）：`files[]`（必填，多文件）、`sourceOrg?`（Form） | `data`：暂存批次；message=“导入暂存已创建” |
| 72 | POST | `/admin/achievement-imports/clear` | 清空全部导入暂存批次 | 需登录·管理员 | — | `data`：清空结果；message=“导入暂存已清空” |
| 73 | GET | `/admin/achievement-imports/{batch_id}` | 导入批次详情 | 需登录·管理员 | Path：`batch_id` | `data`：批次详情；不存在 404 |
| 74 | POST | `/admin/achievement-imports/{batch_id}/items/{item_id}/confirm` | 确认一条暂存记录（仅落 draft，需正常审核） | 需登录·管理员 | Path：`batch_id`、`item_id`；Body（AchievementWriteRequest）：成果字段（同 §5 创建字段） | `data`：入库成果；message=“成果已入库为草稿” |
| 75 | POST | `/admin/achievement-imports/{batch_id}/items/{item_id}/publish` | 一键发布暂存记录（确认入库→提交审核→审核通过） | 需登录·管理员 | Path：`batch_id`、`item_id`；Body（AchievementWriteRequest） | `data`：发布成果；message=“成果已发布” |

### 17.2 字典/范围

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 76 | GET | `/admin/demand-categories` | 需求分类字典（后台） | 需登录·后台 | — | `data`：分类列表 |
| 77 | GET | `/admin/content-organizations` | 内容归属机构列表（按 scope 过滤） | 需登录·后台 | — | `data`：机构列表 |

### 17.3 成果管理

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 78 | GET | `/admin/achievements` | 成果列表（含全状态，按 scope） | 需登录·后台 | Query：分页 + 状态/机构/关键词过滤 | `data`：分页成果列表 |
| 79 | POST | `/admin/achievements` | 后台创建成果（201） | 需登录·后台 | Body（AchievementCreateRequest）：同 §5 #17 | `data`：成果详情；message=“成果创建成功” |
| 80 | GET | `/admin/achievements/review-queue` | 成果审核队列 | 需登录·管理员 | Query：分页等 | `data`：待审核列表 |
| 81 | GET | `/admin/achievements/{ach_id}` | 成果详情（后台视角） | 需登录·后台 | Path：`ach_id` | `data`：成果详情 |
| 82 | PATCH | `/admin/achievements/{ach_id}` | 后台编辑成果 | 需登录·后台 | Path：`ach_id`；Body（AchievementUpdateRequest）：`version` + 可编辑字段 | `data`：更新后详情；message=“成果更新成功” |
| 83 | POST | `/admin/achievements/{ach_id}/claim-organization` | 认领无归属成果到当前机构 | 需登录·后台 | Path：`ach_id`；Body：`version` | `data`：认领结果；message=“已归属到当前机构” |
| 84 | POST | `/admin/achievements/{ach_id}/submit` | 代平台代录成果提交审核（仅 owner 为 NULL 的内容） | 需登录·管理员 | Path：`ach_id`；Body：`version` | `data`：流转结果；message=“已提交审核” |
| 85 | POST | `/admin/achievements/{ach_id}/approve` | 审核通过 | 需登录·管理员 | Path：`ach_id`；Body：`version` | `data`：审核结果 |
| 86 | POST | `/admin/achievements/{ach_id}/reject` | 审核驳回 | 需登录·管理员 | Path：`ach_id`；Body：`version`、`reason`（必填） | `data`：审核结果 |
| 87 | POST | `/admin/achievements/{ach_id}/offline` | 管理员下架已发布成果（published → offline） | 需登录·后台 | Path：`ach_id`；Body：`version` | `data`：流转结果；message=“成果已下架” |
| 88 | DELETE | `/admin/achievements/{ach_id}` | 管理员软删除成果（deleted_at=NOW） | 需登录·后台 | Path：`ach_id` | `data`：删除结果；message=“成果已删除” |

### 17.4 需求管理

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 89 | GET | `/admin/demands` | 需求列表（含全状态，按 scope） | 需登录·后台 | Query：分页 + 状态/机构/关键词过滤 | `data`：分页需求列表 |
| 90 | POST | `/admin/demands` | 后台创建需求（201） | 需登录·后台 | Body（DemandCreateRequest）：同 §6 #22 | `data`：需求详情；message=“需求创建成功” |
| 91 | GET | `/admin/demands/review-queue` | 需求审核队列 | 需登录·管理员 | Query：分页等 | `data`：待审核列表 |
| 92 | GET | `/admin/demands/{demand_id}` | 需求详情（后台视角） | 需登录·后台 | Path：`demand_id` | `data`：需求详情 |
| 93 | PATCH | `/admin/demands/{demand_id}` | 后台编辑需求 | 需登录·后台 | Path：`demand_id`；Body（DemandUpdateRequest）：`version` + 可编辑字段 | `data`：更新后详情；message=“需求更新成功” |
| 94 | POST | `/admin/demands/{demand_id}/claim-organization` | 认领无归属需求到当前机构 | 需登录·后台 | Path：`demand_id`；Body：`version` | `data`：认领结果；message=“已归属到当前机构” |
| 95 | POST | `/admin/demands/{demand_id}/submit` | 代平台代录需求提交审核（仅 owner 为 NULL 的内容） | 需登录·管理员 | Path：`demand_id`；Body：`version` | `data`：流转结果；message=“已提交审核” |
| 96 | POST | `/admin/demands/{demand_id}/approve` | 审核通过 | 需登录·管理员 | Path：`demand_id`；Body：`version` | `data`：审核结果 |
| 97 | POST | `/admin/demands/{demand_id}/reject` | 审核驳回 | 需登录·管理员 | Path：`demand_id`；Body：`version`、`reason`（必填） | `data`：审核结果 |
| 98 | POST | `/admin/demands/{demand_id}/close` | 管理员关闭已发布/对接中的需求 | 需登录·后台 | Path：`demand_id`；Body：`version` | `data`：流转结果；message=“需求已关闭” |
| 99 | DELETE | `/admin/demands/{demand_id}` | 管理员软删除需求（deleted_at=NOW） | 需登录·后台 | Path：`demand_id` | `data`：删除结果；message=“需求已删除” |

### 17.5 审计

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 100 | GET | `/admin/audit-logs` | 审计日志查询 | 需登录·管理员 | Query：分页 + 操作人/类型/时间过滤 | `data`：分页审计日志 |

---

## 18. 管理后台·平台运营（admin_ops）— 23 个接口

Base：`/api/tech-transfer/v1/admin`。写操作 service 层同事务写审计。

### 18.1 Dashboard

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 101 | GET | `/admin/dashboard/summary` | 运营总览汇总 | 需登录·管理员 | — | `data`：统计汇总 |
| 102 | GET | `/admin/notifications/summary` | 后台通知角标汇总（按 scope） | 需登录·后台 | — | `data`：未读汇总 |
| 103 | GET | `/admin/dashboard/todos` | 待办事项列表 | 需登录·管理员 | Query：`limit?`（默认 20） | `data`：待办列表 |
| 104 | GET | `/admin/dashboard/trend` | 趋势统计 | 需登录·管理员 | Query：`days?` | `data`：趋势数据 |

### 18.2 机构注册审核

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 105 | GET | `/admin/institution-registrations` | 机构注册申请列表 | 需登录·管理员 | Query：分页 + 状态过滤 | `data`：分页申请列表 |
| 106 | POST | `/admin/institution-registrations/{institution_id}/approve` | 通过机构注册申请 | 需登录·管理员 | Path：`institution_id` | `data`：审核结果；message=“机构注册申请已通过” |
| 107 | POST | `/admin/institution-registrations/{institution_id}/reject` | 驳回机构注册申请 | 需登录·管理员 | Path：`institution_id`；Body：`reason?` | `data`：审核结果；message=“机构注册申请已驳回” |

### 18.3 机构管理

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 108 | GET | `/admin/institutions` | 机构列表（后台） | 需登录·管理员 | Query：分页 + kind/type/关键词 | `data`：分页机构列表 |
| 109 | POST | `/admin/institutions` | 创建机构（201） | 需登录·管理员 | Body（InstitutionCreateRequest）：`kind`（必填：platform/invest/service/university/institute/enterprise/other）、`name`（必填，≤255）、`region?`、`intro?`、`detailInfo?`、`label?`、`logoFileId?`、`sortOrder?`、`userType?`、platform 专有（`platformType`、`platformTypeKey`、`unit`、`functionText`、`contact`、`phone`、`serialNo`、`sourceStatus`、`orderNum`、`detailActivityId`） | 201：`data`=机构详情 |
| 110 | POST | `/admin/institutions/import` | 批量导入机构 | 需登录·管理员 | Body：`items[]`（必填，≥1 条机构条目） | `data`：`{created, updated, ...}`；message=“导入完成：新增 X，更新 Y” |
| 111 | GET | `/admin/institutions/{institution_id}` | 机构详情（后台） | 需登录·管理员 | Path：`institution_id` | `data`：机构详情 |
| 112 | PATCH | `/admin/institutions/{institution_id}` | 编辑机构 | 需登录·管理员 | Path：`institution_id`；Body（InstitutionUpdateRequest）：同 #109 字段均可选 | `data`：更新后详情 |
| 113 | DELETE | `/admin/institutions/{institution_id}` | 删除机构 | 需登录·管理员 | Path：`institution_id` | `data`：删除结果；message=“机构已删除” |
| 114 | POST | `/admin/institutions/{institution_id}/online` | 机构上架 | 需登录·管理员 | Path：`institution_id` | `data`：状态结果 |
| 115 | POST | `/admin/institutions/{institution_id}/offline` | 机构下架 | 需登录·管理员 | Path：`institution_id` | `data`：状态结果 |

### 18.4 对接管理（只读 + 平台协助运营）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 116 | GET | `/admin/cooperations` | 对接意向列表（按 scope） | 需登录·后台 | Query：分页 + 状态过滤 | `data`：分页意向列表 |
| 117 | GET | `/admin/cooperations/{intent_id}` | 对接意向详情 | 需登录·后台 | Path：`intent_id` | `data`：意向详情 |
| 118 | POST | `/admin/cooperations/{intent_id}/accept` | 平台接受对接申请 | 需登录·后台 | Path：`intent_id`；Body：`version` | `data`：流转结果；message=“对接申请已接受” |
| 119 | POST | `/admin/cooperations/{intent_id}/reject` | 平台驳回对接申请 | 需登录·后台 | Path：`intent_id`；Body：`version`、`reason`（必填） | `data`：流转结果；message=“对接申请已驳回” |
| 120 | POST | `/admin/cooperations/{intent_id}/assist-status` | 平台协助处理阶段流转 | 需登录·管理员 | Path：`intent_id`；Body：`assistStatus`（必填：queued/contacting/waiting_reply/target_agreed/target_rejected/unreachable） | `data`：流转结果 |
| 121 | POST | `/admin/cooperations/{intent_id}/assist-transition` | 平台代目标机构操作状态机（accept 前置 assist_status=target_agreed） | 需登录·管理员 | Path：`intent_id`；Body：`action`（必填：accept/reject/confirm/cancel/complete）、`version` | `data`：流转结果 |

### 18.5 用户管理（只读）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 122 | GET | `/admin/users` | 用户列表（只读，按 scope） | 需登录·后台 | Query：分页 + 关键词/角色过滤 | `data`：分页用户列表 |
| 123 | GET | `/admin/users/{user_id}` | 用户详情（只读） | 需登录·后台 | Path：`user_id` | `data`：用户详情 |

---

## 19. 会员/组织认证（organization-membership）— 24 个接口

Base：`/api/tech-transfer/v1`。所有状态操作需 `version` 乐观锁。

### 19.1 我的组织（需登录）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 124 | GET | `/me/organization-memberships` | 我的组织成员身份列表 | 需登录 | Query：`page`、`pageSize` | `data`：分页成员身份列表 |
| 125 | GET | `/me/organization-certification` | 我的组织认证信息 | 需登录 | — | `data`：认证信息 |
| 126 | GET | `/me/organization-membership-applications` | 我的入会申请列表 | 需登录 | Query：`status?`（pending/approved/rejected/cancelled）、`page`、`pageSize` | `data`：分页申请列表 |
| 127 | POST | `/me/organization-membership-applications` | 提交入会申请 | 需登录 | Body：`orgId`（必填）、`realName?`、`department?`、`title?`、`workEmail?`、`proofMaterial?`（≤10000）、`applyNote?` | `data`：申请详情 |
| 128 | POST | `/me/organization-membership-applications/{application_id}/cancel` | 取消入会申请 | 需登录 | Path：`application_id`；Body：`version` | `data`：取消结果 |
| 129 | POST | `/me/organization-admin-applications` | 申请成为机构管理员 | 需登录 | Body：`orgId`（必填）、`realName?`、`department?`、`title?`、`workEmail?`、`proofMaterial?`、`reason?` | `data`：申请详情 |
| 130 | POST | `/me/organization-applications` | 申请创建/认领组织 | 需登录 | Body：`requestedName`（必填，≤128）、`requestedType?`、`creditCode?`、`website?`、`region?`、`address?`、`contactName?`、`contactPhone?`、`contactEmail?`、`proofMaterial?` | `data`：申请详情 |

### 19.2 机构管理员端（需登录·机构管理员）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 131 | GET | `/org-admin/members` | 机构成员列表 | 需登录·机构管理员 | Query：`orgId`（必填，≥1）、`status?`（active/revoked）、`page`、`pageSize` | `data`：分页成员列表 |
| 132 | GET | `/org-admin/membership-applications` | 机构入会申请列表 | 需登录·机构管理员 | Query：`orgId`（必填）、`status?`、`page`、`pageSize` | `data`：分页申请列表 |
| 133 | POST | `/org-admin/membership-applications/{application_id}/approve` | 通过入会申请 | 需登录·机构管理员 | Path：`application_id`；Body：`version` | `data`：审核结果 |
| 134 | POST | `/org-admin/membership-applications/{application_id}/reject` | 驳回入会申请 | 需登录·机构管理员 | Path：`application_id`；Body：`version`、`reason`（必填，≤1000） | `data`：审核结果 |
| 135 | POST | `/org-admin/members/{membership_id}/revoke` | 撤销成员资格 | 需登录·机构管理员 | Path：`membership_id`；Body：`version`、`reason`（必填） | `data`：撤销结果 |

### 19.3 平台管理员端（需登录·管理员）

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 136 | GET | `/admin/certification-applications` | 组织认证申请列表 | 需登录·管理员 | Query：`status?`、`page`、`pageSize` | `data`：分页申请列表 |
| 137 | GET | `/admin/organization-applications` | 组织创建/认领申请列表 | 需登录·管理员 | Query：`status?`、`page`、`pageSize` | `data`：分页申请列表 |
| 138 | GET | `/admin/organization-membership-applications` | 平台侧入会申请列表 | 需登录·管理员 | Query：`status?`、`page`、`pageSize` | `data`：分页申请列表 |
| 139 | POST | `/admin/organization-membership-applications/{application_id}/approve` | 平台通过入会申请 | 需登录·管理员 | Path：`application_id`；Body：`version` | `data`：审核结果 |
| 140 | POST | `/admin/organization-membership-applications/{application_id}/reject` | 平台驳回入会申请 | 需登录·管理员 | Path：`application_id`；Body：`version`、`reason`（必填） | `data`：审核结果 |
| 141 | POST | `/admin/organization-applications/{application_id}/approve` | 通过组织创建/认领申请 | 需登录·管理员 | Path：`application_id`；Body：`version` | `data`：审核结果 |
| 142 | POST | `/admin/organization-applications/{application_id}/reject` | 驳回组织创建/认领申请 | 需登录·管理员 | Path：`application_id`；Body：`version`、`reason`（必填） | `data`：审核结果 |
| 143 | GET | `/admin/organization-admin-applications` | 机构管理员申请列表 | 需登录·管理员 | Query：`status?`、`page`、`pageSize` | `data`：分页申请列表 |
| 144 | POST | `/admin/organization-admin-applications/{application_id}/approve` | 通过机构管理员申请 | 需登录·管理员 | Path：`application_id`；Body：`version` | `data`：审核结果 |
| 145 | POST | `/admin/organization-admin-applications/{application_id}/reject` | 驳回机构管理员申请 | 需登录·管理员 | Path：`application_id`；Body：`version`、`reason`（必填） | `data`：审核结果 |
| 146 | POST | `/admin/organization-memberships/{membership_id}/grant-admin` | 授予成员机构管理员权限 | 需登录·管理员 | Path：`membership_id`；Body：`version` | `data`：授予结果 |
| 147 | POST | `/admin/organization-memberships/{membership_id}/revoke-admin` | 撤销机构管理员权限 | 需登录·管理员 | Path：`membership_id`；Body：`version`、`reason`（必填） | `data`：撤销结果 |

---

## 20. AI Agent 服务（nanshan-ai-agent）— 3 个接口

> 独立服务（FastAPI，title=“南山科转通 AI Agent”，version 0.3.0）。`POST /api/ai/chat` 由主后端 `/ai/chat`、`/ai/match` 转发调用（`settings.AI_AGENT_URL`），前端不直接访问。

| # | 方法 | 路径 | 描述 | 认证 | 请求参数 | 响应 |
|---|---|---|---|---|---|---|
| 148 | GET | `/health` | 服务健康检查 | 公开 | — | `{"status":"ok","service":"nanshan-ai-agent","version":"0.3.0"}` |
| 149 | GET | `/health/db` | 数据库健康检查 | 公开 | — | ok：`{"status":"ok","database":"tech_transfer","result":[1]}`；异常 503：`{"status":"error","error":"database_unavailable"}` |
| 150 | POST | `/api/ai/chat` | AI 问答/检索（意图分类 → 成果/需求检索 → 重排） | 公开（内网，由主后端转发） | Body（ChatRequest）：`message`（必填，1–2000 字符）、`exclude_owner_user_id?`（int，排除该用户自己的成果/需求） | `ChatResponse`：`{success, intent, message, data:[成果卡\|需求卡]}`；intent ∈ search_achievement / search_demand / out_of_scope。错误：502（LLM 层，detail 含 layer/llmStatus/llmReason）、503（agent/DB 层）、504（超时）、500（意图识别失败） |

---

## 附录 A：模块 ↔ 源码文件对照

| 模块 | 源码文件 | 接口数 |
|---|---|---|
| 认证 | `tech-transfer-service/routes/auth.py` | 5 |
| 用户中心 | `routes/me.py` | 7 |
| 成果 | `routes/achievement.py` | 8 |
| 需求 | `routes/demand.py` | 7 |
| 合作对接 | `routes/cooperation.py` | 8 |
| 收藏 | `routes/favorite.py` | 2 |
| 搜索 | `routes/search.py` | 1 |
| AI 助手 | `routes/ai.py` | 7 |
| 通知 | `routes/notification.py` | 5 |
| 专利 | `routes/patent.py` | 8 |
| 文件 | `routes/file.py` | 5 |
| 机构 | `routes/institution.py` | 2 |
| 机构注册 | `routes/institution_registration.py` | 1 |
| 资本对接（legacy） | `routes/capital.py` | 3 |
| 管理后台·审核 | `routes/admin.py` | 31 |
| 管理后台·运营 | `routes/admin_ops.py` | 23 |
| 会员/组织认证 | `routes/membership.py` | 24 |
| AI Agent | `nanshan-ai-agent/app/main.py` | 3 |
| **合计** | | **150** |

## 附录 B：通用请求体速查

| Schema | 关键字段 |
|---|---|
| `VersionBody` | `version`（必填，乐观锁） |
| `ReasonVersionBody` | `version` + `reason?`、`reasonCode?`、`reasonNote?` |
| `ReviewRejectRequest` | `version` + `reason`（必填） |
| `LoginRequest` | `username?` 或 `phone?` + `password` |
| `RegisterRequest` | `username?` 或 `phone?` + `password`、`displayName?`、`email?` |
| `RefreshTokenRequest` | `refreshToken` |
| `AchievementCreateRequest` | `title`（必填）+ 成果字段（成熟度/定价/简介/发明人/媒体等） |
| `AchievementUpdateRequest` | `version`（必填）+ 同上可编辑字段 |
| `DemandCreateRequest` | `title`、`description`（必填）+ 需求字段（预算/合作方式/期限/附件等） |
| `DemandUpdateRequest` | `version`（必填）+ 同上可编辑字段 |
| `CooperationCreateRequest` | `targetType`、`targetId`、`contactShareConsent`（必填）+ `intentType?`、`message?` |
| `AiChatRequest` | `message`（必填）、`turnId?` |
| `AiMatchRequest` | `demandId`（必填） |
| `EvaluationTaskRequest` | `achievementId`（必填） |
| `MembershipApplicationRequest` | `orgId`（必填）+ 实名/部门/证明材料等 |
| `InstitutionCreateRequest` | `kind`、`name`（必填）+ 机构字段 |
| `InstitutionRegistrationRequest` | `kind`、`name`、`contactName`、`contactPhone`、`username`、`password`（必填） |

> 注：`core/request_schemas.py` 中的请求体均允许 `extra="allow"`（透传额外字段），`modules/membership/schemas.py` 中的请求体为 `extra="forbid"`（严格校验）。
