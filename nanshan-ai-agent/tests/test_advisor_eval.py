import json
from pathlib import Path
import unittest


class AdvisorEvalTests(unittest.TestCase):
    def test_fixed_corpus_covers_eighty_distinct_queries_and_required_categories(self):
        path = Path(__file__).resolve().parents[1] / "evals" / "advisor_cases.json"
        self.assertTrue(path.exists(), "missing fixed evaluation corpus")
        corpus = json.loads(path.read_text(encoding="utf-8"))
        cases = corpus["cases"]
        self.assertGreaterEqual(len(cases), 80)
        self.assertEqual(len({case["id"] for case in cases}), len(cases))
        self.assertEqual(len({case["message"] for case in cases}), len(cases))
        for category, count in {"search": 20, "followup": 15, "reference": 15, "empty_conflict": 10, "guide": 10, "security": 10}.items():
            self.assertGreaterEqual(sum(case["category"] == category for case in cases), count)
        record_ids = {row["id"] for row in corpus["records"]}
        for case in cases:
            self.assertTrue(case["expected"]["kind"] in {"results", "clarify", "guide", "empty", "rejected"})
            self.assertTrue(set(case["expected"].get("ids", [])) <= record_ids)

    def test_metrics_do_not_treat_missing_provider_usage_as_zero(self):
        from evals.run_advisor_eval import summarize
        result = summarize([{"id": "one", "passed": True, "latencyMs": 1.0, "modelCalls": 0, "hitAt5": None, "violations": []}], "offline")
        self.assertIsNone(result["providerTokens"])
        self.assertEqual(result["mode"], "offline")
        self.assertEqual(result["passed"], 1)

    def test_in_memory_retrieval_never_relaxes_owner_price_or_publication(self):
        from evals.run_advisor_eval import search_records
        records = [
            {"id": 1, "card_type": "achievement", "title": "机器视觉", "status": "published", "owner_user_id": 9, "price_max_wan": 5},
            {"id": 2, "card_type": "achievement", "title": "机器视觉", "status": "published", "owner_user_id": 8, "price_max_wan": None},
            {"id": 3, "card_type": "achievement", "title": "机器视觉", "status": "draft", "owner_user_id": 8, "price_max_wan": 5},
            {"id": 4, "card_type": "achievement", "title": "机器视觉", "status": "published", "owner_user_id": 8, "price_max_wan": 5},
        ]
        self.assertEqual([row["id"] for row in search_records(records, "achievement", keywords=["机器视觉"], max_price_wan=10, exclude_owner_user_id=9)], [4])

    def test_baseline_requires_identical_corpus_and_missing_hits_are_not_zero(self):
        from evals.run_advisor_eval import compare_baseline
        baseline = {"mode": "offline", "corpusSha256": "same", "results": [{"id": "guide"}], "hitAt5": None}
        current = dict(baseline)
        self.assertIsNone(compare_baseline(current, baseline))
        with self.assertRaises(ValueError):
            compare_baseline(current, {**baseline, "corpusSha256": "different"})
