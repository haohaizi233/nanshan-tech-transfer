from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest

from core.errors import BizError
from modules.profile import service


def test_profile_avatar_requires_owned_active_image_and_persists_file_id():
    cursor = MagicMock()
    cursor.fetchone.return_value = {"id": 9}

    @contextmanager
    def transaction(**kwargs):
        yield cursor

    with patch.object(service, "get_cursor", transaction), patch.object(service, "build_user_response", return_value={"avatarFileId": 9}):
        result = service.update_my_profile(7, {"version": 1, "avatarFileId": 9})
    assert result["avatarFileId"] == 9
    statements = cursor.execute.call_args_list
    assert "file_object" in statements[0].args[0]
    assert "created_by" in statements[0].args[0]
    assert "mime_type" in statements[0].args[0]
    assert "FOR SHARE" in statements[0].args[0]
    assert "avatar_file_id=%s" in statements[1].args[0]
    assert statements[1].args[1] == [9, 7, 1]


def test_profile_rejects_avatar_from_another_account_or_a_non_image():
    cursor = MagicMock()
    cursor.fetchone.return_value = None
    context = MagicMock()
    context.__enter__.return_value = cursor
    with patch.object(service, "get_cursor", return_value=context):
        with pytest.raises(BizError):
            service.update_my_profile(7, {"version": 1, "avatarFileId": 9})
    assert cursor.execute.call_count == 1
    assert "SELECT" in cursor.execute.call_args.args[0]


@pytest.mark.parametrize("file_id", [True, -1, "9", 0])
def test_avatar_file_id_is_a_strict_positive_integer(file_id):
    with pytest.raises(BizError):
        service.update_my_profile(7, {"version": 1, "avatarFileId": file_id})
