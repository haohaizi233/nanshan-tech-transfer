"""一键启动器的前端新鲜度判断测试。"""
import os
import tempfile
import unittest
from pathlib import Path

import start_dev


class FrontendFreshnessTests(unittest.TestCase):
    def test_marks_output_stale_when_a_source_file_is_newer(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "src" / "App.vue"
            output = root / "dist" / "index.html"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            source.write_text("new", encoding="utf-8")
            output.write_text("old", encoding="utf-8")
            os.utime(output, (100, 100))
            os.utime(source, (101, 101))

            self.assertTrue(start_dev.output_is_stale([source], output))

    def test_keeps_output_when_all_sources_are_older(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "src" / "App.vue"
            output = root / "dist" / "index.html"
            source.parent.mkdir(parents=True)
            output.parent.mkdir(parents=True)
            source.write_text("old", encoding="utf-8")
            output.write_text("new", encoding="utf-8")
            os.utime(source, (100, 100))
            os.utime(output, (101, 101))

            self.assertFalse(start_dev.output_is_stale([source], output))

    def test_marks_missing_output_as_stale(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            source = root / "pages" / "index.vue"
            source.parent.mkdir(parents=True)
            source.write_text("source", encoding="utf-8")

            self.assertTrue(start_dev.output_is_stale([source], root / "missing" / "index.html"))


if __name__ == "__main__":
    unittest.main()
