"""
专利检索路由 —— GET /patents、GET /patents/{publicationNo}、
GET /patents/{publicationNo}/pdf、GET /patents/{publicationNo}/pdf/pages

前端只消费本服务契约。上游 PDF / 源站地址不会出现在 JSON 响应里。
"""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response, StreamingResponse

from core.errors import patent_not_found
from core.middleware import identity
from core.pagination import parse_page_args
from core.request_schemas import PatentSearchHistoryRequest
from core.response import success
from modules.patent.service import (
    get_patent,
    get_patent_pdf_pages_meta,
    iter_patent_pdf,
    render_patent_pdf_page,
    search_patents,
)
from modules.patent.history import clear_history, list_history, record_history

router = APIRouter(prefix="/api/tech-transfer/v1", tags=["patents"])


@router.get("/patents")
def list_patents(request: Request, user: dict = Depends(identity)):
    page, page_size, keyword = parse_page_args(request)
    assignee = (request.query_params.get("assignee") or "").strip()
    return success(search_patents(keyword, assignee, page, page_size))


@router.get("/patents/search-history")
def patent_search_history(mode: str = "keyword", user: dict = Depends(identity)):
    return success(list_history(user["userId"], mode))


@router.post("/patents/search-history")
def record_patent_search_history(body: PatentSearchHistoryRequest, user: dict = Depends(identity)):
    payload = body.as_dict()
    return success(record_history(user["userId"], payload.get("mode"), payload.get("keyword")))


@router.delete("/patents/search-history")
def patent_search_history_clear(mode: str = "keyword", user: dict = Depends(identity)):
    return success(clear_history(user["userId"], mode), "搜索记录已清空")


@router.get("/patents/{publication_no}/pdf")
def patent_pdf(publication_no: str, user: dict = Depends(identity)):
    filename = f"{publication_no.strip()}.pdf"
    stream = iter_patent_pdf(publication_no)
    first = next(stream, b"")
    if not first:
        raise patent_not_found()

    def body():
        yield first
        yield from stream

    return StreamingResponse(
        body(),
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'inline; filename="{filename}"',
            "Cache-Control": "private, max-age=3600",
        },
    )


@router.get("/patents/{publication_no}/pdf/pages")
def patent_pdf_pages(publication_no: str, user: dict = Depends(identity)):
    return success(get_patent_pdf_pages_meta(publication_no))


@router.get("/patents/{publication_no}/pdf/pages/{page}")
def patent_pdf_page(publication_no: str, page: int, user: dict = Depends(identity)):
    png = render_patent_pdf_page(publication_no, page)
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@router.get("/patents/{publication_no}")
def patent_detail(publication_no: str, request: Request, user: dict = Depends(identity)):
    language = (request.query_params.get("language") or "").strip()[:8]
    return success(get_patent(publication_no, language=language))
