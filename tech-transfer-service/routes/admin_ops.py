"""
admin 运营路由（Release Closure）—— Dashboard / Institution / Cooperation(只读) / Users(只读)

与 routes/admin.py（审核组，已冻结）分文件注册，互不影响；
鉴权同一 admin_identity（登录 + user_role 实时查库）。

Institution Create/Update 使用 Pydantic Schema（§21）；
其余为 GET 查询参数。写操作：service 层同事务写审计（§16）。
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.middleware import admin_identity, backend_identity, json_body
from core.response import success, get_request_id
from modules.admin.schemas import InstitutionCreateRequest, InstitutionUpdateRequest
from modules.admin.service import (
    dashboard_summary,
    dashboard_trend,
    list_institutions_admin,
    get_institution_admin,
    create_institution,
    update_institution,
    set_institution_status,
    list_cooperations_admin,
    get_cooperation_admin,
    admin_review_cooperation,
    list_users_admin,
    get_user_admin,
)
from modules.institution_registration.service import (
    list_institution_registrations,
    approve_institution_registration,
    reject_institution_registration,
)

router = APIRouter(prefix="/api/tech-transfer/v1")


# ── admin-dashboard ──────────────────────────────────────────

@router.get("/admin/dashboard/summary", tags=["admin-dashboard"])
def admin_dashboard_summary(admin: dict = Depends(admin_identity)):
    return success(dashboard_summary())


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
    body: dict = Depends(json_body),
    admin: dict = Depends(admin_identity),
):
    result = reject_institution_registration(
        admin,
        institution_id,
        body.get("reason"),
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


@router.post("/admin/institutions/{institution_id}/online", tags=["admin-institutions"])
def admin_institutions_online(institution_id: int, admin: dict = Depends(admin_identity)):
    return success(set_institution_status(admin, institution_id, "online", request_id=get_request_id()))


@router.post("/admin/institutions/{institution_id}/offline", tags=["admin-institutions"])
def admin_institutions_offline(institution_id: int, admin: dict = Depends(admin_identity)):
    return success(set_institution_status(admin, institution_id, "offline", request_id=get_request_id()))


# ── admin-cooperations（READ ONLY，状态机不开放给 Admin） ────

@router.get("/admin/cooperations", tags=["admin-cooperations"])
def admin_cooperations_list(request: Request, scope: dict = Depends(backend_identity)):
    return success(list_cooperations_admin(request.query_params, scope))


@router.get("/admin/cooperations/{intent_id}", tags=["admin-cooperations"])
def admin_cooperations_detail(intent_id: int, scope: dict = Depends(backend_identity)):
    return success(get_cooperation_admin(intent_id, scope))

@router.post("/admin/cooperations/{intent_id}/accept", tags=["admin-cooperations"])
def admin_cooperations_accept(
    intent_id: int,
    body: dict = Depends(json_body),
    scope: dict = Depends(backend_identity),
):
    result = admin_review_cooperation(
        scope,
        intent_id,
        body,
        action="accept",
        request_id=get_request_id(),
    )
    return success(result, "对接申请已接受")


@router.post("/admin/cooperations/{intent_id}/reject", tags=["admin-cooperations"])
def admin_cooperations_reject(
    intent_id: int,
    body: dict = Depends(json_body),
    scope: dict = Depends(backend_identity),
):
    result = admin_review_cooperation(
        scope,
        intent_id,
        body,
        action="reject",
        request_id=get_request_id(),
    )
    return success(result, "对接申请已驳回")

# ── admin-users（READ ONLY，禁用/启用为 P1） ─────────────────

@router.get("/admin/users", tags=["admin-users"])
def admin_users_list(request: Request, scope: dict = Depends(backend_identity)):
    return success(list_users_admin(request.query_params, scope))


@router.get("/admin/users/{user_id}", tags=["admin-users"])
def admin_users_detail(user_id: int, scope: dict = Depends(backend_identity)):
    return success(get_user_admin(user_id, scope))
