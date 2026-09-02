"""
capital routes — 资本对接只读接口

Architecture source: 06-api-design.md §capital
Source: extracted from app.py inline code (Phase A)

Phase A: 保留旧路径 (/api/platform-base, /api/invest-orgs, /api/service-orgs) 兼容
Phase B: 迁移到 /api/tech-transfer/v1/capital/* 新路径
"""

from flask import Blueprint, request, jsonify

from core.response import success, error
from core.pagination import parse_page_args
from modules.capital.service import list_platforms, list_orgs

bp = Blueprint("capital", __name__)


@bp.get("/api/platform-base")
def platform_base_list():
    page, page_size, keyword = parse_page_args()
    type_key = (request.args.get("type") or "all").strip().lower()
    data = list_platforms(page, page_size, type_key, keyword)
    return success(data)


@bp.get("/api/invest-orgs")
def invest_orgs_list():
    page, page_size, keyword = parse_page_args()
    data = list_orgs("featured_invest_org", "invest", ["org_name", "intro"], page, page_size, keyword)
    return success(data)


@bp.get("/api/service-orgs")
def service_orgs_list():
    page, page_size, keyword = parse_page_args()
    data = list_orgs("ip_service_org", "bank", ["org_name", "intro", "label"], page, page_size, keyword)
    return success(data)
