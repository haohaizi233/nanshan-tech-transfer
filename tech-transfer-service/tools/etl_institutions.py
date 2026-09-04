"""P0-1 ETL：nanshan_capital（MySQL）三表 -> tech_transfer.institution（PG）。

- platform_base       -> kind='platform'（source_pk=MySQL id, serial_no 保留）
- featured_invest_org -> kind='invest'  （source_pk=MySQL id, sort_order 保留）
- ip_service_org      -> kind='service' （source_pk=MySQL id, sort_order 保留）
- 幂等可重跑：ON CONFLICT (kind, source_pk) DO UPDATE
- 不删除 PG 侧管理端自建行（source_pk IS NULL 的行不动）

用法：python tools/etl_institutions.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pymysql
import psycopg2
import psycopg2.extras

from config import (
    DB_HOST, DB_PORT, DB_USER, DB_PASSWORD, DB_NAME,
    CAPITAL_DB_HOST, CAPITAL_DB_PORT, CAPITAL_DB_USER, CAPITAL_DB_PASSWORD,
)


def map_type_key(platform_type: str) -> str:
    t = (platform_type or "").strip()
    if "概念验证" in t:
        return "poc"
    if "中小试" in t or "中试" in t:
        return "pilot"
    return "other"


def fetch_mysql():
    conn = pymysql.connect(
        host=CAPITAL_DB_HOST, port=CAPITAL_DB_PORT, user=CAPITAL_DB_USER,
        password=CAPITAL_DB_PASSWORD, database="nanshan_capital",
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor,
    )
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, serial_no, platform_name, platform_type, support_unit, platform_fun, "
                "contact_person, contact_mobile, source_status, order_num, source_site, fetched_at "
                "FROM platform_base"
            )
            platforms = cur.fetchall()
            cur.execute(
                "SELECT id, org_name, intro, detail_info, logo_file_id, detail_activity_id, "
                "sort_order, source_site, source_page, fetched_at FROM featured_invest_org"
            )
            invests = cur.fetchall()
            cur.execute(
                "SELECT id, account, org_name, intro, detail_info, label, user_type, "
                "logo_file_id, sort_order, source_site, source_api, fetched_at FROM ip_service_org"
            )
            services = cur.fetchall()
        return platforms, invests, services
    finally:
        conn.close()


def platform_row(r):
    return (
        "platform", r["platform_name"],
        r["platform_type"] or "", map_type_key(r["platform_type"]),
        r["support_unit"] or "", r["platform_fun"],
        r["contact_person"] or "", r["contact_mobile"] or "",
        r["serial_no"], r["source_status"], r["order_num"],
        None, None, "", "", "", None, 0,
        r["id"], r["source_site"] or "first-net.cn", "", "", r["fetched_at"],
    )


def invest_row(r):
    return (
        "invest", r["org_name"],
        "", "other", "", None, "", "", None, None, None,
        r["intro"], r["detail_info"], "", "",
        r["logo_file_id"] or "", r["detail_activity_id"], r["sort_order"],
        r["id"], r["source_site"] or "szte.com", r["source_page"] or "", "", r["fetched_at"],
    )


def service_row(r):
    return (
        "service", r["org_name"],
        "", "other", "", None, "", "", None, None, None,
        r["intro"], r["detail_info"], r["label"] or "", r["user_type"] or "",
        r["logo_file_id"] or "", None, r["sort_order"],
        r["id"], r["source_site"] or "szte.com", "", r["source_api"] or "", r["fetched_at"],
    )


UPSERT = """
INSERT INTO institution (
    kind, name, platform_type, platform_type_key, support_unit, functions,
    contact_person, contact_mobile, serial_no, source_status, order_num,
    intro, detail_info, label, user_type, logo_file_id, detail_activity_id, sort_order,
    source_pk, source_site, source_page, source_api, fetched_at
) VALUES (
    %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s
)
ON CONFLICT (kind, source_pk) DO UPDATE SET
    name = EXCLUDED.name,
    platform_type = EXCLUDED.platform_type,
    platform_type_key = EXCLUDED.platform_type_key,
    support_unit = EXCLUDED.support_unit,
    functions = EXCLUDED.functions,
    contact_person = EXCLUDED.contact_person,
    contact_mobile = EXCLUDED.contact_mobile,
    serial_no = EXCLUDED.serial_no,
    source_status = EXCLUDED.source_status,
    order_num = EXCLUDED.order_num,
    intro = EXCLUDED.intro,
    detail_info = EXCLUDED.detail_info,
    label = EXCLUDED.label,
    user_type = EXCLUDED.user_type,
    logo_file_id = EXCLUDED.logo_file_id,
    detail_activity_id = EXCLUDED.detail_activity_id,
    sort_order = EXCLUDED.sort_order,
    source_site = EXCLUDED.source_site,
    source_page = EXCLUDED.source_page,
    source_api = EXCLUDED.source_api,
    fetched_at = EXCLUDED.fetched_at
"""


def main():
    platforms, invests, services = fetch_mysql()
    print(f"MySQL 读取: platform_base={len(platforms)}, "
          f"featured_invest_org={len(invests)}, ip_service_org={len(services)}")

    pg = psycopg2.connect(
        host=DB_HOST, port=DB_PORT, user=DB_USER, password=DB_PASSWORD, dbname=DB_NAME,
    )
    try:
        with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            for rows, fn, label in (
                (platforms, platform_row, "platform"),
                (invests, invest_row, "invest"),
                (services, service_row, "service"),
            ):
                for r in rows:
                    cur.execute(UPSERT, fn(r))
            pg.commit()
            cur.execute(
                "SELECT kind, COUNT(*) AS n FROM institution GROUP BY kind ORDER BY kind"
            )
            counts = {row["kind"]: row["n"] for row in cur.fetchall()}
            cur.execute("SELECT COUNT(*) AS n FROM institution WHERE source_pk IS NULL")
            admin_rows = cur.fetchone()["n"]
    finally:
        pg.close()

    print(f"PG institution 落库: {counts}（合计 {sum(counts.values())} 行）")
    print(f"管理端自建行（source_pk IS NULL，未被本次 ETL 触碰）: {admin_rows}")
    expected = {"platform": len(platforms), "invest": len(invests), "service": len(services)}
    if counts != expected:
        raise SystemExit(f"[FATAL] 落库行数不符: expected={expected}, actual={counts}")
    print("ETL 完成，行数核对一致")


if __name__ == "__main__":
    main()
