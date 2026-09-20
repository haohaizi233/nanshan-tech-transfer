"""机构注册申请路由 —— 公开提交（管理端审核接口在 routes/admin_ops.py）。"""

from fastapi.responses import JSONResponse
from fastapi import APIRouter, Request

from core.rate_limit import check_register_rate
from core.request_schemas import InstitutionRegistrationRequest
from core.response import success, get_request_id
from modules.institution_registration.service import create_institution_registration

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["institution-registrations"])


@router.post("/institution-registrations", status_code=201)
def submit_institution_registration(request: Request, body: InstitutionRegistrationRequest):
    # 公开注册端点：与 /auth/register 同样按 IP 限频，防批量账号创建。
    check_register_rate(request)
    data = create_institution_registration(body.as_dict(), request_id=get_request_id())
    return JSONResponse(
        status_code=201,
        content=success(data, "机构注册申请已提交，请等待平台审核"),
    )
