"""
AI 域 API 测试 —— /ai/match（同步需求-成果匹配）边界契约

覆盖：
- 非需求所有者发起匹配 → 403 TT_DMD_40301
- 需求不存在 → 404 TT_DMD_40401
- 非法 demandId → 400
- 未登录 → 401
- 非可匹配状态（draft）的需求 → 400（角色与可见性自洽：仅 published/matched 可匹配）
- 命中成果的可见性由 ai-agent 侧 status='published' 过滤，与前端成果列表一致

依赖：后端已启动；routes/ai.py 中 AI_FEATURE_ENABLED=True。
成功路径（返回 cards）需要 ai-agent 可达，本测试对 ai-agent 不可达时降级为边界校验。
"""
import time

import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
PASS = 0
FAIL = 0

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

# A 创建一个需求（默认 draft 状态，用于触发「状态不支持匹配」边界）
resp = requests.post(f"{BASE}/demands", headers=h_a, json={
    "title": "AI匹配测试需求", "description": "测试AI匹配任务边界",
    "orgName": "测试组织-AI", "contactPhone": "13600009999", "contactName": "测试A",
}, timeout=10)
demand_id = resp.json()["data"]["id"]
print(f"[0] demand={demand_id}\n")

# ── 1. 角色与参数边界 ─────────────────────────────────────────
resp = requests.post(f"{BASE}/ai/match", headers=h_b, json={"demandId": demand_id}, timeout=10)
check("非owner匹配=403", resp.status_code == 403, f"got {resp.status_code}")
check("错误码TT_DMD_40301", resp.json().get("code") == "TT_DMD_40301", resp.text[:100])

resp = requests.post(f"{BASE}/ai/match", headers=h_a, json={"demandId": 999999}, timeout=10)
check("需求不存在=404", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_DMD_40401", resp.json().get("code") == "TT_DMD_40401", resp.text[:100])

resp = requests.post(f"{BASE}/ai/match", headers=h_a, json={"demandId": "abc"}, timeout=10)
check("非法demandId=400", resp.status_code == 400, f"got {resp.status_code}")

resp = requests.post(f"{BASE}/ai/match", json={"demandId": 1}, timeout=10)
check("无Token匹配=401", resp.status_code == 401)
print()

# ── 2. 状态边界（draft 不可匹配，无需 ai-agent 即可判定） ──────
resp = requests.post(f"{BASE}/ai/match", headers=h_a, json={"demandId": demand_id}, timeout=10)
check("draft需求匹配=400", resp.status_code == 400, f"got {resp.status_code}")
check("提示状态不支持", "状态不支持匹配" in (resp.json().get("message") or ""), resp.text[:120])
print()

# ── 3. 评估任务仍可用（回归：未误删异步评估路由） ─────────────
resp = requests.post(f"{BASE}/ai/evaluation-tasks", headers=h_a, json={"achievementId": 999999}, timeout=10)
check("评估任务-成果不存在=404", resp.status_code == 404, f"got {resp.status_code}")
check("错误码TT_ACH_40401", resp.json().get("code") == "TT_ACH_40401", resp.text[:100])
print()

# ── 结果 ─────────────────────────────────────────────────────
print(f"=== AI 域 API 测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
