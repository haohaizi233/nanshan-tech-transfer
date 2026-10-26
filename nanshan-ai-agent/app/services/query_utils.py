MAX_SEARCH_TERMS = 8
MAX_SEARCH_TERM_LENGTH = 80


# 常见中文词组（用于智能分词）
_COMMON_WORDS = {
    "机器学习", "深度学习", "遥感", "监测", "生态", "环境", "环境监测", "生态环境",
    "人工智能", "数据", "分析", "识别", "检测", "治疗", "药物", "材料", "电池",
    "智能", "系统", "技术", "研究", "应用", "开发", "新型", "高性能", "仿生",
}


def _split_chinese_term(term: str) -> list[str]:
    """把长中文关键词拆成有意义的子词，提高ILIKE命中率。

    策略：贪婪匹配已知词组，剩余部分用2-gram补充。
    "机器学习遥感监测" -> ["机器学习遥感监测", "机器学习", "遥感监测", "遥感"]
    """
    result = [term]  # 原词始终保留
    remaining = term
    # 优先匹配已知词组（最长优先）
    for word in sorted(_COMMON_WORDS, key=len, reverse=True):
        if word in remaining and word != term:
            result.append(word)
            remaining = remaining.replace(word, " ", 1)
    # 剩余部分：>2字的用2-gram
    import re
    for part in re.findall(r'[\u4e00-\u9fff]+', remaining):
        if len(part) > 2:
            for i in range(len(part) - 1):
                bigram = part[i:i+2]
                if bigram not in result:
                    result.append(bigram)
    return result


def normalize_search_terms(terms: list[str]) -> list[str]:
    normalized = []
    for term in terms[:MAX_SEARCH_TERMS * 2]:
        if not isinstance(term, str):
            continue
        value = term.strip()[:MAX_SEARCH_TERM_LENGTH]
        if not value:
            continue
        # 长中文词拆分成子词，提高召回
        sub_terms = _split_chinese_term(value)
        for sub in sub_terms:
            if sub not in normalized:
                normalized.append(sub)
                if len(normalized) >= MAX_SEARCH_TERMS:
                    break
        if len(normalized) >= MAX_SEARCH_TERMS:
            break
    return normalized


def escape_like_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")