"""
pagination utilities

Architecture source: 06-api-design.md §general (page/pageSize/keyword/sort)
Source: extracted from app.py _parse_page_args (Phase A)
"""

from fastapi import Request


def parse_page_args(request: Request):
    """Parse page, pageSize, keyword from query string.

    Returns (page, page_size, keyword) with defaults (1, 10, "").
    page_size is clamped to [1, 50].
    """
    args = request.query_params
    try:
        page = max(1, int(args.get("page") or 1))
    except (ValueError, TypeError):
        page = 1
    try:
        page_size = max(1, min(50, int(args.get("pageSize") or 10)))
    except (ValueError, TypeError):
        page_size = 10
    keyword = (args.get("keyword") or "").strip()
    return page, page_size, keyword
