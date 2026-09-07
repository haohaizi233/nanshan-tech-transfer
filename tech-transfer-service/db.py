"""
数据库访问（PostgreSQL / psycopg2，T007：进程级连接池 + 显式事务边界）

架构：
- ThreadedConnectionPool：进程内共享池（DB_POOL_MIN/DB_POOL_MAX/DB_CONNECT_TIMEOUT 见 config）
- 生命周期：app.py lifespan 启动时 init_pool()、退出时 close_pool()
- 懒初始化兜底：未走 lifespan 的脚本/测试首次访问时自动建池
- 借出/归还同线程配对是项目约定（with 块保证）；psycopg2 2.9 池按唯一 key +
  id(conn) 记账，本身不要求同线程（实测语义见 docs/db-session.md）

事务边界：
- transaction()：多语句原子写（推荐写路径使用）
- get_cursor(commit=True)：单语句写，成功 commit / 异常 rollback（兼容存量调用点）
- get_cursor(commit=False)：只读；归还时 psycopg2 pool 对残留事务统一 rollback

异常安全：
- 池耗尽（PoolError）→ 转为 OperationalError，统一映射 503（core/exception_handlers）
- putconn 按连接状态处理：UNKNOWN（服务端已断）→ 关闭；空闲池已满（≥ minconn）
  → 直接关闭（psycopg2 语义，池复用上限即 minconn）；否则按状态清理后回池

行为对齐说明（与原 thread-local 版一致）：
- RealDictCursor：fetchone/fetchall 返回 dict
- jsonb 列默认解析为 Python dict/list（服务层 _parse_json 同时兼容 str/obj）
- TIMESTAMPTZ 读取为带时区 datetime（会话时区 Asia/Shanghai）
"""

import logging
import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool

from config import settings

logger = logging.getLogger("nanshan.db")

_pool: ThreadedConnectionPool | None = None
_pool_lock = threading.Lock()


def _connect_kwargs() -> dict:
    return {
        "host": settings.DB_HOST,
        "port": settings.DB_PORT,
        "user": settings.DB_USER,
        "password": settings.DB_PASSWORD,
        "dbname": settings.DB_NAME,
        "cursor_factory": RealDictCursor,
        "connect_timeout": settings.DB_CONNECT_TIMEOUT,
        "application_name": settings.APP_NAME,
        # TCP keepalive：尽快感知被网络设备/数据库重启断开的死连接
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }


def init_pool() -> None:
    """创建进程级连接池（幂等，线程安全）。

    DB 暂不可用时以空池（minconn=0）启动，不阻塞服务启动：
    健康检查照常报 degraded，DB 恢复后 getconn 懒建连接自动恢复。
    """
    global _pool
    with _pool_lock:
        if _pool is not None:
            return
        kwargs = _connect_kwargs()
        try:
            _pool = ThreadedConnectionPool(
                settings.DB_POOL_MIN, settings.DB_POOL_MAX, **kwargs
            )
        except psycopg2.Error as e:
            logger.warning("连接池初始化失败，降级为空池懒填充：%s", e)
            _pool = ThreadedConnectionPool(0, settings.DB_POOL_MAX, **kwargs)
        logger.info(
            "DB 连接池就绪（min=%s max=%s db=%s@%s:%s）",
            settings.DB_POOL_MIN,
            settings.DB_POOL_MAX,
            settings.DB_NAME,
            settings.DB_HOST,
            settings.DB_PORT,
        )


def close_pool() -> None:
    """关闭连接池（幂等）。lifespan 退出时调用。"""
    global _pool
    with _pool_lock:
        pool, _pool = _pool, None
    if pool is not None:
        pool.closeall()


def _get_pool() -> ThreadedConnectionPool:
    if _pool is None:
        init_pool()
    return _pool  # type: ignore[return-value]


def _acquire_conn():
    """从池借出连接；池耗尽统一转为 OperationalError（→ 503 契约）。"""
    try:
        return _get_pool().getconn()
    except PoolError:
        raise psycopg2.OperationalError("connection pool exhausted") from None


def _release_conn(conn) -> None:
    """归还连接。

    psycopg2 putconn 按连接状态处理：UNKNOWN（服务端已断）→ 关闭；
    事务残留 → rollback 后回池；IDLE → 直接回池复用。
    """
    pool = _pool
    try:
        if pool is None:  # close_pool 之后的退出竞态：直接关闭
            conn.close()
        else:
            pool.putconn(conn)
    except Exception:
        logger.warning("归还连接异常，强制关闭", exc_info=True)
        try:
            conn.close()
        except Exception:
            pass


@contextmanager
def get_conn():
    """借出一个池化连接，用毕归还（事务清理由 putconn 兜底）。"""
    conn = _acquire_conn()
    try:
        yield conn
    finally:
        _release_conn(conn)


@contextmanager
def get_cursor(commit: bool = False):
    """单语句游标（兼容层）：commit=True 时成功后提交，异常一律回滚。"""
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
            else:
                # psycopg2 即使执行 SELECT 也会开启事务；线程长连接若不结束事务，
                # 会长期持有 AccessShareLock，阻塞后续 ALTER TABLE 等迁移。
                conn.rollback()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass  # 坏连接由归还逻辑关闭，不掩盖业务异常
            raise
        finally:
            cur.close()


@contextmanager
def transaction():
    """多语句原子事务：块内全部成功才 commit，任一异常整体 rollback。"""
    with get_conn() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            try:
                conn.rollback()
            except Exception:
                pass
            raise
