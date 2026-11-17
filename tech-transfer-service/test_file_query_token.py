"""File GET can authenticate WeChat <image> requests via access_token query."""

import unittest
from unittest.mock import patch

from core.jwt_utils import sign_access_token
from core.middleware import identity_from_access_token


class FileQueryTokenTests(unittest.TestCase):
    def test_valid_access_token_returns_user_id(self):
        token = sign_access_token(7, "U7", ["user"])
        # _user_is_active 和 _user_session_version 会连库校验，单元测试打桩隔离
        with (
            patch("core.middleware._user_is_active", return_value=True),
            patch("core.middleware._user_session_version", return_value=1),
        ):
            identity = identity_from_access_token(token)
        self.assertEqual(identity["userId"], 7)
        self.assertEqual(identity["userNo"], "U7")

    def test_invalid_or_empty_token_stays_anonymous(self):
        self.assertIsNone(identity_from_access_token(""))
        self.assertIsNone(identity_from_access_token("not-a-jwt"))


if __name__ == "__main__":
    unittest.main()
