"""
南山科转通 tech-transfer-service —— 模块化单体后端

启动：
  python app.py
默认端口：8787
统一 API 前缀：/api/tech-transfer/v1
"""

from __future__ import annotations

import uuid

from flask import Flask, Response, jsonify, request, g
from flask_cors import CORS

from config import assert_environment, API_PREFIX
from core.response import success, error
from core.errors import BizError
from db import get_conn, get_cursor
from routes.auth import bp as auth_bp
from routes.me import bp as me_bp
from routes.achievement import bp as achievement_bp
from routes.capital import bp as capital_bp
from routes.file import bp as file_bp

assert_environment()

app = Flask(__name__)
CORS(app)

app.register_blueprint(auth_bp)
app.register_blueprint(me_bp)
app.register_blueprint(achievement_bp)
app.register_blueprint(capital_bp)
app.register_blueprint(file_bp)

# ── 请求 ID 中间件 ──────────────────────────────────────────
@app.before_request
def _set_request_id():
    g.request_id = request.headers.get("X-Request-Id") or str(uuid.uuid4())


# ── 统一错误处理 ─────────────────────────────────────────────
@app.errorhandler(BizError)
def _handle_biz_error(e: BizError):
    return error(e.code, e.message, e.http_status, e.details)


@app.errorhandler(404)
def _handle_404(_):
    return error("TT_COMMON_40401", "接口不存在", 404)


@app.errorhandler(500)
def _handle_500(e):
    return error("TT_COMMON_50001", f"服务内部错误: {e}", 500)


# ── 健康检查 ─────────────────────────────────────────────────
@app.get("/api/health")
def health():
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_user")
            user_count = cur.fetchone()["c"]
        import config as _cfg
        return jsonify({
            "code": 0,
            "message": "ok",
            "data": {
                "db": True,
                "appUsers": user_count,
                "authProvider": _cfg.AUTH_PROVIDER,
                "appEnv": _cfg.APP_ENV,
            },
        })
    except Exception as e:
        return jsonify({"code": 1, "message": str(e), "data": {"db": False}}), 500


if __name__ == "__main__":
    print("tech-transfer-service listening on http://0.0.0.0:8787")
    print(f"  API prefix: {API_PREFIX}")
    print("  Health:     http://127.0.0.1:8787/api/health")
    print("  Bootstrap:  POST http://127.0.0.1:8787/api/tech-transfer/v1/auth/bootstrap")
    print("  Get Me:     GET  http://127.0.0.1:8787/api/tech-transfer/v1/me")
    app.run(host="0.0.0.0", port=8787, debug=True)
