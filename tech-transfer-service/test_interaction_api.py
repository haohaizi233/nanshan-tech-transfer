"""
交互域 API 测试（favorite + cooperation）
覆盖：
  收藏：PUT/DELETE 幂等、列表内嵌摘要、目标校验（404/400）、可见性
  对接：创建（自对接 400 / 活跃重复 409 / 目标未发布 404）、详情防探测（404）、
       角色权限（403）、状态机 accept/reject/confirm/cancel/complete + 乐观锁冲突、
       accept 副作用（同目标其他 pending 自动拒绝）、confirm 副作用（需求→matched）、
       终态后重新发起、事件时间线、/me/cooperations 视角过滤
依赖：后端已启动（127.0.0.1:8787），005 迁移已执行，etl_demands.py 演示数据在库
"""
import os

# 该脚本包含历史遗留的清理 SQL，默认永久停用，防止误删开发数据。
# 需要重建为隔离测试库后，才允许显式移除此保护。
if os.environ.get("RUN_UNSAFE_INTERACTION_TEST") != "1":
    print("[DISABLED] test_interaction_api.py 已停用：该脚本会清理开发库数据，禁止直接运行。")
    raise SystemExit(2)

import psycopg2
import psycopg2.extras
import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
DB = dict(host="127.0.0.1", port=5432, user="postgres", password="postgres123",
          dbname="tech_transfer")
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


def db_exec(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
    finally:
        conn.close()


def db_query_one(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def cleanup():
    """删除测试用户(userId>5)的意向/事件/收藏/需求；演示数据(owner 1-5)保留"""
    db_exec("DELETE FROM cooperation_intent WHERE initiator_user_id > 5 OR target_owner_user_id > 5")
    db_exec("DELETE FROM favorite WHERE user_id > 5")
    db_exec("DELETE FROM demand WHERE owner_user_id > 5")


def make_published_demand(token, title):
    """B 创建需求并直置 published（模拟未实现的 admin approve）"""
    resp = requests.post(f"{BASE}/demands", headers=token, json={
        "title": title, "description": "对接测试用需求", "orgName": "测试组织-对接",
        "contactPhone": "13600007777", "contactName": "测试联系人",
    }, timeout=10)
    demand_id = resp.json()["data"]["id"]
    db_exec("UPDATE demand SET status='published', published_at=NOW() WHERE id=%s", (demand_id,))
    return demand_id


cleanup()

# ── 0. 用户：A/B/C/D ─────────────────────────────────────────
token_a, user_a = bootstrap("local-dev-ticket-test-coop-a")
token_b, user_b = bootstrap("local-dev-ticket-test-coop-b")
token_c, user_c = bootstrap("local-dev-ticket-test-coop-c")
token_d, user_d = bootstrap("local-dev-ticket-test-coop-d")
h_a = {"Authorization": f"Bearer {token_a}"}
h_b = {"Authorization": f"Bearer {token_b}"}
h_c = {"Authorization": f"Bearer {token_c}"}
h_d = {"Authorization": f"Bearer {token_d}"}
print(f"[0] A={user_a['userId']} B={user_b['userId']} C={user_c['userId']} D={user_d['userId']}\n")

# B 发布三条测试需求
d1 = make_published_demand(h_b, "测试需求-对接主流程")
d2 = make_published_demand(h_b, "测试需求-拒绝流程")
d3 = make_published_demand(h_b, "测试需求-取消流程")
ach = db_query_one(
    "SELECT id FROM achievement WHERE status='published' AND deleted_at IS NULL ORDER BY id LIMIT 1"
)

# ═════════════════════════════════════════════════════════════
print("[1] 收藏：PUT/DELETE 幂等 + 列表")
# ═════════════════════════════════════════════════════════════
resp = requests.put(f"{BASE}/favorites/demand/{d1}", headers=h_a, timeout=10)
check("PUT收藏返回200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:100]}")
fav = resp.json()["data"]
check("返回id和favoritedAt", fav.get("id") and fav.get("favoritedAt"))

resp2 = requests.put(f"{BASE}/favorites/demand/{d1}", headers=h_a, timeout=10)
check("重复PUT幂等(同id)", resp2.json()["data"]["id"] == fav["id"])

resp = requests.get(f"{BASE}/me/favorites?targetType=demand", headers=h_a, timeout=10)
data = resp.json()["data"]
check("收藏列表200", resp.status_code == 200)
check("total=1", data["total"] == 1, f"got {data['total']}")
item = data["list"][0]
check("列表项含targetId", item["targetId"] == d1)
check("列表项含targetSummary.title", item.get("targetSummary", {}).get("title") == "测试需求-对接主流程")
check("列表项含targetSummary.status", item.get("targetSummary", {}).get("status") == "published")

resp = requests.get(f"{BASE}/me/favorites", headers=h_a, timeout=10)
check("缺targetType返回400", resp.status_code == 400 and resp.json()["code"] == "TT_COMMON_40001")

resp = requests.put(f"{BASE}/favorites/demand/99999999", headers=h_a, timeout=10)
check("收藏不存在目标404", resp.status_code == 404 and resp.json()["code"] == "TT_FAV_40401")

resp = requests.put(f"{BASE}/favorites/video/1", headers=h_a, timeout=10)
check("非法targetType返回400", resp.status_code == 400)

resp = requests.put(f"{BASE}/favorites/demand/{d1}", timeout=10)
check("无Token收藏401", resp.status_code == 401)

if ach:
    resp = requests.put(f"{BASE}/favorites/achievement/{ach['id']}", headers=h_a, timeout=10)
    check("收藏成果200", resp.status_code == 200, f"got {resp.status_code}")
    resp = requests.get(f"{BASE}/me/favorites?targetType=achievement", headers=h_a, timeout=10)
    check("成果收藏列表有记录", resp.json()["data"]["total"] == 1)

resp = requests.delete(f"{BASE}/favorites/demand/{d1}", headers=h_a, timeout=10)
check("DELETE取消收藏200", resp.status_code == 200)
resp = requests.delete(f"{BASE}/favorites/demand/{d1}", headers=h_a, timeout=10)
check("重复DELETE幂等200", resp.status_code == 200)
resp = requests.get(f"{BASE}/me/favorites?targetType=demand", headers=h_a, timeout=10)
check("取消后列表total=0", resp.json()["data"]["total"] == 0)
print()

# ═════════════════════════════════════════════════════════════
print("[2] 对接：创建 + 权限校验")
# ═════════════════════════════════════════════════════════════
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d1, "message": "希望对接，我方有相关技术储备",
}, timeout=10)
check("创建意向201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
intent1 = resp.json()["data"]
check("初始status=pending", intent1["status"] == "pending")
check("version=1", intent1["version"] == 1)
check("myRole=initiator", intent1.get("myRole") == "initiator")
check("targetOwner=B", intent1["targetOwnerUserId"] == user_b["userId"])
iid1 = intent1["id"]

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d1,
}, timeout=10)
check("活跃重复发起409", resp.status_code == 409 and resp.json()["code"] == "TT_COOP_40902",
      f"got {resp.status_code}")

resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "demand", "targetId": d1,
}, timeout=10)
check("对自己内容发起400", resp.status_code == 400 and resp.json()["code"] == "TT_COOP_40001")

resp = requests.post(f"{BASE}/cooperations", headers=h_c, json={
    "targetType": "demand", "targetId": d2,
}, timeout=10)
iid2 = resp.json()["data"]["id"]
check("C创建意向201", resp.status_code == 201)

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": 99999999,
}, timeout=10)
check("目标不存在404", resp.status_code == 404)

# 对接已发起（pending，未被接受）时联系方式仍脱敏
resp = requests.get(f"{BASE}/demands/{d1}", headers=h_a, timeout=10)
check("pending(未被接受)联系方式仍脱敏", resp.json()["data"]["contactPhone"] == "136****7777",
      f"got {resp.json().get('data', {}).get('contactPhone')}")

# 未发布目标（B 再建一条 draft）
resp = requests.post(f"{BASE}/demands", headers=h_b, json={
    "title": "测试需求-草稿不可对接", "description": "x",
}, timeout=10)
draft_id = resp.json()["data"]["id"]
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": draft_id,
}, timeout=10)
check("目标未发布404", resp.status_code == 404)
print()

# ═════════════════════════════════════════════════════════════
print("[3] 对接：详情 + 防探测 + 角色权限")
# ═════════════════════════════════════════════════════════════
resp = requests.get(f"{BASE}/cooperations/{iid1}", headers=h_b, timeout=10)
check("目标方查看详情200", resp.status_code == 200)
detail = resp.json()["data"]
check("myRole=target_owner", detail["myRole"] == "target_owner")
check("含counterpartDisplayName", "counterpartDisplayName" in detail)
check("含targetSummary", detail.get("targetSummary", {}).get("title") == "测试需求-对接主流程")

resp = requests.get(f"{BASE}/cooperations/{iid1}", headers=h_d, timeout=10)
check("非参与方404(防探测)", resp.status_code == 404 and resp.json()["code"] == "TT_COOP_40401")

resp = requests.get(f"{BASE}/cooperations/99999999", headers=h_a, timeout=10)
check("意向不存在404", resp.status_code == 404)

resp = requests.post(f"{BASE}/cooperations/{iid1}/accept", headers=h_a, json={"version": 1}, timeout=10)
check("发起方accept被拒403", resp.status_code == 403 and resp.json()["code"] == "TT_COOP_40301")

resp = requests.post(f"{BASE}/cooperations/{iid1}/accept", headers=h_d, json={"version": 1}, timeout=10)
check("非参与方accept=404", resp.status_code == 404)

# 无关用户（同未登录游客视角）查看联系方式一律脱敏
resp = requests.get(f"{BASE}/demands/{d1}", headers=h_d, timeout=10)
check("无关用户联系方式脱敏", resp.json()["data"]["contactPhone"] == "136****7777",
      f"got {resp.json().get('data', {}).get('contactPhone')}")
print()

# ═════════════════════════════════════════════════════════════
print("[4] 对接：主状态机 pending→accepted→confirmed→completed")
# ═════════════════════════════════════════════════════════════
# C 先对 d1 另发一条 pending（用于 accept 自动拒绝副作用验证）
resp = requests.post(f"{BASE}/cooperations", headers=h_c, json={
    "targetType": "demand", "targetId": d1,
}, timeout=10)
iid3 = resp.json()["data"]["id"]
check("C对d1另发意向201", resp.status_code == 201)

resp = requests.post(f"{BASE}/cooperations/{iid1}/accept", headers=h_b, json={"version": 1}, timeout=10)
check("B接受200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
check("status=accepted", resp.json()["data"]["status"] == "accepted")
check("acceptedAt有值", bool(resp.json()["data"]["acceptedAt"]))
check("version=2", resp.json()["data"]["version"] == 2)

# 对接被接受后，发起方 A 可见完整联系方式（脱敏解锁）
resp = requests.get(f"{BASE}/demands/{d1}", headers=h_a, timeout=10)
check("对接接受后发起方联系方式明文", resp.json()["data"]["contactPhone"] == "13600007777",
      f"got {resp.json().get('data', {}).get('contactPhone')}")
check("对接接受后发起方联系人明文", resp.json()["data"]["contactName"] == "测试联系人",
      f"got {resp.json().get('data', {}).get('contactName')}")

# accept 副作用：同目标（d1）其他 pending 意向自动拒绝
resp = requests.get(f"{BASE}/cooperations/{iid3}", headers=h_c, timeout=10)
check("同目标其他pending被自动拒绝", resp.json()["data"]["status"] == "rejected",
      f"got {resp.json()['data']['status']}")
resp = requests.get(f"{BASE}/cooperations/{iid3}/events", headers=h_c, timeout=10)
events = resp.json()["data"]["list"]
check("自动拒绝事件=auto_rejected", any(e["eventType"] == "auto_rejected" for e in events))
check("auto_rejected操作者=system", all(e["operatorRole"] == "system" for e in events if e["eventType"] == "auto_rejected"))

resp = requests.post(f"{BASE}/cooperations/{iid1}/accept", headers=h_b, json={"version": 2}, timeout=10)
check("重复accept=409状态冲突", resp.status_code == 409 and resp.json()["code"] == "TT_COOP_40901")

resp = requests.post(f"{BASE}/cooperations/{iid1}/confirm", headers=h_a, json={"version": 2}, timeout=10)
check("A确认200", resp.status_code == 200)
check("status=confirmed", resp.json()["data"]["status"] == "confirmed")

resp = requests.get(f"{BASE}/demands/{d1}", headers=h_b, timeout=10)
check("confirm副作用:需求→matched", resp.json()["data"]["status"] == "matched",
      f"got {resp.json().get('data', {}).get('status')}")
resp = requests.get(f"{BASE}/demands/{d1}", headers=h_a, timeout=10)
check("matched后已确认对接发起人可查看详情", resp.status_code == 200,
      f"got {resp.status_code} {resp.text[:150]}")

resp = requests.post(f"{BASE}/cooperations/{iid1}/cancel", headers=h_a, json={"version": 99}, timeout=10)
check("错误version乐观锁409", resp.status_code == 409 and resp.json()["code"] == "TT_COMMON_40902",
      f"got {resp.status_code} {resp.json().get('code')}")

resp = requests.post(f"{BASE}/cooperations/{iid1}/complete", headers=h_a, json={"version": 3}, timeout=10)
check("A完成200", resp.status_code == 200)
check("status=completed", resp.json()["data"]["status"] == "completed")

resp = requests.get(f"{BASE}/cooperations/{iid1}/events", headers=h_a, timeout=10)
events = resp.json()["data"]["list"]
seq = [e["eventType"] for e in events]
check("事件时间线完整有序", seq == ["created", "accepted", "confirmed", "completed"], f"got {seq}")
check("事件按时间正序", all(events[i]["id"] < events[i + 1]["id"] for i in range(len(events) - 1)))
print()

# ═════════════════════════════════════════════════════════════
print("[5] 对接：拒绝流程 + 终态后重新发起")
# ═════════════════════════════════════════════════════════════
resp = requests.post(f"{BASE}/cooperations/{iid2}/reject", headers=h_b, json={"version": 1}, timeout=10)
check("reject缺reason=400", resp.status_code == 400)

resp = requests.post(f"{BASE}/cooperations/{iid2}/reject", headers=h_b,
                     json={"version": 1, "reason": "方向不匹配"}, timeout=10)
check("B拒绝200", resp.status_code == 200)
check("status=rejected", resp.json()["data"]["status"] == "rejected")
check("closedAt有值", bool(resp.json()["data"]["closedAt"]))

resp = requests.post(f"{BASE}/cooperations", headers=h_c, json={
    "targetType": "demand", "targetId": d2,
}, timeout=10)
check("终态后重新发起201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:120]}")
iid4 = resp.json()["data"]["id"]

resp = requests.post(f"{BASE}/cooperations", headers=h_c, json={
    "targetType": "demand", "targetId": d2,
}, timeout=10)
check("重新发起后活跃重复仍409", resp.status_code == 409)

# 二次终态后再发起（验证 uk_coop_active 生成列设计：同键两条 rejected 不冲突）
resp = requests.post(f"{BASE}/cooperations/{iid4}/reject", headers=h_b,
                     json={"version": 1, "reason": "再次拒绝"}, timeout=10)
check("二次拒绝200", resp.status_code == 200)
resp = requests.post(f"{BASE}/cooperations", headers=h_c, json={
    "targetType": "demand", "targetId": d2,
}, timeout=10)
check("二次终态后三次发起201", resp.status_code == 201,
      f"got {resp.status_code} {resp.text[:150]}")
print()

# ═════════════════════════════════════════════════════════════
print("[6] 对接：取消流程 + /me/cooperations")
# ═════════════════════════════════════════════════════════════
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d3,
}, timeout=10)
iid5 = resp.json()["data"]["id"]
requests.post(f"{BASE}/cooperations/{iid5}/accept", headers=h_b, json={"version": 1}, timeout=10)
resp = requests.post(f"{BASE}/cooperations/{iid5}/cancel", headers=h_a,
                     json={"version": 2, "reason": "计划调整"}, timeout=10)
check("发起方取消200", resp.status_code == 200)
check("status=cancelled", resp.json()["data"]["status"] == "cancelled")

resp = requests.get(f"{BASE}/me/cooperations?role=initiator", headers=h_a, timeout=10)
data = resp.json()["data"]
ids = [i["id"] for i in data["list"]]
check("A发起列表含iid1/iid5", iid1 in ids and iid5 in ids)
check("A列表myRole=initiator", all(i["myRole"] == "initiator" for i in data["list"]))

resp = requests.get(f"{BASE}/me/cooperations?role=target", headers=h_b, timeout=10)
data = resp.json()["data"]
check("B收到列表含iid1", iid1 in [i["id"] for i in data["list"]])
check("B列表myRole=target_owner", all(i["myRole"] == "target_owner" for i in data["list"]))

resp = requests.get(f"{BASE}/me/cooperations?status=pending", headers=h_c, timeout=10)
data = resp.json()["data"]
check("C的pending过滤", all(i["status"] == "pending" for i in data["list"]) and len(data["list"]) >= 1)

resp = requests.get(f"{BASE}/me/cooperations?role=invalid", headers=h_a, timeout=10)
check("非法role=400", resp.status_code == 400)

resp = requests.get(f"{BASE}/me/cooperations", timeout=10)
check("无Token列表401", resp.status_code == 401)
print()

# ═════════════════════════════════════════════════════════════
print("[7] 审计落库")
# ═════════════════════════════════════════════════════════════
conn = psycopg2.connect(**DB)
try:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT DISTINCT action FROM audit_log WHERE action LIKE 'cooperation.%' OR action LIKE 'favorite.%' ORDER BY action"
        )
        actions = [r["action"] for r in cur.fetchall()]
finally:
    conn.close()
for expected in ("cooperation.create", "cooperation.accept", "cooperation.confirm",
                 "cooperation.complete", "cooperation.reject", "cooperation.cancel",
                 "favorite.add", "favorite.remove"):
    check(f"审计含{expected}", expected in actions)

print()
print(f"=== 交互域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
