"""
成果路由 —— GET /achievements, GET /achievements/{id}, GET /search
"""
from flask import Blueprint, request, g
from core.response import success
from core.errors import bad_request
from core.middleware import auth_required
from modules.achievement.service import (
    list_achievements,
    get_achievement_detail,
    list_categories,
)

bp = Blueprint("achievement", __name__, url_prefix="/api/tech-transfer/v1")


@bp.get("/achievements")
@auth_required
def achievements_list():
    result = list_achievements(request.args)
    return success(result)


@bp.get("/achievements/categories")
@auth_required
def achievements_categories():
    result = list_categories()
    return success(result)


@bp.get("/achievements/<int:ach_id>")
@auth_required
def achievement_detail(ach_id: int):
    detail = get_achievement_detail(ach_id)
    if not detail:
        return success(None, "成果不存在或未发布")
    return success(detail)


@bp.get("/search")
@auth_required
def search():
    search_type = (request.args.get("type") or "").strip()
    if search_type != "achievement":
        return success({"total": 0, "list": [], "page": 1, "pageSize": 10, "totalPages": 0})
    result = list_achievements(request.args)
    return success(result)
