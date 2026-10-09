# 南山科转通 数据库会话与事务边界（DB Session）

> T007 产出 · 唯一实现：`db.py`（psycopg2 `ThreadedConnectionPool`）
> 配置入口：`config.py`（`DB_POOL_MIN` / `DB_POOL_MAX` / `DB_CONNECT_TIMEOUT`）
> 故障恢复验证基线见 §7（Final Hardening，2026-09-04 实测）

## 1. 架构

```
FastAPI lifespan ──启动──▶ init_pool() ──▶ ThreadedConnectionPool（进程内单例）
                              │                min=DB_POOL_MIN(2)  max=DB_POOL_MAX(10)
同步端点（线程池工作线程）      │
  └─ get_cursor()/transaction() ─▶ get_conn() ─▶ _acquire_conn(): pool.getconn()
                                       │                │
                                       │                └─ PoolError → OperationalError → 503
                                       └─ finally: _release_conn(): pool.putconn(conn)
                                                        ├─ 空闲池未满(< min) 且 IDLE        → 回池复用
                                                        ├─ 空闲池未满(< min) 且事务残留/错误 → rollback 后回池
                                                        ├─ 空闲池未满(< min) 且 UNKNOWN     → 关闭（坏连接）
                                                        └─ 空闲池已满(≥ min)               → 直接关闭
                     ──退出──▶ close_pool()
```

关键约束与设计决定：

| 项 | 决定 | 原因 |
|---|---|---|
| 借出/归还同线程配对 | `with` 块内配对（项目约定） | psycopg2 2.9 池按唯一 key + `id(conn)` 记账（`putconn` 以连接对象反查 key），**不要求**同线程；但保持同线程配对可避免嵌套借出意外占用并发额度，语义更清晰 |
| 嵌套借出 | 不推荐（`transaction()` 内再调 `get_cursor()` 等） | psycopg2 2.9 下同线程嵌套借出会拿到**另一个**连接并计入 `DB_POOL_MAX`，可能触发池耗尽；实测行为见 §7 |
| 懒初始化 | `_get_pool()` 首次访问自动建池 | 脚本（etl_demands）/测试（TestClient 不触发 lifespan）不经 FastAPI 也能用 |
| DB 不可用时启动 | 降级为空池（minconn=0），不阻塞服务（仅开发环境语义） | 保持 health degraded 契约（HTTP 200 + `data.status=degraded`），DB 恢复后懒建连接自愈；production 是否 fail-fast 见 §9 RELEASE CONFIG DECISION |
| 死连接感知 | TCP keepalive（30s idle / 10s interval / 3 次探测）+ `putconn` 按 `transaction_status` 处理 | 数据库重启/网络中断后，坏连接被关闭并由池重建，无需重启服务 |
| 池耗尽 | `PoolError` → `OperationalError("connection pool exhausted")` | 复用 T008 错误契约：Operational → 503 `TT_COMMON_50301`，响应不泄露池参数 |

### psycopg2 ThreadedConnectionPool 实测语义（本机安装版本源码级确认）

以磁盘上 `site-packages/psycopg2/pool.py` 为准，纠正两处常见误解：

1. **`getconn()` 每次发出自增唯一 key**（`_keys += 1`），ThreadedConnectionPool
   **不按线程标识登记借出**；`putconn(conn)` 通过 `_rused[id(conn)]` 反查 key，
   归还与借出线程无关。同线程嵌套 `getconn()` 拿到的是另一个连接，不是同一连接。
2. **`DB_POOL_MAX` 是单进程内同时借出（在途）连接数的上限**，不是每线程上限。
   池耗尽条件：`len(self._used) == maxconn` 且空闲池为空 → `PoolError`。
3. **池的复用上限是 `DB_POOL_MIN`**：`putconn` 仅在 `len(self._pool) < minconn`
   时把连接放回空闲池；空闲池已满时归还的连接直接 `close()`。并发突发超出
   minconn 的部分是"按需新建、用完即关"，不缓存。

## 2. 配置（config.py / .env）

| 参数 | 默认 | 说明 |
|---|---|---|
| `DB_POOL_MIN` | 2 | 启动即建的常驻复用连接数（也是池复用上限，见 §1 语义 3） |
| `DB_POOL_MAX` | 10 | 单进程内同时借出连接上限；容量规划：uvicorn worker 数 × DB_POOL_MAX ≈ 总在途连接上限，须 ≤ PG `max_connections` 并留余量 |
| `DB_CONNECT_TIMEOUT` | 5 | 秒；防止 DB 不可用时 connect 长时间挂起 |

校验：三者必须 ≥ 1，且 `DB_POOL_MIN ≤ DB_POOL_MAX`（`Settings._validate_pool_sizes` / `_validate_pool_order`，配置错误启动即失败）。

容量规划示例：4 个 uvicorn worker × maxconn 10 = 理论最多约 40 个 DB 连接（须对照 PG `max_connections=100` 并为超级用户/维护连接留余量）。

## 3. 公共 API 与事务语义

| API | 事务语义 | 适用场景 |
|---|---|---|
| `transaction()` | **多语句原子**：块内全部成功才 commit，任一异常整体 rollback | 写路径首选：一次业务动作跨多表（如 demand + tag_relation + organization get-or-create，见 `etl_demands.py`） |
| `get_cursor(commit=True)` | 单语句写：语句序列成功后 commit，异常 rollback | 存量调用点兼容层（modules/* 已大量使用，不强制迁移） |
| `get_cursor(commit=False)` | 只读：不提交；归还连接时池对残留事务统一 rollback | 查询路径（缺省即此语义） |
| `get_conn()` | 裸连接；事务清理由 `putconn` 兜底 | 需要直接操作连接对象（如设置会话参数）时 |
| `init_pool()` / `close_pool()` | — | 幂等；`app.py` lifespan 启动/退出调用 |

用法示例：

```python
from db import transaction, get_cursor

# 多语句原子写
with transaction() as conn:
    with conn.cursor() as cur:
        cur.execute("INSERT INTO organization (...) VALUES (...) RETURNING id", (...))
        org_id = cur.fetchone()["id"]
        cur.execute("INSERT INTO demand (org_id, ...) VALUES (...)", (...))

# 单语句写（存量风格，保持兼容）
with get_cursor(commit=True) as cur:
    cur.execute("UPDATE demand SET status='published' WHERE id=%s", (did,))

# 只读
with get_cursor() as cur:
    cur.execute("SELECT COUNT(*) AS c FROM demand WHERE deleted_at IS NULL")
    total = cur.fetchone()["c"]
```

规范：

- **禁止**在业务代码直接 `psycopg2.connect(...)`（测试文件的自建验证连接除外）
- **禁止**持有连接跨请求（借出后必须在 `with` 块内用完归还）
- **禁止**嵌套借出（`transaction()` 内再调 `get_cursor()`/`get_conn()`）——会占用第二个连接并可能触发池耗尽；需要子查询就在当前 `cur` 上继续执行
- 写入 PG 后取自增 id 用 `RETURNING id`（psycopg2 无 `lastrowid`；MySQL 的 `INSERT IGNORE` 对应 PG `ON CONFLICT DO NOTHING`）

## 4. 异常映射链（与 T008 错误契约的衔接）

| 故障 | db.py 内部 | 异常类型 | HTTP / 错误码 |
|---|---|---|---|
| 池耗尽 | `_acquire_conn` 转换 | `OperationalError` | 503 / `TT_COMMON_50301` |
| DB 连不上 / 连接中断 | psycopg2 抛出 | `OperationalError` / `InterfaceError` | 503 / `TT_COMMON_50301` |
| 唯一/外键约束冲突 | psycopg2 抛出 | `IntegrityError` | 409 / `TT_COMMON_40903` |
| 业务逻辑回滚 | `transaction()` / `get_cursor` 内部 rollback | 业务异常原样上抛 | 按业务错误码 |

异常文本（含主机/端口/用户名/SQL）只进日志（`logger nanshan.db` / `nanshan.error`），绝不进响应。

## 5. 与请求生命周期的关系

- 同步端点运行在 FastAPI 线程池（默认 40 工作线程）；每个请求内连接借还成对发生在同一工作线程（项目约定）
- 并发上限自然约束：同时在途的 DB 请求 ≤ min(线程池大小, DB_POOL_MAX)
- uvicorn `reload=True`（本地开发）重启 worker 时，旧 worker lifespan 关池、新 worker 建池，无跨进程泄漏；多 worker 部署时每 worker 各持一个独立池（总连接 ≈ workers × DB_POOL_MAX，见 §2）

## 6. 测试

`test_db_session.py`（16 项，无需启动后端，需本地 PG 可用）：

- init_pool / close_pool 幂等；池参数来自 settings
- get_conn 借出/归还/池内 LIFO 复用
- transaction() 成功提交 / 异常整体回滚 / 回滚后池仍可用
- get_cursor(commit=True) 提交可见；commit=False 残留事务由归还逻辑回滚
- 池耗尽 → `OperationalError`（含 "exhausted"）
- 8 线程 × 5 轮并发借还无错乱
- close_pool 后懒初始化自动重建

`test_db_hardening.py`（19 项，T007 Final Hardening，无需启动后端）——故障恢复/压力/并发专项，详见 §7。

## 7. Failure Recovery Verification（Final Hardening 实测基线，2026-09-04）

全部数字来自 `test_db_hardening.py` 真实运行（本地 PostgreSQL，pool min=2/max=10/timeout=5s）：

### Python Exception
rollback verified —— `transaction()` 内 `raise RuntimeError` → 整体回滚，池继续可用（test_db_session [4] + hardening H4-B × 50）。

### PostgreSQL SQL Error / INERROR
rollback verified —— `SELECT 1/0` 触发真实服务端错误（`psycopg2.errors.DivisionByZero`），事务进入 INERROR；`transaction()` 捕获 → rollback → re-raise。**INSERT 在 rollback 后不可见**（H1）。残留 INERROR 不经我们 rollback 直接归还（裸 `get_conn` 路径）→ `putconn` 自动清理（H3）。

### INERROR → next SELECT 1
verified —— INERROR 发生后新 checkout `SELECT 1` 成功、新事务正常提交，无
`current transaction is aborted, commands ignored until end of transaction block` 污染（H2/H3）。

### Pool Exhaustion
verified —— 10/10 连接被同时持有时第 11 次借出 → `OperationalError("connection pool exhausted")`（H5）；HTTP 层联动（503 / `TT_COMMON_50301`）由 `test_error_contract.py` [13] 覆盖（32/32 PASS）。

### Stress（泄漏压力）
verified —— 50 轮 × (成功事务 + Python 异常事务 + SQL 错误事务 + 收尾 SELECT 1) = **200 次借还**，结束后 `_used=0`（无泄漏）、池未耗尽、SELECT 1 全部正常（H4）。

### Concurrency
verified —— 16 个并发短任务（ThreadPoolExecutor max_workers=16）：`ok=16 exhausted=0 polluted=0`（另一轮为 ok=14/exhausted=2，属 fail-fast 设计语义——池无等待机制，瞬时耗尽即报错，重试可恢复）；两轮均 **polluted=0**（无 INERROR 泄漏/closed/unkeyed 类错误），结束后池可用（H6）。另有 10 个连接真正同时持有 + 各自查询正确的专项验证（H5）。

### Broken Connection
verified —— 借出期间连接被关闭（手动 `conn.close()` 模拟）→ 归还时被丢弃不回池 → 新借出 SELECT 1 / 新事务提交均正常，不污染池（H7）。未做杀 PG 服务/真实断网测试（风险控制，靠 TCP keepalive + putconn UNKNOWN 处理兜底）。

### Startup Degradation（DB 不可达）
verified —— DB 端口不可达时 `init_pool()` 不抛异常（降级空池），借出报 `OperationalError`（对应 health degraded 契约）；DB 恢复后池自愈（H8）。

## 8. 与 psycopg2 私有实现的关系

测试可观察 `_pool` / `_used` 做诊断（如 H4 泄漏检查），但**项目正式契约只有**：
`init_pool()` / `close_pool()` / `get_conn()` / `get_cursor()` / `transaction()`。
不依赖 `_used` / `_rused` / 内部 key 等实现细节。

## 9. RELEASE CONFIG DECISION（记录，不在 T007 改动）

- 当前 `init_pool` 在 DB 不可达时降级为空池（fail-soft），适用于**开发环境**（配合 health degraded 契约，DB 恢复后自愈）。
- **production 是否应 fail-fast**（启动时 DB 不可达即退出）：T006 架构未定义。此决定留给发布配置评审——如需 fail-fast，在 `init_pool` 的 `except psycopg2.Error` 分支按 `settings.is_production_like` 分流即可（一行改动 + 对应测试）。
- 多 uvicorn worker 部署时总 DB 连接 ≈ workers × DB_POOL_MAX，上线前须对照 PG `max_connections`。

## 10. 回归基线（T007 Final Hardening 完成时，2026-09-04）

`test_db_hardening` 19/19 + `test_db_session` 16/16 + `test_error_contract` 32/32 + 既有 10 套件（achievement 37、achievement_write 51、admin 118、ai 30、chain、demand 88、institution 43、interaction 78、isolation）+ `tools/smoke_release.py` 74/74 + compileall 全部通过。
