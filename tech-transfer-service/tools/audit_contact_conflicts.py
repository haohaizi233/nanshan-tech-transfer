"""存量联系方式冲突与数据一致性扫描工具。

用于生产迁移前/灰度上线时检查：
1. user_profile.phone 与 user_credential.phone 不一致的账号；
2. 存量存在重复手机号的账号；
3. 存量存在重复邮箱的账号；
4. 无法自动初始化的存量账号清单。
"""

import os
import sys

# 将 tech-transfer-service 加入路径
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from config import settings
from db import get_cursor


def audit_conflicts():
    print(f"[*] 开始扫描数据库: {settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}")
    with get_cursor() as cur:
        # 1. 检查 user_profile.phone 与 user_credential.phone 不一致
        cur.execute(
            """
            SELECT uc.user_id, uc.username, uc.phone AS cred_phone, up.phone AS profile_phone
            FROM user_credential uc
            JOIN user_profile up ON up.user_id = uc.user_id
            WHERE uc.phone IS NOT NULL AND up.phone IS NOT NULL AND uc.phone <> up.phone
            """
        )
        mismatched_phones = cur.fetchall()
        print(f"[!] 发现凭证手机号与资料手机号不一致账号数: {len(mismatched_phones)}")
        for r in mismatched_phones[:5]:
            print(f"    - User {r['user_id']} ({r['username']}): cred={r['cred_phone']}, profile={r['profile_phone']}")

        # 2. 检查 user_profile 中重复填写的手机号
        cur.execute(
            """
            SELECT phone, COUNT(*) AS cnt, array_agg(user_id) AS user_ids
            FROM user_profile
            WHERE phone IS NOT NULL AND phone ~ '^\\d{11}$'
            GROUP BY phone
            HAVING COUNT(*) > 1
            """
        )
        dup_profile_phones = cur.fetchall()
        print(f"[!] 发现资料表中重复填写的手机号数: {len(dup_profile_phones)}")
        for r in dup_profile_phones[:5]:
            print(f"    - Phone {r['phone']}: 关联用户 {r['user_ids']}")

        # 3. 检查 user_profile 中重复填写的邮箱
        cur.execute(
            """
            SELECT email, COUNT(*) AS cnt, array_agg(user_id) AS user_ids
            FROM user_profile
            WHERE email IS NOT NULL AND email <> ''
            GROUP BY email
            HAVING COUNT(*) > 1
            """
        )
        dup_emails = cur.fetchall()
        print(f"[!] 发现资料表中重复填写的邮箱数: {len(dup_emails)}")
        for r in dup_emails[:5]:
            print(f"    - Email {r['email']}: 关联用户 {r['user_ids']}")

        # 4. 统计 account_contact 当前已确权联系方式
        cur.execute(
            """
            SELECT contact_type, COUNT(*) AS total,
                   COUNT(CASE WHEN verified_at IS NOT NULL THEN 1 END) AS verified
            FROM account_contact
            GROUP BY contact_type
            """
        )
        rows = cur.fetchall()
        print("[+] 确权表 account_contact 当前统计:")
        for r in rows:
            print(f"    - {r['contact_type']}: 总计={r['total']}, 已确权={r['verified']}")

    print("[*] 扫描完成。")


if __name__ == "__main__":
    audit_conflicts()
