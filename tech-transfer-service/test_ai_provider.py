"""AiProvider JSON 解析单测（不打外部 HTTP，不碰 8787）。"""
import unittest

from modules.ai.provider import AiProviderError, parse_json_content


class ParseJsonContentTest(unittest.TestCase):
    def test_plain_object(self):
        self.assertEqual(parse_json_content('{"results":[]}'), {"results": []})

    def test_fenced_block(self):
        raw = "```json\n{\"totalScore\": 80}\n```"
        self.assertEqual(parse_json_content(raw)["totalScore"], 80)

    def test_leading_prose(self):
        raw = '好的，结果如下：\n{"scores": {"techFeature": 1}}\n'
        self.assertEqual(parse_json_content(raw)["scores"]["techFeature"], 1)

    def test_empty_raises(self):
        with self.assertRaises(AiProviderError):
            parse_json_content("   ")


if __name__ == "__main__":
    unittest.main()
