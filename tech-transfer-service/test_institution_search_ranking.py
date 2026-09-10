"""Regression checks for relevance ordering in the public institution search."""

from modules.institution.service import institution_search_order


def _bucket(name, keyword):
    """Mirror the SQL CASE so ranking intent can be asserted without a database."""
    n = (name or "").strip()
    kw = (keyword or "").strip()
    if n.lower() == kw.lower():
        return 0
    lowered = n.lower()
    key = kw.lower()
    if lowered.startswith(key) or lowered.endswith(key):
        return 1
    if key in lowered:
        return 2
    return 3


def rank_names(keyword, names):
    return sorted(names, key=lambda name: (_bucket(name, keyword), len(name)))


def main():
    order_sql, params = institution_search_order("创新")

    assert "CASE" in order_sql
    assert "CHAR_LENGTH" in order_sql
    assert "name ILIKE %s OR name ILIKE %s" in order_sql
    assert params == (
        "创新",     # exact institution name
        "创新%",    # name prefix
        "%创新",    # name suffix
        "%创新%",   # name contains the phrase
        "%创新%",   # intro
        "%创新%",   # support unit
        "%创新%",   # label
    )
    assert order_sql.index("name ILIKE %s OR name ILIKE %s") < order_sql.index("intro ILIKE %s")

    ranked = rank_names("创新", [
        "创新药物原料及制剂中试基地",
        "南山科技创新服务平台",
        "恒程创新",
        "深圳先进技术研究院",
    ])
    assert ranked[0] == "恒程创新", ranked
    assert ranked[1] == "创新药物原料及制剂中试基地", ranked
    assert ranked[2] == "南山科技创新服务平台", ranked
    print("PASS: institution search ranks short name hits above long prefix titles")


if __name__ == "__main__":
    main()
