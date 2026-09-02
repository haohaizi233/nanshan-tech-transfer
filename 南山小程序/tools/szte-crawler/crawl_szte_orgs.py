"""
科交中心（szte.com）资本对接数据爬虫

1) 银行融资 ← 知识产权融资信息服务 / 专业服务机构
   API: GET /pubsapi/officialSiteApi/intellectualProperty/zyrz/user/get/2
   表: ip_service_org
   字段: org_name / intro（列表简介）
   说明: 专业服务机构点击详情源站多为「无专属数据」，detail_info 暂空

2) 投资机构 ← 特色投资机构一览
   列表: GET /pubsapi/web/activity/getDetailById?id=81（图文展示卡片 = 悬停/列表简介）
   详情: 点击后的 customize 详情页 getDetailById?id=xxx（detail_info）
   表: featured_invest_org

用法:
  python crawl_szte_orgs.py
  python crawl_szte_orgs.py --host 127.0.0.1 --port 3307 --user root --password=
  python crawl_szte_orgs.py --skip-mysql
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

try:
    import pymysql
except ImportError:
    print("缺少 pymysql，请先执行: pip install pymysql")
    sys.exit(1)


BASE = "https://www.szte.com"
SERVICE_API = f"{BASE}/pubsapi/officialSiteApi/intellectualProperty/zyrz/user/get/2"
INVEST_API = f"{BASE}/pubsapi/web/activity/getDetailById?id=81"
INVEST_PAGE = f"{BASE}/visual/customize/detail?id=81"
DETAIL_API = f"{BASE}/pubsapi/web/activity/getDetailById?id={{id}}"
DB_NAME = "nanshan_capital"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

# 列表页未直接挂链接、但已知存在的详情页（名称 -> activity id）
EXTRA_DETAIL_IDS = {
    "深圳市松禾创业投资有限公司": 312,
}

# 详情页标题与列表卡片名称不一致时的别名
DETAIL_NAME_ALIASES = {
    "深圳市高新投创投股权投资基金管理有限公司": "深圳市高新投集团有限公司",
    "紫金港资本": "深圳市紫金港资本管理有限公司",
    "松禾创投": "深圳市松禾创业投资有限公司",
}


def http_get_json(url: str, referer: str) -> dict:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": UA,
            "Referer": referer,
            "Accept": "application/json, text/plain, */*",
        },
    )
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def clean_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def html_to_text(s: str) -> str:
    t = s or ""
    t = re.sub(r"<br\s*/?>", "\n", t, flags=re.I)
    t = re.sub(r"</p\s*>", "\n", t, flags=re.I)
    t = re.sub(r"<[^>]+>", "", t)
    t = (
        t.replace("&nbsp;", " ")
        .replace("&ldquo;", "“")
        .replace("&rdquo;", "”")
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
    )
    t = re.sub(r"[ \t]+\n", "\n", t)
    t = re.sub(r"\n{3,}", "\n\n", t)
    return t.strip()


def parse_logo_id(logo_field) -> str:
    if not logo_field:
        return ""
    try:
        arr = json.loads(logo_field) if isinstance(logo_field, str) else logo_field
        if isinstance(arr, list) and arr:
            return str(arr[0].get("id") or "")
    except Exception:
        pass
    return ""


def crawl_service_orgs() -> list[dict]:
    data = http_get_json(SERVICE_API, f"{BASE}/capital/financeService/pledge/index.html")
    if int(data.get("code") or 0) != 1:
        raise RuntimeError(f"专业服务机构接口失败: {data.get('msg')}")
    rows = []
    for i, item in enumerate(data.get("data") or []):
        labels = item.get("labelList") or []
        org_name = clean_text(item.get("fullname") or item.get("nickname") or "")
        account = (item.get("account") or "").strip() or org_name
        if not org_name:
            continue
        intro = clean_text(item.get("description") or "")
        rows.append(
            {
                "account": account,
                "org_name": org_name,
                "intro": intro,
                "detail_info": None,  # 源站点击详情无稳定专属正文
                "label": clean_text(labels[0] if labels else "专业服务机构"),
                "user_type": (item.get("userType") or "").strip(),
                "logo_file_id": parse_logo_id(item.get("logo")),
                "sort_order": i + 1,
                "source_api": SERVICE_API,
            }
        )
    print(f"专业服务机构: {len(rows)} 条")
    return rows


def collect_detail_id_map(page: list) -> dict[str, int]:
    """从一览页「往届活动 / 快捷入口」收集 公司名 -> 详情 activity id。"""
    mapping: dict[str, int] = {}
    for comp in page:
        bi_name = ((comp.get("baseInfo") or {}).get("name") or "").strip()
        data_list = (comp.get("data") or {}).get("list") or []
        if bi_name == "往届活动":
            for item in data_list:
                if not isinstance(item, dict):
                    continue
                name = clean_text(item.get("name") or "")
                aid = item.get("id")
                if name and aid:
                    mapping[DETAIL_NAME_ALIASES.get(name, name)] = int(aid)
        elif bi_name == "快捷入口":
            for floor in data_list:
                fname = clean_text((floor or {}).get("floorName") or "")
                for child in (floor or {}).get("floorList") or []:
                    jump = (child or {}).get("jumpUrl") or ""
                    m = re.search(r"[?&]id=(\d+)", jump)
                    if fname and m:
                        mapping[DETAIL_NAME_ALIASES.get(fname, fname)] = int(m.group(1))
    mapping.update(EXTRA_DETAIL_IDS)
    return mapping


def _option_text_values(opts: dict) -> list[str]:
    """从组件 options 中取出可能的正文。"""
    values: list[str] = []

    def push(v):
        if isinstance(v, str) and v.strip():
            values.append(v)
        elif isinstance(v, dict):
            inner = v.get("text")
            if isinstance(inner, str) and inner.strip():
                values.append(inner)
            elif isinstance(inner, dict) and inner.get("text"):
                values.append(str(inner.get("text")))

    push(opts.get("text"))
    push(opts.get("tinymce"))
    push(opts.get("content"))
    return values


def extract_detail_info(page_data, org_name: str) -> str:
    """提取点击详情页中的机构详细介绍（非悬停短文、非基金/案例附件）。"""
    if isinstance(page_data, str):
        page_data = json.loads(page_data)
    if not isinstance(page_data, list):
        return ""

    hints = [org_name]
    short = re.sub(
        r"(股份有限公司|有限责任公司|有限公司|集团有限公司|集团|管理顾问|私募股权基金管理|"
        r"股权投资基金管理|创业投资|资本管理|投资管理)$",
        "",
        org_name,
    )
    if short and short != org_name:
        hints.append(short)
    for alias, target in DETAIL_NAME_ALIASES.items():
        if target == org_name:
            hints.append(alias)

    intro_keys = ("成立", "简称", "注册资本", "有限公司", "致力于", "专注", "使命", "发起")
    candidates: list[str] = []

    for comp in page_data:
        for raw in _option_text_values(comp.get("options") or {}):
            text = html_to_text(raw)
            if len(text) < 40:
                continue
            if "本栏目长期收集" in text or "All Rights Reserved" in text:
                continue
            if text not in candidates:
                candidates.append(text)

    if not candidates:
        return ""

    def score(t: str) -> tuple:
        hit_name = any(h and h in t for h in hints)
        hit_intro = any(k in t for k in intro_keys)
        penalty = 0
        if t.startswith("基金全称") or "基金基本情况" in t[:40]:
            penalty += 1000
        if ("先生" in t[:30] or "女士" in t[:30]) and "负责" in t:
            penalty += 800
        if "在投资管理过程中" in t and org_name not in t and not any(h in t for h in hints if h):
            penalty += 500
        return (1 if hit_name else 0, 1 if hit_intro else 0, len(t) - penalty)

    return max(candidates, key=score)


def fetch_detail_info(activity_id: int, org_name: str) -> str:
    url = DETAIL_API.format(id=activity_id)
    data = http_get_json(url, INVEST_PAGE)
    if int(data.get("code") or 0) != 1:
        return ""
    return extract_detail_info((data.get("data") or {}).get("pageData"), org_name)


def crawl_invest_orgs() -> list[dict]:
    data = http_get_json(INVEST_API, INVEST_PAGE)
    if int(data.get("code") or 0) != 1:
        raise RuntimeError(f"特色投资机构接口失败: {data.get('msg')}")
    page_raw = (data.get("data") or {}).get("pageData")
    page = json.loads(page_raw) if isinstance(page_raw, str) else page_raw
    if not isinstance(page, list):
        raise RuntimeError("pageData 格式异常")

    detail_map = collect_detail_id_map(page)
    print(f"已解析到详情页映射 {len(detail_map)} 个")

    rows: list[dict] = []
    seen: set[str] = set()
    order = 0

    for comp in page:
        bi_name = ((comp.get("baseInfo") or {}).get("name") or "").strip()
        if bi_name != "图文展示":
            continue
        for item in (comp.get("data") or {}).get("list") or []:
            if not isinstance(item, dict):
                continue
            name = clean_text(item.get("title") or "")
            intro = clean_text(item.get("text") or "")
            if not name or name in seen or not intro:
                continue
            seen.add(name)
            order += 1
            aid = detail_map.get(name)
            detail_info = None
            if aid:
                try:
                    time.sleep(0.2)
                    detail_info = fetch_detail_info(aid, name) or None
                    print(f"  详情 {name} id={aid} len={len(detail_info or '')}")
                except Exception as e:
                    print(f"  详情失败 {name} id={aid}: {e}")
                    detail_info = None
            rows.append(
                {
                    "org_name": name,
                    "intro": intro,
                    "detail_info": detail_info,
                    "logo_file_id": parse_logo_id(item.get("backFile") or item.get("iconFile")),
                    "detail_activity_id": aid,
                    "sort_order": order,
                    "source_page": INVEST_PAGE,
                }
            )

    with_detail = sum(1 for r in rows if r.get("detail_info"))
    print(f"特色投资机构: {len(rows)} 条（其中有详细信息 {with_detail} 条）")
    return rows


CREATE_SQL = (Path(__file__).resolve().parent / "schema_szte_orgs.sql").read_text(encoding="utf-8")

UPSERT_SERVICE = """
INSERT INTO `ip_service_org` (
  account, org_name, intro, detail_info, label, user_type, logo_file_id, sort_order, source_api
) VALUES (
  %(account)s, %(org_name)s, %(intro)s, %(detail_info)s, %(label)s, %(user_type)s,
  %(logo_file_id)s, %(sort_order)s, %(source_api)s
)
ON DUPLICATE KEY UPDATE
  org_name = VALUES(org_name),
  intro = VALUES(intro),
  detail_info = VALUES(detail_info),
  label = VALUES(label),
  user_type = VALUES(user_type),
  logo_file_id = VALUES(logo_file_id),
  sort_order = VALUES(sort_order),
  source_api = VALUES(source_api),
  fetched_at = CURRENT_TIMESTAMP
"""

UPSERT_INVEST = """
INSERT INTO `featured_invest_org` (
  org_name, intro, detail_info, logo_file_id, detail_activity_id, sort_order, source_page
) VALUES (
  %(org_name)s, %(intro)s, %(detail_info)s, %(logo_file_id)s, %(detail_activity_id)s,
  %(sort_order)s, %(source_page)s
)
ON DUPLICATE KEY UPDATE
  intro = VALUES(intro),
  detail_info = VALUES(detail_info),
  logo_file_id = VALUES(logo_file_id),
  detail_activity_id = VALUES(detail_activity_id),
  sort_order = VALUES(sort_order),
  source_page = VALUES(source_page),
  fetched_at = CURRENT_TIMESTAMP
"""


def load_db_config() -> dict:
    cfg_path = Path(__file__).resolve().parent / "db_config.json"
    if cfg_path.exists():
        return json.loads(cfg_path.read_text(encoding="utf-8"))
    return {"host": "127.0.0.1", "port": 3307, "user": "root", "password": ""}


def ensure_columns(conn) -> None:
    """兼容已存在的旧表：补 detail_info 列。"""
    alters = [
        (
            "ip_service_org",
            "detail_info",
            "ALTER TABLE `ip_service_org` ADD COLUMN `detail_info` MEDIUMTEXT "
            "COMMENT '详细信息（点击公司后详情页）' AFTER `intro`",
        ),
        (
            "featured_invest_org",
            "detail_info",
            "ALTER TABLE `featured_invest_org` ADD COLUMN `detail_info` MEDIUMTEXT "
            "COMMENT '详细信息（点击公司后详情页正文）' AFTER `intro`",
        ),
    ]
    with conn.cursor() as cur:
        for table, col, sql in alters:
            cur.execute(
                """
                SELECT COUNT(*) FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA=%s AND TABLE_NAME=%s AND COLUMN_NAME=%s
                """,
                (DB_NAME, table, col),
            )
            if cur.fetchone()[0] == 0:
                cur.execute(sql)
                print(f"已为 {table} 增加列 {col}")
    conn.commit()


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for stmt in CREATE_SQL.split(";"):
            sql = stmt.strip()
            if sql:
                cur.execute(sql)
    conn.commit()


def save_to_mysql(
    service_rows: list[dict],
    invest_rows: list[dict],
    host: str,
    port: int,
    user: str,
    password: str,
) -> None:
    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        ensure_schema(conn)
    finally:
        conn.close()

    conn = pymysql.connect(
        host=host,
        port=port,
        user=user,
        password=password,
        database=DB_NAME,
        charset="utf8mb4",
        autocommit=False,
    )
    try:
        ensure_columns(conn)
        with conn.cursor() as cur:
            if service_rows:
                cur.executemany(UPSERT_SERVICE, service_rows)
            if invest_rows:
                cur.executemany(UPSERT_INVEST, invest_rows)
        conn.commit()
        print(
            f"已写入/更新 MySQL：{DB_NAME}."
            f"ip_service_org={len(service_rows)}，"
            f"featured_invest_org={len(invest_rows)}"
        )
    finally:
        conn.close()


def save_json(service_rows: list[dict], invest_rows: list[dict], out_dir: Path) -> None:
    payload = {
        "ip_service_org": {
            "source": f"{BASE}/capital/financeService/pledge/index.html",
            "api": SERVICE_API,
            "total": len(service_rows),
            "items": service_rows,
        },
        "featured_invest_org": {
            "source": INVEST_PAGE,
            "api": INVEST_API,
            "total": len(invest_rows),
            "with_detail_info": sum(1 for r in invest_rows if r.get("detail_info")),
            "items": invest_rows,
        },
    }
    path = out_dir / "szte_orgs_data.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"已导出 JSON：{path}")


def parse_args() -> argparse.Namespace:
    cfg = load_db_config()
    p = argparse.ArgumentParser(description="爬取科交中心专业服务机构/特色投资机构并写入 MySQL")
    p.add_argument("--host", default=cfg.get("host", "127.0.0.1"))
    p.add_argument("--port", type=int, default=int(cfg.get("port", 3307)))
    p.add_argument("--user", default=cfg.get("user", "root"))
    p.add_argument("--password", default=cfg.get("password", ""))
    p.add_argument("--skip-mysql", action="store_true")
    p.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    return p.parse_args()


def main() -> int:
    args = parse_args()
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    try:
        service_rows = crawl_service_orgs()
        invest_rows = crawl_invest_orgs()
    except Exception as e:
        print(f"抓取失败: {e}")
        return 1

    if not service_rows and not invest_rows:
        print("未获取到数据")
        return 1

    save_json(service_rows, invest_rows, out_dir)

    if args.skip_mysql:
        print("已跳过 MySQL 写入（--skip-mysql）")
        return 0

    try:
        save_to_mysql(
            service_rows,
            invest_rows,
            args.host,
            args.port,
            args.user,
            args.password,
        )
    except pymysql.err.OperationalError as e:
        print(f"MySQL 连接/写入失败: {e}")
        print("数据已保存在 szte_orgs_data.json，请先启动 MySQL 后重新执行。")
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
