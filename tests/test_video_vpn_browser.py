"""Run real Chrome startup + VPN checks without submitting a video job."""
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright
from app.core.config import DATA_DIR, STATIC_DIR
from app.services.video_gen import _open_browser_with_fp
from app.services.vpn_ip import connect_unique_vpn_ip, release_vpn_ip


def main():
    with tempfile.TemporaryDirectory(prefix="vpn_video_check_", dir=DATA_DIR) as folder:
        root = Path(folder).resolve()
        assert root.is_relative_to(DATA_DIR.resolve())
        os.environ["TEMP"] = os.environ["TMP"] = str(root)
        source = root / "profile_test"
        source.mkdir()
        profile = SimpleNamespace(id="vpn-video-test", name="VPN startup check",
                                  user_data_dir=str(source), fingerprint={}, extensions="")
        with sync_playwright() as pw:
            context, reused = _open_browser_with_fp(pw, profile, None, engine="chrome", generate_ip=True)
            assert not reused
            try:
                page = next((p for p in context.pages if not p.is_closed()), None) or context.new_page()
                # Verify the existing frontend's FormData, without calling the API.
                page.goto("http://127.0.0.1:5333")
                page.set_content('''<textarea id="videoPrompt_t">test</textarea>
                    <input id="videoProfileId_t" value="test"><input id="videoDuration_t">
                    <input id="videoRatio_t"><input id="videoGenMode_t" value="motion_transfer">
                    <button id="createVideoBtn_t"></button><input id="globalGenerateIp" type="checkbox">''')
                html = (STATIC_DIR / "index.html").read_text(encoding="utf-8")
                start = html.index("async function startVideoCreationDynamic(")
                end = html.index("async function pollTaskStatusDynamic(", start)
                page.evaluate("""() => {
                    window.alert = () => {};
                    window.fetch = async (_, opts) => {
                        window.sentGenerateIp = opts.body.get('generate_ip');
                        return {ok:false, json:async()=>({detail:'isolated frontend test'})};
                    };
                }""")
                page.add_script_tag(content=html[start:end])
                for checked in (True, False):
                    page.evaluate("value => document.getElementById('globalGenerateIp').checked=value", checked)
                    page.evaluate("startVideoCreationDynamic('t')")
                    assert page.evaluate("window.sentGenerateIp") == ("true" if checked else "false")
                print("PASS: frontend sends the actual Sinh IP checkbox", flush=True)

                # Simulate the extension's late welcome tab; no provider request
                # should escape the guard, and the work tab must remain alive.
                attempts = []
                context.on("request", lambda req: attempts.append(req.url))
                welcome = context.new_page()
                try:
                    welcome.goto("https://www.1clickvpn.com/thank-you-ext/?cid=regression", timeout=5000)
                except Exception:
                    pass  # The guard closes this navigation's page.
                page.wait_for_timeout(500)
                assert welcome.is_closed()
                assert not page.is_closed()
                assert not any("thank-you-ext" in p.url for p in context.pages)
                print("PASS: late VPN welcome page dismissed; working tab preserved", flush=True)

                info = connect_unique_vpn_ip(context, profile.id, max_attempts=2)
                print("PASS: VPN selected", info["country"], "and connected to", info["ip"], flush=True)
                assert not any("thank-you-ext" in p.url for p in context.pages)
            finally:
                release_vpn_ip(profile.id)
                context.close()


if __name__ == "__main__":
    main()
