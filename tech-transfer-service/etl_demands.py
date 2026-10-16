"""
需求演示数据 ETL —— 前端 mock-data.js demandList → demand 表（status=published）

Architecture source: 05-data-model-design.md §12.2（演示数据字段映射表）
字段映射：
  company      → organization（get-or-create）+ demand.org_id；companyIntro → organization.intro
  location     → demand.region
  budget       → budget_min_wan / budget_max_wan / budget_negotiable（"面议"→negotiable=1）
  demandDesc   → demand.description（title 取摘要）
  cooperationType → demand.coop_mode JSON（按 " / " 拆分）
  deadline     → demand.deadline_desc
  industry     → demand_category（首段）+ demand_tag（次段）
  contact*     → demand.contact_*
幂等：按 title+owner 已存在则跳过，可重复执行。
"""
import json

from db import transaction

# 演示需求归属 dev-user-002（app_user 2）：与前端 mock 票据身份 dev-user-001 区分，
# 保证本地演示时"浏览他人需求 + 发起对接"与"我发布的需求"两条链路同时可用
DEMO_OWNER_USER_ID = 2

DEMO_DEMANDS = [
    {
        "title": "高精度视觉检测算法合作需求",
        "company": "深圳智造装备有限公司",
        "location": "广东 · 深圳南山",
        "budget": "80–120 万",
        "demandDesc": "寻求高精度视觉检测算法合作，用于产线缺陷识别与实时质检，期望 3 个月内完成样机验证。",
        "companyIntro": "专注智能制造装备与工业视觉系统，服务电子、汽车零部件等行业客户。",
        "cooperationType": "技术合作 / 联合开发",
        "deadline": "期望 3 个月内完成样机",
        "industry": "智能制造 · 工业视觉",
        "contactName": "王工",
        "contactTitle": "技术负责人",
        "phone": "13800001111",
        "email": "wangong@sz-smart.cn",
        "wechat": "sz_smart_wang",
    },
    {
        "title": "生物基可降解材料配方与中试工艺需求",
        "company": "江门绿能新材料科技",
        "location": "广东 · 江门",
        "budget": "50 万以内",
        "demandDesc": "需要可量产的生物基可降解材料配方与中试工艺支持，重点关注成本可控与环保认证。",
        "companyIntro": "新材料研发与应用企业，产品覆盖包装、日化等领域。",
        "cooperationType": "成果转化 / 工艺授权",
        "deadline": "本年度内完成中试",
        "industry": "新材料 · 绿色包装",
        "contactName": "李经理",
        "contactTitle": "研发总监",
        "phone": "13900002222",
        "email": "li@jm-green.com",
        "wechat": "jm_green_li",
    },
    {
        "title": "医学影像 AI 辅助诊断成果引进需求",
        "company": "南山数科医疗科技",
        "location": "广东 · 深圳南山",
        "budget": "面议",
        "demandDesc": "引进医学影像 AI 辅助诊断相关成果，需具备临床验证基础，并支持私有化部署。",
        "companyIntro": "深耕智慧医疗与影像信息化，面向医院与体检机构提供解决方案。",
        "cooperationType": "技术引进 / 产品合作",
        "deadline": "尽快启动对接评估",
        "industry": "智慧医疗 · 医学影像",
        "contactName": "陈医生",
        "contactTitle": "产品合作负责人",
        "phone": "13700003333",
        "email": "chen@ns-medtech.com",
        "wechat": "ns_med_chen",
    },
]


def parse_budget(text):
    """'80–120 万'→(80,120,0)；'50 万以内'→(None,50,0)；'面议'→(None,None,1)"""
    text = (text or "").replace(" ", "")
    if "面议" in text:
        return None, None, 1
    import re
    m = re.match(r"^(\d+(?:\.\d+)?)[–\-~至](\d+(?:\.\d+)?)万?$", text.replace("万", ""))
    if m:
        return float(m.group(1)), float(m.group(2)), 0
    m = re.match(r"^(\d+(?:\.\d+)?)万以内$", text)
    if m:
        return None, float(m.group(1)), 0
    return None, None, 0


def get_or_create(cur, table, code, name):
    cur.execute(f"SELECT id FROM {table} WHERE code=%s", (code,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur.execute(f"INSERT INTO {table} (code, name) VALUES (%s, %s) RETURNING id", (code, name))
    return cur.fetchone()["id"]


def main():
    # 整批原子写入：任一条失败全部回滚，不留半批演示数据
    with transaction() as conn, conn.cursor() as cur:
        for demo in DEMO_DEMANDS:
            cur.execute(
                "SELECT id FROM demand WHERE title=%s AND owner_user_id=%s",
                (demo["title"], DEMO_OWNER_USER_ID),
            )
            if cur.fetchone():
                print(f"skip (exists): {demo['title']}")
                continue

            # organization get-or-create
            cur.execute("SELECT id FROM organization WHERE org_name=%s", (demo["company"],))
            org_row = cur.fetchone()
            if org_row:
                org_id = org_row["id"]
            else:
                cur.execute(
                    "INSERT INTO organization (org_name, intro, region) VALUES (%s, %s, %s) RETURNING id",
                    (demo["company"], demo["companyIntro"], demo["location"]),
                )
                org_id = cur.fetchone()["id"]

            # category / tag（industry 首段=分类，次段=标签）
            industry_parts = [p.strip() for p in demo["industry"].split("·")]
            category_id = get_or_create(cur, "demand_category", industry_parts[0], industry_parts[0])
            tag_ids = [get_or_create(cur, "demand_tag", t, t) for t in industry_parts[1:]]

            budget_min, budget_max, negotiable = parse_budget(demo["budget"])
            coop_mode = json.dumps(
                [p.strip() for p in demo["cooperationType"].split("/")], ensure_ascii=False
            )

            cur.execute(
                """
                    INSERT INTO demand
                        (owner_user_id, org_id, title, category_id, description, region,
                         coop_mode, budget_min_wan, budget_max_wan, budget_negotiable,
                         deadline_desc, contact_name, contact_title, contact_phone,
                         contact_email, contact_wechat, status, published_at)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            'published', NOW())
                    RETURNING id
                    """,
                (
                    DEMO_OWNER_USER_ID, org_id, demo["title"], category_id,
                    demo["demandDesc"], demo["location"], coop_mode,
                    budget_min, budget_max, negotiable, demo["deadline"],
                    demo["contactName"], demo["contactTitle"], demo["phone"],
                    demo["email"], demo["wechat"],
                ),
            )
            demand_id = cur.fetchone()["id"]
            for tag_id in tag_ids:
                cur.execute(
                    "INSERT INTO demand_tag_relation (demand_id, tag_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                    (demand_id, tag_id),
                )
            print(f"inserted: {demo['title']} (id={demand_id}, org={demo['company']})")

        cur.execute(
            "SELECT COUNT(*) AS c FROM demand WHERE status='published' AND deleted_at IS NULL"
        )
        print("published demands:", cur.fetchone()["c"])


if __name__ == "__main__":
    main()
