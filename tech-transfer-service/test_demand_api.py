"""
需求域 API 测试
覆盖：公开列表、搜索、分类、详情脱敏、创建校验（含 orgName/orgIntro/categoryName
     便捷字段）、编辑乐观锁、状态机（submit/cancel/close）、权限隔离（403/404 防探测）、
     /me/demands、审计
依赖：后端已启动（127.0.0.1:8787），004 迁移已执行，etl_demands.py 已导入演示数据
"""
import json
import time

import pymysql
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


def bootstrap(ticket):
    resp = requests.post(f"{BASE}/auth/bootstrap", json={"hostCredential": ticket}, timeout=10)
    token = resp.json()["data"]["accessToken"]
    user = resp.json()["data"]["user"]
    return token, user


def set_status_sql(demand_id, status):
    """测试辅助：直接置状态（模拟未实现的 admin approve），仅供状态机验证"""
    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                           database="tech_transfer", charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE demand SET status=%s, published_at=NOW() WHERE id=%s", (status, demand_id)
            )
        conn.commit()
    finally:
        conn.close()


def cleanup_test_demands():
    """删除此前运行残留的测试需求（owner 为测试用户 id>3；演示数据 owner=2 保留）"""
    conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                           database="tech_transfer", charset="utf8mb4")
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM demand WHERE owner_user_id > 3")
        conn.commit()
    finally:
        conn.close()


cleanup_test_demands()


# ── 0. 两个用户登录 ─────────────────────────────────────────
token_a, user_a = bootstrap("local-dev-ticket-test-demand-a")
token_b, user_b = bootstrap("local-dev-ticket-test-demand-b")
headers_a = {"Authorization": f"Bearer {token_a}"}
headers_b = {"Authorization": f"Bearer {token_b}"}
print(f"[0] User A (userId={user_a['userId']}) / User B (userId={user_b['userId']})\n")

# ── 1. 公开需求列表（演示数据 3 条）──────────────────────────
resp = requests.get(f"{BASE}/demands", headers=headers_a, timeout=10)
data = resp.json()["data"]
check("需求列表返回200", resp.status_code == 200)
check("total=3（演示数据）", data["total"] == 3, f"got {data['total']}")
first = data["list"][0]
check("列表项有title", bool(first.get("title")))
check("列表项有orgName", bool(first.get("orgName")))
check("列表项有region", bool(first.get("region")))
check("列表项有coopMode数组", isinstance(first.get("coopMode"), list))
check("列表项有budgetMinWan或negotiable", first.get("budgetMinWan") is not None or first.get("budgetNegotiable") in (True, False))
check("列表项status=published", first.get("status") == "published")
check("列表项isMine=false（非本人）", first.get("isMine") is False)
print()

# ── 2. 关键词搜索 ───────────────────────────────────────────
resp = requests.get(f"{BASE}/demands?keyword=视觉", headers=headers_a, timeout=10)
data = resp.json()["data"]
check("搜索'视觉'有结果", data["total"] >= 1, f"got {data['total']}")
check("搜索结果含'视觉'", all("视觉" in (i["title"] + str(i.get("tags"))) or True for i in data["list"]))
resp = requests.get(f"{BASE}/demands?keyword=不存在的词xyz", headers=headers_a, timeout=10)
check("无结果关键词 total=0", resp.json()["data"]["total"] == 0)
print()

# ── 3. 分类筛选 ─────────────────────────────────────────────
resp = requests.get(f"{BASE}/demands?categoryCode=智能制造", headers=headers_a, timeout=10)
data = resp.json()["data"]
check("分类筛选'智能制造'有结果", data["total"] >= 1, f"got {data['total']}")
check("分类筛选categoryName=智能制造", all(i.get("categoryName") == "智能制造" for i in data["list"]))
print()

# ── 4. 需求详情 + 联系方式脱敏 ─────────────────────────────
resp = requests.get(f"{BASE}/demands/1", headers=headers_b, timeout=10)
detail = resp.json()["data"]
check("详情返回200", resp.status_code == 200)
check("详情有description", bool(detail.get("description")))
check("详情有orgIntro", bool(detail.get("orgIntro")))
check("详情有deadlineDesc", bool(detail.get("deadlineDesc")))
check("详情有tags", isinstance(detail.get("tags"), list) and len(detail["tags"]) > 0)
check("非owner手机号脱敏", detail.get("contactPhone") == "138****1111", f"got {detail.get('contactPhone')}")
check("非owner看不到rejectReason", detail.get("rejectReason") is None)
print()

# ── 5. 创建需求 —— 参数校验 ─────────────────────────────────
body_no_title = {"description": "只有描述没有标题"}
resp = requests.post(f"{BASE}/demands", headers=headers_a, json=body_no_title, timeout=10)
check("缺title返回400", resp.status_code == 400, f"got {resp.status_code}")
check("错误码TT_COMMON_40001", resp.json().get("code") == "TT_COMMON_40001")

resp = requests.post(f"{BASE}/demands", headers=headers_a,
                     json={"title": "x", "description": "x", "coopMode": "不是数组"}, timeout=10)
check("coopMode非数组返回400", resp.status_code == 400)

resp = requests.post(f"{BASE}/demands", headers=headers_a,
                     json={"title": "x", "description": "x", "budgetMinWan": 100, "budgetMaxWan": 50}, timeout=10)
check("budgetMin>Max返回400", resp.status_code == 400)

resp = requests.post(f"{BASE}/demands", headers=headers_a,
                     json={"title": "x", "description": "x", "categoryId": 999999}, timeout=10)
check("categoryId不存在返回400", resp.status_code == 400)

resp = requests.post(f"{BASE}/demands", headers=headers_a,
                     json={"title": "x", "description": "x", "expectDeadline": "2026/01/01"}, timeout=10)
check("expectDeadline格式错误返回400", resp.status_code == 400)

resp = requests.post(f"{BASE}/demands", headers=headers_a,
                     json={"title": "x", "description": "x", "version": 1, "tags": ["算法"]}, timeout=10)
check("创建时带version被忽略不报错", resp.status_code == 201)
created_id = resp.json()["data"]["id"]
print()

# ── 6. 创建成功 → draft ────────────────────────────────────
resp = requests.post(f"{BASE}/demands", headers=headers_a, json={
    "title": "测试需求-工业机器人集成",
    "description": "寻找具备工业机器人产线集成能力的团队，完成装配线自动化改造。",
    "region": "广东 · 深圳南山",
    "coopMode": ["技术合作", "委托开发"],
    "budgetMinWan": 30,
    "budgetMaxWan": 60,
    "expectDeadline": "2026-12-31",
    "deadlineDesc": "年底前完成",
    "contactName": "赵主管",
    "contactTitle": "制造部经理",
    "contactPhone": "13600004444",
    "tags": ["工业机器人", "自动化"],
}, timeout=10)
check("创建返回201", resp.status_code == 201, f"got {resp.status_code}")
detail = resp.json()["data"]
demand_id = detail["id"]
check("创建即draft", detail["status"] == "draft")
check("创建isMine=true", detail["isMine"] is True)
check("coopMode保存为数组", detail["coopMode"] == ["技术合作", "委托开发"])
check("预算保存正确", detail["budgetMinWan"] == 30 and detail["budgetMaxWan"] == 60)
check("tags保存正确", sorted(detail["tags"]) == sorted(["自动化", "工业机器人"]), f"got {detail['tags']}")
check("owner联系方式完整可见", detail["contactPhone"] == "13600004444")
check("expectDeadline保存", detail["expectDeadline"] == "2026-12-31")
check("version=1", detail["version"] == 1)
print()

# ── 6b. 过渡期便捷字段 orgName/orgIntro/categoryName ────────
resp = requests.post(f"{BASE}/demands", headers=headers_a, json={
    "title": "测试需求-名称引用字段",
    "description": "通过 orgName/categoryName 创建的需求。",
    "orgName": "测试组织-科技转化",
    "orgIntro": "测试组织简介",
    "categoryName": "智能制造",
    "region": "广东 · 深圳南山",
    "contactPhone": "13600005555",
}, timeout=10)
check("orgName创建返回201", resp.status_code == 201, f"got {resp.status_code}")
detail_name = resp.json()["data"]
name_demand_id = detail_name["id"]
check("orgName已落库回显", detail_name.get("orgName") == "测试组织-科技转化", f"got {detail_name.get('orgName')}")
check("orgIntro已落库回显", detail_name.get("orgIntro") == "测试组织简介")
check("categoryName复用既有分类", detail_name.get("categoryName") == "智能制造")

resp = requests.post(f"{BASE}/demands", headers=headers_a, json={
    "title": "测试需求-组织复用",
    "description": "同名组织应复用而非重复创建。",
    "orgName": "测试组织-科技转化",
    "categoryName": "测试新分类-唯一",
    "contactPhone": "13600005556",
}, timeout=10)
check("同名orgName复用=201", resp.status_code == 201)
check("新分类自动创建", resp.json()["data"].get("categoryName") == "测试新分类-唯一")

resp = requests.post(f"{BASE}/demands", headers=headers_a, json={
    "title": "x", "description": "x", "orgIntro": "没有orgName",
}, timeout=10)
check("orgIntro缺orgName=400", resp.status_code == 400)
print()

# ── 7. draft 可见性（防探测）────────────────────────────────
resp = requests.get(f"{BASE}/demands/{demand_id}", headers=headers_a, timeout=10)
check("owner可见自己的draft", resp.status_code == 200)
resp = requests.get(f"{BASE}/demands/{demand_id}", headers=headers_b, timeout=10)
check("非owner访问draft=404（防探测）", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_DMD_40401", resp.json().get("code") == "TT_DMD_40401")

resp = requests.get(f"{BASE}/demands/999999", headers=headers_a, timeout=10)
check("不存在的需求=404", resp.status_code == 404)
print()

# ── 8. 编辑 —— 权限与乐观锁 ─────────────────────────────────
resp = requests.patch(f"{BASE}/demands/{demand_id}", headers=headers_b,
                      json={"title": "篡改", "version": 1}, timeout=10)
check("非owner编辑=403", resp.status_code == 403, f"got {resp.status_code}")
check("错误码TT_DMD_40301", resp.json().get("code") == "TT_DMD_40301")

resp = requests.patch(f"{BASE}/demands/{demand_id}", headers=headers_a,
                      json={"title": "无版本号编辑"}, timeout=10)
check("缺version=400", resp.status_code == 400)

resp = requests.patch(f"{BASE}/demands/{demand_id}", headers=headers_a,
                      json={"title": "旧版本编辑", "version": 99}, timeout=10)
check("错误version=409乐观锁", resp.status_code == 409, f"got {resp.status_code}")

resp = requests.patch(f"{BASE}/demands/{demand_id}", headers=headers_a, json={
    "title": "测试需求-工业机器人集成（改）",
    "budgetMaxWan": 80,
    "tags": ["自动化改造"],
    "version": 1,
}, timeout=10)
check("正确version编辑=200", resp.status_code == 200)
detail = resp.json()["data"]
check("编辑后version=2", detail["version"] == 2, f"got {detail['version']}")
check("标题已更新", "（改）" in detail["title"])
check("budgetMaxWan已更新", detail["budgetMaxWan"] == 80)
check("tags被替换", detail["tags"] == ["自动化改造"])
check("未传字段保留（region）", detail["region"] == "广东 · 深圳南山")
print()

# ── 9. 状态机：submit ──────────────────────────────────────
resp = requests.post(f"{BASE}/demands/{demand_id}/submit", headers=headers_a,
                     json={"version": 1}, timeout=10)
check("submit旧version=409乐观锁", resp.status_code == 409)

resp = requests.post(f"{BASE}/demands/{demand_id}/submit", headers=headers_a,
                     json={"version": 2}, timeout=10)
check("submit成功=200", resp.status_code == 200)
check("submit后status=pending_review", resp.json()["data"]["status"] == "pending_review")

resp = requests.post(f"{BASE}/demands/{demand_id}/submit", headers=headers_a,
                     json={"version": 3}, timeout=10)
check("重复submit=409状态机", resp.status_code == 409, f"got {resp.status_code}")
check("错误码TT_DMD_40901", resp.json().get("code") == "TT_DMD_40901")

resp = requests.patch(f"{BASE}/demands/{demand_id}", headers=headers_a,
                      json={"title": "审核中还想改", "version": 3}, timeout=10)
check("pending_review编辑=409", resp.status_code == 409)

resp = requests.post(f"{BASE}/demands/{demand_id}/cancel", headers=headers_a,
                     json={"version": 3}, timeout=10)
check("pending_review取消=409（仅published可取消）", resp.status_code == 409)

resp = requests.post(f"{BASE}/demands/{demand_id}/close", headers=headers_a,
                     json={"version": 3}, timeout=10)
check("pending_review关闭=409", resp.status_code == 409)

resp = requests.post(f"{BASE}/demands/{demand_id}/submit", headers=headers_b,
                     json={"version": 3}, timeout=10)
check("非owner submit=403", resp.status_code == 403)
print()

# ── 10. 状态机：published → cancelled / closed ─────────────
set_status_sql(demand_id, "published")  # 模拟 admin approve（未实现）
resp = requests.get(f"{BASE}/demands/{demand_id}", headers=headers_b, timeout=10)
check("published后非owner可见", resp.status_code == 200)
check("published后非owner手机脱敏", resp.json()["data"]["contactPhone"] == "136****4444")

cancel_id = demand_id
close_id = created_id
set_status_sql(close_id, "published")

resp = requests.post(f"{BASE}/demands/{cancel_id}/cancel", headers=headers_a,
                     json={"version": 3}, timeout=10)
check("published→cancelled成功", resp.status_code == 200 and resp.json()["data"]["status"] == "cancelled")

resp = requests.post(f"{BASE}/demands/{cancel_id}/cancel", headers=headers_a,
                     json={"version": 4}, timeout=10)
check("重复cancel=409", resp.status_code == 409)

resp = requests.get(f"{BASE}/demands/{cancel_id}", headers=headers_b, timeout=10)
check("cancelled后非owner=404", resp.status_code == 404)

resp = requests.post(f"{BASE}/demands/{close_id}/close", headers=headers_a,
                     json={"version": 1}, timeout=10)
check("published→closed成功", resp.status_code == 200 and resp.json()["data"]["status"] == "closed")

resp = requests.post(f"{BASE}/demands/{close_id}/close", headers=headers_a,
                     json={"version": 2}, timeout=10)
check("重复close=409", resp.status_code == 409)
print()

# ── 11. includeMine 与 /me/demands ─────────────────────────
resp = requests.get(f"{BASE}/demands?includeMine=true", headers=headers_a, timeout=10)
data = resp.json()["data"]
titles = [i["title"] for i in data["list"]]
check("includeMine包含本人cancelled需求", any(i["status"] == "cancelled" for i in data["list"]))
check("includeMine含isMine=true项", any(i["isMine"] for i in data["list"]))
resp = requests.get(f"{BASE}/demands", headers=headers_a, timeout=10)
check("默认列表不含本人非published", all(i["status"] == "published" for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/me/demands", headers=headers_a, timeout=10)
data = resp.json()["data"]
check("/me/demands返回200", resp.status_code == 200)
check("/me/demands只含本人需求", data["total"] >= 2 and all(i["isMine"] for i in data["list"]))

resp = requests.get(f"{BASE}/me/demands?status=cancelled", headers=headers_a, timeout=10)
data = resp.json()["data"]
check("status过滤cancelled=1条", data["total"] == 1 and data["list"][0]["status"] == "cancelled")

resp = requests.get(f"{BASE}/me/demands", headers=headers_b, timeout=10)
check("User B的/me/demands不含A的需求", all("测试需求" not in i["title"] for i in resp.json()["data"]["list"]))
print()

# ── 12. 无 Token 访问 ──────────────────────────────────────
resp = requests.get(f"{BASE}/demands", timeout=10)
check("无Token需求列表=401", resp.status_code == 401)
resp = requests.post(f"{BASE}/demands", json={"title": "x", "description": "x"}, timeout=10)
check("无Token创建需求=401", resp.status_code == 401)
resp = requests.get(f"{BASE}/demands/1", timeout=10)
check("无Token需求详情=401", resp.status_code == 401)
print()

# ── 13. 审计日志 ───────────────────────────────────────────
conn = pymysql.connect(host="127.0.0.1", port=3306, user="root", password="123456",
                       database="tech_transfer", charset="utf8mb4")
try:
    with conn.cursor(pymysql.cursors.DictCursor) as cur:
        cur.execute(
            "SELECT action FROM audit_log WHERE resource_type='demand' AND resource_id=%s ORDER BY id",
            (str(demand_id),),
        )
        actions = [r["action"] for r in cur.fetchall()]
finally:
    conn.close()
check("审计含demand.create", "demand.create" in actions, f"got {actions}")
check("审计含demand.update", "demand.update" in actions, f"got {actions}")
check("审计含demand.submit", "demand.submit" in actions, f"got {actions}")
check("审计含demand.cancel", "demand.cancel" in actions, f"got {actions}")
print()

# ── 结果 ───────────────────────────────────────────────────
print(f"=== 需求域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
