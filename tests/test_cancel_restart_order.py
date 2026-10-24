"""Exercise the actual reset/VPN blocks without opening user browsers."""
import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]


def network_block(filename):
    tree = ast.parse((ROOT / "app/services" / filename).read_text(encoding="utf-8-sig"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Try) and any(
            isinstance(child, ast.Assign)
            and any(isinstance(target, ast.Name) and target.id == "resume_url" for target in child.targets)
            for child in node.body
        ):
            # Run the production block through navigation back to Higgsfield.
            end = next(i for i, child in enumerate(node.body) if isinstance(child, ast.Expr)
                       and isinstance(child.value, ast.Call)
                       and isinstance(child.value.func, ast.Attribute)
                       and child.value.func.attr == "goto")
            return compile(ast.Module(body=node.body[:end + 1], type_ignores=[]), filename, "exec")
    raise AssertionError("Missing reset/VPN block")


class CancelRestartOrderTest(unittest.TestCase):
    def run_scenario(self, filename, restart, cdp):
        events = []
        def make_context(name):
            page = SimpleNamespace(url="https://higgsfield.ai/ai/video?model=genjutsu",
                                   goto=lambda *a, **k: events.append(("navigate", name)))
            browser = SimpleNamespace(new_browser_cdp_session=lambda: SimpleNamespace(
                send=lambda method: events.append((method, name))))
            return SimpleNamespace(pages=[page], browser=browser,
                                   close=lambda: events.append(("close", name)))
        old = make_context("old")
        new = make_context("new")
        def reopen(*a, **kw):
            self.assertFalse(kw["reuse_existing"])
            events.append(("open", "new"))
            return new, False
        def vpn(context, profile_id):
            events.append(("vpn", "new" if context is new else "old"))
            return {"ip": "test-ip", "country": "test-country"}
        state = {"task": {"restart_browser_before_cancel": restart}}
        namespace = dict(video_tasks=state, task_id="task", profile_id="selected-profile",
                         context=old, page=old.pages[0], connected_via_cdp=cdp,
                         close_profile=lambda pid: events.append(("stop-profile", pid)),
                         time=SimpleNamespace(sleep=lambda _: None), p=object(), profile=object(),
                         ext_path=None, enable_ext_btn2=False, is_headless=False, engine="chrome",
                         _open_browser_with_fp=reopen)
        namespace["print"] = lambda *a, **kw: None
        modules = {"app.services.video_gen": SimpleNamespace(_open_browser_with_fp=reopen),
                   "app.services.vpn_ip": SimpleNamespace(connect_unique_vpn_ip=vpn)}
        with patch.dict(sys.modules, modules):
            exec(network_block(filename), namespace)
        if restart:
            self.assertLess(events.index(("close", "old")), events.index(("open", "new")))
            self.assertLess(events.index(("open", "new")), events.index(("vpn", "new")))
            self.assertLess(events.index(("vpn", "new")), events.index(("navigate", "new")))
            if cdp:
                self.assertIn(("Browser.close", "old"), events)
        else:
            self.assertEqual(events, [("vpn", "old"), ("navigate", "old")])
        self.assertNotIn("restart_browser_before_cancel", state["task"])

    def test_restart_and_fresh_browser_order(self):
        for filename in ("video_check.py", "video_gen.py"):
            for restart, cdp in ((True, False), (True, True), (False, False)):
                with self.subTest(filename=filename, restart=restart, cdp=cdp):
                    self.run_scenario(filename, restart, cdp)


if __name__ == "__main__":
    unittest.main()
