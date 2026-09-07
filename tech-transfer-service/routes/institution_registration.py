"""机构注册申请路由 —— 公开提交（管理端审核接口在 routes/admin_ops.py）。"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse

from core.middleware import json_body
from core.response import success, get_request_id
from modules.institution_registration.service import create_institution_registration

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["institution-registrations"])


@router.post("/institution-registrations", status_code=201)
def submit_institution_registration(body: dict = Depends(json_body)):
    data = create_institution_registration(body, request_id=get_request_id())
    return JSONResponse(
        status_code=201,
        content=success(data, "机构注册申请已提交，请等待平台审核"),
    )
