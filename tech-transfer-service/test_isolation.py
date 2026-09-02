"""
用户数据隔离测试 + 环境保护测试
"""
import requests
import subprocess
import sys
import os

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"

print("=" * 60)
print("测试 A: 用户数据隔离")
print("=" * 60)

# 1. Bootstrap user-001 (已有资料: 张三)
resp = requests.post(f"{BASE}/auth/bootstrap",
    json={"hostCredential": "local-dev-ticket-dev-user-001"}, timeout=10)
d1 = resp.json()["data"]
token1 = d1["accessToken"]
u1 = d1["user"]
print(f"\n[1] User-001: userId={u1['userId']}, userNo={u1['userNo']}, displayName={u1['displayName']}")

# 2. Bootstrap user-002 (新用户)
resp = requests.post(f"{BASE}/auth/bootstrap",
    json={"hostCredential": "local-dev-ticket-dev-user-002"}, timeout=10)
d2 = resp.json()["data"]
token2 = d2["accessToken"]
u2 = d2["user"]
print(f"[2] User-002: userId={u2['userId']}, userNo={u2['userNo']}, displayName={u2['displayName']}, isNewUser={d2['isNewUser']}")

# 3. User-002 修改自己的资料
resp = requests.patch(f"{BASE}/me/profile",
    json={"version": u2.get("version") or 1, "displayName": "李四", "userType": "investor", "phone": "13900000000"},
    headers={"Authorization": f"Bearer {token2}"}, timeout=10)
u2_updated = resp.json()["data"]
print(f"[3] User-002 PATCH: displayName={u2_updated['displayName']}, userType={u2_updated['userType']}")

# 4. User-001 查看自己的资料，应该还是张三
resp = requests.get(f"{BASE}/me",
    headers={"Authorization": f"Bearer {token1}"}, timeout=10)
u1_check = resp.json()["data"]
print(f"[4] User-001 GET /me: displayName={u1_check['displayName']} (expected: 张三)")

assert u1_check["displayName"] == "张三", f"FAIL: User-001 资料被篡改! expected=张三, actual={u1_check['displayName']}"
print(f"    -> PASS: User-001 资料未被 User-002 修改影响")

# 5. User-002 查看自己的资料，应该是李四
resp = requests.get(f"{BASE}/me",
    headers={"Authorization": f"Bearer {token2}"}, timeout=10)
u2_check = resp.json()["data"]
print(f"[5] User-002 GET /me: displayName={u2_check['displayName']} (expected: 李四)")

assert u2_check["displayName"] == "李四", f"FAIL: User-002 资料不对! expected=李四, actual={u2_check['displayName']}"
print(f"    -> PASS: User-002 资料正确隔离")

# 6. User-001 无法用 User-002 的 token 访问（不同 userId）
assert u1["userId"] != u2["userId"], "FAIL: 两个 Mock 身份映射到同一个 userId!"
print(f"[6] userId 隔离: User-001={u1['userId']}, User-002={u2['userId']} -> PASS")

# 7. User-001 的 token 不能操作 User-002 的资料
resp = requests.get(f"{BASE}/me",
    headers={"Authorization": f"Bearer {token1}"}, timeout=10)
u1_again = resp.json()["data"]
assert u1_again["userId"] == u1["userId"], "FAIL: token 跨用户!"
print(f"[7] Token 隔离: User-001 token 只返回 userId={u1_again['userId']} -> PASS")

print("\n" + "=" * 60)
print("测试 B: 环境保护（staging/prod 禁止 Mock）")
print("=" * 60)

# 测试 staging 环境下 Mock 启动应该失败
env = os.environ.copy()
env["APP_ENV"] = "staging"
env["HOST_MODE"] = "local"
env["AUTH_PROVIDER"] = "mock"
env["NO_PROXY"] = "pypi.tuna.tsinghua.edu.cn"

proc = subprocess.Popen(
    [sys.executable, "app.py"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
stdout, stderr = proc.communicate(timeout=10)
exit_code = proc.returncode

stderr_text = stderr.decode("utf-8", errors="replace")
print(f"\n[8] APP_ENV=staging, AUTH_PROVIDER=mock")
print(f"    exit_code={exit_code}")
print(f"    stderr={stderr_text.strip()[:200]}")

assert exit_code != 0, "FAIL: staging 环境下 Mock 不应该启动成功!"
assert "环境保护断言失败" in stderr_text or "FATAL" in stderr_text, "FAIL: 缺少 FATAL 错误信息"
print(f"    -> PASS: staging 环境 Mock 启动被正确拒绝")

# 测试 production 环境
env["APP_ENV"] = "production"
proc2 = subprocess.Popen(
    [sys.executable, "app.py"],
    cwd=os.path.dirname(os.path.abspath(__file__)),
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
)
stdout2, stderr2 = proc2.communicate(timeout=10)
exit_code2 = proc2.returncode
stderr_text2 = stderr2.decode("utf-8", errors="replace")

print(f"\n[9] APP_ENV=production, AUTH_PROVIDER=mock")
print(f"    exit_code={exit_code2}")
assert exit_code2 != 0, "FAIL: production 环境下 Mock 不应该启动成功!"
print(f"    -> PASS: production 环境 Mock 启动被正确拒绝")

print("\n" + "=" * 60)
print("ALL VERIFICATION TESTS PASSED")
print("=" * 60)
