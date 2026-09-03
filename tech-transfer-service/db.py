"""
数据库连接（线程本地）

FastAPI 的同步端点运行在线程池中，每个线程持有独立连接，
避免多线程共用同一 pymysql 连接导致的协议错乱。
公共 API 与 Flask 版保持一致：get_conn / get_cursor。
"""

import threading
from contextlib import contextmanager

import pymysql

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

_local = threading.local()


def _get_thread_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
        _local.conn = conn
    return conn


@contextmanager
def get_conn():
    conn = _get_thread_conn()
    try:
        conn.ping(reconnect=True)
        yield conn
    except Exception:
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
