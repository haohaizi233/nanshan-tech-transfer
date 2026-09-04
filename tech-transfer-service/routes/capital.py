"""
capital routes — 资本对接只读接口

Architecture source: 06-api-design.md §capital
Source: extracted from app.py inline code (Phase A)

Phase A: 保留旧路径 (/api/platform-base, /api/invest-orgs, /api/service-orgs) 兼容
Phase B: 迁移到 /api/tech-transfer/v1/capital/* 新路径
"""

from fastapi import APIRouter, Request

from core.response import success
from core.pagination import parse_page_args
from modules.capital.service import list_platforms, list_orgs

router = APIRouter(tags=["capital"])


@router.get("/api/platform-base")
def platform_base_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    type_key = (request.query_params.get("type") or "all").strip().lower()
    data = list_platforms(page, page_size, type_key, keyword)
    return success(data)


@router.get("/api/invest-orgs")
def invest_orgs_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    data = list_orgs("invest", ["org_name", "intro"], page, page_size, keyword)
    return success(data)


@router.get("/api/service-orgs")
def service_orgs_list(request: Request):
    page, page_size, keyword = parse_page_args(request)
    data = list_orgs("bank", ["org_name", "intro", "label"], page, page_size, keyword)
    return success(data)
