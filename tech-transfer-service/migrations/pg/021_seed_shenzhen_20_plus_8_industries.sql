-- 021: 深圳“20+8”产业目录初始值。
-- 名称依据深圳市 2025 年“20+8”产业专利统计口径；目录仍可由平台后续停用或扩展。
INSERT INTO public.industry (code, name, sort_order)
VALUES
    ('sz20-network-communication', '网络与通信', 10),
    ('sz20-semiconductor-integrated-circuit', '半导体与集成电路', 20),
    ('sz20-ultra-hd-display', '超高清视频显示', 30),
    ('sz20-smart-terminal', '智能终端', 40),
    ('sz20-smart-sensor', '智能传感器', 50),
    ('sz20-software-information-service', '软件与信息服务', 60),
    ('sz20-artificial-intelligence', '人工智能', 70),
    ('sz20-digital-creative', '数字创意', 80),
    ('sz20-modern-fashion', '现代时尚', 90),
    ('sz20-high-end-equipment-instruments', '高端装备与仪器', 100),
    ('sz20-low-altitude-aerospace', '低空经济与空天', 110),
    ('sz20-robotics', '机器人', 120),
    ('sz20-new-energy', '新能源', 130),
    ('sz20-energy-conservation-environmental', '安全节能环保', 140),
    ('sz20-intelligent-connected-vehicle', '智能网联汽车', 150),
    ('sz20-high-performance-materials', '高性能材料', 160),
    ('sz20-biomedicine', '生物医药', 170),
    ('sz20-high-end-medical-devices', '高端医疗器械', 180),
    ('sz20-health', '大健康', 190),
    ('sz20-ocean', '海洋', 200),
    ('sz8-synthetic-biology', '合成生物', 210),
    ('sz8-optical-information', '光载信息', 220),
    ('sz8-intelligent-robotics', '智能机器人', 230),
    ('sz8-cell-gene', '细胞与基因', 240),
    ('sz8-brain-science-brain-machine', '脑科学与脑机工程', 250),
    ('sz8-deep-earth-deep-sea', '深地深海', 260),
    ('sz8-quantum-information', '量子信息', 270),
    ('sz8-frontier-new-materials', '前沿新材料', 280)
ON CONFLICT (code) DO UPDATE
SET name = EXCLUDED.name,
    sort_order = EXCLUDED.sort_order,
    updated_at = CURRENT_TIMESTAMP;
