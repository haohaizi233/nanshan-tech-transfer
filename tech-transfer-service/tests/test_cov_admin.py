"""Coverage boost for modules/admin/service.py — pure unit tests with mocked DB cursor.

每个目标函数一条 happy-path 测试（admin_review_cooperation 三条覆盖 accept/reject/assisted 冲突分支）。
统一使用胖字典 FAT 作为 mock 行，仅在调用序列确实不同的场景使用 side_effect 精确映射。
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError

# ── 胖字典：覆盖所有行映射器读取的列（数值列用真实 int/float，时间列用真实 datetime）──

_TS = datetime(2026, 1, 1, 12, 0, 0)

FAT = {
    # 通用
    "id": 101,
    "c": 1,
    "name": "测试机构",
    "kind": "service",
    "title": "测试成果",
    "status": "published",
    "version": 1,
    "created_at": _TS,
    "updated_at": _TS,
    "published_at": _TS,
    "fetched_at": _TS,
    # achievement / demand 行
    "owner_user_id": 1,
    "org_id": 7,
    "category_id": 3,
    "category_name": "新材料",
    "category_code": "new-material",
    "institution_name": "测试机构",
    "source_org_name": "来源单位",
    "submitter_user_no": "U001",
    "submitter_name": "张三",
    "view_count": 5,
    "tech_intro": "技术简介",
    "tech_route": "技术路线",
    "maturity_level": "lab",
    "maturity_desc": "实验室阶段",
    "pricing_mode": "fixed",
    "price_min_wan": 10.0,
    "price_max_wan": 20.0,
    "application_fields": ["机械", "电子"],
    "innovation_points": ["创新一"],
    "reject_reason": None,
    "contact_name": "李四",
    "contact_title": "主任",
    "contact_phone": "13800000000",
    "contact_email": "a@b.com",
    "contact_wechat": "wx001",
    "description": "需求描述",
    "coop_mode": '["许可"]',
    "org_intro": "机构简介",
    "org_name": "测试机构",
    "region": "深圳",
    "budget_min_wan": 10,
    "budget_max_wan": 20,
    "budget_negotiable": True,
    # institution 行
    "intro": "机构简介",
    "detail_info": "机构详情",
    "label": "标签",
    "logo_file_id": "",
    "sort_order": 1,
    "user_type": "enterprise",
    "support_unit": "支持单位",
    "functions": "职能",
    "contact_person": "李四",
    "contact_mobile": "13800000000",
    "platform_type": "概念验证中心",
    "platform_type_key": "poc",
    "serial_no": 8,
    "source_pk": 101,
    "source_status": 1,
    "order_num": 2,
    "source_site": "site",
    "source_api": "api",
    # user 行 / 统计
    "user_no": "U001",
    "display_name": "张三",
    "phone": "13800000000",
    "email": "a@b.com",
    "org_title": "主任",
    "roles": ["org_admin"],
    "memberships": [{"id": 1, "org_id": 7, "org_name": "测试机构", "role": "admin", "status": "active", "version": 1}],
    "ach_count": 3,
    "dmd_count": 2,
    "coop_count": 1,
    "fav_count": 4,
    # cooperation 行 / 事件
    "initiator_user_id": 2,
    "initiator_user_no": "U002",
    "initiator_name": "王五",
    "target_owner_user_id": 3,
    "target_owner_user_no": "U003",
    "target_owner_name": "赵六",
    "target_type": "achievement",
    "target_id": 101,
    "target_title": "测试成果",
    "intent_type": "cooperation",
    "message": "希望合作",
    "handling_mode": "direct",
    "assist_status": None,
    "accept_mode": None,
    "handled_by_user_id": None,
    "target_org_id": 7,
    "target_org_name": "测试机构",
    "initiator_contact_snapshot": None,
    "assist_note": None,
    "contact_share_consent_at": None,
    "accepted_at": None,
    "confirmed_at": None,
    "completed_at": None,
    "closed_at": None,
    "slot_reserved": False,
    "event_type": "accepted",
    "from_status": "pending",
    "to_status": "accepted",
    "operator_user_id": 9,
    "operator_role": "admin",
    "remark": "备注",
    "cooperation_policy": "parallel",
    "cooperation_remaining": None,
    # load_content 子表行
    "section_code": "overview",
    "content": "段落内容",
    "patent_no": "CN123",
    "patent_title": "专利名称",
    "is_primary": True,
    "external_url": "https://example.com",
    "link_type": "video",
    "url": "https://example.com/v",
    "file_id": 55,
    "media_role": "cover",
    "caption": "图注",
    "alt_text": "替代文本",
    "original_name": "a.png",
    "mime_type": "image/png",
    "size_bytes": 1234,
    "code": "MAT",
    "parent_id": None,
    "contribution": "核心贡献",
    # admin_edit_log
    "batch_id": 77,
    # demand_tag 关联
    "demand_id": 101,
}

ADMIN = {"userId": 9, "userNo": "A9"}
PLATFORM_SCOPE = {"isPlatformAdmin": True, "userId": 9, "userNo": "A9"}
ORG_SCOPE = {"isPlatformAdmin": False, "userId": 2, "userNo": "U002", "orgIds": [7]}


def _cur(**overrides):
    cur = MagicMock()
    cur.fetchone.return_value = dict(FAT, **overrides) if overrides else dict(FAT)
    cur.fetchall.return_value = [dict(FAT)]
    cur.rowcount = 1
    return cur


def _wire(mock_gc, cur):
    mock_gc.return_value.__enter__.return_value = cur
    mock_gc.return_value.__exit__.return_value = False


# ── 审核 / 下架 / 关闭 ───────────────────────────────────────


class TestReviewAndOffline:
    @patch("modules.admin.service.get_cursor")
    def test_review_achievement_approve(self, mock_gc):
        from modules.admin.service import review_achievement

        cur = _cur(status="pending_review", version=1, owner_user_id=1)
        _wire(mock_gc, cur)

        result = review_achievement(ADMIN, 21, {"_action": "approve", "version": 1}, request_id="req-1")

        assert result == {"status": "published"}
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("UPDATE achievement" in s and "published" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_review_demand_reject(self, mock_gc):
        from modules.admin.service import review_demand

        cur = _cur(status="pending_review", version=1, owner_user_id=1)
        _wire(mock_gc, cur)

        result = review_demand(ADMIN, 22, {"_action": "reject", "version": 1, "reason": "材料不全"})

        assert result == {"status": "rejected"}
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("UPDATE demand" in s and "rejected" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_offline_achievement_admin(self, mock_gc):
        from modules.admin.service import offline_achievement_admin

        cur = _cur(status="published", owner_user_id=1)
        _wire(mock_gc, cur)

        result = offline_achievement_admin(
            PLATFORM_SCOPE, 21, {"version": 1, "reasonCode": "expired", "reason": "已过期"}, request_id="req-2"
        )

        assert result == {"status": "offline"}

    @patch("modules.admin.service.get_cursor")
    def test_close_demand_admin(self, mock_gc):
        from modules.admin.service import close_demand_admin

        cur = _cur(status="published", owner_user_id=1)
        _wire(mock_gc, cur)

        result = close_demand_admin(
            PLATFORM_SCOPE, 22, {"version": 1, "reasonCode": "fulfilled", "reasonNote": "已解决"}, request_id="req-3"
        )

        assert result == {"status": "closed"}


# ── Institution 管理 ─────────────────────────────────────────


class TestInstitutionAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_list_institutions_admin(self, mock_gc):
        from modules.admin.service import list_institutions_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = list_institutions_admin({"page": 1, "pageSize": 10})

        assert result["total"] == 1
        assert result["totalPages"] == 1
        item = result["list"][0]
        assert item["id"] == 101
        assert item["kind"] == "service"
        assert item["name"] == "测试机构"
        assert item["serialNo"] == 8
        assert item["logoUrl"] == ""

    @patch("modules.admin.service.get_cursor")
    def test_get_institution_admin(self, mock_gc):
        from modules.admin.service import get_institution_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = get_institution_admin(101)

        assert result["id"] == 101
        assert result["kind"] == "service"
        assert result["platformTypeKey"] == "poc"
        assert result["createdAt"] == _TS.isoformat()

    @patch("modules.admin.service.get_cursor")
    def test_create_institution(self, mock_gc):
        from modules.admin.service import create_institution

        cur = _cur(name="新机构", kind="service", status="active")
        _wire(mock_gc, cur)

        result = create_institution(ADMIN, {"name": "新机构", "kind": "service", "region": "深圳"}, request_id="req-4")

        assert result["name"] == "新机构"
        assert result["kind"] == "service"
        assert result["status"] == "active"
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO institution" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_update_institution(self, mock_gc):
        from modules.admin.service import update_institution

        cur = _cur()
        _wire(mock_gc, cur)

        result = update_institution(ADMIN, 101, {"intro": "新简介"}, request_id="req-5")

        assert result["id"] == 101
        update_calls = [c for c in cur.execute.call_args_list if "UPDATE institution" in c.args[0]]
        assert update_calls
        assert list(update_calls[0].args[1]) == ["新简介", 101]

    @patch("modules.admin.service.get_cursor")
    def test_set_institution_status(self, mock_gc):
        from modules.admin.service import set_institution_status

        cur = _cur(id=5, status="active", name="机构A")
        _wire(mock_gc, cur)

        result = set_institution_status(ADMIN, 5, "offline", request_id="req-6")

        assert result == {"status": "disabled"}

    @patch("modules.admin.service.get_cursor")
    def test_import_institutions_update_branch(self, mock_gc):
        from modules.admin.service import import_institutions

        cur = MagicMock()
        cur.fetchone.side_effect = [{"id": 7}, {"id": 7}]
        cur.rowcount = 1
        _wire(mock_gc, cur)

        result = import_institutions(
            ADMIN,
            {"items": [{"kind": "invest", "name": "资本方", "sourcePk": 101, "region": "深圳"}]},
            request_id="req-7",
        )

        assert result["created"] == 0
        assert result["updated"] == 1
        assert result["total"] == 1
        assert result["list"][0]["action"] == "update"
        assert result["list"][0]["id"] == 7
        assert result["list"][0]["name"] == "资本方"

    @patch("modules.admin.service.get_cursor")
    def test_delete_institution(self, mock_gc):
        from modules.admin.service import delete_institution

        cur = MagicMock()
        cur.fetchone.side_effect = [{"id": 3, "name": "机构A", "kind": "service"}, None, None, None, None]
        cur.rowcount = 1
        _wire(mock_gc, cur)

        result = delete_institution(ADMIN, 3, request_id="req-8")

        assert result == {"id": 3, "deleted": True}
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("DELETE FROM institution" in s for s in sqls)


# ── Cooperation 管理 ─────────────────────────────────────────


class TestCooperationAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_list_cooperations_admin(self, mock_gc):
        from modules.admin.service import list_cooperations_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = list_cooperations_admin({"page": 1, "pageSize": 10}, PLATFORM_SCOPE)

        assert result["total"] == 1
        item = result["list"][0]
        assert item["id"] == 101
        assert item["targetType"] == "achievement"
        assert item["initiatorUserId"] == 2
        assert item["handlingMode"] == "direct"

    @patch("modules.admin.service.get_cursor")
    def test_get_cooperation_admin(self, mock_gc):
        from modules.admin.service import get_cooperation_admin

        cur = _cur(status="pending")
        _wire(mock_gc, cur)

        result = get_cooperation_admin(101, PLATFORM_SCOPE)

        assert result["id"] == 101
        assert result["canReview"] is True
        assert len(result["events"]) == 1
        assert result["events"][0]["eventType"] == "accepted"
        assert result["events"][0]["createdAt"] == _TS.isoformat()

    @patch("modules.admin.service.get_cursor")
    def test_admin_review_cooperation_accept(self, mock_gc):
        from modules.admin.service import admin_review_cooperation

        cur = MagicMock()
        cur.fetchone.side_effect = [
            # 主 SELECT ... FOR UPDATE OF ci
            dict(FAT, id=501, status="pending", handling_mode="direct", slot_reserved=False, version=1),
            # _reserve_target_slot 的目标行：published + 不限量 → 提前返回
            dict(FAT, status="published", cooperation_remaining=None, cooperation_policy="parallel"),
            # emit_notification 的 RETURNING id
            dict(FAT),
            # 返回值 get_cooperation_admin 的详情行（受理后状态）
            dict(FAT, id=501, status="accepted"),
        ]
        cur.fetchall.side_effect = [
            [{"id": 502}],  # 同目标其他 pending → 自动驳回
            [dict(FAT)],  # cooperation_event
        ]
        cur.rowcount = 1
        _wire(mock_gc, cur)

        result = admin_review_cooperation(PLATFORM_SCOPE, 501, {"version": 1}, "accept", request_id="req-9")

        assert result["status"] == "accepted"
        assert result["canReview"] is False
        assert result["events"][0]["eventType"] == "accepted"
        # 自动驳回同目标的其他 pending 对接
        executed_params = [c.args[1] for c in cur.execute.call_args_list if len(c.args) > 1]
        assert (502,) in [tuple(p) for p in executed_params]

    @patch("modules.admin.service.get_cursor")
    def test_admin_review_cooperation_reject(self, mock_gc):
        from modules.admin.service import admin_review_cooperation

        cur = MagicMock()
        cur.fetchone.side_effect = [
            dict(FAT, id=501, status="pending", handling_mode="direct", slot_reserved=True, version=1),
            dict(FAT),  # emit_notification RETURNING id
            dict(FAT, id=501, status="rejected"),  # get_cooperation_admin 详情行
        ]
        cur.fetchall.side_effect = [[dict(FAT)]]  # cooperation_event
        cur.rowcount = 1
        _wire(mock_gc, cur)

        result = admin_review_cooperation(
            PLATFORM_SCOPE, 501, {"version": 1, "reason": "不匹配"}, "reject", request_id="req-10"
        )

        assert result["status"] == "rejected"
        assert result["canReview"] is False
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("slot_reserved=FALSE" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_admin_review_cooperation_assisted_conflict(self, mock_gc):
        from modules.admin.service import admin_review_cooperation

        cur = _cur(id=501, status="pending", handling_mode="assisted", initiator_user_id=2, version=1)
        _wire(mock_gc, cur)

        with pytest.raises(BizError) as exc_info:
            admin_review_cooperation(PLATFORM_SCOPE, 501, {"version": 1}, "accept")

        assert "协助" in str(exc_info.value)


# ── 内容归属认领 ─────────────────────────────────────────────


class TestClaimUnassigned:
    @patch("modules.admin.service.audit_record")
    @patch("modules.admin.service.get_cursor")
    def test_claim_unassigned_content(self, mock_gc, mock_audit):
        from modules.admin.service import claim_unassigned_content

        cur = MagicMock()
        cur.fetchone.side_effect = [
            {"id": 11, "org_id": None, "owner_user_id": 5, "version": 3},  # 内容行
            {"1": 1},  # 归属人是否在本机构
            {"name": "某某机构"},  # 机构名
            {"id": 11, "org_id": 7, "version": 4},  # UPDATE ... RETURNING
        ]
        _wire(mock_gc, cur)

        result = claim_unassigned_content(ORG_SCOPE, "achievement", 11, 3, request_id="req-11")

        assert result == {"id": 11, "orgId": 7, "version": 4}
        mock_audit.assert_called_once()
        assert mock_audit.call_args.args[0] == "achievement.organization_claim"


# ── 成果 / 需求详情与列表 ────────────────────────────────────


class TestContentRead:
    @patch("modules.admin.service.get_cursor")
    def test_get_achievement_admin(self, mock_gc):
        from modules.admin.service import get_achievement_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = get_achievement_admin(101, PLATFORM_SCOPE)

        assert result["id"] == 101
        assert result["title"] == "测试成果"
        assert result["statusLabel"] == "已发布"
        assert result["priceMinWan"] == 10.0
        assert result["priceMaxWan"] == 20.0
        assert result["applicationFields"] == ["机械", "电子"]
        assert result["innovationPoints"] == ["创新一"]
        assert result["inventors"][0]["name"] == "测试机构"
        assert result["sections"][0]["code"] == "overview"
        assert result["patents"][0]["patentNo"] == "CN123"
        assert result["media"][0]["fileId"] == 55

    @patch("modules.admin.service.get_cursor")
    def test_get_demand_admin(self, mock_gc):
        from modules.admin.service import get_demand_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = get_demand_admin(101, PLATFORM_SCOPE)

        assert result["id"] == 101
        assert result["budget"] == "10万-20万元"
        assert result["budgetMinWan"] == 10.0
        assert result["description"] == "需求描述"
        assert result["tags"] == ["测试机构"]


# ── 用户管理 ─────────────────────────────────────────────────


class TestUsersAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_list_users_admin(self, mock_gc):
        from modules.admin.service import list_users_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = list_users_admin({"page": 1, "pageSize": 10}, PLATFORM_SCOPE)

        assert result["total"] == 1
        item = result["list"][0]
        assert item["userId"] == 101
        assert item["userNo"] == "U001"
        assert item["roles"] == ["org_admin"]
        assert item["organizationMemberships"][0]["orgId"] == 7

    @patch("modules.admin.service.get_cursor")
    def test_get_user_admin(self, mock_gc):
        from modules.admin.service import get_user_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = get_user_admin(101, PLATFORM_SCOPE)

        assert result["userId"] == 101
        assert result["userNo"] == "U001"
        assert result["statistics"] == {
            "achievementCount": 3,
            "demandCount": 2,
            "cooperationCount": 1,
            "favoriteCount": 4,
        }


# ── 成果 / 需求后台录入与编辑 ────────────────────────────────


class TestContentWrite:
    @patch("modules.admin.service.get_cursor")
    def test_create_achievement_admin(self, mock_gc):
        from modules.admin.service import create_achievement_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = create_achievement_admin(
            PLATFORM_SCOPE, {"title": "新成果", "categoryId": 3, "orgId": 7}, request_id="req-12"
        )

        assert result["id"] == 101
        assert result["title"] == "测试成果"
        assert result["priceMinWan"] == 10.0
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO achievement" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_update_achievement_admin(self, mock_gc):
        from modules.admin.service import update_achievement_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = update_achievement_admin(PLATFORM_SCOPE, 101, {"version": 1, "title": "改后标题"}, request_id="req-13")

        assert result["id"] == 101
        update_calls = [c for c in cur.execute.call_args_list if "UPDATE achievement" in c.args[0]]
        assert update_calls
        assert list(update_calls[0].args[1]) == ["改后标题", 101, 1]

    @patch("modules.admin.service.get_cursor")
    def test_create_demand_admin(self, mock_gc):
        from modules.admin.service import create_demand_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = create_demand_admin(
            PLATFORM_SCOPE,
            {"title": "新需求", "description": "需求描述", "categoryId": 3, "orgId": 7},
            request_id="req-14",
        )

        assert result["id"] == 101
        assert result["budget"] == "10万-20万元"
        assert result["tags"] == ["测试机构"]
        sqls = [c.args[0] for c in cur.execute.call_args_list]
        assert any("INSERT INTO demand" in s for s in sqls)

    @patch("modules.admin.service.get_cursor")
    def test_update_demand_admin(self, mock_gc):
        from modules.admin.service import update_demand_admin

        cur = _cur()
        _wire(mock_gc, cur)

        result = update_demand_admin(PLATFORM_SCOPE, 101, {"version": 1, "title": "改后需求"}, request_id="req-15")

        assert result["id"] == 101
        update_calls = [c for c in cur.execute.call_args_list if "UPDATE demand" in c.args[0]]
        assert update_calls
        assert list(update_calls[0].args[1]) == ["改后需求", 101, 1]


# ── 代平台录入内容提交审核 ───────────────────────────────────


class TestSubmitAdmin:
    @patch("modules.admin.service.get_cursor")
    def test_submit_achievement_admin(self, mock_gc):
        from modules.admin.service import submit_achievement_admin

        cur = _cur(status="draft", version=1, owner_user_id=None)
        _wire(mock_gc, cur)

        result = submit_achievement_admin(ADMIN, 21, {"version": 1}, request_id="req-16")

        assert result == {"status": "pending_review"}

    @patch("modules.admin.service.get_cursor")
    def test_submit_demand_admin(self, mock_gc):
        from modules.admin.service import submit_demand_admin

        cur = _cur(status="rejected", version=1, owner_user_id=None)
        _wire(mock_gc, cur)

        result = submit_demand_admin(ADMIN, 22, {"version": 1}, request_id="req-17")

        assert result == {"status": "pending_review"}
