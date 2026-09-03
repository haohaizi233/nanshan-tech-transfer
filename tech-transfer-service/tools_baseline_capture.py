"""捕获 legacy 资本接口基线响应，供 Institution 统一改造前后 diff 验证。只读，不改数据。"""
import json
import urllib.request

BASE = "http://127.0.0.1:8787"
CASES = {
    "platform_base_default": "/api/platform-base",
    "platform_base_poc": "/api/platform-base?type=poc",
    "platform_base_pilot": "/api/platform-base?type=pilot",
    "platform_base_other": "/api/platform-base?type=other",
    "platform_base_p2": "/api/platform-base?page=2&pageSize=7",
    "platform_base_kw": "/api/platform-base?keyword=%E5%B0%81%E8%A3%85",
    "invest_orgs_default": "/api/invest-orgs",
    "invest_orgs_p2": "/api/invest-orgs?page=2&pageSize=5",
    "invest_orgs_kw": "/api/invest-orgs?keyword=%E6%8A%95%E8%B5%84",
    "service_orgs_default": "/api/service-orgs",
    "service_orgs_kw": "/api/service-orgs?keyword=%E5%92%A8%E8%AF%A2",
}
out = {}
for name, path in CASES.items():
    with urllib.request.urlopen(BASE + path, timeout=10) as resp:
        out[name] = {"status": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    n = len(out[name]["body"].get("data", {}).get("list", []))
    print(f"{name}: HTTP {out[name]['status']}, items={n}")

with open("legacy_capital_baseline.json", "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1, sort_keys=True)
print("saved -> legacy_capital_baseline.json")
