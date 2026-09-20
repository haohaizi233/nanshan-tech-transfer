"""
需求路由 —— /demands CRUD + 状态机

Architecture source: openapi.yaml paths /demands, /demands/{id},
                     /demands/{id}/submit|cancel|close；06-api-design.md §8
"""
from fastapi import APIRouter, Depends, Request

from core.response import success, get_request_id
from core.middleware import identity, optional_identity
from core.errors import bad_request
from core.request_schemas import (
    DemandCreateRequest,
    DemandUpdateRequest,
    ReasonVersionBody,
    VersionBody,
)
from modules.demand.service import (
    list_demands,
    get_demand_detail,
    create_demand,
    update_demand,
    submit_demand,
    cancel_demand,
    close_demand,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["demand"])


@router.get("/demands")
def demands_list(request: Request, user: dict = Depends(optional_identity)):
    return success(list_demands(request.query_params, user["userId"]))


@router.post("/demands", status_code=201)
def demands_create(request: Request, body: DemandCreateRequest, user: dict = Depends(identity)):
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[demand] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    detail = create_demand(
        user["userId"], user.get("userNo", ""), body.as_dict(),
        request_id=get_request_id(),
    )
    return success(detail, "创建成功")


@router.get("/demands/{demand_id}")
def demand_detail(demand_id: int, user: dict = Depends(optional_identity)):
    return success(get_demand_detail(demand_id, user["userId"]))


@router.patch("/demands/{demand_id}")
def demand_update(demand_id: int, body: DemandUpdateRequest, user: dict = Depends(identity)):
    detail = update_demand(
        user["userId"], user.get("userNo", ""), demand_id, body.as_dict(),
        request_id=get_request_id(),
    )
    return success(detail)


def _version_body(body: dict):
    version = (body or {}).get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version


@router.post("/demands/{demand_id}/submit")
def demand_submit(demand_id: int, body: VersionBody, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = submit_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(payload),
        request_id=get_request_id(),
    )
    return success(result)


@router.post("/demands/{demand_id}/cancel")
def demand_cancel(demand_id: int, body: ReasonVersionBody, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = cancel_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(payload), payload.get("reasonCode"), payload.get("reasonNote"),
        request_id=get_request_id(),
    )
    return success(result)


@router.post("/demands/{demand_id}/close")
def demand_close(demand_id: int, body: ReasonVersionBody, user: dict = Depends(identity)):
    payload = body.as_dict()
    result = close_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(payload), payload.get("reasonCode"), payload.get("reasonNote"),
        request_id=get_request_id(),
    )
    return success(result)
