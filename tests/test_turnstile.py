import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace

from app.services.stealth import (
    get_real_chrome_binary,
    install_stealth_guard,
    human_mouse_move,
    solve_cloudflare_turnstile,
)


class TurnstileStealthTests(unittest.TestCase):
    def test_get_real_chrome_binary(self):
        chrome = get_real_chrome_binary()
        if chrome is not None:
            self.assertTrue(chrome.name.endswith(".exe"))

    def test_install_stealth_guard(self):
        context = SimpleNamespace(add_init_script=Mock())
        install_stealth_guard(context)
        context.add_init_script.assert_called_once()
        script = context.add_init_script.call_args[0][0]
        self.assertIn("webdriver", script)
        self.assertIn("window.chrome", script)

    def test_human_mouse_move(self):
        page = SimpleNamespace(
            mouse=SimpleNamespace(move=Mock()),
            wait_for_timeout=Mock(),
        )
        human_mouse_move(page, 50, 50, 200, 200, steps=20)
        self.assertGreater(page.mouse.move.call_count, 10)

    def test_solve_turnstile_returns_false_when_absent(self):
        page = SimpleNamespace(
            is_closed=lambda: False,
            frames=[],
            locator=lambda sel: SimpleNamespace(count=lambda: 0, inner_text=lambda timeout=0: ""),
            evaluate=lambda script: "",
        )
        result = solve_cloudflare_turnstile(page, timeout_sec=1)
        self.assertFalse(result)

    def test_solve_turnstile_returns_true_when_token_already_present(self):
        page = SimpleNamespace(
            is_closed=lambda: False,
            frames=[],
            locator=lambda sel: SimpleNamespace(count=lambda: 0, inner_text=lambda timeout=0: ""),
            evaluate=lambda script: "0.VALID_TEST_TOKEN_1234567890",
        )
        result = solve_cloudflare_turnstile(page, timeout_sec=2)
        self.assertTrue(result)

    def test_solve_turnstile_clicks_and_obtains_token(self):
        mouse_moves = []
        mouse_down = Mock()
        mouse_up = Mock()
        token_state = {"val": ""}

        def mock_eval(script):
            if "cf-turnstile-response" in script:
                return token_state["val"]
            return ""

        frame_el = SimpleNamespace(
            is_visible=lambda timeout=0: True,
            scroll_into_view_if_needed=Mock(),
            bounding_box=lambda: {"x": 100, "y": 200, "width": 300, "height": 65},
        )
        cf_frame = SimpleNamespace(
            url="https://challenges.cloudflare.com/turnstile/v0/api.js",
            frame_element=lambda: frame_el,
        )

        def on_mouse_up():
            mouse_up()
            token_state["val"] = "0.SUCCESS_CF_TURNSTILE_TOKEN_9999"

        page = SimpleNamespace(
            is_closed=lambda: False,
            frames=[cf_frame],
            locator=lambda sel: SimpleNamespace(count=lambda: 1, first=frame_el, inner_text=lambda timeout=0: "Verify you are human"),
            evaluate=mock_eval,
            mouse=SimpleNamespace(
                move=lambda x, y: mouse_moves.append((x, y)),
                down=mouse_down,
                up=on_mouse_up,
            ),
            wait_for_timeout=Mock(),
        )

        result = solve_cloudflare_turnstile(page, timeout_sec=4)
        self.assertTrue(result)
        self.assertGreater(len(mouse_moves), 10)
        mouse_down.assert_called_once()
        mouse_up.assert_called_once()


if __name__ == "__main__":
    unittest.main()

