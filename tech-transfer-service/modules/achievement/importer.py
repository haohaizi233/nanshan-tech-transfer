"""PPT/PDF 成果资料导入：只抽取并写入 staging，绝不自动发布。"""
from __future__ import annotations

import json
import re
from pathlib import Path

from core.errors import BizError, bad_request
from db import get_cursor


_IMAGE_MIME_BY_EXTENSION = {
    "png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
    "webp": "image/webp", "gif": "image/gif",
}


def _pptx_images(slide, source_page_or_slide: str) -> list[dict]:
    """提取可由人工审核的演示稿图片；不把图片二进制写入 staging JSON。"""
    candidates = []
    for index, shape in enumerate(slide.shapes, 1):
        image = getattr(shape, "image", None)
        if image is None:
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
            try:
                file = uploader(int(created_by), image["filename"], image["mimeType"], image["data"])
            except BizError as error:
                warnings.append({"filename": image["filename"], "message": error.message})
                continue
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
    return uploaded_file_ids


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
                "images": _pptx_images(slide, source_page_or_slide),
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
    records = []
    for item in pages:
        if not item["text"].strip() and not item.get("images"):
            continue
        record = _normalize_page(item)
        record["images"] = item.get("images", [])
        records.append(record)
    return records


_LABEL_RE = re.compile(r"^\s*([^:：]{1,32})\s*[:：]\s*(.*)$")
_PATENT_RE = re.compile(r"(?i)(?:CN|ZL)\s*\d{6,16}(?:\.\d+)?")

# 常见高校 PPT/PDF 模板使用的字段名。无法识别的字段不臆造主表列，保留为动态区块。
_FIELD_ALIASES = {
    "成果名称": "title", "中文名称": "title", "项目名称": "title",
    "英文名称": "titleEn", "英文名": "titleEn",
    "成果简介": "techIntro", "技术简介": "techIntro", "项目简介": "techIntro", "简介": "techIntro",
}
_SECTION_ALIASES = {
    "技术创新点": ("innovation", "技术创新点"), "创新点": ("innovation", "技术创新点"),
    "技术成熟度说明": ("maturity_detail", "技术成熟度说明"), "成熟度说明": ("maturity_detail", "技术成熟度说明"),
    "项目支持": ("project_support", "项目支持"), "可应用领域": ("application", "可应用领域"),
    "应用领域": ("application", "可应用领域"), "技术问题": ("tech_problem", "技术问题"),
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


def _normalize_page(page: dict) -> dict:
    lines = [line.strip() for line in page["text"].splitlines() if line.strip()]
    values: dict[str, list[str]] = {}
    sections: list[dict] = []
    patent_text: list[str] = []
    fallback: list[str] = []
    current: tuple[str, object] | None = None

    for line in lines:
        matched = _LABEL_RE.match(line)
        if matched:
            label, content = _clean_label(matched.group(1)), matched.group(2).strip()
            if label in _FIELD_ALIASES:
                key = _FIELD_ALIASES[label]
                values.setdefault(key, []).append(content)
                current = ("field", key)
                continue
            if label in _SECTION_ALIASES:
                code, display_title = _SECTION_ALIASES[label]
                sections.append({"code": code, "title": display_title, "content": content, "sortOrder": len(sections)})
                current = ("section", len(sections) - 1)
                continue
            if label in _PATENT_LABELS:
                patent_text.append(content)
                current = ("patent", None)
                continue
        if current and current[0] == "field":
            values[current[1]].append(line)
        elif current and current[0] == "section":
            index = int(current[1])
            sections[index]["content"] = "\n".join(filter(None, [sections[index]["content"], line]))
        elif current and current[0] == "patent":
            patent_text.append(line)
        else:
            fallback.append(line)

    title = "\n".join(values.get("title", [])).strip() or (fallback.pop(0) if fallback else "")
    description = "\n".join(values.get("techIntro", [])).strip() or "\n".join(fallback).strip()
    errors = []
    if not title:
        errors.append({"field": "title", "message": "未识别到标题"})
    if len(title) > 200:
        errors.append({"field": "title", "message": "标题超过 200 字符"})
    normalized = {"title": title[:200], "techIntro": description[:5000], "sections": [item for item in sections if item["content"].strip()]}
    title_en = "\n".join(values.get("titleEn", [])).strip()
    if title_en:
        normalized["titleEn"] = title_en[:200]
    patents = _patents_from_text("\n".join(patent_text))
    if patents:
        normalized["patents"] = patents
    return {"sourcePageOrSlide": page["sourcePageOrSlide"], "raw": {"text": page["text"]}, "normalized": normalized, "errors": errors}


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
            """SELECT i.id,i.status,i.normalized_data,i.validation_errors,b.source_org_name
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
