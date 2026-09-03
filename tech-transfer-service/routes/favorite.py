"""
收藏路由 —— /favorites/{targetType}/{targetId}（幂等 PUT/DELETE）

Architecture source: openapi.yaml paths /favorites/{targetType}/{targetId}；06-api-design.md §8
"""
from flask import Blueprint, request, g

from core.response import success
from core.middleware import auth_required
from modules.favorite.service import add_favorite, remove_favorite

bp = Blueprint("favorite", __name__, url_prefix="/api/tech-transfer/v1")


@bp.put("/favorites/<target_type>/<int:target_id>")
@auth_required
def favorite_add(target_type: str, target_id: int):
    user = g.identity
    result = add_favorite(
        user["userId"], user.get("userNo", ""), target_type, target_id,
        request_id=g.get("request_id"),
    )
    return success(result)


@bp.delete("/favorites/<target_type>/<int:target_id>")
@auth_required
def favorite_remove(target_type: str, target_id: int):
    user = g.identity
    remove_favorite(
        user["userId"], user.get("userNo", ""), target_type, target_id,
        request_id=g.get("request_id"),
    )
    return success(None, "已取消收藏")
