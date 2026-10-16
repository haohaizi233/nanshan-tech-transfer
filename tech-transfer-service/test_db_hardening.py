"""
T007 Final Hardening 测试 —— PostgreSQL 故障恢复 / 泄漏压力 / 并发连接池

架构冻结：本文件只验证 db.py 现有实现，不修改实现。
场景（对应 Gap Analysis 的 ADD 项）：
  H1  真实 PostgreSQL SQL Error（SELECT 1/0 → INERROR）→ transaction() 整体 rollback
  H2  INERROR 恢复：下一 checkout SELECT 1 成功，新事务正常（无 aborted 污染）
  H3  残留 INERROR 直接归还（get_conn 无 rollback）→ putconn 清理 → 下一借出正常
  H4  50 轮泄漏压力：success / Python error / SQL error 交替 + 每轮收尾 SELECT 1
  H5  并发容量边界：DB_POOL_MAX 个同时持有 + 第 N+1 借出池耗尽 + 归还后恢复
  H6  16 并发短任务（等待归还语义下统计成功/超时耗尽，禁止污染类错误）
  H7  坏连接：借出后手动 close → 归还丢弃 → 新借出不受污染
  H8  DB 不可达时 init_pool 降级空池（fail-soft 启动）→ 恢复后自愈
  H9  同线程嵌套借出行为（事实揭示，为文档提供依据）

运行：python test_db_hardening.py（服务根目录，需本地 PostgreSQL 可用，无需后端进程）
"""
import sys
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor

import psycopg2

import db
from config import settings

PASS = 0
FAIL = 0

TABLE = "t007_hardening_test"


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def fact(name, value):
    """事实输出（非断言）：揭示 psycopg2 实际行为，供文档与报告引用。"""
    print(f"  [FACT] {name}: {value}")


def _unique_id() -> int:
    return uuid.uuid4().int >> 70


def _row_exists(tid: int) -> bool:
    with db.get_cursor() as cur:
        cur.execute(f"SELECT 1 FROM {TABLE} WHERE id = %s", (tid,))
        return cur.fetchone() is not None


def _used_count():
    """防御性读取池借出数（psycopg2 私有结构，仅诊断；读不到返回 None）。"""
    try:
        return len(db._pool._used)
    except Exception:
        return None


def _select_one() -> bool:
    """新 checkout 执行 SELECT 1；若被 INERROR 污染会抛
    'current transaction is aborted, commands ignored until end of transaction block'。"""
    with db.get_cursor() as cur:
        cur.execute("SELECT 1 AS v")
        return cur.fetchone()["v"] == 1


# 建测试表
with db.get_cursor(commit=True) as _cur:
    _cur.execute(
        f"CREATE TABLE IF NOT EXISTS {TABLE} (id BIGINT PRIMARY KEY, v TEXT)"
    )

try:
    # ════════════════════════════════════════════════════════
    # H1 真实 SQL Error → rollback
    # ════════════════════════════════════════════════════════
    print("[H1] SQL INERROR recovery：真实 PostgreSQL 错误 → transaction() 整体回滚")
    tid1 = _unique_id()
    sql_exc = None
    try:
        with db.transaction() as conn, conn.cursor() as cur:
            cur.execute(f"INSERT INTO {TABLE} (id, v) VALUES (%s, 'h1')", (tid1,))
            cur.execute("SELECT 1/0")  # 服务端除零 → 事务进入 INERROR
        check("SELECT 1/0 应从 transaction() 抛出 psycopg2.Error", False, "未抛异常")
    except psycopg2.Error as e:
        sql_exc = e
    check("SQL error 抛出 psycopg2.Error", isinstance(sql_exc, psycopg2.Error),
          repr(sql_exc))
    fact("SQL error 实际类型", type(sql_exc).__name__)
    check("rollback 后 INSERT 不可见", not _row_exists(tid1))

    # ════════════════════════════════════════════════════════
    # H2 INERROR 恢复：新 checkout + 新事务
    # ════════════════════════════════════════════════════════
    print("[H2] INERROR 不污染下一连接：新 checkout SELECT 1 + 新事务提交")
    check("INERROR 后新 checkout SELECT 1 成功", _select_one())
    tid2 = _unique_id()
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(f"INSERT INTO {TABLE} (id, v) VALUES (%s, 'h2')", (tid2,))
    check("INERROR 后新事务正常提交", _row_exists(tid2))

    # ════════════════════════════════════════════════════════
    # H3 残留 INERROR 直接归还 → putconn 安全网清理
    # ════════════════════════════════════════════════════════
    print("[H3] 残留 INERROR 归还（get_conn 无 rollback）→ putconn 清理")
    try:
        with db.get_conn() as conn:  # 故意不做任何 rollback
            with conn.cursor() as cur:
                cur.execute("SELECT 1/0")
        check("SELECT 1/0 应从 get_conn 冒出", False, "未抛异常")
    except psycopg2.Error:
        pass  # 预期：异常冒出，finally 归还时 putconn 对 INERROR 做 rollback
    check("归还后下一 checkout SELECT 1 成功（putconn 已清理 INERROR）", _select_one())

    # ════════════════════════════════════════════════════════
    # H4 50 轮泄漏压力
    # ════════════════════════════════════════════════════════
    print("[H4] Leak stress：50 轮 success / Python error / SQL error 交替")
    CYCLES = 50

    class _PyBoom(Exception):
        pass

    stress_errors = []
    for i in range(CYCLES):
        try:
            # A. 成功事务
            with db.transaction() as conn, conn.cursor() as cur:
                cur.execute("SELECT 1")
            # B. Python 异常 → rollback
            try:
                with db.transaction() as conn:
                    with conn.cursor() as cur:
                        cur.execute("SELECT 1")
                    raise _PyBoom()
            except _PyBoom:
                pass
            # C. SQL 错误 → rollback（真实 INERROR）
            try:
                with db.transaction() as conn, conn.cursor() as cur:
                    cur.execute("SELECT 1")
                    cur.execute("SELECT 1/0")
            except psycopg2.Error:
                pass
            # 每轮收尾：checkout → SELECT 1 → return
            if not _select_one():
                stress_errors.append(f"cycle {i}: SELECT 1 返回异常值")
        except Exception as e:
            stress_errors.append(f"cycle {i}: {e!r}")
    check(f"{CYCLES} 轮交替（{CYCLES * 4} 次借还）后池未耗尽且 SELECT 1 全部正常",
          not stress_errors, str(stress_errors[:3]))
    used_after_stress = _used_count()
    if used_after_stress is None:
        check("压力后无长期借出连接（_used 读取失败 → SKIPPED）", True)
        fact("压力后 _used", "不可读（SKIPPED）")
    else:
        check("压力后无长期借出连接（_used=0）", used_after_stress == 0,
              f"_used={used_after_stress}")
        fact("压力后 _used", used_after_stress)

    # ════════════════════════════════════════════════════════
    # H5 并发容量边界：DB_POOL_MAX 同时持有 + 第 N+1 借出
    # ════════════════════════════════════════════════════════
    print(f"[H5] Concurrent pool：{settings.DB_POOL_MAX} 个同时持有 + 第 {settings.DB_POOL_MAX + 1} 借出池耗尽")
    N = settings.DB_POOL_MAX
    held = [threading.Event() for _ in range(N)]
    release = threading.Event()
    holder_errors = []

    def _holder(idx):
        try:
            with db.get_conn() as conn:
                with conn.cursor() as cur:
                    cur.execute("SELECT %s AS v", (idx,))
                    if cur.fetchone()["v"] != idx:
                        raise AssertionError(f"holder {idx} 结果错乱")
                held[idx].set()
                if not release.wait(timeout=60):
                    holder_errors.append(f"holder {idx}: 等待释放超时")
        except Exception as e:
            holder_errors.append(f"holder {idx}: {e!r}")
            held[idx].set()

    threads = [threading.Thread(target=_holder, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    try:
        for ev in held:
            if not ev.wait(timeout=60):
                holder_errors.append("存在未就绪 holder（等待超时）")
                break

        if not holder_errors:
            # 全部持有的情况下第 N+1 个借出必须报池耗尽（holders 仍持有时检查）
            orig_timeout = settings.DB_POOL_ACQUIRE_TIMEOUT
            settings.DB_POOL_ACQUIRE_TIMEOUT = 0.2
            try:
                with db.get_conn():
                    pass
                check(f"持有 {N}/{N} 时第 {N + 1} 借出应报池耗尽", False, "未抛异常")
            except psycopg2.OperationalError as e:
                check(f"持有 {N}/{N} 时第 {N + 1} 借出 → OperationalError",
                      "exhausted" in str(e), str(e))
            finally:
                settings.DB_POOL_ACQUIRE_TIMEOUT = orig_timeout
    finally:
        release.set()
        for t in threads:
            t.join(timeout=65)
    check(f"{N} 个连接同时持有且各自查询正确", not holder_errors,
          str(holder_errors[:3]))
    check("全部归还后池恢复可用（SELECT 1）", _select_one())

    # ════════════════════════════════════════════════════════
    # H6 16 并发短任务
    # ════════════════════════════════════════════════════════
    print("[H6] Concurrent pool：16 个并发短任务（等待归还语义）")
    stats = {"ok": 0, "exhausted": 0, "polluted": []}

    def _short_task(i):
        try:
            with db.get_conn() as conn, conn.cursor() as cur:
                cur.execute("SELECT %s AS worker_id", (i,))
                if cur.fetchone()["worker_id"] != i:
                    return "polluted:结果错乱"
            return "ok"
        except psycopg2.OperationalError as e:
            if "exhausted" in str(e):
                return "exhausted"  # 等待超时仍耗尽才失败；短任务通常能等到归还
            return f"polluted:{e!r}"
        except Exception as e:
            return f"polluted:{e!r}"

    with ThreadPoolExecutor(max_workers=16) as ex:
        for r in ex.map(_short_task, range(16)):
            if r == "ok":
                stats["ok"] += 1
            elif r == "exhausted":
                stats["exhausted"] += 1
            else:
                stats["polluted"].append(r)
    fact("16 并发短任务结果", f"ok={stats['ok']} exhausted={stats['exhausted']} "
                              f"polluted={len(stats['polluted'])}")
    check("16 并发无污染类错误（INERROR 泄漏/closed/unkeyed 等）",
          not stats["polluted"], str(stats["polluted"][:3]))
    check("16 并发结束后池可用（SELECT 1）", _select_one())
    if stats["exhausted"] == 0:
        check("16 个并发短任务全部成功", stats["ok"] == 16,
              f"ok={stats['ok']}")

    # ════════════════════════════════════════════════════════
    # H7 坏连接：手动 close → 归还丢弃 → 不污染
    # ════════════════════════════════════════════════════════
    print("[H7] Broken connection：借出后连接已死（手动 close）")
    with db.get_conn() as conn:
        conn.close()  # 模拟"借出期间连接被外部关闭/发现已死"
    # 归还时 putconn 对 closed 连接直接丢弃，不回池
    check("坏连接归还后新 checkout SELECT 1 正常", _select_one())
    tid7 = _unique_id()
    with db.transaction() as conn, conn.cursor() as cur:
        cur.execute(f"INSERT INTO {TABLE} (id, v) VALUES (%s, 'h7')", (tid7,))
    check("坏连接归还后新事务正常提交", _row_exists(tid7))

    # ════════════════════════════════════════════════════════
    # H8 DB 不可达时 init_pool 降级空池（fail-soft 启动验证）
    # ════════════════════════════════════════════════════════
    print("[H8] DB 不可达时启动降级：init_pool 空池 + get_conn 报 OperationalError")
    _orig_port = settings.DB_PORT
    try:
        db.close_pool()
        settings.DB_PORT = 59999  # 本机未监听端口 → 立即拒连
        try:
            db.init_pool()
            check("DB 不可达时 init_pool 不抛异常（降级空池）", True)
        except Exception as e:
            check("DB 不可达时 init_pool 不抛异常（降级空池）", False, repr(e))
        try:
            with db.get_conn():
                pass
            check("空池借出应失败（对应 health degraded）", False, "未抛异常")
        except psycopg2.OperationalError:
            check("空池借出 → OperationalError（对应 health degraded）", True)
    finally:
        settings.DB_PORT = _orig_port
        db.close_pool()
        db.init_pool()
    check("DB 恢复后池自愈（SELECT 1）", _select_one())

    # ════════════════════════════════════════════════════════
    # H9 同线程嵌套借出行为（事实揭示）
    # ════════════════════════════════════════════════════════
    print("[H9] 同线程嵌套借出行为（transaction() 内不可嵌 get_cursor 的依据）")
    nested_rejected = None
    nested_detail = ""
    with db.get_conn() as outer:
        with outer.cursor() as cur:
            cur.execute("SELECT 1")  # 外层连接本身可用
        try:
            with db.get_conn() as inner:
                nested_rejected = False
        except psycopg2.OperationalError as e:
            nested_rejected = True
            nested_detail = str(e)
    fact("同线程嵌套借出 rejected", nested_rejected)
    fact("嵌套借出异常文本", nested_detail or "(allowed)")
    if nested_rejected:
        check("同线程嵌套借出被拒绝（转为 OperationalError）", True)
    else:
        check("同线程嵌套借出被允许（文档按实际行为记录）", True)

finally:
    try:
        with db.get_cursor(commit=True) as cur:
            cur.execute(f"DROP TABLE IF EXISTS {TABLE}")
    except psycopg2.Error as e:
        print(f"  [WARN] 清理测试表失败: {e}")
    db.close_pool()

print()
print("=" * 60)
print(f"RESULT: {PASS} passed, {FAIL} failed")
if __name__ == "__main__":
    sys.exit(1 if FAIL else 0)
