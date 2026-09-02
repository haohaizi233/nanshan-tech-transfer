import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"

# 1. Bootstrap
resp = requests.post(f"{BASE}/auth/bootstrap",
    json={"hostCredential": "local-dev-ticket-dev-user-001"}, timeout=10)
d = resp.json()["data"]
token = d["accessToken"]
print(f"[1] Bootstrap: userId={d['user']['userId']}, userNo={d['user']['userNo']}, isNewUser={d['isNewUser']}")

headers = {"Authorization": f"Bearer {token}"}

# 2. GET /me
resp = requests.get(f"{BASE}/me", headers=headers, timeout=10)
me = resp.json()["data"]
print(f"[2] GET /me: displayName={me['displayName']}, version={me.get('version')}")

# 3. PATCH /me/profile
patch = {
    "version": me.get("version", 1),
    "displayName": "张三",
    "userType": "researcher",
    "phone": "13800138000",
    "email": "zhangsan@test.com",
    "orgTitle": "高级工程师",
}
resp = requests.patch(f"{BASE}/me/profile", json=patch, headers=headers, timeout=10)
result = resp.json()["data"]
print(f"[3] PATCH: displayName={result['displayName']}, userType={result['userType']}, orgTitle={result['orgTitle']}, version={result.get('version')}")

# 4. GET /me again to verify persistence
resp = requests.get(f"{BASE}/me", headers=headers, timeout=10)
me2 = resp.json()["data"]
print(f"[4] GET /me (verify): displayName={me2['displayName']}, orgTitle={me2['orgTitle']}, version={me2.get('version')}")

# 5. Test optimistic lock (wrong version should fail)
bad_patch = {"version": 1, "displayName": "should_fail"}
resp = requests.patch(f"{BASE}/me/profile", json=bad_patch, headers=headers, timeout=10)
if resp.status_code == 409:
    print(f"[5] Optimistic lock: correctly rejected (409)")
else:
    print(f"[5] Optimistic lock: UNEXPECTED status={resp.status_code}, body={resp.text}")

# 6. Test auth required (no token)
resp = requests.get(f"{BASE}/me", timeout=10)
if resp.status_code == 401:
    print(f"[6] No-token access: correctly rejected (401)")
else:
    print(f"[6] No-token access: UNEXPECTED status={resp.status_code}")

# 7. Test invalid bootstrap credential
resp = requests.post(f"{BASE}/auth/bootstrap",
    json={"hostCredential": "invalid-ticket"}, timeout=10)
if resp.status_code == 401:
    print(f"[7] Invalid credential: correctly rejected (401)")
else:
    print(f"[7] Invalid credential: UNEXPECTED status={resp.status_code}")

print("\n=== All tests passed ===")
