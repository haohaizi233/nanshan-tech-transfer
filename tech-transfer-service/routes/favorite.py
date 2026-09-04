"""
收藏路由 —— /favorites/{targetType}/{targetId}（幂等 PUT/DELETE）

Architecture source: openapi.yaml paths /favorites/{targetType}/{targetId}；06-api-design.md §8
"""
from fastapi import APIRouter, Depends

from core.response import success, get_request_id
from core.middleware import identity
from modules.favorite.service import add_favorite, remove_favorite

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["favorite"])


@router.put("/favorites/{target_type}/{target_id}")
def favorite_add(target_type: str, target_id: int, user: dict = Depends(identity)):
    result = add_favorite(
        user["userId"], user.get("userNo", ""), target_type, target_id,
        request_id=get_request_id(),
    )
    return success(result)


@router.delete("/favorites/{target_type}/{target_id}")
def favorite_remove(target_type: str, target_id: int, user: dict = Depends(identity)):
    remove_favorite(
        user["userId"], user.get("userNo", ""), target_type, target_id,
        request_id=get_request_id(),
    )
    return success(None, "已取消收藏")
