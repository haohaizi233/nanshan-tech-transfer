"""AI 上游错误透传：不再把模型/agent 失败一律映射成 503。"""
from http.client import RemoteDisconnected
from urllib.error import URLError

from core.errors import BizError, ai_provider_failed
from routes.ai import (
    _network_reason,
    _parse_agent_error_details,
    _raise_from_agent_http,
    _raise_from_agent_network,
)

PASS = 0
FAIL = 0


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def expect_biz(fn, *, status, code, layer=None, llm_status=None, reason=None):
    try:
        fn()
    except BizError as exc:
        check(f"{code} http={status}", exc.http_status == status and exc.code == code,
              f"got {exc.http_status} {exc.code}")
        if layer is not None:
            check(f"layer={layer}", (exc.details or {}).get("layer") == layer,
                  f"got {exc.details}")
        if llm_status is not None:
            check(f"llmStatus={llm_status}", (exc.details or {}).get("llmStatus") == llm_status,
                  f"got {exc.details}")
        if reason is not None:
            check(f"reason={reason}", (exc.details or {}).get("reason") == reason,
                  f"got {exc.details}")
        return exc
    check(f"{code} 应抛 BizError", False, "未抛异常")
    return None


print("[1] 解析 ai-agent 结构化 LLM 回包")
details = _parse_agent_error_details(502, """
{"detail":{"message":"AI服务暂时不可用，请稍后重试。","layer":"llm","llmStatus":401,
"llmReason":"http_error","llmBody":"invalid api key"}}
""")
check("layer=llm", details.get("layer") == "llm", str(details))
check("llmStatus=401", details.get("llmStatus") == 401, str(details))
check("agentStatus=502", details.get("agentStatus") == 502, str(details))
check("reason=http_error", details.get("reason") == "http_error", str(details))
check("upstreamBody 保留模型正文", "invalid api key" in (details.get("upstreamBody") or ""), str(details))

print("\n[2] 上层模型 HTTP 401 → 对外 502 + llmStatus=401，不是 503")
expect_biz(
    lambda: _raise_from_agent_http(502, """{"detail":{"layer":"llm","llmStatus":401,"llmReason":"http_error"}}"""),
    status=502, code="TT_AI_50201", layer="llm", llm_status=401, reason="http_error",
)

exc = ai_provider_failed("AI Provider 调用失败", {"layer": "llm"})
check("provider 错误文案脱敏", "AI Provider 调用失败" not in exc.message and "AI 服务暂时不可用" in exc.message, exc.message)

print("\n[3] 上层模型 HTTP 502 → 对外 502 + llmStatus=502")
expect_biz(
    lambda: _raise_from_agent_http(502, """{"detail":{"layer":"llm","llmStatus":502,"llmReason":"http_error","llmBody":"Bad Gateway"}}"""),
    status=502, code="TT_AI_50201", layer="llm", llm_status=502,
)

print("\n[4] agent 自身 500 → 对外 502 + layer=agent")
expect_biz(
    lambda: _raise_from_agent_http(500, """{"detail":{"layer":"agent","agentReason":"router_error","message":"意图识别失败"}}"""),
    status=502, code="TT_AI_50201", layer="agent", reason="router_error",
)

print("\n[5] agent 连接被掐（无 HTTP 状态）→ 503 + reason=connection_reset")
expect_biz(
    lambda: _raise_from_agent_network(URLError(RemoteDisconnected("Remote end closed connection without response"))),
    status=503, code="TT_AI_50301", layer="agent", reason="connection_reset",
)
check(
    "network_reason=connection_reset",
    _network_reason(URLError(RemoteDisconnected("Remote end closed connection without response"))) == "connection_reset",
    "",
)

print("\n[6] 响应头透出 llmStatus")
from fastapi.responses import JSONResponse  # noqa: E402
from core.exception_handlers import _attach_upstream_headers  # noqa: E402

resp = JSONResponse(status_code=502, content={"code": "TT_AI_50201"})
_attach_upstream_headers(resp, {
    "layer": "llm",
    "llmStatus": 502,
    "reason": "http_error",
    "agentStatus": 502,
    "upstreamBody": "model overloaded",
})
check("X-Upstream-Layer=llm", resp.headers.get("X-Upstream-Layer") == "llm", dict(resp.headers))
check("X-Upstream-Status=502", resp.headers.get("X-Upstream-Status") == "502", dict(resp.headers))
check("X-Upstream-Reason=http_error", resp.headers.get("X-Upstream-Reason") == "http_error", dict(resp.headers))

none_resp = JSONResponse(status_code=503, content={"code": "TT_AI_50301"})
_attach_upstream_headers(none_resp, {"layer": "agent", "reason": "connection_reset"})
check("无 HTTP 状态时 X-Upstream-Status=none", none_resp.headers.get("X-Upstream-Status") == "none", dict(none_resp.headers))
check("X-Upstream-Layer=agent", none_resp.headers.get("X-Upstream-Layer") == "agent", dict(none_resp.headers))

patent_resp = JSONResponse(status_code=502, content={"code": "TT_PATENT_50201"})
_attach_upstream_headers(patent_resp, {
    "layer": "provider",
    "providerStatus": 422,
    "reason": "http_error",
})
check("专利 X-Upstream-Layer=provider", patent_resp.headers.get("X-Upstream-Layer") == "provider", dict(patent_resp.headers))
check("专利 X-Upstream-Status=422", patent_resp.headers.get("X-Upstream-Status") == "422", dict(patent_resp.headers))

print(f"\n=== AI 上游状态透传测试: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
