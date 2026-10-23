import re

from app.formatters import normalize_list


_GUIDES = {
    "publish_achievement": "发布成果：进入首页 → 我要发成果，填写成果介绍、应用领域、成熟度和合作等信息，可先预览再提交。登录及资料要求按页面提示完成；提交后的审核与发布状态可在“我的 → 我发布的成果”查看，不代表立即发布成功。",
    "publish_demand": "发布需求：进入首页 → 我要发需求，说明技术难题、应用场景、期望指标、预算及合作方式，预览后提交。未登录时先按提示登录；可在“我的 → 我发布的需求”查看审核和发布状态。",
    "cooperation": "申请对接：打开成果或需求详情 → 我要对接，按提示登录并完善资料，选择本次合作意向、填写说明，再点击“提交对接意向”。自己的内容不能与自己对接，未发布或已有进行中意向时也可能无法重复申请。进度在“我的 → 意向请求”查看；提交不代表对方已接受，也不保证成交。",
    "certification": "机构认证：进入“我的 → 机构认证”。已有机构可申请加入；代表新机构入驻时使用机构入驻入口，按页面填写材料并等待审核。个人资料里的公司名称和主体类型不等于认证，也不会自动获得机构管理员权限。",
    "favorite": "收藏：在首页卡片或详情中点击收藏，再次点击可取消；在“我的 → 我的收藏”查看。收藏不等于申请对接，也不会自动向发布方发送合作意向。",
    "login": "登录与资料：进入“我的”，使用手机号密码登录或注册。若当前微信小程序已开放微信快捷登录，可按提示授权手机号；已有手机号账号先用原账号登录，再绑定微信。头像与联系方式在编辑资料后保存，选择头像但未保存不算完成更新。不要把密码或验证码发给我。",
    "matching": "使用 AI 匹配：可以直接描述“技术方向＋应用场景＋预算或成熟度要求”，例如“推荐用于产线缺陷检测的机器视觉成果”。也可使用页面的需求匹配入口选择自己已发布的需求。我会介绍真实检索结果并说明推荐依据；卡片可点开查看详情，是否可对接以最新详情为准。",
}
_OVERVIEW = (
    "南山科转通用于科技成果与技术需求的发现、展示和对接。我可以介绍真实成果、按场景推荐并解释依据，也可以指导平台操作。\n"
    "• 首页：搜索、查看和收藏成果或需求；通过“我要发成果”“我要发需求”提交内容。\n"
    "• AI匹配：描述方向、场景及预算，获得候选成果介绍与推荐依据。\n"
    "• 我的：登录、编辑资料、机构认证、查看自己的发布和收藏，以及在“意向请求”跟进对接。\n"
    "你可以问“怎么发布成果”，或“推荐适合工业质检的机器视觉成果”。"
)
_EVIDENCE_FIELDS = {
    "title", "tech_intro", "description", "application_fields", "innovation_points", "region", "coop_mode",
}
_GENERIC_WORDS = re.compile(
    r"请|帮我|给我|我想|我要|我|一下|推荐|介绍|解读|讲讲|几个|一些|点|个|些|好的|好|优质|合适|适合我的|的|科技|科研|技术|成果|项目|需求|[\d\s，。！？?]"
)
_REFERENCE_WORDS = re.compile(
    r"请|帮我|介绍|解读|讲讲|对比|一下|这个|那个|它|第[一二三四五六七八九十\d]+个|上一个|刚才的|成果|技术|科技|需求|项目|的|适合我吗|有什么用|怎么样|[\s，。！？?]"
)
_REFERENCE_POINTER = re.compile(
    r"第[一二三四五六七八九十\d]+(?:个|项|条)|(?:这个|那个|上一个|刚才的|上述|上面的)(?:成果|需求|技术|项目|卡片)|^(?:请|帮我|介绍|解读|讲讲|对比|一下|\s)*(?:它|这个|那个)(?:的|有|适|怎|能|可|是|在|和|跟|比)"
)

# 结论性 / 承诺性措辞：除非在原始资料里出现过，否则一律视为模型编造。
_UNSUPPORTED_CLAIMS = (
    "保证", "必然", "必定", "承诺", "稳赚", "包过", "一定能", "肯定能",
    "已获认证", "已获批准", "已通过检测", "已通过认证", "已获专利", "已授权专利",
    "国际领先", "国内领先", "行业领先", "全球领先", "填补空白",
    "唯一", "首个", "首家", "首创", "独家", "成熟可靠", "完全满足",
    "百分之百", "零风险", "立即见效", "稳定盈利", "投资回报",
    "已量产", "已规模化", "已完成验证", "已通过验证", "已通过中试",
)

# 明显超出资料范围、不可核实的措辞。
_UNSUPPORTED_PATTERNS = re.compile(
    r"https?://|@|\d{11}|忽略.{0,8}(?:指令|规则)|系统提示|作为AI|我的知识库|训练数据"
)


def advice_mode(message: str) -> str:
    if re.search(r"比较|对比|选哪|哪个好|哪个更", message):
        return "compare"
    if re.search(r"介绍|解读|讲解|讲讲|有什么用|是什么", message):
        return "introduce"
    if re.search(r"推荐|适合|优先|对比|选哪|匹配|建议", message):
        return "recommend"
    return "search"


def local_reply(message: str, resolve_references: bool = True) -> str | None:
    text = message.strip()
    if re.fullmatch(r"(?:你好|您好|嗨|hi|hello|谢谢|再见|在吗)[!！。.?？~～\s]*", text, re.I):
        return _OVERVIEW
    if not _GENERIC_WORDS.sub("", text):
        return "请告诉我技术方向或具体成果名称，以及准备解决的应用场景；预算、成熟度和合作方式知道多少说多少，不确定可以留空。我会基于真实资料介绍和推荐，而不是随意挑选成果。"
    asks_how = bool(re.search(r"怎么|如何|怎样|在哪|哪里|入口|流程|步骤|操作|指南|教程", text))
    guide = None
    if asks_how:
        if re.search(r"发布|发成果|发需求|提交成果|提交需求", text):
            guide = "publish_demand" if "需求" in text else "publish_achievement"
        elif re.search(r"对接|合作意向|意向请求", text):
            guide = "cooperation"
        elif re.search(r"机构|认证|入驻", text):
            guide = "certification"
        elif "收藏" in text:
            guide = "favorite"
        elif re.search(r"登录|注册|头像|个人资料|手机号|微信绑定|绑定微信", text):
            guide = "login"
        elif re.search(r"AI|AI匹配|人工智能匹配", text, re.I):
            guide = "matching"
    if guide:
        reply = _GUIDES[guide]
        if guide.startswith("publish_") and "对接" in text:
            reply += "\n\n" + _GUIDES["cooperation"]
        return reply
    if resolve_references and (not _REFERENCE_WORDS.sub("", text) or _REFERENCE_POINTER.search(text)):
        return "请提供你指的成果名称、技术方向或具体内容，避免把“这个/第一个”误指到其他卡片。我会根据对应资料介绍用途、匹配依据和待确认事项。"
    if re.search(r"你能做什么|你有什么功能|你是谁|平台.*(?:有哪些功能|能做什么|怎么用)|小程序.*(?:有哪些功能|怎么用)", text):
        return _OVERVIEW
    if re.fullmatch(r"(?:请|帮我|一下|介绍|了解|讲讲|解读|\s)*(?:南山科转通(?:平台)?|这个平台|本平台|平台|这个小程序)(?:的功能|功能|是什么|介绍|一下|[。！？?\s])*", text):
        return _OVERVIEW
    return None


def _source_text(value, depth=0) -> str:
    if isinstance(value, str):
        return value[:2000]
    if depth > 3 or value is None:
        return ""
    if isinstance(value, list):
        return "；".join(_source_text(item, depth + 1) for item in value[:8])
    if isinstance(value, dict):
        return "；".join(_source_text(item, depth + 1) for item in list(value.values())[:8])
    return str(value)[:100]


def _normalize_analysis(value) -> str | None:
    """把模型返回的 analysis 归一化成一段文本。

    模型可能返回字符串、单元素列表或多元素列表（不同模型 / 不同版本
    提示词的输出形态不一致）。旧实现只在 ``isinstance(value, str)`` 时
    才放行，列表形态会被**静默丢弃**——用户看不到解读，系统也不报错。
    这里统一归一化，再交给同一套幻觉校验。
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        parts = [
            str(entry).strip()
            for entry in value[:3]
            if isinstance(entry, (str, int, float)) and str(entry).strip()
        ]
        if parts:
            return "；".join(parts)
    return None


def grounded_explanation(ranking: dict, item: dict) -> tuple[list[str], str]:
    """校验模型给出的原文引用与解读，只放行可追溯的部分。

    校验项：
    1. quote 必须是该字段的逐字原文；
    2. analysis 里的数字必须全部能在原始资料中找到；
    3. analysis 里的结论性措辞（保证/领先/已认证…）必须也在原始资料里出现，
       否则视为模型虚构，直接丢弃解读（引用仍保留）。
    """
    evidence = []
    raw = ranking.get("evidence")
    for entry in raw[:3] if isinstance(raw, list) else []:
        if not isinstance(entry, dict) or not isinstance(entry.get("field"), str) or entry["field"] not in _EVIDENCE_FIELDS:
            continue
        quote = entry.get("quote")
        if not isinstance(quote, str) or not 2 <= len(quote.strip()) <= 120:
            continue
        quote = quote.strip()
        if quote in _source_text(item.get(entry["field"])) and quote not in evidence:
            evidence.append(quote)
    analysis = _normalize_analysis(ranking.get("analysis"))
    if not evidence or analysis is None or len(analysis) > 180:
        return evidence, ""
    if _UNSUPPORTED_PATTERNS.search(analysis):
        return evidence, ""
    source = " ".join(_source_text(item.get(field)) for field in _EVIDENCE_FIELDS)
    source_numbers = set(re.findall(r"\d+(?:\.\d+)?%?", source))
    if any(number not in source_numbers for number in re.findall(r"\d+(?:\.\d+)?%?", analysis)):
        return evidence, ""
    for claim in _UNSUPPORTED_CLAIMS:
        if claim in analysis and claim not in source:
            return evidence, ""
    return evidence, analysis


def enrich_cards(cards: list[dict], records: list[dict], route) -> list[dict]:
    enriched = []
    for card, item in zip(cards, records):
        card = dict(card)
        achievement = card.get("card_type") == "achievement"
        description = _source_text(item.get("tech_intro" if achievement else "description")).strip()
        facts = [f"发布方简介：{description[:220]}{'…' if len(description) > 220 else ''}"] if description else []
        if achievement:
            fields = normalize_list(item.get("application_fields"))[:3]
            innovation = normalize_list(item.get("innovation_points"))[:2]
            if fields:
                facts.append("应用方向：" + "、".join(value[:60] for value in fields))
            if innovation:
                facts.append("发布方列出的创新点：" + "；".join(value[:80] for value in innovation))
        reasons = []
        searchable = " ".join(_source_text(item.get(field)) for field in _EVIDENCE_FIELDS)
        for keyword in route.keywords[:8]:
            keyword = keyword.strip()
            matched = re.search(r"(?<![A-Za-z0-9])" + re.escape(keyword) + r"(?![A-Za-z0-9])", searchable, re.I) if keyword.isascii() else keyword in searchable
            if keyword and matched:
                reasons.append(f"技术方向依据：发布资料提及“{keyword[:40]}”")
        evidence = item.get("_advisor_evidence", [])
        reasons.extend(f"原文依据：“{quote}”" for quote in evidence[:2] if isinstance(quote, str))
        cautions = []
        if not description:
            cautions.append("发布方未披露详细介绍，需进一步确认技术内容")
        if achievement and not item.get("maturity_level"):
            cautions.append("成熟度未披露，需向发布方核实验证阶段")
        price = card.get("price" if achievement else "budget") or {}
        if price.get("text") in (None, "未填写", "面议"):
            cautions.append("具体报价或预算待沟通，不能据此判断成本是否符合预期")
        if not reasons:
            cautions.append("仅作为检索候选，尚需确认与实际应用场景的适配性")
        card.update({
            "advisorSummary": "\n".join(facts) or "发布方尚未填写足够的介绍资料。",
            "advisorInsight": item.get("_advisor_insight", ""),
            "matchReason": reasons[:4],
            "advisorCautions": cautions[:3],
        })
        enriched.append(card)
    return enriched


def _condition_summary(route) -> list[str]:
    conditions = []
    for label, value in [
        ("机构", route.organization), ("地域", route.region),
        ("最低报价（万元）", route.min_price_wan), ("最高报价（万元）", route.max_price_wan),
        ("最低预算（万元）", route.min_budget_wan), ("最高预算（万元）", route.max_budget_wan),
        ("最低成熟度", route.min_maturity),
    ]:
        if value is not None:
            conditions.append(f"{label}：{value}")
    if route.coop_modes:
        conditions.append("合作方式：" + "、".join(route.coop_modes))
    return conditions


def _empty_result_message(route, facts: dict | None) -> str:
    """零结果时给出可核实的说明，而不是笼统的「不符合条件」。"""
    from app.services.taxonomy import maturity_label

    name = "科技成果" if route.intent == "search_achievement" else "技术需求"
    keywords = "、".join(route.keywords) or "该方向"
    conditions = _condition_summary(route)
    detail = f"（{'；'.join(conditions)}）" if conditions else ""
    reasons: list[str] = []

    if facts:
        total = facts.get("total") or 0
        unpriced = facts.get("unpriced") or 0
        priced = facts.get("priced") or 0
        if route.intent == "search_achievement" and (route.min_price_wan is not None or route.max_price_wan is not None):
            if total and unpriced and priced <= 1:
                reasons.append(
                    f"平台当前已发布的 {total} 项{name}里，{unpriced} 项报价为「面议」（未填写具体金额），"
                    "无法与金额条件直接比较，这些记录不会被金额条件排除，但也不能据此断定符合预算"
                )
            elif total and priced == 0:
                reasons.append(f"平台当前已发布的 {total} 项{name}全部未填写具体报价")
        if route.intent == "search_demand" and (route.min_budget_wan is not None or route.max_budget_wan is not None):
            if total and unpriced and priced <= 1:
                reasons.append(
                    f"平台当前已发布的 {total} 项{name}里，{unpriced} 项预算为「面议」，无法与预算条件直接比较"
                )
        max_maturity = facts.get("max_maturity")
        if route.intent == "search_achievement" and route.min_maturity and max_maturity:
            if not taxonomy.maturity_at_least(max_maturity, route.min_maturity):
                reasons.append(
                    f"已发布{name}中成熟度最高的是「{maturity_label(max_maturity)}」，"
                    f"尚无达到「{maturity_label(route.min_maturity)}」的记录"
                )

    body = f"暂未找到同时满足「{keywords}」{detail}的{name}"
    if reasons:
        body += "。原因：" + "；".join(reasons)
    else:
        body += "，不会用无关结果代替推荐"
    body += "。可以调整技术关键词或放宽条件后重试；若某项条件对您不是必须，建议直接去掉该条件再查一次。"
    return body


def result_message(message: str, cards: list[dict], route, facts: dict | None = None) -> str:
    name = "科技成果" if route.intent == "search_achievement" else "技术需求"
    if not cards:
        return _empty_result_message(route, facts)
    mode = advice_mode(message)
    if mode == "compare" and len(cards) == 2:
        comparison = []
        for card in cards:
            amount = card.get("price" if card.get("card_type") == "achievement" else "budget") or {}
            amount_text = amount.get("text")
            if amount_text in (None, "未填写", "面议"):
                amount_text = "未披露，待确认"
            maturity = card.get("maturity") or {}
            maturity_text = maturity.get("label") if isinstance(maturity, dict) else str(maturity)
            if maturity_text == "未填写":
                maturity_text = "未披露，待确认"
            comparison.append(f"《{str(card.get('title') or '未命名')[:60]}》：报价或预算 {amount_text}；成熟度 {maturity_text or '未披露，待确认'}")
        reply = "按最新发布资料并列比较两项：\n" + "\n".join(comparison) + "\n用途和应用方向见各卡片资料摘要；未披露的性能、实施成本及适配性均待确认。"
    elif mode == "introduce":
        reply = f"以下基于发布资料介绍 {len(cards)} 项{name}，用途、依据和待确认事项见对应卡片。"
    elif mode == "recommend":
        titles = "、".join(f"《{str(card.get('title') or '未命名')[:60]}》" for card in cards[:3])
        reply = f"按当前检索条件整理了 {len(cards)} 项{name}，可先比较{titles}。推荐依据见下方原文与资料摘要，AI适配解读仅供初筛参考。"
    else:
        reply = f"找到 {len(cards)} 条相关{name}，已整理发布资料摘要、匹配依据和待确认事项。"
    if mode != "search":
        missing = []
        if not re.search(r"场景|用于|产线|生产线|质检|检测|应用于", message):
            missing.append("应用场景")
        if route.min_price_wan is None and route.max_price_wan is None and route.min_budget_wan is None and route.max_budget_wan is None:
            missing.append("预算范围（不确定可留空）")
        if missing:
            reply += "\n如需进一步筛选，请补充" + "、".join(missing) + "。"
    return reply + "\n以上依据发布方资料，不代表独立技术验证、适配保证或成交承诺；合作前请核实实施条件与验证数据。"
