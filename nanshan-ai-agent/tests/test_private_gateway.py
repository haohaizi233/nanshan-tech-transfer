from pathlib import Path
import re
import unittest


class PrivateGatewayTests(unittest.TestCase):
    def test_public_gateway_explicitly_rejects_internal_agent_paths(self):
        root = Path(__file__).resolve().parents[2]
        content = (root / "deploy" / "Caddyfile").read_text(encoding="utf-8")
        self.assertRegex(content, re.compile(r'handle /internal/\*\s*\{\s*respond\s+"Not Found"\s+404\s*\}'))
