"""
Comprehensive tests for db.py and app.py (lifespan, health, middleware).
"""
import time
from unittest.mock import MagicMock, patch

import pytest

# ── db.py ───────────────────────────────────────────────────

class TestDB:
    def test_connect_kwargs(self):
        from db import _connect_kwargs
        kwargs = _connect_kwargs()
        assert "host" in kwargs
        assert "port" in kwargs
        assert "user" in kwargs
        assert "password" in kwargs
        assert "dbname" in kwargs
        assert "connect_timeout" in kwargs
        assert "keepalives" in kwargs
        assert kwargs["keepalives"] == 1

    @patch("db.ThreadedConnectionPool")
    @patch("db.settings")
    def test_init_pool_success(self, mock_settings, mock_pool_cls):
        import db
        db._pool = None  # Reset
        mock_settings.DB_POOL_MIN = 2
        mock_settings.DB_POOL_MAX = 10
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_USER = "test"
        mock_settings.DB_PASSWORD = "test"
        mock_settings.DB_NAME = "testdb"
        mock_settings.DB_CONNECT_TIMEOUT = 5
        mock_settings.APP_NAME = "test"
        db.init_pool()
        mock_pool_cls.assert_called_once()
        # Cleanup
        db._pool = None

    @patch("db.ThreadedConnectionPool")
    @patch("db.settings")
    def test_init_pool_idempotent(self, mock_settings, mock_pool_cls):
        import db
        db._pool = MagicMock()  # Already initialized
        db.init_pool()
        mock_pool_cls.assert_not_called()
        db._pool = None

    @patch("db.ThreadedConnectionPool")
    @patch("db.settings")
    def test_init_pool_degraded(self, mock_settings, mock_pool_cls):
        """DB unavailable: should degrade to empty pool."""
        import db
        db._pool = None
        mock_settings.DB_POOL_MIN = 2
        mock_settings.DB_POOL_MAX = 10
        mock_settings.DB_HOST = "localhost"
        mock_settings.DB_PORT = 5432
        mock_settings.DB_USER = "test"
        mock_settings.DB_PASSWORD = "test"
        mock_settings.DB_NAME = "testdb"
        mock_settings.DB_CONNECT_TIMEOUT = 5
        mock_settings.APP_NAME = "test"
        # First call raises, second succeeds (degraded pool)
        import psycopg2
        mock_pool_cls.side_effect = [psycopg2.Error("connection refused"), MagicMock()]
        db.init_pool()
        assert mock_pool_cls.call_count == 2
        db._pool = None

    def test_close_pool(self):
        import db
        mock_pool = MagicMock()
        db._pool = mock_pool
        db.close_pool()
        mock_pool.closeall.assert_called_once()
        assert db._pool is None

    def test_close_pool_idempotent(self):
        import db
        db._pool = None
        db.close_pool()  # Should not raise

    def test_ping_success(self):
        from db import _ping
        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur
        mock_cur.fetchone.return_value = (1,)
        assert _ping(mock_conn) is True
        mock_conn.rollback.assert_called()

    def test_ping_failure(self):
        from db import _ping
        mock_conn = MagicMock()
        mock_conn.cursor.side_effect = Exception("connection lost")
        assert _ping(mock_conn) is False

    def test_release_conn_normal(self):
        import db as db_module
        from db import _release_conn
        mock_pool = MagicMock()
        db_module._pool = mock_pool
        mock_conn = MagicMock()
        db_module._conn_born[id(mock_conn)] = time.monotonic()
        _release_conn(mock_conn)
        mock_pool.putconn.assert_called_once()
        db_module._pool = None

    def test_release_conn_no_pool(self):
        """After close_pool, release should close connection directly."""
        import db as db_module
        from db import _release_conn
        db_module._pool = None
        mock_conn = MagicMock()
        _release_conn(mock_conn)
        mock_conn.close.assert_called_once()

    def test_release_conn_recycle(self):
        """Old connections should be recycled."""
        import db as db_module
        from db import _CONN_RECYCLE_SECONDS, _release_conn
        mock_pool = MagicMock()
        db_module._pool = mock_pool
        mock_conn = MagicMock()
        # Set born time far in the past
        db_module._conn_born[id(mock_conn)] = time.monotonic() - _CONN_RECYCLE_SECONDS - 100
        _release_conn(mock_conn)
        mock_conn.close.assert_called_once()
        mock_pool.putconn.assert_not_called()
        db_module._pool = None

    def test_get_cursor_context_manager(self):
        """get_cursor should yield a cursor and handle commit/rollback."""
        import db as db_module
        from db import get_cursor

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_release_conn"):
            with get_cursor(commit=False) as cur:
                assert cur == mock_cur
            mock_conn.rollback.assert_called()

    def test_get_cursor_commit(self):
        """get_cursor with commit=True should commit on success."""
        import db as db_module
        from db import get_cursor

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_release_conn"):
            with get_cursor(commit=True) as cur:
                cur.execute("INSERT ...")
            mock_conn.commit.assert_called_once()

    def test_get_cursor_exception_rollback(self):
        """get_cursor should rollback on exception."""
        import db as db_module
        from db import get_cursor

        mock_conn = MagicMock()
        mock_cur = MagicMock()
        mock_conn.cursor.return_value = mock_cur

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_release_conn"):
            with pytest.raises(ValueError):
                with get_cursor(commit=True):
                    raise ValueError("test error")
            mock_conn.rollback.assert_called()

    def test_transaction_context_manager(self):
        """transaction should commit on success."""
        import db as db_module
        from db import transaction

        mock_conn = MagicMock()

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_release_conn"):
            with transaction() as conn:
                assert conn == mock_conn
            mock_conn.commit.assert_called_once()

    def test_transaction_exception_rollback(self):
        """transaction should rollback on exception."""
        import db as db_module
        from db import transaction

        mock_conn = MagicMock()

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_release_conn"):
            with pytest.raises(ValueError):
                with transaction():
                    raise ValueError("test error")
            mock_conn.rollback.assert_called()

    def test_acquire_conn_timeout(self):
        """Pool exhaustion with timeout should raise OperationalError."""
        import psycopg2

        import db as db_module
        from db import _acquire_conn

        mock_pool = MagicMock()
        mock_pool.getconn.side_effect = psycopg2.pool.PoolError("pool exhausted")
        db_module._pool = mock_pool

        with patch("db.settings") as mock_settings:
            mock_settings.DB_POOL_ACQUIRE_TIMEOUT = 0.1
            with pytest.raises(psycopg2.OperationalError, match="pool exhausted"):
                _acquire_conn()
        db_module._pool = None

    def test_dirty_conn_replacement(self):
        """Dirty connections should be pinged and replaced if bad."""
        import db as db_module
        from db import get_conn

        mock_conn = MagicMock()
        mock_conn_id = id(mock_conn)

        # Mark as dirty
        db_module._dirty_conns.add(mock_conn_id)

        with patch.object(db_module, "_acquire_conn", return_value=mock_conn), \
             patch.object(db_module, "_ping", return_value=False), \
             patch.object(db_module, "_replace_conn", return_value=MagicMock()) as mock_replace, \
             patch.object(db_module, "_release_conn"):
            with get_conn() as conn:
                pass
            mock_replace.assert_called_once()
        db_module._dirty_conns.discard(mock_conn_id)


# ── app.py ──────────────────────────────────────────────────

class TestApp:
    def test_app_importable(self):
        """app module should be importable without errors."""
        from app import app
        assert app.title == "tech-transfer-service"

    def test_app_routes_count(self):
        """App should have a significant number of routes."""
        from app import app
        routes = [r for r in app.routes if hasattr(r, "methods")]
        assert len(routes) > 20  # We have 144+ routes

    def test_health_endpoint(self):
        """Health endpoint should exist."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (1,)
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 0
            assert data["data"]["status"] == "ok"

    def test_health_degraded(self):
        """Health endpoint returns degraded when DB fails."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            import psycopg2
            mock_cur.execute.side_effect = psycopg2.OperationalError("DB down")
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == 1
            assert data["data"]["status"] == "degraded"

    def test_request_id_middleware(self):
        """Requests should get X-Request-Id header."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (1,)
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert "X-Request-Id" in resp.headers

    def test_custom_request_id(self):
        """Client-provided X-Request-Id should be reused."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (1,)
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health", headers={"X-Request-Id": "custom-id-123456"})
            assert resp.headers["X-Request-Id"] == "custom-id-123456"

    def test_security_headers(self):
        """Responses should include security headers."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            mock_cur.fetchone.return_value = (1,)
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/health")
            assert resp.headers.get("X-Frame-Options") == "DENY"
            assert resp.headers.get("X-Content-Type-Options") == "nosniff"
            assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"
            assert "Strict-Transport-Security" in resp.headers

    def test_not_found_error_contract(self):
        """404 should return unified error contract."""
        from fastapi.testclient import TestClient

        from app import app

        with patch("db.init_pool"), \
             patch("db.close_pool"), \
             patch("db.get_cursor") as mock_gc:
            mock_cur = MagicMock()
            mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cur)
            mock_gc.return_value.__exit__ = MagicMock(return_value=False)

            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/nonexistent/path")
            assert resp.status_code == 404
            data = resp.json()
            assert data["code"] == "TT_COMMON_40401"
            assert "requestId" in data
