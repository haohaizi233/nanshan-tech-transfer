"""Coverage tests for modules.achievement and modules.identity (pure unit tests, mocked DB cursor).

每条用例只依赖 MagicMock 游标，绝不连接真实数据库/网络。
"""

import json
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError

NOW = datetime(2026, 1, 1, 12, 0)

FAT = {
    # 通用列
    "id": 1,
    "user_id": 1,
    "org_id": 1,
    "content_id": 1,
    "category_id": 1,
    "name": "机构甲",
    "title": "成果标题",
    "status": "active",
    "version": 1,
    "c": 1,
    "m": 0,
    "count": 1,
    "total": 1,
    "user_no": "U001",
    "role": "admin",
    "role_code": "user",
    "code": "tech",
    "parent_id": None,
    "sort_order": 1,
    "file_id": 1,
    "created_at": NOW,
    "updated_at": NOW,
    "completed_at": NOW,
    # achievement 主表
    "owner_user_id": 1,
    "source_org_name": "来源单位",
    "certified_org_name": "认证机构",
    "category_name": "类别",
    "category_code": "cat",
    "tech_intro": "简介",
    "tech_route": "路线",
    "maturity_level": "02_lab",
    "maturity_desc": "实验室验证",
    "application_fields": '["农业"]',
    "innovation_points": '["创新"]',
    "pricing_mode": "negotiable",
    "price_min_wan": 1.0,
    "price_max_wan": 2.0,
    "view_count": 5,
    "published_at": NOW,
    "reject_reason": None,
    "title_en": "Title",
    "achievement_kind": "technology",
    "contact_name": "张三",
    "contact_title": "教授",
    "contact_phone": "13800138000",
    "contact_email": "a@b.com",
    "contact_wechat": "wx001",
    "cooperation_capacity": 2,
    "cooperation_remaining": 1,
    # 动态内容行（load_content）
    "section_code": "innovation",
    "content": "区块内容",
    "patent_no": "CN12345678A",
    "patent_title": "专利名",
    "is_primary": True,
    "external_url": "https://p.example.com",
    "link_type": "official_site",
    "label": "官网",
    "url": "https://o.example.com",
    "media_role": "cover",
    "caption": "封面",
    "alt_text": "alt",
    "original_name": "a.png",
    "mime_type": "image/png",
    "size_bytes": 100,
    # identity 行
    "display_name": "张三",
    "user_type": "person",
    "phone": "13800138000",
    "email": "a@b.com",
    "wechat": "wx001",
    "company_text": "公司",
    "org_title": "CTO",
    "org_name": "机构甲",
    "subject_type": "person",
    "business_capabilities": '["转化"]',
    "avatar_file_id": 7,
    "password_configured": True,
    "wechat_bound": True,
    "user_status": "active",
    "cred_status": "active",
    # importer 批次/条目行
    "source_filename": "deck.pptx",
    "total_count": 2,
    "success_count": 1,
    "failed_count": 1,
    "source_page_or_slide": "slide-1",
    "raw_data": {"text": "raw"},
    "normalized_data": {"title": "导入成果"},
    "validation_errors": [],
    "achievement_id": 1,
    "imported_by_user_id": 7,
}


def _row(**overrides):
    row = dict(FAT)
    row.update(overrides)
    return row


_KEEP = object()


def _cur(fetchone=_KEEP, fetchall=_KEEP, rowcount=1):
    """fetchone/fetchall 显式传 None 表示无行；省略才回退到 FAT 默认行。"""
    cur = MagicMock()
    cur.fetchone.return_value = _row() if fetchone is _KEEP else fetchone
    cur.fetchall.return_value = [_row()] if fetchall is _KEEP else fetchall
    cur.rowcount = rowcount
    return cur


def _gc(cur):
    mock_gc = MagicMock()
    mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
    mock_gc.return_value.__exit__ = MagicMock(return_value=False)
    return mock_gc


# ══════════════════════════════════════════════════════════════
# modules/achievement/service.py
# ══════════════════════════════════════════════════════════════


class TestListAchievements:
    @patch("modules.achievement.service.get_cursor")
    def test_list_with_all_filters(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_achievements

        out = list_achievements(
            {"keyword": "材料", "category": "cat", "maturityLevel": "02_lab", "industryId": "3"}, user_id=1
        )
        assert out["total"] == 1
        assert out["page"] == 1
        assert out["totalPages"] == 1
        assert out["list"][0]["title"] == "成果标题"
        assert out["list"][0]["applicationFields"] == ["农业"]
        assert out["list"][0]["isMine"] is True

    @patch("modules.achievement.service.get_cursor")
    def test_list_invalid_industry_id(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_achievements

        with pytest.raises(BizError):
            list_achievements({"industryId": "abc"})

    @patch("modules.achievement.service.get_cursor")
    def test_list_bad_page_args_and_empty(self, mock_gc):
        cur = _cur(fetchall=[])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_achievements

        out = list_achievements({"page": "x", "pageSize": "y"})
        assert out["page"] == 1
        assert out["pageSize"] == 10
        assert out["list"] == []


class TestGetAchievementDetail:
    @patch("modules.achievement.service.get_cursor")
    def test_published_owner_json_fields_visible_contact(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", application_fields='["a"]', innovation_points='["i"]'))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import get_achievement_detail

        out = get_achievement_detail(1, user_id=1)
        assert out["status"] == "published"
        assert out["viewCount"] == 5
        assert out["applicationFields"] == ["a"]
        assert out["innovationPoints"] == ["i"]
        assert out["contactPhone"] == "13800138000"
        assert out["contactName"] == "张三"
        assert out["publishedAt"] == "2026-01-01"

    @patch("modules.achievement.service.get_cursor")
    def test_draft_dock_party_masked_contact_none_fields(self, mock_gc):
        cur = _cur()
        cur.fetchone.side_effect = [
            _row(status="draft", owner_user_id=999, application_fields=None, innovation_points=None),
            _row(),
            None,
        ]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import get_achievement_detail

        out = get_achievement_detail(1, user_id=1)
        assert out["status"] == "draft"
        assert out["applicationFields"] == []
        assert out["innovationPoints"] == []
        assert out["contactPhone"] == "138****8000"
        assert out["contactName"] == "张**"
        assert out["contactTitle"] == "教授"

    @patch("modules.achievement.service.get_cursor")
    def test_invalid_json_fields_and_masked_anonymous(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", application_fields="x{y", innovation_points="z{"))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import get_achievement_detail

        out = get_achievement_detail(1, user_id=None)
        assert out["applicationFields"] == []
        assert out["innovationPoints"] == []
        assert out["contactPhone"] == "138****8000"
        assert out["isMine"] is False
        assert out["platformAssisted"] is False

    @patch("modules.achievement.service.get_cursor")
    def test_hidden_draft_returns_none(self, mock_gc):
        cur = _cur()
        cur.fetchone.side_effect = [_row(status="draft", owner_user_id=999), None]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import get_achievement_detail

        assert get_achievement_detail(1, user_id=1) is None


class TestParseUpsertBody:
    def test_rich_body_parses_all_field_types(self):
        from modules.achievement.service import _parse_upsert_body

        body = {
            "title": "新成果",
            "maturityLevel": "02_lab",
            "pricingMode": "license",
            "achievementKind": "patent",
            "techIntro": "简介",
            "sourceOrgName": "来源单位",
            "contactPhone": "13800138000",
            "contactEmail": "user@example.com",
            "applicationFields": ["农业"],
            "innovationPoints": ["创新"],
            "priceMinWan": 1,
            "priceMaxWan": 2,
            "categoryId": 3,
            "orgId": 4,
            "ownerUserId": 9,
            "cooperationCapacity": 3,
            "inventorRefs": [
                {
                    "name": "张三",
                    "orgName": "大学",
                    "personType": "first_inventor",
                    "sortOrder": 0,
                    "department": "院系",
                    "title": "教授",
                    "bio": "简介",
                    "phone": "13800138000",
                    "email": "user@example.com",
                    "homepageUrl": "https://a.example.com",
                    "avatarFileId": 5,
                },
                {"name": "张三", "orgName": "大学"},
            ],
            "sections": [{"code": "innovation", "title": "创新点", "content": "内容"}],
            "tags": ["AI"],
        }
        fields, refs, content = _parse_upsert_body(body, partial=False)
        assert fields["title"] == "新成果"
        assert fields["maturity_level"] == "02_lab"
        assert fields["maturity_desc"] == "实验室验证"
        assert fields["pricing_mode"] == "license"
        assert fields["achievement_kind"] == "patent"
        assert fields["contact_phone"] == "13800138000"
        assert fields["contact_email"] == "user@example.com"
        assert json.loads(fields["application_fields"]) == ["农业"]
        assert json.loads(fields["innovation_points"]) == ["创新"]
        assert fields["price_min_wan"] == 1.0
        assert fields["cooperation_capacity"] == 3
        assert fields["cooperation_remaining"] == 3
        assert len(refs) == 1
        assert refs[0]["homepage_url"] == "https://a.example.com"
        assert refs[0]["avatar_file_id"] == 5
        assert content["tags"] == ["AI"]
        assert content["sections"][0]["code"] == "innovation"

    def test_inventor_department_too_long(self):
        from modules.achievement.service import _parse_upsert_body

        with pytest.raises(BizError):
            _parse_upsert_body({"title": "x", "inventorRefs": [{"name": "a", "department": "d" * 129}]}, partial=False)

    def test_inventor_homepage_rejects_dangerous_scheme(self):
        from modules.achievement.service import _parse_upsert_body

        with pytest.raises(BizError):
            _parse_upsert_body(
                {"title": "x", "inventorRefs": [{"name": "a", "homepageUrl": "javascript:alert(1)"}]}, partial=False
            )

    def test_inventor_avatar_file_id_must_be_int(self):
        from modules.achievement.service import _parse_upsert_body

        with pytest.raises(BizError):
            _parse_upsert_body({"title": "x", "inventorRefs": [{"name": "a", "avatarFileId": "xx"}]}, partial=False)


class TestValidateRefs:
    def test_backfills_source_org_name_from_institution(self):
        from modules.achievement.service import _validate_refs

        cur = _cur()
        fields = {"category_id": 1, "org_id": 2}
        _validate_refs(cur, fields)
        assert fields["source_org_name"] == "机构甲"

    def test_category_missing_raises(self):
        from modules.achievement.service import _validate_refs

        cur = _cur(fetchone=None)
        with pytest.raises(BizError):
            _validate_refs(cur, {"category_id": 9})

    def test_org_missing_raises(self):
        from modules.achievement.service import _validate_refs

        cur = _cur(fetchone=None)
        with pytest.raises(BizError):
            _validate_refs(cur, {"org_id": 9})


class TestSyncInventors:
    def test_existing_inventor_enriched_and_linked(self):
        from modules.achievement.service import _sync_inventors

        cur = _cur()
        refs = [
            {
                "name": "张三",
                "org_name": "大学",
                "person_type": "first_inventor",
                "sort_order": 0,
                "department": "院系",
                "avatar_file_id": 1,
            }
        ]
        _sync_inventors(cur, 1, refs, user_id=1)
        executed = [call.args[0] for call in cur.execute.call_args_list]
        assert any("DELETE FROM achievement_inventor" in sql for sql in executed)
        assert any("UPDATE inventor SET" in sql for sql in executed)
        assert any("INSERT INTO achievement_inventor" in sql for sql in executed)

    def test_avatar_not_owned_raises(self):
        from modules.achievement.service import _sync_inventors

        cur = _cur(fetchall=[])
        refs = [{"name": "张三", "org_name": None, "sort_order": 0, "avatar_file_id": 9}]
        with pytest.raises(BizError):
            _sync_inventors(cur, 1, refs, user_id=1)

    def test_new_inventor_inserted(self):
        from modules.achievement.service import _sync_inventors

        cur = _cur()
        cur.fetchone.side_effect = [None, {"id": 7}]
        refs = [{"name": "李四", "org_name": None, "person_type": None, "sort_order": 0}]
        _sync_inventors(cur, 1, refs)
        executed = [call.args[0] for call in cur.execute.call_args_list]
        assert any("INSERT INTO inventor" in sql for sql in executed)
        assert any("INSERT INTO achievement_inventor" in sql for sql in executed)


class TestOwnerDetail:
    @patch("modules.achievement.service.get_cursor")
    def test_json_fields_parsed_and_invalid_falls_back(self, mock_gc):
        cur = _cur(fetchone=_row(application_fields='["a"]', innovation_points="not{json"))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import _owner_detail_public

        out = _owner_detail_public(1, user_id=1)
        assert out["id"] == 1
        assert out["applicationFields"] == ["a"]
        assert out["innovationPoints"] == []
        assert out["inventors"][0]["name"] == "机构甲"
        assert out["tags"] == ["机构甲"]

    @patch("modules.achievement.service.get_cursor")
    def test_none_fields_become_empty_lists(self, mock_gc):
        cur = _cur(fetchone=_row(application_fields=None, innovation_points=None))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import _owner_detail_public

        out = _owner_detail_public(1, user_id=1)
        assert out["applicationFields"] == []
        assert out["innovationPoints"] == []
        assert out["status"] == "active"

    def test_owner_detail_missing_row_returns_none(self):
        from modules.achievement.service import _owner_detail

        assert _owner_detail(_cur(fetchone=None), 9) is None


class TestCreateAchievement:
    @patch("modules.achievement.service.get_cursor")
    def test_create_with_inventors_and_content(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import create_achievement

        body = {
            "title": "新成果",
            "maturityLevel": "02_lab",
            "pricingMode": "license",
            "achievementKind": "patent",
            "contactPhone": "13800138000",
            "contactEmail": "user@example.com",
            "applicationFields": ["农业"],
            "innovationPoints": ["创新"],
            "priceMinWan": 1,
            "priceMaxWan": 2,
            "categoryId": 3,
            "orgId": 4,
            "ownerUserId": 9,
            "cooperationCapacity": 3,
            "inventorRefs": [
                {
                    "name": "张三",
                    "orgName": "大学",
                    "personType": "first_inventor",
                    "department": "院系",
                    "phone": "13800138000",
                    "email": "user@example.com",
                    "homepageUrl": "https://a.example.com",
                    "avatarFileId": 1,
                }
            ],
            "tags": ["AI"],
            "sections": [{"code": "innovation", "title": "创新点", "content": "内容"}],
            "media": [{"fileId": 1, "role": "cover", "sortOrder": 0}],
            "industryIds": [1],
        }
        out = create_achievement(1, "U001", body, request_id="req-1", source_import_item_id=8)
        assert out["id"] == 1
        assert out["title"] == "成果标题"
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "INSERT INTO achievement" in executed
        assert "INSERT INTO achievement_tag" in executed
        assert "INSERT INTO achievement_media" in executed
        assert "INSERT INTO audit_log" in executed

    @patch("modules.achievement.service.get_cursor")
    def test_price_min_greater_than_max(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import create_achievement

        with pytest.raises(BizError):
            create_achievement(1, "U001", {"title": "x", "priceMinWan": 5, "priceMaxWan": 2})


class TestUpdateAchievement:
    @patch("modules.achievement.service.get_cursor")
    def test_update_moves_remaining_capacity(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1, cooperation_capacity=2, cooperation_remaining=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        out = update_achievement(1, "U001", 1, {"title": "改标题", "version": 1, "cooperationCapacity": 3})
        assert out["id"] == 1
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "UPDATE achievement SET" in executed
        # remaining = min(3, 1 + (3 - 2)) = 2
        update_calls = [call.args for call in cur.execute.call_args_list if "UPDATE achievement SET" in call.args[0]]
        assert 2 in update_calls[0][1]

    @patch("modules.achievement.service.get_cursor")
    def test_update_unlimited_capacity_keeps_remaining_none(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        update_achievement(1, "U001", 1, {"version": 1, "cooperationCapacity": None})
        update_calls = [call.args for call in cur.execute.call_args_list if "UPDATE achievement SET" in call.args[0]]
        assert None in update_calls[0][1]

    @patch("modules.achievement.service.get_cursor")
    def test_update_capacity_from_unlimited_fills(self, mock_gc):
        cur = _cur(
            fetchone=_row(status="draft", owner_user_id=1, cooperation_capacity=None, cooperation_remaining=None)
        )
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        update_achievement(1, "U001", 1, {"version": 1, "cooperationCapacity": 3})
        update_calls = [call.args for call in cur.execute.call_args_list if "UPDATE achievement SET" in call.args[0]]
        assert 3 in update_calls[0][1]

    @patch("modules.achievement.service.get_cursor")
    def test_update_requires_version(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"title": "x"})

    @patch("modules.achievement.service.get_cursor")
    def test_update_not_found(self, mock_gc):
        cur = _cur(fetchone=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.achievement.service.get_cursor")
    def test_update_forbidden_for_non_owner(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=999))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.achievement.service.get_cursor")
    def test_update_status_not_editable(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.achievement.service.get_cursor")
    def test_update_version_conflict(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1), rowcount=0)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"title": "x", "version": 1})

    @patch("modules.achievement.service.get_cursor")
    def test_content_only_patch_bumps_version(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        body = {"version": 1, "sections": [{"code": "other", "title": "t", "content": "c"}]}
        out = update_achievement(1, "U001", 1, body)
        assert out["id"] == 1
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "UPDATE achievement SET version=version+1 WHERE id=%s AND version=%s" in executed
        assert "INSERT INTO achievement_section" in executed

    @patch("modules.achievement.service.get_cursor")
    def test_empty_inventor_refs_replaces_links(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        out = update_achievement(1, "U001", 1, {"version": 1, "inventorRefs": []})
        assert out["id"] == 1
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "DELETE FROM achievement_inventor" in executed

    @patch("modules.achievement.service.get_cursor")
    def test_update_price_min_greater_than_max(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(1, "U001", 1, {"priceMinWan": 5, "priceMaxWan": 1, "version": 1})

    @patch("modules.achievement.service.get_cursor")
    def test_update_with_org_checks_active_membership(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1), rowcount=1)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        out = update_achievement(1, "U001", 1, {"title": "新标题", "orgId": 2, "version": 1})
        assert out["id"] == 1
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "organization_membership" in executed
        assert "UPDATE achievement SET" in executed

    @patch("modules.achievement.service.get_cursor")
    def test_content_only_patch_version_conflict(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1), rowcount=0)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import update_achievement

        with pytest.raises(BizError):
            update_achievement(
                1, "U001", 1, {"version": 1, "sections": [{"code": "other", "title": "t", "content": "c"}]}
            )


class TestTransition:
    @patch("modules.achievement.service.get_cursor")
    def test_submit_draft(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        out = submit_achievement(1, "U001", 1, 1, request_id="req-2")
        assert out == {"status": "pending_review"}

    @patch("modules.achievement.service.get_cursor")
    def test_offline_with_reason(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import offline_achievement

        out = offline_achievement(1, "U001", 1, 1, reason="已完成对接", reason_code="cooperated")
        assert out == {"status": "offline"}

    @patch("modules.achievement.service.get_cursor")
    def test_transition_requires_version(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        with pytest.raises(BizError):
            submit_achievement(1, "U001", 1, None)

    @patch("modules.achievement.service.get_cursor")
    def test_transition_not_found(self, mock_gc):
        cur = _cur(fetchone=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        with pytest.raises(BizError):
            submit_achievement(1, "U001", 1, 1)

    @patch("modules.achievement.service.get_cursor")
    def test_transition_forbidden(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=999))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        with pytest.raises(BizError):
            submit_achievement(1, "U001", 1, 1)

    @patch("modules.achievement.service.get_cursor")
    def test_transition_status_not_allowed(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        with pytest.raises(BizError):
            submit_achievement(1, "U001", 1, 1)

    @patch("modules.achievement.service.get_cursor")
    def test_offline_bad_reason_code(self, mock_gc):
        cur = _cur(fetchone=_row(status="published", owner_user_id=1))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import offline_achievement

        with pytest.raises(BizError):
            offline_achievement(1, "U001", 1, 1, reason_code="not-a-code")

    @patch("modules.achievement.service.get_cursor")
    def test_transition_version_conflict(self, mock_gc):
        cur = _cur(fetchone=_row(status="draft", owner_user_id=1), rowcount=0)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import submit_achievement

        with pytest.raises(BizError):
            submit_achievement(1, "U001", 1, 1)


class TestListMyAchievements:
    @patch("modules.achievement.service.get_cursor")
    def test_list_my_with_status_and_json_fields(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_my_achievements

        out = list_my_achievements(1, {"page": "x", "pageSize": "y", "status": "draft"})
        assert out["page"] == 1
        assert out["pageSize"] == 10
        assert out["total"] == 1
        assert out["list"][0]["applicationFields"] == ["农业"]
        assert out["list"][0]["status"] == "active"

    @patch("modules.achievement.service.get_cursor")
    def test_my_item_invalid_json_fields(self, mock_gc):
        cur = _cur(fetchall=[_row(application_fields="not{json")])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_my_achievements

        out = list_my_achievements(1, {})
        assert out["list"][0]["applicationFields"] == []

    @patch("modules.achievement.service.get_cursor")
    def test_my_item_none_fields(self, mock_gc):
        cur = _cur(fetchall=[_row(application_fields=None)])
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.service import list_my_achievements

        out = list_my_achievements(1, {})
        assert out["list"][0]["applicationFields"] == []


# ══════════════════════════════════════════════════════════════
# modules/achievement/content.py
# ══════════════════════════════════════════════════════════════


class TestParseContentPayload:
    def test_media_file_ids_normalizes_roles(self):
        from modules.achievement.content import parse_content_payload

        out = parse_content_payload({"mediaFileIds": [3, 3, 5]})
        assert out["media"][0] == {"file_id": 3, "role": "cover", "caption": None, "alt": None, "sort": 0}
        assert out["media"][1] == {"file_id": 5, "role": "gallery", "caption": None, "alt": None, "sort": 1}

    def test_media_file_ids_not_list(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"mediaFileIds": "x"})

    def test_media_file_ids_invalid_item(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"mediaFileIds": [0]})

    def test_sections_not_list(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"sections": "x"})

    def test_sections_item_not_dict(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"sections": ["x"]})

    def test_patents_not_list(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"patents": "x"})

    def test_patents_item_not_dict(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"patents": ["x"]})

    def test_patent_no_duplicate(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"patents": [{"patentNo": "CN1"}, {"patentNo": "cn1"}]})

    def test_links_not_list(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"links": "x"})

    def test_link_type_invalid(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"links": [{"type": "bad", "label": "x", "url": "https://a.example.com"}]})

    def test_link_url_scheme_invalid(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"links": [{"type": "demo", "label": "x", "url": "ftp://a.example.com"}]})

    def test_media_not_list(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"media": "x"})

    def test_media_item_not_dict(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"media": ["x"]})

    def test_media_role_invalid(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"media": [{"fileId": 1, "role": "bad"}]})

    def test_media_only_one_cover(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"media": [{"fileId": 1, "role": "cover"}, {"fileId": 2, "role": "cover"}]})

    def test_industry_ids_not_int(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"industryIds": ["x"]})

    def test_tags_and_industry_dedup(self):
        from modules.achievement.content import parse_content_payload

        out = parse_content_payload({"tags": ["AI", "AI"], "industryIds": [1, 1]})
        assert out["tags"] == ["AI"]
        assert out["industryIds"] == [1]

    def test_links_normalize(self):
        from modules.achievement.content import parse_content_payload

        out = parse_content_payload(
            {"links": [{"type": "official_site", "label": "官网", "url": "https://example.com"}]}
        )
        assert out["links"] == [{"type": "official_site", "label": "官网", "url": "https://example.com", "sort": 0}]

    def test_industry_ids_too_many(self):
        from modules.achievement.content import parse_content_payload

        with pytest.raises(BizError):
            parse_content_payload({"industryIds": [1, 2, 3, 4, 5, 6, 7, 8, 9]})


class TestSyncContent:
    def test_sync_all_relations(self):
        from modules.achievement.content import sync_content

        cur = _cur(fetchall=[_row(file_id=1)])
        content = {
            "tags": ["AI"],
            "sections": [{"code": "other", "title": "t", "content": "c", "sort": 0}],
            "patents": [{"no": "CN1", "title": None, "primary": True, "url": None, "sort": 0}],
            "links": [{"type": "demo", "label": "l", "url": "https://a.example.com", "sort": 0}],
            "media": [{"file_id": 1, "role": "cover", "sort": 0, "caption": None, "alt": None}],
            "industryIds": [1],
        }
        sync_content(cur, 1, 1, content, allow_existing_media=True)
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "INSERT INTO achievement_tag" in executed
        assert "INSERT INTO achievement_section" in executed
        assert "INSERT INTO achievement_patent" in executed
        assert "INSERT INTO achievement_link" in executed
        assert "INSERT INTO achievement_media" in executed
        assert "INSERT INTO achievement_industry" in executed

    def test_media_not_owned_raises(self):
        from modules.achievement.content import sync_content

        cur = _cur(fetchall=[])
        content = {"media": [{"file_id": 9, "role": "gallery", "sort": 0, "caption": None, "alt": None}]}
        with pytest.raises(BizError):
            sync_content(cur, 1, 1, content)

    def test_industry_unknown_raises(self):
        from modules.achievement.content import sync_content

        cur = _cur(fetchall=[])
        with pytest.raises(BizError):
            sync_content(cur, 1, 1, {"industryIds": [5]})

    def test_empty_industry_ids_clears_relations(self):
        from modules.achievement.content import sync_content

        cur = _cur()
        sync_content(cur, 1, 1, {"industryIds": []})
        executed = [call.args[0] for call in cur.execute.call_args_list]
        assert executed == ["DELETE FROM achievement_industry WHERE achievement_id=%s"]


# ══════════════════════════════════════════════════════════════
# modules/achievement/extract.py
# ══════════════════════════════════════════════════════════════


class TestExtractHelpers:
    def test_parse_labeled_line_empty(self):
        from modules.achievement.extract import parse_labeled_line

        assert parse_labeled_line("  ") == (None, "")

    def test_map_maturity_substring_fallback(self):
        from modules.achievement.extract import map_maturity

        assert map_maturity("中试阶段") == "03_pilot_ready"

    def test_map_maturity_no_match(self):
        from modules.achievement.extract import map_maturity

        assert map_maturity("未知xyz") == ""

    def test_assign_field_empty_value_noop(self):
        from modules.achievement.extract import assign_field

        target = {}
        assign_field(target, "contactName", "  ")
        assert target == {}

    def test_assign_field_pricing_mode(self):
        from modules.achievement.extract import assign_field

        target = {}
        assign_field(target, "pricingMode", "面议")
        assert target["pricingMode"] == "negotiable"

    def test_assign_field_application_fields(self):
        from modules.achievement.extract import assign_field

        target = {}
        assign_field(target, "applicationFields", "农业、工业")
        assert target["applicationFields"] == ["农业", "工业"]

    def test_assign_field_tech_intro_appends(self):
        from modules.achievement.extract import assign_field

        target = {"techIntro": "旧"}
        assign_field(target, "techIntro", "新")
        assert target["techIntro"] == "旧\n新"

    def test_append_link_empty_url_noop(self):
        from modules.achievement.extract import append_link

        target = {}
        append_link(target, "官网", "  ", "official_site")
        assert "links" not in target

    def test_append_link_prepends_https(self):
        from modules.achievement.extract import append_link

        target = {}
        append_link(target, "官网", "example.com", "official_site")
        assert target["links"][0]["url"] == "https://example.com"

    def test_append_link_skips_duplicate(self):
        from modules.achievement.extract import append_link

        target = {"links": [{"url": "https://a.example.com"}]}
        append_link(target, "官网", "https://a.example.com", "other")
        assert len(target["links"]) == 1


class TestHarvestFields:
    def test_harvest_full_pipeline(self):
        from modules.achievement.extract import harvest_fields_from_text

        text = (
            "成果名称：新型材料技术\n"
            "\n"
            "联系人：张三\n"
            "职务：\n"
            "教授\n"
            "个人主页：https://me.example.com\n"
            "官网：\n"
            "https://example.org\n"
            "合作请联系 test@example.com 电话13900139000"
        )
        out = harvest_fields_from_text(text)
        assert out["contactName"] == "张三"
        assert out["contactTitle"] == "教授"
        assert out["contactEmail"] == "test@example.com"
        assert out["contactPhone"] == "13900139000"
        urls = [item["url"] for item in out["links"]]
        assert "https://me.example.com" in urls
        assert "https://example.org" in urls
        assert "新型材料技术" in out["techIntro"]
        assert "合作请联系" in out["techIntro"]


# ══════════════════════════════════════════════════════════════
# modules/achievement/importer.py
# ══════════════════════════════════════════════════════════════


class TestContributorPage:
    def test_labeled_contacts_and_bio(self):
        from modules.achievement.importer import _normalize_contributor_page

        text = (
            "联系人：张三\n"
            "联系电话：13800138000\n"
            "邮箱：\n"
            "zhang@example.com\n"
            "微信：wx001\n"
            "职务：教授\n"
            "成果简介：从事材料研究\n"
            "更多介绍文本"
        )
        page = {"sourcePageOrSlide": "slide-2", "text": text, "images": [{"filename": "x.png"}]}
        out = _normalize_contributor_page(page)
        inventor = out["inventor"]
        assert inventor["name"] == "张三"
        assert inventor["phone"] == "13800138000"
        assert inventor["email"] == "zhang@example.com"
        assert inventor["homepageUrl"] == "wx001"
        assert inventor["title"] == "教授"
        assert "从事材料研究" in inventor["bio"]
        assert inventor["avatarImageIndex"] == 0
        assert out["pageType"] == "contributor"

    def test_short_line_becomes_name(self):
        from modules.achievement.importer import _normalize_contributor_page

        out = _normalize_contributor_page({"sourcePageOrSlide": "slide-1", "text": "张三\n简介文本", "images": []})
        assert out["inventor"]["name"] == "张三"

    def test_fallback_scan_finds_swallowed_name(self):
        from modules.achievement.importer import _normalize_contributor_page

        out = _normalize_contributor_page({"sourcePageOrSlide": "slide-1", "text": "邮箱：\n张三", "images": []})
        assert out["inventor"]["name"] == "张三"


class _FakeImage:
    def __init__(self, ext, blob):
        self.ext = ext
        self.blob = blob


class _FakeImageShape:
    def __init__(self, image):
        self.image = image
        self.width = 10
        self.height = 10
        self.left = 0
        self.top = 0


class TestDocImages:
    def test_pptx_images_skips_unknown_mime(self):
        from modules.achievement.importer import _pptx_images

        slide = MagicMock()
        slide.shapes = [_FakeImageShape(_FakeImage("bmp", b"x")), _FakeImageShape(_FakeImage("png", b"y"))]
        out = _pptx_images(slide, "slide-1", 100, 100)
        assert len(out) == 1
        assert out[0]["filename"] == "slide-1-image-2.png"
        assert out[0]["mimeType"] == "image/png"

    def test_pdf_images_skips_unknown_mime(self):
        from modules.achievement.importer import _pdf_images

        good = MagicMock(spec=["name", "data"])
        good.name = "a.png"
        good.data = b"x"
        bad = MagicMock(spec=["name", "data"])
        bad.name = "b.tiff"
        bad.data = b"y"
        page = MagicMock(spec=["images"])
        page.images = [good, bad]
        out = _pdf_images(page, "page-1")
        assert len(out) == 1
        assert out[0]["filename"] == "page-1-image-1.png"


class _FakeShape:
    def __init__(self, text):
        self.text = text
        self.has_text_frame = True


class _FakeSlide:
    def __init__(self, *texts):
        self.shapes = [_FakeShape(t) for t in texts]


class _FakeDeck:
    slide_width = 100
    slide_height = 100

    def __init__(self, slides):
        self.slides = slides


class _FakePdfPage:
    def __init__(self, text):
        self._text = text
        self.images = []

    def extract_text(self):
        return self._text


class TestExtractDocumentRecords:
    def test_project_contributor_patent_template_flow(self):
        from modules.achievement.importer import extract_document_records

        deck = _FakeDeck(
            [
                _FakeSlide("成果名称：新型材料技术", "成果简介：一种新材料"),
                _FakeSlide("成果完成人", "联系人：张三", "联系电话：13800138000", "从事材料研究"),
                _FakeSlide("专利号：CN12345678A", "扫码查看专利公布公告"),
                _FakeSlide("单击此处添加标题"),
            ]
        )
        with patch("pptx.Presentation", return_value=deck):
            records = extract_document_records("deck.pptx")
        assert [r["raw"]["pageType"] for r in records] == ["project", "patent"]
        assert records[0]["normalized"]["title"] == "新型材料技术"
        assert records[1]["normalized"]["patents"][0]["patentNo"] == "CN12345678"

    def test_trailing_contributors_merge_into_project(self):
        from modules.achievement.importer import extract_document_records

        deck = _FakeDeck(
            [
                _FakeSlide("成果名称：第一成果", "成果简介：简介"),
                _FakeSlide("成果完成人", "联系人：张三", "联系电话：13800138000"),
                _FakeSlide("成果名称：第二成果", "成果简介：简介二"),
                _FakeSlide("成果完成人", "联系人：李四", "邮箱：li@example.com"),
            ]
        )
        with patch("pptx.Presentation", return_value=deck):
            records = extract_document_records("deck.pptx")
        assert len(records) == 2
        names = [inv["name"] for inv in records[1]["normalized"]["inventorRefs"]]
        assert names == ["张三", "李四"]
        assert records[1]["raw"]["contributorPages"] == ["slide-2", "slide-4"]
        assert records[1]["images"] == []
        assert "contributorPages" not in records[0]["raw"]

    def test_lone_contributor_becomes_own_record(self):
        from modules.achievement.importer import extract_document_records

        deck = _FakeDeck([_FakeSlide("成果完成人", "联系人：李四", "邮箱：li@example.com")])
        with patch("pptx.Presentation", return_value=deck):
            records = extract_document_records("deck.pptx")
        assert len(records) == 1
        assert records[0]["raw"]["pageType"] == "contributor"
        assert records[0]["normalized"]["inventorRefs"][0]["name"] == "李四"
        assert records[0]["normalized"]["title"] == "李四"

    def test_pdf_pages_extract_records(self):
        from modules.achievement.importer import extract_document_records

        reader = MagicMock()
        reader.pages = [_FakePdfPage("成果名称：PDF成果\n成果简介：简介"), _FakePdfPage("专利号：CN202410999999")]
        with patch("pypdf.PdfReader", return_value=reader):
            records = extract_document_records("deck.pdf")
        assert [r["raw"]["pageType"] for r in records] == ["project", "patent"]
        assert records[0]["normalized"]["title"] == "PDF成果"
        assert records[0]["images"] == []
        assert records[1]["normalized"]["patents"][0]["patentNo"] == "CN202410999999"


class TestNormalizePage:
    def test_labels_links_patents_and_title_en(self):
        from modules.achievement.importer import _normalize_page

        text = (
            "成果名称：\n"
            "新型材料技术\n"
            "官网：https://example.com\n"
            "个人网站：\n"
            "https://blog.example.com\n"
            "专利号：\n"
            "CN12345678A\n"
            "英文名称：Material Technology\n"
        )
        out = _normalize_page({"sourcePageOrSlide": "slide-1", "text": text})
        normalized = out["normalized"]
        assert normalized["title"] == "新型材料技术"
        assert normalized["titleEn"] == "Material Technology"
        assert normalized["patents"][0]["patentNo"] == "CN12345678"
        link_urls = [item["url"] for item in normalized["links"]]
        assert "https://example.com" in link_urls
        assert "https://blog.example.com" in link_urls

    def test_link_label_with_url_on_next_line(self):
        from modules.achievement.importer import _normalize_page

        out = _normalize_page({"sourcePageOrSlide": "slide-1", "text": "官网：\nwww.example.com\n"})
        links = out["normalized"]["links"]
        assert links[0]["url"] == "https://www.example.com"
        assert links[0]["type"] == "official_site"

    def test_short_application_fields_stay_list(self):
        from modules.achievement.importer import _normalize_page

        out = _normalize_page({"sourcePageOrSlide": "slide-1", "text": "成果名称：材料技术\n应用领域：农业、工业\n"})
        assert out["normalized"]["applicationFields"] == ["农业", "工业"]

    def test_long_application_fields_become_section(self):
        from modules.achievement.importer import _normalize_page

        text = "成果名称：材料技术\n应用领域：" + "甲" * 50 + "、农业\n"
        out = _normalize_page({"sourcePageOrSlide": "slide-1", "text": text})
        normalized = out["normalized"]
        assert "applicationFields" not in normalized
        assert any(item["code"] == "application" for item in normalized["sections"])


class TestStageDocument:
    def _records(self):
        return [
            {
                "sourcePageOrSlide": "slide-1",
                "raw": {"text": "a"},
                "normalized": {"title": "T1"},
                "errors": [],
                "images": [{"filename": "a.png", "mimeType": "image/png", "data": b"x"}],
            },
            {
                "sourcePageOrSlide": "slide-2",
                "raw": {"text": "b"},
                "normalized": {"title": "T2"},
                "errors": [{"field": "title", "message": "未识别到标题"}],
                "images": [],
            },
        ]

    def test_stage_missing_file(self):
        from modules.achievement.importer import stage_document

        with pytest.raises(BizError):
            stage_document("Z:/definitely/not/here.pptx", 1)

    def test_stage_images_require_created_by(self, tmp_path):
        from modules.achievement.importer import stage_document

        source = tmp_path / "deck.pptx"
        source.write_bytes(b"x")
        with patch("modules.achievement.importer.extract_document_records", return_value=self._records()):
            with pytest.raises(BizError):
                stage_document(source, None)

    def test_stage_success_stages_records(self, tmp_path):
        from modules.achievement.importer import stage_document

        source = tmp_path / "deck.pptx"
        source.write_bytes(b"x")
        cur = _cur()
        with (
            patch("modules.achievement.importer.extract_document_records", return_value=self._records()),
            patch("modules.achievement.importer.get_cursor", _gc(cur)),
            patch("modules.file.service.create_uploaded_file", return_value={"id": 3, "width": 1, "height": 1}),
        ):
            out = stage_document(source, 1, "某大学")
        assert out == {"batchId": 1, "total": 2, "staged": 1, "failed": 1}
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "INSERT INTO achievement_import_batch" in executed
        assert "INSERT INTO achievement_import_item" in executed

    def test_stage_failure_cleans_uploaded_files(self, tmp_path):
        from modules.achievement.importer import stage_document

        source = tmp_path / "deck.pptx"
        source.write_bytes(b"x")
        cur = _cur()
        gc_mock = _gc(cur)
        gc_mock.return_value.__enter__.side_effect = RuntimeError("db down")
        with (
            patch("modules.achievement.importer.extract_document_records", return_value=self._records()),
            patch("modules.achievement.importer.get_cursor", gc_mock),
            patch("modules.file.service.create_uploaded_file", return_value={"id": 3, "width": 1, "height": 1}),
            patch("modules.file.service.delete_uploaded_file") as mock_delete,
        ):
            with pytest.raises(RuntimeError):
                stage_document(source, 1)
        mock_delete.assert_called_once_with(3, 1)


class TestSafeFilename:
    def test_empty_name_falls_back(self):
        from modules.achievement.importer import _safe_import_filename

        assert _safe_import_filename("///", ".pptx") == "import.pptx"

    def test_missing_suffix_appended(self):
        from modules.achievement.importer import _safe_import_filename

        assert _safe_import_filename("report", ".pptx") == "report.pptx"


class TestStageUploads:
    def test_rejects_legacy_ppt(self):
        from modules.achievement.importer import stage_uploaded_document

        with pytest.raises(BizError):
            stage_uploaded_document("old.ppt", b"data", 1)

    def test_rejects_unknown_suffix(self):
        from modules.achievement.importer import stage_uploaded_document

        with pytest.raises(BizError):
            stage_uploaded_document("doc.docx", b"data", 1)

    def test_rejects_empty_data(self):
        from modules.achievement.importer import stage_uploaded_document

        with pytest.raises(BizError):
            stage_uploaded_document("a.pptx", b"", 1)

    def test_rejects_oversize(self):
        from modules.achievement.importer import stage_uploaded_document

        with patch("modules.achievement.importer.settings") as mock_settings:
            mock_settings.MAX_IMPORT_BYTES = 4
            mock_settings.MAX_UPLOAD_BYTES = 4
            with pytest.raises(BizError):
                stage_uploaded_document("a.pptx", b"12345", 1)

    def test_writes_temp_file_and_stages(self):
        from modules.achievement.importer import stage_uploaded_document

        with patch(
            "modules.achievement.importer.stage_document",
            return_value={"batchId": 9, "total": 1, "staged": 1, "failed": 0},
        ) as mock_stage:
            out = stage_uploaded_document("演示文稿.pptx", b"data", 3, "某大学")
        assert out["batchId"] == 9
        path, created_by, org = mock_stage.call_args.args
        assert str(path).endswith("演示文稿.pptx")
        assert created_by == 3
        assert org == "某大学"

    def test_batch_no_uploads_raises(self):
        from modules.achievement.importer import stage_uploaded_documents

        with pytest.raises(BizError):
            stage_uploaded_documents([], 1)

    def test_batch_collects_errors_and_single_batch_id(self):
        from modules.achievement.importer import stage_uploaded_documents

        ok = {"batchId": 1, "total": 2, "staged": 1, "failed": 1}
        with patch(
            "modules.achievement.importer.stage_uploaded_document",
            side_effect=[BizError("X", "文件坏了", 400), ok],
        ):
            out = stage_uploaded_documents([("坏.pptx", b""), ("好.pptx", b"d")], 1)
        assert out["batchId"] == 1
        assert out["total"] == 2
        assert out["errors"] == [{"filename": "坏.pptx", "message": "文件坏了"}]
        assert len(out["list"]) == 1

    def test_batch_all_failed_raises_first_error(self):
        from modules.achievement.importer import stage_uploaded_documents

        with patch(
            "modules.achievement.importer.stage_uploaded_document",
            side_effect=[BizError("X", "失败A", 400), BizError("X", "失败B", 400)],
        ):
            with pytest.raises(BizError) as err:
                stage_uploaded_documents([("a.pptx", b""), ("b.pptx", b"")], 1)
        assert err.value.message == "失败A"

    def test_batch_multiple_no_single_batch_id(self):
        from modules.achievement.importer import stage_uploaded_documents

        ok = {"batchId": 1, "total": 1, "staged": 1, "failed": 0}
        with patch("modules.achievement.importer.stage_uploaded_document", side_effect=[ok, dict(ok, batchId=2)]):
            out = stage_uploaded_documents([("a.pptx", b"d"), ("b.pptx", b"d")], 1)
        assert "batchId" not in out
        assert len(out["list"]) == 2


class TestImportBatchRead:
    @patch("modules.achievement.importer.get_cursor")
    def test_get_import_batch_with_items(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import get_import_batch

        out = get_import_batch(1)
        assert out["id"] == 1
        assert out["sourceFilename"] == "deck.pptx"
        assert out["createdAt"] == NOW.isoformat()
        assert out["items"][0]["sourcePageOrSlide"] == "slide-1"
        assert out["items"][0]["normalized"] == {"title": "导入成果"}
        assert out["items"][0]["achievementId"] == 1

    @patch("modules.achievement.importer.get_cursor")
    def test_get_import_batch_missing(self, mock_gc):
        cur = _cur(fetchone=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.achievement.importer import get_import_batch

        assert get_import_batch(9) is None


class TestConfirmImportItem:
    @staticmethod
    def _item(**overrides):
        base = {"status": "staged", "normalized_data": {"title": "导入成果"}, "validation_errors": []}
        base.update(overrides)
        return _row(**base)

    def test_confirm_creates_draft(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=self._item())
        gc_mock = _gc(cur)
        with (
            patch("modules.achievement.importer.get_cursor", gc_mock),
            patch("modules.achievement.service.get_cursor", gc_mock),
        ):
            out = confirm_import_item(2, 5, {"userId": 1, "userNo": "U001"}, overrides={"title": "覆盖", "bogus": 1})
        assert out["itemId"] == 5
        assert out["achievementId"] == 1
        assert out["status"] == "imported"
        assert out["achievement"]["id"] == 1

    def test_confirm_missing_item(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=None)
        with patch("modules.achievement.importer.get_cursor", _gc(cur)):
            with pytest.raises(BizError):
                confirm_import_item(2, 5, {"userId": 1})

    def test_confirm_already_imported(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=self._item(status="imported"))
        with patch("modules.achievement.importer.get_cursor", _gc(cur)):
            with pytest.raises(BizError):
                confirm_import_item(2, 5, {"userId": 1})

    def test_confirm_with_validation_errors(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=self._item(validation_errors=[{"field": "title", "message": "缺标题"}]))
        with patch("modules.achievement.importer.get_cursor", _gc(cur)):
            with pytest.raises(BizError):
                confirm_import_item(2, 5, {"userId": 1})

    def test_confirm_without_actor(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=self._item())
        with patch("modules.achievement.importer.get_cursor", _gc(cur)):
            with pytest.raises(BizError):
                confirm_import_item(2, 5, {})

    def test_confirm_stale_rowcount_raises(self):
        from modules.achievement.importer import confirm_import_item

        cur = _cur(fetchone=self._item(), rowcount=0)
        gc_mock = _gc(cur)
        with (
            patch("modules.achievement.importer.get_cursor", gc_mock),
            patch("modules.achievement.service.create_achievement", return_value={"id": 6}),
        ):
            with pytest.raises(BizError):
                confirm_import_item(2, 5, {"userId": 1, "userNo": "U001"})


class TestPublishImportItem:
    @patch("modules.admin.service.review_achievement")
    @patch("modules.admin.service.submit_achievement_admin")
    @patch("modules.achievement.importer.confirm_import_item")
    @patch("modules.achievement.importer.get_cursor")
    def test_publish_happy_path(self, mock_gc, mock_confirm, mock_submit, mock_review):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_confirm.return_value = {"itemId": 5, "achievementId": 6, "status": "imported"}
        from modules.achievement.importer import publish_import_item

        out = publish_import_item(2, 5, {"userId": 1, "userNo": "U001"})
        assert out == {"itemId": 5, "achievementId": 6, "status": "published"}
        mock_submit.assert_called_once()
        mock_review.assert_called_once()

    @patch("modules.achievement.importer.confirm_import_item")
    @patch("modules.achievement.importer.get_cursor")
    def test_publish_missing_draft(self, mock_gc, mock_confirm):
        cur = _cur(fetchone=None)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_confirm.return_value = {"itemId": 5, "achievementId": 6, "status": "imported"}
        from modules.achievement.importer import publish_import_item

        with pytest.raises(BizError):
            publish_import_item(2, 5, {"userId": 1})

    @patch("modules.admin.service.submit_achievement_admin")
    @patch("modules.achievement.importer.confirm_import_item")
    @patch("modules.achievement.importer.get_cursor")
    def test_publish_missing_after_submit(self, mock_gc, mock_confirm, mock_submit):
        cur = _cur()
        cur.fetchone.side_effect = [_row(), None]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_confirm.return_value = {"itemId": 5, "achievementId": 6, "status": "imported"}
        from modules.achievement.importer import publish_import_item

        with pytest.raises(BizError):
            publish_import_item(2, 5, {"userId": 1})


# ══════════════════════════════════════════════════════════════
# modules/identity/service.py
# ══════════════════════════════════════════════════════════════


class TestFindOrCreateUser:
    @patch("modules.identity.service.get_cursor")
    def test_existing_external_identity(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.provider import ExternalIdentity
        from modules.identity.service import find_or_create_user

        ext = ExternalIdentity(issuer="mock", tenant_id="default", external_subject="s1", display_name="张三")
        identity, is_new = find_or_create_user(ext)
        assert is_new is False
        assert identity.userId == 1
        assert "org_admin" in identity.roles

    @patch("modules.identity.service.get_cursor")
    def test_new_external_identity_creates_user(self, mock_gc):
        cur = _cur()
        cur.fetchone.side_effect = [None, {"m": 0}, {"id": 7}, None]
        cur.fetchall.return_value = [{"role_code": "user"}]
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.provider import ExternalIdentity
        from modules.identity.service import find_or_create_user

        ext = ExternalIdentity(issuer="mock", tenant_id="default", external_subject="s2", display_name="李四")
        identity, is_new = find_or_create_user(ext)
        assert is_new is True
        assert identity.userId == 7
        assert identity.roles == ["user"]
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "INSERT INTO app_user" in executed
        assert "INSERT INTO external_identity" in executed
        assert "INSERT INTO user_profile" in executed
        assert "INSERT INTO user_role" in executed


class TestBootstrapSession:
    @patch("modules.identity.service.get_cursor")
    def test_bootstrap_returns_session_and_user(self, mock_gc):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        from modules.identity.provider import ExternalIdentity
        from modules.identity.service import bootstrap_session

        ext = ExternalIdentity(issuer="mock", tenant_id="default", external_subject="s1", display_name="张三")
        with (
            patch("modules.identity.service.sign_access_token", return_value="tok"),
            patch("modules.identity.service.sign_refresh_token", return_value=("ref", "jti-1")),
        ):
            out = bootstrap_session(ext)
        assert out["accessToken"] == "tok"
        assert out["refreshToken"] == "ref"
        assert out["isNewUser"] is False
        assert out["user"]["userId"] == 1
        assert out["user"]["userNo"] == "U001"
        assert out["user"]["displayName"] == "张三"


class TestRefreshSession:
    def _payload(self):
        return {"type": "refresh", "jti": "j1", "sub": "1"}

    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_refresh_happy_path(self, mock_gc, mock_decode):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.return_value = self._payload()
        from modules.identity.service import refresh_session

        with (
            patch("modules.identity.service.sign_access_token", return_value="tok2"),
            patch("modules.identity.service.sign_refresh_token", return_value=("ref2", "jti-2")),
        ):
            out = refresh_session("old-refresh")
        assert out["accessToken"] == "tok2"
        assert out["refreshToken"] == "ref2"
        assert out["isNewUser"] is False
        assert out["user"]["userId"] == 1
        assert out["expiresIn"] > 0

    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_refresh_consumed_token_rejected(self, mock_gc, mock_decode):
        cur = _cur(rowcount=0)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.return_value = self._payload()
        from modules.identity.service import refresh_session

        with pytest.raises(BizError):
            refresh_session("old-refresh")

    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_refresh_disabled_user_revokes_sessions(self, mock_gc, mock_decode):
        cur = _cur(fetchone=_row(user_status="disabled"))
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.return_value = self._payload()
        from modules.identity.service import refresh_session

        with pytest.raises(BizError):
            refresh_session("old-refresh")
        executed = " ".join(call.args[0] for call in cur.execute.call_args_list)
        assert "UPDATE auth_session SET status='revoked'" in executed


class TestLogoutSession:
    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_logout_revokes_active_session(self, mock_gc, mock_decode):
        cur = _cur(rowcount=1)
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.return_value = {"jti": "j1"}
        from modules.identity.service import logout_session

        assert logout_session("refresh") == {"revoked": True}

    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_logout_without_jti(self, mock_gc, mock_decode):
        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.return_value = {}
        from modules.identity.service import logout_session

        assert logout_session("refresh") == {"revoked": False}

    @patch("core.jwt_utils.decode_no_verify_exp")
    @patch("modules.identity.service.get_cursor")
    def test_logout_invalid_token(self, mock_gc, mock_decode):
        import jwt as _jwt

        cur = _cur()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)
        mock_decode.side_effect = _jwt.InvalidTokenError("bad")
        from modules.identity.service import logout_session

        assert logout_session("bad") == {"revoked": False}


# ══════════════════════════════════════════════════════════════
# modules/identity/wechat.py
# ══════════════════════════════════════════════════════════════


class TestWechatExchange:
    def test_exchange_login_code_success(self):
        from modules.identity import wechat

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"openid": "o1"}).encode()
        with patch.object(wechat.urllib.request, "urlopen", return_value=response):
            assert wechat.exchange_login_code("code-1") == "o1"

    def test_exchange_login_code_bad_openid(self):
        from modules.identity import wechat

        response = MagicMock()
        response.__enter__.return_value.read.return_value = json.dumps({"openid": ""}).encode()
        with patch.object(wechat.urllib.request, "urlopen", return_value=response):
            with pytest.raises(BizError):
                wechat.exchange_login_code("code-1")


class TestWechatAccessToken:
    def test_access_token_is_cached(self):
        from modules.identity import wechat

        wechat._token_cache.clear()
        try:
            with patch.object(
                wechat, "_wechat_json", return_value={"access_token": "T", "expires_in": 7200}
            ) as mock_json:
                assert wechat._access_token() == "T"
                assert wechat._access_token() == "T"
            assert mock_json.call_count == 1
        finally:
            wechat._token_cache.clear()

    def test_access_token_invalid_response(self):
        from modules.identity import wechat

        wechat._token_cache.clear()
        try:
            with patch.object(wechat, "_wechat_json", return_value={}):
                with pytest.raises(BizError):
                    wechat._access_token()
        finally:
            wechat._token_cache.clear()


class TestWechatLoginBranches:
    @staticmethod
    def _runtime(cursor, phone="13900000000"):
        from modules.identity import wechat

        return (
            patch.object(wechat.settings, "WECHAT_LOGIN_ENABLED", True),
            patch.object(wechat.settings, "WECHAT_APPID", "app-id"),
            patch.object(wechat.settings, "WECHAT_APP_SECRET", "secret"),
            patch.object(wechat, "get_cursor", _gc(cursor)),
            patch.object(wechat, "exchange_login_code", return_value="trusted-openid"),
            patch.object(wechat, "exchange_phone_code", return_value=phone),
        )

    def test_bind_requires_phone_authorization(self):
        from modules.identity import wechat

        cursor = MagicMock()
        patches = self._runtime(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            with pytest.raises(BizError):
                wechat.wechat_login_session("code", None, bind_user_id=5)

    def test_bound_wechat_cannot_merge_other_account(self):
        from modules.identity import wechat

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "user_id": 7,
            "user_status": "active",
            "cred_status": "active",
            "phone": "13900000000",
            "unlinked_at": None,
        }
        patches = self._runtime(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with pytest.raises(BizError):
                wechat.wechat_login_session("code", "phone-code", bind_user_id=9)

    def test_bound_phone_mismatch_rejected(self):
        from modules.identity import wechat

        cursor = MagicMock()
        cursor.fetchone.return_value = {
            "user_id": 7,
            "user_status": "active",
            "cred_status": "active",
            "phone": "13800000000",
            "unlinked_at": None,
        }
        patches = self._runtime(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with pytest.raises(BizError):
                wechat.wechat_login_session("code", "phone-code")

    def test_bind_new_phone_must_match_login_phone(self):
        from modules.identity import wechat

        cursor = MagicMock()
        cursor.fetchone.side_effect = [None, None]
        patches = self._runtime(cursor)
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            with pytest.raises(BizError):
                wechat.wechat_login_session("code", "phone-code", bind_user_id=5)
