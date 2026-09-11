"""说明书 PDF 本页预览：页数元数据 + PNG 渲染（不打真实上游）。"""

from io import BytesIO

import pypdfium2 as pdfium

from core.errors import BizError
from modules.patent import service


def _make_pdf(page_count=1) -> bytes:
    pdf = pdfium.PdfDocument.new()
    for _ in range(page_count):
        pdf.new_page(200, 200)
    buf = BytesIO()
    pdf.save(buf)
    pdf.close()
    return buf.getvalue()


def main():
    fixture = _make_pdf(2)
    original = service.provider.iter_pdf_bytes
    service.clear_pdf_preview_cache()
    service.provider.iter_pdf_bytes = lambda pub: iter([fixture])
    try:
        meta = service.get_patent_pdf_pages_meta("CN1234567A")
        assert meta["pageCount"] == 2

        png = service.render_patent_pdf_page("CN1234567A", 1)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"
        cached = service.render_patent_pdf_page("CN1234567A", 1)
        assert cached == png

        page2 = service.render_patent_pdf_page("CN1234567A", 2)
        assert page2[:8] == b"\x89PNG\r\n\x1a\n"

        try:
            service.render_patent_pdf_page("CN1234567A", 9)
            raise AssertionError("expected invalid page to fail")
        except BizError as exc:
            assert exc.code == "TT_COMMON_40001"

        try:
            service.get_patent_pdf_pages_meta("not-a-patent")
            raise AssertionError("expected invalid publication no to fail")
        except BizError as exc:
            assert exc.code == "TT_COMMON_40001"
    finally:
        service.provider.iter_pdf_bytes = original
        service.clear_pdf_preview_cache()

    print("PASS: patent pdf preview")


if __name__ == "__main__":
    main()
