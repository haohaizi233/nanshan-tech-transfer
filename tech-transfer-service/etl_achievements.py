"""
成果 ETL 脚本 —— 生成 223 条成果数据并导入 tech_transfer 数据库
可重复执行：每次清空已有数据后全量导入
"""
import json
import random
import pymysql
from datetime import datetime, timedelta

random.seed(42)

# 演示成果归属 dev-user-002（app_user 2）：与前端 mock 票据身份 dev-user-001 区分，
# 使默认用户可对成果发起对接（不能对接自己发布的内容），与 etl_demands.py 约定一致
DEMO_OWNER_USER_ID = 2

DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": "123456",
    "database": "tech_transfer",
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
}

# ── 分类 ──────────────────────────────────────────────────
CATEGORIES = [
    ("new_material", "新材料", 1),
    ("smart_mfg", "智能制造", 2),
    ("biomed", "生物医药", 3),
    ("it", "信息技术", 4),
    ("new_energy", "新能源", 5),
    ("eco_env", "节能环保", 6),
    ("electronics", "电子信息", 7),
    ("precision", "精密制造", 8),
    ("ai", "人工智能", 9),
    ("agri_food", "农业与食品", 10),
]

# ── 机构池 ────────────────────────────────────────────────
ORGS = [
    ("中国科学院深圳先进技术研究院", "institute", "广东·深圳南山"),
    ("南方科技大学", "university", "广东·深圳南山"),
    ("中山大学", "university", "广东·广州"),
    ("深圳大学", "university", "广东·深圳南山"),
    ("哈尔滨工业大学（深圳）", "university", "广东·深圳南山"),
    ("清华大学深圳国际研究生院", "university", "广东·深圳南山"),
    ("中国科学院深圳理工大学", "institute", "广东·深圳南山"),
    ("深圳先进电子材料国际创新研究院", "institute", "广东·深圳南山"),
    ("广东省人工智能产业研究院", "institute", "广东·深圳"),
    ("深圳市机器人研究院", "institute", "广东·深圳南山"),
    ("澳门大学", "university", "澳门"),
    ("华南理工大学", "university", "广东·广州"),
    ("深圳技术大学", "university", "广东·深圳"),
    ("鹏城实验室", "institute", "广东·深圳"),
    ("中科院深圳先进院-合成所", "institute", "广东·深圳南山"),
]

# ── 成果模板池（按分类） ──────────────────────────────────
ACHIEVEMENT_TEMPLATES = {
    "new_material": [
        ("二维黑磷半导体材料制备技术", "面向光电与传感应用的二维黑磷制备与稳定化工艺", ["光电探测器", "柔性传感器", "高性能晶体管"], "02_lab", "实验室验证完成，可进入中试"),
        ("低成本海水淡化膜材料与组件", "提升抗污染与使用寿命，降低运维成本", ["工业用水", "海岛供水", "膜分离"], "02_lab", "实验室验证完成，可提供样品"),
        ("高导热石墨烯复合材料", "面向热管理的高导热石墨烯复合制备工艺", ["电子散热", "动力电池热管理", "LED散热"], "03_pilot_ready", "可进入中试"),
        ("柔性透明导电薄膜", "替代ITO的柔性透明电极材料", ["柔性显示", "触控屏", "光伏电池"], "03_pilot_ready", "可进入中试"),
        ("高性能碳纤维复合材料", "T800级碳纤维国产化制备技术", ["航空航天", "汽车轻量化", "压力容器"], "04_pilot_done", "中试完成"),
        ("生物基可降解材料配方", "PBS基全生物降解材料低成本配方", ["绿色包装", "农用地膜", "一次性用品"], "02_lab", "实验室验证完成"),
        ("钙钛矿太阳能电池材料", "高效率钙钛矿吸光层制备工艺", ["太阳能发电", "建筑光伏"], "02_lab", "实验室验证完成"),
        ("超疏水自清洁涂层", "基于纳米结构的超疏水表面技术", ["建筑外墙", "汽车涂层", "船舶防污"], "03_pilot_ready", "可进入中试"),
    ],
    "smart_mfg": [
        ("工业机器人柔顺力控算法包", "适用于装配打磨等接触式作业的柔顺控制", ["3C装配", "汽车零部件", "精密打磨"], "04_pilot_done", "已完成产线试点验证"),
        ("数字孪生产线仿真平台", "面向产线规划与优化的数字孪平台", ["智能制造", "产线优化", "工厂仿真"], "04_pilot_done", "产线试点完成"),
        ("机器视觉表面缺陷检测系统", "基于深度学习的实时缺陷识别", ["3C质检", "面板检测", "半导体"], "04_pilot_done", "产线试点完成"),
        ("协作机器人安全监控模块", "人机协作场景的安全感知与停机", ["协作机器人", "安全防护"], "03_pilot_ready", "可进入中试"),
        ("智能焊接参数自适应系统", "焊接参数实时调整与质量预测", ["汽车制造", "船舶焊接", "钢结构"], "03_pilot_ready", "可进入中试"),
        ("柔性产线调度优化算法", "多品种小批量产线的智能调度", ["3C制造", "电子组装"], "04_pilot_done", "产线试点完成"),
        ("AGV路径规划与避障系统", "复杂仓储环境的自主导航", ["智能仓储", "物流配送"], "04_pilot_done", "产线试点完成"),
    ],
    "biomed": [
        ("医学影像AI辅助诊断系统", "肺结节CT影像AI筛查算法", ["医学影像", "AI诊断", "肺癌筛查"], "03_pilot_ready", "可进入临床试验"),
        ("纳米药物递送载体平台", "脂质体药物递送系统通用平台", ["靶向给药", "抗肿瘤", "缓释制剂"], "02_lab", "实验室验证完成"),
        ("可降解心血管支架", "聚乳酸可吸收支架材料与工艺", ["介入器械", "心血管"], "04_pilot_done", "已完成动物实验"),
        ("PCR快速检测试剂盒", "恒温扩增快速核酸检测技术", ["体外诊断", "核酸检测", "即时检测"], "05_mass_ready", "可量产"),
        ("生物传感器芯片", "电化学检测生物标志物芯片", ["即时检测", "血糖监测", "环境监测"], "03_pilot_ready", "可进入中试"),
        ("组织工程人工皮肤", "脱细胞基质人工皮肤支架", ["烧伤修复", "创面覆盖"], "02_lab", "实验室验证完成"),
        ("微流控细胞分选芯片", "高通量单细胞分选微流控器件", ["细胞治疗", "液体活检", "稀有细胞捕获"], "02_lab", "实验室验证完成"),
        ("中药有效成分缓释微球", "中药单体缓释微球制备", ["中药现代化", "药物递送"], "03_pilot_ready", "可进入中试"),
    ],
    "it": [
        ("边缘计算实时推理框架", "面向IoT设备的轻量推理引擎", ["工业物联网", "智能终端", "边缘AI"], "04_pilot_done", "已完成部署验证"),
        ("区块链数据确权平台", "科技成果权属链上登记与存证", ["数据确权", "知识产权", "技术转移"], "04_pilot_done", "已完成部署验证"),
        ("联邦学习隐私计算框架", "多方数据协作训练框架", ["金融风控", "医疗数据", "广告投放"], "03_pilot_ready", "可进入试点"),
        ("知识图谱构建与推理引擎", "科技成果领域知识图谱", ["技术检索", "智能匹配", "图谱分析"], "04_pilot_done", "已完成部署验证"),
        ("低代码表单引擎", "动态表单配置与渲染引擎", ["数据采集", "审批流程", "企业应用"], "05_mass_ready", "可量产"),
        ("分布式任务调度中间件", "高可用分布式定时任务框架", ["微服务", "批处理", "ETL"], "05_mass_ready", "可量产"),
    ],
    "new_energy": [
        ("高安全固态电池电解质", "硫化物固态电解质制备工艺", ["动力电池", "储能", "消费电子"], "03_pilot_ready", "可进入中试"),
        ("钠离子电池正极材料", "层状氧化物钠离子正极材料", ["储能电池", "低速车"], "02_lab", "实验室验证完成"),
        ("钙钛矿叠层太阳能电池", "硅-钙钛矿叠层电池技术", ["光伏发电", "建筑光伏"], "03_pilot_ready", "可进入中试"),
        ("氢燃料电池催化剂", "低铂高活性燃料电池催化剂", ["氢能", "燃料电池", "新能源汽车"], "03_pilot_ready", "可进入中试"),
        ("锂电池梯次利用分选系统", "退役电池梯次利用快速分选", ["储能", "电池回收"], "04_pilot_done", "产线试点完成"),
        ("光伏组件智能运维平台", "组串级故障诊断与发电优化", ["光伏运维", "故障诊断"], "04_pilot_done", "已完成部署验证"),
    ],
    "eco_env": [
        ("VOCs低温催化氧化催化剂", "高效低温VOCs催化氧化材料", ["工业废气", "涂装", "印刷"], "03_pilot_ready", "可进入中试"),
        ("高盐废水膜分质处理技术", "分盐结晶零排放工艺", ["工业废水", "零排放", "盐分资源化"], "04_pilot_done", "产线试点完成"),
        ("厨余垃圾好氧发酵设备", "快速好氧发酵减量化设备", ["厨余垃圾", "有机固废"], "04_pilot_done", "已完成试点"),
        ("土壤重金属稳定化药剂", "重金属污染土壤稳定化修复", ["土壤修复", "矿区治理"], "03_pilot_ready", "可进入中试"),
        ("污水深度处理臭氧催化", "臭氧催化氧化深度处理", ["市政污水", "工业废水"], "04_pilot_done", "产线试点完成"),
    ],
    "electronics": [
        ("GaN功率器件驱动芯片", "氮化镓高频功率器件驱动IC", ["快充电源", "数据中心", "光伏逆变"], "04_pilot_done", "已完成流片验证"),
        ("硅基OLED微显示器件", "硅基微型OLED显示技术", ["AR/VR", "近眼显示", "微型投影"], "03_pilot_ready", "可进入中试"),
        ("MEMS压力传感器芯片", "高精度MEMS压力传感器", ["消费电子", "工业控制", "汽车"], "04_pilot_done", "已完成流片验证"),
        ("毫米波雷达芯片", "77GHz车载毫米波雷达收发IC", ["自动驾驶", "车载雷达"], "03_pilot_ready", "可进入中试"),
        ("柔性印刷电路板材料", "高频高速柔性基板材料", ["5G通信", "可穿戴", "柔性连接"], "03_pilot_ready", "可进入中试"),
    ],
    "precision": [
        ("超精密磨削主轴系统", "纳米级超精密磨削主轴", ["超精密加工", "光学镜头", "模具"], "04_pilot_done", "产线试点完成"),
        ("五轴联动数控系统", "高性能五轴联动CNC系统", ["航空航天", "叶轮加工", "模具制造"], "04_pilot_done", "产线试点完成"),
        ("在线光学检测设备", "亚微米级光学在线检测", ["精密制造", "质量检测"], "03_pilot_ready", "可进入中试"),
        ("激光精密微加工系统", "飞秒激光微纳加工设备", ["微纳制造", "半导体", "生物医用"], "03_pilot_ready", "可进入中试"),
    ],
    "ai": [
        ("大模型轻量化压缩工具", "通用大模型剪枝量化压缩", ["边缘部署", "移动端", "低成本推理"], "04_pilot_done", "已完成部署验证"),
        ("多模态缺陷检测算法", "视觉+触觉多模态质检模型", ["工业质检", "缺陷识别", "质量控制"], "04_pilot_done", "已完成部署验证"),
        ("自然语言到代码生成", "代码自动补全模型微调", ["软件工程", "开发效率", "代码质量"], "04_pilot_done", "已完成部署验证"),
        ("语音情感识别引擎", "多语种情感识别与分析", ["智能客服", "心理健康", "教育"], "03_pilot_ready", "可进入试点"),
        ("工业知识问答系统", "设备运维知识图谱与问答", ["设备运维", "故障排查", "知识管理"], "04_pilot_done", "已完成部署验证"),
        ("智能用药推荐算法", "基于电子病历的用药安全推荐", ["智慧医疗", "合理用药", "药物警戒"], "03_pilot_ready", "可进入试点"),
    ],
    "agri_food": [
        ("植物基替代蛋白食品", "大豆蛋白仿生肉制品工艺", ["人造肉", "健康食品", "素食"], "04_pilot_done", "已完成中试"),
        ("冷链保鲜纳米涂层", "果蔬保鲜纳米涂层材料", ["冷链物流", "果蔬保鲜"], "03_pilot_ready", "可进入中试"),
        ("农业物联网传感节点", "低功耗土壤环境监测节点", ["智慧农业", "土壤监测", "精准灌溉"], "05_mass_ready", "可量产"),
        ("食品快检生物芯片", "农残/致病菌快检微流控芯片", ["食品安全", "快速检测", "农贸市场"], "03_pilot_ready", "可进入中试"),
        ("益生菌发酵剂包埋技术", "高活菌数微胶囊包埋工艺", ["发酵食品", "益生菌", "功能食品"], "03_pilot_ready", "可进入中试"),
    ],
}

# ── 完成人姓名池 ──────────────────────────────────────────
INVENTOR_NAMES = [
    "赵明", "周强", "李伟", "吴芳", "陈杰", "王磊", "张敏", "刘洋",
    "黄涛", "孙红", "徐辉", "胡波", "朱琳", "郭峰", "何静", "高翔",
    "林雪", "郑华", "罗刚", "谢军", "梁宇", "宋佳", "唐飞", "韩雪",
    "曹阳", "秦风", "冯雷", "邓超", "彭勇", "许宁", "于洋", "董敏",
    "萧然", "袁媛", "潘涛", "蔡明", "蒋华", "余斌", "杜鹃", "魏然",
]

CONTACT_TITLES = ["成果转化联系人", "技术成果联系人", "专利转化联系人", "项目主管", "科研处副处长"]
PRICING_MODES = ["negotiable", "license", "transfer", "cooperation"]
MATURITY_LEVELS = ["01_idea", "02_lab", "03_pilot_ready", "04_pilot_done", "05_mass_ready"]
MATURITY_DESCS = {
    "01_idea": "概念阶段，尚在理论验证",
    "02_lab": "实验室验证完成",
    "03_pilot_ready": "可进入中试",
    "04_pilot_done": "已完成产线试点验证",
    "05_mass_ready": "可量产",
}


def generate_223_achievements():
    """生成 223 条成果数据"""
    achievements = []
    inventors = []
    relations = []

    templates = []
    for cat_code, templates_list in ACHIEVEMENT_TEMPLATES.items():
        for t in templates_list:
            templates.append((cat_code, t))

    while len(templates) < 223:
        cat_code, t = random.choice(list(ACHIEVEMENT_TEMPLATES.items()))
        base_title, base_intro, base_fields, base_mat, base_desc = random.choice(t)
        suffix = f"（改进型{len(templates)+1}）"
        templates.append((cat_code, (base_title + suffix, base_intro, base_fields, base_mat, base_desc)))

    for idx, (cat_code, tpl) in enumerate(templates[:223], start=1):
        title, tech_intro, app_fields, maturity, mat_desc = tpl
        org = random.choice(ORGS)
        contact_name = random.choice(INVENTOR_NAMES)
        contact_title = random.choice(CONTACT_TITLES)
        pricing = random.choice(PRICING_MODES)

        if pricing == "negotiable":
            price_min = None
            price_max = None
        else:
            price_min = round(random.uniform(20, 200), 2)
            price_max = round(price_min + random.uniform(10, 100), 2)

        inv1 = random.choice(INVENTOR_NAMES)
        inv2 = random.choice([n for n in INVENTOR_NAMES if n != inv1])

        phone = f"1{random.choice(['3','5','7','8','9'])}{random.randint(0,9):01d}{random.randint(1000000,9999999):07d}"
        email_prefix = contact_name.lower() if contact_name.isascii() else f"contact{idx}"

        days_ago = random.randint(1, 365)
        pub_date = datetime.now() - timedelta(days=days_ago)

        achievements.append({
            "id": idx,
            "owner_user_id": DEMO_OWNER_USER_ID,
            "source_org_name": org[0],
            "org_type": org[1],
            "region": org[2],
            "title": title,
            "category_code": cat_code,
            "tech_intro": tech_intro,
            "tech_route": f"理论建模 → 实验验证 → 工艺优化 → {MATURITY_DESCS[maturity]}",
            "maturity_level": maturity,
            "maturity_desc": mat_desc,
            "application_fields": app_fields,
            "innovation_points": [
                f"技术创新点{random.randint(1,5)}",
                f"核心优势{random.randint(1,5)}",
            ],
            "pricing_mode": pricing,
            "price_min_wan": price_min,
            "price_max_wan": price_max,
            "contact_name": contact_name,
            "contact_title": contact_title,
            "contact_phone": phone,
            "contact_email": f"{email_prefix}@example.edu.cn",
            "contact_wechat": f"tech_{idx:03d}",
            # 浏览量由详情接口在真实访问时原子累计；导入数据不得伪造热度。
            "view_count": 0,
            "published_at": pub_date.strftime("%Y-%m-%d %H:%M:%S"),
        })

        for i, inv_name in enumerate([inv1, inv2]):
            inventors.append({
                "name": inv_name,
                "org_name": org[0],
                "person_type": "first_inventor" if i == 0 else "co_inventor",
                "_achievement_id": idx,
                "_sort_order": i,
            })

    return achievements, inventors


def main():
    conn = pymysql.connect(**DB_CONFIG)
    cur = conn.cursor()

    print("=== 成果 ETL 开始 ===")

    # 清空已有数据（关闭外键检查）
    cur.execute("SET FOREIGN_KEY_CHECKS=0")
    for table in ["achievement_inventor", "achievement", "inventor", "achievement_category", "organization"]:
        cur.execute(f"TRUNCATE TABLE `{table}`")
        print(f"  清空 {table}")
    cur.execute("SET FOREIGN_KEY_CHECKS=1")
    conn.commit()

    # 1. 插入分类
    for code, name, sort_order in CATEGORIES:
        cur.execute(
            "INSERT INTO achievement_category (code, name, sort_order, enabled) VALUES (%s, %s, %s, 1)",
            (code, name, sort_order)
        )
    conn.commit()
    print(f"  插入 {len(CATEGORIES)} 条分类")

    # 2. 插入机构
    org_map = {}
    for org_name, org_type, region in ORGS:
        cur.execute(
            "INSERT INTO organization (org_name, org_type, region, status) VALUES (%s, %s, %s, 'active')",
            (org_name, org_type, region)
        )
        org_map[org_name] = cur.lastrowid
    conn.commit()
    print(f"  插入 {len(ORGS)} 条机构")

    # 3. 生成成果数据
    achievements, inventors = generate_223_achievements()

    cat_map = {}
    cur.execute("SELECT id, code FROM achievement_category")
    for row in cur.fetchall():
        cat_map[row["code"]] = row["id"]

    # 4. 插入成果
    for ach in achievements:
        cur.execute(
            "SELECT id FROM organization WHERE org_name=%s AND status='active'", (ach["source_org_name"],)
        )
        org_row = cur.fetchone()
        org_id = org_row["id"] if org_row else None

        cur.execute(
            """
            INSERT INTO achievement (
                owner_user_id, org_id, source_org_name, title, category_id,
                tech_intro, tech_route, maturity_level, maturity_desc,
                application_fields, innovation_points,
                pricing_mode, price_min_wan, price_max_wan,
                contact_name, contact_title, contact_phone, contact_email, contact_wechat,
                status, view_count, published_at
            ) VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s,
                %s, %s,
                %s, %s, %s,
                %s, %s, %s, %s, %s,
                'published', %s, %s
            )
            """,
            (
                ach["owner_user_id"], org_id, ach["source_org_name"], ach["title"],
                cat_map.get(ach["category_code"]),
                ach["tech_intro"], ach["tech_route"], ach["maturity_level"], ach["maturity_desc"],
                json.dumps(ach["application_fields"], ensure_ascii=False),
                json.dumps(ach["innovation_points"], ensure_ascii=False),
                ach["pricing_mode"], ach["price_min_wan"], ach["price_max_wan"],
                ach["contact_name"], ach["contact_title"], ach["contact_phone"], ach["contact_email"], ach["contact_wechat"],
                ach["view_count"], ach["published_at"],
            )
        )
    conn.commit()
    print(f"  插入 {len(achievements)} 条成果")

    # 5. 插入完成人（去重）
    seen_inventors = {}
    inv_relations = []
    for inv in inventors:
        key = (inv["name"], inv["org_name"])
        if key not in seen_inventors:
            cur.execute(
                "INSERT INTO inventor (name, org_name, person_type) VALUES (%s, %s, %s)",
                (inv["name"], inv["org_name"], inv["person_type"])
            )
            seen_inventors[key] = cur.lastrowid

        inv_relations.append({
            "achievement_id": inv["_achievement_id"],
            "inventor_id": seen_inventors[key],
            "sort_order": inv["_sort_order"],
        })

    # 6. 插入成果-完成人关联
    for rel in inv_relations:
        cur.execute(
            """
            INSERT INTO achievement_inventor (achievement_id, inventor_id, sort_order)
            VALUES (%s, %s, %s)
            """,
            (rel["achievement_id"], rel["inventor_id"], rel["sort_order"])
        )
    conn.commit()
    print(f"  插入 {len(seen_inventors)} 个完成人，{len(inv_relations)} 条关联")

    # 验证
    cur.execute("SELECT COUNT(*) AS c FROM achievement WHERE status='published' AND deleted_at IS NULL")
    count = cur.fetchone()["c"]
    print(f"\n=== ETL 完成：{count} 条成果已发布 ===")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
