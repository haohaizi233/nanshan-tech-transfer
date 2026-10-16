"""轻量级进程内限流器（滑动窗口）。

用于登录/注册等敏感端点的暴力破解防护：
- 按 IP 限频：每 60s 最多 10 次尝试
- 按账号限频：每 300s 最多 5 次失败

注：进程内实现，多 worker 部署下每进程独立计数（保守，不会漏放，只会更严）。
如需跨进程共享，可后续替换为 Redis 实现。

内存护栏（M7）：桶按惰性修剪 + 定期全局清扫 + 硬上限，防止大量 IP/key 时无限增长。
"""
import os
import threading
import time
from collections import defaultdict, deque

from core.errors import TT_COMMON_42901, BizError

_buckets: dict[str, deque] = defaultdict(deque)
_bucket_lock = threading.Lock()
# 桶数量硬上限：超过时强制全局清扫，仍超限则丢弃最旧的桶（限流状态可丢，宁严勿漏）
_MAX_BUCKETS = 20000
# 每 N 次检查触发一次全局清扫，删除窗口内已空的桶
_CLEAN_EVERY = 256
_check_counter = 0

# N3: 可信反向代理列表（逗号分隔 IP/CIDR）。只有当 TCP 直连对端是可信代理时，
# 才解析 X-Forwarded-For；否则 XFF 完全不可信（客户端可任意伪造），直接用对端 IP。
# 默认只信任本机回环（Caddy/frp 与服务同机部署的拓扑）；多机拓扑用
# TRUSTED_PROXIES=10.0.0.5,192.168.1.0/24 显式扩展。
_DEFAULT_TRUSTED_PROXIES = ("127.0.0.1", "::1", "localhost")


def _parse_trusted_proxies() -> tuple:
    raw = os.getenv("TRUSTED_PROXIES", "")
    items = [item.strip() for item in raw.split(",") if item.strip()]
    return tuple(items) if items else _DEFAULT_TRUSTED_PROXIES


def _is_trusted_proxy(host: str) -> bool:
    if not host:
        return False
    normalized = host.lower()
    if normalized.startswith("::ffff:"):  # IPv4-mapped IPv6
        normalized = normalized[7:]
    for proxy in _parse_trusted_proxies():
        proxy = proxy.lower()
        if "/" in proxy:
            try:
                import ipaddress
                if ipaddress.ip_address(normalized) in ipaddress.ip_network(proxy, strict=False):
                    return True
            except ValueError:
                continue
        elif normalized == proxy:
            return True
    return False


def _sweep_locked(now: float) -> None:
    """删除所有元素都已滑出窗口的空桶；超硬上限时按插入序丢弃最旧的桶。"""
    empty = [key for key, q in _buckets.items() if not q]
    for key in empty:
        _buckets.pop(key, None)
    while len(_buckets) > _MAX_BUCKETS:
        _buckets.pop(next(iter(_buckets)), None)


def _check(key: str, limit: int, window_s: int):
    global _check_counter
    now = time.time()
    cutoff = now - window_s
    with _bucket_lock:
        q = _buckets[key]
        while q and q[0] < cutoff:
            q.popleft()
        if len(q) >= limit:
            code, message, status = TT_COMMON_42901
            raise BizError(code, "操作过于频繁，请稍后再试", status)
        q.append(now)
        _check_counter += 1
        if _check_counter % _CLEAN_EVERY == 0:
            _sweep_locked(now)


def _client_ip(request) -> str:
    """真实客户端 IP（N3: trusted-proxy 防 XFF 伪造）。

    只有当 TCP 直连对端（request.client.host）在 TRUSTED_PROXIES 白名单内时，
    才信任 X-Forwarded-For：反代（Caddy/frp）会把上一跳来源 IP 追加到 XFF 尾部，
    因此只取 XFF 的最后一跳——首段是客户端自带的，可任意伪造，绝不能用于限流。
    直连（非可信代理）场景下 XFF 整体忽略，用 TCP 对端 IP 限流，
    否则攻击者伪造 XFF 轮换假 IP 即可完全绕过 IP 维度限流。
    """
    peer = request.client.host if request.client else "unknown"
    if not _is_trusted_proxy(peer):
        return peer
    xff = request.headers.get("x-forwarded-for", "")
    if xff:
        last_hop = xff.split(",")[-1].strip()
        if last_hop:
            return last_hop
    return peer


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


def check_ip_rate(request, action: str, limit: int, window_s: int):
    """按 IP 的通用滑动窗口限流（/refresh、/logout 等敏感端点复用）。"""
    ip = _client_ip(request)
    _check(f"{action}:ip:{ip}", limit=limit, window_s=window_s)


def check_user_rate(user_id, action: str, limit: int, window_s: int):
    """按用户的滑动窗口限流（/ai/* 成本防刷、上传防刷）。"""
    _check(f"{action}:user:{user_id}", limit=limit, window_s=window_s)


def check_user_daily_quota(user_id, action: str, limit: int):
    """按用户的自然日配额（上传量等）。key 含日期，隔天自动重置。"""
    day = time.strftime("%Y-%m-%d", time.localtime())
    _check(f"{action}:day:{day}:user:{user_id}", limit=limit, window_s=24 * 3600)
