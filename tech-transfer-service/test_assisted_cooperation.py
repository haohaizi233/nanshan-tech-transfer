"""
平台协助对接（Assisted Cooperation）+ Admin 代发布 定向测试（2026-09-07）

覆盖：
  1. Admin 代发布：ownerUserId 留空 → owner NULL + created_by=admin + platformAssisted；
     admin submit（代无账号内容）→ approve → published
  2. 用户对代录内容发起对接 → 自动 assisted（queued），联系方式快照 + 同意时间戳 + 对方展示机构名
  3. 普通用户无法代目标方操作（404 防探测）
  4. assist_status 流转校验（跳步 409 / 非法值 400 / direct 意向 400 / 非 pending 409）
  5. 代 accept 前置：未 target_agreed → 409；同意后 accept → accepted + acceptMode=platform_assisted
  6. accepted 后联系方式解锁（明文）；协助驳回后仍脱敏
  7. auto-reject 副作用（同目标其他 pending 自动拒绝）
  8. direct 模式回归：目标方自行 accept → acceptMode=self；admin 对 direct 意向代操作=400
  9. 终态后重新发起 + 发起方主动撤回（cancel）
 10. admin 列表 handlingMode/assistStatus 筛选 + 详情 assist 字段 + 快照
 11. 审计：cooperation.assist_status / cooperation.admin_accept / admin_submit 落库
 12. admin submit 对有归属用户的内容=400（边界）
依赖：后端已启动（127.0.0.1:8787），005 种子已执行（dev-user-001 = admin）
"""

import psycopg2
import psycopg2.extras
import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
DB = dict(host="127.0.0.1", port=5432, user="postgres", password="postgres123",
          dbname="tech_transfer")
PASS = 0
FAIL = 0

ORG_NAME = "协助对接测试机构"
ACH_TITLES = ("协助对接-代录成果A", "协助对接-代录成果B")
DMD_TITLES = ("协助对接-代录需求D", "协助对接-直连需求", "协助对接-归属用户草稿")


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


def db_one(sql, params=()):
    conn = psycopg2.connect(**DB)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, params)
            return cur.fetchone()
    finally:
        conn.close()


# ── 身份 ─────────────────────────────────────────────────────
token_admin, user_admin = bootstrap("local-dev-ticket-dev-user-001")
token_a, user_a = bootstrap("local-dev-ticket-test-coop-a")
token_b, user_b = bootstrap("local-dev-ticket-test-coop-b")
h_admin = {"Authorization": f"Bearer {token_admin}"}
h_a = {"Authorization": f"Bearer {token_a}"}
h_b = {"Authorization": f"Bearer {token_b}"}
print(f"[0] admin={user_admin['userId']} A={user_a['userId']} B={user_b['userId']}\n")

# 对接发起方的联系方式来自用户资料快照；为可重复验证，给测试账号补齐资料。
profile_b_before = db_one(
    "SELECT display_name, phone, email, wechat, org_title FROM user_profile WHERE user_id=%s",
    (user_b["userId"],),
) or {}
db_exec(
    """
    UPDATE user_profile
    SET display_name=%s, phone=%s, email=%s, wechat=%s, org_title=%s
    WHERE user_id=%s
    """,
    ("测试发起方B", "13612345678", "coop-b@example.com", "coop_b_wechat", "技术负责人", user_b["userId"]),
)

# ── 清理上轮残留（顺序：事件→意向→需求/成果→机构） ────────────
db_exec(
    "DELETE FROM cooperation_event WHERE intent_id IN "
    "(SELECT id FROM cooperation_intent ci WHERE "
    " (ci.target_type='achievement' AND ci.target_id IN (SELECT id FROM achievement WHERE title LIKE '协助对接%%')) OR "
    " (ci.target_type='demand' AND ci.target_id IN (SELECT id FROM demand WHERE title LIKE '协助对接%%')))"
)
db_exec(
    "DELETE FROM cooperation_intent WHERE "
    "(target_type='achievement' AND target_id IN (SELECT id FROM achievement WHERE title LIKE '协助对接%%')) OR "
    "(target_type='demand' AND target_id IN (SELECT id FROM demand WHERE title LIKE '协助对接%%'))"
)
db_exec("DELETE FROM demand WHERE title LIKE '协助对接%%'")
db_exec("DELETE FROM achievement WHERE title LIKE '协助对接%%'")
db_exec("DELETE FROM institution WHERE name LIKE '协助对接%%'")

# 测试机构（enterprise 类不在 admin 机构管理三分类内，按表单路径直接落库）
db_exec(
    "INSERT INTO institution (kind, name, intro, user_type, source_site) "
    "VALUES ('enterprise', %s, '平台协助对接测试机构', 'enterprise', 'test')",
    (ORG_NAME,),
)
org = db_one("SELECT id FROM institution WHERE name=%s", (ORG_NAME,))
org_id = org["id"]

cats = requests.get(f"{BASE}/achievements/categories", headers=h_a, timeout=10).json()["data"]
cat_id = cats[0]["id"]
print(f"[0] org_id={org_id} cat_id={cat_id}\n")


# ══ 1. Admin 代发布（成果，owner 留空） ════════════════════════
resp = requests.post(f"{BASE}/admin/achievements", headers=h_admin, json={
    "title": ACH_TITLES[0], "categoryId": cat_id, "orgId": org_id,
    "maturityLevel": "03_pilot_ready", "pricingMode": "negotiable",
    "techIntro": "平台代录成果简介", "sourceOrgName": ORG_NAME,
    "contactName": "机构联系人", "contactTitle": "技术转移办主任",
    "contactPhone": "13911112222", "contactEmail": "org-assist@example.com",
    "cooperationPolicy": "exclusive",
}, timeout=10)
check("代录成果=201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
ach = resp.json()["data"]
ach_id = ach["id"]
check("platformAssisted=true", ach.get("platformAssisted") is True, str(ach.get("platformAssisted")))
check("ownerUserId=null", ach.get("ownerUserId") is None, str(ach.get("ownerUserId")))

row = db_one("SELECT owner_user_id, created_by_user_id, status FROM achievement WHERE id=%s", (ach_id,))
check("DB owner=NULL", row["owner_user_id"] is None, str(row["owner_user_id"]))
check("DB created_by=admin", row["created_by_user_id"] == user_admin["userId"],
      f"created_by={row['created_by_user_id']} admin={user_admin['userId']}")
check("初始状态=draft", row["status"] == "draft", row["status"])

# admin submit（代无账号内容提交审核）→ approve → published
resp = requests.post(f"{BASE}/admin/achievements/{ach_id}/submit", headers=h_admin,
                     json={"version": ach["version"]}, timeout=10)
check("admin submit=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
check("submit后=pending_review", resp.json()["data"]["status"] == "pending_review",
      resp.text[:100])

v = requests.get(f"{BASE}/admin/achievements/{ach_id}", headers=h_admin, timeout=10).json()["data"]["version"]
resp = requests.post(f"{BASE}/admin/achievements/{ach_id}/approve", headers=h_admin,
                     json={"version": v}, timeout=10)
check("approve=200", resp.status_code == 200, resp.text[:150])
check("approve后=published", resp.json()["data"]["status"] == "published", resp.text[:100])
print()

# ── 公开视角：代录成果可见 + 联系方式脱敏 ─────────────────────
pub = requests.get(f"{BASE}/achievements/{ach_id}", headers=h_a, timeout=10).json()["data"]
check("公开可见", pub is not None and pub.get("id") == ach_id)
check("公开视角platformAssisted=true", pub.get("platformAssisted") is True)
check("公开视角isMine=false", pub.get("isMine") is False)
check("未接受前电话脱敏", pub.get("contactPhone") == "139****2222", str(pub.get("contactPhone")))
check("未接受前邮箱脱敏", pub.get("contactEmail") == "or****@example.com", str(pub.get("contactEmail")))
check("未接受前姓名脱敏", pub.get("contactName") == "机**", str(pub.get("contactName")))
print()

# ══ 2. 用户发起对接 → 自动 assisted ═══════════════════════════
resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "achievement", "targetId": ach_id, "intentType": "purchase",
    "message": "希望购买该成果", "contactShareConsent": False,
}, timeout=10)
check("拒绝联系方式共享=400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:100]}")

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "achievement", "targetId": ach_id, "intentType": "purchase",
    "message": "协助对接测试意向", "contactShareConsent": True,
}, timeout=10)
check("发起意向=201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
intent_a = resp.json()["data"]
intent_id_a = intent_a["id"]
check("handlingMode=assisted", intent_a.get("handlingMode") == "assisted", str(intent_a.get("handlingMode")))
check("assistStatus=queued", intent_a.get("assistStatus") == "queued", str(intent_a.get("assistStatus")))
check("acceptMode=null", intent_a.get("acceptMode") is None, str(intent_a.get("acceptMode")))
check("platformAssisted=true", intent_a.get("platformAssisted") is True)
check("对方展示=机构名", intent_a.get("counterpartDisplayName") == ORG_NAME,
      str(intent_a.get("counterpartDisplayName")))
check("targetOwnerUserId=null", intent_a.get("targetOwnerUserId") is None)

row = db_one(
    "SELECT initiator_contact_snapshot, contact_share_consent_at, target_org_id "
    "FROM cooperation_intent WHERE id=%s", (intent_id_a,)
)
snap = row["initiator_contact_snapshot"]
check("联系方式快照已落库", isinstance(snap, dict) and "displayName" in snap, str(snap)[:100])
check("同意时间戳已落库", row["contact_share_consent_at"] is not None)
check("target_org_id=机构", row["target_org_id"] == org_id, str(row["target_org_id"]))
print()

# B 也发起（auto-reject 测试素材）
resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "achievement", "targetId": ach_id, "intentType": "license",
    "message": "B 的协助意向", "contactShareConsent": True,
}, timeout=10)
intent_b = resp.json()["data"]
intent_id_b = intent_b["id"]
check("B 发起=201（同目标多意向允许）", resp.status_code == 201, resp.text[:150])

# ══ 3. 普通用户无法代目标方操作（防探测 404） ═════════════════
resp = requests.post(f"{BASE}/cooperations/{intent_id_a}/accept", headers=h_a,
                     json={"version": intent_a["version"]}, timeout=10)
check("发起方A尝试accept=404", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_COOP_40401", resp.json().get("code") == "TT_COOP_40401", resp.text[:100])

resp = requests.post(f"{BASE}/cooperations/{intent_id_a}/reject", headers=h_b,
                     json={"version": 1, "reason": "x"}, timeout=10)
check("无关用户B尝试reject=404", resp.status_code == 404, f"got {resp.status_code}")
print()

# ══ 4. assist_status 流转校验 ═════════════════════════════════
resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_admin,
                     json={"assistStatus": "target_agreed"}, timeout=10)
check("queued跳步target_agreed=409", resp.status_code == 409, f"got {resp.status_code} {resp.text[:120]}")

resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_admin,
                     json={"assistStatus": "bad_value"}, timeout=10)
check("非法assistStatus=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_admin,
                     json={"assistStatus": "contacting", "note": "电话已接通"}, timeout=10)
check("queued→contacting=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:120]}")

resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_admin,
                     json={"assistStatus": "waiting_reply"}, timeout=10)
check("contacting→waiting_reply=200", resp.status_code == 200, resp.text[:120])

# ══ 5. 代 accept 前置校验 ═════════════════════════════════════
resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-transition", headers=h_admin,
                     json={"action": "accept", "version": intent_a["version"]}, timeout=10)
check("未target_agreed代accept=400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:150]}")

resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_admin,
                     json={"assistStatus": "target_agreed", "note": "机构邮件确认同意"}, timeout=10)
check("waiting_reply→target_agreed=200", resp.status_code == 200, resp.text[:120])

# target_agreed 但没带 confirmationNote → 400（强制确认依据）
resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-transition", headers=h_admin,
                     json={"action": "accept", "version": intent_a["version"]}, timeout=10)
check("target_agreed无confirmationNote=400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:150]}")
check("错误码TT_COMMON_40001", resp.json().get("code") == "TT_COMMON_40001", resp.text[:100])

resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-transition", headers=h_admin,
                     json={"action": "accept", "version": intent_a["version"],
                           "confirmationNote": "2026-09-07 电话联系李老师，对方确认愿意进一步对接"}, timeout=10)
check("代accept=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
check("代accept后status=accepted", resp.json()["data"]["status"] == "accepted", resp.text[:100])
check("acceptMode=platform_assisted", resp.json()["data"]["acceptMode"] == "platform_assisted",
      str(resp.json()["data"].get("acceptMode")))

row = db_one("SELECT handled_by_user_id, accepted_at FROM cooperation_intent WHERE id=%s", (intent_id_a,))
check("handled_by=admin", row["handled_by_user_id"] == user_admin["userId"], str(row["handled_by_user_id"]))
check("accepted_at已置", row["accepted_at"] is not None)
print()

# ══ 6. accepted 后联系方式解锁 ════════════════════════════════
pub = requests.get(f"{BASE}/achievements/{ach_id}", headers=h_a, timeout=10).json()["data"]
check("accepted后电话明文", pub.get("contactPhone") == "13911112222", str(pub.get("contactPhone")))
check("accepted后邮箱明文", pub.get("contactEmail") == "org-assist@example.com", str(pub.get("contactEmail")))

# A 侧详情：状态 + acceptMode
detail = requests.get(f"{BASE}/cooperations/{intent_id_a}", headers=h_a, timeout=10).json()["data"]
check("A详情status=accepted", detail.get("status") == "accepted")
check("A详情acceptMode=platform_assisted", detail.get("acceptMode") == "platform_assisted")
check("A详情assistStatus=target_agreed", detail.get("assistStatus") == "target_agreed")

# ══ 7. auto-reject 副作用 ═════════════════════════════════════
detail_b = requests.get(f"{BASE}/cooperations/{intent_id_b}", headers=h_b, timeout=10).json()["data"]
check("B 意向被自动拒绝", detail_b.get("status") == "rejected", str(detail_b.get("status")))
ev_types = [e["eventType"] for e in requests.get(
    f"{BASE}/cooperations/{intent_id_b}/events", headers=h_b, timeout=10).json()["data"]["list"]]
check("B 事件含auto_rejected", "auto_rejected" in ev_types, str(ev_types))
print()

# ══ 8. 事件时间线含平台操作留痕 ═══════════════════════════════
events = requests.get(f"{BASE}/cooperations/{intent_id_a}/events", headers=h_a, timeout=10).json()["data"]["list"]
types = [e["eventType"] for e in events]
check("事件含created", "created" in types, str(types))
check("事件含assist_status_change", "assist_status_change" in types, str(types))
check("事件含accepted", "accepted" in types, str(types))
admin_events = [e for e in events if e.get("operatorRole") == "platform_admin"]
check("platform_admin操作留痕>=3", len(admin_events) >= 3, f"got {len(admin_events)}")
print()

# ══ 9. 协助驳回路径（需求侧） ═════════════════════════════════
resp = requests.post(f"{BASE}/admin/demands", headers=h_admin, json={
    "title": DMD_TITLES[0], "categoryId": 1, "orgId": org_id,
    "description": "代录需求描述", "contactPhone": "13733334444", "contactName": "需求联系人",
}, timeout=10)
check("代录需求=201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:150]}")
dmd = resp.json()["data"]
dmd_id = dmd["id"]
check("代录需求platformAssisted=true", dmd.get("platformAssisted") is True)

resp = requests.post(f"{BASE}/admin/demands/{dmd_id}/submit", headers=h_admin,
                     json={"version": dmd["version"]}, timeout=10)
check("需求admin submit=200", resp.status_code == 200, resp.text[:120])
v = requests.get(f"{BASE}/admin/demands/{dmd_id}", headers=h_admin, timeout=10).json()["data"]["version"]
resp = requests.post(f"{BASE}/admin/demands/{dmd_id}/approve", headers=h_admin,
                     json={"version": v}, timeout=10)
check("需求approve=published", resp.status_code == 200 and resp.json()["data"]["status"] == "published",
      resp.text[:120])

resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": dmd_id, "intentType": "provide_solution",
    "message": "提供方案", "contactShareConsent": True,
}, timeout=10)
d_intent = resp.json()["data"]
d_intent_id = d_intent["id"]
check("需求侧assisted=queued", d_intent.get("handlingMode") == "assisted"
      and d_intent.get("assistStatus") == "queued", str(d_intent.get("assistStatus")))

# 代 reject：无需 target_rejected 前置但必填 reason
resp = requests.post(f"{BASE}/admin/cooperations/{d_intent_id}/assist-transition", headers=h_admin,
                     json={"action": "reject", "version": d_intent["version"]}, timeout=10)
check("代reject缺reason=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.post(f"{BASE}/admin/cooperations/{d_intent_id}/assist-status", headers=h_admin,
                     json={"assistStatus": "contacting"}, timeout=10)
check("queued→contacting=200", resp.status_code == 200, resp.text[:100])
resp = requests.post(f"{BASE}/admin/cooperations/{d_intent_id}/assist-status", headers=h_admin,
                     json={"assistStatus": "target_rejected", "note": "机构暂无对接意愿"}, timeout=10)
check("contacting→target_rejected=200", resp.status_code == 200, resp.text[:100])

resp = requests.post(f"{BASE}/admin/cooperations/{d_intent_id}/assist-transition", headers=h_admin,
                     json={"action": "reject", "version": d_intent["version"], "reason": "机构明确拒绝"}, timeout=10)
check("代reject=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:150]}")
check("代reject后status=rejected", resp.json()["data"]["status"] == "rejected", resp.text[:100])

# 驳回后联系方式仍脱敏
pub = requests.get(f"{BASE}/demands/{dmd_id}", headers=h_a, timeout=10).json()["data"]
check("驳回后电话仍脱敏", pub.get("contactPhone") == "137****4444", str(pub.get("contactPhone")))

# 驳回后（终态）可重新发起 + 发起方可主动撤回
resp = requests.post(f"{BASE}/cooperations", headers=h_a, json={
    "targetType": "demand", "targetId": dmd_id, "intentType": "provide_service",
    "message": "重新发起", "contactShareConsent": True,
}, timeout=10)
check("终态后可重新发起", resp.status_code == 201, f"got {resp.status_code} {resp.text[:120]}")
d2 = resp.json()["data"]
resp = requests.post(f"{BASE}/cooperations/{d2['id']}/cancel", headers=h_a,
                     json={"version": d2["version"], "reason": "我方计划变更"}, timeout=10)
check("发起方撤回=200", resp.status_code == 200 and resp.json()["data"]["status"] == "cancelled",
      f"got {resp.status_code} {resp.text[:120]}")
print()

# ══ 10. direct 模式回归 ═══════════════════════════════════════
resp = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": DMD_TITLES[1], "description": "直连需求",
    "orgName": ORG_NAME, "contactPhone": "13855556666", "contactName": "A",
}, timeout=10)
d_direct = resp.json()["data"]
d_direct_id = d_direct["id"]
v = requests.get(f"{BASE}/demands/{d_direct_id}", headers=h_a, timeout=10).json()["data"]["version"]
requests.post(f"{BASE}/demands/{d_direct_id}/submit", headers=h_a, json={"version": v}, timeout=10)
v = requests.get(f"{BASE}/demands/{d_direct_id}", headers=h_a, timeout=10).json()["data"]["version"]
requests.post(f"{BASE}/admin/demands/{d_direct_id}/approve", headers=h_admin, json={"version": v}, timeout=10)

resp = requests.post(f"{BASE}/cooperations", headers=h_b, json={
    "targetType": "demand", "targetId": d_direct_id, "intentType": "provide_achievement",
    "message": "直连模式", "contactShareConsent": True,
}, timeout=10)
direct = resp.json()["data"]
check("direct意向handlingMode=direct", direct.get("handlingMode") == "direct", str(direct.get("handlingMode")))
check("direct意向assistStatus=null", direct.get("assistStatus") is None, str(direct.get("assistStatus")))

# pending：接收方可直接联系发起方；发起方仍不可见发布方明文
pending_target = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_a, timeout=10).json()["data"]
pending_initiator = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_b, timeout=10).json()["data"]
check("pending接收方可见发起方联系人", pending_target.get("counterpartContact", {}).get("masked") is False
      and "*" not in (pending_target.get("counterpartContact", {}).get("phone") or ""),
      str(pending_target.get("counterpartContact")))
check("pending发起方联系人仍脱敏", pending_initiator.get("counterpartContact", {}).get("masked") is True
      and "*" in (pending_initiator.get("counterpartContact", {}).get("phone") or ""),
      str(pending_initiator.get("counterpartContact")))

# pending 阶段目标方不可撤回他人申请（应使用 reject）
resp = requests.post(f"{BASE}/cooperations/{direct['id']}/cancel", headers=h_a,
                     json={"version": direct["version"]}, timeout=10)
check("pending目标方cancel=403", resp.status_code == 403, f"got {resp.status_code} {resp.text[:120]}")

# 目标方（A）自行 accept → acceptMode=self
resp = requests.post(f"{BASE}/cooperations/{direct['id']}/accept", headers=h_a,
                     json={"version": direct["version"]}, timeout=10)
check("A 自行accept=200", resp.status_code == 200, f"got {resp.status_code} {resp.text[:120]}")
check("acceptMode=self", resp.json()["data"].get("acceptMode") == "self",
      str(resp.json()["data"].get("acceptMode")))

accepted_target = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_a, timeout=10).json()["data"]
accepted_initiator = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_b, timeout=10).json()["data"]
check("accepted双方联系人解锁", accepted_target.get("counterpartContact", {}).get("masked") is False
      and accepted_initiator.get("counterpartContact", {}).get("masked") is False,
      f"target={accepted_target.get('counterpartContact')} initiator={accepted_initiator.get('counterpartContact')}")

resp = requests.post(f"{BASE}/cooperations/{direct['id']}/cancel", headers=h_b,
                     json={"version": accepted_initiator["version"], "reason": "验证终态重新脱敏"}, timeout=10)
check("accepted发起方取消=200", resp.status_code == 200 and resp.json()["data"]["status"] == "cancelled",
      f"got {resp.status_code} {resp.text[:120]}")
cancelled_target = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_a, timeout=10).json()["data"]
cancelled_initiator = requests.get(f"{BASE}/cooperations/{direct['id']}", headers=h_b, timeout=10).json()["data"]
check("cancelled双方联系人重新脱敏", cancelled_target.get("counterpartContact", {}).get("masked") is True
      and cancelled_initiator.get("counterpartContact", {}).get("masked") is True,
      f"target={cancelled_target.get('counterpartContact')} initiator={cancelled_initiator.get('counterpartContact')}")

# admin 对 direct 意向代操作=400
resp = requests.post(f"{BASE}/admin/cooperations/{direct['id']}/assist-status", headers=h_admin,
                     json={"assistStatus": "contacting"}, timeout=10)
check("admin对direct意向改阶段=400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:120]}")

# ══ 11. admin submit 边界：有归属用户的内容不可代提交 ═════════
resp = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": DMD_TITLES[2], "description": "归属用户草稿",
    "contactPhone": "13677778888", "contactName": "A",
}, timeout=10)
d_own = resp.json()["data"]
resp = requests.post(f"{BASE}/admin/demands/{d_own['id']}/submit", headers=h_admin,
                     json={"version": d_own["version"]}, timeout=10)
check("有归属用户内容代submit=400", resp.status_code == 400, f"got {resp.status_code} {resp.text[:120]}")
print()

# ══ 12. admin 列表筛选 + 详情 assist 字段 ═════════════════════
resp = requests.get(f"{BASE}/admin/cooperations", headers=h_admin,
                    params={"handlingMode": "assisted", "pageSize": 50}, timeout=10)
check("handlingMode=assisted筛选=200", resp.status_code == 200)
items = resp.json()["data"]["list"]
match = next((i for i in items if i["id"] == intent_id_a), None)
check("assisted列表含A意向", match is not None, f"total={resp.json()['data']['total']}")
if match:
    check("列表项含targetOrgName", match.get("targetOrgName") == ORG_NAME, str(match.get("targetOrgName")))
    check("列表项含initiatorContact", isinstance(match.get("initiatorContact"), dict))
    check("列表项含assistNote", match.get("assistNote") is not None)
    check("列表项含contactShareConsentAt", match.get("contactShareConsentAt") is not None)

resp = requests.get(f"{BASE}/admin/cooperations", headers=h_admin,
                    params={"handlingMode": "direct", "pageSize": 50}, timeout=10)
check("direct筛选不含A意向", all(i["id"] != intent_id_a for i in resp.json()["data"]["list"]))

resp = requests.get(f"{BASE}/admin/cooperations/{intent_id_a}", headers=h_admin, timeout=10)
check("admin详情=200", resp.status_code == 200)
cd = resp.json()["data"]
check("详情含handledByUserId", cd.get("handledByUserId") == user_admin["userId"])
check("详情快照含displayName", isinstance(cd.get("initiatorContact"), dict)
      and "displayName" in cd["initiatorContact"])

# ══ 13. 审计留痕 ═════════════════════════════════════════════
resp = requests.get(f"{BASE}/admin/audit-logs", headers=h_admin,
                    params={"targetType": "cooperation_intent", "pageSize": 50}, timeout=10)
actions = {i["action"] for i in resp.json()["data"]["list"]}
check("审计含cooperation.assist_status", "cooperation.assist_status" in actions, str(actions))
check("审计含cooperation.admin_accept", "cooperation.admin_accept" in actions, str(actions))
check("审计含cooperation.admin_reject", "cooperation.admin_reject" in actions, str(actions))

resp = requests.get(f"{BASE}/admin/audit-logs", headers=h_admin,
                    params={"targetType": "achievement", "pageSize": 50}, timeout=10)
actions = {i["action"] for i in resp.json()["data"]["list"]}
check("审计含achievement.admin_submit", "achievement.admin_submit" in actions, str(actions))
check("审计含achievement.admin_create", "achievement.admin_create" in actions, str(actions))
print()

# ══ 14. 非管理员不可操作协助接口 ══════════════════════════════
resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-status", headers=h_a,
                     json={"assistStatus": "contacting"}, timeout=10)
check("普通用户assist-status=403", resp.status_code == 403, f"got {resp.status_code}")
resp = requests.post(f"{BASE}/admin/cooperations/{intent_id_a}/assist-transition", headers=h_a,
                     json={"action": "cancel", "version": 99}, timeout=10)
check("普通用户assist-transition=403", resp.status_code == 403, f"got {resp.status_code}")

# ── 清理（事件→意向→需求/成果→机构；audit_log 为追加型证据保留） ──
db_exec(
    "DELETE FROM cooperation_event WHERE intent_id IN (SELECT id FROM cooperation_intent WHERE "
    "initiator_user_id IN (%s, %s) OR target_owner_user_id IN (%s, %s))",
    (user_a["userId"], user_b["userId"], user_a["userId"], user_b["userId"]),
)
db_exec(
    "DELETE FROM cooperation_intent WHERE initiator_user_id IN (%s, %s) OR target_owner_user_id IN (%s, %s)",
    (user_a["userId"], user_b["userId"], user_a["userId"], user_b["userId"]),
)
db_exec("DELETE FROM demand WHERE title LIKE '协助对接%%'")
db_exec("DELETE FROM achievement WHERE title LIKE '协助对接%%'")
db_exec("DELETE FROM institution WHERE name LIKE '协助对接%%'")
db_exec(
    """
    UPDATE user_profile
    SET display_name=%s, phone=%s, email=%s, wechat=%s, org_title=%s
    WHERE user_id=%s
    """,
    (profile_b_before.get("display_name"), profile_b_before.get("phone"),
     profile_b_before.get("email"), profile_b_before.get("wechat"),
     profile_b_before.get("org_title"), user_b["userId"]),
)

row = db_one(
    "SELECT (SELECT COUNT(*) FROM demand WHERE status='pending_review' AND title LIKE '协助对接%%') AS d, "
    "(SELECT COUNT(*) FROM achievement WHERE status='pending_review' AND title LIKE '协助对接%%') AS a"
)
check("清理后审核队列无残留", (row["d"], row["a"]) == (0, 0), f"dmd={row['d']} ach={row['a']}")

# ── 结果 ─────────────────────────────────────────────────────
print()
print(f"=== 平台协助对接测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
