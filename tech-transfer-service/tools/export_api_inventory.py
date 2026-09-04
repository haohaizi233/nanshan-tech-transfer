"""导出 8787 运行中服务的完整 API 清单（method path tag summary）"""
import json
import urllib.request

op = urllib.request.build_opener(urllib.request.ProxyHandler({}))
spec = json.load(op.open("http://127.0.0.1:8787/openapi.json", timeout=10))
rows = []
for p, item in sorted(spec["paths"].items()):
    for m, o in item.items():
        if m in ("get", "post", "put", "patch", "delete"):
            tag = (o.get("tags") or ["-"])[0]
            rows.append(f"{m.upper():7} {p:60} {tag:12} {o.get('summary','')}")
print("\n".join(rows))
print("TOTAL", len(rows))
