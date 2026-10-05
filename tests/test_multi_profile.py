"""Regression checks for simultaneous isolated Chrome profiles.
Run: python tests/test_multi_profile.py
Uses temporary profiles and closes only browsers created by this test.
"""
import concurrent.futures
import os
from pathlib import Path
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app import browser

class MultiProfileTest(unittest.TestCase):
    def test_generated_runner(self):
        for proxy in (None, {"server": "http://127.0.0.1:8080"}):
            code = browser.get_chromium_runner_simple(
                "syntax", "syntax", r"D:\test profile", proxy, {"random_id": 123456})
            compile(code, "runner", "exec")
            self.assertIn("--fingerprint=123456", code)
            self.assertNotIn("--fingerprint={random_id}", code)

    def test_concurrent_profiles(self):
        from playwright.sync_api import sync_playwright
        old_data, old_logs = browser.DATA_DIR, browser.LOGS_DIR
        original_generator = browser.get_chromium_runner_simple
        old_engine = os.environ.get("HIGGSFIELD_BROWSER_ENGINE")
        os.environ["HIGGSFIELD_BROWSER_ENGINE"] = os.environ.get("HIGGSFIELD_TEST_ENGINE", "chrome")
        # Avoid network dependencies in the integration check.
        browser.get_chromium_runner_simple = lambda *a, **kw: original_generator(*a, **kw).replace(
            "https://www.dola.com/chat/", "about:blank")
        with tempfile.TemporaryDirectory(prefix="higgsfield_multi_profile_", dir=old_data) as folder:
            root = Path(folder).resolve()
            assert root.is_relative_to(old_data.resolve())
            old_temp = {key: os.environ.get(key) for key in ("TEMP", "TMP")}
            os.environ["TEMP"] = os.environ["TMP"] = str(root)
            browser.DATA_DIR = root
            browser.LOGS_DIR = root / "logs"
            profiles = [
                SimpleNamespace(id=f"regression_{i}", user_data_dir=str(root / f"profile_{i}"),
                                proxy=None, fingerprint={"random_id": 123456+i}, extensions="")
                for i in range(2)
            ]
            def connect(pw, profile):
                runtime_dir = browser.prepare_chrome_136_profile(profile.user_data_dir)
                port = Path(runtime_dir, "cdp_port.txt").read_text().strip()
                return pw.chromium.connect_over_cdp(f"http://127.0.0.1:{port}")
            try:
                with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
                    futures = [pool.submit(browser.launch_profile, p)
                               for p in (profiles[0], profiles[1], profiles[0])]
                    results = [f.result(timeout=120) for f in futures]
                print("Concurrent launches:", results, flush=True)
                self.assertEqual(sum(r["status"] == "launched" for r in results), 2, results)
                self.assertEqual(sum(r["status"] == "already_running" for r in results), 1, results)
                time.sleep(3)
                self.assertTrue(all(browser.is_running(p.id) for p in profiles))
                with sync_playwright() as pw:
                    first = connect(pw, profiles[0])
                    if os.environ["HIGGSFIELD_BROWSER_ENGINE"] == "cloakbrowser":
                        self.assertTrue(first.version.startswith("146."), first.version)
                    second = connect(pw, profiles[1])
                    for client in (first, second):
                        check = client.contexts[0].new_page()
                        try:
                            check.goto('chrome://settings/searchEngines')
                            engines = check.evaluate("async () => {const cr=await import('chrome://resources/js/cr.js');return await cr.sendWithPromise('getSearchEnginesList');}")
                            defaults = [e for group in engines.values() for e in group if e.get('default')]
                            self.assertEqual(defaults[0]['keyword'], 'google.com', defaults)
                            print('Verified default search:', defaults[0]['url'], flush=True)
                        finally:
                            check.close()

                    first.contexts[0].add_cookies([{
                        "name": "isolation_check", "value": "profile_one",
                        "domain": "example.test", "path": "/", "expires": time.time()+3600
                    }])
                    self.assertFalse(any(c["name"] == "isolation_check"
                                         for c in second.contexts[0].cookies()))
                    self.assertEqual(browser.close_profile(profiles[0].id)["status"], "closed")
                    self.assertTrue(browser.is_running(profiles[1].id))
                    self.assertEqual(second.contexts[0].pages[0].evaluate("2 + 2"), 4)
                    self.assertEqual(browser.launch_profile(profiles[0])["status"], "launched")
                    first = connect(pw, profiles[0])
                    self.assertTrue(any(c["name"] == "isolation_check"
                                        for c in first.contexts[0].cookies()))
                    # Closing the browser itself must end its runner too.
                    session = second.new_browser_cdp_session()
                    try:
                        session.send("Browser.close")
                    except Exception:
                        pass
                    deadline = time.monotonic()+10
                    while browser.is_running(profiles[1].id) and time.monotonic() < deadline:
                        time.sleep(.2)
                    self.assertFalse(browser.is_running(profiles[1].id))
                    self.assertTrue(browser.is_running(profiles[0].id))
                print("PASS: close isolation, persistent cookies, browser-close status", flush=True)
            finally:
                for profile in profiles:
                    browser.close_profile(profile.id)
                for key, value in old_temp.items():
                    if value is None: os.environ.pop(key, None)
                    else: os.environ[key] = value
                browser.DATA_DIR, browser.LOGS_DIR = old_data, old_logs
                browser.get_chromium_runner_simple = original_generator
                if old_engine is None:
                    os.environ.pop("HIGGSFIELD_BROWSER_ENGINE", None)
                else:
                    os.environ["HIGGSFIELD_BROWSER_ENGINE"] = old_engine

if __name__ == "__main__":
    unittest.main(verbosity=2)
