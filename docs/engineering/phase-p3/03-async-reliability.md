# Phase P3-C：AI 异步任务与跨进程 SSE 治理

## 1. 问题确认
- 原 [eval_stream.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/ai/eval_stream.py) 仅使用进程内 `_channels`、`threading.Lock` 与 `queue.Queue`。
- 当独立 AI Worker 进程与 FastAPI SSE 进程分离时，API 进程无法实时接收 Worker 推送的 `content_delta` 与 `terminal` 信号。

## 2. 最小跨进程修复方案
- 保留原有 PostgreSQL 任务队列（`SKIP LOCKED` + Lease + Heartbeat + CAS + 超时回收）与 `eval_stream` 对外接口不变，不引入 Kafka。
- 在 [eval_stream.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/ai/eval_stream.py) 接入基于 Redis List（`RPUSH` + `LTRIM` 有界 512 + TTL `600s`）与 `PUBLISH`/`SUBSCRIBE`（`protocol=2` 兼容 Redis 3.x ~ 7.x）的跨进程通道（`ai:eval:events:{task_id}`、`ai:eval:meta:{task_id}`）：
  - `execution_id` 围栏：[worker.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/ai/worker.py) 传入 `v{version}` 作为 `execution_id`，旧执行者或过期版本产生的迟到增量/终态被拦截；
  - 终态不可逆：一旦写入 `succeeded` / `failed`，后续增量和重复终态一律丢弃；
  - 断线重连回放：`subscribe()` 从 Stream 头构建全文 `snapshot` 并从最新 ID 继续 `XREAD BLOCK`；
  - 优雅降级：未启用 Redis 或 Redis 瞬断时自动回退到进程内队列及 [routes/ai.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/routes/ai.py) 的 DB 巡检；
  - 权限校验：`/ai/evaluation-tasks/{task_id}/stream` 在建立流之前调用 `get_evaluation_task(user_id, task_id)` 校验归属。

## 3. 双进程实测验证
- [test_eval_stream_cross_process.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/tests/test_eval_stream_cross_process.py) 启动真实独立子进程作为 Worker 生产者，主进程作为 SSE 订阅端连接本地 Redis：
  - 验证实时 `content_delta` 跨进程有序送达；
  - 验证旧 `execution_id` 被拦截及终态后增量丢弃；
  - 验证断线重连 `snapshot` 完整回放与 `terminal` 事件；
  - 验证 Redis 不可达时的离线降级路径。
- `test_eval_stream_cross_process.py` + `test_evaluation_api.py` 全部通过，`ruff check` 与 `ruff format --check` 全绿。
