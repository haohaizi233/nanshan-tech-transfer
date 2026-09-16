"""联系方式共享必须得到明确授权的回归测试。"""

import unittest

from core.errors import BizError
from modules.cooperation.service import create_intent


class ContactShareConsentTests(unittest.TestCase):
    def test_missing_or_non_boolean_consent_is_rejected_before_database_access(self):
        base = {"targetType": "demand", "targetId": 1}
        for consent in (None, False, "true", 1):
            body = dict(base)
            if consent is not None:
                body["contactShareConsent"] = consent
            with self.assertRaises(BizError):
                create_intent(1, "u1", body)


if __name__ == "__main__":
    unittest.main()
