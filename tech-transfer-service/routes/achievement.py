"""
成果路由 —— GET /achievements（列表/详情/分类/搜索）+ 用户写接口（P0-5）

Architecture source: openapi.yaml paths /achievements, /achievements/{id},
                     /achievements/{id}/submit|offline；06-api-design.md §7、§5.1
"""
from fastapi import APIRouter, Depends, Request

from core.response import success, get_request_id
from core.middleware import identity, json_body
from core.errors import bad_request
from modules.achievement.service import (
    list_achievements,
    get_achievement_detail,
    list_categories,
    create_achievement,
    update_achievement,
    submit_achievement,
    offline_achievement,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["achievement"])


@router.get("/achievements", summary="成果列表（仅 published）")
def achievements_list(request: Request, user: dict = Depends(identity)):
    result = list_achievements(request.query_params)
    return success(result)


@router.get("/achievements/categories", summary="成果分类字典")
def achievements_categories(user: dict = Depends(identity)):
    result = list_categories()
    return success(result)


@router.get("/achievements/{ach_id}", summary="成果详情（防探测：非 published 非 owner 返回 null）")
def achievement_detail(ach_id: int, user: dict = Depends(identity)):
    detail = get_achievement_detail(ach_id)
    if not detail:
        return success(None, "成果不存在或未发布")
    return success(detail)


@router.post("/achievements", status_code=201, summary="创建成果（draft）")
def achievements_create(request: Request, user: dict = Depends(identity), body: dict = Depends(json_body)):
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[achievement] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    detail = create_achievement(
        user["userId"], user.get("userNo", ""), body,
        request_id=get_request_id(),
    )
    return success(detail, "创建成功")


@router.patch("/achievements/{ach_id}", summary="编辑成果（owner + 乐观锁 + draft/rejected）")
def achievement_update(ach_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    detail = update_achievement(
        user["userId"], user.get("userNo", ""), ach_id, body,
        request_id=get_request_id(),
    )
    return success(detail)


def _version_body(body: dict):
    version = (body or {}).get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version


@router.post("/achievements/{ach_id}/submit", summary="提交审核（draft/rejected → pending_review）")
def achievement_submit(ach_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    result = submit_achievement(
        user["userId"], user.get("userNo", ""), ach_id, _version_body(body),
        request_id=get_request_id(),
    )
    return success(result)


@router.post("/achievements/{ach_id}/offline", summary="下线成果（published → offline）")
def achievement_offline(ach_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    result = offline_achievement(
        user["userId"], user.get("userNo", ""), ach_id, _version_body(body),
        reason=(body or {}).get("reason"),
        request_id=get_request_id(),
    )
    return success(result)


@router.get("/search", summary="统一搜索（type=achievement）")
def search(request: Request, user: dict = Depends(identity)):
    search_type = (request.query_params.get("type") or "").strip()
    if search_type != "achievement":
        return success({"total": 0, "list": [], "page": 1, "pageSize": 10, "totalPages": 0})
    result = list_achievements(request.query_params)
    return success(result)
