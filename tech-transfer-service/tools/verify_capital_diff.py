"""P0-1 diff 验证：legacy 三接口（现走 institution 表）与 MySQL 基线响应逐字段比对。

基线：legacy_capital_baseline.json（tools_baseline_capture.py 于 MySQL 版捕获）
忽略 requestId（每次请求必然不同）。任何字段/顺序差异都算 FAIL。
"""
import json
import sys
import urllib.request
from pathlib import Path

# 本机回环请求必须绕过系统代理（Clash 等会拦截 127.0.0.1）
_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))

BASE = "http://127.0.0.1:8787"
HERE = Path(__file__).resolve().parent.parent
CASES = json.load(open(HERE / "legacy_capital_baseline.json", encoding="utf-8"))

IGNORED_KEYS = {"requestId"}


def normalize(body):
    if isinstance(body, dict):
        return {k: normalize(v) for k, v in body.items() if k not in IGNORED_KEYS}
    if isinstance(body, list):
        return [normalize(v) for v in body]
    return body


def diff(a, b, path, out):
    if isinstance(a, dict) and isinstance(b, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a:
                out.append(f"{path}.{k}: 新增字段（基线无）={a[k]!r:.200}")
            elif k not in b:
                out.append(f"{path}.{k}: 基线有、现在缺失={b[k]!r:.200}")
            else:
                diff(a[k], b[k], f"{path}.{k}", out)
    elif isinstance(a, list) and isinstance(b, list):
        if len(a) != len(b):
            out.append(f"{path}: 列表长度 基线={len(b)} 现在={len(a)}")
        for i, (x, y) in enumerate(zip(a, b)):
            diff(x, y, f"{path}[{i}]", out)
    elif a != b:
        out.append(f"{path}: 基线={b!r:.200} -> 现在={a!r:.200}")


total_cases = len(CASES)
failed = 0
for name, case in sorted(CASES.items()):
    path = case["body"].get("_path") or None
    url = BASE + {
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
    }[name]
    with _OPENER.open(url, timeout=10) as resp:
        current = {"status": resp.status, "body": json.loads(resp.read().decode("utf-8"))}
    print(f"[GET ] {name} {url}")

    diffs = []
    diff(normalize(current), normalize(case), name, diffs)
    if diffs:
        failed += 1
        print(f"[DIFF] {name} ({len(diffs)} 处差异):")
        for d in diffs[:10]:
            print(f"    {d}")
    else:
        print(f"[ZERO-DIFF] {name}")

print()
if failed:
    print(f"=== diff 验证失败: {failed}/{total_cases} 个场景有差异 ===")
    sys.exit(1)
print(f"=== diff 验证通过: {total_cases}/{total_cases} 场景零差异 ===")
