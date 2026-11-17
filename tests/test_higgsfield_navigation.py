"""Navigation regressions without connecting to user profiles or the website."""
import unittest
from unittest.mock import Mock

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from app.services.browser_navigation import install_higgsfield_pricing_guard, navigate_higgsfield


URL = 'https://higgsfield.ai/ai/video?model=genjutsu'


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.page = Mock()
        self.page.is_closed.return_value = False
        self.page.url = URL
        self.logs = []

    def navigate(self):
        navigate_higgsfield(self.page, URL, log=self.logs.append)

    def test_waits_for_dom_instead_of_media_load(self):
        self.navigate()
        self.page.goto.assert_called_once_with(URL, wait_until='domcontentloaded', timeout=30000)

    def test_usable_quiz_redirect_survives_timeout(self):
        self.page.url = 'https://higgsfield.ai/quiz?redirect=%2Fai%2Fvideo'
        self.page.goto.side_effect = PlaywrightTimeoutError('slow asset')
        self.page.evaluate.return_value = True
        self.navigate()
        self.page.goto.assert_called_once()

    def test_blank_document_is_retried_until_success(self):
        self.page.goto.side_effect = [PlaywrightTimeoutError('blank'), None]
        self.page.evaluate.return_value = False
        self.navigate()
        self.assertEqual(self.page.goto.call_count, 2)
        self.page.wait_for_timeout.assert_called_once_with(1500)

    def test_unrelated_document_is_not_accepted_as_video(self):
        for url in ('https://example.com/', 'https://higgsfield.ai/pricing'):
            with self.subTest(url=url):
                self.page.reset_mock()
                self.page.url = url
                self.page.goto.side_effect = [PlaywrightTimeoutError('not committed'), None]
                self.navigate()
                self.assertEqual(self.page.goto.call_count, 2)
                self.page.evaluate.assert_not_called()

    def test_transient_vpn_failure_is_retried(self):
        self.page.goto.side_effect = [RuntimeError('net::ERR_CONNECTION_RESET'), None]
        self.navigate()
        self.assertEqual(self.page.goto.call_count, 2)

    def test_permanent_failure_is_bounded(self):
        self.page.goto.side_effect = PlaywrightTimeoutError('VPN down')
        self.page.evaluate.return_value = False
        with self.assertRaises(PlaywrightTimeoutError):
            self.navigate()
        self.assertEqual(self.page.goto.call_count, 3)

    def test_closed_page_is_not_retried(self):
        self.page.goto.side_effect = RuntimeError('closed')
        self.page.is_closed.return_value = True
        with self.assertRaises(RuntimeError):
            self.navigate()
        self.page.goto.assert_called_once()


class PricingNavigationGuardTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context()
        self.context.route("**/*", lambda route: route.fulfill(
            content_type="text/html",
            body="<a href='/pricing?from=ad'>View offer</a><button id='upload'>Upload</button>",
        ))
        self.page = self.context.new_page()
        self.page.goto(URL)
        install_higgsfield_pricing_guard(self.context)

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()

    def test_pricing_link_is_blocked_and_upload_page_stays_usable(self):
        self.page.get_by_role("link", name="View offer").click()
        self.assertEqual(self.page.url, URL)
        self.assertTrue(self.page.get_by_role("button", name="Upload").is_visible())

    def test_client_side_pricing_navigation_is_blocked(self):
        self.page.evaluate("history.pushState({}, '', '/pricing?from=ad')")
        self.assertEqual(self.page.url, URL)


if __name__ == '__main__':
    unittest.main()
