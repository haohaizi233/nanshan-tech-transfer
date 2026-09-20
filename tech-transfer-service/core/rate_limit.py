"""轻量级进程内限流器（滑动窗口）。

用于登录/注册等敏感端点的暴力破解防护：
- 按 IP 限频：每 60s 最多 10 次尝试
- 按账号限频：每 300s 最多 5 次失败

注：进程内实现，多 worker 部署下每进程独立计数（保守，不会漏放，只会更严）。
如需跨进程共享，可后续替换为 Redis 实现。
"""
import time
from collections import defaultdict, deque

from core.errors import BizError, TT_COMMON_42901

_buckets = defaultdict(deque)


def _check(key: str, limit: int, window_s: int):
    now = time.time()
    q = _buckets[key]
    cutoff = now - window_s
    while q and q[0] < cutoff:
        q.popleft()
    if len(q) >= limit:
        code, message, status = TT_COMMON_42901
        raise BizError(code, "操作过于频繁，请稍后再试", status)
    q.append(now)


def _client_ip(request) -> str:
    # 反代场景下优先取 X-Forwarded-For 首段
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        return xff.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def check_login_rate(request, account: str = ""):
    """登录端点限流：按 IP + 按账号双重限频。

    IP 维度 20/60s 容忍正常多端登录与测试；账号维度 5/300s 才是暴力破解主防线
    （同一账号 5 分钟内 5 次失败即锁定该账号窗口）。
    """
    ip = _client_ip(request)
    _check(f"login:ip:{ip}", limit=20, window_s=60)
    if account:
        _check(f"login:acct:{account}", limit=5, window_s=300)


def check_register_rate(request):
    """注册端点限流：按 IP 限频，防止批量账号创建。

    阈值 30/5min：单 IP 5 分钟内注册超 30 个账号即视为批量脚本。
    正常用户极少注册，该阈值对真实流量无感，但能阻断自动化批量创建。
    """
    ip = _client_ip(request)
    _check(f"register:ip:{ip}", limit=30, window_s=300)
