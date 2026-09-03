"""
file service — 文件代理

Architecture source: 04-backend-domain-design.md §file
Source: extracted from app.py inline code (Phase A)

Note: Phase B will replace with proper upload/presign flow per OpenAPI.
框架无关：成功返回 (本地路径, mime)，失败抛 FileProxyError，
由路由层转成 HTTP 响应。
"""

import mimetypes
import re
import urllib.error
import urllib.request
from pathlib import Path

LOGO_CACHE = Path(__file__).resolve().parent.parent / "cache" / "logos"
LOGO_CACHE.mkdir(parents=True, exist_ok=True)
SZTE_FILE_URL = "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId={file_id}"


class FileProxyError(Exception):
    def __init__(self, http_status: int, msg: str):
        super().__init__(msg)
        self.http_status = http_status
        self.msg = msg


def proxy_file(file_id: str) -> tuple[Path, str]:
    """返回 (本地文件路径, mimetype)，失败抛 FileProxyError。"""
    fid = re.sub(r"[^0-9A-Za-z_-]", "", file_id or "")
    if not fid:
        raise FileProxyError(400, "无效文件 id")

    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".bin"):
        cached = LOGO_CACHE / f"{fid}{ext}"
        if cached.exists() and cached.stat().st_size > 0:
            mime = mimetypes.guess_type(str(cached))[0] or "application/octet-stream"
            return cached, mime

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
        raise FileProxyError(502, f"源站文件获取失败: HTTP {e.code}")
    except Exception as e:
        raise FileProxyError(502, f"源站文件获取失败: {e}")

    if not content:
        raise FileProxyError(404, "空文件")

    ext = mimetypes.guess_extension(ctype) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    path = LOGO_CACHE / f"{fid}{ext}"
    path.write_bytes(content)
    return path, ctype
