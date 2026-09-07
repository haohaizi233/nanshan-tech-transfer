"""
Excel 真实成果数据导入（SIAT 待转化技术成果 223 条）

数据源：成果表格导出 Excel（编码/标签/标题/内容/结果列表/发明人卡片/联系方式）
目标：PG tech_transfer 库 achievement + inventor + achievement_inventor

设计约定：
- 幂等可重跑：每次清空成果域（TRUNCATE RESTART IDENTITY）后全量导入
- 成果归属 dev-user-002（app_user.id=2），与 etl_demands.py 约定一致：
  默认用户 dev-user-001 可对其发起对接
- 机构挂 SIAT（按名称从统一 institution 表查找，不依赖固定 ID）
- Excel 标签 → 分类映射：新增 medical_device/material_energy/brain_science/
  synthetic_bio 4 类（add-only），复用 ai/biomed
- innovation_points ← Excel「结果列表」JSON（[{title,content,_lock}]，剔除 _lock）
- inventor 复用：同名同机构共享一条记录（uk name+org_name），简介截 255
- 旧 demo 数据（etl_achievements.py 随机生成）连同其收藏/对接意向一并清除；
  audit_log 遵循只增不删原则保留历史

用法：python tools/import_achievements_excel.py <excel路径>
"""
import json
import re
import sys
from pathlib import Path

import openpyxl
import psycopg2
import psycopg2.extras

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import settings  # noqa: E402

OWNER_USER_ID = 2                      # dev-user-002
ORG_NAME = "中国科学院深圳先进技术研究院"
SOURCE_XLSX = r"c:\Users\admin\.trae-cn\attachments\6a994f6e5ccb52d03a16d9c3\e752f292-2224-4168-807e-a3a71f661797_54406ecb-dc56-4a40-bba9-e3c471f6b9db_待转化技术成果表格导出_1786344353.xlsx"

# Excel 标签 → 分类 code（现有 10 类之外的按 add-only 新增）
CATEGORY_MAP = {
    "人工智能与机器人": ("ai", "人工智能"),
    "生物医药": ("biomed", "生物医药"),
    "医疗器械与高端装备": ("medical_device", "医疗器械与高端装备"),
    "材料能源": ("material_energy", "材料能源"),
    "脑科学": ("brain_science", "脑科学"),
    "合成生物": ("synthetic_bio", "合成生物"),
}


def parse_contact(raw: str):
    """从格式化联系方式文本提取电话/邮箱"""
    text = str(raw or "")
    phone = re.search(r"1[3-9]\d{9}", text)
    email = re.search(r"[\w.+-]+@[\w.-]+\.\w+", text)
    return (phone.group(0) if phone else None,
            email.group(0) if email else None)


def load_rows(path: str):
    wb = openpyxl.load_workbook(path, read_only=True)
    ws = wb["Worksheet"]
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() for h in rows[0]]
    idx = {h: i for i, h in enumerate(header)}
    out = []
    for r in rows[1:]:
        out.append({
            "code": str(r[idx["编码"]] or "").strip(),
            "tag": str(r[idx["标签"]] or "").strip(),
            "title": str(r[idx["中文标题"]] or "").strip()
                     or str(r[idx["后台标题"]] or "").strip(),
            "en_title": str(r[idx["英文标题"]] or "").strip(),
            "intro": str(r[idx["内容"]] or "").strip(),
            "result_list": str(r[idx["结果列表"]] or "").strip(),
            "created_at": str(r[idx["创建时间"]] or "").strip(),
            "cards": [
                {
                    "name": str(r[idx["姓名" + s]] or "").strip(),
                    "intro": str(r[idx["简介" + s]] or "").strip(),
                }
                for s in ("", "2", "3")
            ],
            "contact_raw": str(r[idx["联系方式"]] or ""),
        })
    return out


def parse_innovation_points(raw: str):
    if not raw:
        return None
    try:
        items = json.loads(raw)
    except (ValueError, TypeError):
        return None
    cleaned = [
        {"title": str(it.get("title", "")).strip(),
         "content": str(it.get("content", "")).strip()}
        for it in items if isinstance(it, dict) and it.get("title")
    ]
    return cleaned or None


def main():
    xlsx = sys.argv[1] if len(sys.argv) > 1 else SOURCE_XLSX
    rows = load_rows(xlsx)
    print(f"Excel 读取 {len(rows)} 行")

    conn = psycopg2.connect(
        host=settings.DB_HOST, port=settings.DB_PORT,
        user=settings.DB_USER, password=settings.DB_PASSWORD,
        dbname=settings.DB_NAME,
    )
    conn.autocommit = False
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    try:
        cur.execute(
            """
            SELECT id FROM institution
            WHERE name=%s AND status='active'
            ORDER BY id LIMIT 1
            """,
            (ORG_NAME,),
        )
        org = cur.fetchone()
        if not org:
            raise RuntimeError(f"统一机构表中不存在已启用机构：{ORG_NAME}")
        org_id = org["id"]

        # 1. 清理成果域旧数据（demo 随机数据 + 其收藏/意向），id 序列归零
        cur.execute("SELECT COUNT(*) AS c FROM achievement")
        old_ach = cur.fetchone()["c"]
        cur.execute("SELECT COUNT(*) AS c FROM inventor")
        old_inv = cur.fetchone()["c"]
        cur.execute("DELETE FROM favorite WHERE target_type='achievement'")
        fav_deleted = cur.rowcount
        cur.execute(
            "DELETE FROM cooperation_intent WHERE target_type='achievement'")
        coop_deleted = cur.rowcount
        cur.execute(
            "TRUNCATE achievement_inventor, achievement, inventor "
            "RESTART IDENTITY CASCADE")
        print(f"清理: 旧成果 {old_ach} 条 / 旧发明人 {old_inv} 条 / "
              f"收藏 {fav_deleted} / 对接意向 {coop_deleted}")

        # 2. 分类（add-only 新增 4 类）
        for sort, (code, name) in enumerate(
                CATEGORY_MAP.values(), start=len(CATEGORY_MAP) + 8):
            cur.execute(
                "INSERT INTO achievement_category (code, name, sort_order) "
                "VALUES (%s, %s, %s) ON CONFLICT (code) DO NOTHING",
                (code, name, sort))
        cur.execute("SELECT id, code FROM achievement_category")
        cat_ids = {r["code"]: r["id"] for r in cur.fetchall()}
        print(f"分类字典: {len(cat_ids)} 类")

        # 3. 插入成果 + 发明人
        ach_count = inv_new = 0
        for row in rows:
            cat = CATEGORY_MAP.get(row["tag"])
            cat_id = cat_ids.get(cat[0]) if cat else None
            if not cat_id:
                print(f"  [WARN] 未知标签 '{row['tag']}' → category NULL "
                      f"(code={row['code']})")
            phone, email = parse_contact(row["contact_raw"])
            first_card = row["cards"][0]

            cur.execute(
                """
                INSERT INTO achievement
                    (owner_user_id, org_id, source_org_name, title,
                     category_id, tech_intro, maturity_level,
                     innovation_points, pricing_mode,
                     contact_name, contact_phone, contact_email,
                     status, published_at, created_at, updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,'02_lab',%s,'negotiable',%s,%s,%s,
                        'published', %s::timestamptz, %s::timestamptz,
                        %s::timestamptz)
                RETURNING id
                """,
                (OWNER_USER_ID, org_id, ORG_NAME,
                 row["title"][:200], cat_id,
                 row["intro"] or None,
                 json.dumps(parse_innovation_points(row["result_list"]),
                            ensure_ascii=False)
                 if parse_innovation_points(row["result_list"]) else None,
                 first_card["name"] or None, phone, email,
                 row["created_at"] or None, row["created_at"] or None,
                 row["created_at"] or None),
            )
            ach_id = cur.fetchone()["id"]
            ach_count += 1

            for order, card in enumerate(row["cards"]):
                if not card["name"]:
                    continue
                contribution = (card["intro"] or "").strip()[:255] or None
                cur.execute(
                    """
                    INSERT INTO inventor (name, org_name, person_type)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (name, org_name) DO NOTHING
                    RETURNING id
                    """,
                    (card["name"], ORG_NAME,
                     "first_inventor" if order == 0 else "co_inventor"),
                )
                got = cur.fetchone()
                if got:
                    inv_new += 1
                    inv_id = got["id"]
                else:
                    cur.execute(
                        "SELECT id FROM inventor WHERE name=%s AND org_name=%s",
                        (card["name"], ORG_NAME))
                    inv_id = cur.fetchone()["id"]
                cur.execute(
                    """
                    INSERT INTO achievement_inventor
                        (achievement_id, inventor_id, sort_order, contribution)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (achievement_id, inventor_id) DO NOTHING
                    """,
                    (ach_id, inv_id, order, contribution))

        conn.commit()
        print(f"\n导入完成: 成果 {ach_count} 条 / 新增发明人 {inv_new} 位")

        # 4. 结果校验
        cur.execute("SELECT COUNT(*) AS c FROM achievement")
        print(f"校验 achievement = {cur.fetchone()['c']}")
        cur.execute("SELECT COUNT(*) AS c FROM inventor")
        print(f"校验 inventor = {cur.fetchone()['c']}")
        cur.execute("SELECT COUNT(*) AS c FROM achievement_inventor")
        print(f"校验 achievement_inventor = {cur.fetchone()['c']}")
        cur.execute(
            "SELECT c.name, COUNT(a.id) AS n FROM achievement a "
            "JOIN achievement_category c ON a.category_id=c.id "
            "GROUP BY c.name ORDER BY n DESC")
        print("分类分布:", [(r["name"], r["n"]) for r in cur.fetchall()])
        cur.execute(
            "SELECT COUNT(*) AS c FROM achievement "
            "WHERE innovation_points IS NOT NULL")
        print(f"含创新点结构化内容: {cur.fetchone()['c']} 条")
        cur.execute(
            "SELECT id, title FROM achievement WHERE id=1")
        first = cur.fetchone()
        print(f"id=1: {first['title']}")
    except Exception:
        conn.rollback()
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
