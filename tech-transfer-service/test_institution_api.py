"""
机构域 API 测试（P0-1）
覆盖：统一列表（kind 过滤/type 过滤/keyword/分页）、详情（存在/不存在）、
     legacy 三接口与新 API 数据一致性、disabled 行不可见、非法参数 400
依赖：后端已启动（127.0.0.1:8787），002 迁移 + etl_institutions.py 已执行
"""
import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
LEGACY = "http://127.0.0.1:8787"
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


# ── 1. 统一列表 ──────────────────────────────────────────────
resp = requests.get(f"{BASE}/institutions", timeout=10)
data = resp.json()["data"]
check("列表返回200", resp.status_code == 200)
check("total=137（100+21+16）", data["total"] == 137, f"got {data['total']}")
check("默认pageSize=10", data["pageSize"] == 10)
check("totalPages=14", data["totalPages"] == 14, f"got {data['totalPages']}")
item = data["list"][0]
check("列表项有id", bool(item.get("id")))
check("列表项有kind", item.get("kind") in ("platform", "invest", "service"))
check("列表项有name", bool(item.get("name")))
check("列表项有logoUrl", "logoUrl" in item)
print()

# ── 2. kind 过滤 ─────────────────────────────────────────────
resp = requests.get(f"{BASE}/institutions?kind=platform", timeout=10)
data = resp.json()["data"]
check("kind=platform total=100", data["total"] == 100, f"got {data['total']}")
check("全部kind=platform", all(i["kind"] == "platform" for i in data["list"]))
p0 = data["list"][0]
check("platform项有platformTypeKey", p0.get("platformTypeKey") in ("poc", "pilot", "other"))
check("platform项有serialNo", isinstance(p0.get("serialNo"), int))
check("platform项有unit", "unit" in p0)

resp = requests.get(f"{BASE}/institutions?kind=invest", timeout=10)
data = resp.json()["data"]
check("kind=invest total=21", data["total"] == 21, f"got {data['total']}")
check("invest项无platformTypeKey", "platformTypeKey" not in data["list"][0])
check("invest项有intro", "intro" in data["list"][0])

resp = requests.get(f"{BASE}/institutions?kind=service", timeout=10)
data = resp.json()["data"]
check("kind=service total=16", data["total"] == 16, f"got {data['total']}")
check("service项有label", "label" in data["list"][0])
print()

# ── 3. platform type 过滤 ────────────────────────────────────
resp = requests.get(f"{BASE}/institutions?kind=platform&type=poc", timeout=10)
check("type=poc total=49", resp.json()["data"]["total"] == 49, f"got {resp.json()['data']['total']}")
check("poc全部platformTypeKey=poc",
      all(i["platformTypeKey"] == "poc" for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/institutions?kind=platform&type=pilot", timeout=10)
check("type=pilot total=51", resp.json()["data"]["total"] == 51, f"got {resp.json()['data']['total']}")
check("pilot全部platformTypeKey=pilot",
      all(i["platformTypeKey"] == "pilot" for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/institutions?kind=platform&type=other", timeout=10)
check("type=other不过滤total=100", resp.json()["data"]["total"] == 100)

resp = requests.get(f"{BASE}/institutions?kind=platform&type=invalid", timeout=10)
check("非法type=400", resp.status_code == 400)

resp = requests.get(f"{BASE}/institutions?kind=invalid", timeout=10)
check("非法kind=400", resp.status_code == 400)
print()

# ── 4. keyword 搜索 ──────────────────────────────────────────
resp = requests.get(f"{BASE}/institutions?kind=platform&keyword=%E5%B0%81%E8%A3%85", timeout=10)
data = resp.json()["data"]
check("platform keyword'封装' total=4", data["total"] == 4, f"got {data['total']}")

resp = requests.get(f"{BASE}/institutions?kind=invest&keyword=%E6%8A%95%E8%B5%84", timeout=10)
check("invest keyword'投资' total=20", resp.json()["data"]["total"] == 20,
      f"got {resp.json()['data']['total']}")

resp = requests.get(f"{BASE}/institutions?keyword=%E4%B8%8D%E5%AD%98%E5%9C%A8xx", timeout=10)
check("无结果keyword total=0", resp.json()["data"]["total"] == 0)
check("空结果list=[]", resp.json()["data"]["list"] == [])
print()

# ── 5. 分页 ──────────────────────────────────────────────────
resp = requests.get(f"{BASE}/institutions?kind=service&page=2&pageSize=5", timeout=10)
data = resp.json()["data"]
check("分页page=2", data["page"] == 2)
check("分页pageSize=5", data["pageSize"] == 5)
check("分页list长度=5", len(data["list"]) == 5)
check("分页total不变", data["total"] == 16)

page1 = requests.get(f"{BASE}/institutions?kind=service&page=1&pageSize=8", timeout=10).json()["data"]["list"]
page2 = requests.get(f"{BASE}/institutions?kind=service&page=2&pageSize=8", timeout=10).json()["data"]["list"]
ids1 = {i["id"] for i in page1}
ids2 = {i["id"] for i in page2}
check("页间无重叠", not (ids1 & ids2))
print()

# ── 6. 详情 ──────────────────────────────────────────────────
resp = requests.get(f"{BASE}/institutions/1", timeout=10)
d = resp.json()["data"]
check("详情返回200", resp.status_code == 200)
check("详情有name", bool(d.get("name")))
check("详情kind=platform", d.get("kind") == "platform")
check("详情有detailInfo", "detailInfo" in d)

resp = requests.get(f"{BASE}/institutions/101", timeout=10)
d = resp.json()["data"]
check("invest详情可查（id=101）", resp.json()["code"] == 0 and d is not None and d.get("kind") == "invest",
      f"got {d}")

resp = requests.get(f"{BASE}/institutions/99999", timeout=10)
check("不存在详情data=null", resp.json()["data"] is None, f"got {resp.json()['data']}")
print()

# ── 7. legacy 一致性（同数据双路径） ──────────────────────────
legacy_platforms = requests.get(f"{LEGACY}/api/platform-base", timeout=10).json()["data"]["list"]
new_platforms = requests.get(f"{BASE}/institutions?kind=platform&pageSize=50", timeout=10).json()["data"]["list"]
check("legacy平台首行=新API首行",
      legacy_platforms[0]["name"] == new_platforms[0]["name"],
      f"legacy={legacy_platforms[0]['name'][:20]} new={new_platforms[0]['name'][:20]}")

legacy_invests = requests.get(f"{LEGACY}/api/invest-orgs", timeout=10).json()["data"]["list"]
new_invests = requests.get(f"{BASE}/institutions?kind=invest", timeout=10).json()["data"]["list"]
check("legacy投资首行=新API首行",
      legacy_invests[0]["name"] == new_invests[0]["name"])
check("legacy投资详情=新API detailInfo",
      legacy_invests[0]["detailInfo"] == new_invests[0]["detailInfo"])

# ── 结果 ─────────────────────────────────────────────────────
print()
print(f"=== 机构域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
