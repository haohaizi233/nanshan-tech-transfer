import psycopg2

conn = psycopg2.connect(
    host="127.0.0.1",
    port=5432,
    dbname="tech_transfer",
    user="postgres",
    password="postgres123",
    connect_timeout=5,
)
cur = conn.cursor()
cur.execute("SELECT count(*) FROM achievement WHERE status='published'")
print("published achievements:", cur.fetchone()[0])
cur.execute("SELECT count(*) FROM demand")
print("demands:", cur.fetchone()[0])
conn.close()
