from flask import Blueprint, request, g
from core.response import success
from core.middleware import auth_required
from modules.profile.service import get_my_profile, update_my_profile
from modules.demand.service import list_my_demands

bp = Blueprint("me", __name__, url_prefix="/api/tech-transfer/v1/me")


@bp.get("")
@auth_required
def get_me():
    user_id = g.identity["userId"]
    profile = get_my_profile(user_id)
    return success(profile)


@bp.patch("/profile")
@auth_required
def patch_my_profile():
    user_id = g.identity["userId"]
    body = request.get_json(silent=True) or {}
    profile = update_my_profile(user_id, body)
    return success(profile)


@bp.get("/demands")
@auth_required
def get_my_demands():
    user_id = g.identity["userId"]
    return success(list_my_demands(user_id, request.args))
