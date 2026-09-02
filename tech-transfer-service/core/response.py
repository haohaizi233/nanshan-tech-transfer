from flask import jsonify, g
from datetime import datetime, timezone
import uuid


def _request_id():
    if hasattr(g, "request_id"):
        return g.request_id
    return str(uuid.uuid4())


def success(data=None, message="ok"):
    return jsonify({
        "code": 0,
        "message": message,
        "data": data,
        "requestId": _request_id(),
    })


def error(code: str, message: str, http_status: int = 400, details=None):
    body = {
        "code": code,
        "message": message,
        "requestId": _request_id(),
    }
    if details is not None:
        body["details"] = details
    return jsonify(body), http_status
