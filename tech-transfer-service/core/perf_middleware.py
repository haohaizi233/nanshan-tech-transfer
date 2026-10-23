"""低侵入性能埋点中间件：记录每个请求各阶段耗时。

对慢请求（>100ms）输出结构化日志，正常请求只记debug级。
通过 X-Request-Id 关联全链路。
"""
import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logger = logging.getLogger("nanshan.perf")

# 慢请求阈值（毫秒）
SLOW_THRESHOLD_MS = 100


class PerformanceMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        start = time.perf_counter()
        request_id = request.headers.get("X-Request-Id", "-")
        
        # 请求进入时间
        entry_time = time.time()
        
        # 执行业务
        response = await call_next(request)
        
        # 计算耗时
        elapsed_ms = (time.perf_counter() - start) * 1000
        
        # 获取响应大小
        content_length = response.headers.get("content-length", "?")
        
        # 慢请求告警
        if elapsed_ms > SLOW_THRESHOLD_MS:
            logger.warning(
                "SLOW %s %s %.1fms size=%s rid=%s",
                request.method, request.url.path, elapsed_ms,
                content_length, request_id,
            )
        else:
            logger.debug(
                "%s %s %.1fms size=%s rid=%s",
                request.method, request.url.path, elapsed_ms,
                content_length, request_id,
            )
        
        # 添加性能响应头（可选，用于DevTools查看）
        response.headers["X-Response-Time"] = f"{elapsed_ms:.1f}ms"
        
        return response
