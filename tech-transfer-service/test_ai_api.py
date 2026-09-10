"""
AI 域 API 测试（P0-2）
覆盖：创建任务（202/owner 403/需求不存在 404/非法参数 400）、
     去重（同需求 10 分钟窗口返回同 taskId 200）、
     用户级限流 429、查询（创建者可见 queued/results=null、非创建者 403、
     不存在 404）、审计 ai.task.create 落库
依赖：后端已启动，004 迁移已执行；routes/ai.py 中 AI_FEATURE_ENABLED=True
边界验证：无 worker 时任务保持 queued，GET results 恒为 null（禁止假 AI）
"""
import time

import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
PASS = 0
FAIL = 0

# 限流是进程内计数（1 小时窗口），每轮测试用新身份避免跨轮残留
_run = int(time.time())


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


token_a, user_a = bootstrap(f"local-dev-ticket-test-ai-a-{_run}")
token_b, user_b = bootstrap(f"local-dev-ticket-test-ai-b-{_run}")
h_a = {"Authorization": f"Bearer {token_a}"}
h_b = {"Authorization": f"Bearer {token_b}"}
print(f"[0] A={user_a['userId']} B={user_b['userId']}\n")

# A 创建一个需求（draft 亦可发起匹配；快照固化）
resp = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": "AI匹配测试需求", "description": "测试AI匹配任务边界",
    "orgName": "测试组织-AI", "contactPhone": "13600009999", "contactName": "测试A",
}, timeout=10)
demand_id = resp.json()["data"]["id"]
print(f"[0] demand={demand_id}\n")

# ── 1. 创建任务 ──────────────────────────────────────────────
resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": demand_id}, timeout=10)
check("创建返回202", resp.status_code == 202, f"got {resp.status_code}")
d = resp.json()["data"]
check("返回taskId", isinstance(d.get("taskId"), int))
check("初始status=queued", d.get("status") == "queued")
task_id = d["taskId"]

resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_b, json={"demandId": demand_id}, timeout=10)
check("非owner创建=403", resp.status_code == 403, f"got {resp.status_code}")
check("错误码TT_DMD_40301", resp.json().get("code") == "TT_DMD_40301", resp.text[:100])

resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": 999999}, timeout=10)
check("需求不存在=404", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_DMD_40401", resp.json().get("code") == "TT_DMD_40401", resp.text[:100])

resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": "abc"}, timeout=10)
check("非法demandId=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.post(f"{BASE}/ai/match-tasks", json={"demandId": 1}, timeout=10)
check("无Token创建=401", resp.status_code == 401)
print()

# ── 2. 去重（同需求 10 分钟窗口） ─────────────────────────────
resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": demand_id}, timeout=10)
check("重复创建返回200（去重）", resp.status_code == 200, f"got {resp.status_code}")
check("去重返回同taskId", resp.json()["data"]["taskId"] == task_id)
check("去重返回进行中status", resp.json()["data"]["status"] == "queued")
print()

# ── 3. 查询任务 ──────────────────────────────────────────────
resp = requests.get(f"{BASE}/ai/match-tasks/{task_id}", headers=h_a, timeout=10)
check("创建者查询=200", resp.status_code == 200)
d = resp.json()["data"]
check("taskId一致", d["taskId"] == task_id)
check("status=queued", d["status"] == "queued")
check("queued时results=null（无假AI）", d["results"] is None, f"got {d['results']}")
check("有inputDataVersion（快照哈希）", isinstance(d.get("inputDataVersion"), str) and len(d["inputDataVersion"]) == 16)
check("有createdAt", bool(d.get("createdAt")))
check("finishedAt=null", d.get("finishedAt") is None)
check("failReason=null", d.get("failReason") is None)

resp = requests.get(f"{BASE}/ai/match-tasks/{task_id}", headers=h_b, timeout=10)
check("非创建者查询=403", resp.status_code == 403)
check("错误码TT_AI_40301", resp.json().get("code") == "TT_AI_40301", resp.text[:100])

resp = requests.get(f"{BASE}/ai/match-tasks/999999", headers=h_a, timeout=10)
check("任务不存在=404", resp.status_code == 404)
check("错误码TT_AI_40401", resp.json().get("code") == "TT_AI_40401", resp.text[:100])

resp = requests.get(f"{BASE}/ai/match-tasks/{task_id}", timeout=10)
check("无Token查询=401", resp.status_code == 401)
print()

# ── 4. 用户级限流（5 次/小时） ───────────────────────────────
# A 已创建 1 个任务；再创建 4 个不同需求任务 → 第 5 个成功后第 6 个应 429
created = 0
for i in range(4):
    r = requests.post(f"{BASE}/demands", headers=h_a, json={
        "title": f"限流测试需求{i}", "description": "x", "contactPhone": "13600009999",
    }, timeout=10)
    did = r.json()["data"]["id"]
    r = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": did}, timeout=10)
    if r.status_code == 202:
        created += 1
check("限流前还能创建4个", created == 4, f"created {created}")

r = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": "限流触发需求", "description": "x", "contactPhone": "13600009999",
}, timeout=10)
rate_demand_id = r.json()["data"]["id"]
resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_a, json={"demandId": rate_demand_id}, timeout=10)
check("超过5次/小时=429", resp.status_code == 429, f"got {resp.status_code}")
check("错误码TT_AI_42901", resp.json().get("code") == "TT_AI_42901", resp.text[:100])

resp = requests.get(f"{BASE}/ai/match-tasks/{task_id}", headers=h_a, timeout=10)
check("限流不影响查询", resp.status_code == 200)
print()

# ── 5. 审计落库 ──────────────────────────────────────────────
import psycopg2
import psycopg2.extras
conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres",
                        password="postgres123", dbname="tech_transfer")
try:
    with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(
            "SELECT COUNT(*) AS n FROM audit_log WHERE action='ai.task.create' AND resource_id=%s",
            (str(task_id),),
        )
        n = cur.fetchone()["n"]
finally:
    conn.close()
check("审计含ai.task.create", n >= 1, f"got {n}")
print()

# ── 结果 ─────────────────────────────────────────────────────
print(f"=== AI 域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
