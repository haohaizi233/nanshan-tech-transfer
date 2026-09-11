"""一键启动器的前端新鲜度判断测试。"""
import os
import sys
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


class SpawnChildDetectionTests(unittest.TestCase):
    """uvicorn reload worker（multiprocessing spawn 子进程）的枚举逻辑。"""

    def test_finds_spawn_child_by_parent_pid(self):
        original = start_dev._python_processes_with_cmdline
        try:
            start_dev._python_processes_with_cmdline = lambda: [
                (14520, r"C:\python.exe C:\南山小程序\start_dev.py"),
                (14404, '"C:\\python.exe" "-c" "from multiprocessing.spawn import spawn_main; '
                        'spawn_main(parent_pid=30584, pipe_handle=504)" "--multiprocessing-fork"'),
                (999, '"C:\\python.exe" "-c" "spawn_main(parent_pid=11111, pipe_handle=1)"'),
            ]
            self.assertEqual(start_dev._spawn_child_pids([30584]), [14404])
            self.assertEqual(start_dev._spawn_child_pids([11111]), [999])
            self.assertEqual(start_dev._spawn_child_pids([42]), [])
        finally:
            start_dev._python_processes_with_cmdline = original

    def test_ignores_non_spawn_python_processes(self):
        original = start_dev._python_processes_with_cmdline
        try:
            start_dev._python_processes_with_cmdline = lambda: [
                (14520, r"C:\python.exe C:\南山小程序\start_dev.py"),
                (200, r"C:\python.exe -u app.py"),
            ]
            self.assertEqual(start_dev._spawn_child_pids([14520, 200]), [])
        finally:
            start_dev._python_processes_with_cmdline = original

    def test_processes_with_cmdline_parses_single_object_and_array(self):
        import json as json_mod

        class FakeCompleted:
            def __init__(self, payload):
                self.stdout = payload

        cases = [
            (json_mod.dumps([{"ProcessId": 1, "CommandLine": "a"},
                             {"ProcessId": 2, "CommandLine": "b"}]), [(1, "a"), (2, "b")]),
            (json_mod.dumps({"ProcessId": 7, "CommandLine": "c"}), [(7, "c")]),
            ("", []),
            ("not json", []),
        ]
        original_run = start_dev.subprocess.run
        try:
            for payload, expected in cases:
                start_dev.subprocess.run = lambda *a, **k: FakeCompleted(payload)
                self.assertEqual(start_dev._python_processes_with_cmdline(), expected)
        finally:
            start_dev.subprocess.run = original_run


class CaddyLauncherTests(unittest.TestCase):
    def test_default_site_is_inanshan(self):
        previous = os.environ.pop("NS_SITE", None)
        try:
            self.assertEqual(start_dev.caddy_site(), "inanshan.sjhcip.com")
        finally:
            if previous is None:
                os.environ.pop("NS_SITE", None)
            else:
                os.environ["NS_SITE"] = previous

    def test_ns_site_env_overrides_domain(self):
        previous = os.environ.get("NS_SITE")
        os.environ["NS_SITE"] = "demo.example.com"
        try:
            self.assertEqual(start_dev.caddy_site(), "demo.example.com")
        finally:
            if previous is None:
                os.environ.pop("NS_SITE", None)
            else:
                os.environ["NS_SITE"] = previous

    def test_find_caddy_uses_caddy_home(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            exe = Path(temp_dir) / "caddy.exe"
            exe.write_bytes(b"fake")
            previous = os.environ.get("CADDY_HOME")
            os.environ["CADDY_HOME"] = str(Path(temp_dir))
            try:
                found, source = start_dev.find_caddy()
                self.assertEqual(found, exe)
                self.assertEqual(source, "环境变量 CADDY_HOME")
            finally:
                if previous is None:
                    os.environ.pop("CADDY_HOME", None)
                else:
                    os.environ["CADDY_HOME"] = previous

    def test_caddy_on_by_default_and_no_caddy_disables(self):
        original = sys.argv
        try:
            sys.argv = ["start_dev.py"]
            self.assertTrue(start_dev.parse_args().caddy)
            sys.argv = ["start_dev.py", "--no-caddy"]
            self.assertFalse(start_dev.parse_args().caddy)
        finally:
            sys.argv = original


if __name__ == "__main__":
    unittest.main()
