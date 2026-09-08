"""
search routes —— GET /search 统一搜索（成果 + 需求双类型聚合）

Architecture source: 06-api-design.md §search, openapi.yaml /search
Phase B 收口：接管原挂于 achievement 路由的 type=achievement 单类型实现。
"""

from fastapi import APIRouter, Depends, Request

from core.response import success
from core.errors import bad_request
from core.pagination import parse_page_args
from core.middleware import identity
from modules.search.service import search

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["search"])


@router.get("/search", summary="统一搜索（achievement/demand/all 双类型聚合）")
def search_endpoint(request: Request, user: dict = Depends(identity)):
    q = (request.query_params.get("q") or "").strip()
    if not q:
        raise bad_request("q 不能为空")
    if len(q) > 64:
        raise bad_request("q 长度不能超过 64")

    search_type = (request.query_params.get("type") or "all").strip().lower()
    if search_type not in ("achievement", "demand", "all"):
        raise bad_request("type 必须是 achievement/demand/all")

    page, page_size, _ = parse_page_args(request)
    category_code = (request.query_params.get("categoryCode") or "").strip()
    maturity_level = (request.query_params.get("maturityLevel") or "").strip()

    data = search(q, search_type, category_code, maturity_level, page, page_size, user.get("userId"))
    return success(data)
