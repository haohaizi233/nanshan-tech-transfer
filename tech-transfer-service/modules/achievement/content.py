"""成果动态内容关系的校验、同步与读取。

这些关系不混入 achievement 主表，旧字段继续由 service.py 负责，因而老数据和
老客户端仍可工作；新客户端可以按 sections / patents / links / media 渲染。
"""
from __future__ import annotations

from urllib.parse import urlparse

from config import settings
from core.errors import bad_request
from modules.patent.normalize import is_publication_no

SECTION_CODES = {
    "innovation", "maturity_detail", "project_support", "application", "tech_problem",
    "tech_method", "tech_effect", "market_prospect", "industrialization", "team_intro",
    "technical_route", "commercialization", "other",
}
PATENT_NO_MAX = 64
LINK_TYPES = {"official_site", "personal_homepage", "company_site", "demo", "video", "paper", "other"}
MEDIA_ROLES = {"cover", "gallery", "demo", "patent_qr", "diagram", "product"}


def supports_internal_patent_lookup(patent_no: str | None) -> bool:
    """只为现有专利模块可受理的公开号提供内部跳转入口。

    成果关系允许收录项目内部编号等宽松标识；它们不能被误导航到一个必然失败的
    专利详情页，应由调用方在存在 externalUrl 时走 WebView fallback。
    """
    return is_publication_no(str(patent_no or ""))


def _text(value, field, maximum, required=False):
    value = "" if value is None else str(value).strip()
    if required and not value:
        raise bad_request(f"{field} 必填")
    if len(value) > maximum:
        raise bad_request(f"{field} 长度不能超过 {maximum}")
    return value or None


def _sort_order(value, field, default):
    """将外部排序值收敛到有限的非负整数，绝不让 ValueError 泄漏成 500。"""
    if value is None:
        return default
    if isinstance(value, bool):
        raise bad_request(f"{field} 必须是非负整数")
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        raise bad_request(f"{field} 必须是非负整数")
    if parsed < 0 or parsed > 10000:
        raise bad_request(f"{field} 必须在 0 到 10000 之间")
    return parsed


def parse_content_payload(body: dict) -> dict:
    """仅解析出现的关系，PATCH 未出现的关系不会被整体清空。"""
    # 兼容旧客户端的 mediaFileIds，但绝不能像旧实现那样“接收后忽略”。
    # 没有角色信息时，按列表顺序把首项作为封面，其余作为图集；新版 media
    # 与旧字段同时传入则拒绝，避免两个载体对同一关系给出相互矛盾的结果。
    if "mediaFileIds" in body:
        if "media" in body:
            raise bad_request("media 与 mediaFileIds 不能同时传入")
        legacy_ids = body["mediaFileIds"]
        if not isinstance(legacy_ids, list) or len(legacy_ids) > 30:
            raise bad_request("mediaFileIds 必须是最多 30 项的数组")
        normalized_ids = []
        for index, value in enumerate(legacy_ids):
            try:
                file_id = int(value)
            except (TypeError, ValueError):
                raise bad_request(f"mediaFileIds[{index}] 无效")
            if file_id < 1:
                raise bad_request(f"mediaFileIds[{index}] 无效")
            if file_id not in normalized_ids:
                normalized_ids.append(file_id)
        body = dict(body)
        body["media"] = [
            {"fileId": file_id, "role": "cover" if index == 0 else "gallery", "sortOrder": index}
            for index, file_id in enumerate(normalized_ids)
        ]
    result = {}
    if "tags" in body:
        raw = body["tags"]
        if not isinstance(raw, list) or len(raw) > 20 or any(not isinstance(value, str) for value in raw):
            raise bad_request("tags 必须是最多 20 项的字符串数组")
        tags = []
        for index, value in enumerate(raw):
            tag = _text(value, f"tags[{index}]", 64, True)
            if tag not in tags:
                tags.append(tag)
        result["tags"] = tags
    if "sections" in body:
        raw = body["sections"]
        if not isinstance(raw, list) or len(raw) > 30:
            raise bad_request("sections 必须是最多 30 项的数组")
        sections, seen = [], set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise bad_request(f"sections[{index}] 必须是对象")
            code = _text(item.get("code"), f"sections[{index}].code", 32, True)
            if code not in SECTION_CODES or code in seen:
                raise bad_request(f"sections[{index}].code 无效或重复")
            seen.add(code)
            sections.append({"code": code, "title": _text(item.get("title"), f"sections[{index}].title", 128, True), "content": _text(item.get("content"), f"sections[{index}].content", 20000, True), "sort": _sort_order(item.get("sortOrder"), f"sections[{index}].sortOrder", index)})
        result["sections"] = sections
    if "patents" in body:
        raw = body["patents"]
        if not isinstance(raw, list) or len(raw) > 20:
            raise bad_request("patents 必须是最多 20 项的数组")
        patents, seen, primary_count = [], set(), 0
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise bad_request(f"patents[{index}] 必须是对象")
            no = _text(item.get("patentNo"), f"patents[{index}].patentNo", PATENT_NO_MAX, True).upper()
            if no in seen:
                raise bad_request("patentNo 不能重复")
            seen.add(no)
            is_primary = bool(item.get("isPrimary"))
            primary_count += int(is_primary)
            if primary_count > 1:
                raise bad_request("最多只能指定一个主专利")
            url = _optional_url(item.get("externalUrl"), f"patents[{index}].externalUrl")
            patents.append({"no": no, "title": _text(item.get("title"), f"patents[{index}].title", 500), "primary": is_primary, "url": url, "sort": _sort_order(item.get("sortOrder"), f"patents[{index}].sortOrder", index)})
        result["patents"] = patents
    if "links" in body:
        raw = body["links"]
        if not isinstance(raw, list) or len(raw) > 20:
            raise bad_request("links 必须是最多 20 项的数组")
        links = []
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or item.get("type") not in LINK_TYPES:
                raise bad_request(f"links[{index}] 类型无效")
            links.append({"type": item["type"], "label": _text(item.get("label"), f"links[{index}].label", 255, True), "url": _optional_url(item.get("url"), f"links[{index}].url", required=True), "sort": _sort_order(item.get("sortOrder"), f"links[{index}].sortOrder", index)})
        result["links"] = links
    if "media" in body:
        raw = body["media"]
        if not isinstance(raw, list) or len(raw) > 30:
            raise bad_request("media 必须是最多 30 项的数组")
        media, cover_count = [], 0
        for index, item in enumerate(raw):
            if not isinstance(item, dict):
                raise bad_request(f"media[{index}] 必须是对象")
            try:
                file_id = int(item.get("fileId"))
            except (ValueError, TypeError):
                raise bad_request(f"media[{index}].fileId 无效")
            role = item.get("role", "gallery")
            if role not in MEDIA_ROLES:
                raise bad_request(f"media[{index}].role 无效")
            cover_count += int(role == "cover")
            if cover_count > 1:
                raise bad_request("最多只能设置一张封面")
            media.append({"file_id": file_id, "role": role, "caption": _text(item.get("caption"), f"media[{index}].caption", 500), "alt": _text(item.get("altText"), f"media[{index}].altText", 500), "sort": _sort_order(item.get("sortOrder"), f"media[{index}].sortOrder", index)})
        result["media"] = media
    if "industryIds" in body:
        raw = body["industryIds"]
        if not isinstance(raw, list) or len(raw) > 8:
            raise bad_request("industryIds 必须是最多 8 项的数组")
        industry_ids = []
        for index, value in enumerate(raw):
            try:
                industry_id = int(value)
            except (TypeError, ValueError):
                raise bad_request(f"industryIds[{index}] 必须是整数")
            if industry_id < 1:
                raise bad_request(f"industryIds[{index}] 无效")
            if industry_id not in industry_ids:
                industry_ids.append(industry_id)
        result["industryIds"] = industry_ids
    return result


def _optional_url(value, field, required=False):
    value = _text(value, field, 2048, required)
    if value:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise bad_request(f"{field} 必须是 http(s) URL")
    return value


def _assert_owned_files(cur, user_id: int, file_ids: list[int]):
    if not file_ids:
        return
    cur.execute("SELECT id FROM file_object WHERE created_by=%s AND status='active' AND id = ANY(%s)", (user_id, file_ids))
    if {int(row["id"]) for row in cur.fetchall()} != set(file_ids):
        raise bad_request("媒体文件不存在、已删除或不属于当前用户")


def sync_content(cur, achievement_id: int, user_id: int, content: dict):
    if "tags" in content:
        cur.execute("DELETE FROM achievement_tag_relation WHERE achievement_id=%s", (achievement_id,))
        for sort_order, tag_name in enumerate(content["tags"]):
            # 对英文大小写归一，中文保持原值；名称是展示文本，code 是稳定去重键。
            code = tag_name.casefold()
            cur.execute(
                """INSERT INTO achievement_tag (code,name) VALUES (%s,%s)
                   ON CONFLICT (code) DO UPDATE SET code=EXCLUDED.code
                   RETURNING id""",
                (code, tag_name),
            )
            tag_id = cur.fetchone()["id"]
            cur.execute(
                "INSERT INTO achievement_tag_relation (achievement_id,tag_id,sort_order) VALUES (%s,%s,%s)",
                (achievement_id, tag_id, sort_order),
            )
    if "sections" in content:
        cur.execute("DELETE FROM achievement_section WHERE achievement_id=%s", (achievement_id,))
        for item in content["sections"]:
            cur.execute("INSERT INTO achievement_section (achievement_id,section_code,title,content,sort_order) VALUES (%s,%s,%s,%s,%s)", (achievement_id, item["code"], item["title"], item["content"], item["sort"]))
    if "patents" in content:
        cur.execute("DELETE FROM achievement_patent WHERE achievement_id=%s", (achievement_id,))
        for item in content["patents"]:
            cur.execute("INSERT INTO achievement_patent (achievement_id,patent_no,patent_title,is_primary,external_url,sort_order) VALUES (%s,%s,%s,%s,%s,%s)", (achievement_id, item["no"], item["title"], item["primary"], item["url"], item["sort"]))
    if "links" in content:
        cur.execute("DELETE FROM achievement_link WHERE achievement_id=%s", (achievement_id,))
        for item in content["links"]:
            cur.execute("INSERT INTO achievement_link (achievement_id,link_type,label,url,sort_order) VALUES (%s,%s,%s,%s,%s)", (achievement_id, item["type"], item["label"], item["url"], item["sort"]))
    if "media" in content:
        _assert_owned_files(cur, user_id, [item["file_id"] for item in content["media"]])
        cur.execute("DELETE FROM achievement_media WHERE achievement_id=%s", (achievement_id,))
        for item in content["media"]:
            cur.execute("INSERT INTO achievement_media (achievement_id,file_id,media_role,sort_order,caption,alt_text) VALUES (%s,%s,%s,%s,%s,%s)", (achievement_id, item["file_id"], item["role"], item["sort"], item["caption"], item["alt"]))
    if "industryIds" in content:
        industry_ids = content["industryIds"]
        if industry_ids:
            cur.execute(
                "SELECT id FROM industry WHERE enabled AND id = ANY(%s)",
                (industry_ids,),
            )
            if {int(row["id"]) for row in cur.fetchall()} != set(industry_ids):
                raise bad_request("industryIds 包含不存在或停用的产业")
        cur.execute("DELETE FROM achievement_industry WHERE achievement_id=%s", (achievement_id,))
        for sort_order, industry_id in enumerate(industry_ids):
            cur.execute(
                "INSERT INTO achievement_industry (achievement_id,industry_id,sort_order) VALUES (%s,%s,%s)",
                (achievement_id, industry_id, sort_order),
            )


def load_content(cur, achievement_id: int) -> dict:
    cur.execute(
        """SELECT t.name FROM achievement_tag_relation atr
           JOIN achievement_tag t ON t.id=atr.tag_id AND t.enabled
           WHERE atr.achievement_id=%s ORDER BY atr.sort_order,atr.id""",
        (achievement_id,),
    )
    tags = [row["name"] for row in cur.fetchall()]
    cur.execute("SELECT section_code,title,content,sort_order FROM achievement_section WHERE achievement_id=%s ORDER BY sort_order,id", (achievement_id,))
    sections = [{"code": r["section_code"], "title": r["title"], "content": r["content"], "sortOrder": r["sort_order"]} for r in cur.fetchall()]
    cur.execute("SELECT patent_no,patent_title,is_primary,external_url,sort_order FROM achievement_patent WHERE achievement_id=%s ORDER BY sort_order,id", (achievement_id,))
    patents = [{"patentNo": r["patent_no"], "title": r["patent_title"], "isPrimary": r["is_primary"], "externalUrl": r["external_url"], "sortOrder": r["sort_order"], "internalDetailAvailable": supports_internal_patent_lookup(r["patent_no"])} for r in cur.fetchall()]
    cur.execute("SELECT link_type,label,url,sort_order FROM achievement_link WHERE achievement_id=%s ORDER BY sort_order,id", (achievement_id,))
    links = [{"type": r["link_type"], "label": r["label"], "url": r["url"], "sortOrder": r["sort_order"]} for r in cur.fetchall()]
    cur.execute("SELECT am.file_id,am.media_role,am.sort_order,am.caption,am.alt_text,fo.original_name,fo.mime_type,fo.size_bytes FROM achievement_media am JOIN file_object fo ON fo.id=am.file_id AND fo.status='active' WHERE am.achievement_id=%s ORDER BY am.sort_order,am.id", (achievement_id,))
    base = settings.MEDIA_BASE_URL.rstrip("/")
    media = [{"fileId": r["file_id"], "role": r["media_role"], "sortOrder": r["sort_order"], "caption": r["caption"], "altText": r["alt_text"], "name": r["original_name"], "mimeType": r["mime_type"], "sizeBytes": r["size_bytes"], "url": f"{base}/{r['file_id']}"} for r in cur.fetchall()]
    cur.execute(
        """SELECT i.id,i.code,i.name,i.parent_id,ai.sort_order
           FROM achievement_industry ai JOIN industry i ON i.id=ai.industry_id AND i.enabled
           WHERE ai.achievement_id=%s ORDER BY ai.sort_order,ai.id""",
        (achievement_id,),
    )
    industries = [
        {"id": row["id"], "code": row["code"], "name": row["name"], "parentId": row["parent_id"], "sortOrder": row["sort_order"]}
        for row in cur.fetchall()
    ]
    return {"tags": tags, "sections": sections, "patents": patents, "links": links, "media": media, "industries": industries}
