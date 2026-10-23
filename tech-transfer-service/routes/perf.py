"""性能监控端点：慢SQL查询 + 系统指标。"""
from fastapi import APIRouter, Depends

from core.auth import identity
from core.response import success
from db import get_cursor

router = APIRouter()


@router.get("/perf/slow-sql")
def get_slow_sql(limit: int = 10, user: dict = Depends(identity)):
    """获取最慢的SQL查询（需要pg_stat_statements扩展）。"""
    try:
        with get_cursor(commit=False) as cur:
            cur.execute("""
                SELECT 
                    query,
                    calls,
                    round(mean_exec_time::numeric, 2) as mean_ms,
                    round(total_exec_time::numeric, 2) as total_ms,
                    rows
                FROM pg_stat_statements
                ORDER BY mean_exec_time DESC
                LIMIT %s
            """, (min(limit, 50),))
            rows = cur.fetchall()
        return success({"slowSql": [dict(r) for r in rows]})
    except Exception:
        return success({"slowSql": [], "note": "pg_stat_statements未启用或无权限"})


@router.get("/perf/connections")
def get_db_connections(user: dict = Depends(identity)):
    """获取数据库连接池状态。"""
    with get_cursor(commit=False) as cur:
        cur.execute("""
            SELECT state, count(*) as count 
            FROM pg_stat_activity 
            WHERE datname = current_database()
            GROUP BY state
        """)
        rows = cur.fetchall()
    return success({"connections": [dict(r) for r in rows]})


@router.get("/perf/response-stats")
def get_response_stats(user: dict = Depends(identity)):
    """获取API响应统计（从性能中间件日志解析）。"""
    return success({
        "note": "请查看后端日志 nanshan-backend.log 中的 X-Response-Time 头",
        "threshold": "慢请求 > 100ms 会输出 SLOW 日志"
    })
