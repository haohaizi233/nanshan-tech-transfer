"""
Admin 域 API 测试（P0-3/P0-4）
覆盖：鉴权真校验（非 admin 403 TT_ADMIN_40301、无 Token 401）、
     成果审核队列（含提交人）、成果 approve/reject（状态机 + 乐观锁 + reason 必填 + 审计）、
     需求审核队列/approve/reject（同上 + published 副作用）、审计日志查询（过滤/分页）
依赖：后端已启动，005 种子已执行（dev-user-001 = admin）
"""
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


# admin = dev-user-001（种子）；普通用户 C
token_admin, user_admin = bootstrap("local-dev-ticket-dev-user-001")
token_c, user_c = bootstrap("local-dev-ticket-test-admin-c")
h_admin = {"Authorization": f"Bearer {token_admin}"}
h_c = {"Authorization": f"Bearer {token_c}"}
print(f"[0] admin={user_admin['userId']} C={user_c['userId']}\n")

# 清理上轮残留的待审测试需求（演示数据 owner<=3 保留）；
# 恢复上轮借用后被置 pending_review 未审完的演示成果
db_exec("DELETE FROM demand WHERE owner_user_id > 3 AND title LIKE 'admin审核%%'")
db_exec("UPDATE achievement SET status='published' WHERE status='pending_review' AND deleted_at IS NULL")

# C 建两个需求并提交（pending_review）
d1 = requests.post(f"{BASE}/demands", headers=h_c, json={
    "title": "admin审核-通过流程", "description": "x",
    "orgName": "测试组织-admin", "contactPhone": "13600008888", "contactName": "C",
}, timeout=10).json()["data"]["id"]
d2 = requests.post(f"{BASE}/demands", headers=h_c, json={
    "title": "admin审核-驳回流程", "description": "x",
    "contactPhone": "13600008888", "contactName": "C",
}, timeout=10).json()["data"]["id"]
for did in (d1, d2):
    v = requests.get(f"{BASE}/demands/{did}", headers=h_c, timeout=10).json()["data"]["version"]
    requests.post(f"{BASE}/demands/{did}/submit", headers=h_c, json={"version": v}, timeout=10)

# 成果置 pending_review（成果用户写接口未实现，直接 SQL 模拟，同既有测试做法）
db_exec(
    "UPDATE achievement SET status='pending_review', version=1 WHERE id = "
    "(SELECT id FROM achievement WHERE status='published' AND deleted_at IS NULL ORDER BY id LIMIT 1)"
)
a1 = None
conn = psycopg2.connect(**DB)
try:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT id, version FROM achievement WHERE status='pending_review' AND deleted_at IS NULL ORDER BY id LIMIT 1"
        )
        row = cur.fetchone()
        a1 = row["id"]
finally:
    conn.close()

# ── 1. 鉴权（真校验：user_role 查库） ─────────────────────────
resp = requests.get(f"{BASE}/admin/demands/review-queue", timeout=10)
check("无Token=401", resp.status_code == 401)

resp = requests.get(f"{BASE}/admin/demands/review-queue", headers=h_c, timeout=10)
check("普通用户=403", resp.status_code == 403, f"got {resp.status_code}")
check("错误码TT_ADMIN_40301", resp.json().get("code") == "TT_ADMIN_40301", resp.text[:100])

resp = requests.get(f"{BASE}/admin/demands/review-queue", headers=h_admin, timeout=10)
check("admin访问=200", resp.status_code == 200)
print()

# ── 2. 需求审核队列 ──────────────────────────────────────────
data = resp.json()["data"]
check("队列含2条待审需求", data["total"] == 2, f"got {data['total']}")
item = data["list"][0]
check("队列项有title", bool(item.get("title")))
check("队列项有提交人userNo", bool(item.get("submitterUserNo")))
check("队列项有version", isinstance(item.get("version"), int))
check("队列项有submittedAt", bool(item.get("submittedAt")))
print()

# ── 3. 需求 approve（状态机 + 乐观锁 + published 副作用） ────
v1 = requests.get(f"{BASE}/demands/{d1}", headers=h_c, timeout=10).json()["data"]["version"]
resp = requests.post(f"{BASE}/admin/demands/{d1}/approve", headers=h_admin, json={"version": v1}, timeout=10)
check("approve返回200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:100]}")
check("approve后status=published", resp.json()["data"]["status"] == "published")

detail = requests.get(f"{BASE}/demands/{d1}", headers=h_c, timeout=10).json()["data"]
check("published后公开可见", detail is not None and detail.get("status") == "published")
check("published_at已置", bool(detail.get("publishedAt")))

resp = requests.post(f"{BASE}/admin/demands/{d1}/approve", headers=h_admin, json={"version": v1 + 1}, timeout=10)
check("重复approve=409状态机", resp.status_code == 409, f"got {resp.status_code}")
check("错误码TT_DMD_40901", resp.json().get("code") == "TT_DMD_40901", resp.text[:100])

resp = requests.post(f"{BASE}/admin/demands/{d2}/approve", headers=h_admin, json={"version": 999}, timeout=10)
check("错误version=409乐观锁", resp.status_code == 409, f"got {resp.status_code}")
check("错误码TT_COMMON_40902", resp.json().get("code") == "TT_COMMON_40902", resp.text[:100])
print()

# ── 4. 需求 reject（reason 必填） ────────────────────────────
v2 = requests.get(f"{BASE}/demands/{d2}", headers=h_c, timeout=10).json()["data"]["version"]
resp = requests.post(f"{BASE}/admin/demands/{d2}/reject", headers=h_admin, json={"version": v2}, timeout=10)
check("reject缺reason=400", resp.status_code == 400, f"got {resp.status_code}")
check("错误码TT_ADMIN_40001", resp.json().get("code") == "TT_ADMIN_40001", resp.text[:100])

resp = requests.post(f"{BASE}/admin/demands/{d2}/reject", headers=h_admin,
                     json={"version": v2, "reason": "信息不完整"}, timeout=10)
check("reject带reason=200", resp.status_code == 200, f"got {resp.status_code}")
check("reject后status=rejected", resp.json()["data"]["status"] == "rejected")

d2_detail = requests.get(f"{BASE}/demands/{d2}", headers=h_c, timeout=10).json()["data"]
check("owner可见rejectReason", d2_detail.get("rejectReason") == "信息不完整")
print()

# ── 5. 成果审核队列 + approve ───────────────────────────────
resp = requests.get(f"{BASE}/admin/achievements/review-queue", headers=h_admin, timeout=10)
data = resp.json()["data"]
check("成果队列含1条", data["total"] == 1, f"got {data['total']}")
ach_item = data["list"][0]
check("成果队列项有categoryCode", ach_item.get("categoryCode") is not None)

resp = requests.post(f"{BASE}/admin/achievements/{a1}/approve", headers=h_admin,
                     json={"version": ach_item["version"]}, timeout=10)
check("成果approve=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
check("成果status=published", resp.json()["data"]["status"] == "published")
print()

# ── 6. 审计日志查询 ──────────────────────────────────────────
resp = requests.get(f"{BASE}/admin/audit-logs?targetType=demand&action=demand.approve", headers=h_admin, timeout=10)
data = resp.json()["data"]
check("审计查询200", resp.status_code == 200)
check("过滤targetType=demand有记录", data["total"] >= 1)
actions = {i["action"] for i in data["list"]}
check("审计含demand.approve", "demand.approve" in actions, f"got {actions}")

resp = requests.get(f"{BASE}/admin/audit-logs?targetType=demand", headers=h_admin, timeout=10)
data = resp.json()["data"]
all_actions = {i["action"] for i in data["list"]}
check("审计含demand.reject", "demand.reject" in all_actions, f"got {all_actions}")

resp = requests.get(f"{BASE}/admin/audit-logs", headers=h_c, timeout=10)
check("普通用户查审计=403", resp.status_code == 403)
print()

# ── 7. 队列复核（审核完成后清空） ────────────────────────────
resp = requests.get(f"{BASE}/admin/demands/review-queue", headers=h_admin, timeout=10)
check("审核后需求队列清空", resp.json()["data"]["total"] == 0, f"got {resp.json()['data']['total']}")
resp = requests.get(f"{BASE}/admin/achievements/review-queue", headers=h_admin, timeout=10)
check("审核后成果队列清空", resp.json()["data"]["total"] == 0)
print()


# ═════════════════════════════════════════════════════════════
# Release Closure（P0-1 ~ P0-4）：Dashboard / Institution /
# Cooperation（只读）/ Users（只读）
# ═════════════════════════════════════════════════════════════

def db_query(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


# ── 8. Dashboard summary（真实 COUNT，无假数据） ──────────────
resp = requests.get(f"{BASE}/admin/dashboard/summary", timeout=10)
check("Dashboard无Token=401", resp.status_code == 401)

resp = requests.get(f"{BASE}/admin/dashboard/summary", headers=h_c, timeout=10)
check("Dashboard普通用户=403", resp.status_code == 403, f"got {resp.status_code}")
check("Dashboard错误码TT_ADMIN_40301", resp.json().get("code") == "TT_ADMIN_40301", resp.text[:100])

resp = requests.get(f"{BASE}/admin/dashboard/summary", headers=h_admin, timeout=10)
check("Dashboard admin=200", resp.status_code == 200, resp.text[:150])
d = resp.json()["data"]
for f in ("users", "achievements", "demands", "cooperations",
          "pendingAchievements", "pendingDemands", "pendingTotal", "institutions"):
    check(f"字段{f}为int", isinstance(d.get(f), int), f"got {type(d.get(f))}")
check("pendingTotal=两项之和", d["pendingTotal"] == d["pendingAchievements"] + d["pendingDemands"])

sql_users = db_query("SELECT COUNT(*) FROM app_user WHERE status='active' AND deleted_at IS NULL")[0]
sql_dmds = db_query("SELECT COUNT(*) FROM demand WHERE deleted_at IS NULL")[0]
sql_coops = db_query("SELECT COUNT(*) FROM cooperation_intent")[0]
check("users与SQL一致", d["users"] == sql_users, f"api={d['users']} sql={sql_users}")
check("demands与SQL一致", d["demands"] == sql_dmds, f"api={d['demands']} sql={sql_dmds}")
check("cooperations与SQL一致", d["cooperations"] == sql_coops, f"api={d['cooperations']} sql={sql_coops}")
check("无趋势假字段", "trend" not in d and "growth" not in d)
print()

# ── 9. Institution 管理端（含公开可见性闭环） ─────────────────
RC_NAME = "RC闭环测试机构"
db_exec("DELETE FROM institution WHERE name LIKE 'RC闭环%%'")

resp = requests.get(f"{BASE}/admin/institutions", headers=h_c, timeout=10)
check("机构列表普通用户=403", resp.status_code == 403)
resp = requests.post(f"{BASE}/admin/institutions", headers=h_c, json={"kind": "invest", "name": RC_NAME}, timeout=10)
check("机构创建普通用户=403", resp.status_code == 403)

resp = requests.get(f"{BASE}/admin/institutions", headers=h_admin, timeout=10)
check("机构列表admin=200", resp.status_code == 200, resp.text[:150])
il = resp.json()["data"]
check("机构分页契约", all(k in il for k in ("total", "page", "pageSize", "totalPages", "list")))
check("机构列表默认全量含disabled", il["total"] >= 1)

resp = requests.get(f"{BASE}/admin/institutions?pageSize=2&page=2", headers=h_admin, timeout=10)
p2 = resp.json()["data"]
check("机构分页pageSize=2生效", len(p2["list"]) <= 2 and p2["pageSize"] == 2)
check("机构分页page回显", p2["page"] == 2)

resp = requests.get(f"{BASE}/admin/institutions?status=disabled", headers=h_admin, timeout=10)
check("status=disabled过滤可用", resp.status_code == 200 and resp.json()["data"]["total"] >= 0)

# create 201 + 闭环核心
resp = requests.post(f"{BASE}/admin/institutions", headers=h_admin, json={
    "kind": "invest", "name": RC_NAME, "intro": "闭环测试", "label": "RC",
}, timeout=10)
check("创建机构=201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
inst_id = resp.json()["data"]["id"]
check("创建默认status=active", resp.json()["data"]["status"] == "active")
check("创建返回camelCase字段", "detailInfo" in resp.json()["data"] and "logoFileId" in resp.json()["data"])

resp = requests.post(f"{BASE}/admin/institutions", headers=h_admin, json={"kind": "investment", "name": "x"}, timeout=10)
check("非法kind=400", resp.status_code == 400)
check("非法kind错误码TT_INST_40001", resp.json().get("code") == "TT_INST_40001", resp.text[:100])

resp = requests.post(f"{BASE}/admin/institutions", headers=h_admin, json={"kind": "invest"}, timeout=10)
check("缺name走RequestValidation=422(T008统一契约)", resp.status_code == 422
      and resp.json().get("code") == "TT_COMMON_42201", resp.text[:100])

resp = requests.get(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin, timeout=10)
check("管理端详情=200", resp.status_code == 200)
check("详情name一致", resp.json()["data"]["name"] == RC_NAME)

resp = requests.get(f"{BASE}/admin/institutions/99999999", headers=h_admin, timeout=10)
check("机构不存在=404", resp.status_code == 404)
check("机构不存在错误码TT_INST_40401", resp.json().get("code") == "TT_INST_40401", resp.text[:100])

# 闭环：创建即公开可见
resp = requests.get(f"{BASE}/institutions/{inst_id}", timeout=10)
check("闭环1:创建后public可见", resp.status_code == 200 and resp.json()["data"] is not None, resp.text[:100])

resp = requests.get(f"{BASE}/institutions?kind=invest&pageSize=50", timeout=10)
names = [i["name"] for i in resp.json()["data"]["list"]]
check("闭环1b:public列表含新机构", RC_NAME in names)

# offline → public 不可见、admin 可见
resp = requests.post(f"{BASE}/admin/institutions/{inst_id}/offline", headers=h_admin, timeout=10)
check("offline=200且status=disabled", resp.status_code == 200 and resp.json()["data"]["status"] == "disabled", resp.text[:120])

resp = requests.get(f"{BASE}/institutions/{inst_id}", timeout=10)
check("闭环2:offline后public不可见(data=null)", resp.json().get("data") is None, resp.text[:100])

resp = requests.get(f"{BASE}/institutions?kind=invest&pageSize=50", timeout=10)
names = [i["name"] for i in resp.json()["data"]["list"]]
check("闭环2b:public列表不含已下架机构", RC_NAME not in names)

resp = requests.get(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin, timeout=10)
check("闭环3:offline后admin仍可见disabled", resp.status_code == 200 and resp.json()["data"]["status"] == "disabled")

resp = requests.get(f"{BASE}/admin/institutions?status=disabled&keyword=RC闭环", headers=h_admin, timeout=10)
check("admin按disabled+keyword可检索", resp.json()["data"]["total"] == 1, resp.text[:150])

resp = requests.post(f"{BASE}/admin/institutions/{inst_id}/offline", headers=h_admin, timeout=10)
check("重复offline=409", resp.status_code == 409)
check("重复offline错误码TT_INST_40901", resp.json().get("code") == "TT_INST_40901", resp.text[:100])

# online → public 恢复可见
resp = requests.post(f"{BASE}/admin/institutions/{inst_id}/online", headers=h_admin, timeout=10)
check("online=200且status=active", resp.status_code == 200 and resp.json()["data"]["status"] == "active")

resp = requests.get(f"{BASE}/institutions/{inst_id}", timeout=10)
check("闭环4:online后public恢复可见", resp.json().get("data") is not None)

# PATCH 可编辑字段（camelCase），系统字段不可改
resp = requests.patch(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin,
                      json={"intro": "闭环测试-已更新", "label": "RC2", "sortOrder": 9}, timeout=10)
check("PATCH=200", resp.status_code == 200, resp.text[:150])
pd = resp.json()["data"]
check("PATCH后intro已更新", pd["intro"] == "闭环测试-已更新")
check("PATCH后label已更新", pd["label"] == "RC2")
check("PATCH后sortOrder已更新", pd["sortOrder"] == 9)
check("PATCH不改变status", pd["status"] == "active")

resp = requests.patch(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin, json={}, timeout=10)
check("PATCH空body=400", resp.status_code == 400 and resp.json().get("code") == "TT_INST_40001", resp.text[:100])

resp = requests.patch(f"{BASE}/admin/institutions/99999999", headers=h_admin, json={"intro": "x"}, timeout=10)
check("PATCH不存在=404", resp.status_code == 404)

resp = requests.patch(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin,
                      json={"platformTypeKey": "bad_key"}, timeout=10)
check("PATCH非法platformTypeKey=400", resp.status_code == 400)

# 审计：institution.create/offline/online/update 同事务落库
resp = requests.get(f"{BASE}/admin/audit-logs?targetType=institution", headers=h_admin, timeout=10)
actions = {i["action"] for i in resp.json()["data"]["list"]}
check("审计含institution.create", "institution.create" in actions, f"got {actions}")
check("审计含institution.offline", "institution.offline" in actions)
check("审计含institution.online", "institution.online" in actions)
check("审计含institution.update", "institution.update" in actions)
print()

# ── 10. Cooperation 管理端（READ ONLY） ──────────────────────
# admin 对 C 已发布的 d1 发起意向（d1 在第 3 节已 approve=published）
coop_msg = "RC管理端查看测试"
coop = requests.post(f"{BASE}/cooperations", headers=h_admin, json={
    "targetType": "demand", "targetId": d1, "message": coop_msg,
}, timeout=10).json()["data"]
intent_id = coop["id"]

resp = requests.get(f"{BASE}/admin/cooperations", headers=h_c, timeout=10)
check("合作列表普通用户=403", resp.status_code == 403)

resp = requests.get(f"{BASE}/admin/cooperations", headers=h_admin, timeout=10)
check("合作列表admin=200", resp.status_code == 200, resp.text[:150])
cl = resp.json()["data"]
check("合作分页契约", all(k in cl for k in ("total", "page", "pageSize", "totalPages", "list")))
check("合作列表含测试意向", any(i["id"] == intent_id for i in cl["list"]))

resp = requests.get(f"{BASE}/admin/cooperations?status=pending", headers=h_admin, timeout=10)
check("status=pending过滤含测试意向", any(i["id"] == intent_id for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/admin/cooperations", headers=h_admin, params={"keyword": coop_msg}, timeout=10)
check("keyword命中message", any(i["id"] == intent_id for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/admin/cooperations/{intent_id}", headers=h_admin, timeout=10)
check("合作详情=200", resp.status_code == 200, resp.text[:150])
cd = resp.json()["data"]
check("详情initiator为admin", cd["initiatorUserId"] == user_admin["userId"])
check("详情target为需求d1", cd["targetType"] == "demand" and cd["targetId"] == d1)
check("详情targetTitle非空", bool(cd.get("targetTitle")))
check("详情含events数组", isinstance(cd.get("events"), list) and len(cd["events"]) >= 1)

before = (cd["status"], cd["version"])
resp2 = requests.get(f"{BASE}/admin/cooperations/{intent_id}", headers=h_admin, timeout=10)
cd2 = resp2.json()["data"]
check("GET不改变状态(READ ONLY)", (cd2["status"], cd2["version"]) == before)

resp = requests.get(f"{BASE}/admin/cooperations/99999999", headers=h_admin, timeout=10)
check("合作不存在=404", resp.status_code == 404 and resp.json().get("code") == "TT_COOP_40401", resp.text[:100])
print()

# ── 11. Users 管理端（READ ONLY） ─────────────────────────────
resp = requests.get(f"{BASE}/admin/users", headers=h_c, timeout=10)
check("用户列表普通用户=403", resp.status_code == 403)

resp = requests.get(f"{BASE}/admin/users", headers=h_admin, timeout=10)
check("用户列表admin=200", resp.status_code == 200, resp.text[:150])
ul = resp.json()["data"]
check("用户分页契约", all(k in ul for k in ("total", "page", "pageSize", "totalPages", "list")))
# 列表按 u.id DESC，admin(id=1) 恒在最后一页 —— 取末页断言，不受用户新增影响
last_page = requests.get(f"{BASE}/admin/users", headers=h_admin,
                         params={"page": ul["totalPages"]}, timeout=10).json()["data"]
check("用户列表含admin自身", any(u["userId"] == user_admin["userId"] for u in last_page["list"]))
u0 = ul["list"][0]
check("用户项含roles数组", isinstance(u0.get("roles"), list))

resp = requests.get(f"{BASE}/admin/users", headers=h_admin, params={"keyword": user_admin["userNo"]}, timeout=10)
check("keyword搜userNo命中", any(u["userId"] == user_admin["userId"] for u in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/admin/users?pageSize=1", headers=h_admin, timeout=10)
p1 = resp.json()["data"]
check("用户分页pageSize=1", len(p1["list"]) == 1 and p1["pageSize"] == 1)

resp = requests.get(f"{BASE}/admin/users/{user_admin['userId']}", headers=h_admin, timeout=10)
check("用户详情=200", resp.status_code == 200, resp.text[:150])
ud = resp.json()["data"]
check("详情userId一致", ud["userId"] == user_admin["userId"])
check("详情roles含admin", "admin" in ud.get("roles", []), f"got {ud.get('roles')}")
stat = ud.get("statistics")
check("详情statistics四项为int", isinstance(stat, dict) and all(
    isinstance(stat.get(k), int) for k in ("achievementCount", "demandCount", "cooperationCount", "favoriteCount")))

resp = requests.get(f"{BASE}/admin/users/99999999", headers=h_admin, timeout=10)
check("用户不存在=404", resp.status_code == 404 and resp.json().get("code") == "TT_COMMON_40402", resp.text[:100])

# ── 清理（保证 legacy baseline 不被污染） ─────────────────────
db_exec("DELETE FROM institution WHERE id = %s", (inst_id,))
db_exec("DELETE FROM cooperation_event WHERE intent_id = %s", (intent_id,))
db_exec("DELETE FROM cooperation_intent WHERE id = %s", (intent_id,))
resp = requests.get(f"{BASE}/institutions/{inst_id}", timeout=10)
check("清理后public不可见", resp.json().get("data") is None)
resp = requests.get(f"{BASE}/admin/institutions/{inst_id}", headers=h_admin, timeout=10)
check("清理后admin不可见", resp.status_code == 404)

# ── 结果 ─────────────────────────────────────────────────────
print()
print(f"=== Admin 域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
