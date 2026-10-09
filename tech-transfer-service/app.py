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
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from config import assert_environment, settings
from core.response import set_request_id, get_request_id
from core.exception_handlers import configure_logging, register_exception_handlers
from db import close_pool, get_cursor, init_pool
from routes.auth import router as auth_router
from routes.me import router as me_router
from routes.achievement import router as achievement_router
from routes.demand import router as demand_router
from routes.favorite import router as favorite_router
from routes.cooperation import router as cooperation_router
from routes.capital import router as capital_router
from routes.institution import router as institution_router
from routes.ai import router as ai_router
from routes.search import router as search_router
from routes.patent import router as patent_router
from routes.admin import router as admin_router
from routes.admin_ops import router as admin_ops_router
from routes.file import router as file_router
from routes.membership import router as membership_router
from routes.institution_registration import router as institution_registration_router
from routes.notification import router as notification_router

assert_environment()
configure_logging()

# /docs、/redoc、/openapi.json 仅开发环境启用（联调与测试用）；
# staging/production 关闭，避免对外暴露接口面
_docs_enabled = settings.is_local


# ── DB 连接池生命周期（T007）────────────────────────────────
@asynccontextmanager
async def lifespan(_: FastAPI):
    # 启动即建池（DB 不可用时降级为空池懒填充，不阻塞服务）
    init_pool()
    yield
    close_pool()


app = FastAPI(
    title=settings.APP_NAME,
    description="南山科转通 —— 统一后端（成果/需求/对接/机构/AI/Admin）",
    version=settings.APP_VERSION,
    docs_url="/docs" if _docs_enabled else None,
    redoc_url="/redoc" if _docs_enabled else None,
    openapi_url="/openapi.json" if _docs_enabled else None,
    lifespan=lifespan,
)

# CORS 白名单来自 Settings（CORS_ORIGINS）；
# 开发环境额外用 regex 放行本机/局域网/隧道 H5 dev server（见 config.cors_origin_regex）
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_origin_regex=settings.cors_origin_regex,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Request-Id", "X-Idempotency-Key"],
    expose_headers=["X-Request-Id", "X-Upstream-Layer", "X-Upstream-Status", "X-Upstream-Reason"],
)


# ── 安全响应头（防点击劫持 / MIME 嗅探 / 降级）────────────────
@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    # 限制内嵌 iframe；API 响应不需要 CSP，仅对 HTML 页面设 frame-ancestors
    if "text/html" in response.headers.get("content-type", ""):
        response.headers["Content-Security-Policy"] = "frame-ancestors 'none'"
    return response


app.include_router(auth_router)
app.include_router(institution_registration_router)
app.include_router(notification_router)
app.include_router(me_router)
app.include_router(achievement_router)
app.include_router(demand_router)
app.include_router(favorite_router)
app.include_router(cooperation_router)
app.include_router(capital_router)
app.include_router(institution_router)
app.include_router(ai_router)
app.include_router(search_router)
app.include_router(patent_router)
app.include_router(admin_router)
app.include_router(admin_ops_router)
app.include_router(file_router)
app.include_router(membership_router)


# ── Vue 后台管理静态托管（nanshan-frontend/dist）────────────
# 路由约定与 SPA 一致（vite/vue-router base 均为 '/'）：
#   页面路径 /login、/register、/admin/* 一律回 index.html（history 路由刷新不 404）
#   静态资源挂 /assets（资源名带内容 hash 可长缓存），另挂 /admin/assets 兼容旧缓存页
# 同源直连 API（前端 BASE 为相对路径 /api/tech-transfer/v1），免代理免 CORS；
# 不使用根级 catch-all，避免吞掉 /api/* 的 404 错误契约
_admin_dist = Path(__file__).resolve().parent.parent / "nanshan-frontend" / "dist"

if (_admin_dist / "index.html").is_file():
    _assets_dir = _admin_dist / "assets"

    if _assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=_assets_dir), name="admin-assets")
        app.mount("/admin/assets", StaticFiles(directory=_assets_dir), name="admin-assets-legacy")

    _admin_icons_dir = _admin_dist / "admin-icons"
    if _admin_icons_dir.is_dir():
        app.mount("/admin-icons", StaticFiles(directory=_admin_icons_dir), name="admin-icons")

    @app.get("/", include_in_schema=False)
    @app.get("/login", include_in_schema=False)
    @app.get("/register", include_in_schema=False)
    @app.get("/admin", include_in_schema=False)
    @app.get("/admin/{full_path:path}", include_in_schema=False)
    def admin_spa(full_path: str = ""):
        # /admin/ 下的静态文件（favicon 等）命中即返回，其余一律回 index.html
        if full_path:
            candidate = (_admin_dist / full_path).resolve()
            if candidate.is_file() and _admin_dist in candidate.parents:
                return FileResponse(candidate)
        # index.html 不缓存：避免旧页面引用已失效的资源 hash 导致白屏
        return FileResponse(
            _admin_dist / "index.html", headers={"Cache-Control": "no-cache"}
        )

    # 根级静态文件（favicon / icons）
    for _static_name in ("favicon.svg", "icons.svg"):
        if (_admin_dist / _static_name).is_file():

            def _serve_static(file_name: str = _static_name):
                return FileResponse(_admin_dist / file_name)

            app.add_api_route(
                f"/{_static_name}", _serve_static, methods=["GET"], include_in_schema=False
            )

    # 浏览器会默认请求 /favicon.ico；后台只有 SVG 图标时复用它，避免每次访问都
    # 产生一条无意义的 404（现代浏览器支持以 SVG 作为站点图标）。
    if (_admin_dist / "favicon.svg").is_file():
        @app.get("/favicon.ico", include_in_schema=False)
        def admin_favicon_ico():
            return FileResponse(_admin_dist / "favicon.svg", media_type="image/svg+xml")


# ── 小程序 H5（/h5/）────────────────────────────────────────
# 公网 Caddy 把 /h5 转到本服务（与 /api 同一上游），再反代本机 :5173。
# VPS 上没有 HBuilder 进程；不能把 /h5 直接打到 127.0.0.1:5173。
_H5_DEV_ORIGIN = "http://127.0.0.1:5173"
_H5_ROOT = Path(__file__).resolve().parent.parent / "南山小程序" / "南山"
_H5_DIST_CANDIDATES = (
    _H5_ROOT / "dist" / "build" / "h5",
    _H5_ROOT / "unpackage" / "dist" / "build" / "h5",
    _H5_ROOT / "unpackage" / "dist" / "dev" / "h5",
)
_H5_PROXY_OPENER = None


def _h5_opener():
    # HTTP-only：避免 build_opener 默认装 HTTPSHandler 时扫 Windows 证书库卡住 reload
    global _H5_PROXY_OPENER
    if _H5_PROXY_OPENER is None:
        opener = urllib.request.OpenerDirector()
        opener.add_handler(urllib.request.ProxyHandler({}))
        opener.add_handler(urllib.request.HTTPHandler())
        _H5_PROXY_OPENER = opener
    return _H5_PROXY_OPENER


def _h5_dist_dir() -> Path | None:
    for candidate in _H5_DIST_CANDIDATES:
        if (candidate / "index.html").is_file():
            return candidate
    return None


def _h5_from_dist(full_path: str):
    dist = _h5_dist_dir()
    if dist is None:
        return None
    relative = (full_path or "").lstrip("/")
    if relative:
        candidate = (dist / relative).resolve()
        if candidate.is_file() and dist in candidate.parents:
            return FileResponse(candidate)
    return FileResponse(dist / "index.html", headers={"Cache-Control": "no-cache"})


def _h5_dev_url(full_path: str, query: str) -> str:
    suffix = (full_path or "").lstrip("/")
    target = f"{_H5_DEV_ORIGIN}/h5/{suffix}" if suffix else f"{_H5_DEV_ORIGIN}/h5/"
    if query:
        # 必须用 request.url.query 原样拼接。str(QueryParams) 会把 Vite
        # `?vue&type=style` 改成 `vue=`，Vue SFC 样式就会以裸 CSS 当 JS 下发，H5 白屏。
        target = f"{target}?{query}"
    return target


def _h5_from_dev(full_path: str, query: str):
    target = _h5_dev_url(full_path, query)
    try:
        with _h5_opener().open(target, timeout=15) as resp:  # M1: 降低 H5 代理超时
            headers = {}
            content_type = resp.headers.get("Content-Type")
            cache = resp.headers.get("Cache-Control")
            if cache:
                headers["Cache-Control"] = cache
            return Response(
                content=resp.read(),
                status_code=getattr(resp, "status", 200),
                media_type=content_type,
                headers=headers,
            )
    except urllib.error.HTTPError as exc:
        return Response(
            content=exc.read(),
            status_code=exc.code,
            media_type=exc.headers.get("Content-Type"),
        )
    except (urllib.error.URLError, TimeoutError, OSError):
        return None


@app.api_route("/h5", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/h5/", methods=["GET", "HEAD"], include_in_schema=False)
@app.api_route("/h5/{full_path:path}", methods=["GET", "HEAD"], include_in_schema=False)
def mini_program_h5(request: Request, full_path: str = ""):
    proxied = _h5_from_dev(full_path, request.url.query)
    if proxied is not None:
        return proxied
    disted = _h5_from_dist(full_path)
    if disted is not None:
        return disted
    return JSONResponse(
        {
            "code": "TT_COMMON_50301",
            "message": "小程序 H5 未启动。请在本机运行 start_dev.py --h5 后刷新。",
            "requestId": get_request_id(),
        },
        status_code=503,
    )


# ── 请求超时保护（M1：sync 路由保护，防止长阻塞耗尽线程池）────
import asyncio

@app.middleware("http")
async def request_timeout_middleware(request: Request, call_next):
    max_seconds = getattr(settings, "MAX_REQUEST_SECONDS", 60.0)
    try:
        return await asyncio.wait_for(call_next(request), timeout=max_seconds)
    except asyncio.TimeoutError:
        from core.response import error as error_response
        from core.errors import TT_COMMON_50301
        code, message, status = TT_COMMON_50301
        return JSONResponse(
            status_code=504,
            content={"code": code, "message": "请求处理超时，请稍后重试", "requestId": get_request_id()},
        )

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
@app.get("/health", tags=["health"], summary="存活检查（Caddy / 负载均衡探针）")
@app.get("/api/health", tags=["health"], summary="健康检查（DB 连通 + 运行环境）")
def health():
    try:
        with get_cursor() as cur:
            # 仅探活，不暴露用户总数（公开端点不应泄露业务量级）
            cur.execute("SELECT 1")
        return {
            "code": 0,
            "message": "ok",
            "data": {
                "status": "ok",
                "database": "ok",
                "db": True,
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
    print(f"  Health:     http://127.0.0.1:{settings.PORT}/health")
    print(f"  API health: http://127.0.0.1:{settings.PORT}/api/health")
    print(f"  Bootstrap:  POST http://127.0.0.1:{settings.PORT}{settings.API_PREFIX}/auth/bootstrap")
    print(f"  Get Me:     GET  http://127.0.0.1:{settings.PORT}{settings.API_PREFIX}/me")
    uvicorn.run(
        "app:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG or settings.is_local,  # local reload picks up AI_FEATURE_ENABLED
        # 生产环境多 worker 提升吞吐并隔离阻塞；本地 reload 模式不支持多 worker
        workers=settings.UVICORN_WORKERS if not (settings.DEBUG or settings.is_local) else 1,
    )

