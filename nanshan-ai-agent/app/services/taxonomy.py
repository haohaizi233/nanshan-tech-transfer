"""业务分类词表的单一事实源（Single Source of Truth）。

背景：Agent 侧此前把成熟度 / 合作方式的枚举写死在 prompt 与正则里，与生产库
实际取值不一致（生产库成果成熟度全部为 02_lab、需求 coop_mode 取值为
「联合研发 / 技术服务 / 成果转化 / 工艺授权」），导致硬性条件恒定命中 0 条。
本模块把这些枚举集中管理，并提供：

- 成熟度解析（兼容后端与 Agent 历史上并存的多套中文标签）
- 合作方式别名归一（用户说法 -> 库内实际取值集合）
- 技术领域登记表（用于约束「裸领域词」启发式，避免把闲聊当成业务查询）
- 硬性条件 / 软偏好的判定词表
"""

from __future__ import annotations

import re
from dataclasses import dataclass


# ── 成熟度 ────────────────────────────────────────────────────────────────

MATURITY_ORDER = (
    "01_idea",
    "02_lab",
    "03_pilot_ready",
    "04_pilot_done",
    "05_mass_ready",
    "06_mass_done",
)

# 历史数据、后端展示与 Agent 展示并存多套标签，解析时全部接受。
# 顺序敏感：先匹配更长的标签，避免「中试完成」被「中试」类短标签抢先命中。
MATURITY_LABEL_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("01_idea", ("概念阶段", "概念验证", "创意阶段", "idea stage")),
    ("02_lab", ("实验室验证", "实验室阶段", "小试", "lab stage")),
    ("03_pilot_ready", ("中试就绪", "可进入中试", "中试准备", "pilot ready")),
    ("04_pilot_done", ("中试完成", "已完成中试", "中试结束", "pilot done")),
    ("05_mass_ready", ("量产就绪", "可量产", "量产准备", "mass ready")),
    ("06_mass_done", ("已量产", "量产完成", "批量生产", "mass done")),
)

# 展示标签沿用 Agent 既有文案，避免改变已有接口输出。
MATURITY_DISPLAY = {
    "01_idea": "概念阶段",
    "02_lab": "实验室验证",
    "03_pilot_ready": "中试就绪",
    "04_pilot_done": "中试完成",
    "05_mass_ready": "量产就绪",
    "06_mass_done": "已量产",
}


def maturity_label(level: str | None) -> str | None:
    if not level:
        return None
    return MATURITY_DISPLAY.get(level, level)


def maturity_at_least(level: str | None, minimum: str | None) -> bool:
    """成熟度是否达到下限。未知（None）一律不满足硬性成熟度要求。"""
    if not minimum:
        return True
    if not level or level not in MATURITY_ORDER or minimum not in MATURITY_ORDER:
        return False
    return MATURITY_ORDER.index(level) >= MATURITY_ORDER.index(minimum)


def find_maturity_level(text: str) -> str | None:
    """从自然语言中解析成熟度等级（不含「以上/不低于」等边界语义）。"""
    span = find_maturity_span(text)
    return span[0] if span else None


def find_maturity_span(text: str) -> tuple[str, int] | None:
    """返回 ``(等级, 命中起始下标)``；起始下标用于判断该条件是否只是软偏好。"""
    if not text:
        return None
    best: tuple[str, int] | None = None
    for level, labels in MATURITY_LABEL_GROUPS:
        for label in labels:
            position = text.find(label)
            if position < 0:
                continue
            # 多个标签同时命中时取更靠前者，保证结果稳定。
            if best is None or position < best[1]:
                best = (level, position)
    return best


# ── 合作方式 ──────────────────────────────────────────────────────────────

# 生产库 coop_mode 实际取值：联合研发 / 技术服务 / 成果转化 / 工艺授权。
# 用户常见说法与之不一致（「联合开发」vs「联合研发」），必须做别名归一。
COOP_MODE_GROUPS: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "联合研发",
        ("联合研发", "联合开发", "联合研究", "合作开发", "联合攻关", "合作研发"),
    ),
    ("技术服务", ("技术服务", "服务外包", "技术服务合作")),
    ("成果转化", ("成果转化", "技术转让", "转让", "成果转让")),
    ("许可授权", ("工艺授权", "技术许可", "许可授权", "专利许可", "授权")),
)

# 旧 Agent 枚举保留兼容，便于历史 queryPlan 继续被解析。
COOP_MODE_LEGACY = ("联合开发", "技术转让", "技术许可", "委托开发")

COOP_MODE_ALL_SPELLINGS = tuple(
    dict.fromkeys(
        [spelling for _, spellings in COOP_MODE_GROUPS for spelling in spellings]
        + list(COOP_MODE_LEGACY)
    )
)

# 未登记词条时的兜底：取前两个字做词根匹配，覆盖「联合XXX」这类命名漂移。
_COOP_STEM = re.compile(r"^[\u4e00-\u9fa5A-Za-z]{2,12}$")


def resolve_coop_modes(term: str) -> list[str]:
    """把用户说的合作方式归一到库内可能出现的取值集合。

    返回值用于 SQL 的 OR 匹配；命中任一即视为满足该硬性条件。
    """
    text = (term or "").strip()
    if not text:
        return []
    for _, spellings in COOP_MODE_GROUPS:
        for spelling in spellings:
            if spelling in text or text in spelling:
                return list(spellings)
    if _COOP_STEM.match(text):
        return [text[:2]]
    return [text]


def canonical_coop_mode(term: str) -> str | None:
    """把合作方式说法归一为库内标准组名（写入查询计划用）。"""
    text = (term or "").strip()
    if not text:
        return None
    for canonical, spellings in COOP_MODE_GROUPS:
        for spelling in spellings:
            if spelling in text or text in spelling:
                return canonical
    return None


def detect_coop_modes(text: str) -> list[str]:
    """从自然语言中识别用户要求的合作方式（返回标准组名，已去重）。"""
    message = text or ""
    found: list[str] = []
    for spelling in sorted(COOP_MODE_ALL_SPELLINGS, key=len, reverse=True):
        if spelling in message:
            canonical = canonical_coop_mode(spelling) or spelling
            if canonical not in found:
                found.append(canonical)
    return found


def coop_mode_stem(term: str) -> str:
    """合作方式兜底词根（用于登记表未覆盖时的二次放宽检索）。"""
    text = (term or "").strip()
    return text[:2] if len(text) >= 2 else text


# ── 技术领域登记表 ────────────────────────────────────────────────────────

# 受控同义词表：既是检索扩展表，也是「裸领域词」启发式的白名单。
KEYWORD_EXPANSIONS: dict[str, list[str]] = {
    "人工智能": [
        "人工智能", "AI", "artificial intelligence",
        "机器学习", "machine learning", "深度学习", "deep learning",
    ],
    "AI": [
        "AI", "人工智能", "artificial intelligence",
        "机器学习", "machine learning", "深度学习", "deep learning",
    ],
    "机器视觉": [
        "机器视觉", "machine vision", "computer vision",
        "视觉检测", "图像识别",
    ],
    "生物医药": [
        "生物医药", "生物", "医药", "生物医学", "生物技术",
        "biology", "biological", "pharmaceutical", "medical",
    ],
    "生物": [
        "生物", "生物医药", "生物医学", "生物技术", "医药",
        "biology", "biological", "pharmaceutical", "medical",
    ],
    "芯片": [
        "芯片", "半导体", "集成电路",
        "chip", "semiconductor", "integrated circuit",
    ],
}

# 允许「XX 方面 / XX 领域 / XX 相关」这类裸领域短句直接进入检索的登记领域。
REGISTERED_DOMAINS = frozenset(KEYWORD_EXPANSIONS)

# 领域同义登记（用于把「半导体」也视作已登记领域）。
DOMAIN_ALIASES: dict[str, str] = {
    "半导体": "芯片",
    "集成电路": "芯片",
    "artificial intelligence": "人工智能",
    "machine learning": "人工智能",
    "deep learning": "人工智能",
    "computer vision": "机器视觉",
    "machine vision": "机器视觉",
    "图像识别": "机器视觉",
    "视觉检测": "机器视觉",
    "生物医学": "生物医药",
    "生物技术": "生物医药",
    "医药": "生物医药",
}


def is_registered_domain(text: str) -> bool:
    """判断一个裸词是否是已登记的技术领域（用于拦截闲聊 / 无效短语）。"""
    value = (text or "").strip()
    if not value:
        return False
    if value in REGISTERED_DOMAINS:
        return True
    return DOMAIN_ALIASES.get(value.casefold()) in REGISTERED_DOMAINS


# ── 硬性条件 / 软偏好 ────────────────────────────────────────────────────

# 软偏好标记：出现这些词说明后面的条件是「倾向」而不是「必须」。
PREFERENCE_MARKERS = (
    "优先考虑", "优先推荐", "优先选择", "优先", "首选", "最佳", "最好",
    "倾向", "倾向于", "更希望", "更看重", "更关注", "尽量", "希望是",
    "最好是", "酌情", "优先考虑",
)

# 硬性覆盖标记：即使前面有软偏好词，也按硬性条件处理。
HARD_OVERRIDE_MARKERS = (
    "必须", "只能", "仅限", "只限", "限定", "严格", "务必", "一定要",
    "不得", "不能超过",
)

# 显式赋值标记：用户明确说出「改成 / 限定为 / 要求」时，该条件是硬性条件。
HARD_SET_MARKERS = (
    "改成", "改为", "调整为", "调整到", "限定为", "限定", "必须是", "只能是",
    "要求", "要达到", "设为", "设置为", "变成", "切到", "换成",
)

# 硬性边界词：明确的上限 / 下限表达。
HARD_BOUND_MARKERS = (
    "以内", "以下", "之内", "不超过", "不高于", "不大于", "最多", "最高",
    "上限", "封顶", "以上", "起步", "不少于", "不低于", "至少", "最低",
    "下限", "高于", "超过", "必须", "限定为", "限定", "只能是",
)

# 软偏好编码（写入 queryPlan.preferences，供重排阶段加权使用）。
PREFERENCE_CODES = (
    "prefer_recent",        # 优先最新发布
    "prefer_mature",        # 优先成熟度更高
    "prefer_stable_price",  # 优先报价 / 预算明确
    "prefer_low_price",     # 优先报价落在用户预算内（软上限，不做硬过滤）
    "prefer_local",         # 优先本地 / 同机构
    "prefer_popular",       # 优先热度高
)

PREFERENCE_CODE_SET = frozenset(PREFERENCE_CODES)

# 软偏好语义 -> 偏好编码
PREFERENCE_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"最新发布|最新的?|最近的?|新发布|近期"), "prefer_recent"),
    (re.compile(r"成熟度(?:更高|高的?|好)|更成熟|成熟的?|验证充分"), "prefer_mature"),
    (re.compile(r"报价(?:明确|清楚|清晰)|价格(?:明确|清楚|清晰)|预算(?:明确|清楚|清晰)"), "prefer_stable_price"),
    (re.compile(r"本地|本地机构|本地成果|本地需求|本区|区内"), "prefer_local"),
    (re.compile(r"热门|受欢迎|关注度|浏览量|高热度"), "prefer_popular"),
)

# 软偏好标记命中时，条件回看窗口（字符数）。
PREFERENCE_LOOKBACK = 10


def has_preference_marker(text: str) -> bool:
    return any(marker in (text or "") for marker in PREFERENCE_MARKERS)


def has_hard_override(text: str) -> bool:
    return any(marker in (text or "") for marker in HARD_OVERRIDE_MARKERS)


def detect_preferences(text: str) -> list[str]:
    """从用户原话中识别软偏好编码（确定性规则，不依赖模型）。"""
    found: list[str] = []
    for pattern, code in PREFERENCE_PATTERNS:
        if pattern.search(text or "") and code not in found:
            found.append(code)
    return found


def is_soft_condition(text: str, start: int) -> bool:
    """判断位于 ``start`` 处的条件是否只是软偏好。

    规则：条件前方的回看窗口内出现软偏好标记、且没有硬性覆盖标记时，
    该条件视为软偏好（不进入数据库硬过滤）。
    """
    segment = (text or "")[max(0, start - PREFERENCE_LOOKBACK):start]
    if not segment:
        return False
    if has_hard_override(segment):
        return False
    if has_explicit_set(segment):
        return False
    return has_preference_marker(segment)


def has_explicit_set(segment: str) -> bool:
    """片段里是否出现显式赋值动词（改成 / 限定为 / 要求 …）。"""
    return any(marker in (segment or "") for marker in HARD_SET_MARKERS)


# ── 检索字段权重 ──────────────────────────────────────────────────────────
#
# 相关度模型（SQL 与 Python 必须完全一致，否则两阶段排序会互相打架）：
#   相关度 = Σ_词条 系数(词条) × (标题命中×5 + 正文命中×3)
# 标题权重高于正文；用户原词系数 3，同义词扩展系数 1。
# 正文使用「多字段拼接表达式」：WHERE 判定与打分各只需一次 ILIKE / 词条。

TITLE_WEIGHT = 5
BODY_WEIGHT = 3

ACHIEVEMENT_TITLE_EXPR = "title"
ACHIEVEMENT_BODY_EXPR = (
    "coalesce(tech_intro, '') || ' ' || "
    "coalesce(application_fields::text, '') || ' ' || "
    "coalesce(innovation_points::text, '') || ' ' || "
    "coalesce(source_org_name, '')"
)

DEMAND_TITLE_EXPR = "title"
DEMAND_BODY_EXPR = (
    "coalesce(description, '') || ' ' || "
    "coalesce(org_name_snapshot, '') || ' ' || "
    "coalesce(region, '') || ' ' || "
    "coalesce(coop_mode::text, '')"
)


@dataclass(frozen=True)
class SearchFields:
    """一次检索涉及的可读字段（SQL 表达式 + 展示用键名）。"""

    title_sql: str
    body_sql: str
    title_key: str
    body_keys: tuple[str, ...]


ACHIEVEMENT_FIELDS = SearchFields(
    title_sql=ACHIEVEMENT_TITLE_EXPR,
    body_sql=ACHIEVEMENT_BODY_EXPR,
    title_key="title",
    body_keys=("tech_intro", "application_fields", "innovation_points", "source_org_name"),
)

DEMAND_FIELDS = SearchFields(
    title_sql=DEMAND_TITLE_EXPR,
    body_sql=DEMAND_BODY_EXPR,
    title_key="title",
    body_keys=("description", "org_name_snapshot", "region", "coop_mode"),
)

# 同义词扩展词的权重系数：用户原词命中显著高于扩展词命中。
LITERAL_TERM_MULTIPLIER = 3
EXPANDED_TERM_MULTIPLIER = 1

# 单次查询最多使用的同义词扩展数（控制 ILIKE 谓词数量，避免拖垮 SQL）。
MAX_EXPANDED_TERMS = 4
# 用户原词上限。
MAX_LITERAL_TERMS = 4


def fields_for(kind: str) -> SearchFields:
    return ACHIEVEMENT_FIELDS if kind == "achievement" else DEMAND_FIELDS


def combined_expression(kind: str) -> str:
    """把全部可检索字段拼成一个表达式，用于 WHERE 判定（单次 ILIKE 而非 N 次）。"""
    fields = fields_for(kind)
    return f"coalesce({fields.title_sql}, '') || ' ' || {fields.body_sql}"


# ── 金额区间语义 ──────────────────────────────────────────────────────────

def is_invalid_number(value) -> bool:
    """判断字段值是否为非法数值（NaN / Inf / 非数字）。

    与「字段缺失」严格区分：缺失代表「未知」，非法数值代表「数据损坏」，
    后者必须 fail closed，不能因为无法比较就放行。
    """
    if value is None:
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return True
    if number != number:
        return True
    return number in (float("inf"), float("-inf"))


def amount_band_matches(record_lower, record_upper, user_lower, user_upper) -> bool:
    """价格 / 预算区间与用户条件是否相容（区间重叠语义）。

    修复前语义：``price_max_wan IS NOT NULL AND price_max_wan <= 上限``。
    生产库里 222/223 条成果报价为「面议」（price 字段为 NULL），
    旧语义会把**整个成果库**过滤干净，用户问「100 万元以内的成果」恒定 0 条。

    现在的语义：

    - 记录端价格未知（None）→ 未知不等于不符，**不排除**，由重排阶段降权并标注；
    - 记录端价格非法（NaN/Inf）→ 数据损坏，**排除**（fail closed）；
    - 用户给上限 → 记录价格下限高于上限才排除；
    - 用户给下限 → 记录价格上限低于下限才排除。
    """
    if is_invalid_number(record_lower) or is_invalid_number(record_upper):
        return False
    if user_upper is not None and record_lower is not None:
        if float(record_lower) > float(user_upper):
            return False
    if user_lower is not None and record_upper is not None:
        if float(record_upper) < float(user_lower):
            return False
    return True


def price_is_unknown(record_lower, record_upper) -> bool:
    """记录端价格是否完全未知（面议 / 未填写）。"""
    return record_lower is None and record_upper is None
