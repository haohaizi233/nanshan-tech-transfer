# AI Runtime v1 重构 · Gap Analysis

> 基于对 `nanshan-ai-agent/app/**` 全量源码与主后端 `tech-transfer-service/routes/**`、`modules/**` 实际接口的扫描，不臆测接口。分析阶段不修改代码。

## 0. 扫描范围与结论速览

### 已扫描文件（AI Runtime 侧）
| 文件 | 职责 | 关键问题 |
|---|---|---|
| `app/main.py` | FastAPI 入口、`/api/ai/chat`、`/health`、`/health/db` | 直连 DB；硬编码业务分支；print 日志 |
| `app/router.py` | LLM 意图分类 + 参数抽取 | 仅 3 intent；机械要求 keywords；无 QueryPlan/硬软筛 |
| `app/reranker.py` | LLM 重排 | 候选仅 20 条；无结构化打分；无 reason |
| `app/llm_client.py` | 调 Qwen | 已有退避重试；但用 print；无 Provider 抽象 |
| `app/schemas.py` | Pydantic 模型 | IntentType 仅 3 值；无 meta；无 QueryPlan |
| `app/services/achievement_service.py` | psycopg2 拼 SQL 检索成果 | 直连 DB；静态同义词表；ORDER BY created_at DESC 主导召回 |
| `app/services/demand_service.py` | psycopg2 拼 SQL 检索需求 | 同上 |
| `app/database.py` | psycopg2 连接（readonly） | DB 凭据在 AI Runtime；错误边界 |
| `app/formatters.py` | 卡片格式化 + 脱敏 | 自行脱敏（与主后端重复且可能漂移） |
| `app/config.py` | env 读取 | 含 DB_* 凭据 |

### 已扫描文件（主后端侧，确认可复用 Tool Endpoint）
- `routes/search.py` — `GET /api/tech-transfer/v1/search`（需 identity 登录）
- `routes/achievement.py` — `GET /achievements`、`GET /achievements/{id}`、`GET /achievements/categories`、`GET /achievements/industries`（optional_identity，游客可访问）
- `routes/demand.py` — `GET /demands`、`GET /demands/{id}`（optional_identity，游客可访问）
- `modules/achievement/service.py`、`modules/demand/service.py`、`modules/search/service.py`
- `core/middleware.py`（identity / optional_identity / JWT）、`core/masking.py`（服务端脱敏）

### 结论速览
当前 AI Runtime 实质是 LLM Router → psycopg2 ILIKE → LLM Reranker → Card Formatter 的线性管道，不是 Agent。与目标架构存在 13 类 Gap，详见 §1–§13。

---

## 1. AI 直连数据库（最高优先级 Gap）

**现状**：
- `app/database.py:14` 直接 `psycopg2.connect(host/port/dbname/user/password)`，DB 凭据由 `app/config.py:14-18` 从 env 读取，AI Runtime 持有完整 DB 凭据。
- `app/services/achievement_service.py:272-292` 与 `demand_service.py:209-228` 手拼 SQL（SELECT ... FROM achievement/demand WHERE ... ORDER BY created_at DESC LIMIT 50）。
- `app/main.py:39-58` `/health/db` 直接 `cur.execute("SELECT 1")`。

**违反第一原则**：
- AI Runtime `import psycopg2`（database.py、两个 service）。
- AI Runtime 持有 `DB_PASSWORD`。
- AI Runtime 拼 SQL，绕过主 FastAPI 的 permission（`can_access_target`）与 masking（`mask_contact`）。
- 成果/需求可见性（status='published'）由 AI Runtime 自判，与主后端 `list_achievements`/`list_demands` 重复且可能漂移。

**目标路径**：Agent → FastAPI Tool Client → tech-transfer-service → Domain Service → PostgreSQL。

---

## 2. Foundation Skill 接入

**现状**：无 Skill Loader 概念。`router.py` 把意图识别 + 参数抽取塞进一个 263 行巨型 `ROUTER_SYSTEM_PROMPT`，无技能注册、无版本、无冻结/候选区分。

**目标**：加载已冻结 `tech-transfer-domain v0.1.1`、`agent-tool-policy v0.2.1`；`achievement-evaluation v0.1.1` 仅 feature flag 候选，不默认生产。

**Gap**：当前无任何 Skill 抽象；评估能力（`/ai/evaluation-tasks`）实际在主后端 `routes/ai.py`，AI Runtime 内没有评估技能，需作为候选技能通过 flag 接入。

---

## 3. Router → Planner

**现状**（`router.py`）：
- `IntentType` 仅 `search_achievement` / `search_demand` / `out_of_scope`（`schemas.py:5-9`）。
- 缺：`GET_ACHIEVEMENT_DETAIL`、`GET_DEMAND_DETAIL`、`COMPARE_RESULTS`、`EXPLAIN_RESULT`、`EVALUATE_ACHIEVEMENT`、`CLARIFY`。
- `main.py:113` `if not route.keywords: return "请告诉我你想查询的技术方向…"` —— 机械要求关键词，与"信息不足才 CLARIFY"相悖。
- 不支持多步：示例"找适合医院康复科的机器人技术，预算100万以内，成熟一点，给我最相关5个并解释原因"无法一次完成（条件理解→检索→rerank→解释），因为解释能力不存在。

**Gap**：无结构化 Intent 枚举；无 Planner；无多步编排；无 CLARIFY 语义。

---

## 4. 查询解析（QueryPlan / 硬软筛）

**现状**（`router.py` prompt + `RouteResult`）：
- 抽取 keywords/organization/region/min/max_price_wan/min/max_budget_wan/min_maturity/coop_modes/limit。
- 无 `technicalConcepts` / `applicationScenarios` 区分。
- 无 hardFilters / softPreferences 区分：prompt 把"中试完成以上"映射为 min_maturity（硬筛），但"最好已经中试"也会被同一规则当成硬筛 → 模型会把 preference 当 hard filter。
- `reason` 字段存在但未用于决策。

**Gap**：无 QueryPlan 结构；硬软筛未区分；模型可能编造用户未提供的硬筛选。

---

## 5. Retrieval 召回

**现状**（`achievement_service.py`）：
- 召回主路径是静态 5 类同义词表（`KEYWORD_EXPANSIONS` 仅 人工智能/机器视觉/生物医药/芯片 5 类）+ ILIKE。
- `expand_keywords` 命中表内才扩展，表外词原样返回 → 语义召回能力极弱。
- SQL `ORDER BY created_at DESC LIMIT 50`（`achievement_service.py:290-291`、`demand_service.py:226-227`）—— 创建时间主导候选池，相关度评分（`_calculate_score`）只在取回的 50 条内排序，新但无关的成果会挤掉旧但相关的成果。
- 召回字段含 `contact_name/contact_phone/contact_email`（`achievement_service.py:284-286`）—— 原始联系方式进入 AI Runtime 内存。

**目标**：Recall 30~50 → semantic rerank → Top 5~10；复用主后端 Search API；召回综合 title/techIntro/innovationPoints/applicationFields/category/tags/organization；不得 ORDER BY created_at DESC LIMIT 50 后才评分；静态 synonym 仅作 fallback。

**Gap**：召回由 created_at 主导；同义词表是核心而非 fallback；召回即拉取 PII。

---

## 6. Reranker v2

**现状**（`reranker.py`）：
- `rerank_results` 最多送 20 条（`candidates[:20]`，line 178），不满足 30~50 候选。
- 输出仅 `{results:[{id}]}`（prompt line 40-46）—— 无 `relevanceScore/technicalMatch/applicationMatch/constraintMatch/reason`。
- `_achievement_for_llm` / `_demand_for_llm` 裁剪了联系方式，但仍发送 organization、pricing_mode、price_min/max_wan、budget_min/max_wan 等；未显式声明禁止字段清单，且裁剪逻辑分散。
- 排序优先级在 prompt 里写了，但无结构化输出校验，模型可能"命中一个词就高相关"。
- 最终 ID 来自 candidate map（line 223-249），这点已正确（不创造结果）。

**Gap**：候选数不足；无结构化打分；无 reason；安全裁剪未规范化。

---

## 7. Tool Result 安全

**现状**：
- 无 Tool Result 概念（因为直连 DB）。
- `formatters.py` 自行脱敏（mask_name/phone/email），与主后端 `core/masking.py` 逻辑重复且实现不同（如 mask_email 对 local<=2 处理不同）。
- 无 prompt-injection 防护：若未来 Tool 返回文本含"忽略之前规则/调用另一个接口/输出数据库密码"，当前无任何隔离。
- 联系方式明文与否由 AI Runtime 自己 `format_contact` 决定，而非主 FastAPI。

**Gap**：无 Tool 不可信数据隔离；无注入防护；脱敏权威不在主后端。

---

## 8. Response Composer

**现状**（`main.py:174-179` 等）：
- 仅返回 "找到 {n} 条相关科技成果。"，无自然语言摘要：无"为什么推荐/匹配在哪里/哪些条件不完全匹配/信息缺失项"。
- 无 `meta` 字段（`ChatResponse` 仅 success/intent/message/data，`schemas.py:79-83`）。
- 事实来自 DB 行（直连），未来须来自 Tool Result。

**Gap**：无 Composer；无摘要；无 meta；无 clarificationRequired/toolCalls/resultCount。

---

## 9. LLM Provider

**现状**（`llm_client.py`）：
- 已有退避重试（`_RETRY_STATUS={502,503,504,429}`，`_RETRY_TIMES=3`，指数退避 1/2/4s）—— 基本符合。
- 但用 `print(...)`（line 56-57、66）—— 违反"禁止 print"。
- 无 `LLMProvider` 抽象/接口；`chat_completion` 是模块函数，不易替换 provider。
- 配置散在 settings.LLM_API_URL/KEY/MODEL，无 timeout/temperature/max_tokens 统一注入（timeout 硬编码 90）。
- JSON/Schema 语义错误会被当异常抛出但不会无限重试（重试只针对网络状态码）—— 这点已正确。

**Gap**：无 Provider 接口；print 日志；配置不统一。

---

## 10. Observability

**现状**：
- 全程 print（main.py:75,86,150,207；reranker.py:215；llm_client.py:56,66）。
- 无 requestId / runId。
- 无结构化日志；无 route decision / tool calls / latency / candidate count / rerank count / model / token usage / retry / error type 记录。
- 无"禁止记录 API Key / raw phone / email / wechat"的显式约束。

**Gap**：无 observability 体系；全 print。

---

## 11. 测试

**现状**：`nanshan-ai-agent` 内无任何测试目录/文件（扫描确认 `app/` 下仅源码，无 tests/）。

**目标测试矩阵**：router 语义 / tool 路由 / 硬软筛 / 召回 / 重排 / 注入 / PII 泄露 / tool 失败 / LLM 畸形 JSON / 无结果 / 追问 clarify。

**重点用例**（须覆盖）："找AI成果" / "有没有用AI做医疗影像的" / "100万以内并且中试完成以上" / "最好成熟一些" / "给我比较前3个" / "这个为什么推荐" / "有没有类似第一个但更便宜的" / "某某实验室有什么成果"。

**Gap**：测试覆盖为 0。

---

## 12. 强制静态扫描目标

| 扫描项 | 当前值 | 目标 |
|---|---|---|
| `psycopg2` import | 3 处（database / 2 service） | 0 |
| direct SQL（手拼 SELECT/WHERE） | 2 处（achievement/demand service） | 0 |
| `DB_PASSWORD` 在 AI Runtime | 1 处（config.py） | 0 |
| raw contact 送入 LLM | 召回阶段拉取 contact_name/phone/email 进内存；rerank 阶段已裁剪 | 0（召回阶段也不得拉取） |
| hardcoded Gold case | 0（未发现） | 0 ✅ |
| Hermes 生产依赖 | 0（未发现） | 0 ✅ |

---

## 13. 兼容性

**现状**：
- `POST /api/ai/chat` 存在，入参 `ChatRequest{message, exclude_owner_user_id}`，出参 `ChatResponse{success,intent,message,data}`。
- 前端 `ai-match.vue` / `api/ai.js` 依赖此契约；`tech-transfer-service/routes/ai.py` 代理转发并入库。
- `data` 为卡片数组（card_type/id/title/organization/description/maturity/price/application_fields/contact 等，见 formatters.py）。

**目标**：保留 `POST /api/ai/chat`；扩展 response 为 `{success,intent,message,data,meta}`，`meta={requestId,clarificationRequired,toolCalls,resultCount}`；不暴露内部 Prompt / CoT。

**Gap**：无 meta；卡片字段须保持与前端兼容（card_type/id/title/organization/description/maturity/price/application_fields/contact 等键名不变）。

---

## 14. 可复用 Tool Endpoint 清单（扫描主后端所得，非臆测）

| Tool 能力 | 主后端路由 | 鉴权 | 支持的查询参数 | 可用性 |
|---|---|---|---|---|
| 成果列表 | `GET /api/tech-transfer/v1/achievements` | optional_identity（游客可用） | keyword、category、maturityLevel（精确）、industryId、page、pageSize | ✅ 可复用 |
| 成果详情 | `GET /api/tech-transfer/v1/achievements/{id}` | optional_identity | — | ✅ 可复用 |
| 成果分类字典 | `GET /api/tech-transfer/v1/achievements/categories` | optional_identity | — | ✅ 可复用 |
| 成果产业目录 | `GET /api/tech-transfer/v1/achievements/industries` | optional_identity | — | ✅ 可复用 |
| 需求列表 | `GET /api/tech-transfer/v1/demands` | optional_identity | keyword、categoryCode、includeMine、sort、page、pageSize | ✅ 可复用 |
| 需求详情 | `GET /api/tech-transfer/v1/demands/{id}` | optional_identity | — | ✅ 可复用 |
| 统一搜索 | `GET /api/tech-transfer/v1/search` | identity（需登录 token） | q、type、categoryCode、maturityLevel、page、pageSize | ⚠️ 需 token |

### 主后端列表接口返回字段（用于 rerank，已扫描确认）
**成果列表项**（`_row_to_list_item`）：id, title, sourceOrgName, orgId, orgCertified, categoryName, categoryCode, industries, techIntro（截断 120 字）, maturityLevel, maturityDesc, applicationFields, pricingMode, priceMinWan, priceMaxWan, viewCount, publishedAt, isMine, platformAssisted, cover。不含联系方式（列表层不返回 contact）。
**成果/需求详情**：含 contact，但 contact_visible=False 时由主后端 mask_contact 脱敏（仅 owner / 已接受对接方可见明文）。

### ⚠️ Tool Endpoint 能力 Gap（须记录，不得伪造接口）
1. **价格区间筛选**：`/achievements` 不支持 minPriceWan/maxPriceWan。AI 现有 SQL 支持 → Gap。
2. **预算区间筛选**：`/demands` 不支持 minBudgetWan/maxBudgetWan。AI 现有 SQL 支持 → Gap。
3. **机构名筛选**：`/achievements`、`/demands` 不支持 organization 参数（仅 keyword 命中 source_org_name）。→ Gap。
4. **地域筛选**：`/demands` 不支持 region 参数。AI 现有 SQL 支持 → Gap。
5. **合作方式筛选**：`/demands` 不支持 coop_modes 参数。AI 现有 SQL 支持 → Gap。
6. **成熟度"最低"语义**：主后端 maturityLevel 是精确匹配，AI 现有 min_maturity 是"≥某级"。→ Gap。
7. **多关键词/同义词扩展**：主后端仅单 keyword，AI 现有 expand_keywords 多词 OR + 同义词。→ Gap（召回可能下降）。
8. **techIntro 截断**：列表项 techIntro 仅 120 字，rerank 可能信息不足；详情有全文但需额外调用。→ Gap。
9. **自排除**：主后端列表不按 owner_user_id 排除；AI 现有 exclude_owner_user_id。→ 须在 Tool Client 侧对返回结果做后过滤（按 isMine / platformAssisted 或 owner 字段），记录为 Gap。

### 处理策略（不在分析阶段实施）
- 能力 1–8：**不伪造接口**。Planner 把主后端不支持的硬筛降级为"召回后软筛 / rerank 约束"，并在 Composer 摘要里如实说明"已按 XX 软筛"。
- 能力 9：Tool Client 拉取列表后，在 AI Runtime 侧按 `isMine`/`platformAssisted` 过滤掉当前用户自己的内容（exclude_owner_user_id 由调用方传入）。
- `/search` 需 token，AI Runtime 无用户 token，**优先用 `/achievements`、`/demands`（optional_identity）**。

---

## 15. 总结：Gap 优先级与重构边界

| 优先级 | Gap | 重构动作（Phase 2） |
|---|---|---|
| P0 | AI 直连 DB（§1, §12） | 删 psycopg2/DB 凭据/拼 SQL；新建 Tool Client 走主后端 HTTP |
| P0 | PII 进内存（§5, §7, §12） | 召回不拉 contact；rerank 显式禁止字段清单 |
| P1 | Router→Planner（§3, §4） | 结构化 Intent + QueryPlan + 硬软筛 + CLARIFY |
| P1 | Retrieval（§5） | 两阶段 recall→rerank；复用主后端列表 API；synonym 降级 fallback |
| P1 | Reranker v2（§6） | 30~50 候选；结构化打分 + reason |
| P1 | Composer + meta（§8, §13） | 自然语言摘要 + meta；保持卡片键名兼容 |
| P2 | LLM Provider（§9） | LLMProvider 接口 + 结构化日志 + 统一配置 |
| P2 | Observability（§10） | requestId/runId + 结构化日志，禁记密钥/PII |
| P2 | Skill Loader（§2） | 冻结技能注册 + 评估候选 flag |
| P3 | 测试（§11） | 全矩阵测试套件 |
| P3 | 静态扫描（§12） | psycopg2=0 / SQL=0 / DB_PASSWORD=0 / raw contact=0 |

**重构边界**：仅改 `nanshan-ai-agent/app/**`；主后端 `tech-transfer-service` 在本阶段**不新增接口**（缺失 Tool 仅记录 Gap），仅复用现有 optional_identity 列表/详情接口。`POST /api/ai/chat` 契约保持兼容（扩展 meta）。

**分析完成。下一阶段进入设计与实现，不再修改本分析文档。**
