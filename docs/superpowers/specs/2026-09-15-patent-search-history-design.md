# 专利检索历史设计

## 目标

在专利检索页的检索模式栏和结果区域之间展示最近检索记录。记录仅在用户点击“搜索”或通过键盘提交关键词时产生；每位已登录用户最多保留 10 条，并可在不同设备间读取。点击任一记录会将关键词写回输入框并立即按该记录的检索模式执行查询。

## 范围与交互

- 综合检索和按申请人检索分别保存，避免将申请人名称误用于综合检索。
- 历史以标签形式最多展示两行；视觉超出两行时隐藏后续标签，不引入额外的“展开更多”状态。
- 关键词在保存前 `trim`，空白关键词不写入。
- 相同用户、相同模式、相同关键词只保留一条：再次提交时更新其最近使用时间并置顶。
- 记录在提交检索请求时写入；搜索服务返回空结果不影响记录留存，网络请求未能发起或失败时不写入。
- 本期不提供清空、删除单条、管理历史或匿名历史功能。

## 数据模型

新增 PostgreSQL 迁移 `015_patent_search_history.sql`，创建 `patent_search_history`：

| 字段 | 说明 |
| --- | --- |
| `id` | 主键 |
| `user_id` | 当前用户，外键关联 `app_user(id)` |
| `search_mode` | `keyword` 或 `assignee` |
| `keyword` | 1–128 字符的已规范化检索词 |
| `created_at` | 首次记录时间 |
| `updated_at` | 最近提交时间 |

使用唯一约束 `(user_id, search_mode, keyword)` 支持 UPSERT；使用 `(user_id, search_mode, updated_at DESC)` 索引支持读取。写入完成后，在同一事务中删除该用户该模式按 `updated_at DESC` 排序的第 11 条及以后记录，保证库中最多 10 条。

## API 契约

均挂载在既有 `/api/tech-transfer/v1` 前缀与 `patents` 路由下，并由既有 `identity` 依赖取得用户，不接受客户端传入的用户 ID。

| 方法 | 路径 | 请求 | 响应 data |
| --- | --- | --- | --- |
| `GET` | `/patents/search-history?mode=keyword` | `mode` 为 `keyword` 或 `assignee`，缺省为 `keyword` | `{ list: [{ keyword, mode, updatedAt }] }` |
| `POST` | `/patents/search-history` | `{ keyword: string, mode: 'keyword'|'assignee' }` | `{ keyword, mode, updatedAt }` |

服务端拒绝空白、超过 128 字符或不支持的模式，并沿用统一错误响应。`POST` 是幂等的最新使用更新，而不是追加重复数据。

## 前端数据流

`api/patent.js` 新增获取和保存历史的 API 包装。`patent-list.vue` 在页面加载、切换检索模式后读取对应历史；`onSearch` 校验关键词后先写入历史，再执行现有分页搜索。点击标签会赋值 `keyword`，设置标签保存的模式，并复用 `onSearch` 发起查询。

读取或保存历史失败仅静默降级：检索本身继续执行，页面不会因历史功能不可用而显示错误。历史区域在没有记录时不占额外视觉空间。

## 测试与验证

- 后端：使用隔离测试数据库覆盖用户隔离、模式隔离、去重置顶、十条上限和请求校验。
- 前端：覆盖历史 API 请求、标签点击后填词/切换模式/搜索，以及历史失败不阻断检索。
- 回归：运行专利前端测试、相关后端测试和全量测试集；记录与本功能无关的既有失败。
