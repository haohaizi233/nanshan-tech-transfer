from fastapi import APIRouter, Depends, Request

from core.response import success
from core.middleware import identity, json_body
from modules.profile.service import get_my_profile, update_my_profile
from modules.identity.service import change_password
from modules.demand.service import list_my_demands
from modules.achievement.service import list_my_achievements
from modules.favorite.service import list_my_favorites
from modules.cooperation.service import list_my_intents

router = APIRouter(prefix="/api/tech-transfer/v1/me", tags=["me"])


@router.get("")
def get_me(user: dict = Depends(identity)):
    profile = get_my_profile(user["userId"])
    return success(profile)


@router.patch("/profile")
def patch_my_profile(user: dict = Depends(identity), body: dict = Depends(json_body)):
    profile = update_my_profile(user["userId"], body)
    return success(profile)


@router.post("/password")
def post_my_password(user: dict = Depends(identity), body: dict = Depends(json_body)):
    result = change_password(
        user["userId"],
        body.get("currentPassword") or "",
        body.get("newPassword") or "",
    )
    return success(result, "密码已更新")


@router.get("/demands")
def get_my_demands(request: Request, user: dict = Depends(identity)):
    return success(list_my_demands(user["userId"], request.query_params))


@router.get("/achievements")
def get_my_achievements(request: Request, user: dict = Depends(identity)):
    return success(list_my_achievements(user["userId"], request.query_params))


@router.get("/favorites")
def get_my_favorites(request: Request, user: dict = Depends(identity)):
    return success(list_my_favorites(user["userId"], request.query_params))


@router.get("/cooperations")
def get_my_cooperations(request: Request, user: dict = Depends(identity)):
    return success(list_my_intents(user["userId"], request.query_params))
