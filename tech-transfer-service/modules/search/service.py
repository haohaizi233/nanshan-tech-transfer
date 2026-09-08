"""search service —— 统一搜索（成果 + 需求双类型聚合）

Architecture source: 04-backend-domain-design.md §search, openapi.yaml GET /search
Phase B 收口：从 achievement 路由的 type=achievement 单类型实现升级为
跨域聚合（聚合调用 achievement / demand 两域 service，不直接写 SQL）。
"""

from modules.achievement.service import list_achievements
from modules.demand.service import list_demands


def _empty_page(page: int, page_size: int) -> dict:
    return {
        "total": 0,
        "page": page,
        "pageSize": page_size,
        "totalPages": 0,
        "list": [],
    }


def search(q: str, search_type: str, category_code: str, maturity_level: str,
           page: int, page_size: int, user_id) -> dict:
    """统一搜索：keyword 命中成果（title/tech_intro/source_org_name）与需求（title/description/org）。

    search_type: achievement / demand / all —— 非请求类型返回空分页结构（保持响应形状稳定）。
    """
    achievements = _empty_page(page, page_size)
    demands = _empty_page(page, page_size)

    if search_type in ("achievement", "all"):
        achievements = list_achievements(
            {
                "keyword": q,
                "category": category_code,
                "maturityLevel": maturity_level,
                "page": page,
                "pageSize": page_size,
            },
            user_id,
        )

    if search_type in ("demand", "all"):
        demands = list_demands(
            {
                "keyword": q,
                "categoryCode": category_code,
                "page": page,
                "pageSize": page_size,
            },
            user_id,
        )

    return {"achievements": achievements, "demands": demands}
