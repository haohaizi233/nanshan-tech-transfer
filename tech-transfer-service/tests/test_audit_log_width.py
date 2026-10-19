"""audit_log 列宽回归：写入值超过列宽时截断，不得让业务事务回滚。

背景（2026-10-19）：`POST /me/organization-membership-applications` 返回 500。
`membership.apply` 写入 `resource_type='organization_membership_application'`（35 字符），
而 audit_log.resource_type 当时是 VARCHAR(32) → psycopg2 22001 → 审计与业务同事务
→ 整个申请回滚并报 TT_COMMON_50001。修复分两层：
1. 代码层：resource_type 统一用短名 `membership_application`，并在写库前按列宽截断；
2. 数据库层：migrations/pg/028_audit_log_resource_type_width.sql 放宽到 VARCHAR(64)。
"""
from unittest.mock import MagicMock, patch

from modules.audit.service import (
    _MAX_ACTION,
    _MAX_RESOURCE_TYPE,
    _clip,
    record,
)
from modules.membership import service as membership_service

class TestClip:
    def test_short_value_untouched(self):
        assert _clip("achievement", _MAX_RESOURCE_TYPE) == "achievement"

    def test_none_stays_none(self):
        assert _clip(None, _MAX_RESOURCE_TYPE) is None

    def test_long_value_truncated_to_column_width(self):
        clipped = _clip("x" * 200, _MAX_RESOURCE_TYPE)
        assert clipped is not None
        assert len(clipped) == _MAX_RESOURCE_TYPE

    def test_non_string_coerced(self):
        assert _clip(12345, _MAX_ACTION) == "12345"

class TestAuditRecordClipsBeforeInsert:
    @patch("modules.audit.service.get_cursor")
    def test_long_resource_type_is_truncated(self, mock_gc):
        cur = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        record(
            action="membership.apply",
            resource_type="organization_membership_application",
            resource_id=1,
            actor_user_id=1,
            actor_user_no="U202600134",
        )

        values = cur.execute.call_args[0][1]
        assert len(values[3]) <= _MAX_RESOURCE_TYPE
        assert values[3] == "organization_membership_application"[: _MAX_RESOURCE_TYPE]

    @patch("modules.audit.service.get_cursor")
    def test_long_action_and_request_id_are_truncated(self, mock_gc):
        cur = MagicMock()
        mock_gc.return_value.__enter__ = MagicMock(return_value=cur)
        mock_gc.return_value.__exit__ = MagicMock(return_value=False)

        record(
            action="a" * 100,
            resource_type="membership_application",
            request_id="r" * 100,
        )

        values = cur.execute.call_args[0][1]
        assert len(values[2]) == _MAX_ACTION
        assert len(values[7]) == 64

class TestMembershipApplyAuditResourceType:
    """申请提交的审计 resource_type 必须落在列宽内，与其它成员申请动作一致。"""

    @patch("modules.membership.service.audit_record")
    @patch("modules.membership.service.transaction")
    def test_apply_writes_short_resource_type(self, mock_trans, mock_audit):
        conn = MagicMock()
        cur = MagicMock()
        conn.__enter__ = MagicMock(return_value=conn)
        conn.__exit__ = MagicMock(return_value=False)
        conn.cursor.return_value = cur
        cur.__enter__ = MagicMock(return_value=cur)
        cur.__exit__ = MagicMock(return_value=False)
        mock_trans.return_value = conn
        cur.fetchone.side_effect = [
            {"id": 1},        # institution 存在
            None,             # 无有效成员关系
            None,             # 无待审申请
            {"id": 9, "user_id": 1, "org_id": 1, "status": "pending", "version": 1},
        ]

        membership_service.apply_membership({"userId": 1, "userNo": "U1"}, {"orgId": 1})

        action, resource_type = mock_audit.call_args[0][0], mock_audit.call_args[0][1]
        assert action == "membership.apply"
        assert resource_type == "membership_application"
        assert len(resource_type) <= _MAX_RESOURCE_TYPE
