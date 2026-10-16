"""
初始化账号密码登录（幂等，可重复执行）：
1. 应用 migrations/pg/004_user_credential.sql（user_credential 表）
2. 种子管理员：username=admin（密码须显式传入，创建后立即修改）

用法：python tools/seed_admin_account.py <username> <password>
"""

import sys
from pathlib import Path

import psycopg2

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings
from core.password import hash_password

MIGRATION = Path(__file__).resolve().parent.parent / "migrations" / "pg" / "004_user_credential.sql"


def main():
    username = sys.argv[1] if len(sys.argv) > 1 else "admin"
    if len(sys.argv) <= 2:
        print("[ERROR] 必须显式传入密码：python tools/seed_admin_account.py <username> <password>")
        print("        不得使用默认密码，创建后请立即修改。")
        sys.exit(1)
    password = sys.argv[2]
    display_name = "系统管理员"

    conn = psycopg2.connect(
        host=settings.DB_HOST, port=settings.DB_PORT,
        user=settings.DB_USER, password=settings.DB_PASSWORD,
        dbname=settings.DB_NAME,
    )
    conn.autocommit = False
    cur = conn.cursor()
    try:
        cur.execute(MIGRATION.read_text(encoding="utf-8"))
        print("[OK] user_credential 表已就绪")

        cur.execute("SELECT user_id FROM user_credential WHERE username=%s", (username,))
        existing = cur.fetchone()
        if existing:
            cur.execute(
                "UPDATE user_credential SET password_hash=%s, status='active' WHERE username=%s",
                (hash_password(password), username),
            )
            user_id = existing[0]
            print(f"[OK] 已重置密码：{username}（user_id={user_id}）")
        else:
            cur.execute(
                "INSERT INTO app_user (user_no, status) VALUES (%s, 'active') RETURNING id",
                (f"ADMIN{username.upper()[:12]}",),
            )
            user_id = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO user_profile (user_id, display_name) VALUES (%s, %s) "
                "ON CONFLICT (user_id) DO NOTHING",
                (user_id, display_name),
            )
            cur.execute(
                "INSERT INTO user_role (user_id, role_code) VALUES (%s, 'admin')",
                (user_id,),
            )
            cur.execute(
                "INSERT INTO user_credential (user_id, username, password_hash) VALUES (%s, %s, %s)",
                (user_id, username, hash_password(password)),
            )
            print(f"[OK] 已创建管理员：{username} / {password}（user_id={user_id}）")

        conn.commit()
        print("[DONE] 提交完成")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
