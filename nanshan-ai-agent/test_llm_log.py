import json
import tempfile
import unittest
from pathlib import Path

from app.llm_log import enrich_event, format_llm_log_text, rebuild_readable_log


class LlmLogFormatTest(unittest.TestCase):
    def test_summarize_and_parse_router_output(self):
        event = {
            "ts": "2026-09-21 17:00:00",
            "ok": True,
            "model": "Qwen",
            "status": 200,
            "attempt": 1,
            "attempts": 3,
            "input": {
                "messages": [
                    {
                        "role": "system",
                        "content": "你是“南山科转通”平台的业务查询参数解析器。\n后面还有很长的规则。",
                    },
                    {"role": "user", "content": "找机器视觉相关的科技成果"},
                ]
            },
            "output": (
                "Here's a thinking process:\n\n1. Analyze\n"
                "```json\n{\"intent\":\"wrong\"}\n```\n"
                'Final: {"intent": "search_achievement", "keywords": ["机器视觉"], "reason": "用户在找成果"}'
            ),
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "total_time": 1.2,
            },
        }
        rec = enrich_event(event)
        self.assertEqual(rec["stage"], "意图解析")
        self.assertEqual(rec["user"], "找机器视觉相关的科技成果")
        self.assertEqual(rec["output_json"]["intent"], "search_achievement")
        self.assertEqual(rec["output_json"]["keywords"], ["机器视觉"])
        text = format_llm_log_text(event)
        self.assertIn("找机器视觉相关的科技成果", text)
        self.assertIn('"intent": "search_achievement"', text)
        self.assertIn("成功", text)
        console = format_llm_log_text(event, include_raw=False)
        self.assertNotIn("原始输出", console)

    def test_rebuild_readable_log(self):
        records = [
            {
                "ts": "2026-09-21 17:01:00",
                "ok": True,
                "input": {
                    "messages": [
                        {
                            "role": "system",
                            "content": "你是“南山科转通”的科技成果与技术需求搜索结果重排器。",
                        },
                        {"role": "user", "content": "原始问题"},
                    ]
                },
                "output": '{"results": [{"id": "1", "score": 0.9}]}',
            },
            {
                "ts": "2026-09-21 17:02:00",
                "ok": False,
                "reason": "http_error",
                "status": 502,
                "error": {"type": "HTTPError", "message": "HTTP 502"},
                "input": {"messages": [{"role": "user", "content": "你好"}]},
            },
        ]
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "llm-2026-09-21.jsonl"
            out = Path(tmp) / "llm-2026-09-21.log"
            jsonl.write_text(
                "\n".join(json.dumps(item, ensure_ascii=False) for item in records),
                encoding="utf-8",
            )
            count = rebuild_readable_log(jsonl, out)
            self.assertEqual(count, 2)
            text = out.read_text(encoding="utf-8")
            self.assertIn("重排", text)
            self.assertIn("失败", text)
            self.assertIn("原始问题", text)
            self.assertIn('"id": "1"', text)


if __name__ == "__main__":
    unittest.main()
