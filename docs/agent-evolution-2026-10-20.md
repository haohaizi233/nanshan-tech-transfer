# 成果顾问二期交付与部署说明

本轮代码实现不等于生产发布。没有修改实际 `.env`、执行生产迁移、开启新模式或调用付费模型。

## 能力与限制

- 服务端建立有界会话上下文，支持最近卡片的确定指代、两项比较、预算/成熟度等条件调整；模糊指代或无历史条件时追问。历史文本不是系统指令，旧卡片只用于定位，事实重新读取。
- 不再因候选不足取消本人排除。预算未知的记录不冒充满足金额条件；预算、机构、成熟度等硬条件不会为凑结果而取消。
- 成果表没有可核实的地域字段，明确要求成果地域时会澄清，不能据机构名称假定实施地点。
- 新持久聊天模式使用 PostgreSQL 队列、会话代际、执行槽与租约，单用户顺序执行；清空、晚到结果、同轮次不同内容与进程失效均有保护。
- 真实进度从同一 Agent pipeline 产生，显示排队、上下文、理解、检索、重排及整理阶段；不提供虚假进度百分比，不展示模型思考。少候选时跳过重排，不能还显示正在重排。
- WAL 仍只保护客户端未确认的问答；业务状态归服务端，浏览次数归只读统计接口，不写成另一套 WAL 业务缓存。
- 成果评估 worker 与聊天 worker 分离；`/ai/match` 仍校验需求所有者，不迁移成聊天队列。

不能保证外部模型的费用恰好一次。新 worker 不会在结果未知的网络失败后再次 POST 整轮；崩溃中的 running 任务失败收敛，不自动重算。用户显式重问产生新轮次，可能新增费用。原有模型层有限瞬时重试仍受同一截止时间约束。

## 接口兼容

公网基础路径是 `https://inanshan.sjhcip.com/api/tech-transfer/v1`，不是 `/h5/api` 或 AI 独立服务内部路径。

原 `POST /ai/chat` 保留。新前端提供 `turnId` 并带 `Prefer: respond-async`：

- 新模式开启：先持久化受理，返回 202，随后 `GET /ai/chat/turns/{turnId}` 查询。
- 新模式关闭：保持原同步响应，前端兼容 200。
- 同一用户同 turnId 重复请求读取已有轮次；请求内容不一致返回 409。不要在网络超时后改 turnId 自动重发。
- 新 GET/202 附带 generation、stage、stageSeq；queued 在旧 status 中投影为 running。终态继续使用 reply/cards/error 字段。
- 卡片显式引用只对具有服务端消息/轮次元数据、且服务端声明支持引用的结果开放。前端临时消息 ID 不可当服务端 ID。
- 页面隐藏停止轮询，回来先确认旧轮次；等待较久不会擅自清除 pending WAL。退出/清空/切账号后的晚到响应不能恢复旧界面。

## 服务端配置

主服务 `.env.example` 已列出新配置，关键值为：

```dotenv
AI_CHAT_RUNS_ENABLED=false
AI_CHAT_STREAM_URL=http://127.0.0.1:8001/internal/ai/chat/stream
AI_INTERNAL_SERVICE_KEY=
AI_CHAT_GLOBAL_SLOTS=4
AI_CHAT_QUEUE_SECONDS=30
AI_CHAT_EXECUTION_SECONDS=55
AI_CHAT_LEASE_SECONDS=20
AI_CHAT_RENEW_SECONDS=5
AI_CHAT_REAP_SECONDS=5
```

Agent 使用双方一致的独立 `AI_INTERNAL_SERVICE_KEY`，`AI_CHAT_MAX_CONCURRENCY=4`。密钥使用独立高强度随机值，由部署者放入服务端密钥配置；不放前端、HTTP 示例、URL 或 Git。私有流 URL 仅允许回环/私网地址，worker 与 Agent 容量必须对齐。

`GET /internal/ai/ready` 使用 `X-AI-Service-Key`，验证鉴权、协议版本、执行预算及模型配置存在，不会调用付费模型。它不证明真实模型提供商此刻一定能成功回答。

Agent 使用只读数据库账号，仅开放必要业务表读取权限；新阶段通过流传给业务 worker，不要求 Agent 写聊天表。Agent 只监听回环/私网；生产 Caddy 新规则拒绝 `/internal/*`。仍需部署者验证防火墙和实际反向代理配置，源文件规则不是已部署的网络隔离证明。

## 发布顺序

1. 备份数据库，在测试环境执行并验证 `tech-transfer-service/migrations/pg/029_ai_chat_execution.sql`；此前 023/026 等已有迁移必须到位。
2. 发布 Agent 并确认带鉴权的私有 readiness；保留旧 `/api/ai/chat` 供旧同步路径使用。
3. 发布主服务和独立聊天 worker，先保持 `AI_CHAT_RUNS_ENABLED=false`。从主服务目录执行：

   ```powershell
   python tools/run_ai_chat_worker.py --health
   python tools/run_ai_chat_worker.py
   ```

4. worker 需独立进程守护、自动启动与日志轮转。`--health` 同时报告配置、数据库、worker 心跳和 Agent 就绪；仅 Web `/health` 成功不算聊天 worker 就绪。
5. 发布 H5/微信小程序前端，在测试用户上验证登录、卡片追问、断网/返回、清空、退出和账号切换。
6. 健康检查通过后灰度开启主服务新模式。没有 worker、密钥或数据库就绪时应拒绝新模式受理，不能产生无人处理的假 queued。

默认不执行任何生产迁移或自动启用新模式。此前头像/微信登录的 027 和审计字段的 028 仍按各自部署说明执行，不因本轮设计而省略。

## 停机与回退

先关闭新模式受理，再等待已接受任务排干；保留 GET 查询与回收任务。新客户端会回到旧同步路径。不要立即删除新表/字段或停止所有回收进程，让客户端永久停在 running。

只保留回收时可使用 `python tools/run_ai_chat_worker.py --reaper-only`。执行进程收到终止信号停止新认领并等待在途任务；意外中断由有效租约和期限收敛为失败。已清空内容的最小轮次哈希墓碑保留 7 天，供拒绝旧请求重放，不回放已删除聊天。

## 可复现验证

Agent 目录：

```powershell
../.venv/Scripts/python.exe -m unittest discover -s tests -v
../.venv/Scripts/python.exe evals/run_advisor_eval.py --output ../outputs/agent-v2-eval-current.json
```

主服务目录：

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_ai_chat_runs.py tests/test_ai_chat_stream.py tests/test_ai_chat_history.py tests/test_ai_modules.py test_ai_card_view_counts.py test_ai_forward_budget.py -q
```

真实数据库测试只接受显式 `AI_CHAT_TEST_DATABASE_URL`，不回退到业务 DB 配置；必须是专用可建/删临时 schema 的测试库：

```powershell
../.venv/Scripts/python.exe -m pytest tests/test_ai_chat_runs_pg.py -q
```

测试在随机 schema 建最小表并应用 023/026/029，覆盖跨进程认领、全局槽位、用户串行、请求冲突、FIFO 上下文、清空/完成竞态、期限和租约失效；最后清理该测试 schema。未显式提供 DSN 时跳过，不能将 skip 视为事务通过。

前端目录执行 `node --test tests/*.test.mjs`，随后顺序执行 `npm run build:h5`、`npm run build:mp-weixin`。资源紧张时可限制 `NODE_OPTIONS=--max-old-space-size=512`、`UV_THREADPOOL_SIZE=1`、`GOMAXPROCS=2`；不要并行构建或结束用户的其他程序。

80 条评测使用固定合成资料和可控模型替身，覆盖检索、多轮、卡片指代、无结果/冲突、操作指南及注入；基线来自 `c2d0dc0` 的归档代码。报告包含语料哈希，基线比较拒绝不同语料或不同用例顺序。离线延迟不是网络/模型延迟，未知 token 用量为 null 而不是零。

真实模型评测需显式 `AI_EVAL_ALLOW_LIVE=1` 与 `--live`，可能产生费用；本轮没有执行。真实手机、生产模型、真实反向代理和生产数据库只读授权仍需部署验收。

## 2026-10-21 审查收尾记录

- 修正预算否定比较、性能参数误判为金额、礼貌查询及明确换方向的识别；引用依赖字段变化后不再复制旧解读。
- 成功仅由有效终稿确认，不先发送成功阶段再因期限返回失败。网络绝对计时从连接打开前开始，覆盖缓慢响应头与 HTTP/1.0 关闭连接正文；readiness 复用同一受限传输。
- 清空/退出/切页、其他设备代际变化以及明确未受理拒绝不再卡住本地问答；结果未知时仍只查询原 turnId，不盲目重新生成。
- 旧同步路径在迁移存在时也检查代际、墓碑及请求指纹；无 turnId 的成功/失败和需求匹配晚到写入同样被隔离。旧同步消息不冒充具备定位映射的可引用持久卡片。
- history 顶层返回服务端 generation 和引用能力，清空后的空历史及未执行 029 的旧库兼容均已覆盖。

最后独立执行的验证：

| 验证 | 结果 |
| --- | --- |
| Agent unittest 全套（含真实 Agent 流到业务消费的合成契约） | 71 项通过 |
| 固定合成离线评测 | 80/80；相同语料的旧基线 54/80；不是生产模型效果测量 |
| 主服务本轮、历史、模块、路由、浏览统计、转发预算及网络期限定向回归 | 179 项通过，其中 31 项真实 PostgreSQL 测试，无 skip |
| 前端全量 node:test | 276 项中 272 通过，4 项既有失败 |
| H5 / 微信小程序顺序生产构建 | 均成功 |
| Python 编译 / CRLF 感知空白检查 | 通过 |
| 改动中的聊天存储/执行/上下文/worker及新增网络测试定向 Ruff | 忽略既有中文标点规则与 CLI 导入位置规则后通过；不是全项目 lint 通过声明 |

前端已有失败分别是 `api-base.test.mjs:7`、`media-url.test.mjs:23`、`patent-search.test.mjs:92` 的 8076/8025 端口断言，以及 `business-page-freshness.test.mjs:121` 的详情请求次数断言（3/2）；未修改无关接口配置或业务详情页以迁就测试。

实际数据库验证仅使用本机专用临时集群与随机 schema，不使用业务数据库；验证后关闭测试集群。网络期限测试也只访问本机合成 HTTP 服务，没有真实付费模型调用。原始验证日志位于本地忽略的 `outputs/agent-v2-final-*`，生产迁移、私有密钥配置、worker 启动和开启新模式仍由部署流程完成。
