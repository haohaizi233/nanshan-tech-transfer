"""
file routes — 文件代理路由

Architecture source: 06-api-design.md §uploads
Source: extracted from app.py inline code (Phase A)
"""

from fastapi import APIRouter
from fastapi.responses import FileResponse, JSONResponse

from modules.file.service import proxy_file, FileProxyError

router = APIRouter()


@router.get("/api/file/{file_id}")
def get_file(file_id: str):
    try:
        path, mime = proxy_file(file_id)
    except FileProxyError as e:
        return JSONResponse(status_code=e.http_status, content={"code": 1, "msg": e.msg})
    return FileResponse(path, media_type=mime)
