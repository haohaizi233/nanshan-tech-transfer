"""
统一机构路由 —— GET /institutions, GET /institutions/{id}

Architecture source: 06-api-design.md §capital（公开数据，无需登录）
P0-1：接管 legacy 三接口的数据源（institution 表），新路径按 kind 统一。
"""
from fastapi import APIRouter, Request

from core.response import success
from core.errors import bad_request
from core.pagination import parse_page_args
from modules.institution.service import (
    KINDS,
    list_institutions,
    get_institution_detail,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["institution"])


@router.get("/institutions")
def institutions_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    kind = (request.query_params.get("kind") or "all").strip().lower()
    if kind not in KINDS and kind != "all":
        raise bad_request(f"kind 必须是 {'/'.join(KINDS)}/all")
    type_key = (request.query_params.get("type") or "all").strip().lower()
    if kind == "platform" and type_key not in ("poc", "pilot", "other", "all"):
        raise bad_request("type 必须是 poc/pilot/other/all")
    data = list_institutions(page, page_size, kind, type_key, keyword)
    return success(data)


@router.get("/institutions/{inst_id}")
def institution_detail(inst_id: int):
    detail = get_institution_detail(inst_id)
    if not detail:
        return success(None, "机构不存在或已下架")
    return success(detail)
