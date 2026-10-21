"""Tests for modules/patent/service.py 的公开号分支、分页收敛与高亮字段。

覆盖两个线上真实故障场景：
- 截图 2：搜索 CN110086（6 位）→ 上游全文检索误返回葡萄酒专利 CN1170923C；
- 截图 1：搜索"华为"→ 上游 total 是 125 分桶估算值（124922），翻页翻到空页。

全部用 mock fetcher，不触碰真实上游。
"""

import pytest

from modules.patent.service import search_patents


def _row(pub, title="", assignee="", snippet=""):
    return {
        "pub_number": pub,
        "title": title,
        "assignee": assignee,
        "snippet": snippet,
    }


class TestSearchPatentsPublicationBranch:
    def test_six_digit_query_drops_unrelated_hit(self):
        """截图 2：上游对 CN110086 退化成全文检索，返回葡萄酒专利 CN1170923C。"""
        raw = {
            "total": 1,
            "total_pages": 1,
            "results": [
                _row("CN1170923C", "Medicated wine for treating intestinal diseases"),
            ],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("CN110086", "", 1, 10, fetcher=fetcher)
        # 上游全文检索的误报被过滤掉；补位枚举也没有命中 → 0 条
        assert meta["total"] == 0
        assert meta["list"] == []

    def test_six_digit_query_keeps_prefix_match(self):
        """CN110086609B 以 CN110086 开头，必须保留。"""
        raw = {
            "total": 1,
            "total_pages": 1,
            "results": [
                _row("CN1170923C", "Medicated wine"),
                _row("CN110086609B", "数据安全备份和安全恢复的方法及电子设备", "华为技术有限公司"),
            ],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("CN110086", "", 1, 10, fetcher=fetcher)
        assert meta["total"] == 1
        assert len(meta["list"]) == 1
        assert meta["list"][0]["publicationNo"] == "CN110086609B"

    def test_publication_total_uses_real_hit_count(self):
        """公开号查询的 total 用真实命中数，不用上游估算值。"""
        raw = {
            "total": 124922,  # 上游估算值
            "total_pages": 100,
            "results": [_row("CN110086609B")],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("CN110086", "", 1, 10, fetcher=fetcher)
        assert meta["total"] == 1

    def test_kind_code_is_respected(self):
        """CN1100866A 与 CN1100866C 是两件不同专利。"""
        raw = {
            "total": 2,
            "total_pages": 1,
            "results": [_row("CN1100866A"), _row("CN1100866C")],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("CN1100866A", "", 1, 10, fetcher=fetcher)
        assert meta["total"] == 1
        assert meta["list"][0]["publicationNo"] == "CN1100866A"

    def test_assignee_present_skips_publication_branch(self):
        """带申请人时不走公开号分支（上游支持 assignee 过滤语义）。"""
        raw = {"total": 0, "total_pages": 0, "results": []}
        calls = []

        def fetcher(path, params, timeout):
            calls.append(dict(params))
            return raw

        search_patents("CN110086", "华为技术有限公司", 1, 10, fetcher=fetcher)
        assert len(calls) == 1

    def test_six_digit_triggers_bounded_enumeration(self):
        """6 位号段上游不认，本地补位枚举 10 个候选号段。"""
        queries = []

        def fetcher(path, params, timeout):
            queries.append(params["q"])
            if params["q"] == "CN1100866":
                return {"total": 2, "total_pages": 1, "results": [
                    _row("CN1100866C", "数据安全备份"),
                    _row("CN1100866A", "数据安全恢复"),
                ]}
            return {"total": 0, "total_pages": 0, "results": []}

        meta = search_patents("CN110086", "", 1, 10, fetcher=fetcher)
        assert len(queries) == 10
        assert sorted(queries) == [f"CN110086{i}" for i in range(10)]
        assert meta["total"] == 2
        assert {i["publicationNo"] for i in meta["list"]} == {"CN1100866A", "CN1100866C"}

    def test_enumeration_pagination_is_local(self):
        """枚举路径下分页在本地切，不依赖上游页码。"""
        def fetcher(path, params, timeout):
            if params["q"] == "CN1100860":
                return {"total": 0, "total_pages": 1, "results": [
                    _row(f"CN1100860{i}A") for i in range(10)
                ]}
            return {"total": 0, "total_pages": 0, "results": []}

        page1 = search_patents("CN110086", "", 1, 10, fetcher=fetcher)
        assert page1["total"] == 10
        assert len(page1["list"]) == 10
        assert page1["totalPages"] == 1

        page2 = search_patents("CN110086", "", 2, 10, fetcher=fetcher)
        assert page2["total"] == 10
        assert page2["list"] == []

    def test_seven_digit_does_not_enumerate(self):
        """7 位是上游可识别的号段，不做额外请求。"""
        queries = []

        def fetcher(path, params, timeout):
            queries.append(params["q"])
            return {"total": 1, "total_pages": 1, "results": [_row("CN1100866C")]}

        meta = search_patents("CN1100866", "", 1, 10, fetcher=fetcher)
        assert queries == ["CN1100866"]
        assert meta["total"] == 1

    def test_keyword_search_does_not_enumerate(self):
        """普通关键词查询完全不受补位枚举影响。"""
        queries = []

        def fetcher(path, params, timeout):
            queries.append(params["q"])
            return {"total": 1, "total_pages": 1, "results": [_row("CN110086609B")]}

        search_patents("华为", "", 1, 10, fetcher=fetcher)
        assert queries == ["华为"]


class TestSearchPatentsPagination:
    def test_total_pages_capped_by_upstream(self):
        """截图 1：估算 total 算出 12493 页，但上游 page>=100 返回空列表。"""
        raw = {
            "total": 124922,
            "total_pages": 100,
            "results": [_row(f"CN11008660{i}B", "标题", "华为技术有限公司") for i in range(10)],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("华为", "", 1, 10, fetcher=fetcher)
        assert meta["total"] == 124922
        assert meta["totalPages"] == 100

    def test_total_pages_keeps_smaller_local_value(self):
        """上游页数比本地算出的还大时，保留本地的值。"""
        raw = {
            "total": 15,
            "total_pages": 100,
            "results": [_row(f"CN11008660{i}B") for i in range(5)],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("华为", "", 1, 10, fetcher=fetcher)
        assert meta["totalPages"] == 2

    def test_upstream_without_total_pages(self):
        """上游没给 total_pages 时不做收敛。"""
        raw = {"total": 30, "results": [_row("CN110086609B")]}

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("华为", "", 1, 10, fetcher=fetcher)
        assert meta["totalPages"] == 3


class TestSearchPatentsHighlights:
    def test_highlights_extracted_from_bold_tags(self):
        """上游用 <b> 标记命中词，本地要保留下来给前端高亮。"""
        raw = {
            "total": 1,
            "total_pages": 1,
            "results": [
                {
                    "pub_number": "CN110086609B",
                    "title": "数据安全备份和安全恢复的方法及电子设备",
                    "assignee": "<b>华为技术有限公司</b>",
                    "snippet": "涉及<b>华为</b>的技术方案",
                },
            ],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("华为", "", 1, 10, fetcher=fetcher)
        item = meta["list"][0]
        assert item["highlights"] == ["华为", "华为技术有限公司"]
        # 标签本身必须剥掉
        assert "<b>" not in item["applicant"]
        assert item["applicant"] == "华为技术有限公司"

    def test_highlights_empty_when_no_markup(self):
        raw = {
            "total": 1,
            "total_pages": 1,
            "results": [_row("CN110086609B", "数据安全备份")],
        }

        def fetcher(path, params, timeout):
            return raw

        meta = search_patents("华为", "", 1, 10, fetcher=fetcher)
        assert meta["list"][0]["highlights"] == []


class TestSearchPatentsValidation:
    def test_requires_keyword_or_assignee(self):
        from core.errors import BizError

        with pytest.raises(BizError):
            search_patents("", "", 1, 10)

    def test_keyword_too_long(self):
        from core.errors import BizError

        with pytest.raises(BizError):
            search_patents("x" * 65, "", 1, 10)
