"""
数据库连接（线程本地，PostgreSQL / psycopg2）

FastAPI 的同步端点运行在线程池中，每个线程持有独立连接，
避免多线程共用同一连接导致的协议错乱。
公共 API 与 MySQL 版保持一致：get_conn / get_cursor。
行为对齐说明：
- RealDictCursor 等价原 pymysql DictCursor（fetchone/fetchall 返回 dict）
- jsonb 列默认解析为 Python dict/list（服务层 _parse_json 同时兼容 str/obj）
- TIMESTAMPTZ 读取为带时区 datetime（会话时区 Asia/Shanghai，与原 MySQL 本地时间一致）
"""

import threading
from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from config import settings

_local = threading.local()


def _get_thread_conn():
    conn = getattr(_local, "conn", None)
    if conn is None or conn.closed:
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            dbname=settings.DB_NAME,
            cursor_factory=RealDictCursor,
        )
        _local.conn = conn
    return conn


@contextmanager
def get_conn():
    conn = _get_thread_conn()
    try:
        if conn.closed:
            raise psycopg2.OperationalError("connection closed")
        yield conn
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        try:
            conn.close()
        except Exception:
            pass
        _local.conn = None
        raise


@contextmanager
def get_cursor(commit: bool = False):
    with get_conn() as conn:
        cur = conn.cursor()
        try:
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
