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

通过 --base-url 指定 HTTPS 测试 API，--phones 指定三个可收短信的测试手机号。
脚本会发起真实验证码请求，并在终端提示输入验证码。重跑时使用尚未注册的测试号码。
"""

import argparse
import re
import sys
import time
import uuid
from getpass import getpass
from urllib.parse import urlsplit

import requests

BASE = ""
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


def request_registration_proof(phone):
    url = f"{BASE}/auth/register/challenge"
    response = requests.post(url, json={"phone": phone}, timeout=20)
    retry_after = response.headers.get("Retry-After", "")
    if response.status_code == 429 and retry_after.isascii() and retry_after.isdecimal():
        delay = int(retry_after)
        if 0 < delay <= 120:
            print(f"验证码限流，等待 {delay} 秒后重试一次。", flush=True)
            time.sleep(delay)
            response = requests.post(url, json={"phone": phone}, timeout=20)
    response.raise_for_status()
    result = response.json()
    challenge_id = (result.get("data") or {}).get("challengeId")
    if result.get("code") != 0 or not challenge_id:
        raise ValueError("注册短信接口未返回有效的 challengeId")
    code = getpass(f"请输入尾号 {phone[-4:]} 收到的 6 位验证码: ").strip()
    if not re.fullmatch(r"[0-9]{6}", code):
        raise ValueError("验证码必须为 6 位数字")
    return {"challengeId": challenge_id, "code": code}


def register(phone, password, proof, **fields):
    return requests.post(
        f"{BASE}/auth/register",
        json={"phone": phone, "password": password, **proof, **fields},
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


def main(phones):
    suffix = uuid.uuid4().hex[:8]
    phone_a, phone_b, phone_c = phones
    pwd = "pass123456"

    # 先检查参数错误不会消耗这次短信挑战，再用同一凭证完成注册。
    proof_a = request_registration_proof(phone_a)
    r = register("12345", pwd, proof_a)
    check("非法手机号 400", r.status_code == 400, r.text[:200])
    check("非法手机号 TT_COMMON_40001", r.json().get("code") == "TT_COMMON_40001")
    r = register(phone_a, "123", proof_a)
    check("短密码 400", r.status_code == 400, r.text[:200])
    check("短密码 TT_COMMON_40001", r.json().get("code") == "TT_COMMON_40001")

    # 1. 正常注册
    r = register(phone_a, pwd, proof_a)
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
    if not token_a:
        return 1
    r = requests.get(
        f"{BASE}/me",
        headers={"Authorization": f"Bearer {token_a}"},
        timeout=10,
        proxies={"http": None, "https": None},
    )
    check("注册会话 GET /me code=0", r.json().get("code") == 0, r.text[:200])
    check("/me userId 与注册一致", (r.json().get("data") or {}).get("userId") == uid_a)

    # 已消费的凭证不能再次用于注册。
    r = register(phone_a, pwd, proof_a)
    check("已消费的注册验证码不能复用", r.status_code == 400, r.text[:200])

    # 5. 注册后可登录（小程序端 phone 字段）
    r = login_phone(phone_a, pwd)
    check("注册后 phone 登录 code=0", r.json().get("code") == 0, r.text[:200])
    check("登录同一 userId", (r.json().get("data") or {}).get("user", {}).get("userId") == uid_a)

    # 6. 错误密码登录失败
    r = login_phone(phone_a, "wrong-pass")
    check("错误密码 401", r.status_code == 401, r.text[:200])
    check("错误密码 TT_AUTH_40105", r.json().get("code") == "TT_AUTH_40105")

    # 7. 数据隔离：用户 B 注册后各自收藏互不可见
    r = register(phone_b, pwd, request_registration_proof(phone_b))
    token_b = (r.json().get("data") or {}).get("accessToken")
    check("用户B注册成功", bool(token_b))
    if not token_b:
        return 1
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
    admin_username = "ttphone" + suffix
    r = register(
        phone_c, pwd, request_registration_proof(phone_c), username=admin_username, displayName="后台注册用户"
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

    # 已注册号码用一份新的确权凭证验证两种冲突，失败事务不会消费凭证。
    duplicate_proof = request_registration_proof(phone_a)
    r = register(phone_a, pwd, duplicate_proof)
    check("重复注册 409", r.status_code == 409, r.text[:200])
    check("重复注册 TT_AUTH_40901", r.json().get("code") == "TT_AUTH_40901", r.text[:200])
    r = register(phone_a, pwd, duplicate_proof, username="ttconflict" + suffix)
    check("手机号冲突 409", r.status_code == 409, r.text[:200])
    check("手机号冲突 TT_COMMON_40903", r.json().get("code") == "TT_COMMON_40903", r.text[:200])

    print(f"\n=== {PASS} passed, {FAIL} failed ===")
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="使用测试账号验收短信注册和登录")
    parser.add_argument("--base-url", required=True, help="HTTPS 测试 API 根路径，含 /api/tech-transfer/v1")
    parser.add_argument("--phones", required=True, nargs=3, metavar="PHONE", help="三个可接收真实短信的测试手机号")
    args = parser.parse_args()
    url = urlsplit(args.base_url)
    if url.scheme != "https" or not url.hostname or url.query or url.fragment:
        parser.error("--base-url 必须是 HTTPS 测试 API 根路径")
    if len(set(args.phones)) != 3 or any(not re.fullmatch(r"1[3-9][0-9]{9}", phone) for phone in args.phones):
        parser.error("--phones 必须是三个不同的中国大陆测试手机号")
    BASE = args.base_url.rstrip("/")
    try:
        sys.exit(main(args.phones))
    except (requests.RequestException, ValueError, EOFError) as error:
        sys.exit(f"验收中止: {error}")
