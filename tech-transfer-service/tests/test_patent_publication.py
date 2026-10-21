"""Tests for modules/patent/publication.py — 公开号形态识别与前缀兜底。

这些用例全部用 mock，不触碰真实上游（上游是第三方 Google Patents 派生服务，
不稳定且有限流；上游行为矩阵记录在 modules/patent/publication.py 的文档字符串里）。
"""
import time

from modules.patent.publication import (
    expansion_candidates,
    filter_by_prefix,
    is_publication_query,
    matches_prefix,
    needs_prefix_expansion,
    parse_publication_query,
    search_publication_prefix,
)


class TestParsePublicationQuery:
    def test_plain_cn_number(self):
        assert parse_publication_query("CN110086609B") == ("CN", "110086609", "b")

    def test_lowercase_country_and_kind(self):
        assert parse_publication_query("cn1100866a") == ("CN", "1100866", "a")

    def test_without_kind_code(self):
        assert parse_publication_query("CN110086609") == ("CN", "110086609", "")

    def test_separators_removed(self):
        assert parse_publication_query("CN 1100866") == ("CN", "1100866", "")
        assert parse_publication_query("CN-1100866") == ("CN", "1100866", "")
        assert parse_publication_query("CN_1100866") == ("CN", "1100866", "")

    def test_surrounding_whitespace(self):
        assert parse_publication_query("  CN1100866  ") == ("CN", "1100866", "")

    def test_not_publication(self):
        assert parse_publication_query("华为") is None
        assert parse_publication_query("") is None
        assert parse_publication_query(None) is None

    def test_too_few_digits(self):
        # 数字段至少 3 位，"CN12" 不是公开号形态
        assert parse_publication_query("CN12") is None

    def test_is_publication_query(self):
        assert is_publication_query("CN1100866") is True
        assert is_publication_query("数据安全") is False


class TestNeedsPrefixExpansion:
    """上游只在数字段恰好 7 位或 9 位时才做公开号前缀匹配。"""

    def test_six_digit_needs_expansion(self):
        assert needs_prefix_expansion("CN", "110086") is True

    def test_eight_digit_needs_expansion(self):
        assert needs_prefix_expansion("CN", "11008660") is True

    def test_seven_and_nine_digit_do_not(self):
        assert needs_prefix_expansion("CN", "1100866") is False
        assert needs_prefix_expansion("CN", "110086609") is False

    def test_other_country_never_expands(self):
        # US/EP/WO 号段长度不固定，但上游对它们前缀匹配正常
        assert needs_prefix_expansion("US", "1086770") is False
        assert needs_prefix_expansion("WO", "2021052204") is False


class TestExpansionCandidates:
    def test_six_digit_pads_to_seven(self):
        cands = expansion_candidates("CN", "110086")
        assert len(cands) == 10
        # 必须带国家码：上游只认 CN1100860 这种完整公开号形态
        assert cands[0] == "CN1100860"
        assert cands[-1] == "CN1100869"

    def test_eight_digit_pads_to_nine(self):
        cands = expansion_candidates("CN", "11008660")
        assert len(cands) == 10
        assert all(c.startswith("CN") for c in cands)
        # 数字段补齐到 9 位（不含国家码）
        assert all(len(c[2:]) == 9 for c in cands)

    def test_kind_code_is_preserved(self):
        cands = expansion_candidates("CN", "110086", "b")
        assert all(c.endswith("B") for c in cands)

    def test_seven_digit_not_expanded(self):
        # 7 位已是上游可识别长度，不需要枚举
        assert expansion_candidates("CN", "1100866") == []

    def test_nine_digit_not_expanded(self):
        assert expansion_candidates("CN", "110086609") == []

    def test_four_digit_too_many_candidates(self):
        # 4 位补到 7 位需要 1000 种，代价过高，直接放弃
        assert expansion_candidates("CN", "1100") == []

    def test_non_cn_no_candidates(self):
        assert expansion_candidates("US", "108677") == []


class TestMatchesPrefix:
    def test_exact_prefix_hit(self):
        assert matches_prefix("CN110086609B", "CN", "110086609", "b") is True

    def test_prefix_hit_without_kind(self):
        assert matches_prefix("CN1100866C", "CN", "1100866", "") is True

    def test_different_number_rejected(self):
        # 上游全文检索误命中：CN1170923C 与 CN110086 无关
        assert matches_prefix("CN1170923C", "CN", "110086", "") is False

    def test_kind_code_mismatch_rejected(self):
        assert matches_prefix("CN1100866C", "CN", "1100866", "a") is False

    def test_kind_code_match(self):
        assert matches_prefix("CN1100866A", "CN", "1100866", "a") is True

    def test_empty_publication_no(self):
        assert matches_prefix("", "CN", "1100866", "") is False
        assert matches_prefix(None, "CN", "1100866", "") is False

    def test_case_insensitive(self):
        assert matches_prefix("cn110086609b", "CN", "110086609", "b") is True


class TestFilterByPrefix:
    def test_filters_out_unrelated_hits(self):
        rows = [
            {"pub_number": "CN1170923C", "title": "Medicated wine"},
            {"pub_number": "CN110086609B", "title": "数据安全备份"},
        ]
        out = filter_by_prefix(rows, "CN", "110086", "")
        assert [r["pub_number"] for r in out] == ["CN110086609B"]

    def test_deduplicates(self):
        rows = [
            {"pub_number": "CN110086609B"},
            {"pub_number": "cn110086609b"},
        ]
        out = filter_by_prefix(rows, "CN", "110086609", "b")
        assert len(out) == 1

    def test_ignores_non_dict_rows(self):
        rows = ["oops", None, {"pub_number": "CN110086609B"}]
        out = filter_by_prefix(rows, "CN", "110086609", "b")
        assert len(out) == 1

    def test_empty_rows(self):
        assert filter_by_prefix([], "CN", "110086", "") == []
        assert filter_by_prefix(None, "CN", "110086", "") == []

    def test_supports_number_key_alias(self):
        rows = [{"number": "CN110086609B"}]
        out = filter_by_prefix(rows, "CN", "110086609", "b")
        assert len(out) == 1


class TestSearchPublicationPrefix:
    def test_non_publication_returns_empty(self):
        hits, expanded = search_publication_prefix("华为", lambda q, n: [{"pub_number": "CN1A"}])
        assert hits == []
        assert expanded is False

    def test_direct_path_filters_results(self):
        def fake(q, n):
            assert q == "CN110086609B"
            return [{"pub_number": "CN1170923C"}, {"pub_number": "CN110086609B"}]

        hits, expanded = search_publication_prefix("CN110086609B", fake)
        assert [r["pub_number"] for r in hits] == ["CN110086609B"]
        assert expanded is False

    def test_enumeration_path_merges_and_filters(self):
        def fake(q, n):
            # 只有 CN1100866 开头的候选有真实结果
            if q.startswith("CN1100866"):
                return [{"pub_number": "CN1100866C"}]
            return []

        hits, expanded = search_publication_prefix("CN110086", fake)
        assert expanded is True
        assert [r["pub_number"] for r in hits] == ["CN1100866C"]

    def test_enumeration_path_applies_strict_filter(self):
        """枚举路径也必须做严格过滤，不能把全文命中当成匹配。"""
        def fake(q, n):
            return [{"pub_number": "CN1170923C"}]

        hits, _ = search_publication_prefix("CN110086", fake)
        assert hits == []

    def test_enumeration_path_is_bounded(self):
        """补位枚举最多 10 个候选，避免打爆上游。"""
        seen = []

        def fake(q, n):
            seen.append(q)
            return []

        search_publication_prefix("CN110086", fake)
        assert len(seen) == 10

    def test_enumeration_path_sends_full_publication_no(self):
        """候选必须带国家码，否则上游会当普通词做全文检索返回 0 条。"""
        seen = []

        def fake(q, n):
            seen.append(q)
            return []

        search_publication_prefix("CN110086", fake)
        assert all(q.startswith("CN") and q[2:].isdigit() for q in seen)
        assert sorted(seen) == [f"CN110086{i}" for i in range(10)]

    def test_enumeration_path_is_stable_ordered(self):
        """并发合并后必须排序，保证结果稳定可复现。"""
        def fake(q, n):
            if q.endswith("9"):
                return [{"pub_number": "CN1100869A"}]
            if q.endswith("0"):
                return [{"pub_number": "CN1100860A"}]
            return []

        hits, _ = search_publication_prefix("CN110086", fake)
        assert [r["pub_number"] for r in hits] == ["CN1100860A", "CN1100869A"]

    def test_num_is_forwarded_to_search_fn(self):
        """每路请求的条数由调用方决定（上游上限 100）。"""
        seen = []

        def fake(q, n):
            seen.append(n)
            return []

        search_publication_prefix("CN110086", fake, num=100)
        assert set(seen) == {100}

    def test_direct_path_forwards_num(self):
        seen = []

        def fake(q, n):
            seen.append((q, n))
            return []

        search_publication_prefix("CN110086609B", fake, num=50)
        assert seen == [("CN110086609B", 50)]

    def test_single_candidate_failure_does_not_break_others(self):
        """单个候选超时/报错只丢弃该候选，其余候选的结果照常返回。"""
        def fake(q, n):
            if q == "CN1100863":
                raise RuntimeError("upstream timeout")
            if q == "CN1100866":
                return [{"pub_number": "CN1100866C"}]
            return []

        hits, expanded = search_publication_prefix("CN110086", fake)
        assert expanded is True
        assert [r["pub_number"] for r in hits] == ["CN1100866C"]

    def test_timeout_budget_stops_slow_enumeration(self):
        """超出时间预算后放弃剩余候选，用已拿到的结果返回，不无限等待。"""
        def fake(q, n):
            time.sleep(0.3)
            return [{"pub_number": f"{q}C"}]

        t0 = time.monotonic()
        hits, expanded = search_publication_prefix("CN110086", fake, timeout=0.1)
        elapsed = time.monotonic() - t0
        assert expanded is True
        # 超预算后不应等满 10 路（10 × 0.3s = 3s）
        assert elapsed < 2.5

    def test_timeout_budget_returns_even_when_upstream_is_stuck(self):
        """上游完全卡住时也必须按预算返回，不能被拖死。"""
        def stuck(q, n):
            time.sleep(30)
            return []

        t0 = time.monotonic()
        hits, expanded = search_publication_prefix("CN110086", stuck, timeout=0.5)
        elapsed = time.monotonic() - t0
        assert expanded is True
        assert hits == []
        assert elapsed < 3.0

    def test_timeout_budget_keeps_completed_results(self):
        """超时前已完成的候选结果必须保留。"""
        def fake(q, n):
            if q == "CN1100860":
                return [{"pub_number": "CN1100860C"}]
            time.sleep(0.5)
            return []

        hits, _ = search_publication_prefix("CN110086", fake, timeout=1.0)
        assert [r["pub_number"] for r in hits] == ["CN1100860C"]
