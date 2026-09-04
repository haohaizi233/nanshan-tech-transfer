"""
admin 运营路由（Release Closure）—— Dashboard / Institution / Cooperation(只读) / Users(只读)

与 routes/admin.py（审核组，已冻结）分文件注册，互不影响；
鉴权同一 admin_identity（登录 + user_role 实时查库）。

Institution Create/Update 使用 Pydantic Schema（§21）；
其余为 GET 查询参数。写操作：service 层同事务写审计（§16）。
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.middleware import admin_identity
from core.response import success, get_request_id
from modules.admin.schemas import InstitutionCreateRequest, InstitutionUpdateRequest
from modules.admin.service import (
    dashboard_summary,
    list_institutions_admin,
    get_institution_admin,
    create_institution,
    update_institution,
    set_institution_status,
    list_cooperations_admin,
    get_cooperation_admin,
    list_users_admin,
    get_user_admin,
)

router = APIRouter(prefix="/api/tech-transfer/v1")


# ── admin-dashboard ──────────────────────────────────────────

@router.get("/admin/dashboard/summary", tags=["admin-dashboard"])
def admin_dashboard_summary(admin: dict = Depends(admin_identity)):
    return success(dashboard_summary())


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
def admin_cooperations_list(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_cooperations_admin(request.query_params))


@router.get("/admin/cooperations/{intent_id}", tags=["admin-cooperations"])
def admin_cooperations_detail(intent_id: int, admin: dict = Depends(admin_identity)):
    return success(get_cooperation_admin(intent_id))


# ── admin-users（READ ONLY，禁用/启用为 P1） ─────────────────

@router.get("/admin/users", tags=["admin-users"])
def admin_users_list(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_users_admin(request.query_params))


@router.get("/admin/users/{user_id}", tags=["admin-users"])
def admin_users_detail(user_id: int, admin: dict = Depends(admin_identity)):
    return success(get_user_admin(user_id))
