"""
对接路由 —— /cooperations 意向创建、详情、状态机、事件时间线

Architecture source: openapi.yaml paths /cooperations、/cooperations/{id}、
                     /cooperations/{id}/accept|reject|confirm|cancel|complete|events；06-api-design.md §8
"""
from fastapi import APIRouter, Depends, Request

from core.response import success, get_request_id
from core.middleware import identity, json_body
from core.errors import bad_request
from modules.cooperation.service import (
    create_intent,
    get_intent_detail,
    accept_intent,
    reject_intent,
    confirm_intent,
    cancel_intent,
    complete_intent,
    list_events,
)

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["cooperation"])


@router.post("/cooperations", status_code=201)
def cooperations_create(request: Request, user: dict = Depends(identity), body: dict = Depends(json_body)):
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[cooperation] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    detail = create_intent(
        user["userId"], user.get("userNo", ""), body,
        request_id=get_request_id(),
    )
    return success(detail, "意向已创建")


@router.get("/cooperations/{intent_id}")
def cooperation_detail(intent_id: int, user: dict = Depends(identity)):
    return success(get_intent_detail(intent_id, user["userId"]))


def _version_body(body: dict):
    body = body or {}
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version, body


@router.post("/cooperations/{intent_id}/accept")
def cooperation_accept(intent_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    version, _ = _version_body(body)
    return success(accept_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        request_id=get_request_id(),
    ))


@router.post("/cooperations/{intent_id}/reject")
def cooperation_reject(intent_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    version, body = _version_body(body)
    return success(reject_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        reason=body.get("reason"),
        request_id=get_request_id(),
    ))


@router.post("/cooperations/{intent_id}/confirm")
def cooperation_confirm(intent_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    version, _ = _version_body(body)
    return success(confirm_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        request_id=get_request_id(),
    ))


@router.post("/cooperations/{intent_id}/cancel")
def cooperation_cancel(intent_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    version, body = _version_body(body)
    return success(cancel_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        reason=body.get("reason"),
        request_id=get_request_id(),
    ))


@router.post("/cooperations/{intent_id}/complete")
def cooperation_complete(intent_id: int, user: dict = Depends(identity), body: dict = Depends(json_body)):
    version, body = _version_body(body)
    return success(complete_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        remark=body.get("remark"), outcome=body.get("outcome"),
        request_id=get_request_id(),
    ))


@router.get("/cooperations/{intent_id}/events")
def cooperation_events(intent_id: int, request: Request, user: dict = Depends(identity)):
    return success(list_events(intent_id, user["userId"], request.query_params))
