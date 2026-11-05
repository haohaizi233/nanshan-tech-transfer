import psycopg2

conn = psycopg2.connect(host="127.0.0.1", port=5432, user="postgres", password="postgres123", dbname="tech_transfer")
cur = conn.cursor()

cur.execute(
    """
    SELECT ei.external_subject, au.display_name, au.roles, au.status
    FROM external_identity ei
    JOIN app_user au ON au.id = ei.user_id
    WHERE ei.issuer = 'local-dev'
    ORDER BY ei.external_subject
    """
)
rows = cur.fetchall()
print(f"local-dev 身份映射（{len(rows)} 条）:")
for subject, name, roles, status in rows:
    tag = " <-- ADMIN" if "admin" in (roles or []) else ""
    print(f"  subject={subject:<24} name={name:<12} roles={roles} status={status}{tag}")

cur.execute("SELECT COUNT(*), COUNT(*) FILTER (WHERE 'admin' = ANY(roles)) FROM app_user")
total, admins = cur.fetchone()
print()
print(f"app_user 总数={total}，含 admin 角色={admins}")

cur.execute("SELECT id, user_no, display_name, roles FROM app_user WHERE 'admin' = ANY(roles)")
for uid, uno, name, roles in cur.fetchall():
    print(f"  admin 用户: id={uid} userNo={uno} name={name} roles={roles}")

conn.close()
