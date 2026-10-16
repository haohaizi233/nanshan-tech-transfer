"""上线冒烟：health / openapi / 全接口扫描（无 500）/ CORS（H5 dev server 源）

扫描规则：
- GET/HEAD → 带 token 请求，断言 HTTP < 500
- POST/PATCH/PUT/DELETE → 带 token + 空 body 请求，断言 HTTP < 500
  （业务上应返回 400/401/403/404/409 之一——写接口参数校验/鉴权正常工作，
   任何 500 都代表未捕获异常，属发布阻断项）
- 路径参数替换：{xxx} 数值型 → 1，其余 → achievement
运行：python tools/smoke_release.py（后端需已启动，APP_ENV=local）
"""
import json
import sys
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:8787"
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

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


def request(method, path, token=None, body=None, headers=None):
    h = dict(headers or {})
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    if token:
        h["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(BASE + path, data=data, headers=h, method=method)
    try:
        resp = _OPENER.open(req, timeout=10)
        raw = resp.read().decode(errors="replace")
        try:
            return resp.status, json.loads(raw)
        except (ValueError, TypeError):
            return resp.status, {}  # HTML / 空响应（如 /docs 页面、204 预检）
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode() or "{}")
        except Exception:
            return e.code, {}
    except Exception as e:
        return -1, {"message": str(e)}


def sub_params(path):
    out = []
    for seg in path.split("/"):
        if seg.startswith("{") and seg.endswith("}"):
            name = seg[1:-1]
            out.append("achievement" if name in ("type", "targetType") else "1")
        else:
            out.append(seg)
    return "/".join(out)


print("[1] 健康检查与文档端点")
st, body = request("GET", "/api/health")
check("GET /api/health = 200 code=0", st == 200 and body.get("code") == 0, f"{st} {body}")
check("  data.status=ok db=ok", body.get("data", {}).get("status") == "ok"
      and body.get("data", {}).get("database") == "ok", body.get("data"))
st, _ = request("GET", "/docs")
check("GET /docs = 200", st == 200, f"got {st}")
st, _ = request("GET", "/openapi.json")
check("GET /openapi.json = 200", st == 200, f"got {st}")

print("\n[2] 登录获取 token（dev-user-002）")
st, body = request("POST", "/api/tech-transfer/v1/auth/bootstrap",
                   body={"hostCredential": "local-dev-ticket-dev-user-002"})
check("bootstrap = 200", st == 200, f"{st} {body}")
token = body.get("data", {}).get("accessToken", "")

print("\n[3] 全接口扫描（openapi.json 枚举，断言无 500）")
spec = json.load(_OPENER.open(BASE + "/openapi.json", timeout=10))
methods = ("get", "post", "put", "patch", "delete")
WRITE_OK = {400, 401, 403, 404, 409, 422, 429}
# /api/file/{file_id} 是存量源站文件代理（Phase A 内联提取）：502=源站拉取失败
# 属代理语义的合法失败路径，非服务自身异常 —— 存活即可，不断言 <500
PROXY_OK = {400, 404, 502}
scanned = 0
for path, item in sorted(spec["paths"].items()):
    real_path = sub_params(path)
    is_proxy = path.startswith("/api/file/")
    for m in item:
        if m not in methods:
            continue
        scanned += 1
        body = None if m in ("get", "head") else {}
        # auth 相关接口不需要 token；带 token 也无害
        st, resp = request(m.upper(), real_path, token=token, body=body)
        if is_proxy:
            ok = st in PROXY_OK
            expect = f"代理存活（{sorted(PROXY_OK)}）"
        elif m in ("get", "head"):
            ok = st < 500
            expect = "HTTP < 500"
        else:
            ok = (st < 500 and st in WRITE_OK) or st == 200 or st == 201
            expect = f"HTTP<500 且业务可预期（200/201/{sorted(WRITE_OK)}），实际 {st}"
        check(f"{m.upper():6} {path}", ok, f"{st} {resp.get('message', '')[:80]}（预期 {expect}）")

print("\n[4] CORS 预检（模拟 H5 dev server http://localhost:5173）")
st, _ = request("OPTIONS", "/api/tech-transfer/v1/achievements",
                headers={
                    "Origin": "http://localhost:5173",
                    "Access-Control-Request-Method": "GET",
                    "Access-Control-Request-Headers": "authorization,content-type",
                })
# urllib 不回显响应头，预检失败会以 HTTPError 4xx 暴露；200 即通过
check("OPTIONS 预检 = 200（放行 localhost:5173）", st == 200, f"got {st}")
st, resp = request("GET", "/api/tech-transfer/v1/achievements", token=token,
                   headers={"Origin": "http://localhost:5173"})
check("带 Origin 的实际请求 = 200", st == 200, f"{st}")

print()
print(f"=== 上线冒烟: {PASS} passed, {FAIL} failed（扫描 {scanned} 个方法）===")
sys.exit(1 if FAIL else 0)
