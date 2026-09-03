"""
南山科转通 tech-transfer-service —— 模块化单体后端（FastAPI 版）

启动：
  python app.py
默认端口：8787
统一 API 前缀：/api/tech-transfer/v1
"""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from config import assert_environment, API_PREFIX
from core.response import success, error, set_request_id
from core.errors import BizError
from db import get_cursor
from routes.auth import router as auth_router
from routes.me import router as me_router
from routes.achievement import router as achievement_router
from routes.demand import router as demand_router
from routes.favorite import router as favorite_router
from routes.cooperation import router as cooperation_router
from routes.capital import router as capital_router
from routes.file import router as file_router

assert_environment()

app = FastAPI(title="tech-transfer-service", docs_url=None, redoc_url=None, openapi_url=None)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(achievement_router)
app.include_router(demand_router)
app.include_router(favorite_router)
app.include_router(cooperation_router)
app.include_router(capital_router)
app.include_router(file_router)


# ── 请求 ID 中间件 ──────────────────────────────────────────
@app.middleware("http")
async def _set_request_id(request: Request, call_next):
    set_request_id(request.headers.get("X-Request-Id") or str(uuid.uuid4()))
    return await call_next(request)


# ── 统一错误处理 ─────────────────────────────────────────────
@app.exception_handler(BizError)
async def _handle_biz_error(_: Request, e: BizError):
    return error(e.code, e.message, e.http_status, e.details)


@app.exception_handler(RequestValidationError)
async def _handle_validation_error(_: Request, e: RequestValidationError):
    # 等价 Flask 行为：路径参数类型不匹配（如 /demands/abc）→ 404 接口不存在
    return error("TT_COMMON_40401", "接口不存在", 404)


@app.exception_handler(StarletteHTTPException)
async def _handle_http_error(_: Request, e: StarletteHTTPException):
    if e.status_code == 404:
        return error("TT_COMMON_40401", "接口不存在", 404)
    return JSONResponse(status_code=e.status_code, content={"detail": e.detail})


@app.exception_handler(Exception)
async def _handle_500(_: Request, e: Exception):
    logging.exception("unhandled error")
    return error("TT_COMMON_50001", f"服务内部错误: {e}", 500)


# ── 健康检查 ─────────────────────────────────────────────────
@app.get("/api/health")
def health():
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_user")
            user_count = cur.fetchone()["c"]
        import config as _cfg
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "db": True,
                "appUsers": user_count,
                "authProvider": _cfg.AUTH_PROVIDER,
                "appEnv": _cfg.APP_ENV,
            },
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"code": 1, "message": str(e), "data": {"db": False}})


if __name__ == "__main__":
    assert_environment()
    import uvicorn

    print("tech-transfer-service listening on http://0.0.0.0:8787")
    print(f"  API prefix: {API_PREFIX}")
    print("  Health:     http://127.0.0.1:8787/api/health")
    print("  Bootstrap:  POST http://127.0.0.1:8787/api/tech-transfer/v1/auth/bootstrap")
    print("  Get Me:     GET  http://127.0.0.1:8787/api/tech-transfer/v1/me")
    uvicorn.run("app:app", host="0.0.0.0", port=8787, reload=True)
