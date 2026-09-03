"""
执行 migrations/ 下的 SQL 迁移（可重复执行，additive only）

用法：python run_migration.py 004_demand_domain.sql
"""
import re
import sys

import pymysql

from config import DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME


def run_migration(filename: str):
    path = f"migrations/{filename}"
    sql = open(path, encoding="utf-8").read()
    sql = re.sub(r"^--.*$", "", sql, flags=re.M)
    stmts = [s.strip() for s in sql.split(";") if s.strip() and not s.strip().upper().startswith("USE ")]

    conn = pymysql.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD,
        database=DB_NAME, charset="utf8mb4",
    )
    try:
        cur = conn.cursor()
        for stmt in stmts:
            head = re.sub(r"\s+", " ", stmt)[:70]
            try:
                cur.execute(stmt)
                print("OK  :", head)
            except pymysql.err.MySQLError as e:
                if e.args and e.args[0] == 1050:
                    print("SKIP:", head, "(already exists)")
                else:
                    raise
        conn.commit()
        cur.execute("SHOW TABLES")
        print("tables:", [r[0] for r in cur.fetchall()])
    finally:
        conn.close()


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python run_migration.py <migration-file>")
        sys.exit(1)
    run_migration(sys.argv[1])
