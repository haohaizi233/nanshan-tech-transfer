"""Regression checks for relevance ordering in the public institution search."""

from modules.institution.service import institution_search_order


def main():
    order_sql, params = institution_search_order("创新")

    assert "CASE" in order_sql
    assert "name ILIKE %s" in order_sql
    assert "name ILIKE %s" in order_sql
    assert "intro ILIKE %s" in order_sql
    assert params == (
        "创新",     # exact institution name
        "创新%",    # name prefix
        "%创新%",   # name contains the phrase
        "%创新%",   # intro
        "%创新%",   # support unit
        "%创新%",   # label
    )
    assert order_sql.index("name ILIKE %s") < order_sql.index("intro ILIKE %s")
    print("PASS: institution search ranks name matches above auxiliary text matches")


if __name__ == "__main__":
    main()
