MAX_SEARCH_TERMS = 8
MAX_SEARCH_TERM_LENGTH = 80


def normalize_search_terms(terms: list[str]) -> list[str]:
    normalized = []
    for term in terms[:MAX_SEARCH_TERMS * 2]:
        if not isinstance(term, str):
            continue
        value = term.strip()[:MAX_SEARCH_TERM_LENGTH]
        if value and value not in normalized:
            normalized.append(value)
        if len(normalized) >= MAX_SEARCH_TERMS:
            break
    return normalized


def escape_like_term(value: str) -> str:
    return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")