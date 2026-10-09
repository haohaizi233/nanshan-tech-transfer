"""
身份柔性化（账号画像与对接解耦）测试
覆盖：
  /me 与 PATCH /me/profile：subjectType / businessCapabilities 读写、枚举校验、
    数组清洗（去重/去非法）、空数组清空、非法类型 400、user_type 兼容不动
  /cooperations：intentType 按目标类型枚举校验（demand/achievement 各自合法集）、
    非法值 400、缺省放行（兼容历史调用方）、详情与 /me/cooperations 回显 intentType
  权限不变量：对接只受目标归属/状态约束，与主体类型、合作方向画像无关
依赖：后端已启动（127.0.0.1:8787），006 迁移已执行
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


def db_query_one(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


def cleanup():
    """清测试用户(userId>5)数据；画像字段复位，user_type 等既有字段不动"""
    db_exec("DELETE FROM cooperation_intent WHERE initiator_user_id > 5 OR target_owner_user_id > 5")
    db_exec("DELETE FROM favorite WHERE user_id > 5")
    db_exec("DELETE FROM demand WHERE owner_user_id > 5")
    db_exec("UPDATE user_profile SET subject_type=NULL, business_capabilities=NULL WHERE user_id > 5")


cleanup()

# ── 0. 用户：A（企业+多画像）/ B（无画像） ─────────────────────
token_a, user_a = bootstrap("local-dev-ticket-test-flex-a")
token_b, user_b = bootstrap("local-dev-ticket-test-flex-b")
h_a = {"Authorization": f"Bearer {token_a}"}
h_b = {"Authorization": f"Bearer {token_b}"}
print(f"[0] A={user_a['userId']} B={user_b['userId']}\n")

# ═════════════════════════════════════════════════════════════
print("[1] /me 新字段默认值（老数据兼容：字段存在且为空）")
# ═════════════════════════════════════════════════════════════
resp = requests.get(f"{BASE}/me", headers=h_a, timeout=10)
me = resp.json()["data"]
check("GET /me 200", resp.status_code == 200)
check("含 subjectType 字段", "subjectType" in me, f"keys: {sorted(me.keys())}")
check("subjectType 默认 None", me.get("subjectType") is None)
check("含 businessCapabilities 字段", "businessCapabilities" in me)
check("businessCapabilities 默认 []", me.get("businessCapabilities") == [])

# ═════════════════════════════════════════════════════════════
print("[2] PATCH /me/profile：主体类型 + 合作方向读写")
# ═════════════════════════════════════════════════════════════
v = me["version"]
resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": v,
    "subjectType": "enterprise",
    "businessCapabilities": ["seek_technology", "publish_demand", "provide_achievement",
                             "joint_rnd", "provide_service", "investment"],
}, timeout=10)
check("PATCH 200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
updated = resp.json()["data"]
check("subjectType 已写入", updated.get("subjectType") == "enterprise")
check("businessCapabilities 全量写入", updated.get("businessCapabilities") ==
      ["seek_technology", "publish_demand", "provide_achievement", "joint_rnd",
       "provide_service", "investment"])

# 去重与去非法
resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": updated["version"],
    "businessCapabilities": ["investment", "investment", "seek_technology"],
}, timeout=10)
check("重复项去重", resp.json()["data"].get("businessCapabilities") == ["investment", "seek_technology"],
      f"got {resp.json()['data'].get('businessCapabilities')}")

resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": resp.json()["data"]["version"],
    "businessCapabilities": ["hacker_tag"],
}, timeout=10)
check("非法合作方向 400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:150]}")

current = requests.get(f"{BASE}/me", headers=h_a, timeout=10).json()["data"]
resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": current["version"],
    "subjectType": "superman",
}, timeout=10)
check("非法主体类型 400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:150]}")

# 空数组清空
current = requests.get(f"{BASE}/me", headers=h_a, timeout=10).json()["data"]
resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": current["version"],
    "businessCapabilities": [],
}, timeout=10)
check("空数组清空画像", resp.json()["data"].get("businessCapabilities") == [])

# 旧 user_type 仍可独立更新（兼容层，不与新字段冲突）
current = requests.get(f"{BASE}/me", headers=h_a, timeout=10).json()["data"]
resp = requests.patch(f"{BASE}/me/profile", headers=h_a, json={
    "version": current["version"],
    "userType": "enterprise_staff",
}, timeout=10)
check("旧 userType 兼容更新", resp.status_code == 200 and resp.json()["data"].get("userType") == "enterprise_staff")

# ═════════════════════════════════════════════════════════════
print("[3] 对接意向 intentType：按目标类型枚举 + 回显")
# ═════════════════════════════════════════════════════════════
# B 发布需求（A 对接 B 的需求：demand 侧意向枚举）
resp = requests.post(f"{BASE}/demands", headers=h_b, json={
    "title": "测试需求-意向类型", "description": "身份柔性化测试",
    "orgName": "测试组织-柔性", "contactPhone": "13600008888", "contactName": "测试联系人",
}, timeout=10)
d1 = resp.json()["data"]["id"]
db_exec("UPDATE demand SET status='published', published_at=NOW() WHERE id=%s", (d1,))
ach = db_query_one(
    "SELECT id FROM achievement WHERE status='published' AND deleted_at IS NULL ORDER BY id LIMIT 1"
)

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d1, "intentType": "provide_solution",
}, timeout=10)
check("demand 侧合法意向创建 201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
intent_d = resp.json()["data"]
check("详情回显 intentType", intent_d.get("intentType") == "provide_solution")
check("myRole=initiator", intent_d.get("myRole") == "initiator")

resp = requests.get(f"{BASE}/me/cooperations?role=initiator", headers=h_a, timeout=10)
items = resp.json()["data"]["list"]
check("意向列表回显 intentType",
      any(i.get("intentType") == "provide_solution" for i in items), f"got {[i.get('intentType') for i in items]}")

# 意向终态后（reject）才能对同目标再次发起
intent_ver = intent_d["version"]
resp = requests.post(f"{BASE}/cooperations/{intent_d['id']}/reject", headers=h_b,
                     json={"version": intent_ver, "reason": "测试关闭"}, timeout=10)
check("B 拒绝意向（清理活跃态）", resp.status_code == 200)

# demand 侧非法枚举（achievement 侧的值不适用）
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d1, "intentType": "purchase",
}, timeout=10)
check("demand 侧用 achievement 枚举值 → 400", resp.status_code == 400, f"got {resp.status_code}")

# 缺省 intentType 仍可创建（兼容历史调用方）
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d1,
}, timeout=10)
check("缺省 intentType 兼容创建 201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
check("缺省时 intentType=None", resp.json()["data"].get("intentType") is None)
intent_d2 = resp.json()["data"]
requests.post(f"{BASE}/cooperations/{intent_d2['id']}/reject", headers=h_b,
              json={"version": intent_d2["version"], "reason": "测试关闭"}, timeout=10)

# achievement 侧意向
resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "achievement", "targetId": ach["id"], "intentType": "license",
}, timeout=10)
check("achievement 侧合法意向创建 201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
check("achievement 回显 license", resp.json()["data"].get("intentType") == "license")
intent_a1 = resp.json()["data"]

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "achievement", "targetId": ach["id"], "intentType": "provide_solution",
}, timeout=10)
check("achievement 侧用 demand 枚举值 → 400", resp.status_code == 400, f"got {resp.status_code}")

# ═════════════════════════════════════════════════════════════
print("[4] 权限不变量：画像不影响对接（A 企业+全画像 / B 无画像 均可互相发起）")
# ═════════════════════════════════════════════════════════════
# B（无任何画像）对 A 的需求发起 —— B 先发一条需求让 A 对接，同时 B 对 A 能发的目标发起
resp = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": "测试需求-画像无关节制", "description": "A 的需求",
    "orgName": "测试组织-柔性", "contactPhone": "13600008889", "contactName": "A联系人",
}, timeout=10)
d2 = resp.json()["data"]["id"]
db_exec("UPDATE demand SET status='published', published_at=NOW() WHERE id=%s", (d2,))

resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "demand", "targetId": d2, "intentType": "joint_rnd",
}, timeout=10)
check("无画像用户可对接有画像用户需求", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")

# 自有内容仍不可对接（真正的业务约束）
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": d2, "intentType": "other",
}, timeout=10)
check("本人内容对接仍被拒 400", resp.status_code == 400, f"got {resp.status_code}")

# admin 只读列表回显 intentType（admin = dev-user-001 种子账号，走 mock 票据）
token_admin, _ = bootstrap("local-dev-ticket-dev-user-001")
h_admin = {"Authorization": f"Bearer {token_admin}"}
resp = requests.get(f"{BASE}/admin/cooperations?pageSize=50", headers=h_admin, timeout=10)
rows = resp.json()["data"]["list"]
check("admin 列表含 intentType 字段",
      all("intentType" in r for r in rows), "missing intentType key in admin list")
check("admin 列表能查到 license 意向",
      any(r.get("intentType") == "license" for r in rows))

cleanup()
print(f"\n{'='*50}\nRESULT: PASS={PASS} FAIL={FAIL}")
if FAIL:
    raise SystemExit(1)
