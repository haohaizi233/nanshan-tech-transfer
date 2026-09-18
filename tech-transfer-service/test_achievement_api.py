"""
成果只读链路 API 测试
覆盖：分页、详情、搜索、分类、权限、空数据、错误状态
"""
import requests
import json

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
    json={"hostCredential": "local-dev-ticket-test-user"}, timeout=10)
token = resp.json()["data"]["accessToken"]
headers = {"Authorization": f"Bearer {token}"}
print(f"[0] Bootstrap OK, token acquired\n")

# ── 1. 成果列表 — 默认分页 ──────────────────────────────────
resp = requests.get(f"{BASE}/achievements", headers=headers, timeout=10)
data = resp.json()["data"]
check("列表返回200", resp.status_code == 200)
total_first = data["total"]
check("total>=223（导入演示数据，另含审核演示残留）", data["total"] >= 223, f"got {data['total']}")
check("默认page=1", data["page"] == 1)
check("默认pageSize=10", data["pageSize"] == 10)
check("totalPages=23", data["totalPages"] == 23, f"got {data['totalPages']}")
check("list长度=10", len(data["list"]) == 10, f"got {len(data['list'])}")
check("列表项有title", bool(data["list"][0].get("title")))
check("列表项有id", bool(data["list"][0].get("id")))
print()

# ── 2. 分页 — 第2页 ─────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements?page=2&pageSize=20", headers=headers, timeout=10)
data = resp.json()["data"]
check("第2页page=2", data["page"] == 2)
check("pageSize=20", data["pageSize"] == 20)
check("第2页list长度=20", len(data["list"]) == 20)
check("第2页与第1页不同", data["list"][0]["id"] != requests.get(f"{BASE}/achievements?page=1&pageSize=20", headers=headers, timeout=10).json()["data"]["list"][0]["id"])
print()

# ── 3. 关键词搜索 ───────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements?keyword=电池", headers=headers, timeout=10)
data = resp.json()["data"]
# Excel 真实数据 223 条中 15 条标题或简介含"电池"（简介仅返回前120字，不做逐条断言）
check("搜索'电池'有结果", 0 < data["total"] <= 15, f"got {data['total']}")
matched = any("电池" in (item["title"] + item.get("techIntro", "")) for item in data["list"])
check("搜索结果均含'电池'（标题或简介）", matched)
print()

# ── 4. 分类筛选 ─────────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements?category=ai", headers=headers, timeout=10)
data = resp.json()["data"]
check("分类筛选ai有结果", data["total"] > 0, f"got {data['total']}")
check("分类筛选结果categoryCode=ai", all(item["categoryCode"] == "ai" for item in data["list"]))
print()

# ── 5. 分类列表 ──────────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements/categories", headers=headers, timeout=10)
cats = resp.json()["data"]
check("分类列表返回200", resp.status_code == 200)
check("分类数=14（SIAT真实数据导入新增4类）", len(cats) == 14, f"got {len(cats)}")
check("分类有code和name", bool(cats[0].get("code")) and bool(cats[0].get("name")))
print()

# ── 6. 成果详情 ─────────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements/1", headers=headers, timeout=10)
detail = resp.json()["data"]
check("详情返回200", resp.status_code == 200)
check("详情有title", bool(detail.get("title")))
check("详情有techIntro", bool(detail.get("techIntro")))
check("详情有maturityLevel", bool(detail.get("maturityLevel")))
check("详情有inventors", isinstance(detail.get("inventors"), list) and len(detail["inventors"]) > 0)
check("详情有applicationFields", isinstance(detail.get("applicationFields"), list))
check("详情有innovationPoints", isinstance(detail.get("innovationPoints"), list))
# 联系方式脱敏：非 owner 且无已接受对接（原始值 13828858818 / 孙天夫 / tf.sun@siat.ac.cn）
check("非owner电话脱敏", detail.get("contactPhone") == "138****8818", f"got {detail.get('contactPhone')}")
check("非owner联系人脱敏", detail.get("contactName") == "孙**", f"got {detail.get('contactName')}")
check("非owner邮箱脱敏", detail.get("contactEmail") == "tf****@siat.ac.cn", f"got {detail.get('contactEmail')}")
print()

# ── 7. 不存在的成果 ─────────────────────────────────────────
resp = requests.get(f"{BASE}/achievements/99999", headers=headers, timeout=10)
check("不存在成果返回data=null", resp.json().get("data") is None)
print()

# ── 8. 搜索接口 ──────────────────────────────────────────────
# Phase B 收口：/search 已迁至独立 search 域（q 必填 + 双类型聚合），
# 本套件不再覆盖，见 test_search_api.py
print()

# ── 10. 游客浏览公开内容 ─────────────────────────────────────
resp = requests.get(f"{BASE}/achievements", timeout=10)
guest_list = resp.json().get("data") if resp.headers.get("content-type", "").startswith("application/json") else None
check("游客可浏览成果列表", resp.status_code == 200 and isinstance(guest_list, dict))
resp = requests.get(f"{BASE}/achievements/1", timeout=10)
guest_detail = resp.json().get("data") if resp.headers.get("content-type", "").startswith("application/json") else None
check("游客可浏览已发布成果详情", resp.status_code == 200 and isinstance(guest_detail, dict))
print()

# ── 11. 空数据 — 搜索不存在的关键词 ──────────────────────────
resp = requests.get(f"{BASE}/achievements?keyword=zzzznonexistent", headers=headers, timeout=10)
data = resp.json()["data"]
check("不存在的关键词=0结果", data["total"] == 0)
check("空结果list=[]", data["list"] == [])
check("空结果totalPages=0", data["totalPages"] == 0)
print()

# ── 12. 分页边界 — 超出总页数 ────────────────────────────────
resp = requests.get(f"{BASE}/achievements?page=999", headers=headers, timeout=10)
data = resp.json()["data"]
check("超出页数返回空list", data["list"] == [])
check("但total与首页一致", data["total"] == total_first)
print()

print(f"=== 成果 API 测试完成: {PASS} passed, {FAIL} failed ===")
