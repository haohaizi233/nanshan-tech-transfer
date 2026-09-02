"""
南山科转通 - 本地 API
读取 MySQL nanshan_capital，供微信小程序调用。

启动：
  python app.py
默认：http://0.0.0.0:8787
"""

from __future__ import annotations

import json
import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path

import pymysql
from flask import Flask, Response, jsonify, request, send_file
from flask_cors import CORS

ROOT = Path(__file__).resolve().parent
CRAWLER_CFG = ROOT.parent / "platform-crawler" / "db_config.json"
SZTE_CFG = ROOT.parent / "szte-crawler" / "db_config.json"
LOGO_CACHE = ROOT / "cache" / "logos"
SZTE_FILE_URL = "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"

app = Flask(__name__)
CORS(app)
LOGO_CACHE.mkdir(parents=True, exist_ok=True)


def load_db_config() -> dict:
    cfg_path = SZTE_CFG if SZTE_CFG.exists() else CRAWLER_CFG
    if cfg_path.exists():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        return {
            "host": cfg.get("host", "127.0.0.1"),
            "port": int(cfg.get("port", 3307)),
            "user": cfg.get("user", "root"),
            "password": cfg.get("password", ""),
            "database": cfg.get("database", "nanshan_capital"),
            "charset": "utf8mb4",
            "cursorclass": pymysql.cursors.DictCursor,
        }
    return {
        "host": "127.0.0.1",
        "port": 3307,
        "user": "root",
        "password": "",
        "database": "nanshan_capital",
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
    }


def get_conn():
    return pymysql.connect(**load_db_config())


def map_type_key(platform_type: str) -> str:
    t = (platform_type or "").strip()
    if "概念验证" in t:
        return "poc"
    if "中小试" in t or "中试" in t:
        return "pilot"
    return "other"


def row_to_platform_item(row: dict) -> dict:
    ptype = (row.get("platform_type") or "").strip()
    return {
        "id": str(row.get("serial_no") or row.get("id") or ""),
        "serialNo": int(row.get("serial_no") or 0),
        "name": (row.get("platform_name") or "").strip(),
        "platformType": ptype,
        "platformTypeKey": map_type_key(ptype),
        "unit": (row.get("support_unit") or "").strip(),
        "functionText": (row.get("platform_fun") or "").strip(),
        "contact": (row.get("contact_person") or "").strip(),
        "phone": (row.get("contact_mobile") or "").strip(),
    }


def logo_url(file_id: str) -> str:
    fid = (file_id or "").strip()
    if not fid:
        return ""
    return f"/api/file/{fid}"


def row_to_org_item(row: dict, kind: str) -> dict:
    fid = (row.get("logo_file_id") or "").strip()
    return {
        "id": str(row.get("id") or row.get("account") or ""),
        "name": (row.get("org_name") or "").strip(),
        "intro": (row.get("intro") or "").strip(),
        "detailInfo": (row.get("detail_info") or "").strip(),
        "label": (row.get("label") or "").strip(),
        "logoFileId": fid,
        "logoUrl": logo_url(fid),
        "kind": kind,
        "sortOrder": int(row.get("sort_order") or 0),
    }


def parse_page_args():
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


def query_org_list(table: str, kind: str, keyword_fields: list[str]):
    page, page_size, keyword = parse_page_args()
    where_sql = " WHERE 1=1"
    params: list = []
    if keyword:
        like = f"%{keyword}%"
        parts = [f"{f} LIKE %s" for f in keyword_fields]
        where_sql += " AND (" + " OR ".join(parts) + ")"
        params.extend([like] * len(keyword_fields))

    count_sql = f"SELECT COUNT(*) AS c FROM `{table}`" + where_sql
    list_sql = f"""
        SELECT *
        FROM `{table}`
    """ + where_sql + " ORDER BY sort_order ASC, id ASC LIMIT %s OFFSET %s"

    try:
        conn = get_conn()
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
        "list": [row_to_org_item(r, kind) for r in rows],
    }, None


@app.get("/api/health")
def health():
    try:
        conn = get_conn()
        with conn.cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM platform_base")
            platform_count = cur.fetchone()["c"]
            try:
                cur.execute("SELECT COUNT(*) AS c FROM ip_service_org")
                service_count = cur.fetchone()["c"]
            except Exception:
                service_count = None
            try:
                cur.execute("SELECT COUNT(*) AS c FROM featured_invest_org")
                invest_count = cur.fetchone()["c"]
            except Exception:
                invest_count = None
        conn.close()
        return jsonify(
            {
                "code": 0,
                "msg": "ok",
                "data": {
                    "db": True,
                    "platformBase": platform_count,
                    "serviceOrg": service_count,
                    "investOrg": invest_count,
                },
            }
        )
    except Exception as e:
        return jsonify({"code": 1, "msg": str(e), "data": {"db": False}}), 500


@app.get("/api/platform-base")
def platform_base_list():
    """
    query:
      type = poc | pilot | all
      keyword = 可选关键词（名称/单位/功能/联系人）
      page = 页码，从 1 开始，默认 1
      pageSize = 每页条数，默认 10
    """
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
        where_sql += """
            AND (
                platform_name LIKE %s
                OR support_unit LIKE %s
                OR platform_fun LIKE %s
                OR contact_person LIKE %s
                OR contact_mobile LIKE %s
            )
        """
        like = f"%{keyword}%"
        params.extend([like, like, like, like, like])

    count_sql = "SELECT COUNT(*) AS c FROM platform_base" + where_sql
    list_sql = """
        SELECT id, serial_no, platform_name, platform_type, support_unit,
               platform_fun, contact_person, contact_mobile
        FROM platform_base
    """ + where_sql + " ORDER BY serial_no ASC LIMIT %s OFFSET %s"

    try:
        conn = get_conn()
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
    items = [row_to_platform_item(r) for r in rows]
    return jsonify(
        {
            "code": 0,
            "msg": "ok",
            "data": {
                "total": total,
                "page": page,
                "pageSize": page_size,
                "totalPages": total_pages,
                "list": items,
            },
        }
    )


@app.get("/api/service-orgs")
def service_orgs_list():
    """银行融资 ← 专业服务机构。query: keyword/page/pageSize"""
    data, err = query_org_list(
        "ip_service_org",
        "bank",
        ["org_name", "intro", "label"],
    )
    if err:
        return jsonify({"code": 1, "msg": err, "data": None}), 500
    return jsonify({"code": 0, "msg": "ok", "data": data})


@app.get("/api/invest-orgs")
def invest_orgs_list():
    """投资机构 ← 特色投资机构。query: keyword/page/pageSize"""
    data, err = query_org_list(
        "featured_invest_org",
        "invest",
        ["org_name", "intro"],
    )
    if err:
        return jsonify({"code": 1, "msg": err, "data": None}), 500
    return jsonify({"code": 0, "msg": "ok", "data": data})


@app.get("/api/file/<file_id>")
def proxy_file(file_id: str):
    """代理科交中心图片，避免小程序直连外域；本地缓存。"""
    fid = re.sub(r"[^0-9A-Za-z_-]", "", file_id or "")
    if not fid:
        return jsonify({"code": 1, "msg": "无效文件 id"}), 400

    # 已有缓存
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bin"):
        cached = LOGO_CACHE / f"{fid}{ext}"
        if cached.exists() and cached.stat().st_size > 0:
            mime = mimetypes.guess_type(str(cached))[0] or "application/octet-stream"
            return send_file(cached, mimetype=mime)

    url = SZTE_FILE_URL.format(file_id=fid)
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ),
            "Referer": "https://www.szte.com/",
            "Accept": "image/*,*/*",
        },
    )
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
    print("API listening on http://0.0.0.0:8787")
    print("Health:      http://127.0.0.1:8787/api/health")
    print("Platform:    http://127.0.0.1:8787/api/platform-base?type=poc")
    print("ServiceOrgs: http://127.0.0.1:8787/api/service-orgs")
    print("InvestOrgs:  http://127.0.0.1:8787/api/invest-orgs")
    app.run(host="0.0.0.0", port=8787, debug=False)
