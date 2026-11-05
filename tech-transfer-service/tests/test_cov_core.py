"""Coverage-focused unit tests: patent normalize/service/provider, internal AI routes, core plumbing.

纯单元测试：DB 触点一律 patch db.get_cursor，HTTP 触点一律 patch urllib.request.urlopen
或注入 fetcher，绝不触真实网络与数据库。
"""

import io
import logging
import urllib.error
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError
from modules.patent import normalize, provider, service
from routes import internal_ai

FAT = {
    "id": 1,
    "user_id": 1,
    "org_id": 1,
    "name": "n",
    "status": "active",
    "version": 1,
    "c": 1,
    "m": 0,
    "user_no": "U001",
    "role_code": "user",
    "created_at": datetime(2026, 1, 1, 12, 0),
    "updated_at": datetime(2026, 1, 1, 12, 0),
}


def _cur():
    cur = MagicMock()
    cur.fetchone.return_value = dict(FAT)
    cur.fetchall.return_value = [dict(FAT)]
    cur.rowcount = 1
    return cur


def _bind_cursor(mock_gc, cur):
    mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)


def _req(headers=None, host="127.0.0.1", query=None):
    req = MagicMock()
    req.headers = dict(headers or {})
    req.client = None if host is None else MagicMock(host=host)
    req.query_params = dict(query or {})
    return req


def _uniq(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


@pytest.fixture(autouse=True)
def _clear_pdf_cache():
    service.clear_pdf_preview_cache()
    yield


# ══════════════════════════════════════════════════════════════
# modules/patent/normalize.py — 纯函数
# ══════════════════════════════════════════════════════════════


class TestNormalizeScriptRepair:
    def test_repair_subscripts_digit(self):
        assert normalize.repair_broken_subscripts("h\n1") == "h₁"

    def test_repair_subscripts_letter(self):
        assert normalize.repair_broken_subscripts("ρ\ns") == "ρₛ"

    def test_repair_subscripts_fallback_marker(self):
        assert normalize.repair_broken_subscripts("k\n∞") == "k\ue0000|∞\ue001"

    def test_repair_subscripts_comma_index_marker(self):
        assert normalize.repair_broken_subscripts("x\n1,2") == "x\ue0000|1,2\ue001"

    def test_repair_subscripts_noop(self):
        assert normalize.repair_broken_subscripts("plain") == "plain"

    def test_repair_superscripts_exponent(self):
        assert normalize.repair_broken_superscripts("10\n3\nm") == "10³\nm"

    def test_repair_superscripts_unit_power(self):
        assert normalize.repair_broken_superscripts("c\n2\n.") == "c²\n."


class TestNormalizeTexRendering:
    def test_preprocess_tex_env_spacing_align(self):
        assert normalize._preprocess_tex(r"\begin{equation}a & b\\ c\,d\end{equation}") == "a  b； c d"

    def test_tex_to_text_frac_sqrt_symbols(self):
        assert normalize._tex_to_text(r"\frac{a}{b}") == "(a)/(b)"
        assert normalize._tex_to_text(r"\sqrt[3]{x}") == "3√(x)"
        assert normalize._tex_to_text(r"\alpha+\beta") == "α+β"

    def test_tex_to_html_subsup(self):
        assert normalize._tex_to_html(r"x_{i}^{2}") == "x<sub>i</sub><sup>2</sup>"

    def test_tex_to_html_supsub(self):
        assert normalize._tex_to_html(r"x^{2}_{i}") == "x<sup>2</sup><sub>i</sub>"

    def test_tex_to_html_script_chain(self):
        assert normalize._tex_to_html(r"x_{i}^2+y") == "x<sub>i</sub><sup>2</sup>+y"

    def test_tex_to_html_limits(self):
        assert normalize._tex_to_html(r"\sum_{i=1}^{n}") == "∑<sub>i=1</sub><sup>n</sup>"

    def test_tex_to_html_sqrt_index(self):
        rendered = normalize._tex_to_html(r"\sqrt[3]{x}")
        assert rendered.startswith("<sup>3</sup>√")
        assert "text-decoration:overline" in rendered

    def test_tex_to_html_nested_frac_sqrt(self):
        rendered = normalize._tex_to_html(r"\frac{\alpha}{\sqrt{b}}")
        assert "border-bottom:1px solid #475569" in rendered
        assert "α" in rendered
        assert "text-decoration:overline" in rendered


class TestNormalizeMathml:
    def test_mathml_to_tex_basic(self):
        assert normalize._mathml_to_tex("<math><mi>x</mi><mo>+</mo><mn>1</mn></math>") == "x+1"

    def test_mathml_to_tex_mtext(self):
        assert normalize._mathml_to_tex("<math><mtext>txt</mtext></math>") == "txt"

    def test_mathml_to_tex_parse_error(self):
        assert normalize._mathml_to_tex("garbage<>") == ""

    def test_replace_mathml_formula(self):
        assert normalize._replace_mathml("<math><mi>x</mi></math>") == "\n$$x$$\n"

    def test_replace_mathml_malformed_fallback(self):
        assert normalize._replace_mathml("<math><mfrac></math>") == ""

    def test_format_blocks_mfrac(self):
        blocks = normalize.format_patent_content_blocks("<math><mfrac><mi>a</mi><mi>b</mi></mfrac></math>")
        assert blocks[0]["type"] == "formula"
        assert blocks[0]["text"] == "(a)/(b)"
        assert "border-bottom:1px solid #475569" in blocks[0]["html"]

    def test_format_blocks_msqrt_mroot(self):
        assert normalize.format_patent_content_blocks("<maths><msqrt><mi>x</mi></msqrt></maths>")[0]["text"] == "√(x)"
        assert normalize.format_patent_content_blocks("<math><mroot><mi>x</mi><mn>3</mn></mroot></math>")[0][
            "text"
        ] == ("3√(x)")

    def test_format_blocks_scripts(self):
        src = "<math><msub><mi>x</mi><mn>1</mn></msub><msup><mi>y</mi><mn>2</mn></msup>"
        src += "<msubsup><mi>z</mi><mn>1</mn><mn>2</mn></msubsup></math>"
        block = normalize.format_patent_content_blocks(src)[0]
        assert block["text"] == "x_1y^2z_1^2"
        assert block["html"] == "x<sub>1</sub>y<sup>2</sup>z<sub>1</sub><sup>2</sup>"

    def test_format_blocks_mrow_operators(self):
        block = normalize.format_patent_content_blocks(
            "<math><mrow><mi>a</mi><mo>+</mo><mo>⁢</mo><mo>−</mo><mn>1</mn></mrow></math>"
        )[0]
        assert block["text"] == "a+-1"

    def test_format_blocks_mspace_fallback(self):
        block = normalize.format_patent_content_blocks("<math><mspace/><mfenced><mi>q</mi></mfenced></math>")[0]
        assert block["text"] == "q"

    def test_flattened_sinr_english(self):
        block = normalize.format_patent_content_blocks("SINR = Signal level Interference + Noise level")[0]
        assert block["type"] == "formula"
        assert block["text"] == "SINR=(Signal level)/(Interference+Noise level)"

    def test_flattened_sinr_chinese(self):
        block = normalize.format_patent_content_blocks("SINR = 信号电平 干扰 + 噪声电平")[0]
        assert block["type"] == "formula"
        assert block["text"] == "SINR=(信号电平)/(干扰+噪声电平)"


class TestNormalizeBlocks:
    def test_paragraph_without_html(self):
        assert normalize.format_patent_content_blocks("plain text") == [{"type": "paragraph", "text": "plain text"}]

    def test_marker_to_html_sub(self):
        blocks = normalize.format_patent_content_blocks("k\n∞")
        assert blocks == [{"type": "paragraph", "text": "k∞", "html": "k<sub>∞</sub>"}]

    def test_inline_math_dollar(self):
        blocks = normalize.format_patent_content_blocks("a $x_i$ b")
        assert blocks == [{"type": "paragraph", "text": "a $x_i$ b", "html": "a x<sub>i</sub> b"}]

    def test_inline_math_paren(self):
        blocks = normalize.format_patent_content_blocks(r"a \(y\) b")
        assert blocks[0]["html"] == "a y b"

    def test_display_math_groups_and_empty_formula(self):
        src = "段前\n$$x=y$$\n$$ $$\n\\[a+b\\]\n\\begin{equation}c=d\\end{equation}\n段后"
        blocks = normalize.format_patent_content_blocks(src)
        assert [(b["type"], b["text"]) for b in blocks] == [
            ("paragraph", "段前"),
            ("formula", "x=y"),
            ("formula", "a+b"),
            ("formula", "c=d"),
            ("paragraph", "段后"),
        ]

    def test_fenced_code_block_and_empty_fence(self):
        blocks = normalize.format_patent_content_blocks("text\n```python\nprint(1)\n```\n```\n```\nend")
        assert blocks == [
            {"type": "paragraph", "text": "text"},
            {"type": "code", "text": "print(1)", "language": "python"},
            {"type": "paragraph", "text": "end"},
        ]


class TestNormalizeFragments:
    def test_should_join_fragment_empty(self):
        assert normalize._should_join_fragment("", "x") is False
        assert normalize._should_join_fragment("x", "") is False

    def test_should_join_fragment_head(self):
        assert normalize._should_join_fragment("abc", ",more") is True

    def test_should_join_fragment_open_tail(self):
        assert normalize._should_join_fragment("f(", "x") is True

    def test_should_join_fragment_number(self):
        assert normalize._should_join_fragment("Table2", "3") is True

    def test_should_join_fragment_number_head(self):
        assert normalize._should_join_fragment("Fig", "12.") is True

    def test_should_join_fragment_sentence_end(self):
        assert normalize._should_join_fragment("End.", "more") is False

    def test_should_join_fragment_tail_word(self):
        assert normalize._should_join_fragment("of", "x") is True
        assert normalize._should_join_fragment("of", "中") is False

    def test_should_join_fragment_lowercase_phrase(self):
        assert normalize._should_join_fragment("Fig", "zoomed view") is True
        assert normalize._should_join_fragment("Fig", "Zoomed View") is False

    def test_join_fragment_text_branches(self):
        assert normalize._join_fragment_text("abc", ",x") == "abc,x"
        assert normalize._join_fragment_text("f(", "x") == "f(x"
        assert normalize._join_fragment_text("ε", "ij") == "εij"
        assert normalize._join_fragment_text("x", "3") == "x 3"
        assert normalize._join_fragment_text("图", "3") == "图3"
        assert normalize._join_fragment_text("x", "12.") == "x 12."
        assert normalize._join_fragment_text("图", "12.") == "图12."
        assert normalize._join_fragment_text("a", "b") == "a b"

    def test_join_inline_fragments(self):
        assert normalize._join_inline_fragments(["the", "system", "中文", "x"]) == ["the system", "中文", "x"]

    def test_coalesce_wrapped_parenthetical_lines(self):
        assert normalize._coalesce_wrapped_parenthetical_lines("f(\nx\n)") == ["f(x)"]
        assert normalize._coalesce_wrapped_parenthetical_lines("a\n(b") == ["a", "(b"]
        assert normalize._coalesce_wrapped_parenthetical_lines(")") == [")"]

    def test_looks_like_prose(self):
        assert normalize._looks_like_prose("the of in") is True
        assert normalize._looks_like_prose("one two three four five six seven eight") is True
        assert normalize._looks_like_prose("foo bar baz") is False
        assert normalize._looks_like_prose("x") is False

    def test_is_math_fragment(self):
        assert normalize._is_math_fragment("x") is True
        assert normalize._is_math_fragment("x=1") is True
        assert normalize._is_math_fragment("(1.5)") is True
        assert normalize._is_math_fragment("1") is False
        assert normalize._is_math_fragment("") is False
        assert normalize._is_math_fragment("中文 x") is False
        assert normalize._is_math_fragment("a" * 101) is False
        assert normalize._is_math_fragment("hello world") is False

    def test_is_formula_expression(self):
        assert normalize._is_formula_expression("a=b") is True
        assert normalize._is_formula_expression("a+b") is True
        assert normalize._is_formula_expression("the-of-in-and-to") is False
        assert normalize._is_formula_expression("plain text") is False
        assert normalize._is_formula_expression("") is False
        assert normalize._is_formula_expression("中文+a") is False
        assert normalize._is_formula_expression("a+b" + "b" * 60) is False

    def test_join_math_run(self):
        assert normalize._join_math_run(["x", "=", "y"]) == "x=y"
        assert normalize._join_math_run(["ε", "ij"]) == "εij"
        assert normalize._join_math_run(["x", "1"]) == "x 1"
        assert normalize._join_math_run(["x", ")"]) == "x)"
        assert normalize._join_math_run(["", "a"]) == "a"

    def test_coalesce_math_lines(self):
        assert normalize._coalesce_math_lines("x\n=\ny") == ["x=y"]
        assert normalize._coalesce_math_lines("x\ny") == ["x", "y"]
        assert normalize._coalesce_math_lines("中文段\nx\n=\ny") == ["中文段", "x=y"]


class TestNormalizeMisc:
    def test_infer_patent_type(self):
        assert normalize.infer_patent_type("CN123S") == "design"
        assert normalize.infer_patent_type("CN123D") == "design"
        assert normalize.infer_patent_type("CN123B") == "invention"

    def test_assert_no_source_leak_drop_keys(self):
        with pytest.raises(ValueError, match="outbound leak key"):
            normalize.assert_no_source_leak({"pdf_url": "x"})
        with pytest.raises(ValueError, match="outbound leak key"):
            normalize.assert_no_source_leak([{"thumbnail": "t"}])

    def test_assert_no_source_leak_value(self):
        with pytest.raises(ValueError, match="outbound leak in value"):
            normalize.assert_no_source_leak({"a": ["ok", "https://patents.google.com/x"]})

    def test_map_search_hit_non_dict(self):
        assert normalize.map_search_hit("not a dict") is None
        assert normalize.map_search_hit(None) is None


# ══════════════════════════════════════════════════════════════
# modules/patent/service.py — 详情 + PDF 预览
# ══════════════════════════════════════════════════════════════


class _FakeImage:
    def save(self, buf, format=None):
        buf.write(b"\x89PNG-fake")


class _FakeBitmap:
    def to_pil(self):
        return _FakeImage()


class _FakePage:
    def __init__(self, render_error=False):
        self._render_error = render_error

    def render(self, scale=1.0):
        if self._render_error:
            raise RuntimeError("render boom")
        return _FakeBitmap()


class _FakePdf:
    def __init__(self, pages=2, render_error=False):
        self._pages = pages
        self._render_error = render_error
        self.closed = False

    def __len__(self):
        return self._pages

    def __getitem__(self, index):
        return _FakePage(self._render_error)

    def close(self):
        self.closed = True


def _fake_pdfium(pdf):
    fake = MagicMock()
    fake.PdfDocument.return_value = pdf
    return fake


class TestPatentServiceDetail:
    def test_get_patent_invalid_pub(self):
        with pytest.raises(BizError) as exc:
            service.get_patent("bad no")
        assert exc.value.code == "TT_COMMON_40001"

    @patch("modules.patent.provider.info_raw")
    def test_get_patent_not_parsed(self, mock_info):
        mock_info.return_value = {}
        with pytest.raises(BizError) as exc:
            service.get_patent("CN12345678A")
        assert exc.value.code == "TT_PATENT_40401"

    @patch("modules.patent.provider.info_raw")
    def test_get_patent_success_with_language(self, mock_info):
        mock_info.return_value = {"title": "T", "abstract": "A"}
        detail = service.get_patent("CN12345678A", language="en")
        assert detail["title"] == "T"
        assert detail["publicationNo"] == "CN12345678A"
        assert detail["language"] == "en"

    @patch("modules.patent.provider.info_raw")
    def test_get_patent_success_no_language(self, mock_info):
        mock_info.return_value = {"title": "T", "number": "CN12345678A"}
        detail = service.get_patent("CN12345678A")
        assert detail["language"] == ""

    def test_iter_patent_pdf(self):
        with patch("modules.patent.provider.iter_pdf_bytes") as mock_iter:
            mock_iter.return_value = [b"a", b"b"]
            assert list(service.iter_patent_pdf("CN12345678A")) == [b"a", b"b"]
            mock_iter.assert_called_once_with("CN12345678A")

    def test_iter_patent_pdf_invalid_pub(self):
        with pytest.raises(BizError):
            list(service.iter_patent_pdf("!!"))


class TestPatentServicePdf:
    def test_clear_pdf_preview_cache(self):
        service._pdf_cache["x"] = (b"x", 1e18)
        service._page_cache[("x", 1)] = b"p"
        service.clear_pdf_preview_cache()
        assert service._pdf_cache == {}
        assert service._page_cache == {}

    def test_pdf_bytes_skips_empty_chunks_and_caches(self):
        with patch("modules.patent.provider.iter_pdf_bytes") as mock_iter:
            mock_iter.return_value = iter([b"", b"ab"])
            assert service._pdf_bytes("CN100000001A") == b"ab"
            assert service._pdf_bytes("CN100000001A") == b"ab"
            assert mock_iter.call_count == 1

    def test_pdf_bytes_empty_raises_not_found(self):
        with patch("modules.patent.provider.iter_pdf_bytes") as mock_iter:
            mock_iter.return_value = iter([])
            with pytest.raises(BizError) as exc:
                service._pdf_bytes("CN100000002A")
            assert exc.value.code == "TT_PATENT_40401"

    def test_pdf_bytes_too_large(self):
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._PDF_MAX_BYTES", 3),
        ):
            mock_iter.return_value = iter([b"1234"])
            with pytest.raises(BizError) as exc:
                service._pdf_bytes("CN100000003A")
            assert exc.value.details["reason"] == "pdf_too_large"

    def test_pdf_bytes_cache_eviction(self):
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._PDF_CACHE_MAX", 1),
        ):
            mock_iter.side_effect = lambda pub: iter([b"z"])
            service._pdf_bytes("CN100000004A")
            service._pdf_bytes("CN100000005A")
            assert list(service._pdf_cache) == ["CN100000005A"]

    def test_get_patent_pdf_pages_meta(self):
        pdf = _FakePdf(pages=3)
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._pdfium", return_value=_fake_pdfium(pdf)),
        ):
            mock_iter.return_value = iter([b"x"])
            assert service.get_patent_pdf_pages_meta("CN100000006A") == {"pageCount": 3}
            assert pdf.closed is True

    def test_render_patent_pdf_page_invalid_page(self):
        with pytest.raises(BizError):
            service.render_patent_pdf_page("CN100000007A", 0)

    def test_render_patent_pdf_page_success_and_cache(self):
        pdf = _FakePdf(pages=2)
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._pdfium", return_value=_fake_pdfium(pdf)),
        ):
            mock_iter.return_value = iter([b"x"])
            assert service.render_patent_pdf_page("CN100000008A", 1) == b"\x89PNG-fake"
            assert service.render_patent_pdf_page("CN100000008A", 1) == b"\x89PNG-fake"
            assert mock_iter.call_count == 1

    def test_render_patent_pdf_page_out_of_range(self):
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._pdfium", return_value=_fake_pdfium(_FakePdf(pages=1))),
        ):
            mock_iter.return_value = iter([b"x"])
            with pytest.raises(BizError):
                service.render_patent_pdf_page("CN100000009A", 5)

    def test_render_patent_pdf_page_render_failure(self):
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._pdfium", return_value=_fake_pdfium(_FakePdf(render_error=True))),
        ):
            mock_iter.return_value = iter([b"x"])
            with pytest.raises(BizError) as exc:
                service.render_patent_pdf_page("CN100000010A", 1)
            assert exc.value.details["reason"] == "pdf_render_failed"

    def test_render_patent_pdf_page_cache_eviction(self):
        with (
            patch("modules.patent.provider.iter_pdf_bytes") as mock_iter,
            patch("modules.patent.service._pdfium", return_value=_fake_pdfium(_FakePdf(pages=3))),
            patch("modules.patent.service._PAGE_CACHE_MAX", 1),
        ):
            mock_iter.return_value = iter([b"x"])
            service.render_patent_pdf_page("CN100000011A", 1)
            service.render_patent_pdf_page("CN100000011A", 2)
            assert len(service._page_cache) == 1

    def test_open_pdf_success_and_failure(self):
        doc = _FakePdf()
        with patch("modules.patent.service._pdfium", return_value=_fake_pdfium(doc)):
            assert service._open_pdf("CN100000012A", b"data") is doc

        boom = _fake_pdfium(MagicMock())
        boom.PdfDocument.side_effect = ValueError("bad pdf")
        with (
            patch("modules.patent.service._pdfium", return_value=boom),
            pytest.raises(BizError) as exc,
        ):
            service._open_pdf("CN100000012A", b"data")
        assert exc.value.details["reason"] == "pdf_open_failed"

    def test_open_pdf_biz_error_passthrough(self):
        boom = _fake_pdfium(MagicMock())
        boom.PdfDocument.side_effect = BizError("TT_X", "inner", 500)
        with (
            patch("modules.patent.service._pdfium", return_value=boom),
            pytest.raises(BizError) as exc,
        ):
            service._open_pdf("CN100000013A", b"data")
        assert exc.value.code == "TT_X"

    def test_pdfium_missing_dependency(self):
        with (
            patch.dict("sys.modules", {"pypdfium2": None}),
            pytest.raises(BizError) as exc,
        ):
            service._pdfium()
        assert exc.value.details["reason"] == "preview_not_installed"

    def test_pdfium_available(self):
        assert service._pdfium().PdfDocument is not None


# ══════════════════════════════════════════════════════════════
# modules/patent/provider.py — HTTP 客户端（全部 patch urlopen）
# ══════════════════════════════════════════════════════════════


class _FakeResp:
    def __init__(self, body=b"", content_type="application/json"):
        self._body = body
        self.headers = {"Content-Type": content_type}
        self.closed = False

    def read(self, *args):
        data, self._body = self._body, b""
        return data

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _provider_env(base="https://up.example.com", key="secret"):
    ms = MagicMock()
    ms.PATENT_PROVIDER_BASE = base
    ms.PATENT_PROVIDER_KEY = key
    ms.PATENT_PROVIDER_TIMEOUT = 5
    ms.PATENT_PDF_TIMEOUT = 5
    return ms


def _http_error(code, body=b"oops"):
    return urllib.error.HTTPError("https://up.example.com/x", code, "err", {}, io.BytesIO(body))


class TestProviderNotConfigured:
    def test_search_raw_not_configured(self):
        with (
            patch("modules.patent.provider.settings", _provider_env(base="", key="")),
            pytest.raises(BizError) as exc,
        ):
            provider.search_raw(keyword="k", assignee="", page=1, page_size=10)
        assert exc.value.details["reason"] == "not_configured"

    def test_info_raw_not_configured(self):
        with (
            patch("modules.patent.provider.settings", _provider_env(base="", key="")),
            pytest.raises(BizError) as exc,
        ):
            provider.info_raw("CN1")
        assert exc.value.details["reason"] == "not_configured"

    def test_iter_pdf_not_configured(self):
        with (
            patch("modules.patent.provider.settings", _provider_env(base="", key="")),
            pytest.raises(BizError) as exc,
        ):
            next(provider.iter_pdf_bytes("CN1"))
        assert exc.value.details["reason"] == "not_configured"


class TestProviderHttpJson:
    def _search(self):
        return provider.search_raw(keyword="k", assignee="a", page=2, page_size=10)

    def test_search_raw_fetcher_params(self):
        calls = []

        def fetch(path, params, timeout):
            calls.append((path, params, timeout))
            return {"results": []}

        with patch("modules.patent.provider.settings", _provider_env()):
            result = provider.search_raw(keyword="k", assignee="a", page=2, page_size=10, fetcher=fetch)
        assert result == {"results": []}
        assert calls == [("/patent_search", {"q": "k", "assignee": "a", "num": 10, "page": 1}, 5)]

    def test_info_raw_fetcher_params(self):
        calls = []

        def fetch(path, params, timeout):
            calls.append((path, params, timeout))
            return {"title": "T"}

        with patch("modules.patent.provider.settings", _provider_env()):
            assert provider.info_raw("CN1", language="en", fetcher=fetch) == {"title": "T"}
        assert calls == [("/patent_info", {"query": "CN1", "language": "en"}, 5)]

    def test_http_json_success(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=_FakeResp(b'{"a": 1}')),
        ):
            assert self._search() == {"a": 1}

    def test_http_json_empty_body(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=_FakeResp(b"")),
        ):
            assert self._search() == {}

    def test_http_json_non_dict(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=_FakeResp(b"[1]")),
        ):
            assert self._search() == {}

    def test_http_json_invalid_json(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=_FakeResp(b"not json")),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert exc.value.details["reason"] == "invalid_response"

    def test_http_json_invalid_utf8(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=_FakeResp(b"\xff\xfe")),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert exc.value.details["reason"] == "invalid_response"

    def test_http_json_404_returns_empty(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=_http_error(404)),
        ):
            assert self._search() == {}

    def test_http_json_retry_then_success(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=[_http_error(503), _FakeResp(b'{"ok": 1}')]) as mock_open,
            patch("time.sleep") as mock_sleep,
        ):
            assert self._search() == {"ok": 1}
            assert mock_open.call_count == 2
            mock_sleep.assert_called_once()

    def test_http_json_retry_exhausted(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=_http_error(503)) as mock_open,
            patch("time.sleep"),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert mock_open.call_count == 3
        assert exc.value.details["providerStatus"] == 503

    def test_http_json_429_maps_to_rate_limit(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=_http_error(429, body=b"")),
            patch("time.sleep"),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert exc.value.code == "TT_COMMON_42901"
        assert exc.value.http_status == 429
        assert "upstreamBody" not in exc.value.details

    def test_http_json_network_retry_then_success(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=[urllib.error.URLError("dns"), _FakeResp(b'{"ok": 2}')]),
            patch("time.sleep"),
        ):
            assert self._search() == {"ok": 2}

    def test_http_json_network_exhausted(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
            patch("time.sleep"),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert exc.value.code == "TT_PATENT_50301"
        assert exc.value.details["reason"] == "timeout"

    def test_http_json_unreachable_fallback(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("modules.patent.provider._RETRY_TIMES", 0),
            pytest.raises(BizError) as exc,
        ):
            self._search()
        assert exc.value.details["reason"] == "unreachable"


class TestProviderPdfStream:
    def test_iter_pdf_success(self):
        resp = _FakeResp(b"PDFBYTES", "application/pdf; charset=binary")
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=resp) as mock_open,
        ):
            assert list(provider.iter_pdf_bytes("CN12345678A")) == [b"PDFBYTES"]
            assert resp.closed is True
            url = mock_open.call_args[0][0].full_url
            assert url.startswith("https://up.example.com/patent_pdf?")
            assert "key=secret" in url

    def test_iter_pdf_octet_stream_and_empty_type(self):
        for content_type in ("application/octet-stream", ""):
            resp = _FakeResp(b"Z", content_type)
            with (
                patch("modules.patent.provider.settings", _provider_env()),
                patch("urllib.request.urlopen", return_value=resp),
            ):
                assert list(provider.iter_pdf_bytes("CN12345678A")) == [b"Z"]

    def test_iter_pdf_unexpected_content_type(self):
        resp = _FakeResp(b"<html>", "text/html")
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", return_value=resp),
            pytest.raises(BizError) as exc,
        ):
            list(provider.iter_pdf_bytes("CN12345678A"))
        assert exc.value.details["reason"] == "invalid_content_type"
        assert resp.closed is True

    def test_iter_pdf_404(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=_http_error(404)),
            pytest.raises(BizError) as exc,
        ):
            list(provider.iter_pdf_bytes("CN12345678A"))
        assert exc.value.code == "TT_PATENT_40401"

    def test_iter_pdf_http_error(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=_http_error(500)),
            pytest.raises(BizError) as exc,
        ):
            list(provider.iter_pdf_bytes("CN12345678A"))
        assert exc.value.details["providerStatus"] == 500

    def test_iter_pdf_network_error(self):
        with (
            patch("modules.patent.provider.settings", _provider_env()),
            patch("urllib.request.urlopen", side_effect=ConnectionResetError("reset")),
            pytest.raises(BizError) as exc,
        ):
            list(provider.iter_pdf_bytes("CN12345678A"))
        assert exc.value.details["reason"] == "connection_reset"


# ══════════════════════════════════════════════════════════════
# routes/internal_ai.py — handler 直接调用（不启动服务）
# ══════════════════════════════════════════════════════════════


class TestInternalAiAuth:
    def test_client_host(self):
        assert internal_ai._client_host(_req(host="9.9.9.9")) == "9.9.9.9"
        assert internal_ai._client_host(_req(host=None)) == ""

    def test_require_service_key_ok(self):
        with patch("routes.internal_ai.settings") as ms:
            ms.AI_INTERNAL_SERVICE_KEY = "sekret"
            assert internal_ai.require_service_key(_req(headers={"X-AI-Service-Key": "sekret"})) is None

    def test_require_service_key_wrong_or_missing(self):
        with patch("routes.internal_ai.settings") as ms:
            ms.AI_INTERNAL_SERVICE_KEY = "sekret"
            for headers in ({"X-AI-Service-Key": "bad"}, {}, {"X-AI-Service-Key": " "}):
                with pytest.raises(BizError) as exc:
                    internal_ai.require_service_key(_req(headers=headers))
                assert exc.value.http_status == 401

    def test_require_service_key_loopback_without_config(self):
        with patch("routes.internal_ai.settings") as ms:
            ms.AI_INTERNAL_SERVICE_KEY = ""
            assert internal_ai.require_service_key(_req(host="127.0.0.1")) is None
            assert internal_ai.require_service_key(_req(host="::1")) is None

    def test_require_service_key_non_loopback_without_config(self):
        with (
            patch("routes.internal_ai.settings") as ms,
            pytest.raises(BizError) as exc,
        ):
            ms.AI_INTERNAL_SERVICE_KEY = ""
            internal_ai.require_service_key(_req(host="10.1.2.3"))
        assert exc.value.http_status == 401
        with (
            patch("routes.internal_ai.settings") as ms2,
            pytest.raises(BizError),
        ):
            ms2.AI_INTERNAL_SERVICE_KEY = ""
            internal_ai.require_service_key(_req(host=None))

    @patch("db.get_cursor")
    def test_lookup_user_no(self, mock_gc):
        _bind_cursor(mock_gc, _cur())
        assert internal_ai._lookup_user_no(1) == "U001"

    @patch("db.get_cursor")
    def test_lookup_user_no_missing_row(self, mock_gc):
        cur = _cur()
        cur.fetchone.return_value = None
        _bind_cursor(mock_gc, cur)
        assert internal_ai._lookup_user_no(1) == ""

    @patch("db.get_cursor")
    def test_lookup_user_no_db_error(self, mock_gc):
        mock_gc.side_effect = RuntimeError("db down")
        assert internal_ai._lookup_user_no(1) == ""

    def test_positive_int(self):
        assert internal_ai._positive_int("5", "userId") == 5
        assert internal_ai._positive_int(7, "userId") == 7
        for bad in (True, "abc", 0, -3, None):
            with pytest.raises(BizError):
                internal_ai._positive_int(bad, "userId")


class TestInternalAiHandlers:
    @patch("routes.internal_ai.create_evaluation_task")
    @patch("db.get_cursor")
    def test_internal_evaluation_create_new(self, mock_gc, mock_create):
        _bind_cursor(mock_gc, _cur())
        mock_create.return_value = ({"id": 7, "status": "queued"}, True)
        body = internal_ai.InternalEvaluationCreateBody(userId=1, achievementId=2)
        resp = internal_ai.internal_evaluation_create(body, _req())
        assert resp["code"] == 0
        assert resp["data"]["isNew"] is True
        assert resp["message"] == "任务已受理"
        args, _kwargs = mock_create.call_args
        assert args == (1, "U001", 2)

    @patch("routes.internal_ai.create_evaluation_task")
    @patch("db.get_cursor")
    def test_internal_evaluation_create_dedup(self, mock_gc, mock_create):
        _bind_cursor(mock_gc, _cur())
        mock_create.return_value = ({"id": 8, "status": "running"}, False)
        body = internal_ai.InternalEvaluationCreateBody(userId=1, achievementId=2)
        resp = internal_ai.internal_evaluation_create(body, _req())
        assert resp["data"]["isNew"] is False
        assert resp["message"] == "任务进行中"

    def test_internal_evaluation_create_bad_body(self):
        body = internal_ai.InternalEvaluationCreateBody(userId="x", achievementId=2)
        with pytest.raises(BizError) as exc:
            internal_ai.internal_evaluation_create(body, _req())
        assert exc.value.code == "TT_COMMON_40001"

    @patch("routes.internal_ai.get_evaluation_task")
    def test_internal_evaluation_detail(self, mock_get):
        mock_get.return_value = {"id": 3, "status": "succeeded"}
        resp = internal_ai.internal_evaluation_detail(3, _req(query={"userId": "5"}))
        assert resp["data"]["id"] == 3
        mock_get.assert_called_once_with(5, 3)

    def test_internal_evaluation_detail_missing_user(self):
        with pytest.raises(BizError):
            internal_ai.internal_evaluation_detail(3, _req())

    @patch("routes.internal_ai.list_evaluations")
    def test_internal_evaluation_history_full_query(self, mock_list):
        mock_list.return_value = {"list": [], "total": 0}
        query = {"userId": "5", "achievementId": "7", "page": "2", "pageSize": "20"}
        resp = internal_ai.internal_evaluation_history(_req(query=query))
        assert resp["data"] == {"list": [], "total": 0}
        mock_list.assert_called_once_with(5, 2, 20, 7)

    @patch("routes.internal_ai.list_evaluations")
    def test_internal_evaluation_history_defaults(self, mock_list):
        mock_list.return_value = {"list": [], "total": 0}
        resp = internal_ai.internal_evaluation_history(_req(query={"userId": "5", "achievementId": ""}))
        assert resp["code"] == 0
        mock_list.assert_called_once_with(5, 1, 10, None)

    @patch("routes.internal_ai.list_evaluations")
    def test_internal_evaluation_history_bad_page(self, mock_list):
        mock_list.return_value = {"list": [], "total": 0}
        internal_ai.internal_evaluation_history(_req(query={"userId": "5", "page": "x", "pageSize": "y"}))
        mock_list.assert_called_once_with(5, 1, 10, None)

    def test_internal_evaluation_history_bad_achievement(self):
        with pytest.raises(BizError):
            internal_ai.internal_evaluation_history(_req(query={"userId": "5", "achievementId": "x"}))


# ══════════════════════════════════════════════════════════════
# core/middleware.py — DB 三查（patch db.get_cursor + auth_cache 直通）
# ══════════════════════════════════════════════════════════════


class TestMiddlewareDbChecks:
    @patch("core.middleware.auth_cache.cached", lambda key, fn: fn())
    @patch("db.get_cursor")
    def test_user_is_active(self, mock_gc):
        from core import middleware

        _bind_cursor(mock_gc, _cur())
        assert middleware._user_is_active(1) is True

    @patch("core.middleware.auth_cache.cached", lambda key, fn: fn())
    @patch("db.get_cursor")
    def test_user_is_active_missing(self, mock_gc):
        from core import middleware

        cur = _cur()
        cur.fetchone.return_value = None
        _bind_cursor(mock_gc, cur)
        assert middleware._user_is_active(1) is False

    @patch("core.middleware.auth_cache.cached", lambda key, fn: fn())
    @patch("db.get_cursor")
    def test_is_admin_role(self, mock_gc):
        from core import middleware

        _bind_cursor(mock_gc, _cur())
        assert middleware._is_admin_role(1) is True
        cur = _cur()
        cur.fetchone.return_value = None
        _bind_cursor(mock_gc, cur)
        assert middleware._is_admin_role(1) is False

    @patch("core.middleware.auth_cache.cached", lambda key, fn: fn())
    @patch("db.get_cursor")
    def test_org_admin_info(self, mock_gc):
        from core import middleware

        _bind_cursor(mock_gc, _cur())
        assert middleware._org_admin_info(1) == ([1], True)

    @patch("core.middleware.auth_cache.cached", lambda key, fn: fn())
    @patch("db.get_cursor")
    def test_org_admin_info_none(self, mock_gc):
        from core import middleware

        cur = _cur()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        _bind_cursor(mock_gc, cur)
        assert middleware._org_admin_info(1) == ([], False)


# ══════════════════════════════════════════════════════════════
# core/rate_limit.py — 滑动窗口 + trusted-proxy
# ══════════════════════════════════════════════════════════════


class TestRateLimit:
    def test_is_trusted_proxy_default_loopback(self):
        from core import rate_limit

        assert rate_limit._is_trusted_proxy("127.0.0.1") is True
        assert rate_limit._is_trusted_proxy("::ffff:127.0.0.1") is True
        assert rate_limit._is_trusted_proxy("LOCALHOST") is True
        assert rate_limit._is_trusted_proxy("8.8.8.8") is False
        assert rate_limit._is_trusted_proxy("") is False

    def test_is_trusted_proxy_cidr(self):
        from core import rate_limit

        with patch.dict("os.environ", {"TRUSTED_PROXIES": "10.0.0.0/8,192.168.1.5"}):
            assert rate_limit._is_trusted_proxy("10.1.2.3") is True
            assert rate_limit._is_trusted_proxy("192.168.1.5") is True
            assert rate_limit._is_trusted_proxy("11.0.0.1") is False

    def test_is_trusted_proxy_bad_cidr_or_ip(self):
        from core import rate_limit

        with patch.dict("os.environ", {"TRUSTED_PROXIES": "10.0.0.0/99,bad-cidr/zz"}):
            assert rate_limit._is_trusted_proxy("10.1.2.3") is False
            assert rate_limit._is_trusted_proxy("not-an-ip") is False

    def test_sweep_locked(self):
        from collections import deque

        from core import rate_limit

        with rate_limit._bucket_lock:
            rate_limit._buckets.clear()
            rate_limit._buckets["a"] = deque()
            rate_limit._buckets["b"] = deque([1.0])
            rate_limit._buckets["c"] = deque([2.0])
            rate_limit._buckets["d"] = deque([3.0])
            with patch("core.rate_limit._MAX_BUCKETS", 2):
                rate_limit._sweep_locked(99.0)
            assert "a" not in rate_limit._buckets
            assert "b" not in rate_limit._buckets
            assert set(rate_limit._buckets) == {"c", "d"}
            rate_limit._buckets.clear()

    def test_check_window_prune_and_sweep_trigger(self):
        from core import rate_limit

        key = _uniq("prune")
        rate_limit._check(key, limit=5, window_s=60)
        rate_limit._buckets[key][0] -= 999
        with patch("core.rate_limit._CLEAN_EVERY", 1):
            rate_limit._check(key, limit=5, window_s=60)
        assert len(rate_limit._buckets[key]) == 1

    def test_check_rate_limit_exceeded(self):
        from core import rate_limit

        key = _uniq("limit")
        rate_limit._check(key, limit=1, window_s=60)
        with pytest.raises(BizError) as exc:
            rate_limit._check(key, limit=1, window_s=60)
        assert exc.value.code == "TT_COMMON_42901"

    def test_client_ip_untrusted_peer_keeps_peer(self):
        from core import rate_limit

        req = _req(host="9.9.9.9", headers={"x-forwarded-for": "1.1.1.1"})
        assert rate_limit._client_ip(req) == "9.9.9.9"

    def test_client_ip_trusted_peer_uses_last_hop(self):
        from core import rate_limit

        req = _req(host="127.0.0.1", headers={"x-forwarded-for": "1.1.1.1, 10.2.2.2"})
        assert rate_limit._client_ip(req) == "10.2.2.2"

    def test_client_ip_trusted_peer_without_xff(self):
        from core import rate_limit

        assert rate_limit._client_ip(_req(host="127.0.0.1")) == "127.0.0.1"
        req = _req(host="127.0.0.1", headers={"x-forwarded-for": "1.2.3.4, "})
        assert rate_limit._client_ip(req) == "127.0.0.1"

    def test_client_ip_no_client(self):
        from core import rate_limit

        assert rate_limit._client_ip(_req(host=None)) == "unknown"

    def test_check_login_rate_with_account(self):
        from core import rate_limit

        account = _uniq("acct")
        req = _req(host=_uniq("ip"))
        rate_limit.check_login_rate(req, account=account)
        rate_limit.check_login_rate(req)
        with pytest.raises(BizError):
            for _ in range(5):
                rate_limit.check_login_rate(_req(host="127.0.0.1"), account=account)


# ══════════════════════════════════════════════════════════════
# core/exception_handlers.py — 日志配置 + 错误日志
# ══════════════════════════════════════════════════════════════


def _fake_get_logger(fake_root):
    real = logging.getLogger

    def _get(name=None):
        if name is None:
            return fake_root
        return real(name)

    return _get


class TestExceptionHandlersLogging:
    def _settings(self, log_dir):
        ms = MagicMock()
        ms.LOG_LEVEL = "DEBUG"
        ms.LOG_DIR = log_dir
        ms.LOG_MAX_BYTES = 1024
        ms.LOG_BACKUP_COUNT = 1
        return ms

    def test_configure_logging_console_only(self):
        from core import exception_handlers as eh

        fake_root = logging.Logger("cov-root-console")
        with (
            patch("logging.getLogger", side_effect=_fake_get_logger(fake_root)),
            patch("config.settings", self._settings("")),
        ):
            eh.configure_logging()
        assert len(fake_root.handlers) == 1
        assert fake_root.level == logging.DEBUG

    def test_configure_logging_with_file(self, tmp_path):
        from core import exception_handlers as eh

        fake_root = logging.Logger("cov-root-file")
        with (
            patch("logging.getLogger", side_effect=_fake_get_logger(fake_root)),
            patch("config.settings", self._settings(str(tmp_path))),
        ):
            eh.configure_logging()
        assert len(fake_root.handlers) == 2
        assert (tmp_path / "tech-transfer-service.log").exists()

    def test_configure_logging_idempotent(self):
        from core import exception_handlers as eh

        fake_root = logging.Logger("cov-root-has-handler")
        fake_root.addHandler(logging.StreamHandler())
        with (
            patch("logging.getLogger", side_effect=_fake_get_logger(fake_root)),
            patch("config.settings", self._settings("")),
        ):
            eh.configure_logging()
        assert len(fake_root.handlers) == 1

    def test_log_error_levels(self):
        from core import exception_handlers as eh

        req = MagicMock()
        req.method = "GET"
        req.url.path = "/x"
        with patch("core.exception_handlers.logger") as mock_log:
            eh._log_error(req, 404, "C")
            mock_log.debug.assert_called_once()
            mock_log.reset_mock()
            eh._log_error(req, 500, "C")
            mock_log.error.assert_called_once()
            mock_log.reset_mock()
            eh._log_error(req, 200, "C")
            mock_log.info.assert_called_once()
            mock_log.reset_mock()
            eh._log_error(req, 500, "C", exc=True)
            mock_log.error.assert_called_once()
