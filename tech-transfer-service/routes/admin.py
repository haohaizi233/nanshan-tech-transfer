"""
admin 路由 —— 管理审核组（06-api-design.md §15）

统一：需登录 + user_role 实时校验 admin 角色（非 admin 403 TT_ADMIN_40301）；
写操作幂等由状态机校验保证（重复审核 409），不要求 X-Idempotency-Key；全部记审计。
"""
from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from core.middleware import admin_identity, backend_identity
from core.request_schemas import (
    AchievementCreateRequest,
    AchievementUpdateRequest,
    AchievementWriteRequest,
    DemandCreateRequest,
    DemandUpdateRequest,
    ReviewRejectRequest,
    VersionBody,
)
from core.response import get_request_id, success
from modules.achievement.importer import (
    clear_import_batches,
    confirm_import_item,
    get_import_batch,
    list_import_batches,
    publish_import_item,
    stage_uploaded_documents,
)
from modules.admin.service import (
    achievements_review_queue,
    claim_unassigned_content,
    close_demand_admin,
    create_achievement_admin,
    create_demand_admin,
    demands_review_queue,
    get_achievement_admin,
    get_demand_admin,
    list_achievements_admin,
    list_audit_logs,
    list_content_organizations_admin,
    list_demand_categories_admin,
    list_demands_admin,
    offline_achievement_admin,
    review_achievement,
    review_demand,
    soft_delete_achievement_admin,
    soft_delete_demand_admin,
    submit_achievement_admin,
    submit_demand_admin,
    update_achievement_admin,
    update_demand_admin,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["admin"])


@router.get("/admin/achievement-imports")
def admin_achievement_imports(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_import_batches(request.query_params.get("page", 1), request.query_params.get("pageSize", 20)))


@router.post("/admin/achievement-imports")
async def admin_achievement_import_upload(
    files: list[UploadFile] = File(...),
    sourceOrg: str = Form(""),
    admin: dict = Depends(admin_identity),
):
    """管理员上传 PPTX/PDF，解析后写入导入暂存，不自动发布。"""
    uploads = []
    for item in files:
        uploads.append((item.filename or "upload.pptx", await item.read()))
        await item.close()
    created_by = int(admin.get("userId") or admin.get("id") or 0)
    if not created_by:
        from core.errors import bad_request
        raise bad_request("无法识别导入人")
    return success(
        stage_uploaded_documents(uploads, created_by, (sourceOrg or "").strip() or None),
        "导入暂存已创建",
    )


# 静态段（clear）必须在 {batch_id} 之前注册，避免被动态 catch-all 吞掉。
@router.post("/admin/achievement-imports/clear")
def admin_achievement_import_clear(admin: dict = Depends(admin_identity)):
    """清空全部导入暂存批次；已入库为草稿的成果不受影响。"""
    return success(clear_import_batches(admin), "导入暂存已清空")


@router.get("/admin/achievement-imports/{batch_id}")
def admin_achievement_import_detail(batch_id: int, admin: dict = Depends(admin_identity)):
    data = get_import_batch(batch_id)
    if data is None:
        from core.errors import not_found
        raise not_found("导入批次不存在")
    return success(data)


@router.post("/admin/achievement-imports/{batch_id}/items/{item_id}/confirm")
def admin_achievement_import_confirm(
    batch_id: int,
    item_id: int,
    body: AchievementWriteRequest,
    admin: dict = Depends(admin_identity),
):
    """管理员确认一条暂存导入记录；仅落为 draft，仍需正常审核发布。"""
    return success(confirm_import_item(batch_id, item_id, admin, body.as_dict(), get_request_id()), "成果已入库为草稿")


@router.post("/admin/achievement-imports/{batch_id}/items/{item_id}/publish")
def admin_achievement_import_publish(
    batch_id: int,
    item_id: int,
    body: AchievementWriteRequest,
    admin: dict = Depends(admin_identity),
):
    """管理员一键发布暂存导入记录：确认入库 → 提交审核 → 审核通过。"""
    return success(publish_import_item(batch_id, item_id, admin, body.as_dict(), get_request_id()), "成果已发布")


@router.get("/admin/demand-categories")
def admin_demand_categories(scope: dict = Depends(backend_identity)):
    return success(list_demand_categories_admin())


@router.get("/admin/content-organizations")
def admin_content_organizations(scope: dict = Depends(backend_identity)):
    return success(list_content_organizations_admin(scope))


@router.get("/admin/achievements")
def admin_achievements_list(
    request: Request,
    scope: dict = Depends(backend_identity),
):
    return success(list_achievements_admin(request.query_params, scope))

@router.post("/admin/achievements", status_code=201)
def admin_achievement_create(
    body: AchievementCreateRequest,
    admin: dict = Depends(backend_identity),
):
    result = create_achievement_admin(
        admin,
        body.as_dict(),
        request_id=get_request_id(),
    )
    return success(result, "成果创建成功")

@router.get("/admin/achievements/review-queue")
def admin_ach_queue(request: Request, admin: dict = Depends(admin_identity)):
    return success(achievements_review_queue(request.query_params))


@router.get("/admin/achievements/{ach_id}")
def admin_achievement_detail(
    ach_id: int,
    scope: dict = Depends(backend_identity),
):
    return success(get_achievement_admin(ach_id, scope))


@router.patch("/admin/achievements/{ach_id}")
def admin_achievement_update(
    ach_id: int,
    body: AchievementUpdateRequest,
    admin: dict = Depends(backend_identity),
):
    result = update_achievement_admin(
        admin,
        ach_id,
        body.as_dict(),
        request_id=get_request_id(),
    )
    return success(result, "成果更新成功")


@router.post("/admin/achievements/{ach_id}/claim-organization")
def admin_achievement_claim_organization(
    ach_id: int,
    body: VersionBody,
    scope: dict = Depends(backend_identity),
):
    return success(
        claim_unassigned_content(scope, "achievement", ach_id, body.as_dict().get("version"), get_request_id()),
        "已归属到当前机构",
    )


@router.post("/admin/achievements/{ach_id}/submit")
def admin_achievement_submit(
    ach_id: int,
    body: VersionBody,
    admin: dict = Depends(admin_identity),
):
    """代平台代录成果提交审核（仅 owner NULL 的内容）。"""
    return success(
        submit_achievement_admin(admin, ach_id, body.as_dict(), request_id=get_request_id()),
        "已提交审核",
    )


@router.post("/admin/achievements/{ach_id}/approve")
def admin_ach_approve(ach_id: int, body: VersionBody, admin: dict = Depends(admin_identity)):
    payload = body.as_dict()
    payload["_action"] = "approve"
    return success(review_achievement(admin, ach_id, payload, request_id=get_request_id()))


@router.post("/admin/achievements/{ach_id}/reject")
def admin_ach_reject(ach_id: int, body: ReviewRejectRequest, admin: dict = Depends(admin_identity)):
    payload = body.as_dict()
    payload["_action"] = "reject"
    return success(review_achievement(admin, ach_id, payload, request_id=get_request_id()))

@router.post("/admin/achievements/{ach_id}/offline", summary="管理员下架已发布成果（published → offline）")
def admin_ach_offline(ach_id: int, body: VersionBody, scope: dict = Depends(backend_identity)):
    return success(
        offline_achievement_admin(scope, ach_id, body.as_dict(), request_id=get_request_id()),
        "成果已下架",
    )


@router.delete("/admin/achievements/{ach_id}", summary="管理员软删除成果（deleted_at=NOW）")
def admin_achievement_delete(
    ach_id: int,
    scope: dict = Depends(backend_identity),
):
    return success(soft_delete_achievement_admin(scope, ach_id, request_id=get_request_id()), "成果已删除")


@router.get("/admin/demands")
def admin_demands_list(
    request: Request,
    scope: dict = Depends(backend_identity),
):
    return success(list_demands_admin(request.query_params, scope))

@router.post("/admin/demands", status_code=201)
def admin_demand_create(
    body: DemandCreateRequest,
    admin: dict = Depends(backend_identity),
):
    result = create_demand_admin(
        admin,
        body.as_dict(),
        request_id=get_request_id(),
    )
    return success(result, "需求创建成功")


@router.get("/admin/demands/review-queue")
def admin_dmd_queue(request: Request, admin: dict = Depends(admin_identity)):
    return success(demands_review_queue(request.query_params))


@router.get("/admin/demands/{demand_id}")
def admin_demand_detail(
    demand_id: int,
    scope: dict = Depends(backend_identity),
):
    return success(get_demand_admin(demand_id, scope))

@router.patch("/admin/demands/{demand_id}")
def admin_demand_update(
    demand_id: int,
    body: DemandUpdateRequest,
    admin: dict = Depends(backend_identity),
):
    result = update_demand_admin(
        admin,
        demand_id,
        body.as_dict(),
        request_id=get_request_id(),
    )
    return success(result, "需求更新成功")


@router.post("/admin/demands/{demand_id}/claim-organization")
def admin_demand_claim_organization(
    demand_id: int,
    body: VersionBody,
    scope: dict = Depends(backend_identity),
):
    return success(
        claim_unassigned_content(scope, "demand", demand_id, body.as_dict().get("version"), get_request_id()),
        "已归属到当前机构",
    )


@router.post("/admin/demands/{demand_id}/submit")
def admin_demand_submit(
    demand_id: int,
    body: VersionBody,
    admin: dict = Depends(admin_identity),
):
    """代平台代录需求提交审核（仅 owner NULL 的内容）。"""
    return success(
        submit_demand_admin(admin, demand_id, body.as_dict(), request_id=get_request_id()),
        "已提交审核",
    )


@router.post("/admin/demands/{demand_id}/approve")
def admin_dmd_approve(demand_id: int, body: VersionBody, admin: dict = Depends(admin_identity)):
    payload = body.as_dict()
    payload["_action"] = "approve"
    return success(review_demand(admin, demand_id, payload, request_id=get_request_id()))


@router.post("/admin/demands/{demand_id}/reject")
def admin_dmd_reject(demand_id: int, body: ReviewRejectRequest, admin: dict = Depends(admin_identity)):
    payload = body.as_dict()
    payload["_action"] = "reject"
    return success(review_demand(admin, demand_id, payload, request_id=get_request_id()))

@router.post("/admin/demands/{demand_id}/close", summary="管理员关闭已发布/对接中的需求")
def admin_dmd_close(demand_id: int, body: VersionBody, scope: dict = Depends(backend_identity)):
    return success(
        close_demand_admin(scope, demand_id, body.as_dict(), request_id=get_request_id()),
        "需求已关闭",
    )


@router.delete("/admin/demands/{demand_id}", summary="管理员软删除需求（deleted_at=NOW）")
def admin_demand_delete(
    demand_id: int,
    scope: dict = Depends(backend_identity),
):
    return success(soft_delete_demand_admin(scope, demand_id, request_id=get_request_id()), "需求已删除")


@router.get("/admin/audit-logs")
def admin_audit_logs(request: Request, admin: dict = Depends(admin_identity)):
    return success(list_audit_logs(request.query_params))
