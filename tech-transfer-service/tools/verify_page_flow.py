"""模拟外网 H5 页面真实视角：mock 登录 + 首页数据"""
import json
import urllib.request

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
origin = "http://43.138.138.200:8077"

req = urllib.request.Request(
    "http://43.138.138.200:8076/api/tech-transfer/v1/auth/bootstrap",
    data=json.dumps({"hostCredential": "local-dev-ticket-dev-user-001"}).encode(),
    headers={"Content-Type": "application/json", "Origin": origin}, method="POST")
token = json.loads(op.open(req, timeout=10).read().decode())["data"]["accessToken"]
print("login OK, token len", len(token))

for ep in ("demands", "achievements"):
    req = urllib.request.Request(
        f"http://43.138.138.200:8076/api/tech-transfer/v1/{ep}?page=1&pageSize=10",
        headers={"Authorization": f"Bearer {token}", "Origin": origin})
    d = json.loads(op.open(req, timeout=10).read().decode())["data"]
    first = d["list"][0]["title"] if d["list"] else None
    print(f"{ep}: total={d['total']}, first={first}")
