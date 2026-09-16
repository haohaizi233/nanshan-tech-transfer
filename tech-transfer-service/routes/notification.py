from fastapi import APIRouter, Depends, Request
from core.middleware import identity, json_body
from core.response import success
from modules.notification.service import summary, mark_read, list_notifications, mark_notification_read, mark_all_read

router = APIRouter(prefix='/api/tech-transfer/v1')

@router.get('/me/notifications/summary')
def notification_summary(user: dict = Depends(identity)):
    return success(summary(user['userId']))

@router.get('/me/notifications')
def notification_list(request: Request, user: dict = Depends(identity)):
    return success(list_notifications(user['userId'], request.query_params))

@router.post('/me/notifications/read')
async def notification_read(user: dict = Depends(identity), body: dict = Depends(json_body)):
    return success(mark_read(user['userId'], body.get('category')))

@router.post('/me/notifications/{notification_id}/read')
def notification_read_one(notification_id: int, user: dict = Depends(identity)):
    return success(mark_notification_read(user['userId'], notification_id))

@router.post('/me/notifications/read-all')
def notification_read_all(user: dict = Depends(identity)):
    return success(mark_all_read(user['userId']))
