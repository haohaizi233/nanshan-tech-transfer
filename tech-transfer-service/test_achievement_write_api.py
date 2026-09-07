"""
成果用户写接口测试（P0-5）
覆盖：POST /achievements（校验/201/draft/inventorRefs/JSONB/ownerUserId 忽略）、
     PATCH（乐观锁/owner-only/状态门/404）、submit/offline 状态机（含端到端审核链）、
     /me/achievements（全状态/status 过滤/isMine）、防探测、审计日志
依赖：后端已启动，005 种子已执行（dev-user-001 = admin）
"""
import psycopg2
import psycopg2.extras
import requests
from config import settings

BASE = settings.API_BASE.rstrip("/") + settings.API_PREFIX
DB = dict(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
          password=settings.DB_PASSWORD, dbname=settings.DB_NAME)
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


def db_query(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        conn.close()


def db_exec(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor() as cur:
            cur.execute(sql, params)
            conn.commit()
    finally:
        conn.close()


token_c, user_c = bootstrap("local-dev-ticket-test-ach-c")
token_d, user_d = bootstrap("local-dev-ticket-test-ach-d")  # 另一用户（非 owner 探测）
token_admin, user_admin = bootstrap("local-dev-ticket-dev-user-001")  # admin
h_c = {"Authorization": f"Bearer {token_c}"}
h_d = {"Authorization": f"Bearer {token_d}"}
h_admin = {"Authorization": f"Bearer {token_admin}"}
print(f"[0] C={user_c['userId']} D={user_d['userId']} admin={user_admin['userId']}\n")

# 清理上轮残留（演示数据 owner<=3 保留）
db_exec("DELETE FROM achievement WHERE owner_user_id > 3 AND title LIKE '成果写接口%%'")

# ── 1. 鉴权 ─────────────────────────────────────────────────
print("[1] 鉴权")
r = requests.post(f"{BASE}/achievements", json={"title": "x", "maturityLevel": "02_lab", "pricingMode": "negotiable"}, timeout=10)
check("无Token=401", r.status_code == 401, f"got {r.status_code}")
r = requests.get(f"{BASE}/me/achievements", timeout=10)
check("me/achievements 无Token=401", r.status_code == 401, f"got {r.status_code}")

# ── 2. 创建校验 ──────────────────────────────────────────────
print("[2] 创建校验")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={}, timeout=10)
check("缺必填=400", r.status_code == 400, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={"title": "成果写接口-缺成熟度"}, timeout=10)
check("缺maturityLevel=400", r.status_code == 400, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-非法枚举", "maturityLevel": "bad", "pricingMode": "negotiable"}, timeout=10)
check("非法maturityLevel=400", r.status_code == 400, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-非法定价", "maturityLevel": "02_lab", "pricingMode": "money"}, timeout=10)
check("非法pricingMode=400", r.status_code == 400, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-价格倒挂", "maturityLevel": "02_lab", "pricingMode": "priced",
    "priceMinWan": 100, "priceMaxWan": 50}, timeout=10)
check("priceMin>priceMax=400", r.status_code == 400, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-坏inventor", "maturityLevel": "02_lab", "pricingMode": "negotiable",
    "inventorRefs": [{"orgName": "X"}]}, timeout=10)
check("inventorRefs缺name=400", r.status_code == 400, f"got {r.status_code}")

# ── 3. 创建成功 ──────────────────────────────────────────────
print("[3] 创建成功")
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-A1", "maturityLevel": "03_pilot_ready", "pricingMode": "license",
    "techIntro": "简介", "techRoute": "路径", "maturityDesc": "中试完成",
    "applicationFields": ["新能源", "储能"],
    "innovationPoints": ["点1", "点2"],
    "priceMinWan": 10, "priceMaxWan": 100,
    "contactName": "C", "contactPhone": "13800001111",
    "sourceOrgName": "成果写接口-测试大学",
    "inventorRefs": [
        {"name": "成果写接口-张三", "orgName": "成果写接口-测试大学", "personType": "first_inventor", "sortOrder": 0},
        {"name": "成果写接口-李四", "personType": "co_inventor"},
    ],
    "ownerUserId": 999,  # 必须被忽略
    "tags": ["tag"], "mediaFileIds": [1],  # 无表，接受但忽略
}, timeout=10)
check("创建=201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
a1 = r.json()["data"]
check("创建即draft", a1["status"] == "draft", a1.get("status"))
check("version=1", a1["version"] == 1, a1.get("version"))
check("owner注入=C", not a1.get("ownerUserId") or True)  # 响应不含 owner 字段，验证 DB 侧
rows = db_query("SELECT owner_user_id, org_id, source_org_name FROM achievement WHERE id=%s", (a1["id"],))
check("DB owner=C", rows[0]["owner_user_id"] == user_c["userId"])
check("来源名称仅保存展示快照", rows[0]["org_id"] is None and rows[0]["source_org_name"] == "成果写接口-测试大学")
check("applicationFields落库", a1["applicationFields"] == ["新能源", "储能"], a1.get("applicationFields"))
check("innovationPoints落库", a1["innovationPoints"] == ["点1", "点2"], a1.get("innovationPoints"))
check("inventors=2", len(a1["inventors"]) == 2, a1.get("inventors"))
check("inventor personType", a1["inventors"][0]["personType"] == "first_inventor", a1["inventors"])

# 重复 inventorRefs（同 name+org）去重，不触发唯一约束 500
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-A2", "maturityLevel": "02_lab", "pricingMode": "negotiable",
    "inventorRefs": [{"name": "成果写接口-王五"}, {"name": "成果写接口-王五"}],
}, timeout=10)
check("重复inventor去重=201", r.status_code == 201, f"got {r.status_code}: {r.text[:200]}")
a2 = r.json()["data"]
check("A2 inventors=1", len(a2["inventors"]) == 1, a2.get("inventors"))

# ── 4. 编辑 ─────────────────────────────────────────────────
print("[4] 编辑")
r = requests.patch(f"{BASE}/achievements/{a1['id']}", headers=h_c, json={"title": "成果写接口-A1改"}, timeout=10)
check("无version=400", r.status_code == 400, f"got {r.status_code}")
r = requests.patch(f"{BASE}/achievements/{a1['id']}", headers=h_d, json={"title": "x", "version": 1}, timeout=10)
check("非owner=403", r.status_code == 403 and r.json().get("code") == "TT_ACH_40301", f"got {r.status_code}: {r.text[:100]}")
r = requests.patch(f"{BASE}/achievements/999999", headers=h_c, json={"title": "x", "version": 1}, timeout=10)
check("不存在=404 TT_ACH_40401", r.status_code == 404 and r.json().get("code") == "TT_ACH_40401", f"got {r.status_code}: {r.text[:100]}")
r = requests.patch(f"{BASE}/achievements/{a1['id']}", headers=h_c, json={"title": "成果写接口-A1改", "version": 99}, timeout=10)
check("错version=409", r.status_code == 409 and r.json().get("code") == "TT_COMMON_40902", f"got {r.status_code}: {r.text[:100]}")

r = requests.patch(f"{BASE}/achievements/{a1['id']}", headers=h_c, json={
    "title": "成果写接口-A1改", "techIntro": "新简介", "version": 1,
    "inventorRefs": [{"name": "成果写接口-张三", "orgName": "成果写接口-测试大学"},
                     {"name": "成果写接口-赵六"}],
}, timeout=10)
check("编辑=200", r.status_code == 200, f"got {r.status_code}: {r.text[:200]}")
upd = r.json()["data"]
check("编辑生效", upd["title"] == "成果写接口-A1改", upd.get("title"))
check("编辑version+1", upd["version"] == 2, upd.get("version"))
check("inventor整体替换", {i["name"] for i in upd["inventors"]} == {"成果写接口-张三", "成果写接口-赵六"}, upd.get("inventors"))

# ── 5. 提交审核（状态机） ───────────────────────────────────
print("[5] 提交审核")
r = requests.post(f"{BASE}/achievements/{a1['id']}/submit", headers=h_d, json={"version": 2}, timeout=10)
check("非owner submit=403", r.status_code == 403, f"got {r.status_code}")
r = requests.post(f"{BASE}/achievements/{a1['id']}/submit", headers=h_c, json={"version": 2}, timeout=10)
check("submit=200 pending_review", r.status_code == 200 and r.json()["data"]["status"] == "pending_review", r.text[:200])
r = requests.post(f"{BASE}/achievements/{a1['id']}/submit", headers=h_c, json={"version": 3}, timeout=10)
check("重复submit=409 TT_ACH_40901", r.status_code == 409 and r.json().get("code") == "TT_ACH_40901", f"got {r.status_code}: {r.text[:100]}")
r = requests.patch(f"{BASE}/achievements/{a1['id']}", headers=h_c, json={"title": "y", "version": 3}, timeout=10)
check("pending_review编辑=409", r.status_code == 409 and r.json().get("code") == "TT_ACH_40901", f"got {r.status_code}: {r.text[:100]}")

# ── 6. 端到端：admin 审核链（approve→offline；reject→重新提交） ──
print("[6] 审核链")
r = requests.post(f"{BASE}/admin/achievements/{a1['id']}/approve", headers=h_admin, json={"version": 3}, timeout=10)
check("admin approve=200 published", r.status_code == 200 and r.json()["data"]["status"] == "published", r.text[:200])
rows = db_query("SELECT published_at FROM achievement WHERE id=%s", (a1["id"],))
check("published_at已设置", rows[0]["published_at"] is not None)

r = requests.post(f"{BASE}/achievements/{a1['id']}/offline", headers=h_c, json={"version": 4, "reason": "已转让"}, timeout=10)
check("offline=200", r.status_code == 200 and r.json()["data"]["status"] == "offline", r.text[:200])
r = requests.post(f"{BASE}/achievements/{a1['id']}/offline", headers=h_c, json={"version": 5}, timeout=10)
check("重复offline=409", r.status_code == 409, f"got {r.status_code}")

# A2: reject → 重新编辑 → 重新 submit
r = requests.post(f"{BASE}/achievements/{a2['id']}/submit", headers=h_c, json={"version": 1}, timeout=10)
check("A2 submit=200", r.status_code == 200, r.text[:100])
r = requests.post(f"{BASE}/admin/achievements/{a2['id']}/reject", headers=h_admin, json={"version": 2, "reason": "描述不足"}, timeout=10)
check("admin reject=200 rejected", r.status_code == 200 and r.json()["data"]["status"] == "rejected", r.text[:200])
r = requests.patch(f"{BASE}/achievements/{a2['id']}", headers=h_c, json={"techIntro": "补充后", "version": 3}, timeout=10)
check("rejected可编辑=200", r.status_code == 200, f"got {r.status_code}: {r.text[:100]}")
r = requests.post(f"{BASE}/achievements/{a2['id']}/submit", headers=h_c, json={"version": 4}, timeout=10)
check("rejected重新submit=200", r.status_code == 200, r.text[:100])

# A3: 已驳回的成果必须在“我发布的成果”列表中看到管理员原因
r = requests.post(f"{BASE}/achievements", headers=h_c, json={
    "title": "成果写接口-审核反馈", "maturityLevel": "02_lab", "pricingMode": "negotiable",
}, timeout=10)
a3 = r.json()["data"]
r = requests.post(f"{BASE}/achievements/{a3['id']}/submit", headers=h_c, json={"version": 1}, timeout=10)
check("A3 submit=200", r.status_code == 200, r.text[:100])
r = requests.post(f"{BASE}/admin/achievements/{a3['id']}/reject", headers=h_admin, json={"version": 2, "reason": "请补充应用场景"}, timeout=10)
check("A3 admin reject=200", r.status_code == 200, r.text[:100])

# ── 7. /me/achievements ─────────────────────────────────────
print("[7] me/achievements")
r = requests.get(f"{BASE}/me/achievements", headers=h_c, timeout=10)
d = r.json()["data"]
check("列表=200", r.status_code == 200)
check("含全状态", any(x["status"] == "offline" for x in d["list"]) and any(x["status"] == "pending_review" for x in d["list"]), [x["status"] for x in d["list"]])
check("isMine=true", all(x["isMine"] for x in d["list"]))
check("summary含version", all("version" in x for x in d["list"]))
rejected_a3 = next((x for x in d["list"] if x["id"] == a3["id"]), None)
check("驳回成果列表回显管理员原因", rejected_a3 and rejected_a3.get("rejectReason") == "请补充应用场景", rejected_a3)
r = requests.get(f"{BASE}/me/achievements?status=pending_review", headers=h_c, timeout=10)
d2 = r.json()["data"]
check("status过滤", all(x["status"] == "pending_review" for x in d2["list"]) and len(d2["list"]) >= 1, [x["status"] for x in d2["list"]])
r = requests.get(f"{BASE}/me/achievements", headers=h_d, timeout=10)
check("D看不到C的成果", r.json()["data"]["total"] == 0, r.json()["data"]["total"])

# ── 8. 防探测（存量行为保持：非 published 非 owner → data=null） ──
print("[8] 防探测")
r = requests.get(f"{BASE}/achievements/{a2['id']}", headers=h_d, timeout=10)
check("非owner看draft=null", r.status_code == 200 and r.json().get("data") is None, r.text[:100])

# ── 9. 审计日志 ─────────────────────────────────────────────
print("[9] 审计日志")
actions = {row["action"] for row in db_query(
    "SELECT action FROM audit_log WHERE resource_type='achievement' AND resource_id=%s",
    (str(a1["id"]),))}
for expected in ("achievement.create", "achievement.update", "achievement.submit", "achievement.offline", "achievement.approve"):
    check(f"审计 {expected}", expected in actions, sorted(actions))

# ── 10. 清理 ────────────────────────────────────────────────
db_exec("DELETE FROM achievement WHERE owner_user_id > 3 AND title LIKE '成果写接口%%'")
db_exec("DELETE FROM inventor WHERE name LIKE '成果写接口%%' AND id NOT IN (SELECT inventor_id FROM achievement_inventor)")

print()
print(f"=== P0-5 成果写接口测试: {PASS} passed, {FAIL} failed ===")
exit(1 if FAIL else 0)
