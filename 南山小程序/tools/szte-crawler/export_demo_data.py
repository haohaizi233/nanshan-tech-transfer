# -*- coding: utf-8 -*-
"""从 MySQL 导出演示用静态数据 JSON"""
import json
import sys
from pathlib import Path

import pymysql

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent
cfg = json.loads((ROOT / "db_config.json").read_text(encoding="utf-8"))
conn = pymysql.connect(
    host=cfg["host"],
    port=cfg["port"],
    user=cfg["user"],
    password=cfg["password"],
    database=cfg["database"],
    charset="utf8mb4",
    cursorclass=pymysql.cursors.DictCursor,
)
cur = conn.cursor()
out = {"poc": [], "pilot": [], "bank": [], "invest": []}

cur.execute(
    """
    SELECT serial_no, platform_name, platform_type, support_unit,
           platform_fun, contact_person, contact_mobile
    FROM platform_base
    WHERE platform_type LIKE %s
    ORDER BY serial_no
    LIMIT 12
    """,
    ("%概念验证%",),
)
for r in cur.fetchall():
    out["poc"].append(
        {
            "id": str(r["serial_no"]),
            "serialNo": r["serial_no"],
            "name": r["platform_name"],
            "platformType": r["platform_type"],
            "platformTypeKey": "poc",
            "unit": r["support_unit"] or "",
            "functionText": r["platform_fun"] or "",
            "contact": r["contact_person"] or "",
            "phone": r["contact_mobile"] or "",
        }
    )

cur.execute(
    """
    SELECT serial_no, platform_name, platform_type, support_unit,
           platform_fun, contact_person, contact_mobile
    FROM platform_base
    WHERE (platform_type LIKE %s OR platform_type LIKE %s)
      AND platform_type NOT LIKE %s
    ORDER BY serial_no
    LIMIT 12
    """,
    ("%中小试%", "%中试%", "%概念验证%"),
)
for r in cur.fetchall():
    out["pilot"].append(
        {
            "id": str(r["serial_no"]),
            "serialNo": r["serial_no"],
            "name": r["platform_name"],
            "platformType": r["platform_type"],
            "platformTypeKey": "pilot",
            "unit": r["support_unit"] or "",
            "functionText": r["platform_fun"] or "",
            "contact": r["contact_person"] or "",
            "phone": r["contact_mobile"] or "",
        }
    )

cur.execute(
    """
    SELECT id, org_name, intro, label, logo_file_id, sort_order
    FROM ip_service_org
    ORDER BY sort_order
    """
)
for r in cur.fetchall():
    fid = (r["logo_file_id"] or "").strip()
    out["bank"].append(
        {
            "id": str(r["id"]),
            "name": r["org_name"],
            "intro": r["intro"] or "",
            "label": r["label"] or "专业服务机构",
            "logoFileId": fid,
            "logoUrl": (
                "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId=" + fid
                if fid
                else ""
            ),
            "kind": "bank",
            "sortOrder": r["sort_order"],
        }
    )

cur.execute(
    """
    SELECT id, org_name, intro, logo_file_id, sort_order
    FROM featured_invest_org
    ORDER BY sort_order
    """
)
for r in cur.fetchall():
    fid = (r["logo_file_id"] or "").strip()
    out["invest"].append(
        {
            "id": str(r["id"]),
            "name": r["org_name"],
            "intro": r["intro"] or "",
            "label": "投资机构",
            "logoFileId": fid,
            "logoUrl": (
                "https://www.szte.com/portalapi/system/file/v1/downloadFile?fileId=" + fid
                if fid
                else ""
            ),
            "kind": "invest",
            "sortOrder": r["sort_order"],
        }
    )

conn.close()
dest = ROOT.parent.parent / "南山" / "common" / "capital-demo-data.js"
# write as JS module
lines = [
    "/**",
    " * 资本对接演示数据（从本地库导出，供真机演示，不依赖本机 API）",
    " * 概念验证/中小试各 12 条；专业服务机构、投资机构为全量。",
    " */",
    "",
    "export const DEMO_POC_LIST = " + json.dumps(out["poc"], ensure_ascii=False, indent=2),
    "",
    "export const DEMO_PILOT_LIST = " + json.dumps(out["pilot"], ensure_ascii=False, indent=2),
    "",
    "export const DEMO_BANK_LIST = " + json.dumps(out["bank"], ensure_ascii=False, indent=2),
    "",
    "export const DEMO_INVEST_LIST = " + json.dumps(out["invest"], ensure_ascii=False, indent=2),
    "",
]
dest.write_text("\n".join(lines) + "\n", encoding="utf-8")
print("counts", {k: len(v) for k, v in out.items()})
print("wrote", dest, "size", dest.stat().st_size)
