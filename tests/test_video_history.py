"""Exercise history tabs and status detection in a local browser fixture."""
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import sync_playwright
from app.services import video_history


def main():
    binary = Path('data/browser_bins/chrome-136/chrome-win64/chrome.exe').resolve()
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=str(binary), headless=True)
        page = browser.new_page()
        try:
            for status in ('Processing', 'Generating'):
                page.set_content(f'<span hidden>Processing</span><span>{status}</span>')
                video_history.wait_for_generation(page, timeout=1000)
            print('PASS: both visible statuses accepted despite hidden Processing')
            page.set_content('''<button onclick="window.steps=['library']">Motion Library</button>
                <button onclick="window.steps.push('history');document.querySelector('#status').innerText='Generating'">History</button>
                <span id="status"></span><button onclick="window.submitted=true">Generate</button>''')
            original_wait = video_history.wait_for_generation
            with patch.object(video_history, 'wait_for_generation', side_effect=lambda p: original_wait(p, timeout=300)):
                video_history.confirm_generation(page)
            assert page.evaluate('window.steps') == ['library', 'history']
            assert page.evaluate('Boolean(window.submitted)') is False
            print('PASS: missing status refreshes Library then History without Generate/reload')
        finally:
            browser.close()


if __name__ == '__main__':
    main()
