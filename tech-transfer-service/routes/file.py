"""
file routes — 文件代理路由

Architecture source: 06-api-design.md §uploads
Source: extracted from app.py inline code (Phase A)

错误契约（T008）：FileProxyError 在路由层翻译为 BizError，
走全局统一异常处理器，不再输出 {"code":1,"msg":...} 并行格式。
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse

from core.errors import BizError, TT_FILE_40001, TT_FILE_40401, TT_FILE_50201
from modules.file.service import proxy_file, FileProxyError

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
