"""清理 test_auth_register.py 固定手机号的残留账号（重跑前的标准清理）。"""
import psycopg2
import psycopg2.extras

DB = dict(host="127.0.0.1", port=5432, user="postgres", password="postgres123",
          dbname="tech_transfer")
PHONES = ("13911111111", "13922222222")

conn = psycopg2.connect(**DB)
try:
    with conn.cursor(cursor_factory=psycopg2.extras.DictCursor) as cur:
        for phone in PHONES:
            cur.execute(
            "SELECT u.id FROM app_user u JOIN user_profile p ON p.user_id = u.id WHERE p.phone = %s",
            (phone,),
        )
            rows = cur.fetchall() or []
            for row in rows:
                uid = row["id"]
                cur.execute("DELETE FROM favorite WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM user_credential WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM user_role WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM user_profile WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM organization_membership WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM organization_membership_application WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM organization_admin_application WHERE user_id = %s", (uid,))
                cur.execute("DELETE FROM organization_application WHERE applicant_user_id = %s", (uid,))
                cur.execute("DELETE FROM app_user WHERE id = %s", (uid,))
                print(f"cleaned app_user {uid} (phone={phone})")
    conn.commit()
finally:
    conn.close()
print("done")
