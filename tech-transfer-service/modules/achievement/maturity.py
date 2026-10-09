"""成果成熟度枚举与展示文案。"""

MATURITY_LEVELS = ("01_idea", "02_lab", "03_pilot_ready", "04_pilot_done", "05_mass_ready")
MATURITY_LABELS = {
    "01_idea": "概念阶段",
    "02_lab": "实验室验证",
    "03_pilot_ready": "可进入中试",
    "04_pilot_done": "中试完成",
    "05_mass_ready": "可量产",
}


def resolve_maturity_desc(level, desc=None):
    """优先用显式描述；缺省或回传枚举码时按成熟度回填中文。"""
    text = str(desc).strip() if desc else ""
    if text and text not in MATURITY_LEVELS:
        return text
    return MATURITY_LABELS.get(level) or text or None
