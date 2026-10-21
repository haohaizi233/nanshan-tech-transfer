"""
发布者侧变更对比路由 —— 管理员修改需求/成果后，发布者可见字段级变更

交互（手机端）：
- 详情页顶部提示条「管理员修改了 N 处内容」
- 点击展开字段级对比卡片（字段名 + 修改前 + 修改后；新增绿色 / 修改黄色）
- 展开即标记已读

GET  /demands/{id}/admin-changes       发布者拉取变更（未读数 + 对比明细）
POST /demands/{id}/admin-changes/read  标记已读
GET  /achievements/{id}/admin-changes
POST /achievements/{id}/admin-changes/read

权限：仅内容归属人（发布者）与平台管理员（403 TT_COMMON_40301）。
"""
from fastapi import APIRouter, Depends

from core.middleware import identity
from core.response import success
from modules.admin.edit_log import list_admin_changes, mark_admin_changes_read

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["admin-changes"])


@router.get("/demands/{demand_id}/admin-changes")
def demand_admin_changes(demand_id: int, user: dict = Depends(identity)):
    return success(list_admin_changes("demand", demand_id, user))


@router.post("/demands/{demand_id}/admin-changes/read")
def demand_admin_changes_read(demand_id: int, user: dict = Depends(identity)):
    return success(mark_admin_changes_read("demand", demand_id, user), "已标记为已读")


@router.get("/achievements/{ach_id}/admin-changes")
def achievement_admin_changes(ach_id: int, user: dict = Depends(identity)):
    return success(list_admin_changes("achievement", ach_id, user))


@router.post("/achievements/{ach_id}/admin-changes/read")
def achievement_admin_changes_read(ach_id: int, user: dict = Depends(identity)):
    return success(mark_admin_changes_read("achievement", ach_id, user), "已标记为已读")
