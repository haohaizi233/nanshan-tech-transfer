# 南山科转通 统一错误契约（Error Contract）

> T008 产出 · 冻结契约 · 错误码 add-only（只增不改不删）
> 唯一注册表：`core/errors.py`；唯一处理器入口：`core/exception_handlers.py::register_exception_handlers(app)`

## 1. 错误响应结构（所有 API 错误路径唯一格式）

```json
{
  "code": "TT_DEMAND_40401",
  "message": "需求不存在",
  "requestId": "e5adcb6312534e3a",
  "details": [{"field": "name", "message": "Field required"}]
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `code` | string | 稳定业务错误码 `TT_<域>_<HTTP类><序号>`，程序识别用 |
| `message` | string | 安全、稳定、可直接展示给用户的中文描述 |
| `requestId` | string | 请求追踪 ID，与响应头 `X-Request-Id`、后端日志一致 |
| `details` | any（可选） | 仅安全结构化字段（表单校验字段/冲突版本等）；无则整个键不出现 |

成功响应保持既有契约不变：`{"code": 0, "message": "ok", "data": ..., "requestId": "..."}`。

**永不出现**在响应中：traceback、Python 异常类型/repr、SQL、约束名、数据库连接串、内部文件路径、密钥/Token。完整异常细节仅写入服务端日志（`logger.exception`，含 requestId/method/path）。

**例外**：`GET /api/health` 的 degraded 契约为独立格式（HTTP 200 + `code=1` + `data.status=degraded`），属健康检查语义，不适用本错误契约。

## 2. HTTP 状态映射总表

| HTTP | Error Code | 场景 |
|---:|---|---|
| 400 | `TT_COMMON_40001` | 通用业务参数错误（服务层校验） |
| 400 | `TT_COOP_40001` | 不能对自己发布的内容发起对接 |
| 400 | `TT_ADMIN_40001` | 审核驳回必须填写原因 |
| 400 | `TT_INST_40001` | 机构参数无效 |
| 400 | `TT_FILE_40001` | 无效文件 id（文件代理） |
| 401 | `TT_COMMON_40101` | 未提供认证令牌（缺 Authorization/Bearer） |
| 401 | `TT_COMMON_40102` | 认证令牌无效或已过期 |
| 401 | `TT_AUTH_40103` | 宿主凭证无效（bootstrap） |
| 401 | `TT_AUTH_40104` | refresh token 已被吊销 |
| 403 | `TT_COMMON_40301` | 通用无权限访问该资源 |
| 403 | `TT_ACH_40301` / `TT_DMD_40301` | 非成果/需求所有者 |
| 403 | `TT_COOP_40301` | 无权操作此对接（非参与方执行状态操作） |
| 403 | `TT_AI_40301` | 无权查看该 AI 任务 |
| 403 | `TT_ADMIN_40301` | 非管理员（user_role 实时校验） |
| 404 | `TT_COMMON_40401` | 路由不存在 / 路径参数类型不匹配（Flask `<int:>` 兼容，如 `/demands/abc`） |
| 404 | `TT_COMMON_40402` | 通用资源不存在 |
| 404 | `TT_ACH_40401` / `TT_DMD_40401` / `TT_COOP_40401` / `TT_INST_40401` / `TT_AI_40401` / `TT_FAV_40401` / `TT_FILE_40401` / `TT_PATENT_40401` | 各域业务对象不存在（防探测 404 同样走域码） |
| 405 | `TT_COMMON_40501` | Method Not Allowed（如 `POST /api/health`） |
| 409 | `TT_COMMON_40901` | 幂等键冲突，请勿重复提交 |
| 409 | `TT_COMMON_40902` | 资源版本冲突（乐观锁 version 不匹配） |
| 409 | `TT_COMMON_40903` | 数据库约束冲突兜底（唯一/外键竞态漏到框架层） |
| 409 | `TT_ACH_40901` / `TT_DMD_40901` / `TT_COOP_40901` / `TT_INST_40901` | 状态机不允许此操作（非法 submit/approve/cancel/…） |
| 409 | `TT_COOP_40902` | 已有进行中的对接意向 |
| 422 | `TT_COMMON_42201` | Pydantic 请求体校验失败（`details` 列出字段级错误；路径参数不匹配除外→404） |
| 429 | `TT_COMMON_42901` | 请求过于频繁（通用限流） |
| 429 | `TT_AI_42901` | AI 任务创建频率超限（5 次/小时/用户） |
| 500 | `TT_COMMON_50001` | 未预期内部错误（固定文案"服务内部错误"，异常细节只进日志） |
| 502 | `TT_AI_50201` | AI Provider 调用失败 |
| 502 | `TT_FILE_50201` | 文件源站获取失败（代理语义） |
| 503 | `TT_COMMON_50301` | 数据库连接故障（OperationalError/InterfaceError 兜底） |
| 503 | `TT_AI_50301` / `TT_PATENT_50301` | AI / 专利查询服务不可用 |

## 3. 异常 → 响应的转换规则（`core/exception_handlers.py`）

| 异常 | 转换 |
|---|---|
| `BizError`（业务层唯一异常类） | 直接映射其 `code/message/http_status/details` |
| `RequestValidationError` | 全部错误位于 `path` 参数 → 404 `TT_COMMON_40401`（Flask 兼容）；其余（body/query/header）→ 422 `TT_COMMON_42201` + 安全 details（仅 `field`+`message`，绝不携带请求体原文/input 值，上限 20 条） |
| `StarletteHTTPException` | 404→`TT_COMMON_40401`；405→`TT_COMMON_40501`；401/403/429→对应通用码；其余（理论不可达）保底统一结构并保留原 HTTP 状态 |
| `psycopg2.OperationalError` / `InterfaceError` | 503 `TT_COMMON_50301`，连接细节（主机/端口/用户/密码错误）只进日志 |
| `psycopg2.IntegrityError`（Unique/FK/Check Violation） | 409 `TT_COMMON_40903`，约束名与 SQL 只进日志（业务层应尽量前置校验转域码） |
| 其他 `psycopg2.Error` | 500 `TT_COMMON_50001`，完整 traceback 只进日志 |
| 任何未捕获 `Exception` | 500 `TT_COMMON_50001` 固定文案；`logger.exception` 输出 requestId/method/path |

规则：

- **DEBUG 不改变契约**：`settings.DEBUG` 只影响日志详细度/reload/开发工具，任何环境下 API 错误结构一致，绝不外发 traceback。
- **HTTP 状态保持语义**：错误码与 HTTP 状态一一对应，禁止把错误体包在 HTTP 200 里返回。
- **不吞异常**：禁止 `except Exception: raise BizError("TT_COMMON_40001", "操作失败")` 式的一律转 400；分类见上表。
- 服务层应优先抛 `BizError`（`core/errors.py` 便捷构造器），DB 可预期错误（如重复收藏）在业务层转域码，框架层 DB handler 仅为兜底。

## 4. Request ID 链路

- 中间件（`app.py::_set_request_id`）：入站 `X-Request-Id` 若匹配 `^[A-Za-z0-9_-]{8,64}$` 则复用，否则服务端生成 `uuid4().hex`；contextvar 传递（同步端点线程池可读）。
- 每个响应（成功与错误）都带 `X-Request-Id` 响应头（CORS `expose_headers` 已放行，浏览器 JS 可读）；错误体 `requestId` 与之相同。
- 后端错误日志统一格式：`request_id=... method=... path=... status=... code=...`，可由前端报错 requestId 直接检索定位。

## 5. 与推荐约定的差异（项目既有决策，保留）

- 路径参数类型不匹配（`/demands/abc`）→ **404** 而非 422：对齐 Flask `<int:>` 转换器行为（迁移期 203 项测试锁定的约定）。
- query 参数校验：本项目 query 参数由服务层手工解析（非法值取默认值或 400 业务码），不使用 FastAPI typed query，故不产生框架级 query 422。
- 域码前缀为既有缩写（`TT_ACH_`/`TT_DMD_`/`TT_COOP_`/`TT_FAV_`/`TT_INST_`），非全词（`TT_ACHIEVEMENT_` 等），历史既定，add-only 不改。

## 6. 错误码注册表（`core/errors.py`，唯一事实来源）

新增错误码只允许 append；修改/删除/重编号既有码均违规。
