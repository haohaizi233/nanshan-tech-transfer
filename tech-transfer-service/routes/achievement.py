"""
成果路由 —— GET /achievements（列表/详情/分类/搜索）+ 用户写接口（P0-5）

Architecture source: openapi.yaml paths /achievements, /achievements/{id},
                     /achievements/{id}/submit|offline；06-api-design.md §7、§5.1
"""
from fastapi import APIRouter, Depends, Request

from core.response import success, get_request_id
from core.middleware import identity, optional_identity
from core.errors import bad_request
from core.idempotency import idempotent_create, current_key, cache_response
from core.request_schemas import (
    AchievementCreateRequest,
    AchievementOfflineRequest,
    AchievementUpdateRequest,
    VersionBody,
)
from modules.achievement.service import (
    list_achievements,
    get_achievement_detail,
    list_categories,
    list_industries,
    create_achievement,
    update_achievement,
    submit_achievement,
    offline_achievement,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["achievement"])


@router.get("/achievements", summary="成果列表（仅 published）")
def achievements_list(request: Request, user: dict = Depends(optional_identity)):
    result = list_achievements(request.query_params, user.get("userId"))
    return success(result)


@router.get("/achievements/categories", summary="成果分类字典")
def achievements_categories(user: dict = Depends(optional_identity)):
    result = list_categories()
    return success(result)


@router.get("/achievements/industries", summary="成果产业目录")
def achievements_industries(user: dict = Depends(optional_identity)):
    return success(list_industries())


@router.get("/achievements/{ach_id}", summary="成果详情（防探测：非 published 非 owner 返回 null）")
def achievement_detail(ach_id: int, user: dict = Depends(optional_identity)):
    detail = get_achievement_detail(ach_id, user["userId"])
    if not detail:
        return success(None, "成果不存在或未发布")
    return success(detail)


@router.post("/achievements", status_code=201, summary="创建成果（draft）")
def achievements_create(request: Request, body: AchievementCreateRequest, user: dict = Depends(identity)):
    replay = idempotent_create(request, user)
    if replay is not None:
        return replay
    detail = create_achievement(
        user["userId"], user.get("userNo", ""), body.as_dict(),
        request_id=get_request_id(),
    )
    result = success(detail, "创建成功")
    cache_response(int(user["userId"]), current_key(request), 201, result)
    return result


@router.patch("/achievements/{ach_id}", summary="编辑成果（owner + 乐观锁 + draft/rejected）")
def achievement_update(ach_id: int, body: AchievementUpdateRequest, user: dict = Depends(identity)):
    detail = update_achievement(
        user["userId"], user.get("userNo", ""), ach_id, body.as_dict(),
        request_id=get_request_id(),
    )
    return success(detail)


def _version_body(body: dict):
    version = (body or {}).get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version


@router.post("/achievements/{ach_id}/submit", summary="提交审核（draft/rejected/offline → pending_review）")
def achievement_submit(ach_id: int, body: VersionBody, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = submit_achievement(
        user["userId"], user.get("userNo", ""), ach_id, _version_body(payload),
        request_id=get_request_id(),
    )
    return success(result)


@router.post("/achievements/{ach_id}/offline", summary="下线成果（published → offline）")
def achievement_offline(ach_id: int, body: AchievementOfflineRequest, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = offline_achievement(
        user["userId"], user.get("userNo", ""), ach_id, _version_body(payload),
        reason=payload.get("reason"),
        reason_code=payload.get("reasonCode"),
        request_id=get_request_id(),
    )
    return success(result)
