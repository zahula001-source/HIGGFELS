"""Regression tests for closing the correct profile after OTP and Free Gen checks.

The real signup worker runs against a simulated Microsoft recovery flow. Browser
launch/close and the profile store are isolated from the user's running profiles.
"""

import importlib.util
import io
import sys
import tempfile
import types
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


VIDEO_URL = "https://higgsfield.ai/ai/video?model=genjutsu"


class RecoveryLocator:
    def __init__(self, page, selector):
        self.page = page
        self.selector = selector
        self.first = self.last = self

    def count(self):
        if self.selector == "body":
            return 1
        if self.page.stage == "proof":
            return int("#iProofEmail" in self.selector or "#iSelectProofAction" in self.selector)
        if self.page.stage == "otp":
            return int("#iOttText" in self.selector or "#iVerifyCodeAction" in self.selector)
        return 0

    def nth(self, index):
        return self

    def is_visible(self, **kwargs):
        return bool(self.count())

    def is_enabled(self):
        return True

    def inner_text(self, **kwargs):
        return "Verify your email - Send code" if self.page.stage == "proof" else "Enter code"

    def fill(self, value, **kwargs):
        self.page.filled.append(value)

    def click(self, **kwargs):
        if "#iSelectProofAction" in self.selector:
            self.page.stage = "otp"
        elif "#iVerifyCodeAction" in self.selector:
            self.page.stage = "done"
            self.page.url = VIDEO_URL

    def filter(self, **kwargs):
        return self


class RecoveryPage:
    def __init__(self, recover_otp=True):
        self.url = VIDEO_URL
        self.stage = "initial"
        self.recover_otp = recover_otp
        self.frames = []
        self.filled = []

    def is_closed(self):
        return False

    def locator(self, selector):
        return RecoveryLocator(self, selector)

    def bring_to_front(self):
        pass

    def wait_for_timeout(self, milliseconds):
        if self.recover_otp and milliseconds == 800 and self.stage == "initial":
            self.stage = "proof"
            self.url = "https://account.live.com/proofs/Verify"

    def wait_for_url(self, *args, **kwargs):
        raise RuntimeError("No quiz redirect")

    def goto(self, url, **kwargs):
        self.url = url

    def reload(self, **kwargs):
        pass

    def evaluate(self, *args):
        return False

    def evaluate_handle(self, *args):
        return SimpleNamespace(as_element=lambda: None)


class SignupBrowserCloseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="signup_close_test_")
        self.addCleanup(temporary.cleanup)
        profile_dir = Path(temporary.name)
        (profile_dir / "cdp_port.txt").write_text("12345", encoding="utf-8")
        (profile_dir / "ms_account.txt").write_text(
            "primary@example.com|password|refresh|client|backup@fviainboxes.com|secret",
            encoding="utf-8",
        )
        self.profile = SimpleNamespace(
            id="signup-test", name="Test profile", notes="", user_data_dir=str(profile_dir)
        )
        self.manager = SimpleNamespace(
            get_profile=Mock(return_value=self.profile), _save=Mock()
        )
        manager_module = types.ModuleType("app.manager")
        manager_module.manager = self.manager
        browser_module = types.ModuleType("app.browser")
        for name in (
            "launch_profile_with_fallback", "close_profile", "is_running", "list_running",
            "prepare_chrome_136_profile",
            "ensure_profile_network_mode",
        ):
            setattr(browser_module, name, Mock())
        browser_module.close_profile.return_value = {"status": "closed"}
        self.close_profile = browser_module.close_profile
        modules = patch.dict(sys.modules, {
            "app.manager": manager_module, "app.browser": browser_module,
        })
        modules.start()
        self.addCleanup(modules.stop)

        source = Path(__file__).resolve().parents[1] / "app" / "api" / "profiles.py"
        spec = importlib.util.spec_from_file_location("signup_profiles_under_test", source)
        self.api = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.api)

        self.page = RecoveryPage()
        self.context = SimpleNamespace(pages=[self.page])
        self.playwright = SimpleNamespace(
            chromium=SimpleNamespace(connect_over_cdp=Mock(return_value=SimpleNamespace(
                contexts=[self.context]
            ))),
            stop=Mock(),
        )
        self.sync_playwright = Mock(return_value=SimpleNamespace(start=lambda: self.playwright))
        self.thread = Mock()
        self.worker = None

        def capture_worker(*args, **kwargs):
            self.worker = kwargs["target"]
            return self.thread

        for target, replacement in (
            ("threading.Thread", capture_worker),
            ("time.sleep", lambda _: None),
            ("playwright.sync_api.sync_playwright", self.sync_playwright),
        ):
            mocked = patch(target, replacement)
            mocked.start()
            self.addCleanup(mocked.stop)
        self.api.install_upgrade_plan_guard = Mock()
        self.api.wait_video_login_state = Mock(return_value=True)
        self.api.click_use_password = Mock(return_value=False)
        self.api.fetch_roundcube_messages = Mock(side_effect=self.api.MailboxAccessDenied("denied"))
        self.api.read_code_in_fviainboxes_tab = Mock(return_value="123456")
        self.api.read_free_gens = Mock(return_value={"count": 1, "enabled": True, "disabled": False})
        self.api.read_quality = Mock(return_value="480p")
        self.output = io.StringIO()

    def start_signup(self, keep_open=False, manual_open=False):
        return self.api.auto_signup_endpoint(
            self.profile.id, keep_open=keep_open, engine="cloakbrowser", manual_open=manual_open,
        )

    def test_microsoft_fido_security_key_url_is_detected(self):
        self.assertTrue(self.api._is_microsoft_security_key_challenge(
            "https://login.microsoft.com/consumers/fido/create?mkt=vi-VN"
        ))
        self.assertFalse(self.api._is_microsoft_security_key_challenge(
            "https://higgsfield.ai/ai/video?model=genjutsu"
        ))

    def test_signup_consent_is_checked_only_when_present_and_unchecked(self):
        consent = Mock()
        consent.is_checked.side_effect = [False, True, True]
        label = Mock()
        label.count.return_value = 1
        label.is_visible.return_value = True
        label.locator.return_value.first = consent
        page = Mock()
        page.locator.return_value.first = label

        self.assertTrue(self.api._check_higgsfield_signup_consent(page))
        label.click.assert_called_once_with(force=True, timeout=2500)

        consent.is_checked.reset_mock()
        consent.is_checked.side_effect = None
        consent.is_checked.return_value = True
        label.click.reset_mock()
        self.assertTrue(self.api._check_higgsfield_signup_consent(page))
        label.click.assert_not_called()

    def test_missing_signup_consent_is_optional(self):
        page = Mock()
        label = page.locator.return_value.first
        label.count.return_value = 0

        self.assertIsNone(self.api._check_higgsfield_signup_consent(page))
        label.locator.assert_not_called()

    def test_fido_challenge_uses_escape_and_resumes_after_leaving_fido_url(self):
        page = SimpleNamespace(url="https://login.microsoft.com/consumers/fido/create")
        page.wait_for_timeout = Mock()

        def press_key(key):
            self.assertEqual(key, "Escape")
            page.url = "https://login.microsoftonline.com/common/oauth2/authorize"

        page.keyboard = SimpleNamespace(press=Mock(side_effect=press_key))
        page.locator = Mock()

        self.assertTrue(self.api._dismiss_microsoft_security_key_challenge(page))
        page.keyboard.press.assert_called_once_with("Escape")
        page.locator.assert_not_called()

    def test_fido_challenge_uses_native_escape_when_windows_security_is_foreground(self):
        page = SimpleNamespace(url="https://login.microsoft.com/consumers/fido/create")
        page.wait_for_timeout = Mock()
        page.keyboard = SimpleNamespace(press=Mock())
        page.locator = Mock()

        def dismiss_native_prompt():
            page.url = "https://login.microsoftonline.com/common/oauth2/authorize"
            return True

        with patch.object(
            self.api, "_send_escape_to_foreground_security_prompt", side_effect=dismiss_native_prompt
        ) as native_escape:
            self.assertTrue(self.api._dismiss_microsoft_security_key_challenge(page))

        native_escape.assert_called_once()
        page.keyboard.press.assert_not_called()
        page.locator.assert_not_called()

    def test_native_escape_targets_visible_security_dialog_when_other_app_is_foreground(self):
        import ctypes

        class FakeUser32:
            def __init__(self):
                self.posted = []

            def EnumWindows(self, callback, extra):
                callback(101, extra)

            def IsWindowVisible(self, hwnd):
                return True

            def GetWindowTextLengthW(self, hwnd):
                return len("Windows Security")

            def GetWindowTextW(self, hwnd, buffer, count):
                buffer.value = "Windows Security"
                return len(buffer.value)

            def SetForegroundWindow(self, hwnd):
                return False

            def GetForegroundWindow(self):
                return 202

            def PostMessageW(self, hwnd, message, key, detail):
                self.posted.append((hwnd, message, key))
                return True

        user32 = FakeUser32()
        self.assertTrue(self.api._send_escape_to_security_window(user32, ctypes))
        self.assertEqual(user32.posted, [(101, 0x0100, 0x1B), (101, 0x0101, 0x1B)])

    def test_fido_dismissal_rechecks_for_late_native_security_dialog(self):
        page = SimpleNamespace(url="https://login.microsoft.com/consumers/fido/create")
        page.keyboard = SimpleNamespace(press=Mock())
        page.locator = Mock()
        page.wait_for_timeout = Mock()
        with patch.object(
            self.api, "_send_escape_to_foreground_security_prompt", side_effect=[False, False, True]
        ) as native_escape:
            page.wait_for_timeout.side_effect = lambda _: setattr(
                page, "url", "https://login.microsoftonline.com/common/oauth2/authorize"
            ) if native_escape.call_count == 3 else None
            self.assertTrue(self.api._dismiss_microsoft_security_key_challenge(page))

        self.assertEqual(native_escape.call_count, 3)

    def test_fido_wait_resumes_when_url_leaves_challenge(self):
        page = SimpleNamespace(
            url="https://login.microsoft.com/consumers/fido/create",
            is_closed=Mock(return_value=False),
            wait_for_timeout=Mock(),
        )
        page.wait_for_timeout.side_effect = lambda _: setattr(
            page, "url", "https://login.microsoftonline.com/common/oauth2/authorize"
        )

        self.assertTrue(self.api._wait_for_microsoft_security_key_resolution(page))
        page.wait_for_timeout.assert_called_once_with(1000)

    def test_fido_wait_exits_when_tab_is_closed(self):
        page = SimpleNamespace(
            url="https://login.microsoft.com/consumers/fido/create",
            is_closed=Mock(return_value=True),
            wait_for_timeout=Mock(),
        )

        self.assertFalse(self.api._wait_for_microsoft_security_key_resolution(page))
        page.wait_for_timeout.assert_not_called()

    def test_fido_challenge_clicks_cancel_after_escape_does_not_dismiss_it(self):
        page = SimpleNamespace(url="https://login.microsoft.com/consumers/fido/create")
        page.keyboard = SimpleNamespace(press=Mock())
        page.wait_for_timeout = Mock()
        cancel = Mock()
        cancel.count.return_value = 1
        cancel.nth.return_value = cancel
        cancel.is_visible.return_value = True

        def click_cancel(**kwargs):
            page.url = "https://login.microsoftonline.com/common/oauth2/authorize"

        cancel.click.side_effect = click_cancel
        page.locator = Mock(return_value=cancel)

        self.assertTrue(self.api._dismiss_microsoft_security_key_challenge(page))
        self.assertEqual(page.keyboard.press.call_count, 1)
        cancel.click.assert_called_once()

    def run_worker(self):
        with redirect_stdout(self.output):
            self.worker()
        self.assertNotIn("Auto signup FATAL err", self.output.getvalue())
        self.assertNotIn(self.profile.id, self.api._running_signups)
        self.assertNotIn(self.profile.id, self.api._signup_options)

    def test_closes_after_successful_web_otp_and_free_gen_check(self):
        self.start_signup(keep_open=False)
        self.run_worker()
        self.api.fetch_roundcube_messages.assert_called_once()
        self.api.read_code_in_fviainboxes_tab.assert_called_once()
        self.assertIn("123456", self.page.filled)
        self.assertEqual(self.profile.notes, "free gen 1 480p")
        self.close_profile.assert_called_once_with(self.profile.id)
        self.playwright.stop.assert_called_once()
        self.assertIn("Đã đóng Chrome", self.output.getvalue())

    def test_preserves_explicit_keep_chrome_after_successful_check(self):
        self.start_signup(keep_open=True)
        self.run_worker()
        self.api.read_code_in_fviainboxes_tab.assert_called_once()
        self.assertEqual(self.profile.notes, "free gen 1 480p")
        self.close_profile.assert_not_called()
        self.assertIn("theo yêu cầu", self.output.getvalue())

    def test_new_close_request_applies_to_already_running_signup(self):
        self.start_signup(keep_open=True)
        with redirect_stdout(self.output):
            self.start_signup(keep_open=False)
        self.thread.start.assert_called_once()
        self.run_worker()
        self.close_profile.assert_called_once_with(self.profile.id)

    def test_signup_reserves_profile_before_network_mode_change(self):
        def assert_reserved(*args, **kwargs):
            self.assertIn(self.profile.id, self.api._running_signups)

        self.api.ensure_profile_network_mode.side_effect = assert_reserved
        self.start_signup()
        with redirect_stdout(self.output):
            self.start_signup(keep_open=True)
        self.api.ensure_profile_network_mode.assert_called_once()
        self.thread.start.assert_called_once()
        self.run_worker()

    def test_regular_check_still_tags_and_closes_when_switch_never_loads(self):
        self.page.recover_otp = False
        self.api.read_free_gens.return_value = None
        self.start_signup(keep_open=False)
        self.run_worker()
        self.assertEqual(self.api.read_free_gens.call_count, 2)
        self.assertEqual(self.profile.notes, "không free")
        self.close_profile.assert_called_once_with(self.profile.id)

    def test_homepage_login_stall_is_reported_and_browser_is_kept_open(self):
        self.page.recover_otp = False
        self.page.evaluate = Mock(return_value="Login")
        self.api.wait_video_login_state.return_value = False
        self.api.video_login_state = Mock(return_value=False)
        self.start_signup(keep_open=False)

        self.run_worker()

        self.assertEqual(self.profile.notes, "⚠️ Cần đăng nhập thủ công")
        self.manager._save.assert_called_once()
        self.assertIn("Microsoft sign-in option did not appear", self.output.getvalue())
        self.close_profile.assert_not_called()
        self.playwright.stop.assert_called_once()

    def test_manual_open_checks_once_and_keeps_chrome(self):
        self.page.recover_otp = False
        self.page.reload = Mock()
        self.start_signup(manual_open=True)
        self.run_worker()
        self.api.read_free_gens.assert_called_once_with(self.page, immediate=True)
        self.api.read_quality.assert_called_once_with(self.page, immediate=True)
        self.assertEqual(self.profile.notes, "free gen 1 480p")
        self.page.reload.assert_not_called()
        self.close_profile.assert_not_called()
        self.playwright.stop.assert_not_called()

    def test_manual_open_missing_switch_preserves_tag_without_reload_or_close(self):
        self.page.recover_otp = False
        self.page.reload = Mock()
        self.profile.notes = "existing tag"
        self.api.read_free_gens.return_value = None
        self.start_signup(manual_open=True)
        self.run_worker()
        self.api.read_free_gens.assert_called_once_with(self.page, immediate=True)
        self.api.read_quality.assert_not_called()
        self.assertEqual(self.profile.notes, "existing tag")
        self.manager._save.assert_not_called()
        self.page.reload.assert_not_called()
        self.close_profile.assert_not_called()
        self.playwright.stop.assert_not_called()

    def test_manual_open_leaving_genjutsu_skips_check_and_navigation(self):
        self.page.recover_otp = False
        self.page.reload = Mock()
        self.page.goto = Mock()

        def leave_video(*args, **kwargs):
            self.page.url = "https://higgsfield.ai/ai/video?model=other"
            raise RuntimeError("No quiz redirect")

        self.page.wait_for_url = leave_video
        self.start_signup(manual_open=True)
        self.run_worker()
        self.api.read_free_gens.assert_not_called()
        self.page.goto.assert_not_called()
        self.page.reload.assert_not_called()
        self.close_profile.assert_not_called()

    def test_manual_open_disabled_switch_tags_without_closing(self):
        self.page.recover_otp = False
        self.api.read_free_gens.return_value = {"count": 0, "enabled": False, "disabled": True}
        self.start_signup(manual_open=True)
        self.run_worker()
        self.assertEqual(self.profile.notes, "không free")
        self.close_profile.assert_not_called()

    def test_manual_open_off_switch_with_remaining_gens_is_free(self):
        self.page.recover_otp = False
        self.api.read_free_gens.return_value = {"count": 1, "enabled": False, "disabled": False}
        self.start_signup(manual_open=True)
        self.run_worker()
        self.assertEqual(self.profile.notes, "free gen 1 480p")
        self.close_profile.assert_not_called()

    def test_manual_open_is_preserved_when_delayed_signup_requests_close(self):
        self.page.recover_otp = False
        self.start_signup(keep_open=False)
        with redirect_stdout(self.output):
            self.start_signup(manual_open=True)
            self.start_signup(keep_open=False)
        self.run_worker()
        self.thread.start.assert_called_once()
        self.api.read_free_gens.assert_called_once_with(self.page, immediate=True)
        self.close_profile.assert_not_called()

    def test_manual_open_check_error_still_keeps_chrome(self):
        self.page.recover_otp = False
        self.api.read_free_gens.side_effect = RuntimeError("Page navigating")
        self.start_signup(manual_open=True)
        with redirect_stdout(self.output):
            self.worker()
        self.assertNotIn(self.profile.id, self.api._running_signups)
        self.assertNotIn(self.profile.id, self.api._signup_options)
        self.close_profile.assert_not_called()
        self.playwright.stop.assert_not_called()

    def test_manual_launch_passes_its_mode_to_login_worker(self):
        self.profile.extensions = ""
        self.api.video_tasks.clear()
        self.api.launch_profile_with_fallback.return_value = {"status": "already_running", "pid": 12}
        self.api.auto_signup_endpoint = Mock()
        req = self.api.LaunchRequest(manual_open=True, keep_open_after_check=False)
        result = self.api.launch_profile_endpoint(self.profile.id, req)
        self.assertTrue(result["ok"])
        self.assertTrue(self.api.auto_signup_endpoint.call_args.kwargs["manual_open"])

    def test_reports_close_failure_instead_of_claiming_chrome_closed(self):
        self.close_profile.return_value = {"status": "error", "message": "Runner did not stop"}
        self.start_signup(keep_open=False)
        self.run_worker()
        self.close_profile.assert_called_once_with(self.profile.id)
        self.assertIn("Runner did not stop", self.output.getvalue())
        self.assertNotIn("Đã đóng Chrome", self.output.getvalue())

    def test_original_manual_button_request_is_recognized_without_new_flag(self):
        req = self.api.LaunchRequest(
            headless=False, auto_random_fp=False, startup_urls="", startup_mode="once",
            enable_ext_btn2=False, enable_ext=True, keep_open_after_check=False,
            engine="cloakbrowser", generate_ip=False,
        )
        self.assertTrue(self.api._is_manual_launch(req))

    def test_other_legacy_launch_handlers_keep_their_original_mode(self):
        payloads = (
            {"keep_open_after_check": False, "enable_ext": True, "startup_urls": ""},
            {"enable_ext_btn2": False, "enable_ext": True, "startup_urls": ""},
            {"enable_ext_btn2": False, "keep_open_after_check": False, "manual_open": False},
        )
        for payload in payloads:
            with self.subTest(payload=payload):
                self.assertFalse(self.api._is_manual_launch(self.api.LaunchRequest(**payload)))

    def test_manual_route_overrides_false_payload_and_keeps_runner_for_later_signup(self):
        self.profile.extensions = ""
        self.api.video_tasks.clear()
        self.api.launch_profile_with_fallback.return_value = {"status": "already_running", "pid": 12}
        self.api.list_running.return_value = {self.profile.id: 12}
        self.page.recover_otp = False
        req = self.api.LaunchRequest(manual_open=False, keep_open_after_check=False)
        with redirect_stdout(self.output):
            self.api.launch_manual_profile_endpoint(self.profile.id, req)
        self.run_worker()
        self.assertTrue(req.manual_open)
        self.assertTrue(req.keep_open_after_check)
        self.start_signup(keep_open=False)
        self.run_worker()
        self.assertEqual(self.api.read_free_gens.call_count, 2)
        for call in self.api.read_free_gens.call_args_list:
            self.assertEqual(call.kwargs, {"immediate": True})
        self.close_profile.assert_not_called()

    def test_manual_session_protection_expires_for_a_different_runner(self):
        self.api._manual_open_sessions[self.profile.id] = 12
        self.api.list_running.return_value = {self.profile.id: 13}
        self.start_signup(keep_open=False)
        self.run_worker()
        self.close_profile.assert_called_once_with(self.profile.id)
        self.assertNotIn(self.profile.id, self.api._manual_open_sessions)

    def test_manual_open_keeps_old_tab_when_another_higgsfield_tab_appears(self):
        self.page.recover_otp = False
        self.page.close = Mock()
        second_page = RecoveryPage(recover_otp=False)
        self.context.pages.append(second_page)
        self.start_signup(manual_open=True)
        self.run_worker()
        self.page.close.assert_not_called()
        self.api.read_free_gens.assert_called_once_with(second_page, immediate=True)
        self.close_profile.assert_not_called()

    def test_regular_signup_still_closes_old_tab_when_switching(self):
        self.page.recover_otp = False
        self.page.close = Mock()
        self.context.pages.append(RecoveryPage(recover_otp=False))
        self.start_signup(keep_open=False)
        self.run_worker()
        self.page.close.assert_called_once()
        self.close_profile.assert_called_once_with(self.profile.id)

    def test_navigation_failure_keeps_chrome_and_existing_tag(self):
        self.page.url = 'about:blank'
        self.profile.notes = 'existing tag'
        self.page.goto = Mock(side_effect=RuntimeError('VPN connection interrupted'))
        self.start_signup(keep_open=False)
        self.run_worker()
        self.assertEqual(self.page.goto.call_count, 3)
        self.close_profile.assert_not_called()
        self.api.read_free_gens.assert_not_called()
        self.assertEqual(self.profile.notes, 'existing tag')
        self.playwright.stop.assert_called_once()
        self.assertNotIn('sau khi hoàn tất cập nhật', self.output.getvalue())

    def test_domcontentloaded_navigation_continues_signup_after_ip_change(self):
        self.page.url = 'about:blank'
        self.page.goto = Mock(wraps=self.page.goto)
        self.start_signup(keep_open=False)
        self.run_worker()
        self.assertEqual(self.page.goto.call_args_list[0].kwargs['wait_until'], 'domcontentloaded')
        self.assertEqual(self.profile.notes, 'free gen 1 480p')
        self.close_profile.assert_called_once_with(self.profile.id)

    def test_incomplete_login_keeps_chrome_without_claiming_success(self):
        self.page.recover_otp = False
        self.api.wait_video_login_state.return_value = None
        self.profile.notes = 'existing tag'
        self.start_signup(keep_open=False)
        self.run_worker()
        self.close_profile.assert_not_called()
        self.api.read_free_gens.assert_not_called()
        self.assertNotIn('sau khi hoàn tất cập nhật', self.output.getvalue())

    def test_existing_quiz_is_handled_without_navigating_away(self):
        self.page.recover_otp = False
        self.page.url = 'https://higgsfield.ai/quiz?redirect=%2Fai%2Fvideo'
        self.page.goto = Mock(wraps=self.page.goto)

        def answer_quiz(page, state):
            page.url = VIDEO_URL
            return True

        self.api.handle_quiz_step = Mock(side_effect=answer_quiz)
        self.start_signup(keep_open=False)
        self.run_worker()
        self.api.handle_quiz_step.assert_called_once()
        self.page.goto.assert_not_called()
        self.assertEqual(self.profile.notes, 'free gen 1 480p')
        self.close_profile.assert_called_once_with(self.profile.id)

    def test_network_mode_failure_reports_error_before_starting_signup(self):
        from fastapi import HTTPException
        self.api.ensure_profile_network_mode.side_effect = RuntimeError('Cannot apply proxy OFF')
        with self.assertRaises(HTTPException) as error:
            self.start_signup()
        self.assertEqual(error.exception.status_code, 400)
        self.assertIn('proxy OFF', error.exception.detail)
        self.assertIsNone(self.worker)


class ImmediateFreeGenReadTests(unittest.TestCase):
    def test_new_free_generation_badge_counts_are_parsed(self):
        from app.services.higgsfield_login import read_free_gens

        for count in (2, 1):
            with self.subTest(count=count):
                page = Mock()
                page.evaluate.return_value = {
                    "countText": f"{count} left",
                    "enabled": False,
                    "disabled": False,
                }
                result = read_free_gens(page, immediate=True)
                self.assertEqual(result["count"], count)
                self.assertFalse(result["enabled"])

    def test_missing_switch_returns_after_one_dom_read(self):
        from app.services.higgsfield_login import read_free_gens
        page = Mock()
        page.evaluate.return_value = None
        self.assertIsNone(read_free_gens(page, immediate=True))
        page.evaluate.assert_called_once()
        page.wait_for_timeout.assert_not_called()
        page.locator.assert_not_called()

    def test_off_switch_is_read_without_clicking_or_waiting(self):
        from app.services.higgsfield_login import read_free_gens
        page = Mock()
        page.evaluate.return_value = {"count": 1, "enabled": False, "disabled": False}
        self.assertEqual(read_free_gens(page, immediate=True), page.evaluate.return_value)
        page.evaluate.assert_called_once()
        page.wait_for_timeout.assert_not_called()
        page.locator.assert_not_called()

    def test_missing_quality_returns_after_one_dom_read(self):
        from app.services.higgsfield_login import read_quality
        page = Mock()
        page.evaluate.return_value = ""
        self.assertEqual(read_quality(page, immediate=True), "")
        page.evaluate.assert_called_once()
        page.wait_for_timeout.assert_not_called()


if __name__ == "__main__":
    unittest.main()
