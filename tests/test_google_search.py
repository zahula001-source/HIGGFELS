"""Check address-bar search in isolated profiles using the real profile runner."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import browser
from app.search_settings import google_search_extension


class GoogleSearchTests(unittest.TestCase):
    def test_manifest_configures_google_only(self):
        with tempfile.TemporaryDirectory(prefix="search_manifest_", dir=browser.DATA_DIR) as folder:
            path = Path(google_search_extension(folder))
            manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
            provider = manifest["chrome_settings_overrides"]["search_provider"]
            self.assertTrue(provider["is_default"])
            self.assertEqual(provider["search_url"], "https://www.google.com/search?q={searchTerms}")
            self.assertNotIn("permissions", manifest)

    def test_real_runner_defaults_to_google_on_both_engines(self):
        from playwright.sync_api import sync_playwright
        for engine in ("chrome", "cloakbrowser"):
            with self.subTest(engine=engine):
                with tempfile.TemporaryDirectory(prefix="search_browser_", dir=browser.DATA_DIR) as folder:
                    root = Path(folder)
                    profile_dir = root / "profile"
                    profile_dir.mkdir()
                    code = browser.get_chromium_runner_simple(
                        "search_test", "Search test", str(profile_dir), None,
                        {"random_id": 123456}, enable_ext=False, engine=engine, headless=True,
                    )
                    # No account, VPN, global extensions, or external website is used.
                    code = code.replace('global_ext_dir = Path(__file__).parent.parent / "data" / "extensions"',
                                        'global_ext_dir = Path(user_data_dir) / "unused_extensions"')
                    code = code.replace("https://higgsfield.ai/ai/video?model=genjutsu", "about:blank")
                    code = code.replace('ext_page.goto("chrome-extension://facgnnelgcipeopfbjcajpaibhhdjgcp/popup.html", wait_until="load", timeout=5000)',
                                        'raise RuntimeError("No optional popup in search test")')
                    compile(code, "search_test_runner", "exec")
                    with (root / "runner.log").open("w", encoding="utf-8") as output:
                        proc = subprocess.Popen(
                            [sys.executable, "-c", code], stdout=output, stderr=subprocess.STDOUT,
                            cwd=browser.BASE_DIR, creationflags=0x08000000,
                        )
                        try:
                            port_file = profile_dir / "cdp_port.txt"
                            deadline = time.monotonic() + 45
                            while not port_file.is_file() and proc.poll() is None and time.monotonic() < deadline:
                                time.sleep(0.2)
                            log = (root / "runner.log").read_text(encoding="utf-8", errors="replace")
                            self.assertTrue(port_file.is_file(), log)
                            with sync_playwright() as pw:
                                client = pw.chromium.connect_over_cdp(
                                    "http://127.0.0.1:" + port_file.read_text().strip()
                                )
                                context = client.contexts[0]
                                page = context.new_page()
                                page.goto("chrome://settings/searchEngines")
                                read_engines = """async () => {
                                    const cr = await import('chrome://resources/js/cr.js');
                                    return await cr.sendWithPromise('getSearchEnginesList');
                                }"""
                                deadline = time.monotonic() + 10
                                default = []
                                while time.monotonic() < deadline:
                                    engines = page.evaluate(read_engines)
                                    default = [e for group in engines.values() if isinstance(group, list)
                                               for e in group if e.get("default")]
                                    if default:
                                        break
                                    page.wait_for_timeout(200)
                                self.assertTrue(default, engines)
                                self.assertEqual(default[0]["keyword"], "google.com", default)
                                self.assertIn("google.com/search?q=", default[0]["url"])
                                print(f"{engine}: Google is the default address-bar search provider", flush=True)
                        finally:
                            (profile_dir / "runner.stop").touch()
                            try:
                                proc.wait(timeout=15)
                            except subprocess.TimeoutExpired:
                                subprocess.run(
                                    ["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                                    capture_output=True, creationflags=0x08000000,
                                )
                                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
