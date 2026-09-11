"""Crawl SZTE 知识产权质押融资信息服务 → 银行 tab (userType=1).

API: GET /pubsapi/officialSiteApi/intellectualProperty/zyrz/user/get/1
Page: https://www.szte.com/capital/financeService/pledge/index.html

Only public card fields are kept (name / intro / logo / label). Source-user
secrets from the API payload are discarded.

Output: bank_financing.json (POST /admin/institutions/import items)

Usage:
  python crawl_banks.py
  python crawl_banks.py --out bank_financing.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

BASE = "https://www.szte.com"
BANK_API = f"{BASE}/pubsapi/officialSiteApi/intellectualProperty/zyrz/user/get/1"
BANK_PAGE = f"{BASE}/capital/financeService/pledge/index.html"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)

_session = requests.Session()
_session.trust_env = False


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


def crawl_banks() -> list[dict]:
    resp = _session.get(
        BANK_API,
        headers={
            "User-Agent": UA,
            "Referer": BANK_PAGE,
            "Accept": "application/json, text/plain, */*",
        },
        timeout=45,
    )
    resp.raise_for_status()
    data = resp.json()
    if int(data.get("code") or 0) != 1:
        raise RuntimeError(f"银行列表接口失败: {data.get('msg')}")
    fetched_at = datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")
    rows = []
    for i, item in enumerate(data.get("data") or []):
        name = str(item.get("fullname") or item.get("nickname") or "").strip()
        if not name:
            continue
        labels = item.get("labelList") or []
        rows.append(
            {
                "kind": "service",
                "name": name,
                "intro": str(item.get("description") or "").strip(),
                "label": str(labels[0] if labels else "银行").strip() or "银行",
                "logoFileId": parse_logo_id(item.get("logo")),
                "sortOrder": i + 1,
                "status": "active",
                "sourceSite": "szte.com",
                "sourceApi": BANK_API,
                "fetchedAt": fetched_at,
            }
        )
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description="爬取科交中心银行融资（银行 tab）")
    parser.add_argument(
        "--out",
        default=str(Path(__file__).resolve().parent / "bank_financing.json"),
    )
    args = parser.parse_args()
    rows = crawl_banks()
    if not rows:
        print("未获取到银行数据")
        return 1
    payload = {
        "source": BANK_PAGE,
        "api": BANK_API,
        "total": len(rows),
        "items": rows,
    }
    out = Path(args.out)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"银行 {len(rows)} 条 → {out}")
    for row in rows:
        print(f"  {row['sortOrder']}. {row['name']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
