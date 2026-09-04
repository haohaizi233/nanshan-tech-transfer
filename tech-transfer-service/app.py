"""
南山科转通 tech-transfer-service —— 模块化单体后端（FastAPI 版）

启动：
  python app.py
默认端口：8787
统一 API 前缀：/api/tech-transfer/v1
"""

from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from config import assert_environment, settings
from core.response import set_request_id, get_request_id
from core.exception_handlers import configure_logging, register_exception_handlers
from db import get_cursor
from routes.auth import router as auth_router
from routes.me import router as me_router
from routes.achievement import router as achievement_router
from routes.demand import router as demand_router
from routes.favorite import router as favorite_router
from routes.cooperation import router as cooperation_router
from routes.capital import router as capital_router
from routes.institution import router as institution_router
from routes.ai import router as ai_router
from routes.admin import router as admin_router
from routes.admin_ops import router as admin_ops_router
from routes.file import router as file_router

assert_environment()
configure_logging()

# /docs、/redoc、/openapi.json 仅开发环境启用（联调与测试用）；
# staging/production 关闭，避免对外暴露接口面
_docs_enabled = settings.is_local

app = FastAPI(
    title=settings.APP_NAME,
    description="南山科转通 —— 统一后端（成果/需求/对接/机构/AI/Admin）",
    version=settings.APP_VERSION,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
)

# CORS 白名单来自 Settings（CORS_ORIGINS）；
# 开发环境额外用 regex 放行本机/局域网/隧道 H5 dev server（见 config.cors_origin_regex）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Idempotency-Key"],
    expose_headers=["X-Request-Id"],
)

app.include_router(auth_router)
app.include_router(me_router)
app.include_router(achievement_router)
app.include_router(demand_router)
app.include_router(favorite_router)
app.include_router(cooperation_router)
app.include_router(capital_router)
app.include_router(institution_router)
app.include_router(ai_router)
app.include_router(admin_router)
app.include_router(admin_ops_router)
app.include_router(file_router)


# ── Vue 后台管理静态托管（nanshan-frontend/dist → /admin）────
# 构建产物存在才挂载：cd nanshan-frontend && npm run build
# 同源直连 API（前端 BASE 为相对路径 /api/tech-transfer/v1），免代理免 CORS
# 与 API admin 路由（/api/tech-transfer/v1/admin/...）无前缀冲突
_admin_dist = Path(__file__).resolve().parent.parent / "nanshan-frontend" / "dist"

if (_admin_dist / "index.html").is_file():
    app.mount(
        "/admin/assets",
        StaticFiles(directory=_admin_dist / "assets"),
        name="admin-assets",
    )

    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    def admin_spa(full_path: str = ""):
        # 静态文件命中即返回（favicon 等），其余一律回 index.html（SPA history 路由）
        if full_path:
            candidate = (_admin_dist / full_path).resolve()
            if candidate.is_file() and _admin_dist in candidate.parents:
                return FileResponse(candidate)
        return FileResponse(_admin_dist / "index.html")


# ── 请求 ID 中间件 ──────────────────────────────────────────
# 客户端 X-Request-Id 合法（受限字符集/长度）→ 复用；否则服务端生成。
# 响应统一回写 X-Request-Id 头，与错误体 requestId 一致，形成前端↔日志追踪链路。
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")


@app.middleware("http")
async def _set_request_id(request: Request, call_next):
    incoming = request.headers.get("X-Request-Id", "")
    request_id = incoming if _REQUEST_ID_RE.fullmatch(incoming) else uuid.uuid4().hex
    set_request_id(request_id)
    response = await call_next(request)
    response.headers["X-Request-Id"] = request_id
    return response


# ── 统一错误处理（全部集中在 core/exception_handlers.py 注册） ──
register_exception_handlers(app)


# ── 健康检查 ─────────────────────────────────────────────────
@app.get("/api/health", tags=["health"], summary="健康检查（DB 连通 + 运行环境）")
def health():
    try:
        with get_cursor() as cur:
            cur.execute("SELECT COUNT(*) AS c FROM app_user")
            user_count = cur.fetchone()["c"]
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "ok",
                "database": "ok",
                "db": True,
                "appUsers": user_count,
                "authProvider": settings.AUTH_PROVIDER,
                "appEnv": settings.APP_ENV,
            },
        }
    except Exception:
        # degraded 契约保持不变（HTTP 200 + code=1 + data.status=degraded）；
        # 具体异常（含 DB 连接细节）只进日志，不进响应
        logging.getLogger("nanshan.error").exception(
            "health check degraded request_id=%s", get_request_id()
        )
        return JSONResponse(status_code=200, content={
            "code": 1,
            "message": "数据库暂不可用",
            "data": {"status": "degraded", "database": "unavailable", "db": False},
        })


if __name__ == "__main__":
    assert_environment()
    import uvicorn

    print(f"tech-transfer-service listening on http://{settings.HOST}:{settings.PORT}")
    print(f"  API prefix: {settings.API_PREFIX}")
    print(f"  Health:     http://127.0.0.1:{settings.PORT}/api/health")
    print(f"  Bootstrap:  POST http://127.0.0.1:{settings.PORT}{settings.API_PREFIX}/auth/bootstrap")
    print(f"  Get Me:     GET  http://127.0.0.1:{settings.PORT}{settings.API_PREFIX}/me")
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG or settings.is_local,
    )

