"""专利 Provider 出站清洗与检索映射（不打真实上游）。"""

from core.errors import BizError
from modules.patent.normalize import (
    assert_no_source_leak,
    clean_text,
    infer_patent_type,
    map_patent_info,
    map_search_hit,
)
from modules.patent.service import get_patent, search_patents


GOOGLE_HIT = {
    "pub_number": "CN108604342B",
    "title": "基于nfc进行数据传输的方法及移动设备",
    "snippet": "所述移动设备基于<b>北京银行</b>相关情景信息… https://patentimages.storage.googleapis.com/x/y.pdf",
    "assignee": "<b>华为技术有限公司</b>",
    "inventor": "张艺宝",
    "priority_date": "2017-01-20",
    "filing_date": "2017-03-03",
    "publication_date": "2022-04-12",
    "grant_date": "2022-04-12",
    "pdf_url": "https://patentimages.storage.googleapis.com/60/7f/0e/b73b700305515c/CN108604342B.pdf",
    "thumbnail": "ae/c8/44/c4bba695b0057d/HPA0000259217240000281.png",
    "language": "zh",
}

INFO_RAW = {
    "patent_id": "patent/CN217384194U/en",
    "number": "CN217384194U",
    "title": "Three-coordinate measuring instrument with accurate positioning",
    "abstract": "A utility model.",
    "description": "Description text.\nSecond line.",
    "claims": "1. A device.",
}


def fake_fetch(path, params, timeout):
    if path == "/patent_search":
        return {
            "q": params.get("q"),
            "assignee": params.get("assignee"),
            "num": params.get("num"),
            "page": params.get("page"),
            "total": 93,
            "results": [GOOGLE_HIT],
        }
    if path == "/patent_info":
        return INFO_RAW
    raise AssertionError(path)


def main():
    assert infer_patent_type("CN108604342B") == "invention"
    assert infer_patent_type("CN217384194U") == "utility_model"
    assert infer_patent_type("CN305516311S") == "design"
    assert clean_text("<b>北京银行</b>股份有限公司") == "北京银行股份有限公司"

    mapped = map_search_hit(GOOGLE_HIT)
    assert mapped["publicationNo"] == "CN108604342B"
    assert mapped["applicant"] == "华为技术有限公司"
    assert "googleapis" not in mapped["snippet"]
    assert "<b>" not in mapped["snippet"]
    assert mapped["hasPdf"] is True
    assert "pdf_url" not in mapped
    assert "thumbnail" not in mapped
    assert_no_source_leak(mapped)

    info = map_patent_info(INFO_RAW, "CN217384194U", None)
    assert info["publicationNo"] == "CN217384194U"
    assert info["patentType"] == "utility_model"
    assert "patent_id" not in info
    assert_no_source_leak(info)

    page = search_patents("北京银行", "", 1, 1, fetcher=fake_fetch)
    assert page["pageSize"] == 1
    assert len(page["list"]) == 1

    detail = get_patent("CN217384194U", fetcher=fake_fetch)
    assert detail["abstract"] == "A utility model."
    assert detail["claims"] == "1. A device."
    assert "patent/CN" not in str(detail)
    assert_no_source_leak(detail)

    try:
        search_patents("", "", 1, 10, fetcher=fake_fetch)
        raise AssertionError("expected empty query to fail")
    except BizError as exc:
        assert exc.code == "TT_COMMON_40001"

    print("PASS: patent provider normalize")


if __name__ == "__main__":
    main()
