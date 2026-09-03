"""
成果路由 —— GET /achievements, GET /achievements/{id}, GET /search
"""
from fastapi import APIRouter, Depends, Request

from core.response import success
from core.middleware import identity
from modules.achievement.service import (
    list_achievements,
    get_achievement_detail,
    list_categories,
)

router = APIRouter(prefix="/api/tech-transfer/v1")


@router.get("/achievements")
def achievements_list(request: Request, user: dict = Depends(identity)):
    result = list_achievements(request.query_params)
    return success(result)


@router.get("/achievements/categories")
def achievements_categories(user: dict = Depends(identity)):
    result = list_categories()
    return success(result)


@router.get("/achievements/{ach_id}")
def achievement_detail(ach_id: int, user: dict = Depends(identity)):
    detail = get_achievement_detail(ach_id)
    if not detail:
        return success(None, "成果不存在或未发布")
    return success(detail)


@router.get("/search")
def search(request: Request, user: dict = Depends(identity)):
    search_type = (request.query_params.get("type") or "").strip()
    if search_type != "achievement":
        return success({"total": 0, "list": [], "page": 1, "pageSize": 10, "totalPages": 0})
    result = list_achievements(request.query_params)
    return success(result)
