"""
MySQL(tech_transfer) → PostgreSQL(tech_transfer) 一次性数据迁移

- PG 结构由 migrations/pg/001_tech_transfer_schema.sql 预先创建（表存在、零数据）
- 本脚本按 FK 依赖顺序逐表复制，boolean 列做 int→bool 转换，jsonb 列原样传字符串
- 复制完成后重置 identity 序列
- 可重复执行：先清空目标表再复制（仅用于 PG 尚无真实数据的初始化阶段）
用法：python tools/migrate_mysql_to_pg.py
"""
import os

import psycopg2
import psycopg2.extras
import pymysql

MY = dict(host="127.0.0.1", port=3306, user="root", password="123456",
          database="tech_transfer", charset="utf8mb4",
          cursorclass=pymysql.cursors.DictCursor)
PG = dict(host=os.environ.get("DB_HOST", "127.0.0.1"),
          port=int(os.environ.get("DB_PORT", "5432")),
          user=os.environ.get("DB_USER", "postgres"),
          password=os.environ.get("DB_PASSWORD", "postgres123"),
          dbname=os.environ.get("DB_NAME", "tech_transfer"))

TABLES = [
    "app_user",
    "external_identity",
    "user_profile",
    "user_role",
    "auth_session",
    "organization",
    "achievement_category",
    "inventor",
    "achievement",
    "achievement_inventor",
    "demand_category",
    "demand_tag",
    "demand",
    "demand_tag_relation",
    "audit_log",
    "favorite",
    "cooperation_intent",
    "cooperation_event",
]

# FK 依赖顺序


def main():
    my = pymysql.connect(**MY)
    pg = psycopg2.connect(**PG)
    pg.autocommit = False

    try:
        with my.cursor() as mcur, pg.cursor() as pcur:
            # 目标列与类型（排除生成列），校验与 MySQL 列对齐
            tables_with_id = []
            for table in TABLES:
                pcur.execute(
                    """
                    SELECT column_name, data_type
                    FROM information_schema.columns
                    WHERE table_schema='public' AND table_name=%s
                      AND is_generated='NEVER'
                    ORDER BY ordinal_position
                    """,
                    (table,),
                )
                pg_cols = {r[0]: r[1] for r in pcur.fetchall()}
                if not pg_cols:
                    raise SystemExit(f"[FATAL] PG 缺表 {table}")

                mcur.execute(f"SHOW COLUMNS FROM `{table}`")
                my_cols = [r["Field"] for r in mcur.fetchall()]
                missing = [c for c in pg_cols if c not in my_cols]
                if missing:
                    raise SystemExit(f"[FATAL] {table}: PG 有列 MySQL 缺失: {missing}")
                cols = [c for c in my_cols if c in pg_cols]
                skipped = [c for c in my_cols if c not in pg_cols]
                if skipped:
                    print(f"[WARN] {table}: MySQL 列未复制: {skipped}")

                bool_cols = {c for c, t in pg_cols.items() if t == "boolean"}
                if "id" in pg_cols:
                    tables_with_id.append(table)
                col_list = ", ".join(cols)
                ph = ", ".join(["%s"] * len(cols))
                sql = f"INSERT INTO {table} ({col_list}) VALUES ({ph})"

                mcur.execute(f"SELECT {col_list} FROM `{table}`")
                rows = mcur.fetchall()
                for row in rows:
                    vals = []
                    for c in cols:
                        v = row[c]
                        if c in bool_cols and v is not None:
                            v = bool(v)
                        vals.append(v)
                    pcur.execute(sql, vals)
                print(f"OK {table}: {len(rows)} rows")

            # 重置 identity 序列（仅含 id 列的表；无序列时 pg_get_serial_sequence 返回 NULL 跳过）
            for table in tables_with_id:
                pcur.execute("SELECT pg_get_serial_sequence(%s, 'id')", (table,))
                seq = pcur.fetchone()[0]
                if not seq:
                    continue
                pcur.execute(
                    f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {table}), 0) + 1, false)"
                )
            print("sequences reset")
        pg.commit()
        print("=== MySQL → PG 数据迁移完成 ===")
    except Exception:
        pg.rollback()
        raise
    finally:
        my.close()
        pg.close()


if __name__ == "__main__":
    main()
