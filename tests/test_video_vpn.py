import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from starlette.datastructures import FormData
from app.api import video
from app.services import video_gen, vpn_ip
from app.services.browser_navigation import is_vpn_welcome_url, install_vpn_welcome_guard


class VideoVpnTests(unittest.TestCase):
    def setUp(self):
        self.saved_tasks = dict(video.video_tasks)
        video.video_tasks.clear()

    def tearDown(self):
        video.video_tasks.clear()
        video.video_tasks.update(self.saved_tasks)

    def create(self, generate_ip):
        class Request:
            async def form(self):
                fields = {"prompt": "test", "profile_id": "test-profile",
                          "browser_engine": "chrome"}
                if generate_ip is not None:
                    fields["generate_ip"] = generate_ip
                return FormData(fields)

        with patch.object(video.threading, "Thread") as thread, \
                patch.object(video, "list_running", return_value={"another-profile": 1}):
            result = asyncio.run(video.create_video(Request()))
            task = video.video_tasks[result["task_id"]]
            return task, thread.call_args.kwargs["args"]

    def test_create_propagates_checked_flag(self):
        task, args = self.create("true")
        self.assertTrue(task["params"]["generate_ip"])
        self.assertTrue(args[-1])

    def test_unchecked_does_not_generate_ip(self):
        task, args = self.create("false")
        self.assertFalse(task["params"]["generate_ip"])
        self.assertFalse(args[-1])

    def test_older_ui_without_flag_still_connects_vpn(self):
        task, args = self.create(None)
        self.assertTrue(task["params"]["generate_ip"])
        self.assertTrue(args[-1])

    def test_retry_preserves_engine_and_vpn(self):
        video.video_tasks["retry"] = {"params": {"prompt": "test", "profile_id": "p",
            "generate_ip": True, "browser_engine": "cloakbrowser", "gen_mode": "image_to_video"}}
        with patch.object(video.threading, "Thread") as thread:
            video.retry_video("retry")
        args = thread.call_args.kwargs["args"]
        self.assertEqual(args[-3:], ("image_to_video", "cloakbrowser", True))

    def test_network_preparation_obeys_flag_and_reports_result(self):
        video.video_tasks["task"] = {"params": {"generate_ip": True}}
        with patch.object(vpn_ip, "connect_unique_vpn_ip", return_value={"ip": "1.2.3.4", "country": "Japan"}) as connect:
            video_gen._prepare_video_network(Mock(), "task", "p", False)
            connect.assert_not_called()
            context = Mock()
            video_gen._prepare_video_network(context, "task", "p", True)
            connect.assert_called_once_with(context, "p")
        self.assertEqual(video.video_tasks["task"]["vpn_ip"], "1.2.3.4")
        self.assertTrue(video.video_tasks["task"]["params"]["generate_ip"])

    def test_network_failure_stops_preparation(self):
        video.video_tasks["task"] = {}
        with patch.object(vpn_ip, "connect_unique_vpn_ip", side_effect=RuntimeError("VPN unavailable")):
            with self.assertRaisesRegex(RuntimeError, "VPN unavailable"):
                video_gen._prepare_video_network(Mock(), "task", "p", True)

    def test_existing_generation_status_is_detected(self):
        page = Mock()
        page.is_closed.return_value = False
        page.locator.return_value.inner_text.return_value = "History\nGenerating\n"
        context = Mock(pages=[page])
        self.assertEqual(video_gen._existing_generation_status(context), "Generating")

    def test_welcome_match_is_limited_to_requested_site(self):
        self.assertTrue(is_vpn_welcome_url("https://hola.org/welcome?ext_ver=1.259&uuid=test"))
        self.assertTrue(is_vpn_welcome_url("https://holavpn.com/welcome"))
        self.assertTrue(is_vpn_welcome_url("http://1clickvpn.com/thank-you-ext"))
        self.assertFalse(is_vpn_welcome_url("https://www.1clickvpn.com/help"))
        self.assertFalse(is_vpn_welcome_url("https://example.com/thank-you-ext/"))

    def test_guard_preserves_only_tab_and_is_idempotent(self):
        context = Mock(spec=["pages", "route", "on"])
        page = Mock()
        page.url = "https://www.1clickvpn.com/thank-you-ext/?cid=test"
        page.is_closed.return_value = False
        context.pages = [page]
        install_vpn_welcome_guard(context)
        page.goto.assert_called_once_with("about:blank", wait_until="commit")
        page.close.assert_not_called()
        install_vpn_welcome_guard(context)
        context.route.assert_called_once()

    def test_guard_keeps_multiple_welcome_tabs_open_as_blank_pages(self):
        context = Mock(spec=["pages", "route", "on"])
        pages = [Mock(), Mock(), Mock(), Mock()]
        context.pages = pages
        for page in pages:
            page.url = "https://www.1clickvpn.com/thank-you-ext/?cid=test"
            page.is_closed.return_value = False

        install_vpn_welcome_guard(context)

        for page in pages:
            page.goto.assert_called_once_with("about:blank", wait_until="commit")
            page.close.assert_not_called()


class VpnIpTests(unittest.TestCase):
    def setUp(self):
        self.saved_ips = dict(vpn_ip._reserved_ips)
        self.saved_live = set(vpn_ip._live_vpn_profiles)
        vpn_ip._reserved_ips.clear()
        vpn_ip._live_vpn_profiles.clear()

    def tearDown(self):
        vpn_ip._reserved_ips.clear()
        vpn_ip._reserved_ips.update(self.saved_ips)
        vpn_ip._live_vpn_profiles.clear()
        vpn_ip._live_vpn_profiles.update(self.saved_live)

    def connect(self, ips, context):
        with patch.object(vpn_ip, "get_active_vpn", return_value="1clickvpn"), \
                patch.object(vpn_ip, "_wait_for_popup_ready"), \
                patch.object(vpn_ip, "_choose_random_country", return_value="Japan"), \
                patch.object(vpn_ip, "_wait_connected"), \
                patch.object(vpn_ip, "_public_ip", side_effect=ips), \
                patch.object(vpn_ip, "_save_reservations"), \
                patch("app.browser.is_running", return_value=False):
            return vpn_ip.connect_unique_vpn_ip(context, "new", max_attempts=2)

    def test_retries_unchanged_ip_before_accepting_new_ip(self):
        context = Mock()
        result = self.connect(["1.1.1.1", "1.1.1.1", "2.2.2.2"], context)
        self.assertEqual(result["ip"], "2.2.2.2")
        self.assertIn("new", vpn_ip._live_vpn_profiles)
        context.once.assert_called_once()


    def test_initialization_warning_clicks_reset_once(self):
        page = Mock()
        page.locator.return_value.inner_text.return_value = (
            "It seems there's an issue. Initialization takes longer than expected - try resetting below. Reset"
        )
        page.get_by_text.return_value.count.return_value = 1
        page.get_by_text.return_value.first.is_visible.return_value = True
        with self.assertRaisesRegex(RuntimeError, "stuck initializing after Reset"):
            vpn_ip._wait_for_popup_ready(page)
        page.get_by_text.return_value.first.click.assert_called_once_with(timeout=2000)

    def test_does_not_reuse_ip_of_running_video_task(self):
        vpn_ip._reserved_ips["video-owner"] = "2.2.2.2"
        vpn_ip._live_vpn_profiles.add("video-owner")
        result = self.connect(["1.1.1.1", "2.2.2.2", "3.3.3.3"], Mock())
        self.assertEqual(result["ip"], "3.3.3.3")
        self.assertEqual(vpn_ip._reserved_ips["video-owner"], "2.2.2.2")

    def test_1click_fail_rotates_hma_and_retries_then_urban_fallback(self):
        context = Mock()
        hma_mock = Mock(return_value={"ip": "8.8.8.8", "country": "Singapore"})
        with patch("app.services.hma_vpn.rotate_hma_random_country", hma_mock), \
                patch.object(vpn_ip, "_connect_1clickvpn", side_effect=[RuntimeError("1click 1 error"), RuntimeError("1click 2 error")]), \
                patch.object(vpn_ip, "_disconnect_1clickvpn"), \
                patch.object(vpn_ip, "_disable_extension"), \
                patch.object(vpn_ip, "_connect_urban_vpn", side_effect=[RuntimeError("urban 1 error"), {"ip": "9.9.9.9", "country": "Germany"}]), \
                patch("time.sleep"):
            result = vpn_ip.connect_unique_vpn_ip(context, "test-p")
            self.assertEqual(result["ip"], "9.9.9.9")
            self.assertEqual(result["country"], "Germany")
            self.assertEqual(hma_mock.call_count, 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
