from contextlib import contextmanager

import psycopg2
from psycopg2.extras import RealDictCursor

from app.config import settings


@contextmanager
def get_db():
    conn = None

    try:
        conn = psycopg2.connect(
            host=settings.DB_HOST,
            port=settings.DB_PORT,
            dbname=settings.DB_NAME,
            user=settings.DB_USER,
            password=settings.DB_PASSWORD,
            connect_timeout=5,
            cursor_factory=RealDictCursor,
        )

        # 当前 AI 服务只允许读数据库
        conn.set_session(
            readonly=True,
            autocommit=True,
        )

        yield conn

    finally:
        if conn is not None:
            conn.close()