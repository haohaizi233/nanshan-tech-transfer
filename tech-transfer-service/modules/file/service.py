"""
file service — 文件代理

Architecture source: 04-backend-domain-design.md §file
Source: extracted from app.py inline code (Phase A)

Note: Phase B will replace with proper upload/presign flow per OpenAPI.
"""

import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path

from flask import jsonify, send_file

LOGO_CACHE = Path(__file__).resolve().parent.parent / "cache" / "logos"
LOGO_CACHE.mkdir(parents=True, exist_ok=True)
SZTE_FILE_URL = "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"


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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
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
