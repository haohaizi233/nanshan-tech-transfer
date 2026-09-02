import pymysql
from contextlib import contextmanager

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME

_pool = None


def _get_pool():
    global _pool
    if _pool is None:
        _pool = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=False,
        )
    return _pool


@contextmanager
def get_conn():
    conn = _get_pool()
    try:
        conn.ping(reconnect=True)
        yield conn
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        global _pool
        _pool = None
        raise


@contextmanager
def get_cursor(commit: bool = False):
    with get_conn() as conn:
        try:
            cur = conn.cursor()
            yield cur
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
