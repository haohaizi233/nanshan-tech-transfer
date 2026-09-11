"""
把爬虫产出的 JSON 批量导入后台管理（institution 表，kind=platform）

数据文件：默认读取脚本目录下 concept_validation_centers.json + pilot_test_bases.json
（字段由 crawl_platform_base.py 生成，与 POST /admin/institutions/import 兼容），
也可用 --files 指定其他文件（取每个文件的 items 数组）。

鉴权（三选一，优先级从高到低）：
  --token <JWT>                                  直接传 access token
  --username admin --password Admin@2026          账号密码登录（tools/seed_admin_account.py 可建号）
  --host-credential local-dev-ticket-dev-user-001 本地开发 mock 票据（默认，dev-user-001 是 admin 种子）

幂等：后端按 (kind, source_pk) 或 (kind, name) upsert，可重复执行。

用法：
  python import_to_admin.py                                  # 本地开发默认
  python import_to_admin.py --base-url http://127.0.0.1:8787
  python import_to_admin.py --username admin --password Admin@2026
  python import_to_admin.py --files a.json --files b.json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import requests

DEFAULT_BASE_URL = "http://127.0.0.1:8787"
API_PREFIX = "/api/tech-transfer/v1"
DEFAULT_HOST_CREDENTIAL = "local-dev-ticket-dev-user-001"
IMPORT_CHUNK = 500  # 后端单次导入上限

_session = requests.Session()
_session.trust_env = False  # 本地后端不走系统代理


def get_token(args) -> str:
    if args.token:
        return args.token
    if args.username:
        resp = _session.post(
            f"{args.base_url}{API_PREFIX}/auth/login",
            json={"username": args.username, "password": args.password},
            timeout=15,
        )
    else:
        resp = _session.post(
            f"{args.base_url}{API_PREFIX}/auth/bootstrap",
            json={"hostCredential": args.host_credential},
            timeout=15,
        )
    resp.raise_for_status()
    payload = resp.json()
    if payload.get("code") != 0:
        raise SystemExit(f"获取 token 失败: {payload}")
    return payload["data"]["accessToken"]


def load_items(files: list[Path]) -> list[dict]:
    items: list[dict] = []
    for f in files:
        data = json.loads(f.read_text(encoding="utf-8"))
        batch = data.get("items") if isinstance(data, dict) else data
        if not isinstance(batch, list):
            raise SystemExit(f"{f} 中未找到 items 数组")
        print(f"读取 {f.name}: {len(batch)} 条")
        items.extend(batch)
    return items


def import_items(base_url: str, token: str, items: list[dict]) -> dict:
    headers = {"Authorization": f"Bearer {token}"}
    total_created = total_updated = 0
    for start in range(0, len(items), IMPORT_CHUNK):
        chunk = items[start:start + IMPORT_CHUNK]
        resp = _session.post(
            f"{base_url}{API_PREFIX}/admin/institutions/import",
            json={"items": chunk},
            headers=headers,
            timeout=120,
        )
        if resp.status_code == 401:
            raise SystemExit("token 无效或已过期（401），请重新获取")
        payload = resp.json()
        if payload.get("code") != 0:
            raise SystemExit(f"导入失败: {json.dumps(payload, ensure_ascii=False)[:500]}")
        data = payload["data"]
        total_created += data["created"]
        total_updated += data["updated"]
        print(f"批次 {start // IMPORT_CHUNK + 1}: 新增 {data['created']}，更新 {data['updated']}")
    return {"created": total_created, "updated": total_updated, "total": len(items)}


def main() -> int:
    parser = argparse.ArgumentParser(description="批量导入平台/机构 JSON 到后台管理")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--token", help="已获取的 access token（JWT）")
    parser.add_argument("--username", help="后台登录账号（与 --password 搭配）")
    parser.add_argument("--password", default="", help="后台登录密码")
    parser.add_argument(
        "--host-credential", default=DEFAULT_HOST_CREDENTIAL,
        help=f"本地开发 mock 票据（默认 {DEFAULT_HOST_CREDENTIAL}）",
    )
    parser.add_argument(
        "--files", action="append", default=None,
        help="待导入 JSON（可重复传）；默认取脚本目录下两个分类 JSON",
    )
    args = parser.parse_args()

    script_dir = Path(__file__).resolve().parent
    files = [Path(p) for p in args.files] if args.files else [
        script_dir / "concept_validation_centers.json",
        script_dir / "pilot_test_bases.json",
    ]
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        print(f"文件不存在: {missing}\n请先运行 crawl_platform_base.py 生成数据。")
        return 1

    items = load_items(files)
    if not items:
        print("没有可导入的数据")
        return 1

    token = get_token(args)
    result = import_items(args.base_url, token, items)
    print(f"导入完成：共 {result['total']} 条，新增 {result['created']}，更新 {result['updated']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
