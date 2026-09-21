"""回归：公网扫描产生的 404 不得淹没业务错误日志。"""

import logging
from unittest.mock import Mock, patch

from core.exception_handlers import _DropNotFoundAccessLog, _log_error


def _request(path="/missing"):
    request = Mock()
    request.method = "GET"
    request.url.path = path
    return request


def test_not_found_is_debug_log():
    with patch("core.exception_handlers.logger") as logger:
        _log_error(_request(), 404, "TT_COMMON_40401")
    logger.debug.assert_called_once()
    logger.info.assert_not_called()
    logger.error.assert_not_called()


def test_server_error_remains_error_log():
    with patch("core.exception_handlers.logger") as logger:
        _log_error(_request("/api/example"), 503, "TT_COMMON_50301")
    logger.error.assert_called_once()
    logger.debug.assert_not_called()


def test_uvicorn_404_access_log_is_filtered():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", (), None
    )
    record.args = ("127.0.0.1", "GET", "/.env", "1.1", 404)
    assert not _DropNotFoundAccessLog().filter(record)


def test_uvicorn_successful_notification_summary_is_filtered():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", (), None
    )
    record.args = (
        "127.0.0.1", "GET",
        "/api/tech-transfer/v1/me/notifications/summary", "1.1", 200,
    )
    assert not _DropNotFoundAccessLog().filter(record)


def test_uvicorn_successful_admin_notification_summary_is_filtered():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", (), None
    )
    record.args = (
        "127.0.0.1", "GET",
        "/api/tech-transfer/v1/admin/notifications/summary", "1.1", 200,
    )
    assert not _DropNotFoundAccessLog().filter(record)


def test_uvicorn_server_error_access_log_is_kept():
    record = logging.LogRecord(
        "uvicorn.access", logging.INFO, __file__, 1, "%s", (), None
    )
    record.args = ("127.0.0.1", "GET", "/api/example", "1.1", 503)
    assert _DropNotFoundAccessLog().filter(record)
