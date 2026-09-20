"""PPT/PDF 成果资料导入：只抽取并写入 staging，绝不自动发布。"""
from __future__ import annotations

import gc
import json
import re
from pathlib import Path

from core.errors import BizError, bad_request
from db import get_cursor
from modules.audit.service import record as audit_record
from modules.achievement.extract import (
    FIELD_ALIASES,
    LINK_ALIASES,
    append_link,
    assign_field,
    harvest_fields_from_text,
    looks_like_title,
    parse_labeled_line,
    split_names,
)


_IMAGE_MIME_BY_EXTENSION = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}


def _is_full_slide_background(shape, slide_width: int, slide_height: int) -> bool:
    """识别铺满演示稿画布的背景/装饰图，避免进入文件库。"""
    if not slide_width or not slide_height:
        return False
    horizontal_padding = slide_width * 0.06
    vertical_padding = slide_height * 0.06
    return (
        getattr(shape, "width", 0) >= slide_width * 0.9
        and getattr(shape, "height", 0) >= slide_height * 0.9
        and getattr(shape, "left", slide_width) <= horizontal_padding
        and getattr(shape, "top", slide_height) <= vertical_padding
    )


def _pptx_images(slide, source_page_or_slide: str, slide_width: int, slide_height: int) -> list[dict]:
    """提取可由人工审核的演示稿图片；不把图片二进制写入 staging JSON。"""
    candidates = []
    for index, shape in enumerate(slide.shapes, 1):
        image = getattr(shape, "image", None)
        if image is None or _is_full_slide_background(shape, slide_width, slide_height):
            continue
        extension = (getattr(image, "ext", "") or "").lower()
        mime_type = _IMAGE_MIME_BY_EXTENSION.get(extension)
        blob = getattr(image, "blob", b"")
        if not mime_type or not blob:
            continue
        candidates.append({
            "filename": f"{source_page_or_slide}-image-{index}.{extension}",
            "mimeType": mime_type,
            "data": blob,
        })
    return candidates


def _pdf_images(page, source_page_or_slide: str) -> list[dict]:
    """pypdf 提供的嵌入图片统一转为候选媒体。"""
    candidates = []
    for index, image in enumerate(getattr(page, "images", []) or [], 1):
        filename = str(getattr(image, "name", f"image-{index}.bin"))
        extension = Path(filename).suffix.lower().lstrip(".")
        mime_type = _IMAGE_MIME_BY_EXTENSION.get(extension)
        data = getattr(image, "data", b"")
        if not mime_type or not data:
            continue
        candidates.append({
            "filename": f"{source_page_or_slide}-image-{index}.{extension}",
            "mimeType": mime_type,
            "data": data,
        })
    return candidates


def _media_payload_from_uploads(uploaded_files: list[dict]) -> list[dict]:
    """把已落到统一文件库的候选图转换为成果媒体关系。"""
    return [
        {"fileId": int(file["id"]), "role": "cover" if index == 0 else "gallery", "sortOrder": index}
        for index, file in enumerate(uploaded_files)
    ]


def upload_candidate_media(records: list[dict], created_by: int, uploader) -> list[int]:
    """上传导入图片候选；单张不合规则保留正文并写入审核提示。"""
    uploaded_file_ids: list[int] = []
    for record in records:
        uploaded: list[dict] = []
        raw_images: list[dict] = []
        warnings: list[dict] = []
        for image in record.get("images", []):
            blob = image.get("data")
            try:
                file = uploader(int(created_by), image["filename"], image["mimeType"], blob)
            except BizError as error:
                warnings.append({"filename": image["filename"], "message": error.message})
                continue
            finally:
                # 释放图片二进制：上传/校验完成后立即丢弃引用，避免整批图片
                # 候选在内存中堆积导致大文档导入 OOM。
                image["data"] = None
                del blob
            uploaded.append(file)
            uploaded_file_ids.append(int(file["id"]))
            raw_images.append(
                {key: image[key] for key in ("filename", "mimeType")}
                | {"fileId": int(file["id"]), "width": file.get("width"), "height": file.get("height")}
            )
        if uploaded:
            record["normalized"]["media"] = _media_payload_from_uploads(uploaded)
            record["raw"]["images"] = raw_images
        if warnings:
            record["raw"]["imageUploadWarnings"] = warnings
        # 单条记录处理完毕：清空候选图片列表，仅保留已上传的 fileId 元数据。
        record["images"] = []
        gc.collect()
    return uploaded_file_ids


_TEMPLATE_PLACEHOLDERS = re.compile(
    r"(?:单击|双击|点击|单击此处|双击此处|点击此处|在此处|请输入|请添加|添加标题|添加文本|添加内容|"
    r"Click\s+to\s+add|Double\s+click\s+to\s+add|Enter\s+your|Placeholder|占位符|"
    r"输入文字|输入标题|输入内容|添加备注|Add\s+title|Add\s+text)",
    re.IGNORECASE,
)
_CONTRIBUTOR_HEADINGS = {
    "成果完成人", "完成人", "发明人介绍", "团队成员介绍", "负责人介绍",
    "团队简介", "项目牵头人简介", "项目联系人及联系方式",
}
_CONTRIBUTOR_CONTACT_HINTS = ("联系邮箱", "联系方式", "联系电话", "邮箱", "电话", "Email", "E-mail")
_PATENT_PAGE_HINTS = ("专利号", "专利", "知识产权", "扫码查看", "专利公布公告")
_NUMBERED_LABEL_PREFIX = re.compile(r"^\s*(?:\d+|[一二三四五六七八九十]+)[\s、.．)）-]*")


def _classify_page(page: dict) -> str:
    """判断页面类型：template（模板占位页）/ patent（专利页）/ contributor（完成人页）/ project（项目页）。

    A类第一页 = project：标题 + 简介 + 图片 + 右侧小模块。
    A类第二页及之后 = contributor：头像 + 联系方式 + 右侧简介，一个成果可有多页完成人。
    B类 = template：含"单击添加标题"等占位文本，直接跳过。
    C类 = patent：含专利号 + 二维码/扫码说明 + 右侧技术模块。
    """
    text = page.get("text") or ""
    stripped = text.strip()
    if not stripped and not page.get("images"):
        return "empty"
    if _TEMPLATE_PLACEHOLDERS.search(stripped) and len(stripped) < 120:
        return "template"
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    has_patent_no = bool(_PATENT_RE.search(text))
    has_patent_hint = any(hint in text for hint in _PATENT_PAGE_HINTS)
    if has_patent_no and has_patent_hint:
        return "patent"
    first_lines = "\n".join(lines[:5])
    normalized_first_lines = _NUMBERED_LABEL_PREFIX.sub("", first_lines)
    is_contributor_heading = any(heading in normalized_first_lines for heading in _CONTRIBUTOR_HEADINGS)
    has_contact = (
        any(hint in text for hint in _CONTRIBUTOR_CONTACT_HINTS)
        or bool(re.search(r"(?<!\d)1[3-9]\d{9}(?!\d)", text))
        or bool(re.search(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}", text))
    )
    if is_contributor_heading and has_contact:
        return "contributor"
    if is_contributor_heading and len(lines) <= 12 and has_contact:
        return "contributor"
    return "project"


def _normalize_contributor_page(page: dict) -> dict:
    """从完成人页提取姓名、联系方式、头像，返回 inventorRefs 级别的数据。"""
    lines = [line.strip() for line in (page.get("text") or "").splitlines() if line.strip()]
    inventor = {"name": "", "sortOrder": 0}
    extra = {}
    pending = None
    bio_lines = []
    for line in lines:
        label, content = parse_labeled_line(line)
        if label and label in FIELD_ALIASES:
            key = FIELD_ALIASES[label]
            if key == "contactName":
                inventor["name"] = content or inventor["name"]
                pending = None
                continue
            if key in ("contactPhone", "contactEmail", "contactWechat", "contactTitle"):
                if content:
                    extra[key] = content
                    pending = None
                else:
                    pending = key
                continue
            if key == "techIntro":
                if content:
                    bio_lines.append(content)
                pending = None
                continue
        if pending:
            extra[pending] = line
            pending = None
            continue
        if not inventor["name"] and looks_like_title(line) and len(line) <= 20:
            inventor["name"] = line
            continue
        bio_lines.append(line)
    if not inventor["name"]:
        for line in lines:
            if looks_like_title(line) and len(line) <= 20:
                inventor["name"] = line
                break
    if extra.get("contactPhone"):
        inventor["phone"] = extra["contactPhone"]
    if extra.get("contactEmail"):
        inventor["email"] = extra["contactEmail"]
    if extra.get("contactWechat"):
        inventor["homepageUrl"] = extra["contactWechat"]
    if extra.get("contactTitle"):
        inventor["title"] = extra["contactTitle"]
    bio = "\n".join(bio_lines).strip()
    if bio:
        inventor["bio"] = bio[:10000]
    images = page.get("images") or []
    if images:
        inventor["avatarImageIndex"] = 0
    return {
        "sourcePageOrSlide": page["sourcePageOrSlide"],
        "pageType": "contributor",
        "inventor": inventor,
        "images": images,
        "raw": {"text": page.get("text") or "", "pageType": "contributor"},
    }


def extract_document_records(path: str | Path) -> list[dict]:
    source = Path(path)
    suffix = source.suffix.lower()
    if suffix == ".pptx":
        from pptx import Presentation
        deck = Presentation(source)
        pages = []
        for index, slide in enumerate(deck.slides, 1):
            text = "\n".join(shape.text for shape in slide.shapes if getattr(shape, "has_text_frame", False) and shape.text.strip())
            source_page_or_slide = f"slide-{index}"
            pages.append({
                "sourcePageOrSlide": source_page_or_slide,
                "text": text,
                "images": _pptx_images(slide, source_page_or_slide, deck.slide_width, deck.slide_height),
            })
    elif suffix == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(source))
        pages = []
        for index, page in enumerate(reader.pages, 1):
            source_page_or_slide = f"page-{index}"
            pages.append({
                "sourcePageOrSlide": source_page_or_slide,
                "text": page.extract_text() or "",
                "images": _pdf_images(page, source_page_or_slide),
            })
    else:
        raise bad_request("只支持 .pptx 或 .pdf 导入")

    classified = []
    for item in pages:
        page_type = _classify_page(item)
        if page_type in ("empty", "template"):
            continue
        classified.append((page_type, item))

    records = []
    pending_contributors = []
    pending_contributor_images = []

    def flush_project(project_item, contributors, contributor_images):
        record = _normalize_page(project_item)
        record["images"] = list(project_item.get("images") or [])
        record["raw"]["pageType"] = "project"
        merged_inventors = list(record["normalized"].get("inventorRefs") or [])
        existing_names = {inv.get("name") for inv in merged_inventors}
        for contrib in contributors:
            inv = dict(contrib["inventor"])
            inv["sortOrder"] = len(merged_inventors)
            if inv.get("name") and inv["name"] not in existing_names:
                merged_inventors.append(inv)
                existing_names.add(inv["name"])
        if merged_inventors:
            record["normalized"]["inventorRefs"] = merged_inventors
        record["images"].extend(contributor_images)
        if contributors:
            record["raw"]["contributorPages"] = [c["sourcePageOrSlide"] for c in contributors]
        return record

    for page_type, item in classified:
        if page_type == "contributor":
            contrib = _normalize_contributor_page(item)
            pending_contributors.append(contrib)
            pending_contributor_images.extend(contrib.get("images") or [])
            continue
        if page_type == "patent":
            if pending_contributors:
                pending_contributors = []
                pending_contributor_images = []
            record = _normalize_page(item)
            record["raw"]["pageType"] = "patent"
            record["images"] = item.get("images") or []
            records.append(record)
            continue
        if pending_contributors or records:
            if records and records[-1]["raw"].get("pageType") == "project":
                pass
        record = _normalize_page(item)
        record["raw"]["pageType"] = "project"
        record["images"] = list(item.get("images") or [])
        record["images"].extend(pending_contributor_images)
        merged_inventors = list(record["normalized"].get("inventorRefs") or [])
        existing_names = {inv.get("name") for inv in merged_inventors}
        for contrib in pending_contributors:
            inv = dict(contrib["inventor"])
            inv["sortOrder"] = len(merged_inventors)
            if inv.get("name") and inv["name"] not in existing_names:
                merged_inventors.append(inv)
                existing_names.add(inv["name"])
        if merged_inventors:
            record["normalized"]["inventorRefs"] = merged_inventors
        if pending_contributors:
            record["raw"]["contributorPages"] = [c["sourcePageOrSlide"] for c in pending_contributors]
        records.append(record)
        pending_contributors = []
        pending_contributor_images = []

    if pending_contributors:
        if records and records[-1]["raw"].get("pageType") == "project":
            record = records[-1]
            merged_inventors = list(record["normalized"].get("inventorRefs") or [])
            existing_names = {inv.get("name") for inv in merged_inventors}
            for contrib in pending_contributors:
                inv = dict(contrib["inventor"])
                inv["sortOrder"] = len(merged_inventors)
                if inv.get("name") and inv["name"] not in existing_names:
                    merged_inventors.append(inv)
                    existing_names.add(inv["name"])
            if merged_inventors:
                record["normalized"]["inventorRefs"] = merged_inventors
            record["images"].extend(pending_contributor_images)
            record["raw"].setdefault("contributorPages", []).extend(
                c["sourcePageOrSlide"] for c in pending_contributors
            )
        else:
            for contrib in pending_contributors:
                record = _normalize_page({"sourcePageOrSlide": contrib["sourcePageOrSlide"], "text": contrib["raw"]["text"]})
                record["raw"]["pageType"] = "contributor"
                record["normalized"]["inventorRefs"] = [contrib["inventor"]]
                record["images"] = list(contrib.get("images") or [])
                if not record["normalized"].get("title"):
                    record["normalized"]["title"] = contrib["inventor"].get("name") or "未命名完成人"
                records.append(record)
    return records


_PATENT_RE = re.compile(r"(?i)(?:CN|ZL)\s*\d{6,16}(?:\.\d+)?")
_NON_TITLE_HEADINGS = {
    "团队介绍", "团队简介", "联系方式", "相关成果发表", "成果简介", "技术简介",
    "项目简介", "项目介绍", "项目牵头人简介", "项目联系人及联系方式", "成果完成人",
    "参考文献", "目录", "附录", "致谢",
}
_TITLE_KEYWORDS = ("技术", "平台", "系统", "方法", "装置", "材料", "产品", "算法", "模型", "设备", "工艺", "项目", "方案")
_TEMPLATE_CONTENT_HINTS = (
    "成果简介（包括但不限于", "成果照片", "（图片/视频", "图片/视频 1920", "字数800字以内",
    "项目简介（", "项目代表性图片", "技术创新点(", "团队整体情况", "项目联系人",
    "商业价值", "商业模式", "技术成熟度与项目进展", "可应用领域（",
)


def _is_template_content_hint(line: str) -> bool:
    """排除成果模板的说明文案，不能把它当正文或标题。"""
    return any(hint in (line or "") for hint in _TEMPLATE_CONTENT_HINTS)


def _canonical_import_label(label: str | None) -> str | None:
    """模板会写“1 项目名称：”，导入时应识别为标准字段名。"""
    if not label:
        return label
    candidate = _NUMBERED_LABEL_PREFIX.sub("", label).strip()
    return candidate if candidate in _FIELD_ALIASES else label

# 常见高校 PPT/PDF 模板使用的字段名。无法识别的字段不臆造主表列，保留为动态区块。
_FIELD_ALIASES = FIELD_ALIASES
_SECTION_ALIASES = {
    "技术创新点": ("innovation", "技术创新点"), "创新点": ("innovation", "技术创新点"),
    "技术成熟度说明": ("maturity_detail", "技术成熟度说明"), "成熟度说明": ("maturity_detail", "技术成熟度说明"),
    "项目支持": ("project_support", "项目支持"),
    "技术问题": ("tech_problem", "技术问题"),
    "技术手段": ("tech_method", "技术手段"), "技术方法": ("tech_method", "技术手段"),
    "技术功效": ("tech_effect", "技术功效"), "技术效果": ("tech_effect", "技术功效"),
    "市场前景": ("market_prospect", "市场前景"), "产业化情况": ("industrialization", "产业化情况"),
    "团队介绍": ("team_intro", "团队介绍"), "技术路线": ("technical_route", "技术路线"),
    "商业化": ("commercialization", "商业化情况"),
}
_PATENT_LABELS = {"专利", "专利号", "相关专利", "知识产权"}


def _clean_label(label: str) -> str:
    return re.sub(r"[\s（）()【】\[\]-]", "", label or "")


def _patents_from_text(text: str) -> list[dict]:
    seen: set[str] = set()
    records = []
    for index, matched in enumerate(_PATENT_RE.findall(text or "")):
        patent_no = re.sub(r"\s+", "", matched).upper()
        if patent_no not in seen:
            seen.add(patent_no)
            records.append({"patentNo": patent_no, "isPrimary": index == 0, "sortOrder": len(records)})
    return records


def _select_fallback_title(lines: list[str]) -> tuple[str, int | None]:
    """从无字段名的页面文本中选成果标题，排除团队/目录等展示性标题。"""
    candidates = []
    for index, line in enumerate(lines):
        text = line.strip()
        if not looks_like_title(text) or text in _NON_TITLE_HEADINGS:
            continue
        score = 100 - index * 2
        if any(keyword in text for keyword in _TITLE_KEYWORDS):
            score += 35
        if re.fullmatch(r"[A-Za-z0-9 .,&()\-]+", text):
            score -= 20
        candidates.append((score, -index, text, index))
    if candidates:
        _, _, title, index = max(candidates)
        return title, index
    return (lines[0], 0) if lines else ("", None)


def _normalize_page(page: dict) -> dict:
    lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
    values: dict[str, list[str]] = {}
    extra: dict = {}
    sections: list[dict] = []
    patent_text: list[str] = []
    fallback: list[str] = []
    current: tuple[str, object] | None = None

    for line in lines:
        if _is_template_content_hint(line):
            current = None
            continue
        if line in _SECTION_ALIASES:
            code, display_title = _SECTION_ALIASES[line]
            sections.append({"code": code, "title": display_title, "content": "", "sortOrder": len(sections)})
            current = ("section", len(sections) - 1)
            continue

        label, content = parse_labeled_line(line)
        label = _canonical_import_label(label)
        if label:
            if label in _FIELD_ALIASES:
                key = _FIELD_ALIASES[label]
                if key in {"title", "titleEn", "techIntro"}:
                    values.setdefault(key, []).append(content)
                    current = None if content and key in {"title", "titleEn"} else ("field", key)
                else:
                    if content:
                        assign_field(extra, key, content)
                        current = None
                    else:
                        current = ("named", key)
                continue
            if label in _SECTION_ALIASES:
                code, display_title = _SECTION_ALIASES[label]
                sections.append({"code": code, "title": display_title, "content": content, "sortOrder": len(sections)})
                current = ("section", len(sections) - 1)
                continue
            if label in LINK_ALIASES:
                link_type, display = LINK_ALIASES[label]
                if content:
                    append_link(extra, display, content, link_type)
                    current = None
                else:
                    current = ("link", label)
                continue
            if _clean_label(label) in _PATENT_LABELS or label in _PATENT_LABELS:
                patent_text.append(content)
                current = ("patent", None)
                continue
            # 空字段后的下一行若已有自己的标签，不能继续吞进前一个字段。
            # 高校模板常见“成果名称：”留空、紧接“成果简介（……）：”的结构。
            current = None
            if not _is_template_content_hint(line):
                fallback.append(line)
            continue
        if current and current[0] == "field":
            values[current[1]].append(line)
        elif current and current[0] == "named":
            assign_field(extra, str(current[1]), line)
            current = None
        elif current and current[0] == "link":
            link_type, display = LINK_ALIASES[str(current[1])]
            append_link(extra, display, line, link_type)
            current = None
        elif current and current[0] == "section":
            # 一些模板以“团队介绍”开头，却在后面另起真正的成果标题。
            # 带成果关键词的短行不应继续并入团队说明区块。
            if looks_like_title(line) and any(keyword in line for keyword in _TITLE_KEYWORDS):
                fallback.append(line)
                current = None
            else:
                index = int(current[1])
                sections[index]["content"] = "\n".join(filter(None, [sections[index]["content"], line]))
        elif current and current[0] == "patent":
            patent_text.append(line)
        else:
            if not _is_template_content_hint(line):
                fallback.append(line)

    title = "\n".join(values.get("title", [])).strip()
    if not title:
        title, title_index = _select_fallback_title(fallback)
        if title_index is not None:
            fallback.pop(title_index)
    description = "\n".join(values.get("techIntro", [])).strip() or "\n".join(fallback).strip()
    harvested = harvest_fields_from_text(description, extra)
    description = str(harvested.get("techIntro") or "").strip()
    errors = []
    normalization_warnings = []
    if not title:
        errors.append({"field": "title", "message": "未识别到标题"})
    if len(title) > 200:
        # 演示稿中常把整段团队/成果介绍放在首个文本框。保留原始内容，
        # 以数据库可承载的候选标题进入人工审核，而不是让整页资料丢失。
        normalization_warnings.append({
            "field": "title",
            "message": "原始标题超过 200 字符，已截断为候选标题，请人工确认",
        })
    normalized = {"title": title[:200], "techIntro": description[:5000], "sections": [item for item in sections if item["content"].strip()]}
    for key in (
        "titleEn", "sourceOrgName", "techRoute", "contactName", "contactTitle",
        "contactPhone", "contactEmail", "contactWechat", "maturityLevel", "pricingMode",
    ):
        value = harvested.get(key)
        if value:
            normalized[key] = value
    if harvested.get("inventorRefs"):
        normalized["inventorRefs"] = harvested["inventorRefs"]
    if harvested.get("applicationFields"):
        fields = harvested["applicationFields"]
        if all(len(item) <= 40 for item in fields):
            normalized["applicationFields"] = fields[:20]
        else:
            sections.append({
                "code": "application",
                "title": "可应用领域",
                "content": "、".join(fields),
                "sortOrder": len(sections),
            })
            normalized["sections"] = [item for item in sections if item["content"].strip()]
    if harvested.get("links"):
        normalized["links"] = harvested["links"]
    title_en = "\n".join(values.get("titleEn", [])).strip()
    if title_en:
        normalized["titleEn"] = title_en[:200]
    patents = _patents_from_text("\n".join(patent_text))
    if patents:
        normalized["patents"] = patents
    raw = {"text": page["text"]}
    if len(title) > 200:
        raw["sourceTitle"] = title
    if normalization_warnings:
        raw["normalizationWarnings"] = normalization_warnings
    return {"sourcePageOrSlide": page["sourcePageOrSlide"], "raw": raw, "normalized": normalized, "errors": errors}


def stage_document(path: str | Path, created_by: int | None, source_org_name: str | None = None) -> dict:
    source = Path(path)
    if not source.is_file():
        raise bad_request("导入文件不存在")
    records = extract_document_records(source)
    candidates = [image for record in records for image in record.get("images", [])]
    if candidates and not created_by:
        raise bad_request("含图片的导入必须提供 created_by，以便安全归属媒体文件")

    uploaded_file_ids: list[int] = []
    try:
        if candidates:
            from modules.file.service import create_uploaded_file
            uploaded_file_ids = upload_candidate_media(records, int(created_by), create_uploaded_file)
        with get_cursor(commit=True) as cur:
            cur.execute("INSERT INTO achievement_import_batch (source_filename,source_org_name,total_count,created_by) VALUES (%s,%s,%s,%s) RETURNING id", (source.name, source_org_name, len(records), created_by))
            batch_id = int(cur.fetchone()["id"])
            for record in records:
                status = "failed" if record["errors"] else "staged"
                cur.execute("INSERT INTO achievement_import_item (batch_id,source_page_or_slide,raw_data,normalized_data,validation_errors,status) VALUES (%s,%s,%s::jsonb,%s::jsonb,%s::jsonb,%s)", (batch_id, record["sourcePageOrSlide"], json.dumps(record["raw"], ensure_ascii=False), json.dumps(record["normalized"], ensure_ascii=False), json.dumps(record["errors"], ensure_ascii=False), status))
            cur.execute("UPDATE achievement_import_batch SET failed_count=%s WHERE id=%s", (sum(bool(r["errors"]) for r in records), batch_id))
    except Exception:
        if uploaded_file_ids and created_by:
            from modules.file.service import delete_uploaded_file
            for file_id in uploaded_file_ids:
                try:
                    delete_uploaded_file(file_id, int(created_by))
                except Exception:
                    pass
        raise
    return {"batchId": batch_id, "total": len(records), "staged": sum(not r["errors"] for r in records), "failed": sum(bool(r["errors"]) for r in records)}


def list_import_batches(page: int = 1, page_size: int = 20) -> dict:
    page, page_size = max(1, int(page)), max(1, min(100, int(page_size)))
    with get_cursor() as cur:
        cur.execute("SELECT COUNT(*) AS total FROM achievement_import_batch")
        total = int(cur.fetchone()["total"])
        cur.execute("SELECT id,source_filename,source_org_name,status,total_count,success_count,failed_count,created_at,completed_at FROM achievement_import_batch ORDER BY id DESC LIMIT %s OFFSET %s", (page_size, (page - 1) * page_size))
        rows = cur.fetchall()
    return {"page": page, "pageSize": page_size, "total": total, "list": [_batch_dto(row) for row in rows]}


def get_import_batch(batch_id: int) -> dict | None:
    with get_cursor() as cur:
        cur.execute("SELECT id,source_filename,source_org_name,status,total_count,success_count,failed_count,created_at,completed_at FROM achievement_import_batch WHERE id=%s", (batch_id,))
        batch = cur.fetchone()
        if not batch:
            return None
        cur.execute("SELECT id,source_page_or_slide,raw_data,normalized_data,validation_errors,status,achievement_id,created_at,updated_at FROM achievement_import_item WHERE batch_id=%s ORDER BY id", (batch_id,))
        items = cur.fetchall()
    data = _batch_dto(batch)
    data["items"] = [{"id": row["id"], "sourcePageOrSlide": row["source_page_or_slide"], "raw": row["raw_data"], "normalized": row["normalized_data"], "validationErrors": row["validation_errors"], "status": row["status"], "achievementId": row["achievement_id"], "createdAt": row["created_at"].isoformat() if row["created_at"] else None} for row in items]
    return data


def confirm_import_item(batch_id: int, item_id: int, actor: dict, overrides: dict | None = None, request_id=None) -> dict:
    """将一条已审核的暂存记录创建为成果草稿，绝不直接发布。"""
    overrides = overrides or {}
    with get_cursor() as cur:
        cur.execute(
            """SELECT i.id,i.status,i.normalized_data,i.validation_errors,b.source_org_name,
                       b.created_by AS imported_by_user_id
                 FROM achievement_import_item i JOIN achievement_import_batch b ON b.id=i.batch_id
                 WHERE i.id=%s AND i.batch_id=%s""",
            (item_id, batch_id),
        )
        item = cur.fetchone()
    if not item:
        raise bad_request("导入暂存记录不存在")
    if item["status"] == "imported":
        raise bad_request("该暂存记录已确认入库")
    if item["status"] != "staged" or item["validation_errors"]:
        raise bad_request("含校验错误的暂存记录不能入库，请先修正后重新导入")

    normalized = dict(item["normalized_data"] or {})
    # 只允许补充当前成果写入接口接受的字段，保留原始文本用于追溯。
    allowed = {"title", "titleEn", "achievementKind", "techIntro", "techRoute", "sourceOrgName", "maturityLevel", "pricingMode", "applicationFields", "sections", "patents", "links", "media", "inventorRefs", "contactName", "contactTitle", "contactPhone", "contactEmail", "contactWechat", "categoryId"}
    payload = {key: value for key, value in normalized.items() if key in allowed}
    payload.update({key: value for key, value in overrides.items() if key in allowed and value is not None})
    if not payload.get("sourceOrgName") and item["source_org_name"]:
        payload["sourceOrgName"] = item["source_org_name"]

    from modules.achievement.service import create_achievement
    user_id = int(actor.get("userId") or actor.get("id") or 0)
    if not user_id:
        raise bad_request("无法识别确认人")
    created = create_achievement(
        user_id,
        str(actor.get("userNo") or ""),
        payload,
        request_id=request_id,
        source_import_item_id=item_id,
        media_owner_user_id=int(item["imported_by_user_id"]) if item.get("imported_by_user_id") else None,
    )

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE achievement_import_item SET status='imported',achievement_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND batch_id=%s AND status='staged'",
            (created["id"], item_id, batch_id),
        )
        if cur.rowcount != 1:
            raise bad_request("导入状态已变化，请刷新后重试")
        cur.execute(
            """UPDATE achievement_import_batch SET
                   success_count=(SELECT COUNT(*) FROM achievement_import_item WHERE batch_id=%s AND status='imported'),
                   failed_count=(SELECT COUNT(*) FROM achievement_import_item WHERE batch_id=%s AND status='failed'),
                   status=CASE WHEN NOT EXISTS (SELECT 1 FROM achievement_import_item WHERE batch_id=%s AND status='staged') THEN 'completed' ELSE 'staging' END,
                   completed_at=CASE WHEN NOT EXISTS (SELECT 1 FROM achievement_import_item WHERE batch_id=%s AND status='staged') THEN CURRENT_TIMESTAMP ELSE NULL END
                 WHERE id=%s""",
            (batch_id, batch_id, batch_id, batch_id, batch_id),
        )
    return {"itemId": item_id, "achievementId": created["id"], "status": "imported", "achievement": created}


def _batch_dto(row: dict) -> dict:
    return {"id": row["id"], "sourceFilename": row["source_filename"], "sourceOrgName": row["source_org_name"], "status": row["status"], "totalCount": row["total_count"], "successCount": row["success_count"], "failedCount": row["failed_count"], "createdAt": row["created_at"].isoformat() if row["created_at"] else None, "completedAt": row["completed_at"].isoformat() if row["completed_at"] else None}


def clear_import_batches(actor: dict) -> dict:
    """清空全部导入暂存批次及其条目；已入库为草稿的成果不受影响。"""
    with get_cursor(commit=True) as cur:
        cur.execute(
            """SELECT i.id, i.batch_id, i.status, i.normalized_data
                 FROM achievement_import_item i
                 JOIN achievement_import_batch b ON b.id = i.batch_id
                WHERE i.status = 'staged'"""
        )
        staged_items = cur.fetchall()
        cur.execute("DELETE FROM achievement_import_item")
        cur.execute("DELETE FROM achievement_import_batch")
        deleted_batches = cur.rowcount
    audit_record(
        "achievement_import.clear", "achievement_import_batch",
        actor_user_id=int(actor.get("userId") or 0),
        actor_user_no=actor.get("userNo", ""),
        details={"deletedBatches": deleted_batches, "stagedItemsCleared": len(staged_items)},
    )
    return {"deletedBatches": deleted_batches, "stagedItemsCleared": len(staged_items)}


def publish_import_item(batch_id: int, item_id: int, actor: dict, overrides: dict | None = None, request_id=None) -> dict:
    """一步完成：确认暂存条目 → 提交审核 → 审核通过发布。仅限管理员一键发布。"""
    from modules.admin.service import submit_achievement_admin, review_achievement

    confirmed = confirm_import_item(batch_id, item_id, actor, overrides, request_id)
    ach_id = confirmed["achievementId"]

    with get_cursor() as cur:
        cur.execute("SELECT version FROM achievement WHERE id=%s AND deleted_at IS NULL", (ach_id,))
        row = cur.fetchone()
    if not row:
        raise bad_request("成果草稿创建失败，无法发布")
    version = row["version"]

    submit_achievement_admin(actor, ach_id, {"version": version}, request_id=request_id)

    with get_cursor() as cur:
        cur.execute("SELECT version FROM achievement WHERE id=%s AND deleted_at IS NULL", (ach_id,))
        row = cur.fetchone()
    if not row:
        raise bad_request("成果提交审核后状态异常，无法发布")
    version = row["version"]

    review_achievement(actor, ach_id, {"_action": "approve", "version": version}, request_id=request_id)

    with get_cursor(commit=True) as cur:
        cur.execute(
            "UPDATE achievement_import_item SET status='imported',achievement_id=%s,updated_at=CURRENT_TIMESTAMP WHERE id=%s AND batch_id=%s",
            (ach_id, item_id, batch_id),
        )
    return {"itemId": item_id, "achievementId": ach_id, "status": "published"}
