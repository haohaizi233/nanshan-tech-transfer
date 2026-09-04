"""
admin 路由 —— 管理审核组（06-api-design.md §15）

统一：需登录 + user_role 实时校验 admin 角色（非 admin 403 TT_ADMIN_40301）；
写操作幂等由状态机校验保证（重复审核 409），不要求 X-Idempotency-Key；全部记审计。
"""
from fastapi import APIRouter, Depends, Request

from core.response import success, get_request_id
from core.middleware import admin_identity, json_body
from modules.admin.service import (
    achievements_review_queue,
    demands_review_queue,
    review_achievement,
    review_demand,
    list_audit_logs,
    list_achievements_admin,
    get_achievement_admin,
    list_demands_admin,
    get_demand_admin,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["admin"])


@router.get("/admin/achievements")
def admin_achievements_list(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_achievements_admin(request.query_params))


@router.get("/admin/achievements/review-queue")
def admin_ach_queue(request: Request, admin: dict = Depends(admin_identity)):
    return success(achievements_review_queue(request.query_params))


@router.get("/admin/achievements/{ach_id}")
def admin_achievement_detail(ach_id: int, admin: dict = Depends(admin_identity)):
    return success(get_achievement_admin(ach_id))


@router.post("/admin/achievements/{ach_id}/approve")
def admin_ach_approve(ach_id: int, body: dict = Depends(json_body), admin: dict = Depends(admin_identity)):
    body = dict(body)
    body["_action"] = "approve"
    return success(review_achievement(admin, ach_id, body, request_id=get_request_id()))


@router.post("/admin/achievements/{ach_id}/reject")
def admin_ach_reject(ach_id: int, body: dict = Depends(json_body), admin: dict = Depends(admin_identity)):
    body = dict(body)
    body["_action"] = "reject"
    return success(review_achievement(admin, ach_id, body, request_id=get_request_id()))


@router.get("/admin/demands")
def admin_demands_list(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_demands_admin(request.query_params))


@router.get("/admin/demands/review-queue")
def admin_dmd_queue(request: Request, admin: dict = Depends(admin_identity)):
    return success(demands_review_queue(request.query_params))


@router.get("/admin/demands/{demand_id}")
def admin_demand_detail(demand_id: int, admin: dict = Depends(admin_identity)):
    return success(get_demand_admin(demand_id))


@router.post("/admin/demands/{demand_id}/approve")
def admin_dmd_approve(demand_id: int, body: dict = Depends(json_body), admin: dict = Depends(admin_identity)):
    body = dict(body)
    body["_action"] = "approve"
    return success(review_demand(admin, demand_id, body, request_id=get_request_id()))


@router.post("/admin/demands/{demand_id}/reject")
def admin_dmd_reject(demand_id: int, body: dict = Depends(json_body), admin: dict = Depends(admin_identity)):
    body = dict(body)
    body["_action"] = "reject"
    return success(review_demand(admin, demand_id, body, request_id=get_request_id()))


@router.get("/admin/audit-logs")
def admin_audit_logs(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_audit_logs(request.query_params))
