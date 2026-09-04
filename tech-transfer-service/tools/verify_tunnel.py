"""端到端验证：外网隧道 H5(8077) + API(8076) + CORS 跨域组合"""
import json
import urllib.request

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


print("[1] 外网 API 隧道（8076 → 本地 8787）")
try:
    with _OPENER.open("http://43.138.138.200:8076/api/health", timeout=15) as r:
        body = json.loads(r.read().decode())
    check("GET 43.138.138.200:8076/api/health = 200", True)
    check("  code=0 status=ok db=ok", body.get("code") == 0
          and body.get("data", {}).get("status") == "ok"
          and body.get("data", {}).get("database") == "ok", body)
except Exception as e:
    check("GET 8076/api/health", False, str(e))

print("\n[2] 外网 H5 隧道（8077 → 本地 5173）")
try:
    with _OPENER.open("http://43.138.138.200:8077/", timeout=15) as r:
        html = r.read().decode(errors="replace")
    check("GET 43.138.138.200:8077/ = 200", True)
    check("  返回 HTML（含 #app 或 script）", "app" in html or "script" in html, html[:80])
except Exception as e:
    check("GET 8077/", False, str(e))

print("\n[3] H5 页面视角的 API 跨域（Origin=8077 → API 8076，CORS 放行验证）")
try:
    req = urllib.request.Request(
        "http://43.138.138.200:8076/api/tech-transfer/v1/auth/bootstrap",
        data=json.dumps({"hostCredential": "local-dev-ticket-dev-user-002"}).encode(),
        headers={"Content-Type": "application/json", "Origin": "http://43.138.138.200:8077"},
        method="POST")
    with _OPENER.open(req, timeout=15) as r:
        body = json.loads(r.read().decode())
        cors_header = r.headers.get("access-control-allow-origin", "")
    check("POST bootstrap（Origin=8077）= 200", body.get("code") == 0, body)
    check("  响应带 CORS 头", "8077" in cors_header, f"got: {cors_header!r}")
    token = body.get("data", {}).get("accessToken", "")
except Exception as e:
    token = ""
    check("POST bootstrap", False, str(e))

try:
    req = urllib.request.Request(
        "http://43.138.138.200:8076/api/tech-transfer/v1/demands",
        headers={"Authorization": f"Bearer {token}", "Origin": "http://43.138.138.200:8077"})
    with _OPENER.open(req, timeout=15) as r:
        body = json.loads(r.read().decode())
    d = body.get("data", {})
    check("GET demands（外网+登录）列表有数据", d.get("total", 0) > 0, f"total={d.get('total')}")
except Exception as e:
    check("GET demands", False, str(e))

print()
print(f"=== 隧道端到端验证: {PASS} passed, {FAIL} failed ===")
