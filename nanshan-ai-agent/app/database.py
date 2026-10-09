from contextlib import contextmanager
from threading import BoundedSemaphore, Lock

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import PoolError, ThreadedConnectionPool

from app.config import settings

# 进程级连接池：限制最大连接数，避免与主服务争抢 PG max_connections
_pool = None
_pool_lock = Lock()
_connection_slots = BoundedSemaphore(settings.DB_MAX_CONN)


class DatabaseBusyError(RuntimeError):
    pass


def _get_pool():
    global _pool
    if _pool is None:
        with _pool_lock:
            if _pool is None:
                _pool = ThreadedConnectionPool(
                    minconn=1,
                    maxconn=settings.DB_MAX_CONN,
                    host=settings.DB_HOST,
                    port=settings.DB_PORT,
                    dbname=settings.DB_NAME,
                    user=settings.DB_USER,
                    password=settings.DB_PASSWORD,
                    connect_timeout=5,
                    options=f"-c statement_timeout={settings.DB_STATEMENT_TIMEOUT_MS}",
                    cursor_factory=RealDictCursor,
                )
    return _pool


@contextmanager
def get_db():
    conn = None
    discard = False
    if not _connection_slots.acquire(timeout=settings.DB_POOL_WAIT_SECONDS):
        raise DatabaseBusyError("AI 数据库连接繁忙，请稍后重试")

    try:
        pool = _get_pool()
        try:
            conn = pool.getconn()
        except PoolError as exc:
            raise DatabaseBusyError("AI 数据库连接繁忙，请稍后重试") from exc
        if conn.closed:
            pool.putconn(conn, close=True)
            conn = pool.getconn()

        # 当前 AI 服务只允许读数据库
        conn.set_session(
            readonly=True,
            autocommit=True,
        )

        yield conn
    except BaseException:
        discard = True
        raise

    finally:
        if conn is not None:
            try:
                _get_pool().putconn(conn, close=discard or bool(conn.closed))
            finally:
                _connection_slots.release()
        else:
            _connection_slots.release()