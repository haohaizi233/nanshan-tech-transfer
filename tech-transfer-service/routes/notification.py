from fastapi import APIRouter, Depends
from core.middleware import identity, json_body
from core.response import success
from modules.notification.service import summary, mark_read

router = APIRouter(prefix='/api/tech-transfer/v1')

@router.get('/me/notifications/summary')
def notification_summary(user: dict = Depends(identity)):
    return success(summary(user['userId']))

@router.post('/me/notifications/read')
async def notification_read(user: dict = Depends(identity), body: dict = Depends(json_body)):
    return success(mark_read(user['userId'], body.get('category')))
