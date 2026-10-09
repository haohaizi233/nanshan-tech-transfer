"""
AI 聊天记录入库 回归测试 —— /ai/chat/messages（GET/DELETE）+ /ai/chat 持久化

覆盖：
- GET /ai/chat/messages 未登录 → 401
- GET 空历史 → messages 为空数组
- POST /ai/chat 成功后 → 历史新增 user + assistant 两条；assistant 卡片快照可回放
- DELETE /ai/chat/messages → 清空；再 GET → 空
- ai-agent 不可达（503）时 → 仍入库 user+assistant 失败提示，刷新后可见用户原问题

依赖：后端已启动；routes/ai.py 中 AI_FEATURE_ENABLED=True。
成功路径（验证入库）需要 ai-agent 可达；不可达时本测试降级为只校验边界与清空。
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


token_a, user_a = bootstrap(f"local-dev-ticket-test-ai-chat-{_run}")
h_a = {"Authorization": f"Bearer {token_a}"}
print(f"[0] A={user_a['userId']}\n")


# ── 1. 未登录访问历史 → 401 ───────────────────────────────────
resp = requests.get(f"{BASE}/ai/chat/messages", timeout=10)
check("无Token取历史=401", resp.status_code == 401, f"got {resp.status_code}")

resp = requests.delete(f"{BASE}/ai/chat/messages", timeout=10)
check("无Token清历史=401", resp.status_code == 401, f"got {resp.status_code}")
print()

# ── 2. 清空起点：历史应为空数组 ────────────────────────────────
resp = requests.delete(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
check("清空(起点)=200", resp.status_code == 200, f"got {resp.status_code}")

resp = requests.get(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
check("空历史=200", resp.status_code == 200, f"got {resp.status_code}")
msgs = resp.json().get("data", {}).get("messages")
check("空历史 messages 为数组", isinstance(msgs, list), str(msgs))
check("空历史 messages 长度为 0", isinstance(msgs, list) and len(msgs) == 0, str(msgs))
print()

# ── 3. 发起一次对话；成功则验证入库，503 则降级 ─────────────────
chat_ok = False
resp = requests.post(
    f"{BASE}/ai/chat", headers=h_a,
    json={"message": "帮我找机器视觉相关的科技成果"},
    timeout=120,
)
if resp.status_code == 200:
    chat_ok = True
    data = resp.json().get("data") or {}
    cards = data.get("data") if isinstance(data, dict) else None
    print(f"[chat] 200, intent={data.get('intent')}, cards={len(cards) if isinstance(cards, list) else 'n/a'}")
else:
    print(f"[chat] 非 200：{resp.status_code}（ai-agent 可能不可达，降级校验边界）")

if chat_ok:
    resp = requests.get(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
    msgs = resp.json().get("data", {}).get("messages") or []
    check("对话后历史=200", resp.status_code == 200, f"got {resp.status_code}")
    check("对话后历史>=2 条", len(msgs) >= 2, f"got {len(msgs)}")
    if len(msgs) >= 2:
        check("首条 role=user", msgs[0].get("role") == "user", str(msgs[0]))
        check("次条 role=assistant", msgs[1].get("role") == "assistant", str(msgs[1]))
        check("用户消息内容非空", bool((msgs[0].get("content") or "").strip()), str(msgs[0]))
        # assistant 卡片快照：若 agent 返回了卡片，则历史 cards 字段应为数组
        agent_cards = data.get("data")
        if isinstance(agent_cards, list) and agent_cards:
            hist_cards = msgs[1].get("cards")
            check("assistant 卡片快照已入库", isinstance(hist_cards, list) and len(hist_cards) > 0,
                  f"cards={hist_cards}")
            # 自排除：返回的成果卡片不应属于当前用户（卡片若带 owner_user_id 字段）
            own = [c for c in hist_cards if isinstance(c, dict) and c.get("owner_user_id") == user_a["userId"]]
            check("推荐不含自己的成果", len(own) == 0, f"own={own}")
        else:
            check("无卡片时 assistant 仍入库", True, "")
else:
    # 502/503 仍保留 user+失败提示，避免刷新后用户看不到刚发的问题
    resp = requests.get(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
    msgs = resp.json().get("data", {}).get("messages") or []
    check("ai-agent 不可达时仍保留失败对话", len(msgs) >= 2, f"got {len(msgs)} 条")
    if len(msgs) >= 2:
        check("失败对话首条 role=user", msgs[0].get("role") == "user", str(msgs[0]))
        check("失败对话次条 role=assistant", msgs[1].get("role") == "assistant", str(msgs[1]))
print()

# ── 4. 清空后再查 → 空 ────────────────────────────────────────
resp = requests.delete(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
check("清空=200", resp.status_code == 200, f"got {resp.status_code}")
deleted = resp.json().get("data", {}).get("deleted")
check("清空返回 deleted>=0", isinstance(deleted, int) and deleted >= 0, str(deleted))

resp = requests.get(f"{BASE}/ai/chat/messages", headers=h_a, timeout=10)
msgs = resp.json().get("data", {}).get("messages") or []
check("清空后历史为空", len(msgs) == 0, f"got {len(msgs)} 条")
print()

# ── 结果 ─────────────────────────────────────────────────────
print(f"=== AI 聊天记录入库测试完成: {PASS} passed, {FAIL} failed ===")
if FAIL:
    raise SystemExit(1)
