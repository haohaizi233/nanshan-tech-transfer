"""
admin 运营路由（Release Closure）—— Dashboard / Institution / Cooperation(只读) / Users(只读)

与 routes/admin.py（审核组，已冻结）分文件注册，互不影响；
平台运营接口走 admin_identity；后台角标走 backend_identity（机构管理员可按本机构范围读取）。

Institution Create/Update 使用 Pydantic Schema（§21）；
其余为 GET 查询参数。写操作：service 层同事务写审计（§16）。
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.middleware import admin_identity, backend_identity
from core.request_schemas import (
    AssistStatusRequest,
    AssistTransitionRequest,
    InstitutionImportRequest,
    InstitutionRejectRequest,
    ReviewRejectRequest,
    VersionBody,
)
from core.response import get_request_id, success
from modules.admin.schemas import InstitutionCreateRequest, InstitutionUpdateRequest
from modules.admin.service import (
    admin_review_cooperation,
    create_institution,
    dashboard_summary,
    dashboard_todos,
    dashboard_trend,
    delete_institution,
    get_cooperation_admin,
    get_institution_admin,
    get_user_admin,
    import_institutions,
    list_cooperations_admin,
    list_institutions_admin,
    list_users_admin,
    notification_summary,
    set_institution_status,
    update_institution,
)
from modules.cooperation.service import (
    admin_assist_transition,
    update_assist_status,
)
from modules.institution_registration.service import (
    approve_institution_registration,
    list_institution_registrations,
    reject_institution_registration,
)

router = APIRouter(prefix="/api/tech-transfer/v1")


# ── admin-dashboard ──────────────────────────────────────────

@router.get("/admin/dashboard/summary", tags=["admin-dashboard"])
def admin_dashboard_summary(admin: dict = Depends(admin_identity)):
    return success(dashboard_summary())


@router.get("/admin/notifications/summary", tags=["admin-dashboard"])
def admin_notification_summary(scope: dict = Depends(backend_identity)):
    return success(notification_summary(scope))


@router.get("/admin/dashboard/todos", tags=["admin-dashboard"])
def admin_dashboard_todos(request: Request, admin: dict = Depends(admin_identity)):
    return success(dashboard_todos(request.query_params.get("limit") or 20))


@router.get("/admin/dashboard/trend", tags=["admin-dashboard"])
def admin_dashboard_trend(request: Request, admin: dict = Depends(admin_identity)):
    return success(dashboard_trend(request.query_params.get("days")))


# ── 机构注册审核 ─────────────────────────────────────────────

@router.get("/admin/institution-registrations", tags=["admin-institution-registrations"])
def admin_institution_registrations_list(
    request: Request,
    admin: dict = Depends(admin_identity),
):
    return success(list_institution_registrations(request.query_params))


@router.post(
    "/admin/institution-registrations/{institution_id}/approve",
    tags=["admin-institution-registrations"],
)
def admin_institution_registration_approve(
    institution_id: int,
    admin: dict = Depends(admin_identity),
):
    result = approve_institution_registration(
        admin,
        institution_id,
        request_id=get_request_id(),
    )
    return success(result, "机构注册申请已通过")


@router.post(
    "/admin/institution-registrations/{institution_id}/reject",
    tags=["admin-institution-registrations"],
)
def admin_institution_registration_reject(
    institution_id: int,
    body: InstitutionRejectRequest,
    admin: dict = Depends(admin_identity),
):
    result = reject_institution_registration(
        admin,
        institution_id,
        body.as_dict().get("reason"),
        request_id=get_request_id(),
    )
    return success(result, "机构注册申请已驳回")


# ── admin-institutions ───────────────────────────────────────

@router.get("/admin/institutions", tags=["admin-institutions"])
def admin_institutions_list(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_institutions_admin(request.query_params))


@router.post("/admin/institutions", status_code=201, tags=["admin-institutions"])
def admin_institutions_create(
    body: InstitutionCreateRequest,
    admin: dict = Depends(admin_identity),
):
    data = create_institution(admin, body.model_dump(exclude_unset=True), request_id=get_request_id())
    return JSONResponse(status_code=201, content=success(data))


# 静态段（import）必须在 {institution_id} 之前注册，避免被动态 catch-all 吞掉。
@router.post("/admin/institutions/import", tags=["admin-institutions"])
def admin_institutions_import(
    body: InstitutionImportRequest,
    admin: dict = Depends(admin_identity),
):
    data = import_institutions(admin, body.as_dict(), request_id=get_request_id())
    return success(data, f"导入完成：新增 {data['created']}，更新 {data['updated']}")


@router.get("/admin/institutions/{institution_id}", tags=["admin-institutions"])
def admin_institutions_detail(institution_id: int, admin: dict = Depends(admin_identity)):
    return success(get_institution_admin(institution_id))


@router.patch("/admin/institutions/{institution_id}", tags=["admin-institutions"])
def admin_institutions_update(
    institution_id: int,
    body: InstitutionUpdateRequest,
    admin: dict = Depends(admin_identity),
):
    data = update_institution(
        admin, institution_id, body.model_dump(exclude_unset=True), request_id=get_request_id(),
    )
    return success(data)


@router.delete("/admin/institutions/{institution_id}", tags=["admin-institutions"])
def admin_institutions_delete(institution_id: int, admin: dict = Depends(admin_identity)):
    data = delete_institution(admin, institution_id, request_id=get_request_id())
    return success(data, "机构已删除")


@router.post("/admin/institutions/{institution_id}/online", tags=["admin-institutions"])
def admin_institutions_online(institution_id: int, admin: dict = Depends(admin_identity)):
    return success(set_institution_status(admin, institution_id, "online", request_id=get_request_id()))


@router.post("/admin/institutions/{institution_id}/offline", tags=["admin-institutions"])
def admin_institutions_offline(institution_id: int, admin: dict = Depends(admin_identity)):
    return success(set_institution_status(admin, institution_id, "offline", request_id=get_request_id()))


# ── admin-cooperations（只读 + 平台协助运营操作） ─────────────

@router.get("/admin/cooperations", tags=["admin-cooperations"])
def admin_cooperations_list(request: Request, scope: dict = Depends(backend_identity)):
    return success(list_cooperations_admin(request.query_params, scope))


@router.get("/admin/cooperations/{intent_id}", tags=["admin-cooperations"])
def admin_cooperations_detail(intent_id: int, scope: dict = Depends(backend_identity)):
    return success(get_cooperation_admin(intent_id, scope))

@router.post("/admin/cooperations/{intent_id}/accept", tags=["admin-cooperations"])
def admin_cooperations_accept(
    intent_id: int,
    body: VersionBody,
    scope: dict = Depends(backend_identity),
):
    result = admin_review_cooperation(
        scope,
        intent_id,
        body.as_dict(),
        action="accept",
        request_id=get_request_id(),
    )
    return success(result, "对接申请已接受")


@router.post("/admin/cooperations/{intent_id}/reject", tags=["admin-cooperations"])
def admin_cooperations_reject(
    intent_id: int,
    body: ReviewRejectRequest,
    scope: dict = Depends(backend_identity),
):
    result = admin_review_cooperation(
        scope,
        intent_id,
        body.as_dict(),
        action="reject",
        request_id=get_request_id(),
    )
    return success(result, "对接申请已驳回")

@router.post("/admin/cooperations/{intent_id}/assist-status", tags=["admin-cooperations"])
def admin_cooperation_assist_status(
    intent_id: int,
    body: AssistStatusRequest,
    admin: dict = Depends(admin_identity),
):
    """平台协助处理阶段流转（queued/contacting/waiting_reply/target_agreed/...）。"""
    return success(update_assist_status(admin, intent_id, body.as_dict(), request_id=get_request_id()))


@router.post("/admin/cooperations/{intent_id}/assist-transition", tags=["admin-cooperations"])
def admin_cooperation_assist_transition(
    intent_id: int,
    body: AssistTransitionRequest,
    admin: dict = Depends(admin_identity),
):
    """平台代目标机构操作状态机（accept 强制前置 assist_status=target_agreed）。"""
    return success(admin_assist_transition(admin, intent_id, body.as_dict(), request_id=get_request_id()))


# ── admin-users（READ ONLY，禁用/启用为 P1） ─────────────────
# E2: 当前 admin-users 仅支持只读操作；未来若扩展禁用/启用用户写操作，
# 必须同步接入 auth_cache.invalidate_user(user_id) 使缓存即时失效。

@router.get("/admin/users", tags=["admin-users"])
def admin_users_list(request: Request, scope: dict = Depends(backend_identity)):
    return success(list_users_admin(request.query_params, scope))


@router.get("/admin/users/{user_id}", tags=["admin-users"])
def admin_users_detail(user_id: int, scope: dict = Depends(backend_identity)):
    return success(get_user_admin(user_id, scope))
