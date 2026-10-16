"""
capital routes — 资本对接只读接口（legacy 兼容层）

DEPRECATED since 2026-09-08: 前端已切统一机构接口 /api/tech-transfer/v1/institutions
（routes/institution.py，institution 单表），本文件仅保留 legacy 三路径兼容期，
响应格式零差异（modules/capital/service.py 适配 institution 表）。下线计划见 17-change-report。

Architecture source: 06-api-design.md §capital
Source: extracted from app.py inline code (Phase A)

Phase A: 保留旧路径 (/api/platform-base, /api/invest-orgs, /api/service-orgs) 兼容
Phase B: 数据源迁移至 institution 表（/institutions 新路径由 institution.py 承接）
"""

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.pagination import parse_page_args
from core.response import success
from modules.capital.service import list_orgs, list_platforms

router = APIRouter(tags=["capital"])


def _deprecated_response(payload: dict, request: Request) -> JSONResponse:
    """legacy 路径响应：附加 Deprecation/Sunset 头，并在服务端日志告警。"""
    import logging
    logging.getLogger("nanshan.deprecation").warning(
        "legacy capital route called path=%s ua=%s",
        request.url.path,
        request.headers.get("user-agent", "")[:80],
    )
    body = success(payload)
    resp = JSONResponse(content=body)
    resp.headers["Deprecation"] = "true"
    resp.headers["Link"] = '</api/tech-transfer/v1/institutions>; rel="successor-version"'
    return resp


@router.get("/api/platform-base")
def platform_base_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    type_key = (request.query_params.get("type") or "all").strip().lower()
    data = list_platforms(page, page_size, type_key, keyword)
    return _deprecated_response(data, request)


@router.get("/api/invest-orgs")
def invest_orgs_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    data = list_orgs("invest", ["org_name", "intro"], page, page_size, keyword)
    return _deprecated_response(data, request)


@router.get("/api/service-orgs")
def service_orgs_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    data = list_orgs("bank", ["org_name", "intro", "label"], page, page_size, keyword)
    return _deprecated_response(data, request)
