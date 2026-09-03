"""
需求路由 —— /demands CRUD + 状态机

Architecture source: openapi.yaml paths /demands, /demands/{id},
                     /demands/{id}/submit|cancel|close；06-api-design.md §8
"""
from flask import Blueprint, request, g

from core.response import success
from core.errors import bad_request
from core.middleware import auth_required
from modules.demand.service import (
    list_demands,
    get_demand_detail,
    create_demand,
    update_demand,
    submit_demand,
    cancel_demand,
    close_demand,
)

bp = Blueprint("demand", __name__, url_prefix="/api/tech-transfer/v1")


@bp.get("/demands")
@auth_required
def demands_list():
    user_id = g.identity["userId"]
    return success(list_demands(request.args, user_id))


@bp.post("/demands")
@auth_required
def demands_create():
    user = g.identity
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[demand] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    body = request.get_json(silent=True)
    detail = create_demand(
        user["userId"], user.get("userNo", ""), body,
        request_id=g.get("request_id"),
    )
    return success(detail, "创建成功"), 201


@bp.get("/demands/<int:demand_id>")
@auth_required
def demand_detail(demand_id: int):
    user_id = g.identity["userId"]
    return success(get_demand_detail(demand_id, user_id))


@bp.patch("/demands/<int:demand_id>")
@auth_required
def demand_update(demand_id: int):
    user = g.identity
    body = request.get_json(silent=True)
    detail = update_demand(
        user["userId"], user.get("userNo", ""), demand_id, body,
        request_id=g.get("request_id"),
    )
    return success(detail)


def _version_body():
    body = request.get_json(silent=True) or {}
    version = body.get("version")
    if version is None:
        raise bad_request("必须携带 version（乐观锁）")
    return version


@bp.post("/demands/<int:demand_id>/submit")
@auth_required
def demand_submit(demand_id: int):
    user = g.identity
    result = submit_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(),
        request_id=g.get("request_id"),
    )
    return success(result)


@bp.post("/demands/<int:demand_id>/cancel")
@auth_required
def demand_cancel(demand_id: int):
    user = g.identity
    result = cancel_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(),
        request_id=g.get("request_id"),
    )
    return success(result)


@bp.post("/demands/<int:demand_id>/close")
@auth_required
def demand_close(demand_id: int):
    user = g.identity
    result = close_demand(
        user["userId"], user.get("userNo", ""), demand_id, _version_body(),
        request_id=g.get("request_id"),
    )
    return success(result)
