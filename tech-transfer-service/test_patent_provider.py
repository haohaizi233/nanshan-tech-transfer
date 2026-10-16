"""专利 Provider 出站清洗与检索映射（不打真实上游）。"""

import io
import json
import urllib.error
from unittest.mock import patch

from config import settings
from core.errors import BizError
from modules.patent import provider
from modules.patent.normalize import (
    assert_no_source_leak,
    clean_multiline,
    clean_text,
    format_patent_content_blocks,
    infer_patent_type,
    map_patent_info,
    map_search_hit,
    repair_broken_subscripts,
    to_simplified,
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


def language_aware_fetch(path, params, timeout):
    if path == "/patent_info":
        assert params["query"] == "CN217384194U"
        assert params["language"] == "zh"
        return INFO_RAW
    raise AssertionError(path)


def main():
    assert infer_patent_type("CN108604342B") == "invention"
    assert infer_patent_type("CN217384194U") == "utility_model"
    assert infer_patent_type("CN305516311S") == "design"
    assert clean_text("<b>北京银行</b>股份有限公司") == "北京银行股份有限公司"
    assert to_simplified("CN108604342B") == "CN108604342B"
    assert to_simplified("Software interface testing method") == "Software interface testing method"
    assert to_simplified("基於NFC進行資料傳輸的方法及移動設備") == "基于NFC进行数据传输的方法及移动设备"
    assert to_simplified("發明專利 / 軟體測試") == "发明专利 / 软件测试"
    traditional_hit = dict(GOOGLE_HIT)
    traditional_hit["title"] = "基於nfc進行資料傳輸的方法及移動設備"
    traditional_hit["assignee"] = "<b>華為技術有限公司</b>"
    traditional_hit["snippet"] = "所述移動設備基於<b>北京銀行</b>相關情景資訊"
    traditional_mapped = map_search_hit(traditional_hit)
    assert traditional_mapped["title"] == "基于nfc进行数据传输的方法及移动设备"
    assert traditional_mapped["applicant"] == "华为技术有限公司"
    assert "相关情景信息" in traditional_mapped["snippet"]
    traditional_info = map_patent_info({
        **INFO_RAW,
        "title": "三座標測量儀",
        "abstract": "一種實用新型。",
        "claims": "1. 一種裝置。",
        "description": "說明書正文。\n第二行。",
    }, "CN217384194U", None)
    assert traditional_info["title"] == "三座标测量仪"
    assert traditional_info["abstract"] == "一种实用新型。"
    assert traditional_info["claims"] == "1. 一种设备。"
    assert traditional_info["descriptionBlocks"][0]["text"] == "说明书正文。"
    assert repair_broken_subscripts("高度范围在\n内，h\n1\n第一个是") == "高度范围在\n内，h₁\n第一个是"
    assert "w₁" in clean_multiline("差值大于前一个符号的宽w\n1\n。")
    assert repair_broken_subscripts("Figure\n1\nshows") == "Figure\n1\nshows"
    assert clean_multiline("段落一\n段落二") == "段落一\n段落二"

    blocks = format_patent_content_blocks(
        "具体执行过程可以表示为：TSN(T\n1\n,T\n2\n,��,T\nK\n)=H(G(F(T\n1\n；W)))。其中，T\n1\n表示第一个视频分片。"
    )
    assert blocks == [
        {"type": "paragraph", "text": "具体执行过程可以表示为：TSN(T₁,T₂,��,Tₖ)=H(G(F(T₁；W)))。其中，T₁表示第一个视频分片。"},
    ]

    # 正文可能混用 Markdown/LaTeX、HTML 角标及代码围栏；代码不得被公式修复器改写。
    rich_blocks = format_patent_content_blocks(
        "变量为 $q_{ads,i}=\\frac{m_i}{V_{std}}$。\n\n"
        "$$\\sum_{i=1}^{n} x_i^2$$\n\n"
        "```python\nq_ads_i = 1\n```\n\n"
        "气体密度ρ\ns\n，扩散系数为 k\n∞\n。<sup>2</sup>"
    )
    assert [block["type"] for block in rich_blocks] == ["paragraph", "formula", "code", "paragraph"]
    assert "<sub>ads,i</sub>" in rich_blocks[0]["html"]
    assert "<span" in rich_blocks[0]["html"]  # 分式/求和等 LaTeX 输出为小程序 rich-text 节点。
    assert rich_blocks[2]["text"] == "q_ads_i = 1"
    assert "ρₛ" in rich_blocks[3]["text"]
    assert "<sub>∞</sub>" in rich_blocks[3]["html"]
    assert "<sup>2</sup>" in rich_blocks[3]["html"]

    display_delimiters = format_patent_content_blocks(
        r"\[ a^2 + b^2 \]" + "\n\n" + r"\begin{equation} \sum_{i=1}^{n} x_i \end{equation}"
    )
    assert [block["type"] for block in display_delimiters] == ["formula", "formula"]
    assert "<sup>2</sup>" in display_delimiters[0]["html"]
    assert "∑<sub>i=1</sub><sup>n</sup>" in display_delimiters[1]["html"]

    flattened_formula = format_patent_content_blocks(
        "资源量约为1013×10\n12\nm\n3\n。\n\nσ′\nij\n＝λεδ\nij\n+2Gε\nij\n(2.2-2)"
    )
    assert flattened_formula[0]["text"] == "资源量约为1013×10¹²m³。"
    assert flattened_formula[1]["type"] == "formula"
    assert flattened_formula[1]["text"] == "σ′ij＝λεδᵢⱼ+2Gεij(2.2-2)"

    # 上游把同一行里的下标和运算符拆开时，不能把公式尾巴误拆为独立居中公式。
    inline_equation = format_patent_content_blocks(
        "网格块的中心满足：x\ni\n＝(x\ni+1/2\n+x\ni-1/2\n)/2，Δx\ni\n＝x\ni+1/2\n-x\ni-1/2\n；Δx\ni\n,Δy\nj\n分别为网格步长。"
    )
    assert [block["type"] for block in inline_equation] == ["paragraph"]
    assert inline_equation[0]["text"] == "网格块的中心满足：xᵢ＝(xᵢ+1/2+xᵢ-1/2)/2，Δxᵢ＝xᵢ+1/2-xᵢ-1/2；Δxᵢ,Δyⱼ分别为网格步长。"

    greek_index = format_patent_content_blocks("式中，C\nφ\n—孔隙压缩系数，无量纲。")
    assert greek_index[0]["text"] == "式中，Cφ—孔隙压缩系数，无量纲。"
    assert "C<sub>φ</sub>" in greek_index[0]["html"]

    wrapped_claim = format_patent_content_blocks(
        "1. 一株鼠李糖乳杆菌（\nLactobacillus rhamnosus\n），其特征在于，所述鼠李糖乳杆菌保藏于广东省微生物菌种保藏中心。"
    )
    assert wrapped_claim == [
        {
            "type": "paragraph",
            "text": "1. 一株鼠李糖乳杆菌（Lactobacillus rhamnosus），其特征在于，所述鼠李糖乳杆菌保藏于广东省微生物菌种保藏中心。",
        }
    ]

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

    # 详情请求必须把列表项的语言上下文继续传给上游，避免上游默认语言覆盖标题。
    language_detail = get_patent("CN217384194U", language="zh", fetcher=language_aware_fetch)
    assert language_detail["title"] == "Three-coordinate measuring instrument with accurate positioning"

    try:
        search_patents("", "", 1, 10, fetcher=fake_fetch)
        raise AssertionError("expected empty query to fail")
    except BizError as exc:
        assert exc.code == "TT_COMMON_40001"

    _assert_upstream_key_is_query_param()
    _assert_http_json_retries_then_succeeds()
    _assert_http_json_422_exposes_upstream_status()
    _assert_http_json_502_exposes_upstream_status()
    _assert_http_json_connection_reset_is_503()

    print("PASS: patent provider normalize")


class _FakeHttpResponse:
    def __init__(self, body: bytes, status=200):
        self.status = status
        self._body = body

    def read(self, n=-1):
        if n is None or n < 0:
            data, self._body = self._body, b""
            return data
        data, self._body = self._body[:n], self._body[n:]
        return data

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _http_error(code: int, body: bytes = b""):
    return urllib.error.HTTPError(
        "http://patent.test/patent_search",
        code,
        "error",
        hdrs=None,
        fp=io.BytesIO(body),
    )


def _assert_upstream_key_is_query_param():
    old_base = settings.PATENT_PROVIDER_BASE
    old_key = settings.PATENT_PROVIDER_KEY
    settings.PATENT_PROVIDER_BASE = "http://patent.test"
    settings.PATENT_PROVIDER_KEY = "secret-key"
    try:
        url = provider._build_url("/patent_search", {"q": "nihao1", "page": 0})
        assert url.startswith("http://patent.test/patent_search?")
        assert "q=nihao1" in url
        assert "key=secret-key" in url
        headers = provider._auth_headers()
        assert headers["Authorization"] == "Bearer secret-key"
    finally:
        settings.PATENT_PROVIDER_BASE = old_base
        settings.PATENT_PROVIDER_KEY = old_key


def _assert_http_json_retries_then_succeeds():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        if calls["n"] < 2:
            raise _http_error(503, b"upstream busy")
        return _FakeHttpResponse(json.dumps({"ok": True}).encode("utf-8"))

    with patch.object(provider.urllib.request, "urlopen", fake_urlopen), \
            patch.object(provider.time, "sleep"):
        data = provider._http_json("/patent_search", {"q": "x"}, 5)
    assert data == {"ok": True}
    assert calls["n"] == 2


def _assert_http_json_422_exposes_upstream_status():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise _http_error(
            422,
            b'{"detail":[{"loc":["query","key"],"msg":"Field required"}]}',
        )

    with patch.object(provider.urllib.request, "urlopen", fake_urlopen):
        try:
            provider._http_json("/patent_search", {"q": "x"}, 5)
            raise AssertionError("expected 422 to map to patent provider failed")
        except BizError as exc:
            assert exc.code == "TT_PATENT_50201"
            assert exc.http_status == 502
            assert (exc.details or {}).get("layer") == "provider"
            assert (exc.details or {}).get("providerStatus") == 422
    assert calls["n"] == 1


def _assert_http_json_502_exposes_upstream_status():
    calls = {"n": 0}

    def fake_urlopen(req, timeout=0):
        calls["n"] += 1
        raise _http_error(502, b"Bad Gateway")

    with patch.object(provider.urllib.request, "urlopen", fake_urlopen), \
            patch.object(provider.time, "sleep"):
        try:
            provider._http_json("/patent_search", {"q": "x"}, 5)
            raise AssertionError("expected 502 to map to patent provider failed")
        except BizError as exc:
            assert exc.code == "TT_PATENT_50201"
            assert exc.http_status == 502
            assert (exc.details or {}).get("layer") == "provider"
            assert (exc.details or {}).get("providerStatus") == 502
            assert "Bad Gateway" in ((exc.details or {}).get("upstreamBody") or "")
    assert calls["n"] == 3


def _assert_http_json_connection_reset_is_503():
    from http.client import RemoteDisconnected
    from urllib.error import URLError

    def fake_urlopen(req, timeout=0):
        raise URLError(RemoteDisconnected("Remote end closed connection without response"))

    with patch.object(provider.urllib.request, "urlopen", fake_urlopen), \
            patch.object(provider.time, "sleep"):
        try:
            provider._http_json("/patent_search", {"q": "x"}, 5)
            raise AssertionError("expected connection reset to map to unavailable")
        except BizError as exc:
            assert exc.code == "TT_PATENT_50301"
            assert exc.http_status == 503
            assert (exc.details or {}).get("layer") == "provider"
            assert (exc.details or {}).get("reason") == "connection_reset"
            assert (exc.details or {}).get("providerStatus") is None


if __name__ == "__main__":
    main()
