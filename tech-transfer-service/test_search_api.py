"""
统一搜索 API 测试（Phase B 收口）
覆盖：参数校验（q 必填/长度/type 枚举）、鉴权（无Token 401）、
     双类型聚合（all/achievement/demand 的响应形状稳定）、
     关键词命中（成果"电池"15 条量级、需求"需求"≥1）、
     分页、maturityLevel/categoryCode 过滤透传、空结果形状
依赖：后端已启动，演示数据已导入（成果≥223 published）
契约：GET /search?q=&type=achievement|demand|all 返回 {achievements:{...}, demands:{...}}
"""
import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
PASS = 0
FAIL = 0


def check(name, condition, detail=""):
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


# ── 0. 获取 token ──────────────────────────────────────────
resp = requests.post(f"{BASE}/auth/bootstrap",
    json={"hostCredential": "local-dev-ticket-test-search-user"}, timeout=10)
token = resp.json()["data"]["accessToken"]
headers = {"Authorization": f"Bearer {token}"}
print("[0] Bootstrap OK\n")

# ── 1. 参数校验 ──────────────────────────────────────────────
resp = requests.get(f"{BASE}/search", headers=headers, timeout=10)
check("缺q=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.get(f"{BASE}/search?q=", headers=headers, timeout=10)
check("空q=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.get(f"{BASE}/search?q=" + "a" * 65, headers=headers, timeout=10)
check("q超64字符=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.get(f"{BASE}/search?q=x&type=invalid", headers=headers, timeout=10)
check("非法type=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.get(f"{BASE}/search?q=x", timeout=10)
check("无Token=401", resp.status_code == 401)
print()

# ── 2. type=all 双类型聚合 ──────────────────────────────────
resp = requests.get(f"{BASE}/search?q=电池&type=all", headers=headers, timeout=10)
check("type=all返回200", resp.status_code == 200)
data = resp.json()["data"]
check("响应含achievements", "achievements" in data)
check("响应含demands", "demands" in data)
check("achievements有分页结构", all(k in data["achievements"] for k in ("total", "page", "pageSize", "totalPages", "list")))
check("demands有分页结构", all(k in data["demands"] for k in ("total", "page", "pageSize", "totalPages", "list")))
# Excel 真实数据 223 条中 15 条标题/简介/来源机构含"电池"
check("成果命中'电池'（1~15）", 0 < data["achievements"]["total"] <= 15, f"got {data['achievements']['total']}")
check("成果列表非空", len(data["achievements"]["list"]) > 0)
check("成果列表项有title", bool(data["achievements"]["list"][0].get("title")))
print()

# ── 3. type=achievement 单类型 ──────────────────────────────
resp = requests.get(f"{BASE}/search?q=电池&type=achievement", headers=headers, timeout=10)
data = resp.json()["data"]
check("type=achievement成果有结果", data["achievements"]["total"] > 0, f"got {data['achievements']['total']}")
check("type=achievement需求侧为空", data["demands"]["total"] == 0 and data["demands"]["list"] == [])
print()

# ── 4. type=demand 单类型 ──────────────────────────────────
resp = requests.get(f"{BASE}/search?q=需求&type=demand", headers=headers, timeout=10)
data = resp.json()["data"]
check("type=demand需求有结果（演示数据标题含'需求'）", data["demands"]["total"] >= 1, f"got {data['demands']['total']}")
check("需求列表项有title", bool(data["demands"]["list"][0].get("title")))
check("type=demand成果侧为空", data["achievements"]["total"] == 0 and data["achievements"]["list"] == [])
print()

# ── 5. 分页 ─────────────────────────────────────────────────
resp = requests.get(f"{BASE}/search?q=电池&type=achievement&page=2&pageSize=3", headers=headers, timeout=10)
data = resp.json()["data"]["achievements"]
check("分页page=2", data["page"] == 2, f"got {data['page']}")
check("分页pageSize=3", data["pageSize"] == 3, f"got {data['pageSize']}")
check("分页totalPages=5（15条/3每页）", data["totalPages"] == 5, f"got {data['totalPages']}")
check("分页list长度=3", len(data["list"]) == 3, f"got {len(data['list'])}")

resp = requests.get(f"{BASE}/search?q=电池&type=achievement&page=999", headers=headers, timeout=10)
data = resp.json()["data"]["achievements"]
check("超出页数返回空list", data["list"] == [])
print()

# ── 6. 空结果形状稳定 ────────────────────────────────────────
resp = requests.get(f"{BASE}/search?q=zzzznonexistent", headers=headers, timeout=10)
data = resp.json()["data"]
check("不存在关键词成果=0", data["achievements"]["total"] == 0)
check("不存在关键词需求=0", data["demands"]["total"] == 0)
check("空结果两侧list=[]", data["achievements"]["list"] == [] and data["demands"]["list"] == [])
check("空结果totalPages=0", data["achievements"]["totalPages"] == 0)
print()

# ── 7. maturityLevel 过滤透传 ────────────────────────────────
resp = requests.get(f"{BASE}/search?q=电池&type=achievement&maturityLevel=02_lab", headers=headers, timeout=10)
data = resp.json()["data"]["achievements"]
check("maturity过滤有结果", data["total"] > 0, f"got {data['total']}")
check("结果maturityLevel均为02_lab", all(item.get("maturityLevel") == "02_lab" for item in data["list"]))

resp = requests.get(f"{BASE}/search?q=电池&type=achievement&maturityLevel=zz_invalid", headers=headers, timeout=10)
data = resp.json()["data"]["achievements"]
check("无效maturity=0结果（不过滤出非法值）", data["total"] == 0, f"got {data['total']}")
print()

# ── 8. categoryCode 过滤透传 ────────────────────────────────
resp = requests.get(f"{BASE}/search?q=AI&type=achievement&categoryCode=ai", headers=headers, timeout=10)
data = resp.json()["data"]["achievements"]
check("categoryCode=ai有结果", data["total"] > 0, f"got {data['total']}")
check("结果categoryCode均为ai", all(item.get("categoryCode") == "ai" for item in data["list"]))
print()

# ── 结果 ─────────────────────────────────────────────────────
print(f"=== 统一搜索 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
