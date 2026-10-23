"""接口鉴权：区分「同机回环」与「服务间调用」两种可信来源。

背景（真实审计结论）：
- ``/internal/*`` 是后端 → Agent 的私有通道，必须用共享密钥严格校验；
- ``/api/ai/chat`` 曾经**完全没有鉴权**，而后端转发时也不带任何身份凭据。
  Agent 一旦绑定在可路由地址上（例如历史部署的公网 IP + 8000 端口），
  任何人都能把它当成「免费的模型代理 + 成果库查询接口」使用：
  既能烧掉模型的额度，也能绕过主服务的登录校验与频控枚举全部已发布数据。

因此这里明确两条边界：

1. 配置了共享密钥 → 必须携带且必须匹配（常量时间比较，失败一律 401）；
2. 未配置共享密钥 → 只接受**同机回环**调用；非回环来源直接拒绝，
   既保持本地开发的零配置可用，又不会把无鉴权端点暴露到网络上。
"""

from __future__ import annotations

import hmac
import ipaddress

from fastapi import HTTPException

from app.config import settings


_LOOPBACK_HOSTNAMES = {"localhost", "localhost.localdomain", "ip6-localhost"}


def _is_loopback(host: str | None) -> bool:
    """判断对端是否为本机回环地址。"""
    if not host:
        return False
    candidate = str(host).strip().lower()
    if candidate in _LOOPBACK_HOSTNAMES:
        return True
    # IPv6 回环在 ASGI 里可能带 %scope 或方括号
    candidate = candidate.strip("[]").split("%", 1)[0]
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _matches(supplied: str | None, configured: str) -> bool:
    if not supplied:
        return False
    return hmac.compare_digest(
        supplied.encode("utf-8"), configured.encode("utf-8")
    )


def authorize_internal(supplied: str | None) -> None:
    """私有通道鉴权：必须配置共享密钥且必须匹配。

    密钥未配置时 fail-closed（503），绝不放行。
    """
    configured = settings.AI_INTERNAL_SERVICE_KEY
    if not configured:
        raise HTTPException(
            status_code=503,
            detail={"reason": "internal_key_not_configured"},
        )
    if not _matches(supplied, configured):
        raise HTTPException(status_code=401, detail={"reason": "unauthorized"})


def authorize_service_call(
    supplied: str | None,
    client_host: str | None = None,
) -> None:
    """服务间调用鉴权（后端 → Agent 的同步对话通道）。

    - 配置了 ``AI_PUBLIC_API_KEY``（或复用 ``AI_INTERNAL_SERVICE_KEY``）：
      必须携带匹配密钥，否则 401；
    - 未配置密钥：仅接受同机回环来源；非回环来源返回 503，
      并明确告诉运维「服务未配置服务密钥」，而不是静默放行。
    """
    configured = settings.AI_PUBLIC_API_KEY or settings.AI_INTERNAL_SERVICE_KEY
    if configured:
        if not _matches(supplied, configured):
            raise HTTPException(status_code=401, detail={"reason": "unauthorized"})
        return
    if not _is_loopback(client_host):
        raise HTTPException(
            status_code=503,
            detail={
                "reason": "service_key_not_configured",
                "message": "AI 服务未配置服务间密钥，已拒绝非本机调用。",
            },
        )
