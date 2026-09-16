"""对接库存和结果记录的无数据库回归测试。"""
import unittest

from core.errors import BizError
from modules.cooperation import service


class FakeCursor:
    def __init__(self, row):
        self.row = row
        self.sql = []

    def execute(self, sql, params=None):
        self.sql.append((sql, params))

    def fetchone(self):
        return self.row


class CooperationGovernanceTests(unittest.TestCase):
    def test_limited_slot_is_reserved_atomically(self):
        cur = FakeCursor({'cooperation_policy': 'parallel', 'cooperation_remaining': 1, 'status': 'published'})
        result = service._reserve_target_slot(cur, {'target_type': 'demand', 'target_id': 7}, 99)
        self.assertEqual(result, {'reserved': True, 'closePending': True})
        self.assertIn('cooperation_remaining=cooperation_remaining-1', cur.sql[1][0])
        self.assertIn('slot_reserved=TRUE', cur.sql[2][0])

    def test_unlimited_parallel_does_not_consume_or_close_other_requests(self):
        cur = FakeCursor({'cooperation_policy': 'parallel', 'cooperation_remaining': None, 'status': 'published'})
        self.assertEqual(
            service._reserve_target_slot(cur, {'target_type': 'achievement', 'target_id': 7}, 99),
            {'reserved': False, 'closePending': False},
        )

    def test_invalid_outcome_is_rejected_before_database_access(self):
        with self.assertRaises(BizError):
            service.complete_intent(1, 'u1', 1, 1, None, outcome={'status': 'bad'})
        with self.assertRaises(BizError):
            service.complete_intent(1, 'u1', 1, 1, None, outcome={'status': 'not_cooperated'})


if __name__ == '__main__':
    unittest.main()
