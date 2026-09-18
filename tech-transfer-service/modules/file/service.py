"""
file service — 文件代理

Architecture source: 04-backend-domain-design.md §file
Source: extracted from app.py inline code (Phase A)

Note: Phase B will replace with proper upload/presign flow per OpenAPI.
框架无关：成功返回 (本地路径, mime)，失败抛 FileProxyError，
由路由层转成 HTTP 响应。
"""

import logging
import hashlib
import mimetypes
import re
import urllib.error
import urllib.request
import uuid
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

from PIL import Image

from config import settings
from core.errors import bad_request, forbidden, not_found
from db import get_cursor

LOGO_CACHE = settings.file_cache_path
LOGO_CACHE.mkdir(parents=True, exist_ok=True)


class FileProxyError(Exception):
    def __init__(self, http_status: int, msg: str):
        super().__init__(msg)
        self.http_status = http_status
        self.msg = msg


# 上传文件与旧的第三方 Logo 代理完全隔离。所有允许类型都要同时满足扩展名、
# 声明 MIME 与文件头（图片）校验，避免把可执行内容伪装成附件。
_ALLOWED = {
    ".png": {"image/png"}, ".jpg": {"image/jpeg"}, ".jpeg": {"image/jpeg"},
    ".webp": {"image/webp"}, ".gif": {"image/gif"},
    ".pdf": {"application/pdf"},
    ".doc": {"application/msword"},
    ".docx": {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
    ".ppt": {"application/vnd.ms-powerpoint"},
    ".pptx": {"application/vnd.openxmlformats-officedocument.presentationml.presentation"},
    ".xls": {"application/vnd.ms-excel"},
    ".xlsx": {"application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"},
}
_IMAGE_SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n", ".jpg": b"\xff\xd8\xff", ".jpeg": b"\xff\xd8\xff",
    ".gif": b"GIF8", ".webp": b"RIFF",
}
_IMAGE_MIMES = {suffix: next(iter(mimes)) for suffix, mimes in _ALLOWED.items() if suffix in _IMAGE_SIGNATURES}


def _safe_name(name: str) -> str:
    name = Path(name or "upload").name.strip()
    return name[:255] or "upload"


def _validate_upload(name: str, content_type: str, data: bytes) -> tuple[str, str]:
    suffix = Path(_safe_name(name)).suffix.lower()
    declared = (content_type or "").split(";", 1)[0].strip().lower()
    if suffix not in _ALLOWED:
        raise bad_request("不支持的文件类型")
    if not data:
        raise bad_request("不能上传空文件")
    signature = _IMAGE_SIGNATURES.get(suffix)
    if signature:
        # 微信上传图片时常把 PNG 标为 application/octet-stream，部分设备还会把
        # 已压缩的 PNG 误标为 image/jpeg。真实魔数才是图片 MIME 的可信来源。
        if not data.startswith(signature) or (suffix == ".webp" and data[8:12] != b"WEBP"):
            raise bad_request("文件内容与声明类型不一致")
        # 仅检查魔数会让“PNG 头 + 任意垃圾”绕过上传，在缩略图/详情阶段才报错。
        # verify 不会完整解码像素，但能确认格式结构可被 Pillow 正常识别。
        try:
            with Image.open(BytesIO(data)) as image:
                image.verify()
        except (OSError, ValueError, SyntaxError, Image.UnidentifiedImageError):
            raise bad_request("文件内容与声明类型不一致")
        return suffix, _IMAGE_MIMES[suffix]
    if declared not in _ALLOWED[suffix]:
        raise bad_request("不支持的文件类型")
    if suffix == ".pdf" and not data.startswith(b"%PDF-"):
        raise bad_request("文件内容与声明类型不一致")
    return suffix, declared


def _image_dimensions(suffix: str, data: bytes) -> tuple[int | None, int | None]:
    """读取已验证图片的像素尺寸；解析失败不阻断非关键元数据写入。"""
    if suffix not in _IMAGE_SIGNATURES:
        return None, None
    try:
        with Image.open(BytesIO(data)) as image:
            width, height = image.size
        return int(width), int(height)
    except (OSError, ValueError):
        return None, None


def _write_thumbnail(source: Path, target: Path) -> None:
    """生成列表专用 JPEG 缩略图；调用方负责缓存键和权限校验。"""
    with Image.open(source) as image:
        image.thumbnail((320, 320), Image.Resampling.LANCZOS)
        if image.mode in ("RGBA", "LA") or (image.mode == "P" and "transparency" in image.info):
            background = Image.new("RGB", image.size, "white")
            alpha = image.getchannel("A") if image.mode in ("RGBA", "LA") else image.convert("RGBA").getchannel("A")
            background.paste(image.convert("RGBA"), mask=alpha)
            image = background
        elif image.mode != "RGB":
            image = image.convert("RGB")
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
        try:
            image.save(temporary, format="JPEG", quality=82, optimize=True)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)


def thumbnail_path_for_file(file_id: int) -> Path:
    return settings.media_root_path / ".thumbnails" / f"{int(file_id)}.jpg"


def get_uploaded_thumbnail(path: Path, mime: str, file_id: int) -> tuple[Path, str]:
    """返回缓存缩略图。非图片明确拒绝，避免以缩略图接口读取附件。"""
    if not (mime or "").startswith("image/"):
        raise bad_request("仅图片支持缩略图")
    thumbnail = thumbnail_path_for_file(file_id)
    try:
        stale = not thumbnail.exists() or thumbnail.stat().st_mtime_ns < path.stat().st_mtime_ns
        if stale:
            _write_thumbnail(path, thumbnail)
    except (OSError, ValueError, Image.UnidentifiedImageError):
        raise bad_request("图片缩略图生成失败")
    return thumbnail, "image/jpeg"


def create_uploaded_file(user_id: int, filename: str, content_type: str, data: bytes) -> dict:
    if len(data) > settings.MAX_UPLOAD_BYTES:
        raise bad_request(f"文件不能超过 {settings.MAX_UPLOAD_BYTES // 1024 // 1024}MB")
    suffix, mime = _validate_upload(filename, content_type, data)
    width, height = _image_dimensions(suffix, data)
    digest = hashlib.sha256(data).hexdigest()
    storage_key = f"{user_id}/{uuid.uuid4().hex}{suffix}"
    path = settings.media_root_path / storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # x 模式确保不会覆盖任何已有对象；DB 写失败时立即删除孤儿文件。
        with path.open("xb") as output:
            output.write(data)
        with get_cursor(commit=True) as cur:
            cur.execute(
                """INSERT INTO file_object
                   (storage_key, original_name, mime_type, size_bytes, sha256, width, height, created_by)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id, created_at""",
                (storage_key, _safe_name(filename), mime, len(data), digest, width, height, user_id),
            )
            row = cur.fetchone()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    return {
        "id": int(row["id"]), "name": _safe_name(filename), "mimeType": mime,
        "sizeBytes": len(data), "sha256": digest,
        "width": width, "height": height,
        "url": f"{settings.MEDIA_BASE_URL.rstrip('/')}/{int(row['id'])}",
        "createdAt": row["created_at"].isoformat() if row.get("created_at") else None,
    }


def get_uploaded_file(
    file_id: int,
    user_id: int | None,
    can_review_import_media: bool = False,
) -> tuple[Path, str, str]:
    with get_cursor() as cur:
        cur.execute(
            "SELECT id, storage_key, original_name, mime_type, created_by FROM file_object WHERE id=%s AND status='active'",
            (file_id,),
        )
        row = cur.fetchone()
    if not row:
        raise not_found("文件不存在")
    # 公开内容的引用文件可读；草稿图仅上传者、成果/需求归属方或机构管理员可读。
    if user_id is None or int(row["created_by"]) != int(user_id):
        with get_cursor() as cur:
            cur.execute(
                """
                SELECT 1 FROM achievement_media am
                JOIN achievement a ON a.id = am.achievement_id AND a.deleted_at IS NULL
                WHERE am.file_id = %s AND (
                    a.status = 'published'
                    OR (%s IS NOT NULL AND a.owner_user_id = %s)
                    OR %s
                    OR (%s IS NOT NULL AND a.org_id IN (
                        SELECT org_id FROM organization_membership
                        WHERE user_id = %s AND role = 'admin' AND status = 'active'
                    ))
                )
                UNION ALL
                SELECT 1 FROM demand_attachment da
                JOIN demand d ON d.id = da.demand_id AND d.deleted_at IS NULL
                WHERE da.file_id = %s AND (
                    d.status = 'published'
                    OR (%s IS NOT NULL AND d.owner_user_id = %s)
                    OR %s
                    OR (%s IS NOT NULL AND d.org_id IN (
                        SELECT org_id FROM organization_membership
                        WHERE user_id = %s AND role = 'admin' AND status = 'active'
                    ))
                )
                LIMIT 1
                """,
                (
                    file_id, user_id, user_id, can_review_import_media, user_id, user_id,
                    file_id, user_id, user_id, can_review_import_media, user_id, user_id,
                ),
            )
            readable = bool(cur.fetchone())
            if not readable and can_review_import_media:
                # 平台管理员仅可在导入尚未形成公开内容前审核候选媒体；JSONB
                # 包含查询精确绑定 fileId，不能借此读取任意私人上传文件。
                cur.execute(
                    """SELECT 1 FROM achievement_import_item
                       WHERE status='staged'
                         AND raw_data @> jsonb_build_object(
                           'images', jsonb_build_array(jsonb_build_object('fileId', %s))
                         )
                       LIMIT 1""",
                    (file_id,),
                )
                readable = bool(cur.fetchone())
            if not readable:
                raise forbidden("无权访问此文件")
    path = (settings.media_root_path / row["storage_key"]).resolve()
    root = settings.media_root_path.resolve()
    if root not in path.parents or not path.is_file():
        raise not_found("文件不存在")
    return path, row["mime_type"], row["original_name"]


def delete_uploaded_file(file_id: int, user_id: int) -> None:
    with get_cursor(commit=True) as cur:
        cur.execute("SELECT storage_key, created_by FROM file_object WHERE id=%s AND status='active' FOR UPDATE", (file_id,))
        row = cur.fetchone()
        if not row:
            raise not_found("文件不存在")
        if int(row["created_by"]) != user_id:
            raise forbidden("无权删除此文件")
        cur.execute(
            """SELECT EXISTS(SELECT 1 FROM achievement_media WHERE file_id=%s)
                      OR EXISTS(SELECT 1 FROM demand_attachment WHERE file_id=%s)
                      OR EXISTS(SELECT 1 FROM inventor WHERE avatar_file_id=%s) AS linked""",
            (file_id, file_id, file_id),
        )
        if cur.fetchone()["linked"]:
            raise bad_request("文件已被内容引用，不能删除")
        cur.execute("UPDATE file_object SET status='deleted', deleted_at=CURRENT_TIMESTAMP, updated_at=CURRENT_TIMESTAMP WHERE id=%s", (file_id,))
    (settings.media_root_path / row["storage_key"]).unlink(missing_ok=True)
    thumbnail_path_for_file(file_id).unlink(missing_ok=True)


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

    source_url = settings.SZTE_FILE_URL
    _split = urlsplit(source_url)
    referer = f"{_split.scheme}://{_split.netloc}/"
    url = source_url.format(file_id=fid)
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Referer": referer,
        "Accept": "image/*,*/*",
    })
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read()
            ctype = (resp.headers.get("Content-Type") or "application/octet-stream").split(";")[0].strip()
    except urllib.error.HTTPError as e:
        # 源站 HTTP 状态码可安全对外；其余细节不外发
        raise FileProxyError(502, f"源站文件获取失败: HTTP {e.code}")
    except Exception as e:
        # 异常文本（URL/网络栈细节）只进日志，响应用固定文案
        logging.getLogger("nanshan.error").warning(
            "file proxy fetch failed file_id=%s err=%r", fid, e
        )
        raise FileProxyError(502, "源站文件获取失败")

    if not content:
        raise FileProxyError(404, "空文件")

    ext = mimetypes.guess_extension(ctype) or ".bin"
    if ext == ".jpe":
        ext = ".jpg"
    path = LOGO_CACHE / f"{fid}{ext}"
    path.write_bytes(content)
    return path, ctype
