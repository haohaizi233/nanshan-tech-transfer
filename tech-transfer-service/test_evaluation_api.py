"""
成果 AI 评估任务 API 测试（Phase C）
覆盖：创建任务（202/owner 403/成果不存在 404/非法参数 400）、
     去重（同成果 10 分钟窗口返回同 taskId 200）、
     查询（创建者可见 queued/evaluation=null、非创建者 403、不存在 404）、
     任务类型隔离（match 任务经 evaluation 端点查 404）、
     用户级限流 429（与 match 共享 5 次/小时）、
     审计 ai.task.create 落库（taskType=evaluation）、
     边界：无 worker 时任务保持 queued，ai_evaluation 表不产生任何假评分
依赖：后端已启动，013 迁移（ai_evaluation 表）已执行；routes/ai.py 中 AI_FEATURE_ENABLED=True
"""
import json
import time

import psycopg2
import psycopg2.extras
import requests
from config import settings

BASE = settings.API_BASE.rstrip("/") + settings.API_PREFIX
DB = dict(host=settings.DB_HOST, port=settings.DB_PORT, user=settings.DB_USER,
          password=settings.DB_PASSWORD, dbname=settings.DB_NAME)
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


def create_achievement(headers, title):
    resp = requests.post(f"{BASE}/achievements", headers=headers, json={
        "title": title, "maturityLevel": "02_lab", "pricingMode": "negotiable",
        "techIntro": "评估链路测试成果简介",
    }, timeout=10)
    return resp


token_a, user_a = bootstrap(f"local-dev-ticket-test-ai-eval-a-{_run}")
token_b, user_b = bootstrap(f"local-dev-ticket-test-ai-eval-b-{_run}")
h_a = {"Authorization": f"Bearer {token_a}"}
h_b = {"Authorization": f"Bearer {token_b}"}
print(f"[0] A={user_a['userId']} B={user_b['userId']}\n")

# 清理上轮残留（演示数据 owner<=3 保留；draft 不进审核队列，无 admin 污染）
db_exec("DELETE FROM achievement WHERE owner_user_id > 3 AND title LIKE '成果评估测试%%'")

# A 创建一个成果（draft 即可发起评估；快照固化）
resp = create_achievement(h_a, f"成果评估测试-AI-{_run}")
check("A 创建成果=201", resp.status_code == 201, f"got {resp.status_code} {resp.text[:120]}")
ach_id = resp.json()["data"]["id"]
print(f"[0] achievement={ach_id}\n")

# ── 1. 创建任务 ──────────────────────────────────────────────
resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": ach_id}, timeout=10)
check("创建返回202", resp.status_code == 202, f"got {resp.status_code}")
d = resp.json()["data"]
check("返回taskId", isinstance(d.get("taskId"), int))
check("初始status=queued", d.get("status") == "queued")
task_id = d["taskId"]

resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_b, json={"achievementId": ach_id}, timeout=10)
check("非owner创建=403", resp.status_code == 403, f"got {resp.status_code}")
check("错误码TT_ACH_40301", resp.json().get("code") == "TT_ACH_40301", resp.text[:100])

resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": 999999}, timeout=10)
check("成果不存在=404", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_ACH_40401", resp.json().get("code") == "TT_ACH_40401", resp.text[:100])

resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": "abc"}, timeout=10)
check("非法achievementId=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.post(f"{BASE}/ai/evaluation-tasks", json={"achievementId": 1}, timeout=10)
check("无Token创建=401", resp.status_code == 401)
print()

# ── 2. 去重（同成果 10 分钟窗口） ─────────────────────────────
resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": ach_id}, timeout=10)
check("重复创建返回200（去重）", resp.status_code == 200, f"got {resp.status_code}")
check("去重返回同taskId", resp.json()["data"]["taskId"] == task_id)
check("去重返回进行中status", resp.json()["data"]["status"] == "queued")
print()

# ── 3. 查询任务 ──────────────────────────────────────────────
resp = requests.get(f"{BASE}/ai/evaluation-tasks/{task_id}", headers=h_a, timeout=10)
check("创建者查询=200", resp.status_code == 200)
d = resp.json()["data"]
check("taskId一致", d["taskId"] == task_id)
check("status=queued", d["status"] == "queued")
check("queued时evaluation=null（无假评分）", d["evaluation"] is None, f"got {d['evaluation']}")
check("有inputDataVersion（快照哈希）", isinstance(d.get("inputDataVersion"), str) and len(d["inputDataVersion"]) == 16)
check("有createdAt", bool(d.get("createdAt")))
check("finishedAt=null", d.get("finishedAt") is None)
check("failReason=null", d.get("failReason") is None)

resp = requests.get(f"{BASE}/ai/evaluation-tasks/{task_id}", headers=h_b, timeout=10)
check("非创建者查询=403", resp.status_code == 403)
check("错误码TT_AI_40301", resp.json().get("code") == "TT_AI_40301", resp.text[:100])

resp = requests.get(f"{BASE}/ai/evaluation-tasks/999999", headers=h_a, timeout=10)
check("任务不存在=404", resp.status_code == 404)
check("错误码TT_AI_40401", resp.json().get("code") == "TT_AI_40401", resp.text[:100])

resp = requests.get(f"{BASE}/ai/evaluation-tasks/{task_id}", timeout=10)
check("无Token查询=401", resp.status_code == 401)
print()

# ── 4. 任务类型隔离（match ≠ evaluation） ────────────────────
resp = requests.post(f"{BASE}/demands", headers=h_b, json={
    "title": "评估隔离测试需求", "description": "x", "contactPhone": "13600009999",
}, timeout=10)
b_demand_id = resp.json()["data"]["id"]
resp = requests.post(f"{BASE}/ai/match-tasks", headers=h_b, json={"demandId": b_demand_id}, timeout=10)
b_match_task_id = resp.json()["data"]["taskId"]
resp = requests.get(f"{BASE}/ai/evaluation-tasks/{b_match_task_id}", headers=h_b, timeout=10)
check("match任务经evaluation端点查=404（类型隔离）", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_AI_40401", resp.json().get("code") == "TT_AI_40401", resp.text[:100])
print()

# ── 5. 用户级限流（5 次/小时，与 match 共享） ─────────────────
# A 已新建 1 个评估任务；再建 4 个不同成果任务 → 第 6 个应 429
created = 0
for i in range(4):
    r = create_achievement(h_a, f"成果评估测试-限流{i}-{_run}")
    aid = r.json()["data"]["id"]
    r = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": aid}, timeout=10)
    if r.status_code == 202:
        created += 1
check("限流前还能创建4个", created == 4, f"created {created}")

r = create_achievement(h_a, f"成果评估测试-限流触发-{_run}")
rate_ach_id = r.json()["data"]["id"]
resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": rate_ach_id}, timeout=10)
check("超过5次/小时=429", resp.status_code == 429, f"got {resp.status_code}")
check("错误码TT_AI_42901", resp.json().get("code") == "TT_AI_42901", resp.text[:100])

resp = requests.get(f"{BASE}/ai/evaluation-tasks/{task_id}", headers=h_a, timeout=10)
check("限流不影响查询", resp.status_code == 200)
print()

# ── 6. 审计落库 ──────────────────────────────────────────────
rows = db_query(
    "SELECT details FROM audit_log WHERE action='ai.task.create' AND resource_id=%s",
    (str(task_id),),
)
check("审计含ai.task.create", len(rows) >= 1, f"got {len(rows)}")
if rows:
    details = rows[0]["details"]
    if isinstance(details, str):
        details = json.loads(details)
    check("审计details.taskType=evaluation", details.get("taskType") == "evaluation", f"got {details}")
    check("审计details.achievementId", details.get("achievementId") == ach_id, f"got {details}")
print()

# ── 7. 无假评分边界（worker 未接入） ─────────────────────────
rows = db_query(
    "SELECT COUNT(*) AS n FROM ai_evaluation e JOIN ai_task t ON e.task_id=t.id WHERE t.created_by_user_id=%s",
    (user_a["userId"],),
)
check("ai_evaluation无假评分行", rows[0]["n"] == 0, f"got {rows[0]['n']}")
print()

# ── 结果 ─────────────────────────────────────────────────────
print(f"=== 成果 AI 评估任务 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
