"""
对接路由 —— /cooperations 意向创建、详情、状态机、事件时间线

Architecture source: openapi.yaml paths /cooperations、/cooperations/{id}、
                     /cooperations/{id}/accept|reject|confirm|cancel|complete|events；06-api-design.md §8
"""
from flask import Blueprint, request, g

from core.response import success
from core.errors import bad_request
from core.middleware import auth_required
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

bp = Blueprint("cooperation", __name__, url_prefix="/api/tech-transfer/v1")


@bp.post("/cooperations")
@auth_required
def cooperations_create():
    user = g.identity
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[cooperation] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    body = request.get_json(silent=True)
    detail = create_intent(
        user["userId"], user.get("userNo", ""), body,
        request_id=g.get("request_id"),
    )
    return success(detail, "意向已创建"), 201


@bp.get("/cooperations/<int:intent_id>")
@auth_required
def cooperation_detail(intent_id: int):
    user_id = g.identity["userId"]
    return success(get_intent_detail(intent_id, user_id))


def _version_body():
    body = request.get_json(silent=True) or {}
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version, body


@bp.post("/cooperations/<int:intent_id>/accept")
@auth_required
def cooperation_accept(intent_id: int):
    user = g.identity
    version, _ = _version_body()
    return success(accept_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        request_id=g.get("request_id"),
    ))


@bp.post("/cooperations/<int:intent_id>/reject")
@auth_required
def cooperation_reject(intent_id: int):
    user = g.identity
    version, body = _version_body()
    return success(reject_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        reason=body.get("reason"),
        request_id=g.get("request_id"),
    ))


@bp.post("/cooperations/<int:intent_id>/confirm")
@auth_required
def cooperation_confirm(intent_id: int):
    user = g.identity
    version, _ = _version_body()
    return success(confirm_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        request_id=g.get("request_id"),
    ))


@bp.post("/cooperations/<int:intent_id>/cancel")
@auth_required
def cooperation_cancel(intent_id: int):
    user = g.identity
    version, body = _version_body()
    return success(cancel_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        reason=body.get("reason"),
        request_id=g.get("request_id"),
    ))


@bp.post("/cooperations/<int:intent_id>/complete")
@auth_required
def cooperation_complete(intent_id: int):
    user = g.identity
    version, body = _version_body()
    return success(complete_intent(
        user["userId"], user.get("userNo", ""), intent_id, version,
        remark=body.get("remark"),
        request_id=g.get("request_id"),
    ))


@bp.get("/cooperations/<int:intent_id>/events")
@auth_required
def cooperation_events(intent_id: int):
    user_id = g.identity["userId"]
    return success(list_events(intent_id, user_id, request.args))
