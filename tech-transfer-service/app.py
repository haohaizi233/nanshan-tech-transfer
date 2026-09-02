"""
南山科转通 tech-transfer-service —— 模块化单体后端

启动：
  python app.py
默认端口：8787
统一 API 前缀：/api/tech-transfer/v1
"""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pymysql
from flask import Flask, Response, jsonify, request, send_file, g
from flask_cors import CORS

from config import (
    assert_environment,
    API_PREFIX,
    DB_HOST,
    DB_PORT,
    DB_USER,
    DB_PASSWORD,
    DB_NAME,
)
from core.response import success, error
from core.errors import BizError
from db import get_conn, get_cursor
from routes.auth import bp as auth_bp
from routes.me import bp as me_bp

assert_environment()

app = Flask(__name__)
CORS(app)

app.register_blueprint(auth_bp)
app.register_blueprint(me_bp)

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


# ── 资本资源接口（保留现有只读数据服务） ──────────────────────
CAPITAL_DB_CONFIG = {
    "host": DB_HOST,
    "port": DB_PORT,
    "user": DB_USER,
    "password": DB_PASSWORD,
    "database": "nanshan_capital",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

LOGO_CACHE = Path(__file__).resolve().parent / "cache" / "logos"
LOGO_CACHE.mkdir(parents=True, exist_ok=True)
SZTE_FILE_URL = "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"


def _get_capital_conn():
    return pymysql.connect(**CAPITAL_DB_CONFIG)


def _map_type_key(platform_type: str) -> str:
    t = (platform_type or "").strip()
    if "概念验证" in t:
        return "poc"
    if "中小试" in t or "中试" in t:
        return "pilot"
    return "other"


def _row_to_platform_item(row: dict) -> dict:
    ptype = (row.get("platform_type") or "").strip()
    return {
        "id": str(row.get("serial_no") or row.get("id") or ""),
        "serialNo": int(row.get("serial_no") or 0),
        "name": (row.get("platform_name") or "").strip(),
        "platformType": ptype,
        "platformTypeKey": _map_type_key(ptype),
        "unit": (row.get("support_unit") or "").strip(),
        "functionText": (row.get("platform_fun") or "").strip(),
        "contact": (row.get("contact_person") or "").strip(),
        "phone": (row.get("contact_mobile") or "").strip(),
    }


def _logo_url(file_id: str) -> str:
    fid = (file_id or "").strip()
    if not fid:
        return ""
    return f"/api/file/{fid}"


def _row_to_org_item(row: dict, kind: str) -> dict:
    fid = (row.get("logo_file_id") or "").strip()
    return {
        "id": str(row.get("id") or row.get("account") or ""),
        "name": (row.get("org_name") or "").strip(),
        "intro": (row.get("intro") or "").strip(),
        "detailInfo": (row.get("detail_info") or "").strip(),
        "label": (row.get("label") or "").strip(),
        "logoFileId": fid,
        "logoUrl": _logo_url(fid),
        "kind": kind,
        "sortOrder": int(row.get("sort_order") or 0),
    }


def _parse_page_args():
    try:
        page = max(1, int(request.args.get("page") or 1))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(50, int(request.args.get("pageSize") or 10)))
    except ValueError:
        page_size = 10
    keyword = (request.args.get("keyword") or "").strip()
    return page, page_size, keyword


def _query_org_list(table: str, kind: str, keyword_fields: list[str]):
    page, page_size, keyword = _parse_page_args()
    where_sql = " WHERE 1=1"
    params: list = []
    if keyword:
        like = f"%{keyword}%"
        parts = [f"{f} LIKE %s" for f in keyword_fields]
        where_sql += " AND (" + " OR ".join(parts) + ")"
        params.extend([like] * len(keyword_fields))

    count_sql = f"SELECT COUNT(*) AS c FROM `{table}`" + where_sql
    list_sql = f"SELECT * FROM `{table}`" + where_sql + " ORDER BY sort_order ASC, id ASC LIMIT %s OFFSET %s"

    try:
        conn = _get_capital_conn()
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = int((cur.fetchone() or {}).get("c") or 0)
            offset = (page - 1) * page_size
            cur.execute(list_sql, params + [page_size, offset])
            rows = cur.fetchall() or []
        conn.close()
    except Exception as e:
        return None, f"数据库查询失败: {e}"

    total_pages = (total + page_size - 1) // page_size if total else 0
    return {
        "total": total,
        "page": page,
        "pageSize": page_size,
        "totalPages": total_pages,
        "list": [_row_to_org_item(r, kind) for r in rows],
    }, None


@app.get("/api/platform-base")
def platform_base_list():
    type_key = (request.args.get("type") or "all").strip().lower()
    keyword = (request.args.get("keyword") or "").strip()
    try:
        page = max(1, int(request.args.get("page") or 1))
    except ValueError:
        page = 1
    try:
        page_size = max(1, min(50, int(request.args.get("pageSize") or 10)))
    except ValueError:
        page_size = 10

    where_sql = " WHERE 1=1"
    params = []
    if type_key == "poc":
        where_sql += " AND platform_type LIKE %s"
        params.append("%概念验证%")
    elif type_key == "pilot":
        where_sql += " AND (platform_type LIKE %s OR platform_type LIKE %s)"
        params.extend(["%中小试%", "%中试%"])
        where_sql += " AND platform_type NOT LIKE %s"
        params.append("%概念验证%")
    if keyword:
        where_sql += " AND (platform_name LIKE %s OR support_unit LIKE %s OR platform_fun LIKE %s OR contact_person LIKE %s OR contact_mobile LIKE %s)"
        like = f"%{keyword}%"
        params.extend([like, like, like, like, like])

    count_sql = "SELECT COUNT(*) AS c FROM platform_base" + where_sql
    list_sql = "SELECT id, serial_no, platform_name, platform_type, support_unit, platform_fun, contact_person, contact_mobile FROM platform_base" + where_sql + " ORDER BY serial_no ASC LIMIT %s OFFSET %s"

    try:
        conn = _get_capital_conn()
        with conn.cursor() as cur:
            cur.execute(count_sql, params)
            total = int((cur.fetchone() or {}).get("c") or 0)
            offset = (page - 1) * page_size
            cur.execute(list_sql, params + [page_size, offset])
            rows = cur.fetchall() or []
        conn.close()
    except Exception as e:
        return jsonify({"code": 1, "msg": f"数据库查询失败: {e}", "data": None}), 500

    total_pages = (total + page_size - 1) // page_size if total else 0
    items = [_row_to_platform_item(r) for r in rows]
    return jsonify({"code": 0, "msg": "ok", "data": {"total": total, "page": page, "pageSize": page_size, "totalPages": total_pages, "list": items}})


@app.get("/api/service-orgs")
def service_orgs_list():
    data, err = _query_org_list("ip_service_org", "bank", ["org_name", "intro", "label"])
    if err:
        return jsonify({"code": 1, "msg": err, "data": None}), 500
    return jsonify({"code": 0, "msg": "ok", "data": data})


@app.get("/api/invest-orgs")
def invest_orgs_list():
    data, err = _query_org_list("featured_invest_org", "invest", ["org_name", "intro"])
    if err:
        return jsonify({"code": 1, "msg": err, "data": None}), 500
    return jsonify({"code": 0, "msg": "ok", "data": data})


@app.get("/api/file/<file_id>")
def proxy_file(file_id: str):
    fid = re.sub(r"[^0-9A-Za-z_-]", "", file_id or "")
    if not fid:
        return jsonify({"code": 1, "msg": "无效文件 id"}), 400
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bin"):
        cached = LOGO_CACHE / f"{fid}{ext}"
        if cached.exists() and cached.stat().st_size > 0:
            mime = mimetypes.guess_type(str(cached))[0] or "application/octet-stream"
            return send_file(cached, mimetype=mime)
    url = SZTE_FILE_URL.format(file_id=fid)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": "https://www.szte.com/",
        "Accept": "image/*,*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
    except urllib.error.HTTPError as e:
        return jsonify({"code": 1, "msg": f"源站文件获取失败: HTTP {e.code}"}), 502
    except Exception as e:
        return jsonify({"code": 1, "msg": f"源站文件获取失败: {e}"}), 502
    if not content:
        return jsonify({"code": 1, "msg": "空文件"}), 404
    ext = mimetypes.guess_extension(ctype) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    path = LOGO_CACHE / f"{fid}{ext}"
    path.write_bytes(content)
    return send_file(path, mimetype=ctype)


if __name__ == "__main__":
    print("tech-transfer-service listening on http://0.0.0.0:8787")
    print(f"  API prefix: {API_PREFIX}")
    print("  Health:     http://127.0.0.1:8787/api/health")
    print("  Bootstrap:  POST http://127.0.0.1:8787/api/tech-transfer/v1/auth/bootstrap")
    print("  Get Me:     GET  http://127.0.0.1:8787/api/tech-transfer/v1/me")
    app.run(host="0.0.0.0", port=8787, debug=True)
