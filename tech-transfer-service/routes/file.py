"""
file routes — 文件代理路由

Architecture source: 06-api-design.md §uploads
Source: extracted from app.py inline code (Phase A)

错误契约（T008）：FileProxyError 在路由层翻译为 BizError，
走全局统一异常处理器，不再输出 {"code":1,"msg":...} 并行格式。
"""

from fastapi import APIRouter, Depends, File, Request, UploadFile
from fastapi.responses import FileResponse

from core.errors import BizError, TT_FILE_40001, TT_FILE_40401, TT_FILE_50201
from core.middleware import identity, identity_from_access_token, optional_identity
from core.response import success
from modules.file.service import (
    proxy_file, FileProxyError, create_uploaded_file, get_uploaded_file, get_uploaded_thumbnail, delete_uploaded_file,
)

router = APIRouter(tags=["file"])

# FileProxyError.http_status → 统一错误码（HTTP 语义保持不变）
_FILE_ERROR_MAP = {
    400: TT_FILE_40001,
    404: TT_FILE_40401,
    502: TT_FILE_50201,
}


@router.get("/api/file/{file_id}")
def get_file(file_id: str):
    try:
        path, mime = proxy_file(file_id)
    except FileProxyError as e:
        code, _msg, status = _FILE_ERROR_MAP.get(e.http_status, TT_FILE_50201)
        raise BizError(code, e.msg, status)
    return FileResponse(path, media_type=mime)


@router.post("/api/tech-transfer/v1/files", status_code=201, summary="上传成果/需求媒体")
async def upload_file(file: UploadFile = File(...), user: dict = Depends(identity)):
    # UploadFile 不调用 read() 无上限后直接落盘，先受限读取，拒绝大文件以防内存耗尽。
    max_bytes = __import__("config").settings.MAX_UPLOAD_BYTES
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        from core.errors import bad_request
        raise bad_request(f"文件不能超过 {max_bytes // 1024 // 1024}MB")
    result = create_uploaded_file(user["userId"], file.filename or "upload", file.content_type or "", data)
    return success(result, "上传成功")


@router.get("/api/tech-transfer/v1/files/{file_id}", summary="读取已授权上传文件")
def get_uploaded(request: Request, file_id: int, variant: str = "", user: dict = Depends(optional_identity)):
    actor = user
    if actor.get("userId") is None:
        queried = identity_from_access_token(request.query_params.get("access_token") or "")
        if queried:
            actor = queried
    # 不信任 JWT roles 快照：实时查 user_role 表判定平台管理员（与 admin_identity 同源）。
    actor_id = actor.get("userId")
    can_review_import_media = False
    if actor_id is not None:
        from db import get_cursor
        with get_cursor() as cur:
            cur.execute(
                "SELECT 1 FROM user_role WHERE user_id = %s AND role_code = 'admin'",
                (actor_id,),
            )
            can_review_import_media = cur.fetchone() is not None
    path, mime, name = get_uploaded_file(
        file_id,
        actor["userId"],
        can_review_import_media=can_review_import_media,
    )
    if variant:
        if variant != "thumbnail":
            from core.errors import bad_request
            raise bad_request("不支持的文件变体")
        path, mime = get_uploaded_thumbnail(path, mime, file_id)
    return FileResponse(path, media_type=mime, filename=name, content_disposition_type="inline")


@router.delete("/api/tech-transfer/v1/files/{file_id}", summary="删除未被引用的上传文件")
def delete_uploaded(file_id: int, user: dict = Depends(identity)):
    delete_uploaded_file(file_id, user["userId"])
    return success(None, "已删除")
