"""
file routes — 文件代理路由

Architecture source: 06-api-design.md §uploads
Source: extracted from app.py inline code (Phase A)
"""

from flask import Blueprint

from modules.file.service import proxy_file

bp = Blueprint("file", __name__)


@bp.get("/api/file/<file_id>")
def get_file(file_id: str):
    return proxy_file(file_id)
