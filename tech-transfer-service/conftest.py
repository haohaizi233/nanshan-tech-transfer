"""
Shared pytest fixtures for tech-transfer-service tests.

Provides:
- FastAPI TestClient with mocked DB
- Auth token generation helpers
- Common test data factories
"""
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest
import jwt

# Ensure project root is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

# Force local/test environment before any config import
os.environ.setdefault("APP_ENV", "local")
os.environ.setdefault("AUTH_PROVIDER", "mock")
os.environ.setdefault("DB_HOST", "127.0.0.1")
os.environ.setdefault("DB_PORT", "5432")
os.environ.setdefault("DB_USER", "mac")
os.environ.setdefault("DB_PASSWORD", "test")
os.environ.setdefault("DB_NAME", "tech_transfer_test")
os.environ.setdefault("JWT_SECRET", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("HOST_MODE", "local")

from config import settings


@pytest.fixture
def mock_cursor():
    """A MagicMock cursor that behaves like psycopg2 RealDictCursor."""
    cur = MagicMock()
    cur.fetchone.return_value = None
    cur.fetchall.return_value = []
    cur.execute.return_value = None
    return cur


@pytest.fixture
def mock_conn():
    """A MagicMock database connection."""
    conn = MagicMock()
    conn.cursor.return_value = MagicMock()
    return conn


@pytest.fixture
def mock_get_cursor(mock_cursor):
    """Patch db.get_cursor to return a mock cursor."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx(commit=False):
        yield mock_cursor

    with patch("db.get_cursor", _ctx):
        yield mock_cursor


@pytest.fixture
def mock_get_conn(mock_conn):
    """Patch db.get_conn to return a mock connection."""
    from contextlib import contextmanager

    @contextmanager
    def _ctx():
        yield mock_conn

    with patch("db.get_conn", _ctx):
        yield mock_conn


@pytest.fixture
def make_token():
    """Factory fixture: generate a valid JWT access token."""
    def _make(user_id=1, user_no="U001", roles=None, token_type="access", expired=False):
        if roles is None:
            roles = ["user"]
        now = int(time.time())
        payload = {
            "sub": str(user_id),
            "userNo": user_no,
            "roles": roles,
            "type": token_type,
            "iat": now,
            "exp": now - 3600 if expired else now + settings.ACCESS_TOKEN_EXPIRES,
        }
        return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)
    return _make


@pytest.fixture
def auth_headers(make_token):
    """Factory fixture: produce Authorization headers for a given user."""
    def _make(user_id=1, user_no="U001", roles=None):
        token = make_token(user_id=user_id, user_no=user_no, roles=roles)
        return {"Authorization": f"Bearer {token}"}
    return _make


@pytest.fixture
def admin_auth_headers(make_token):
    """Authorization headers for an admin user."""
    token = make_token(user_id=999, user_no="ADMIN001", roles=["admin"])
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def app_client():
    """FastAPI TestClient with DB mocked out."""
    from fastapi.testclient import TestClient

    # Mock DB pool init to avoid real connections
    with patch("db.init_pool"), \
         patch("db.close_pool"), \
         patch("db.get_cursor") as mock_gc, \
         patch("db.get_conn") as mock_gconn:

        mock_cursor = MagicMock()
        mock_cursor.fetchone.return_value = None
        mock_cursor.fetchall.return_value = []
        mock_gc.return_value.__enter__ = MagicMock(return_value=mock_cursor)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn = MagicMock()
        mock_gconn.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_gconn.return_value.__exit__ = MagicMock(return_value=False)

        from app import app
        client = TestClient(app, raise_server_exceptions=False)
        yield client