"""动态成果内容与文件上传的无数据库回归测试。"""
import base64
import unittest
from io import BytesIO
from pathlib import Path
import re
from tempfile import TemporaryDirectory

from PIL import Image

from core.errors import BizError, bad_request
from modules.achievement.content import parse_content_payload, supports_internal_patent_lookup
from modules.achievement.importer import _media_payload_from_uploads, _normalize_page, extract_document_records, upload_candidate_media
from modules.file.service import _image_dimensions, _validate_upload, _write_thumbnail


class ContentPayloadTests(unittest.TestCase):
    def test_parses_multiple_patents_and_ordered_sections(self):
        parsed = parse_content_payload({
            "sections": [
                {"code": "tech_problem", "title": "技术问题", "content": "要解决的问题"},
                {"code": "tech_method", "title": "技术方案", "content": "实现方案", "sortOrder": 3},
            ],
            "patents": [
                {"patentNo": "cn123", "isPrimary": True},
                {"patentNo": "CN456"},
            ],
        })
        self.assertEqual([x["code"] for x in parsed["sections"]], ["tech_problem", "tech_method"])
        self.assertEqual(parsed["patents"][0]["no"], "CN123")
        self.assertTrue(parsed["patents"][0]["primary"])

    def test_rejects_duplicate_primary_patents(self):
        with self.assertRaises(BizError):
            parse_content_payload({"patents": [
                {"patentNo": "CN1", "isPrimary": True}, {"patentNo": "CN2", "isPrimary": True},
            ]})

    def test_patent_internal_navigation_only_marks_numbers_supported_by_the_patent_module(self):
        self.assertTrue(supports_internal_patent_lookup("CN202310366203.1"))
        self.assertFalse(supports_internal_patent_lookup("内部项目编号-2026-A"))

    def test_rejects_invalid_dynamic_content_sort_orders_as_a_business_error(self):
        for payload in (
            {"sections": [{"code": "innovation", "title": "创新点", "content": "内容", "sortOrder": "bad"}]},
            {"patents": [{"patentNo": "CN1", "sortOrder": -1}]},
            {"links": [{"type": "other", "label": "链接", "url": "https://example.com", "sortOrder": True}]},
            {"media": [{"fileId": 1, "sortOrder": 10001}]},
        ):
            with self.assertRaises(BizError):
                parse_content_payload(payload)

    def test_rejects_mismatched_image_signature(self):
        with self.assertRaises(BizError):
            _validate_upload("cover.png", "image/png", b"not a png")

    def test_accepts_real_png_signature(self):
        output = BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, format="PNG")
        suffix, mime = _validate_upload("cover.png", "image/png", output.getvalue())
        self.assertEqual((suffix, mime), (".png", "image/png"))

    def test_accepts_png_when_wechat_reports_generic_or_wrong_image_mime(self):
        output = BytesIO()
        Image.new("RGB", (2, 2), "white").save(output, format="PNG")
        png = output.getvalue()
        self.assertEqual(_validate_upload("cover.png", "application/octet-stream", png), (".png", "image/png"))
        self.assertEqual(_validate_upload("cover.png", "image/jpeg", png), (".png", "image/png"))

    def test_rejects_image_with_a_valid_signature_but_corrupt_image_body(self):
        with self.assertRaises(BizError):
            _validate_upload("cover.png", "image/png", b"\x89PNG\r\n\x1a\nsmall")

    def test_rejects_png_with_a_bad_idat_checksum_as_a_client_error(self):
        broken_png = base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAF/gJ+cyfLwQAAAABJRU5ErkJggg=="
        )
        with self.assertRaises(BizError):
            _validate_upload("cover.png", "image/png", broken_png)

    def test_legacy_media_file_ids_become_real_media_relations(self):
        parsed = parse_content_payload({"mediaFileIds": [12, "18"]})
        self.assertEqual(
            parsed["media"],
            [
                {"file_id": 12, "role": "cover", "caption": None, "alt": None, "sort": 0},
                {"file_id": 18, "role": "gallery", "caption": None, "alt": None, "sort": 1},
            ],
        )
        with self.assertRaises(BizError):
            parse_content_payload({"mediaFileIds": [12], "media": [{"fileId": 12}]})

    def test_achievement_tags_are_validated_as_a_real_relation_payload(self):
        parsed = parse_content_payload({"tags": ["人工智能", "人工智能", " AI "]})
        self.assertEqual(parsed["tags"], ["人工智能", "AI"])
        with self.assertRaises(BizError):
            parse_content_payload({"tags": [1]})

    def test_reads_uploaded_image_dimensions(self):
        output = BytesIO()
        Image.new("RGB", (640, 360), "white").save(output, format="PNG")
        self.assertEqual(_image_dimensions(".png", output.getvalue()), (640, 360))

    def test_thumbnail_writer_creates_a_bounded_jpeg_derivative(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source, thumbnail = root / "source.png", root / "thumbnail.jpg"
            Image.new("RGBA", (1600, 800), (20, 70, 180, 120)).save(source, format="PNG")
            _write_thumbnail(source, thumbnail)
            with Image.open(thumbnail) as generated:
                self.assertEqual(generated.format, "JPEG")
                self.assertLessEqual(generated.width, 320)
                self.assertLessEqual(generated.height, 320)

    def test_import_normalizes_labeled_sections_and_patents(self):
        record = _normalize_page({
            "sourcePageOrSlide": "slide-3",
            "text": "高精度视觉检测技术\n成果简介：面向工业缺陷识别。\n技术创新点：多模态融合提升小样本精度。\n技术问题：解决复杂光照误检。\n专利号：CN202310366203.1；CN202411797801.5",
        })
        normalized = record["normalized"]
        self.assertEqual(normalized["title"], "高精度视觉检测技术")
        self.assertEqual(normalized["techIntro"], "面向工业缺陷识别。")
        self.assertEqual(
            [(item["code"], item["content"]) for item in normalized["sections"]],
            [("innovation", "多模态融合提升小样本精度。"), ("tech_problem", "解决复杂光照误检。")],
        )
        self.assertEqual(
            [item["patentNo"] for item in normalized["patents"]],
            ["CN202310366203.1", "CN202411797801.5"],
        )

    def test_import_confirmation_writes_source_trace_with_the_draft_insert(self):
        base = Path(__file__).parent / "modules" / "achievement"
        service_source = (base / "service.py").read_text(encoding="utf-8")
        importer_source = (base / "importer.py").read_text(encoding="utf-8")

        self.assertRegex(service_source, r"source_import_item_id:\s*int \| None = None")
        insert_sql = service_source.split("INSERT INTO achievement", 1)[1].split("RETURNING id", 1)[0]
        self.assertIn("source_import_item_id", insert_sql)
        self.assertIn("source_import_item_id=item_id", importer_source)

    def test_pptx_import_extracts_embedded_images_as_candidates(self):
        from pptx import Presentation
        from pptx.util import Inches

        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            image_path = root / "candidate.png"
            Image.new("RGB", (32, 18), "navy").save(image_path, format="PNG")
            presentation = Presentation()
            slide = presentation.slides.add_slide(presentation.slide_layouts[6])
            slide.shapes.add_textbox(Inches(1), Inches(.2), Inches(4), Inches(.5)).text_frame.text = "图像成果"
            slide.shapes.add_picture(str(image_path), Inches(1), Inches(1))
            pptx_path = root / "source.pptx"
            presentation.save(pptx_path)

            records = extract_document_records(pptx_path)

        self.assertEqual(len(records), 1)
        image = records[0]["images"][0]
        self.assertEqual(image["mimeType"], "image/png")
        self.assertEqual(image["data"][:8], b"\x89PNG\r\n\x1a\n")

    def test_pdf_import_extracts_embedded_images_as_candidates(self):
        with TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "source.pdf"
            Image.new("RGB", (30, 20), "maroon").save(source, format="PDF")
            records = extract_document_records(source)

        self.assertEqual(len(records), 1)
        image = records[0]["images"][0]
        self.assertEqual(image["mimeType"], "image/jpeg")
        self.assertEqual(image["data"][:3], b"\xff\xd8\xff")

    def test_imported_candidate_uploads_become_ordered_media_payload(self):
        media = _media_payload_from_uploads([
            {"id": 12, "name": "slide-1-image-1.png"},
            {"id": 18, "name": "slide-1-image-2.png"},
        ])
        self.assertEqual(media, [
            {"fileId": 12, "role": "cover", "sortOrder": 0},
            {"fileId": 18, "role": "gallery", "sortOrder": 1},
        ])

    def test_import_keeps_text_staged_when_one_candidate_image_is_over_limit(self):
        records = [{
            "normalized": {},
            "raw": {"text": "资料正文"},
            "images": [
                {"filename": "small.png", "mimeType": "image/png", "data": b"small"},
                {"filename": "large.png", "mimeType": "image/png", "data": b"large"},
            ],
        }]

        def uploader(_user_id, filename, _mime, _data):
            if filename == "large.png":
                raise bad_request("文件不能超过 20MB")
            return {"id": 88, "width": 32, "height": 18}

        uploaded_ids = upload_candidate_media(records, 1, uploader)

        self.assertEqual(uploaded_ids, [88])
        self.assertEqual(records[0]["normalized"]["media"], [{"fileId": 88, "role": "cover", "sortOrder": 0}])
        self.assertEqual(records[0]["raw"]["images"][0]["fileId"], 88)
        self.assertEqual(records[0]["raw"]["imageUploadWarnings"], [
            {"filename": "large.png", "message": "文件不能超过 20MB"}
        ])

    def test_admin_preview_permission_is_limited_to_staged_import_media(self):
        base = Path(__file__).parent
        service_source = (base / "modules" / "file" / "service.py").read_text(encoding="utf-8")
        route_source = (base / "routes" / "file.py").read_text(encoding="utf-8")

        self.assertIn("can_review_import_media", service_source)
        self.assertIn("achievement_import_item", service_source)
        self.assertIn("raw_data @>", service_source)
        self.assertIn("'admin' in user.get(\"roles\", [])", route_source)

    def test_content_payload_parses_deduplicated_industry_ids(self):
        parsed = parse_content_payload({"industryIds": ["4", 9, 4]})
        self.assertEqual(parsed["industryIds"], [4, 9])

    def test_content_payload_rejects_invalid_industry_ids(self):
        with self.assertRaises(BizError):
            parse_content_payload({"industryIds": [0]})


if __name__ == "__main__":
    unittest.main()
