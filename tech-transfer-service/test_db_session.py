"""
T007 数据库连接池与事务边界测试

验证 db.py 的 ThreadedConnectionPool 实现：
  1. init_pool / close_pool 幂等
  2. get_conn 借出/归还 + 池内连接复用
  3. transaction() 多语句原子提交 / 异常整体回滚
  4. get_cursor(commit=True) 提交可见
  5. get_cursor(commit=False) 残留事务由归还逻辑 rollback（不残留半写状态）
  6. 池耗尽 → OperationalError（供异常处理器统一映射 503）
  7. 池满等待归还后续借出成功
  8. 多线程并发借还互不干扰
  9. 懒初始化（未 init_pool 时首次访问自动建池）

运行：python test_db_session.py（服务根目录，需本地 PostgreSQL 可用）
"""
import sys
import threading
import time

import psycopg2
from psycopg2.pool import ThreadedConnectionPool

import db
from config import settings

PASS = 0
FAIL = 0

_TX_TABLE = "t007_tx_test"


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def _count_rows(v: str) -> int:
    with db.get_cursor() as cur:
        cur.execute(f"SELECT COUNT(*) AS c FROM {_TX_TABLE} WHERE v = %s", (v,))
        return cur.fetchone()["c"]


# ════════════════════════════════════════════════════════════
# [1] init_pool / close_pool 幂等性
# ════════════════════════════════════════════════════════════
print("[1] init_pool / close_pool 幂等性")
db.init_pool()
pool_a = db._pool
db.init_pool()
check("init_pool 重复调用不重建池", db._pool is pool_a)
check("池参数来自 settings", pool_a.maxconn == db.settings.DB_POOL_MAX)

# ════════════════════════════════════════════════════════════
# [2] get_conn 借出 / 归还 / 复用
# ════════════════════════════════════════════════════════════
print("[2] get_conn 借出 / 归还 / 复用")
with db.get_conn() as c1:
    check("借出连接可用（非 closed）", not c1.closed)
    with c1.cursor() as cur:
        cur.execute("SELECT 1 AS v")
        check("借出连接可执行查询", cur.fetchone()["v"] == 1)
check("归还后池存在空闲连接", len(db._pool._pool) >= 1,
      f"idle={len(db._pool._pool)}")
with db.get_conn() as c2:
    check("池复用同一连接（LIFO）", c2 is c1, f"{c2!r} vs {c1!r}")

# 建事务测试表（真实表：跨连接可见，验证原子性最可靠）
with db.get_cursor(commit=True) as cur:
    cur.execute(f"CREATE TABLE IF NOT EXISTS {_TX_TABLE}(id serial PRIMARY KEY, v text)")

try:
    # ════════════════════════════════════════════════════════
    # [3] transaction() 成功提交
    # ════════════════════════════════════════════════════════
    print("[3] transaction() 成功提交")
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(f"INSERT INTO {_TX_TABLE}(v) VALUES ('committed')")
    check("transaction 提交后可见", _count_rows("committed") == 1)

    # ════════════════════════════════════════════════════════
    # [4] transaction() 异常整体回滚
    # ════════════════════════════════════════════════════════
    print("[4] transaction() 异常整体回滚")

    class _Boom(Exception):
        pass

    try:
        with db.transaction() as conn:
            with conn.cursor() as cur:
                cur.execute(f"INSERT INTO {_TX_TABLE}(v) VALUES ('rolled-back')")
            raise _Boom("intentional")
    except _Boom:
        pass
    check("transaction 回滚后不可见", _count_rows("rolled-back") == 0)
    check("回滚不破坏池（后续查询正常）", _count_rows("committed") == 1)

    # ════════════════════════════════════════════════════════
    # [5] get_cursor(commit=True) 提交可见
    # ════════════════════════════════════════════════════════
    print("[5] get_cursor(commit=True) 提交可见")
    with db.get_cursor(commit=True) as cur:
        cur.execute(f"INSERT INTO {_TX_TABLE}(v) VALUES ('cursor-commit')")
    check("get_cursor(commit=True) 提交后可见", _count_rows("cursor-commit") == 1)

    # ════════════════════════════════════════════════════════
    # [6] get_cursor(commit=False) 残留事务由归还逻辑回滚
    # ════════════════════════════════════════════════════════
    print("[6] get_cursor(commit=False) 残留事务由归还逻辑回滚")
    with db.get_cursor() as cur:  # 故意不 commit
        cur.execute(f"INSERT INTO {_TX_TABLE}(v) VALUES ('never-committed')")
    check("未提交写入归还后不可见", _count_rows("never-committed") == 0)

    # ════════════════════════════════════════════════════════
    # [7] 池耗尽 → OperationalError
    # ════════════════════════════════════════════════════════
    print("[7] 池耗尽 → OperationalError")
    orig_pool = db._pool
    orig_timeout = settings.DB_POOL_ACQUIRE_TIMEOUT
    try:
        settings.DB_POOL_ACQUIRE_TIMEOUT = 0.15
        db._pool = ThreadedConnectionPool(0, 1, **db._connect_kwargs())
        with db.get_conn():  # 占满 max=1
            try:
                with db.get_conn():
                    pass
                check("池耗尽应抛 OperationalError", False, "未抛异常")
            except psycopg2.OperationalError as e:
                check("池耗尽 → OperationalError（含 exhausted）",
                      "exhausted" in str(e), str(e))
    finally:
        settings.DB_POOL_ACQUIRE_TIMEOUT = orig_timeout
        db._pool.closeall()
        db._pool = orig_pool

    # ════════════════════════════════════════════════════════
    # [7b] 池满时等待归还，随后借出成功
    # ════════════════════════════════════════════════════════
    print("[7b] 池满等待归还 → 第二借出成功")
    orig_pool = db._pool
    orig_timeout = settings.DB_POOL_ACQUIRE_TIMEOUT
    waiter_errors = []
    acquired = threading.Event()
    release_holder = threading.Event()
    holder_ready = threading.Event()

    def _holder():
        with db.get_conn():
            holder_ready.set()
            release_holder.wait(timeout=5)

    def _waiter():
        try:
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1 AS v")
                if cur.fetchone()["v"] != 1:
                    waiter_errors.append("结果错乱")
            acquired.set()
        except Exception as e:
            waiter_errors.append(repr(e))
            acquired.set()

    try:
        settings.DB_POOL_ACQUIRE_TIMEOUT = 2.0
        db._pool = ThreadedConnectionPool(0, 1, **db._connect_kwargs())
        holder = threading.Thread(target=_holder)
        waiter = threading.Thread(target=_waiter)
        holder.start()
        if not holder_ready.wait(timeout=5):
            waiter_errors.append("holder 未就绪")
        waiter.start()
        time.sleep(0.05)
        release_holder.set()
        holder.join(timeout=5)
        waiter.join(timeout=5)
        check("等待归还后第二借出成功", acquired.is_set() and not waiter_errors,
              str(waiter_errors[:3]))
    finally:
        release_holder.set()
        settings.DB_POOL_ACQUIRE_TIMEOUT = orig_timeout
        db._pool.closeall()
        db._pool = orig_pool

    # ════════════════════════════════════════════════════════
    # [8] 多线程并发借还
    # ════════════════════════════════════════════════════════
    print("[8] 多线程并发借还")
    errors = []

    def _worker(i):
        try:
            for _ in range(5):
                with db.get_conn() as conn, conn.cursor() as cur:
                    cur.execute("SELECT %s AS v", (i,))
                    assert cur.fetchone()["v"] == i, "结果错乱"
        except Exception as e:
            errors.append((i, repr(e)))

    threads = [threading.Thread(target=_worker, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("8 线程 × 5 轮并发借还无错误", not errors, str(errors[:3]))

    # ════════════════════════════════════════════════════════
    # [9] close_pool 后懒初始化重建
    # ════════════════════════════════════════════════════════
    print("[9] close_pool / 懒初始化")
    db.close_pool()
    check("close_pool 后 _pool 置空", db._pool is None)
    db.close_pool()  # 幂等，不抛
    with db.get_conn() as c:
        check("懒初始化自动重建池", db._pool is not None and not c.closed)
    check("懒初始化后事务可用", _count_rows("committed") == 1)

finally:
    # 清理：测试表 + 池
    try:
        with db.get_cursor(commit=True) as cur:
            cur.execute(f"DROP TABLE IF EXISTS {_TX_TABLE}")
    except psycopg2.Error as e:
        print(f"  [WARN] 清理测试表失败: {e}")
    db.close_pool()

print()
print("=" * 60)
print(f"RESULT: {PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
