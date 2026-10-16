"""
/auth/register + /auth/login 认证接口测试

覆盖：
1. 正常注册：创建 app_user/profile/role/credential 全套，直接签发会话
2. 重复注册：TT_AUTH_40901
3. 参数校验：非法手机号 / 短密码 → TT_COMMON_40001
4. 注册后立即可用 /auth/login 登录（小程序端 phone 字段）
5. 注册会话可直接调 /me 且身份正确（userId 对应新用户）
6. 数据隔离：两个注册用户各看各的 /me/favorites
7. 后台 username 注册：username 登录（后台）+ phone 登录（小程序）双通道
8. 后台注册手机号与小程序账号冲突 → 409

注意：使用固定手机号 13911111111 / 13922222222 / 13933333333，重跑前需先
运行 cleanup_auth_register_fixture.py 清理上一轮注册用户（五表按 phone
定位 user_id 后删除），否则首轮"注册返回200"会因重复注册失败。
"""

import sys
import uuid

import requests

BASE = "http://127.0.0.1:8787/api/tech-transfer/v1"
PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"[PASS] {name}")
    else:
        FAIL += 1
        print(f"[FAIL] {name} {detail}")


def register(phone, password):
    return requests.post(
        f"{BASE}/auth/register",
        json={"phone": phone, "password": password},
        timeout=10,
        proxies={"http": None, "https": None},
    )


def login_phone(phone, password):
    return requests.post(
        f"{BASE}/auth/login",
        json={"phone": phone, "password": password},
        timeout=10,
        proxies={"http": None, "https": None},
    )


def login_username(username, password):
    return requests.post(
        f"{BASE}/auth/login",
        json={"username": username, "password": password},
        timeout=10,
        proxies={"http": None, "https": None},
    )


def main():
    suffix = uuid.uuid4().hex[:8]
    phone_a = "139" + "1" * 8
    phone_b = "139" + "2" * 8
    pwd = "pass123456"

    # 1. 正常注册
    r = register(phone_a, pwd)
    check("注册返回200", r.status_code == 200, r.text[:200])
    data = r.json()
    check("注册 code=0", data.get("code") == 0, r.text[:200])
    d = data.get("data") or {}
    check("注册返回 accessToken", bool(d.get("accessToken")))
    check("注册返回 refreshToken", bool(d.get("refreshToken")))
    user = d.get("user") or {}
    check("注册返回 user.userId", isinstance(user.get("userId"), int))
    check("注册 isNewUser=True", d.get("isNewUser") is True)
    check("注册返回手机号", user.get("phone") == phone_a)
    check("注册返回 wechat 字段", "wechat" in user)
    uid_a = user.get("userId")

    # 2. 注册会话直接可用：GET /me
    token_a = d.get("accessToken")
    r = requests.get(
        f"{BASE}/me",
        headers={"Authorization": f"Bearer {token_a}"},
        timeout=10,
        proxies={"http": None, "https": None},
    )
    check("注册会话 GET /me code=0", r.json().get("code") == 0, r.text[:200])
    check("/me userId 与注册一致", (r.json().get("data") or {}).get("userId") == uid_a)

    # 3. 重复注册
    r = register(phone_a, pwd)
    body = r.json()
    check("重复注册 409", r.status_code == 409, r.text[:200])
    check("重复注册 TT_AUTH_40901", body.get("code") == "TT_AUTH_40901", r.text[:200])

    # 4. 参数校验
    r = register("12345", pwd)
    check("非法手机号 400", r.status_code == 400, r.text[:200])
    check("非法手机号 TT_COMMON_40001", r.json().get("code") == "TT_COMMON_40001")
    r = register(phone_a, "123")
    check("短密码 400", r.status_code == 400, r.text[:200])
    check("短密码 TT_COMMON_40001", r.json().get("code") == "TT_COMMON_40001")

    # 5. 注册后可登录（小程序端 phone 字段）
    r = login_phone(phone_a, pwd)
    check("注册后 phone 登录 code=0", r.json().get("code") == 0, r.text[:200])
    check("登录同一 userId", (r.json().get("data") or {}).get("user", {}).get("userId") == uid_a)

    # 6. 错误密码登录失败
    r = login_phone(phone_a, "wrong-pass")
    check("错误密码 401", r.status_code == 401, r.text[:200])
    check("错误密码 TT_AUTH_40105", r.json().get("code") == "TT_AUTH_40105")

    # 7. 数据隔离：用户 B 注册后各自收藏互不可见
    r = register(phone_b, pwd)
    token_b = (r.json().get("data") or {}).get("accessToken")
    check("用户B注册成功", bool(token_b))
    for token, tid in ((token_a, 1), (token_b, 2)):
        rr = requests.put(
            f"{BASE}/favorites/demand/{tid}",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            proxies={"http": None, "https": None},
        )
        check(f"收藏 demand/{tid} code=0", rr.json().get("code") == 0, rr.text[:200])
    for token, expect_tid in ((token_a, 1), (token_b, 2)):
        rr = requests.get(
            f"{BASE}/me/favorites?targetType=demand&pageSize=10",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
            proxies={"http": None, "https": None},
        )
        d2 = rr.json().get("data") or {}
        ids = [x.get("targetId") for x in (d2.get("list") or [])]
        check(f"/me/favorites 隔离（期望含 {expect_tid}）", expect_tid in ids, str(ids))

    # 8. wechat 资料更新（新增列）
    r = requests.patch(
        f"{BASE}/me/profile",
        headers={"Authorization": f"Bearer {token_a}"},
        json={"version": 1, "wechat": "wx_" + suffix, "displayName": "测试用户A"},
        timeout=10,
        proxies={"http": None, "https": None},
    )
    check("PATCH /me/profile 含 wechat code=0", r.json().get("code") == 0, r.text[:200])
    check("返回 wechat 回显", (r.json().get("data") or {}).get("wechat") == "wx_" + suffix)

    # 9. 后台 username 注册（Vue 注册页）：填手机号后双通道可登录
    phone_c = "139" + "3" * 8
    admin_username = "ttphone" + suffix
    r = requests.post(
        f"{BASE}/auth/register",
        json={
            "username": admin_username,
            "password": pwd,
            "displayName": "后台注册用户",
            "phone": phone_c,
        },
        timeout=10,
        proxies={"http": None, "https": None},
    )
    check("后台 username 注册 code=0", r.json().get("code") == 0, r.text[:200])
    uid_c = ((r.json().get("data") or {}).get("user") or {}).get("userId")

    # 后台端：username + 密码登录（链路保持不变）
    r = login_username(admin_username, pwd)
    check("后台 username 登录 code=0", r.json().get("code") == 0, r.text[:200])
    check("username 登录同一 userId", (r.json().get("data") or {}).get("user", {}).get("userId") == uid_c)

    # 小程序端：后台注册用户也能用手机号登录（本次修复的业务场景）
    r = login_phone(phone_c, pwd)
    check("后台用户 phone 登录 code=0", r.json().get("code") == 0, r.text[:200])
    check("phone 登录同一 userId", (r.json().get("data") or {}).get("user", {}).get("userId") == uid_c)

    # 后台用户名在小程序端用 phone 方式登录应失败（用户名不是手机号）
    r = login_phone(admin_username, pwd)
    check("用户名走 phone 登录 401", r.status_code == 401, r.text[:200])

    # 10. 后台注册手机号与已有小程序账号冲突 → 409
    r = requests.post(
        f"{BASE}/auth/register",
        json={"username": "ttconflict" + suffix, "password": pwd, "phone": phone_a},
        timeout=10,
        proxies={"http": None, "https": None},
    )
    check("手机号冲突 409", r.status_code == 409, r.text[:200])
    check("手机号冲突 TT_COMMON_40903", r.json().get("code") == "TT_COMMON_40903", r.text[:200])

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
