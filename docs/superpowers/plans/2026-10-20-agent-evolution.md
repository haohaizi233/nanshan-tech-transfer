# Agent 二期实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保留旧同步接口的前提下，实现可信多轮、严格推荐、持久聊天执行和真实阶段反馈。
**Architecture:** Agent、业务持久调度、前端恢复分别实现，并以本文约定的 JSON 契约集成；复用 PostgreSQL，不新增外部框架。真实数据库不可用时保留可运行的集成测试并明确报告未验收，不打开生产开关。
**Tech Stack:** FastAPI、Pydantic、psycopg2、PostgreSQL、Vue/uni-app、unittest/pytest、node:test。
**Spec:** `docs/superpowers/specs/2026-10-20-agent-evolution-design.md`

## Global Constraints

- 上下文整体 8000 字符，4 条消息各 800 字符，10 个卡片定位各 80 字符标题，查询状态 2000 字符。
- 最多 50 个 SQL 候选、20 个重排候选、10 张返回卡片；不放宽硬条件或本人排除。
- 单用户一个 running 加 3 个 queued；总槽位默认 4；排队 30 秒、执行 55 秒、租约 20 秒、续租/回收 5 秒。
- NDJSON 单事件 64 KiB、result 1 MiB、整体 2 MiB；心跳不超过 5 秒但不延长截止时间。
- `AI_CHAT_RUNS_ENABLED` 默认 false，新增内部端点使用 `X-AI-Service-Key` 对应 `AI_INTERNAL_SERVICE_KEY`。
- 不推送/部署，不运行生产迁移，不暴露密钥，不调整无关失败测试；本轮按用户“直接执行”在当前目录实施，不另开分支。

## Review Focus

1. 多标签页相同 turnId 不同问题：409，绝不复用错误答复（任务 2）。
2. 卡片排队期间下架：重新验证，澄清而不泄露旧资料（任务 1/2）。
3. NDJSON 无终稿但持续心跳：按总期限失败，不永久运行（任务 2）。
4. 清空同时新受理/完成：代际锁和墓碑防止复活（任务 2/3）。
5. 候选为空/金额未知：不隐式降级硬条件、不虚构成功（任务 1/4）。

## 共享接口（实施前冻结）

- Agent `ChatRequest` 增加可选 `context`，结构为 `{schemaVersion:1,generation:int,queryPlan:dict,cards:[{card_type,id,title,messageId}],messages:[{role,content}],reference?:{card_type,id}}`。reference 仅由主服务校验客户端 messageId/cardType/cardId 后生成；历史卡片仅定位，不作为当前事实。
- `ChatResponse` 可选 `queryPlan` 为 RouteResult 序列化结构；原 `success/intent/message/data` 保持不变。
- 私有 `POST /internal/ai/chat/stream` 请求为 ChatRequest 字段加必填 executionId；阶段事件 `{type:'stage',executionId,stage,sequence}`，心跳 `{type:'heartbeat',executionId}`，终稿 `{type:'result',executionId,result:{success,intent,message,data,queryPlan?}}`，失败 `{type:'error',executionId,reason}`。
- 公网仍为 `/api/tech-transfer/v1/ai/chat`；新前端发送 `Prefer: respond-async` 和原 message/turnId，可选 reference `{messageId,cardType,cardId}`；202 `data={turnId,status:'running',generation,stage,stageSeq,pollAfterMs:2000}`。
- GET turn 终态旧字段不变，新增 generation/stage/stageSeq/messageId；阶段枚举 queued/context/routing/retrieving/reranking/formatting/succeeded/failed。旧 queued 状态对公网映射 running。

### Task 1: Agent 上下文、硬条件和真实事件

**Files:** `nanshan-ai-agent/app/{schemas,main,advisor,router,runtime_trace,config}.py`；新 `conversation.py`、`internal_stream.py`；`app/services/*_service.py`；对应 `tests/test_conversation.py`、`tests/test_internal_stream.py`。
**Interfaces:** 消费共享 context；产出 queryPlan 及上述私有流；`_process_ai_chat(ChatRequest)` 保留。

- [x] 先加失败测试：确定/模糊指代、预算继承/清除/冲突、指南优先、下架重取、原文注入、无本人排除回退、非法/超长 context、流鉴权和阶段/终稿。
- [x] 在 Agent 目录用 `../.venv/Scripts/python.exe -m unittest discover -s tests -v` 观察新增用例失败。
- [x] 实现有界结构化上下文解析、参数化目标重读和经过校验的条件合并；新话题独立路由；保留旧单轮。
- [x] 实现 Observer 真实阶段、私有 NDJSON 同一 pipeline、预算/容量保持真实 Future 生命周期，密钥常量时间比较。
- [x] 回归 Agent 全套；记录可复现结果，不调用付费模型。

### Task 2: 业务持久调度、上下文与内部流消费

**Files:** 新 `tech-transfer-service/migrations/pg/029_ai_chat_execution.sql`、`modules/ai/chat_runs.py`、`chat_context.py`、`chat_runner.py`、`tools/run_ai_chat_worker.py`；修改 `routes/ai.py`、`modules/ai/chat_store.py`、`core/request_schemas.py`、`config.py`、`.env.example`；新 `tests/test_ai_chat_runs.py`、`tests/test_ai_chat_stream.py`、`tests/test_ai_chat_runs_pg.py`。
**Interfaces:** 消费共享私有流；`submit_run(user_id,turn_id,message,reference=None)->dict`、`get_run(user_id,turn_id)->dict|None`、`clear_runs(user_id)->dict`；worker `claim_one()/renew_run()/finish_run()/reap_runs()`；公网上新增字段保持兼容。

- [x] 先写并运行失败测试：schema/请求指纹、reference 归属、202/旧路径、流界限/未知结果不重试。
- [x] 实现 029 加法迁移：session 代际、执行槽、worker 心跳、run 元数据及墓碑；已有同步模式单独标记。
- [x] 实现 session 锁下受理、FIFO/限流、有效租约认领与提交、墓碑、清空和超时回收；连接不跨模型调用。
- [x] 实现主服务上下文构建/引用校验和有界私有流读取，仅一次 POST；续租与实时阶段落库。
- [x] 实现 worker CLI/配置自检、持久心跳健康检查、优雅停止；旧 GET/history/clear 兼容。
- [x] 用 `../.venv/Scripts/python.exe -m pytest tests/test_ai_chat_runs.py tests/test_ai_chat_stream.py tests/test_ai_chat_history.py -q` 验证；真实 PG 用独立 `AI_CHAT_TEST_DATABASE_URL` 显式开启临时 schema 测试，不连接/变更生产库。

### Task 3: 前端阶段、引用与恢复

**Files:** `南山小程序/南山/subpackages/tech-transfer/api/ai.js`、`ai-chat-wal.mjs`、`pages/ai-match/ai-match.vue`；新 `api/ai-chat-progress.mjs` 及 `tests/ai-chat-progress.test.mjs`，扩展相关已有测试。
**Interfaces:** 兼容 200 和 202；依共享 API 轮询阶段，不自动重发 pending；显式引用由服务端验证。

- [x] 先写失败测试：阶段倒序、跨代际/账号结果、未知阶段、成功确认 WAL、隐藏停止、旧响应兼容、相同消息 ID 不伪造引用。
- [x] 实现纯阶段状态归并和实际阶段文案，接入活动轮次轮询；未确认 WAL 不覆盖；清空 generation 与本地请求版本一起失效。
- [x] 为有服务端 messageId 的历史卡片提供“介绍这项”入口；即时结果只有服务端 ID 时可引用，不能使用前端临时 ID 充数。
- [x] `node --test tests/ai-chat-progress.test.mjs tests/ai-chat.test.mjs tests/ai-match-initialization.test.mjs tests/ai-advisor.test.mjs` 及全量测试；顺序构建 H5/微信小程序。

### Task 4: 评测、集成与交付

**Files:** 新 `nanshan-ai-agent/evals/advisor_cases.json`、`evals/run_advisor_eval.py`；`tests/test_advisor_eval.py`；新 `docs/agent-evolution-2026-10-20.md`；按实际实现补 `http/08-ai.http`、部署 worker 说明和观测回归。

- [x] 先以失败测试断言固定至少 80 个真实可解释标注 fixture、分类数量及无虚构 ID/硬条件违规；再实现离线 runner 和相同输入旧/新基线指标。
- [x] 补全跨组件契约测试、故障注入及源码审查；修复集成差异，不削弱安全边界以通过测试。
- [x] 分别运行 Agent、业务选定 pytest、前端定向/全套、两端构建、compileall 和 git diff 空白检查；记录既有失败及 PG/真机不可用项目。
- [x] 做独立最终审查，修复重要问题后重跑相关测试；新模式默认关闭，交付配置、迁移、worker、灰度及回退步骤，不宣称已经上线。
