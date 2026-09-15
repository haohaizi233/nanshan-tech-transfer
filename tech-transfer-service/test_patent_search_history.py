"""专利检索历史：关键词规范化和持久化契约。"""

from core.errors import BizError
from db import get_cursor
from modules.patent.history import list_history, normalize_history_input, record_history


def main():
    assert normalize_history_input(" keyword ", "  人工智能  ") == ("keyword", "人工智能")
    assert normalize_history_input("assignee", "华为技术有限公司") == ("assignee", "华为技术有限公司")

    for mode, keyword in (("invalid", "芯片"), ("keyword", ""), ("keyword", "x" * 129)):
        try:
            normalize_history_input(mode, keyword)
            raise AssertionError(f"expected validation failure for {mode!r}/{keyword!r}")
        except BizError:
            pass

    with get_cursor() as cur:
        cur.execute("SELECT id FROM app_user ORDER BY id LIMIT 1")
        user = cur.fetchone()
    assert user, "test database needs one app_user row"
    user_id = user["id"]
    prefix = "__codex_patent_history_"
    with get_cursor(commit=True) as cur:
        cur.execute("DELETE FROM patent_search_history WHERE user_id=%s AND keyword LIKE %s", (user_id, prefix + "%"))
    try:
        for number in range(11):
            record_history(user_id, "keyword", f"{prefix}{number}")
        record_history(user_id, "assignee", f"{prefix}assignee")
        keyword_rows = [item for item in list_history(user_id, "keyword")["list"] if item["keyword"].startswith(prefix)]
        assignee_rows = [item for item in list_history(user_id, "assignee")["list"] if item["keyword"].startswith(prefix)]
        assert len(keyword_rows) == 10
        assert keyword_rows[0]["keyword"] == f"{prefix}10"
        assert len(assignee_rows) == 1
        assert assignee_rows[0]["keyword"] == f"{prefix}assignee"
        assert assignee_rows[0]["mode"] == "assignee"
    finally:
        with get_cursor(commit=True) as cur:
            cur.execute("DELETE FROM patent_search_history WHERE user_id=%s AND keyword LIKE %s", (user_id, prefix + "%"))

    print("PASS: patent search history validation")


if __name__ == "__main__":
    main()
