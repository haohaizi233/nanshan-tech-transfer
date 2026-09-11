"""
南方创投网 - 概念验证中心/中小试基地库 爬虫

数据源页面:
  https://www.first-net.cn/page/portal/platformBase/platformBase.jsp
列表接口 (XHR POST):
  https://www.first-net.cn/portal/platformBase_showPlatformBaseList
参数:
  pagination.pageSize / pagination.pageIndex
响应:
  {"total": N, "result": [ {storeId, platformName, platformType, supportUnit, platformFun, contactPerson, contactMobile, ...} ]}

输出（--out-dir，默认脚本目录）:
  concept_validation_centers.json  概念验证中心（platformTypeKey=poc）
  pilot_test_bases.json            中小试基地（platformTypeKey=pilot，含源站"中试基地"类型，原始类型保留在 platformType）
  platform_base_data.json          全量数据（兼容旧格式，snake_case）
  两个分类 JSON 的 items 字段与后台管理 POST /admin/institutions/import 兼容，
  可直接用 import_to_admin.py 批量导入。

用法:
  python crawl_platform_base.py                # 爬取并导出 JSON（默认不写 MySQL）
  python crawl_platform_base.py --mysql        # 追加写入 legacy MySQL nanshan_capital.platform_base
  python crawl_platform_base.py --mysql --host 127.0.0.1 --port 3307 --user root --password=
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from pathlib import Path

import requests

BASE_URL = "https://www.first-net.cn"
LIST_URL = f"{BASE_URL}/portal/platformBase_showPlatformBaseList"
REFERER = f"{BASE_URL}/page/portal/platformBase/platformBase.jsp"
PAGE_SIZE = 20
DB_NAME = "nanshan_capital"
TABLE_NAME = "platform_base"

POC_JSON = "concept_validation_centers.json"
PILOT_JSON = "pilot_test_bases.json"
ALL_JSON = "platform_base_data.json"

# 与后端 modules/capital/service.py _map_type_key / tools/etl_institutions.py map_type_key 保持一致
def map_type_key(platform_type: str) -> str:
    t = (platform_type or "").strip()
    if "概念验证" in t:
        return "poc"
    if "中小试" in t or "中试" in t:
        return "pilot"
    return "other"


# 直连会话：绕过 HTTP(S)_PROXY 环境变量（本机代理节点访问该站会间歇性断连）
_session = requests.Session()
_session.trust_env = False


def fetch_page(page_index: int, page_size: int = PAGE_SIZE, retries: int = 3) -> dict:
    last_err: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            resp = _session.post(
                LIST_URL,
                data={
                    "pagination.pageSize": str(page_size),
                    "pagination.pageIndex": str(page_index),
                },
                headers={
                    "User-Agent": (
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    ),
                    "X-Requested-With": "XMLHttpRequest",
                    "Origin": BASE_URL,
                    "Referer": REFERER,
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                },
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()
        except requests.RequestException as e:
            last_err = e
            if attempt < retries:
                wait = attempt * 2
                print(f"第 {page_index + 1} 页请求失败（{attempt}/{retries}），{wait}s 后重试: {e}")
                time.sleep(wait)
    raise last_err  # type: ignore[misc]


def crawl_all(page_size: int = PAGE_SIZE, sleep_sec: float = 0.3) -> list[dict]:
    first = fetch_page(0, page_size)
    total = int(first.get("total") or 0)
    rows = list(first.get("result") or [])
    print(f"总数 total={total}，首页拿到 {len(rows)} 条")

    page_count = (total + page_size - 1) // page_size if total else 1
    for page_index in range(1, page_count):
        time.sleep(sleep_sec)
        data = fetch_page(page_index, page_size)
        batch = data.get("result") or []
        rows.extend(batch)
        print(f"页 {page_index + 1}/{page_count} -> {len(batch)} 条，累计 {len(rows)}")
    return rows


def normalize(row: dict) -> dict:
    """网站字段 -> snake_case（legacy MySQL / 全量 JSON 用）"""
    return {
        "serial_no": int(row.get("storeId") or 0),
        "platform_name": (row.get("platformName") or "").strip(),
        "platform_type": (row.get("platformType") or "").strip(),
        "support_unit": (row.get("supportUnit") or "").strip(),
        "platform_fun": (row.get("platformFun") or "").strip(),
        "contact_person": (row.get("contactPerson") or "").strip(),
        "contact_mobile": (row.get("contactMobile") or "").strip(),
        "source_status": row.get("status"),
        "order_num": row.get("orderNum"),
    }


def to_import_item(row: dict, fetched_at: str) -> dict:
    """网站字段 -> 后台管理 POST /admin/institutions/import 兼容项（camelCase）"""
    platform_type = (row.get("platformType") or "").strip()
    serial_no = int(row.get("storeId") or 0)
    return {
        "kind": "platform",
        "name": (row.get("platformName") or "").strip(),
        "platformType": platform_type,
        "platformTypeKey": map_type_key(platform_type),
        "unit": (row.get("supportUnit") or "").strip(),
        "functionText": (row.get("platformFun") or "").strip(),
        "contact": (row.get("contactPerson") or "").strip(),
        "phone": (row.get("contactMobile") or "").strip(),
        "serialNo": serial_no,
        "sortOrder": 0,
        "sourcePk": serial_no,
        "sourceStatus": row.get("status"),
        "orderNum": row.get("orderNum"),
        "sourceSite": "first-net.cn",
        "sourceApi": LIST_URL,
        "fetchedAt": fetched_at,
        "status": "active",
    }


def split_by_type(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    poc, pilot = [], []
    for r in rows:
        (poc if map_type_key(r.get("platformType") or "") == "poc" else pilot).append(r)
    return poc, pilot


def save_typed_json(rows: list[dict], out_path: Path, type_label: str, type_key: str, fetched_at: str) -> int:
    items = [to_import_item(r, fetched_at) for r in rows]
    payload = {
        "type": type_label,
        "typeKey": type_key,
        "source": REFERER,
        "api": LIST_URL,
        "fetchedAt": fetched_at,
        "total": len(items),
        "items": items,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 JSON：{out_path}（{len(items)} 条）")
    return len(items)


def save_all_json(rows: list[dict], out_path: Path) -> None:
    payload = {
        "source": REFERER,
        "api": LIST_URL,
        "total": len(rows),
        "items": [normalize(r) for r in rows],
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 JSON：{out_path}")


def save_schema_sql(out_path: Path) -> None:
    out_path.write_text(CREATE_SQL.strip() + "\n", encoding="utf-8")
    print(f"已写出建表 SQL：{out_path}")


def save_to_mysql(rows: list[dict], host: str, port: int, user: str, password: str) -> None:
    try:
        import pymysql
    except ImportError:
        print("缺少 pymysql，请先执行: pip install pymysql")
        sys.exit(1)

    # 先连无库创建 database
    conn = pymysql.connect(host=host, port=port, user=user, password=password, charset="utf8mb4", autocommit=False)
    try:
        ensure_schema(conn)
    finally:
        conn.close()

    conn = pymysql.connect(
        host=host, port=port, user=user, password=password,
        database=DB_NAME, charset="utf8mb4", autocommit=False,
    )
    try:
        normalized = [normalize(r) for r in rows]
        with conn.cursor() as cur:
            cur.executemany(UPSERT_SQL, normalized)
        conn.commit()
        print(f"已写入/更新 MySQL：{DB_NAME}.{TABLE_NAME}，共 {len(normalized)} 条")
    finally:
        conn.close()


CREATE_SQL = f"""
CREATE DATABASE IF NOT EXISTS `{DB_NAME}`
  DEFAULT CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;

USE `{DB_NAME}`;

CREATE TABLE IF NOT EXISTS `{TABLE_NAME}` (
  `id` BIGINT UNSIGNED NOT NULL AUTO_INCREMENT COMMENT '主键',
  `serial_no` INT NOT NULL COMMENT '序号',
  `platform_name` VARCHAR(255) NOT NULL COMMENT '平台名称',
  `platform_type` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '平台类型（概念验证中心/中小试基地）',
  `support_unit` VARCHAR(255) NOT NULL DEFAULT '' COMMENT '依托单位',
  `platform_fun` TEXT COMMENT '平台功能',
  `contact_person` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '联系人',
  `contact_mobile` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '联系方式',
  `source_status` INT NULL COMMENT '源站 status',
  `order_num` INT NULL COMMENT '源站 orderNum',
  `source_site` VARCHAR(128) NOT NULL DEFAULT 'first-net.cn' COMMENT '数据来源站点',
  `fetched_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP COMMENT '抓取时间',
  `updated_at` DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
  PRIMARY KEY (`id`),
  UNIQUE KEY `uk_serial_no` (`serial_no`),
  KEY `idx_platform_type` (`platform_type`),
  KEY `idx_platform_name` (`platform_name`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci
  COMMENT='概念验证中心/中小试基地库';
"""

UPSERT_SQL = f"""
INSERT INTO `{TABLE_NAME}` (
  serial_no, platform_name, platform_type, support_unit,
  platform_fun, contact_person, contact_mobile,
  source_status, order_num, source_site
) VALUES (
  %(serial_no)s, %(platform_name)s, %(platform_type)s, %(support_unit)s,
  %(platform_fun)s, %(contact_person)s, %(contact_mobile)s,
  %(source_status)s, %(order_num)s, 'first-net.cn'
)
ON DUPLICATE KEY UPDATE
  platform_name = VALUES(platform_name),
  platform_type = VALUES(platform_type),
  support_unit = VALUES(support_unit),
  platform_fun = VALUES(platform_fun),
  contact_person = VALUES(contact_person),
  contact_mobile = VALUES(contact_mobile),
  source_status = VALUES(source_status),
  order_num = VALUES(order_num),
  fetched_at = CURRENT_TIMESTAMP
"""


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in CREATE_SQL.split(";"):
            sql = stmt.strip()
            if sql:
                cur.execute(sql)
    conn.commit()


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="爬取南方创投网概念验证中心/中小试基地库，导出分类 JSON")
    p.add_argument("--host", default="127.0.0.1", help="legacy MySQL 主机（--mysql 时使用）")
    p.add_argument("--port", type=int, default=3306, help="legacy MySQL 端口（--mysql 时使用）")
    p.add_argument("--user", default="root", help="legacy MySQL 用户（--mysql 时使用）")
    p.add_argument("--password", default="", help="legacy MySQL 密码（--mysql 时使用）")
    p.add_argument("--mysql", action="store_true", help="追加写入 legacy MySQL nanshan_capital.platform_base")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        rows = crawl_all()
    except requests.RequestException as e:
        print(f"请求失败: {e}")
        return 1

    if not rows:
        print("未获取到数据")
        return 1

    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    poc_rows, pilot_rows = split_by_type(rows)

    save_typed_json(poc_rows, out_dir / POC_JSON, "概念验证中心", "poc", fetched_at)
    save_typed_json(pilot_rows, out_dir / PILOT_JSON, "中小试基地", "pilot", fetched_at)
    save_all_json(rows, out_dir / ALL_JSON)
    save_schema_sql(out_dir / "schema_platform_base.sql")

    # 按类型统计
    type_count: dict[str, int] = {}
    for r in rows:
        t = (r.get("platformType") or "未知").strip()
        type_count[t] = type_count.get(t, 0) + 1
    print("类型分布:", type_count)

    if args.mysql:
        try:
            save_to_mysql(rows, args.host, args.port, args.user, args.password)
        except Exception as e:
            print(f"MySQL 连接/写入失败: {e}")
            print("数据已保存在 JSON 文件中。")
            return 2
    else:
        print("默认不写 legacy MySQL；如需写入请加 --mysql")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
