"""
AI 路由 —— POST /ai/match-tasks, GET /ai/match-tasks/{taskId}

Architecture source: 06-api-design.md §AI, openapi.yaml /ai/match-tasks
P0-2 稳定边界：异步任务制（202 + 轮询）；执行 worker 未接入前任务保持 queued，
不产生任何假 AI 结果。
"""
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from core.response import success, get_request_id
from core.middleware import identity, json_body
from modules.ai.service import create_match_task, get_match_task

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["ai"])


@router.post("/ai/match-tasks", status_code=202)
def match_tasks_create(request: Request, user: dict = Depends(identity), body: dict = Depends(json_body)):
    demand_id = body.get("demandId")
    if not isinstance(demand_id, int) or demand_id <= 0:
        # 参数校验与既有路由一致：交给 service 前先挡掉明显非法值
        from core.errors import bad_request
        raise bad_request("demandId 必须为正整数")
    idem_key = request.headers.get("X-Idempotency-Key")
    if idem_key:
        print(f"[ai] X-Idempotency-Key received: {idem_key} (replay protection NOT IMPLEMENTED)")
    task, is_new = create_match_task(
        user["userId"], user.get("userNo", ""), demand_id,
        request_id=get_request_id(),
    )
    if not is_new:
        # 去重命中：返回进行中任务，200 而非 202
        return JSONResponse(status_code=200, content=success(task, "任务进行中"))
    return success(task, "任务已受理")


@router.get("/ai/match-tasks/{task_id}")
def match_task_detail(task_id: int, user: dict = Depends(identity)):
    return success(get_match_task(user["userId"], task_id))
