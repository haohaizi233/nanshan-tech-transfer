"""
T008 统一错误契约测试

验证所有错误路径输出统一结构：
    {"code": "TT_*", "message": str, "requestId": str, "details": 可选}
且任何错误响应不泄露 traceback / SQL / 内部路径 / 连接串 / 密钥。

结构：
  Part 1 —— 针对 live server（127.0.0.1:8787，需先启动后端）
  Part 2 —— 进程内 TestClient + monkeypatch（500/503/409-DB 场景，
             无需真实触发故障，不留 /debug 路由）

运行：python test_error_contract.py（服务根目录，后端需已启动，APP_ENV=local）
"""
import sys

import psycopg2
import requests

BASE = "http://127.0.0.1:8787"
API = f"{BASE}/api/tech-transfer/v1"

PASS = 0
FAIL = 0
# 收集所有错误响应文本，最后统一做敏感信息泄露扫描
ALL_ERROR_BODIES = []


def check(name, ok, detail=""):
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} — {detail}")


def assert_error_contract(resp, expected_status, expected_code=None):
    """统一错误契约断言（§33）：结构 + 禁泄字段。返回 body 供进一步断言。"""
    body = resp.json() if resp.text else {}
    ALL_ERROR_BODIES.append(resp.text)
    problems = []
    if resp.status_code != expected_status:
        problems.append(f"status={resp.status_code} 期望 {expected_status}")
    if not isinstance(body.get("code"), str):
        problems.append(f"code 非字符串: {body.get('code')!r}")
    if expected_code and body.get("code") != expected_code:
        problems.append(f"code={body.get('code')} 期望 {expected_code}")
    if not isinstance(body.get("message"), str) or not body.get("message"):
        problems.append(f"message 非法: {body.get('message')!r}")
    if not body.get("requestId"):
        problems.append("缺少 requestId")
    ctype = resp.headers.get("Content-Type", "")
    if "application/json" not in ctype:
        problems.append(f"Content-Type={ctype}")
    check(f"错误契约 {expected_status} {expected_code or ''}".strip(),
          not problems, "; ".join(problems) + f" | body={resp.text[:160]}")
    return body


def bootstrap(ticket):
    resp = requests.post(f"{API}/auth/bootstrap", json={"hostCredential": ticket}, timeout=10)
    assert resp.status_code == 200, f"bootstrap 失败: {resp.status_code} {resp.text[:200]}"
    return resp.json()["data"]["accessToken"]


# ════════════════════════════════════════════════════════════
# Part 1 —— live server 场景
# ════════════════════════════════════════════════════════════
print("=" * 60)
print("Part 1: live server 错误契约（127.0.0.1:8787）")
print("=" * 60)

try:
    health = requests.get(f"{BASE}/api/health", timeout=5)
except requests.RequestException as e:
    print(f"\n[ABORT] 后端未启动（{e}）。请先运行 start_dev.py 或 python app.py")
    sys.exit(1)

print("\n[0] 基础端点不受异常层影响")
check("GET /api/health = 200 code=0", health.status_code == 200 and health.json().get("code") == 0,
      health.text[:120])
liveness = requests.get(f"{BASE}/health", timeout=5)
check("GET /health = 200 code=0", liveness.status_code == 200 and liveness.json().get("code") == 0,
      liveness.text[:120])
resp = requests.get(f"{BASE}/docs", timeout=10)
check("GET /docs = 200", resp.status_code == 200, f"got {resp.status_code}")
resp = requests.get(f"{BASE}/openapi.json", timeout=10)
check("GET /openapi.json = 200", resp.status_code == 200, f"got {resp.status_code}")

print("\n[1] 未知路由 → 404 统一结构（非 FastAPI 裸 detail）")
resp = requests.get(f"{BASE}/api/not-exists", timeout=10)
body = assert_error_contract(resp, 404, "TT_COMMON_40401")
check("无裸 detail 字段", "detail" not in body, f"body={body}")

print("\n[2] Method Not Allowed → 405 统一结构")
resp = requests.post(f"{BASE}/api/health", timeout=10)
body = assert_error_contract(resp, 405, "TT_COMMON_40501")
check("无裸 detail 字段", "detail" not in body, f"body={body}")

print("\n[3] 路径参数类型不匹配（Flask <int:> 兼容）→ 404")
# 带 token：否则 identity 依赖先抛 401，轮不到路径参数校验
token_user = bootstrap("local-dev-ticket-dev-user-002")
resp = requests.get(f"{API}/demands/abc",
                    headers={"Authorization": f"Bearer {token_user}"}, timeout=10)
assert_error_contract(resp, 404, "TT_COMMON_40401")

print("\n[4] 422 Body Validation（Pydantic）→ 统一结构 + 安全 details")
token_admin = bootstrap("local-dev-ticket-dev-user-001")
resp = requests.post(f"{API}/admin/institutions",
                     headers={"Authorization": f"Bearer {token_admin}"},
                     json={"kind": "invest"}, timeout=10)
body = assert_error_contract(resp, 422, "TT_COMMON_42201")
details = body.get("details")
check("details 含字段名 name", isinstance(details, list) and details
      and details[0].get("field") == "name", f"details={details}")
check("details 不含请求体原文", "kind" not in resp.text.replace('"kind"', ""),
      resp.text[:200])

print("\n[5] 缺 Token → 401 统一结构")
resp = requests.get(f"{API}/demands", timeout=10)
assert_error_contract(resp, 401, "TT_COMMON_40101")

print("\n[6] 普通用户访问 Admin → 403 统一结构")
resp = requests.get(f"{API}/admin/dashboard/summary",
                    headers={"Authorization": f"Bearer {token_user}"}, timeout=10)
assert_error_contract(resp, 403, "TT_ADMIN_40301")

print("\n[7] 业务对象不存在（域级 404）")
resp = requests.get(f"{API}/demands/999999999",
                    headers={"Authorization": f"Bearer {token_user}"}, timeout=10)
assert_error_contract(resp, 404, "TT_DMD_40401")

print("\n[8] 状态机非法转换 → 409")
# 自愈清理：驳回历史运行遗留的 pending_review 测试需求，避免污染 admin 审核队列
resp = requests.get(f"{API}/admin/demands/review-queue",
                    headers={"Authorization": f"Bearer {token_admin}"},
                    params={"page": 1, "pageSize": 100}, timeout=10)
for item in (resp.json().get("data", {}).get("list") or []):
    if "T008错误契约测试需求" in (item.get("title") or ""):
        requests.post(f"{API}/admin/demands/{item['id']}/reject",
                      headers={"Authorization": f"Bearer {token_admin}"},
                      json={"version": item.get("version"), "reason": "T008测试数据清理"},
                      timeout=10)
resp = requests.post(f"{API}/demands", headers={"Authorization": f"Bearer {token_user}"},
                     json={"title": "T008错误契约测试需求", "description": "x",
                           "contactPhone": "13600009999"}, timeout=10)
check("创建需求=201", resp.status_code == 201, f"got {resp.status_code}: {resp.text[:120]}")
demand_id = resp.json()["data"]["id"]
version = resp.json()["data"].get("version") or 1
resp = requests.post(f"{API}/demands/{demand_id}/submit",
                     headers={"Authorization": f"Bearer {token_user}"},
                     json={"version": version}, timeout=10)
check("submit=200", resp.status_code == 200, f"got {resp.status_code}: {resp.text[:120]}")
version = resp.json()["data"].get("version") or version + 1
resp = requests.post(f"{API}/demands/{demand_id}/submit",
                     headers={"Authorization": f"Bearer {token_user}"},
                     json={"version": version}, timeout=10)
assert_error_contract(resp, 409, "TT_DMD_40901")
# 立即清理：驳回本条测试需求，保持 admin 审核队列无污染
requests.post(f"{API}/admin/demands/{demand_id}/reject",
              headers={"Authorization": f"Bearer {token_admin}"},
              json={"version": version, "reason": "T008测试数据清理"}, timeout=10)

print("\n[9] 文件代理错误 → 统一结构（原 {code:1,msg} 并行格式已收敛）")
resp = requests.get(f"{BASE}/api/file/%21%21", timeout=10)  # '!!' 清洗后为空 id
assert_error_contract(resp, 400, "TT_FILE_40001")

print("\n[10] Request ID 链路")
rid = "t008-req-id-abcd1234"
resp = requests.get(f"{BASE}/api/not-exists", headers={"X-Request-Id": rid}, timeout=10)
check("合法入站 X-Request-Id 被复用", resp.headers.get("X-Request-Id") == rid,
      f"header={resp.headers.get('X-Request-Id')}")
check("响应体 requestId 与头一致", resp.json().get("requestId") == rid,
      f"body={resp.json().get('requestId')}")
resp = requests.get(f"{BASE}/api/not-exists",
                    headers={"X-Request-Id": "!! bad id !!" + "x" * 100}, timeout=10)
gen = resp.headers.get("X-Request-Id", "")
check("非法入站 ID 被替换为服务端生成", gen and gen != rid and len(gen) == 32,
      f"header={gen!r}")
check("成功响应也带 X-Request-Id 头",
      requests.get(f"{BASE}/api/health", timeout=10).headers.get("X-Request-Id") is not None)

print("\n[11] CORS 预检不受异常层影响")
resp = requests.options(f"{API}/achievements",
                        headers={"Origin": "http://localhost:5173",
                                 "Access-Control-Request-Method": "GET",
                                 "Access-Control-Request-Headers": "authorization,content-type"},
                        timeout=10)
check("OPTIONS 预检 = 200", resp.status_code == 200, f"got {resp.status_code}")

# ════════════════════════════════════════════════════════════
# Part 2 —— 进程内 monkeypatch（500 / DB 503 / DB 409）
# ════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("Part 2: 进程内异常注入（TestClient + monkeypatch，不留 debug 路由）")
print("=" * 60)

import app as app_module  # noqa: E402
import routes.demand as demand_route  # noqa: E402
import db as db_module  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from core.jwt_utils import sign_access_token  # noqa: E402

client = TestClient(app_module.app, raise_server_exceptions=False)
inproc_token = sign_access_token(2, "local-dev-user-002", ["user"])
H = {"Authorization": f"Bearer {inproc_token}"}
_ORIG = demand_route.get_demand_detail
_ORIG_CONN = db_module._acquire_conn


def _restore():
    demand_route.get_demand_detail = _ORIG
    db_module._acquire_conn = _ORIG_CONN


print("\n[12] 未捕获异常 → 500 固定文案，无泄露")
_sensitive = RuntimeError("sensitive internal error: password=postgres123 C:\\Users\\admin secret")
demand_route.get_demand_detail = lambda *a, **k: (_ for _ in ()).throw(_sensitive)
try:
    resp = client.get(f"{API}/demands/1", headers=H)
finally:
    _restore()
body = assert_error_contract(resp, 500, "TT_COMMON_50001")
check("500 响应带 X-Request-Id 头", bool(resp.headers.get("X-Request-Id")),
      f"headers={dict(resp.headers)}")
check("500 响应头与体 requestId 一致",
      resp.headers.get("X-Request-Id") == body.get("requestId"),
      f"header={resp.headers.get('X-Request-Id')} body={body.get('requestId')}")

print("\n[13] DB 连接故障（OperationalError）→ 503，无连接信息泄露")
_db_msg = ('connection to server at "127.0.0.1", port 5432 failed: '
           'FATAL: password authentication failed for user "postgres"')


def _broken_conn():
    raise psycopg2.OperationalError(_db_msg)


db_module._acquire_conn = _broken_conn
try:
    resp = client.get(f"{API}/demands/1", headers=H)
finally:
    _restore()
assert_error_contract(resp, 503, "TT_COMMON_50301")
check("503 不泄露连接串/端口/用户名",
      all(s not in resp.text for s in ("password authentication", "5432", "postgres")),
      resp.text[:200])

print("\n[14] 唯一约束竞态（UniqueViolation）→ 409，无 SQL/约束名泄露")
demand_route.get_demand_detail = lambda *a, **k: (_ for _ in ()).throw(
    psycopg2.errors.UniqueViolation(
        'duplicate key value violates unique constraint "favorite_unique" '
        "INSERT INTO favorite ... VALUES ('secret')")
)
try:
    resp = client.get(f"{API}/demands/1", headers=H)
finally:
    _restore()
assert_error_contract(resp, 409, "TT_COMMON_40903")
check("409 不泄露约束名/SQL", "favorite_unique" not in resp.text and "INSERT" not in resp.text,
      resp.text[:200])

print("\n[15] 进程内鉴权错误契约一致性（401）")
resp = client.get(f"{API}/demands")
assert_error_contract(resp, 401, "TT_COMMON_40101")

# ════════════════════════════════════════════════════════════
# 敏感信息全局扫描
# ════════════════════════════════════════════════════════════
print()
print("=" * 60)
print("全局敏感信息泄露扫描（所有错误响应体）")
print("=" * 60)
FORBIDDEN = ["Traceback", "psycopg2", "C:\\Users\\", "postgres123", "JWT_SECRET",
             "RuntimeError", "sensitive internal error", "password authentication",
             "INSERT INTO", "duplicate key"]
leaked = []
for raw in ALL_ERROR_BODIES:
    for word in FORBIDDEN:
        if word in raw:
            leaked.append(word)
check(f"全部 {len(ALL_ERROR_BODIES)} 个错误响应无敏感泄露", not leaked,
      f"泄露关键词: {sorted(set(leaked))}")

print()
print(f"=== T008 错误契约测试: {PASS} passed, {FAIL} failed ===")
sys.exit(1 if FAIL else 0)
