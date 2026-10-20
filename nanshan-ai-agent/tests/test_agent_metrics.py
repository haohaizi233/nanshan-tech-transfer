import unittest

from app import runtime_trace


class AgentMetricsTests(unittest.TestCase):
    def test_metrics_only_allow_fixed_names_and_numeric_values(self):
        with self.assertLogs("nanshan.ai.trace", level="INFO") as logs:
            runtime_trace.trace_count("candidate_count", 3)
            runtime_trace.trace_count("private-user-query", 99)
            runtime_trace.trace_degradation("small_candidate_set")
            runtime_trace.trace_degradation("private-user-query")
        self.assertEqual(len(logs.output), 2)
        self.assertIn("candidate_count", logs.output[0])
        self.assertNotIn("private-user-query", " ".join(logs.output))


if __name__ == "__main__":
    unittest.main()
