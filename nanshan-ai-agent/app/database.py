from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from app.config import settings

# 进程级连接池：限制最大连接数，避免与主服务争抢 PG max_connections
_pool = None


def _get_pool():
    global _pool
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
            cursor_factory=RealDictCursor,
        )
    return _pool


@contextmanager
def get_db():
    conn = None

    try:
        conn = _get_pool().getconn()

        # 当前 AI 服务只允许读数据库
        conn.set_session(
            readonly=True,
            autocommit=True,
        )

        yield conn

    finally:
        if conn is not None:
            _get_pool().putconn(conn)