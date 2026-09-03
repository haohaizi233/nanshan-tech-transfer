# 南山科转通 API 接口文档

> 生成依据：`tech-transfer-service` 源码（FastAPI 版，commit be47d0c 之后）
> 统一前缀：`/api/tech-transfer/v1` ｜ 本地默认端口：`8787`
> 接口总数：34（33 个业务接口 + 1 个健康检查）

***

## 目录

1. [通用约定](#1-通用约定)
2. [认证与会话 auth（3）](#2-认证与会话-auth)
3. [我的 me（5）](#3-我的-me)
4. [成果 achievements（4）](#4-成果-achievements)
5. [需求 demands（7）](#5-需求-demands)
6. [收藏 favorites（2）](#6-收藏-favorites)
7. [合作对接 cooperations（8）](#7-合作对接-cooperations)
8. [资本对接 capital（3，存量路径）](#8-资本对接-capital存量路径)
9. [文件代理 file（1，存量路径）](#9-文件代理-file存量路径)
10. [健康检查 health（1）](#10-健康检查-health)
11. [附录：接口总表 / 错误码 / 状态机 / 枚举值](#11-附录)

***

## 1. 通用约定

### 1.1 Base URL

| 环境    | Base URL                          |
| ----- | --------------------------------- |
| 本地    | `http://127.0.0.1:8787`           |
| H5 本地 | 同源 `/api`（生产 H5 不允许硬编码 127.0.0.1） |
| 生产    | 由部署方决定，API 前缀不变                   |

### 1.2 认证方式

除以下接口外，**全部接口需要认证**：

- `POST /auth/bootstrap`、`POST /auth/refresh`、`POST /auth/logout`

- 资本三接口（`/api/platform-base` 等）

- 文件代理 `/api/file/{file_id}`

- 健康检查 `/api/health`

认证方式为 JWT Bearer Token：

```
Authorization: Bearer {accessToken}
```

- accessToken 有效期 **7200 秒（2 小时）**，payload 含 `sub`（userId）、`userNo`、`roles`

- refreshToken 有效期 **14 天**，refresh 时旋转（旧 token 置为 `consumed`）

### 1.3 统一响应格式

成功（业务约定 `code=0`）：

```json
{
  "code": 0,
  "message": "ok",
  "data": { },
  "requestId": "uuid"
}
```

失败（HTTP 状态码与业务码对应）：

```json
{
  "code": "TT_COMMON_40001",
  "message": "请求参数无效",
  "requestId": "uuid",
  "details": { }
}
```

- `requestId`：请求进来时若带 `X-Request-Id` 头则原样返回，否则自动生成 UUID

- 路径参数类型不匹配（如 `/demands/abc`）返回 **404** **`TT_COMMON_40401`**（与 Flask `<int:>` 行为对齐）

### 1.4 通用请求头

| Header              | 说明                       |
| ------------------- | ------------------------ |
| `Authorization`     | `Bearer {token}`，认证接口组必需 |
| `Content-Type`      | `application/json`（写接口）  |
| `X-Request-Id`      | 可选，链路追踪                  |
| `X-Idempotency-Key` | 可选；**当前仅打印日志，防重放未实现**    |

### 1.5 分页约定

请求参数：`page`（默认 1）、`pageSize`（默认 10，**上限 50**）、`keyword`（模糊搜索）。

响应 data 结构统一为：

```json
{
  "total": 100,
  "page": 1,
  "pageSize": 10,
  "totalPages": 10,
  "list": [ ]
}
```

### 1.6 乐观锁

需求编辑、需求/对接状态流转、资料编辑均要求携带 `version` 字段；后端 `WHERE version=%s` 匹配更新，不匹配返回 **409** **`TT_COMMON_40902`**。

***

## 2. 认证与会话 auth

前缀：`/api/tech-transfer/v1/auth`，共 3 个接口，无需登录。

### 2.1 POST /auth/bootstrap — 宿主凭证换取会话

首次登录/自动注册（按 `issuer + tenant_id + external_subject` 唯一映射，新用户自动建 `app_user`/`user_profile`/`user_role`）。

**请求体**：

| 字段             | 类型     | 必填 | 说明                                                                  |
| -------------- | ------ | -- | ------------------------------------------------------------------- |
| hostCredential | string | 是  | 宿主票据。本地 Mock 须以 `local-dev-ticket-` 开头，后缀为外部主体标识（缺省 `dev-user-001`） |

**请求示例（本地开发）**：

```json
{ "hostCredential": "local-dev-ticket-dev-user-002" }
```

**响应 data**：

| 字段           | 类型     | 说明          |
| ------------ | ------ | ----------- |
| accessToken  | string | 访问令牌（2h）    |
| refreshToken | string | 刷新令牌（14d）   |
| expiresIn    | int    | 固定 7200     |
| user         | object | 用户信息（见 3.1） |
| isNewUser    | bool   | 是否本次新建用户    |

**错误**：`TT_AUTH_40103`（401，宿主凭证无效/前缀不符）。

### 2.2 POST /auth/refresh — 刷新会话

**请求体**：`refreshToken`（string，必填）

**响应 data**：同 bootstrap（`isNewUser` 固定 false）。旧 refreshToken 被置 `consumed`，同时签发新 refreshToken。

**错误**：`TT_COMMON_40102`（401，缺参/token 无效/会话非 active/已过期）。

### 2.3 POST /auth/logout — 注销会话

**请求体**：`refreshToken`（string，必填）

**响应 data**：`{ "revoked": true|false }`（token 无效时幂等返回 false）

***

## 3. 我的 me

前缀：`/api/tech-transfer/v1/me`，共 5 个接口，全部需要登录。

### 3.1 GET /me — 我的信息

**响应 data（User 对象，下同）**：

| 字段                                     | 类型        | 说明                |
| -------------------------------------- | --------- | ----------------- |
| userId                                 | int       | 本地用户 ID           |
| userNo                                 | string    | 如 `U202600001`    |
| displayName / userType / phone / email | string    | 资料                |
| orgId / orgName / orgTitle             | <br />    | 组织信息              |
| version                                | int       | 资料版本号（编辑用乐观锁）     |
| roles                                  | string\[] | 角色码，默认 `["user"]` |

### 3.2 PATCH /me/profile — 编辑我的资料

**请求体**：

| 字段            | 类型     | 必填 | 说明                                                                          |
| ------------- | ------ | -- | --------------------------------------------------------------------------- |
| version       | int    | 是  | 正整数，乐观锁                                                                     |
| displayName   | string | 否  | <br />                                                                      |
| userType      | string | 否  | 枚举：`enterprise_staff` / `researcher` / `investor` / `service_org` / `other` |
| phone / email | string | 否  | <br />                                                                      |
| orgId         | int    | 否  | <br />                                                                      |
| orgTitle      | string | 否  | <br />                                                                      |

**响应 data**：更新后的 User 对象。**错误**：`TT_COMMON_40902`（409，版本冲突，details 含 `currentVersion`）。

### 3.3 GET /me/demands — 我的需求列表

| Query           | 类型     | 默认     | 说明                                                                       |
| --------------- | ------ | ------ | ------------------------------------------------------------------------ |
| page / pageSize | int    | 1 / 10 | pageSize 上限 50                                                           |
| status          | string | 空      | 按状态过滤（draft/pending\_review/published/rejected/matched/cancelled/closed） |

**响应 data**：分页结构，list 元素为需求摘要（见 [5.1](#51-get-demands--需求列表)）。

### 3.4 GET /me/favorites — 我的收藏列表

| Query           | 类型     | 必填    | 说明                       |
| --------------- | ------ | ----- | ------------------------ |
| targetType      | string | **是** | `achievement` / `demand` |
| page / pageSize | int    | 否     | 默认 1 / 10                |

**响应 data**：分页结构，list 元素：

```json
{
  "id": 1,
  "targetType": "achievement",
  "targetId": 12,
  "favoritedAt": "2026-09-03 10:00:00",
  "targetSummary": { "title": "...", "orgName": "...", "status": "published", "desc": "前120字..." }
}
```

> 目标已下线仍返回（`status` 标注），不静默丢失收藏。

### 3.5 GET /me/cooperations — 我的对接列表

| Query           | 类型     | 默认     | 说明                                                      |
| --------------- | ------ | ------ | ------------------------------------------------------- |
| role            | string | `both` | `initiator`（我发起）/ `target`（向我发起）/ `both`                |
| status          | string | 空      | pending/accepted/rejected/confirmed/cancelled/completed |
| page / pageSize | int    | 1 / 10 | <br />                                                  |

**响应 data**：分页结构，list 元素为对接意向（含 `myRole`、`counterpartDisplayName`、`targetSummary`，见 [7.2](#22-get-cooperationsintent_id--对接详情)）。

***

## 4. 成果 achievements

前缀：`/api/tech-transfer/v1`，共 4 个接口，全部需要登录。

### 4.1 GET /achievements — 成果列表

| Query           | 类型     | 默认     | 说明                                         |
| --------------- | ------ | ------ | ------------------------------------------ |
| page / pageSize | int    | 1 / 10 | <br />                                     |
| keyword         | string | 空      | 匹配 title / tech\_intro / source\_org\_name |
| category        | string | 空      | 分类 code                                    |
| maturityLevel   | string | 空      | 成熟度                                        |

仅返回 `status='published'` 且未删除的成果，按 `published_at DESC` 排序。

**响应 data**：分页结构，list 元素：

| 字段                           | 类型           | 说明           |
| ---------------------------- | ------------ | ------------ |
| id / title                   | int / string | <br />       |
| sourceOrgName                | string       | 成果来源单位       |
| categoryName / categoryCode  | string       | <br />       |
| techIntro                    | string       | 截断 120 字     |
| maturityLevel / maturityDesc | string       | <br />       |
| applicationFields            | string\[]    | JSON 数组      |
| pricingMode                  | string       | 定价方式         |
| priceMinWan / priceMaxWan    | float        | 万元区间         |
| viewCount                    | int          | <br />       |
| publishedAt                  | string       | `YYYY-MM-DD` |

### 4.2 GET /achievements/categories — 成果分类

**响应 data**：`[{ "id", "code", "name", "sortOrder" }]`（仅 enabled=1，按 sortOrder 排序）。

### 4.3 GET /achievements/{ach\_id} — 成果详情

路径参数：`ach_id`（int）。成果不存在或未发布时 `data=null`、message=`成果不存在或未发布`（HTTP 200）。

**响应 data**：列表字段基础上追加：

| 字段                                                                       | 说明                                              |
| ------------------------------------------------------------------------ | ----------------------------------------------- |
| techRoute                                                                | 技术路线                                            |
| innovationPoints                                                         | string\[] 创新点                                   |
| contactName / contactTitle / contactPhone / contactEmail / contactWechat | 联系人信息                                           |
| inventors                                                                | `[{ "name", "orgName", "contribution" }]` 发明人列表 |

### 4.4 GET /search — 统一搜索

| Query                                                | 必填 | 说明                           |
| ---------------------------------------------------- | -- | ---------------------------- |
| type                                                 | 是  | 当前仅支持 `achievement`，其余值返回空列表 |
| page / pageSize / keyword / category / maturityLevel | 否  | 同 4.1                        |

**响应 data**：同 4.1 分页结构。

***

## 5. 需求 demands

前缀：`/api/tech-transfer/v1`，共 7 个接口，全部需要登录。状态机由后端强校验。

### 5.1 GET /demands — 需求列表

| Query           | 类型     | 默认                  | 说明                                          |
| --------------- | ------ | ------------------- | ------------------------------------------- |
| page / pageSize | int    | 1 / 10              | <br />                                      |
| keyword         | string | 空                   | 匹配 title / description / org\_name          |
| categoryCode    | string | 空                   | 分类 code                                     |
| includeMine     | string | false               | `1/true/yes` 时额外包含自己的非公开需求                  |
| sort            | string | `published_at.desc` | 白名单：`published_at.desc` / `created_at.desc` |

默认仅返回 `published`；**防探测**：非公开需求对非 owner 不出现在结果中。

**响应 data**：分页结构，list 元素（需求摘要）：

| 字段                          | 类型                 | 说明                 |
| --------------------------- | ------------------ | ------------------ |
| id / title                  | int / string       | <br />             |
| orgName                     | string             | 需求单位               |
| region                      | string             | 地区                 |
| coopMode                    | string\[]          | 合作方式               |
| budgetMinWan / budgetMaxWan | float              | 预算区间（万元）           |
| budgetNegotiable            | bool               | 面议                 |
| deadlineDesc                | string             | 期限描述               |
| categoryName / tags         | string / string\[] | <br />             |
| status                      | string             | <br />             |
| isMine                      | bool               | 是否本人发布             |
| publishedAt                 | string             | `YYYY-MM-DD HH:MM` |

### 5.2 POST /demands — 创建需求（201）

**请求体（DemandUpsertRequest）**：

| 字段                          | 类型        | 必填 | 校验                                     |
| --------------------------- | --------- | -- | -------------------------------------- |
| title                       | string    | 是  | ≤200 字                                 |
| description                 | string    | 是  | <br />                                 |
| categoryId                  | int       | 否  | 须存在；也可用 categoryName 按名 get-or-create  |
| orgId                       | int       | 否  | 须存在；也可用 orgName/orgIntro get-or-create |
| region                      | string    | 否  | ≤64                                    |
| coopMode                    | string\[] | 否  | 字符串数组                                  |
| budgetMinWan / budgetMaxWan | number    | 否  | ≥0，且 min ≤ max                         |
| budgetNegotiable            | bool      | 否  | <br />                                 |
| expectDeadline              | string    | 否  | `YYYY-MM-DD`                           |
| deadlineDesc                | string    | 否  | ≤128                                   |
| contactName / contactTitle  | string    | 否  | ≤64                                    |
| contactPhone                | string    | 否  | ≤32                                    |
| contactEmail                | string    | 否  | ≤128                                   |
| contactWechat               | string    | 否  | ≤64                                    |
| tags                        | string\[] | 否  | 标签按名 get-or-create                     |

创建后状态为 `draft`。**响应 data**：需求详情（见 5.3）。`ownerUserId` 若传入会被忽略（服务端从 token 取身份）。

### 5.3 GET /demands/{demand\_id} — 需求详情

摘要字段（5.1）基础上追加：

| 字段                                                        | 说明                                     |
| --------------------------------------------------------- | -------------------------------------- |
| version                                                   | 乐观锁版本                                  |
| description                                               | 完整描述                                   |
| expectDeadline / orgIntro                                 | <br />                                 |
| rejectReason                                              | **仅 owner 可见**，其余为 null                |
| contactPhone                                              | **非 owner 掩码**（`138****1234`），owner 明文 |
| contactName / contactTitle / contactEmail / contactWechat | <br />                                 |

**错误**：`TT_DMD_40401`（404，不存在或非公开且非 owner）。

### 5.4 PATCH /demands/{demand\_id} — 编辑需求

- 请求体：同 5.2（所有业务字段均可选，部分更新），**必须携带** **`version`**

- 仅 `draft` / `rejected` 状态可编辑，其余返回 `TT_DMD_40901`（409）

- 仅 owner 可编辑，否则 `TT_DMD_40301`（403）

- **响应 data**：更新后的需求详情

### 5.5 POST /demands/{demand\_id}/submit — 提交审核

**请求体**：`{ "version": int }`（必填）

流转：`draft / rejected → pending_review`。**响应 data**：`{ "status": "pending_review" }`。

### 5.6 POST /demands/{demand\_id}/cancel — 撤回需求

**请求体**：`{ "version": int }`。流转：`published → cancelled`。

### 5.7 POST /demands/{demand\_id}/close — 关闭需求

**请求体**：`{ "version": int }`。流转：`published / matched → closed`。

> 5.5–5.7 通用错误：`TT_DMD_40401`（404 不存在）、`TT_DMD_40301`（403 非所有者）、`TT_DMD_40901`（409 状态不允许）、`TT_COMMON_40902`（409 version 不匹配）、`TT_COMMON_40001`（400 缺 version）。

***

## 6. 收藏 favorites

前缀：`/api/tech-transfer/v1`，共 2 个接口，需要登录。PUT/DELETE 均幂等。

### 6.1 PUT /favorites/{targetType}/{targetId} — 收藏

路径参数：`targetType`（`achievement` / `demand`）、`targetId`（int）。

- 目标须存在且（`published` 或本人内容），否则 `TT_FAV_40401`（404）

- 重复收藏幂等返回既有记录

**响应 data**：`{ "id": 1, "favoritedAt": "2026-09-03 10:00:00" }`

### 6.2 DELETE /favorites/{targetType}/{targetId} — 取消收藏

物理删除，不存在也返回成功。**响应**：`data=null`，message=`已取消收藏`。

***

## 7. 合作对接 cooperations

前缀：`/api/tech-transfer/v1`，共 8 个接口，全部需要登录。详情/事件仅参与方可见，其余一律 404（防探测）。

### 7.1 POST /cooperations — 发起对接意向（201）

**请求体**：

| 字段         | 类型     | 必填 | 说明                       |
| ---------- | ------ | -- | ------------------------ |
| targetType | string | 是  | `achievement` / `demand` |
| targetId   | int    | 是  | 目标须为 `published`         |
| message    | string | 否  | ≤1000 字                  |

**业务规则**：

- 不能对自己发布的内容发起（`TT_COOP_40001`，400）

- 同一用户对同一目标已有进行中意向（pending/accepted/confirmed）时返回 `TT_COOP_40902`（409）

- 创建后状态为 `pending`，同时写入 `created` 事件

**响应 data**：对接详情（见 7.2）。

### 7.2 GET /cooperations/{intent\_id} — 对接详情

**响应 data**：

| 字段                                                            | 类型     | 说明                                                      |
| ------------------------------------------------------------- | ------ | ------------------------------------------------------- |
| id                                                            | int    | 意向 ID                                                   |
| initiatorUserId / targetOwnerUserId                           | int    | 发起方 / 目标所有方                                             |
| targetType / targetId                                         | <br /> | 目标                                                      |
| message                                                       | string | 留言                                                      |
| status                                                        | string | pending/accepted/rejected/confirmed/completed/cancelled |
| version                                                       | int    | 乐观锁                                                     |
| createdAt / acceptedAt / confirmedAt / completedAt / closedAt | string | `YYYY-MM-DD HH:MM:SS`                                   |
| myRole                                                        | string | `initiator` / `target_owner`                            |
| counterpartDisplayName                                        | string | 对方展示名                                                   |
| targetSummary                                                 | object | `{ title, orgName, status }`，目标下线时 `status=offline`     |

### 7.3–7.7 状态流转接口（均需 `version`）

| 接口                               | 流转                             | 允许角色  | 附加字段              |
| -------------------------------- | ------------------------------ | ----- | ----------------- |
| POST /cooperations/{id}/accept   | pending → accepted             | 目标所有方 | —                 |
| POST /cooperations/{id}/reject   | pending → rejected             | 目标所有方 | `reason`（**必填**）  |
| POST /cooperations/{id}/confirm  | accepted → confirmed           | 双方    | —                 |
| POST /cooperations/{id}/cancel   | accepted/confirmed → cancelled | 双方    | `reason`（可选）      |
| POST /cooperations/{id}/complete | confirmed → completed          | 双方    | `remark`（可选，≤500） |

**副作用**：

- `accept`：同一目标的其他 pending 意向自动拒绝（事件 `auto_rejected`，同一事务）

- `confirm`：目标为需求时，需求自动流转 `published → matched`

**响应 data**：流转后的对接详情。**错误**：`TT_COOP_40401`（404）、`TT_COOP_40301`（403 角色不允许）、`TT_COOP_40901`（409 状态不允许）、`TT_COMMON_40902`（409 version 不匹配）。

### 7.8 GET /cooperations/{intent\_id}/events — 事件时间线

| Query           | 默认     |
| --------------- | ------ |
| page / pageSize | 1 / 20 |

**响应 data**：分页结构，list 元素按时间正序：

```json
{
  "id": 1, "intentId": 1,
  "eventType": "created | accepted | rejected | auto_rejected | confirmed | cancelled | completed",
  "fromStatus": null, "toStatus": "pending",
  "operatorRole": "initiator | target_owner | system",
  "remark": "...", "createdAt": "2026-09-03 10:00:00"
}
```

***

## 8. 资本对接 capital（存量路径）

> 旧路径，无 `/api/tech-transfer/v1` 前缀、无需登录；数据源为 `nanshan_capital` 库。Phase B 计划迁移到 `/api/tech-transfer/v1/capital/*`。

### 8.1 GET /api/platform-base — 平台基底列表

| Query           | 默认     | 说明                                            |
| --------------- | ------ | --------------------------------------------- |
| page / pageSize | 1 / 10 | <br />                                        |
| type            | `all`  | `poc`（概念验证）/ `pilot`（中小试/中试）/ `other` / `all` |
| keyword         | 空      | 匹配名称/依托单位/功能/联系人/电话                           |

**响应 data**：分页结构，list 元素：

```json
{
  "id": "1", "serialNo": 1, "name": "××概念验证中心",
  "platformType": "概念验证", "platformTypeKey": "poc",
  "unit": "依托单位", "functionText": "功能定位",
  "contact": "联系人", "phone": "电话"
}
```

### 8.2 GET /api/invest-orgs — 投资机构列表

Query：`page` / `pageSize` / `keyword`（匹配 org\_name、intro）。list 元素含 `id, name, intro, detailInfo, label, logoFileId, logoUrl, kind:"invest", sortOrder`。

### 8.3 GET /api/service-orgs — 服务机构列表

Query 同 8.2（keyword 匹配 org\_name、intro、label）。list 元素同 8.2，`kind:"bank"`。

***

## 9. 文件代理 file（存量路径）

### GET /api/file/{file\_id} — 文件（logo）代理

- `file_id` 仅保留 `[0-9A-Za-z_-]`，其余字符剔除；空则 400

- 优先读本地缓存 `cache/logos/`，未命中时代理源站 `www.szte.com` 并落盘缓存

- **成功**：直接返回文件流（按 mime 类型，通常是图片），不是 JSON 包装

- **失败**：`{"code": 1, "msg": "..."}`，HTTP 400（无效 id）/ 404（空文件）/ 502（源站获取失败）

***

## 10. 健康检查 health

### GET /api/health — 无需登录

**正常**（HTTP 200）：

```json
{
  "code": 0, "message": "ok",
  "data": {
    "status": "ok", "database": "ok", "db": true,
    "appUsers": 12, "authProvider": "mock", "appEnv": "local"
  }
}
```

**数据库不可用**（仍 HTTP 200，`code=1`）：`data.status="degraded"`、`data.database="unavailable"`。

***

## 11. 附录

### 11.1 全量接口总表（34 个）

> 路径均相对服务根（本地 `http://127.0.0.1:8787`）；「✓」= 需 `Authorization: Bearer {accessToken}`。
> 除标注 `201` 的两个创建接口外，成功状态码均为 `200`。

| #  | 方法     | 路径                                                       | 说明                                     | 认证  | 章节       |
| -- | ------ | -------------------------------------------------------- | -------------------------------------- | --- | -------- |
| 1  | POST   | /api/tech-transfer/v1/auth/bootstrap                     | 宿主凭证换会话（自动注册）                          | 免登录 | §2.1     |
| 2  | POST   | /api/tech-transfer/v1/auth/refresh                       | 刷新令牌（refreshToken 旋转）                  | 免登录 | §2.2     |
| 3  | POST   | /api/tech-transfer/v1/auth/logout                        | 注销会话（幂等）                               | 免登录 | §2.3     |
| 4  | GET    | /api/tech-transfer/v1/me                                 | 我的信息                                   | ✓   | §3.1     |
| 5  | PATCH  | /api/tech-transfer/v1/me/profile                         | 编辑资料（version 乐观锁）                      | ✓   | §3.2     |
| 6  | GET    | /api/tech-transfer/v1/me/demands                         | 我的需求列表                                 | ✓   | §3.3     |
| 7  | GET    | /api/tech-transfer/v1/me/favorites                       | 我的收藏列表                                 | ✓   | §3.4     |
| 8  | GET    | /api/tech-transfer/v1/me/cooperations                    | 我的对接列表                                 | ✓   | §3.5     |
| 9  | GET    | /api/tech-transfer/v1/achievements                       | 成果列表                                   | ✓   | §4.1     |
| 10 | GET    | /api/tech-transfer/v1/achievements/categories            | 成果分类                                   | ✓   | §4.2     |
| 11 | GET    | /api/tech-transfer/v1/achievements/{ach\_id}             | 成果详情                                   | ✓   | §4.3     |
| 12 | GET    | /api/tech-transfer/v1/search                             | 统一搜索（type=achievement）                 | ✓   | §4.4     |
| 13 | GET    | /api/tech-transfer/v1/demands                            | 需求列表                                   | ✓   | §5.1     |
| 14 | POST   | /api/tech-transfer/v1/demands                            | 创建需求（201，初始 draft）                     | ✓   | §5.2     |
| 15 | GET    | /api/tech-transfer/v1/demands/{demand\_id}               | 需求详情（联系方式脱敏）                           | ✓   | §5.3     |
| 16 | PATCH  | /api/tech-transfer/v1/demands/{demand\_id}               | 编辑需求（version 乐观锁，仅 draft/rejected）     | ✓   | §5.4     |
| 17 | POST   | /api/tech-transfer/v1/demands/{demand\_id}/submit        | 提交审核（draft/rejected → pending\_review） | ✓   | §5.5     |
| 18 | POST   | /api/tech-transfer/v1/demands/{demand\_id}/cancel        | 撤回（published → cancelled）              | ✓   | §5.6     |
| 19 | POST   | /api/tech-transfer/v1/demands/{demand\_id}/close         | 关闭（published/matched → closed）         | ✓   | §5.7     |
| 20 | PUT    | /api/tech-transfer/v1/favorites/{targetType}/{targetId}  | 收藏（幂等）                                 | ✓   | §6.1     |
| 21 | DELETE | /api/tech-transfer/v1/favorites/{targetType}/{targetId}  | 取消收藏（幂等，物理删除）                          | ✓   | §6.2     |
| 22 | POST   | /api/tech-transfer/v1/cooperations                       | 发起对接意向（201，仅 published 目标）             | ✓   | §7.1     |
| 23 | GET    | /api/tech-transfer/v1/cooperations/{intent\_id}          | 对接详情（仅参与方可见）                           | ✓   | §7.2     |
| 24 | POST   | /api/tech-transfer/v1/cooperations/{intent\_id}/accept   | 接受（目标方；自动拒绝同目标其他意向）                    | ✓   | §7.3–7.7 |
| 25 | POST   | /api/tech-transfer/v1/cooperations/{intent\_id}/reject   | 拒绝（目标方，reason 必填）                      | ✓   | §7.3–7.7 |
| 26 | POST   | /api/tech-transfer/v1/cooperations/{intent\_id}/confirm  | 确认（双方；demand 目标转 matched）              | ✓   | §7.3–7.7 |
| 27 | POST   | /api/tech-transfer/v1/cooperations/{intent\_id}/cancel   | 取消（双方，reason 可选）                       | ✓   | §7.3–7.7 |
| 28 | POST   | /api/tech-transfer/v1/cooperations/{intent\_id}/complete | 完成（双方，remark 可选）                       | ✓   | §7.3–7.7 |
| 29 | GET    | /api/tech-transfer/v1/cooperations/{intent\_id}/events   | 事件时间线（仅参与方可见）                          | ✓   | §7.8     |
| 30 | GET    | /api/platform-base                                       | 平台基底列表（存量路径）                           | 免登录 | §8.1     |
| 31 | GET    | /api/invest-orgs                                         | 投资机构列表（存量路径）                           | 免登录 | §8.2     |
| 32 | GET    | /api/service-orgs                                        | 服务机构列表（存量路径）                           | 免登录 | §8.3     |
| 33 | GET    | /api/file/{file\_id}                                     | 文件代理（直接返回文件流）                          | 免登录 | §9       |
| 34 | GET    | /api/health                                              | 健康检查（degraded 仍 HTTP 200）              | 免登录 | §10      |

### 11.2 错误码总表（错误码只增不改，frozen）

| 错误码               | HTTP | 说明                 |
| ----------------- | ---- | ------------------ |
| TT\_COMMON\_40001 | 400  | 请求参数无效             |
| TT\_COMMON\_40101 | 401  | 未提供认证令牌            |
| TT\_COMMON\_40102 | 401  | 认证令牌无效或已过期         |
| TT\_COMMON\_40301 | 403  | 无权限访问该资源           |
| TT\_COMMON\_40401 | 404  | 接口不存在              |
| TT\_COMMON\_40402 | 404  | 资源不存在              |
| TT\_COMMON\_40901 | 409  | 幂等键冲突，请勿重复提交       |
| TT\_COMMON\_40902 | 409  | 资源版本冲突（乐观锁）        |
| TT\_COMMON\_42901 | 429  | 请求过于频繁（预留）         |
| TT\_COMMON\_50001 | 500  | 服务内部错误             |
| TT\_AUTH\_40103   | 401  | 宿主凭证无效             |
| TT\_AUTH\_40104   | 401  | refresh token 已被吊销 |
| TT\_ACH\_40901    | 409  | 成果状态不允许此操作         |
| TT\_DMD\_40301    | 403  | 非需求所有者             |
| TT\_DMD\_40401    | 404  | 需求不存在              |
| TT\_DMD\_40901    | 409  | 需求状态不允许此操作         |
| TT\_COOP\_40001   | 400  | 不能对自己发布的内容发起对接     |
| TT\_COOP\_40301   | 403  | 无权操作此对接            |
| TT\_COOP\_40401   | 404  | 对接意向不存在            |
| TT\_COOP\_40901   | 409  | 对接状态不允许此操作         |
| TT\_COOP\_40902   | 409  | 已有进行中的对接意向         |
| TT\_FAV\_40401    | 404  | 收藏目标不存在或不可见        |
| TT\_AI\_50301     | 503  | AI 服务不可用（预留）       |
| TT\_PATENT\_50301 | 503  | 专利查询服务不可用（预留）      |
| TT\_FILE\_40001   | 400  | 文件格式不支持（预留）        |
| TT\_FILE\_40401   | 404  | 文件不存在（预留）          |

### 11.3 需求状态机

```
draft ──submit──▶ pending_review ──(审核)──▶ published / rejected
rejected ──submit──▶ pending_review
published ──cancel──▶ cancelled
published / matched ──close──▶ closed
published ──(对接 confirm 副作用)──▶ matched
```

- 仅 `draft` / `rejected` 可编辑（PATCH）

- 状态流转全部要求 `version` 乐观锁

### 11.4 对接状态机

```
pending ──accept(目标方)──▶ accepted ──confirm(双方)──▶ confirmed ──complete(双方)──▶ completed
pending ──reject(目标方)──▶ rejected
accepted / confirmed ──cancel(双方)──▶ cancelled
```

- `accept` 副作用：同目标其他 pending 意向自动 rejected（event=auto\_rejected）

- `confirm` 副作用：demand 目标自动 `published → matched`

### 11.5 枚举值速查

| 枚举                | 取值                                                                                 |
| ----------------- | ---------------------------------------------------------------------------------- |
| userType          | enterprise\_staff / researcher / investor / service\_org / other                   |
| targetType（收藏/对接） | achievement / demand                                                               |
| 需求状态              | draft / pending\_review / published / rejected / matched / cancelled / closed      |
| 对接状态              | pending / accepted / rejected / confirmed / completed / cancelled                  |
| myRole            | initiator / target\_owner                                                          |
| 对接事件              | created / accepted / rejected / auto\_rejected / confirmed / cancelled / completed |
| 需求排序              | published\_at.desc（默认）/ created\_at.desc                                           |
| 平台类型              | poc（概念验证）/ pilot（中小试/中试）/ other                                                    |

### 11.6 已知限制

- `X-Idempotency-Key`：接收并打印日志，**防重放未实现**

- 资本三接口仍读 MySQL `nanshan_capital` 库（PG 侧已并库但后端未切换）

- 成果为只读域（无创建/编辑接口），对接目标仅支持 achievement / demand 两类

- `/search` 目前仅支持 `type=achievement`

