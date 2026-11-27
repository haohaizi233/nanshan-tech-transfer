# Phase P3-8：性能测试与媒体/SQL 治理报告

> 说明：以下压测数据均基于本机受控测试环境（Windows / FastAPI `TestClient` / PostgreSQL 18.6），仅用于本地基线对照，**不代表生产服务器承载容量**。未经授权不得对生产站点执行高并发压测。

## 1. 本机并发基线（1 / 5 / 10 / 25 并发）

| 端点 | 并发 | 请求数 | P50 (ms) | P95 (ms) | P99 (ms) | RPS | 错误数 |
|---|---:|---:|---:|---:|---:|---:|---:|
| `/health/live` | 1 | 20 | 2.50 | 6.28 | 6.28 | 138.7 | 0 |
| `/health/live` | 5 | 20 | 17.77 | 22.51 | 22.51 | 264.7 | 0 |
| `/health/live` | 10 | 40 | 33.83 | 50.30 | 50.70 | 271.6 | 0 |
| `/health/live` | 25 | 100 | 135.37 | 228.85 | 243.98 | 175.3 | 0 |
| `/health/version` | 1 | 20 | 2.48 | 6.55 | 6.55 | 296.7 | 0 |
| `/health/version` | 5 | 20 | 19.81 | 24.68 | 24.68 | 241.6 | 0 |
| `/health/version` | 10 | 40 | 30.90 | 44.87 | 45.64 | 294.4 | 0 |
| `/health/version` | 25 | 100 | 96.48 | 130.68 | 138.53 | 239.3 | 0 |
| `/health` (PG18 `SELECT 1`) | 1 | 20 | 3.80 | 8.57 | 8.57 | 76.0 | 0 |
| `/health` (PG18 `SELECT 1`) | 5 | 20 | 71.27 | 87.00 | 87.00 | 80.5 | 0 |
| `/health` (PG18 `SELECT 1`) | 10 | 40 | 352.31 | 706.32 | 706.93 | 26.4 | 0 |
| `/health` (PG18 `SELECT 1`) | 25 | 100 | 1425.00 | 1572.59 | 1610.47 | 21.8 | 0 |

- 说明：`TestClient` 未触发 `lifespan` 初始化连接池时按懒连接路径执行，高并发下放大了建连耗时；生产通过 `uvicorn` lifespan 预建连接池。

## 2. 数据库热点与 SQL 执行计划
- AI 检索主路径（`MATERIALIZED` CTE + `COLLATE "C"` + `base_where` 下推）在 PostgreSQL 18.6 上实测：
  - `Planning Time: 0.400 ms`，`Execution Time: 0.215 ms`（100 行样本、`shared hit=5`）。
  - 其余生产业务表未授权在生产库直接 `EXPLAIN ANALYZE`，保持只读分析纪律。

## 3. 媒体缩略图与缓存边界加固
- [modules/file/service.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/modules/file/service.py)：
  - 设置 `Image.MAX_IMAGE_PIXELS = 25_000_000` 并显式捕获 `Image.DecompressionBombError`，防范解压炸弹；
  - `get_uploaded_thumbnail()` 增加按 `(file_id, card_preview)` 分段锁 `_thumbnail_lock()`，防止首次并发请求重复解码踩踏；
  - 保持 `.tmp` + `temporary.replace(target)` 原子写入及删除清理。
- [routes/file.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/routes/file.py)：保持受权文件响应头 `Cache-Control: no-store`。
- 单元测试：[test_p3_ops_and_media.py](file:///d:/Users/Administrator/Desktop/南山小程序/tech-transfer-service/tests/test_p3_ops_and_media.py)（2 passed）。
