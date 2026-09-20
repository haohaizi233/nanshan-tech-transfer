"""
南山科转通 · 数据库导入脚本

数据来源（交接 SQL 备份 nanshan_capital_backup.sql 存在编码损坏，故改用爬虫导出的干净 JSON）：
  - platform-crawler/schema_platform_base.sql + platform_base_data.json  → platform_base（100 行）
  - szte-crawler/schema_szte_orgs.sql       + szte_orgs_data.json        → featured_invest_org（21 行）、ip_service_org（16 行）

用法：
  python tools/import_data.py          # 建表 + 清空 + 全量导入
  python tools/import_data.py --check  # 只检查连接和数据量

数据库连接配置读取 tools/szte-crawler/db_config.json（与 api-server 共用）。
"""

import json
import sys
from pathlib import Path

import pymysql

ROOT = Path(__file__).resolve().parent
SCHEMA_PLATFORM = ROOT / "platform-crawler" / "schema_platform_base.sql"
SCHEMA_SZTE = ROOT / "szte-crawler" / "schema_szte_orgs.sql"
DATA_PLATFORM = ROOT / "platform-crawler" / "platform_base_data.json"
DATA_SZTE = ROOT / "szte-crawler" / "szte_orgs_data.json"
DB_CFG = ROOT / "szte-crawler" / "db_config.json"

EXPECTED = {"platform_base": 100, "featured_invest_org": 21, "ip_service_org": 16}


def load_conn_params():
    cfg = json.loads(DB_CFG.read_text(encoding="utf-8"))
    import os
    return {
        "host": cfg.get("host", "127.0.0.1"),
        "port": int(cfg.get("port", 3306)),
        "user": cfg.get("user", "root"),
        # 优先用环境变量 MYSQL_PASSWORD，避免凭据硬编码入库；json 中留空即可。
        "password": os.getenv("MYSQL_PASSWORD", cfg.get("password", "")),
        "charset": "utf8mb4",
    }


def run_schema(conn, path):
    # schema 文件内含 CREATE DATABASE + USE + 建表语句，按分号拆分逐条执行
    sql = path.read_text(encoding="utf-8")
    with conn.cursor() as cur:
        for stmt in sql.split(";"):
            if stmt.strip():
                cur.execute(stmt)


def insert_items(conn, table, items):
    cols = sorted(items[0].keys())
    placeholders = ", ".join(["%s"] * len(cols))
    col_sql = ", ".join(f"`{c}`" for c in cols)
    rows = [[item.get(c) for c in cols] for item in items]
    with conn.cursor() as cur:
        cur.execute(f"TRUNCATE TABLE `{table}`")
        cur.executemany(
            f"INSERT INTO `{table}` ({col_sql}) VALUES ({placeholders})", rows
        )
    return len(rows)


def check(conn):
    ok = True
    with conn.cursor() as cur:
        for table, expected in EXPECTED.items():
            cur.execute(f"SELECT COUNT(*) FROM `{table}`")
            n = cur.fetchone()[0]
            status = "OK" if n == expected else "MISMATCH"
            if n != expected:
                ok = False
            print(f"  {table}: {n} 行（期望 {expected}）[{status}]")
    return ok


def main():
    if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    check_only = "--check" in sys.argv

    conn = pymysql.connect(**load_conn_params())
    try:
        if check_only:
            print("[检查] 数据库连接成功")
            check(conn)
            return

        print("[1/3] 建表（schema_*.sql）")
        run_schema(conn, SCHEMA_SZTE)
        run_schema(conn, SCHEMA_PLATFORM)

        print("[2/3] 导入数据（*_data.json，重新导入会先清空）")
        platform = json.loads(DATA_PLATFORM.read_text(encoding="utf-8"))
        szte = json.loads(DATA_SZTE.read_text(encoding="utf-8"))
        n1 = insert_items(conn, "platform_base", platform["items"])
        n2 = insert_items(conn, "featured_invest_org", szte["featured_invest_org"]["items"])
        n3 = insert_items(conn, "ip_service_org", szte["ip_service_org"]["items"])
        print(f"  platform_base: {n1} 行, featured_invest_org: {n2} 行, ip_service_org: {n3} 行")
        conn.commit()

        print("[3/3] 校验")
        if not check(conn):
            sys.exit("[!] 数据量与期望不符，请检查数据文件")
        print("[OK] 导入完成")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
