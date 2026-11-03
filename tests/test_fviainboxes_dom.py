"""Browser regression checks using intercepted local HTML, no real mailbox."""
import unittest
from playwright.sync_api import sync_playwright

from app.services.microsoft_recovery import (
    read_code_in_fviainboxes_tab,
    dismiss_fviainboxes_notice,
    is_fviainboxes_notice_present,
)


NOTICE_POPUP_SNIPPET = """
<div id="headlessui-dialog-panel-6" data-headlessui-state="open" class="w-full max-w-lg overflow-hidden rounded-lg bg-white shadow-2xl ring-1 ring-gray-900/10">
  <div class="bg-gradient-to-br from-indigo-600 via-blue-600 to-cyan-500 px-6 py-5 text-white">
    <div class="flex items-start justify-between gap-4">
      <h2 id="headlessui-dialog-title-7" data-headlessui-state="open" class="text-xl font-semibold leading-7">Notice</h2>
      <button type="button" id="notice-close-x" onclick="this.closest('#headlessui-dialog-panel-6').remove()" class="rounded-md p-1.5 text-white/80 hover:bg-white/10 hover:text-white focus:outline-none focus:ring-2 focus:ring-white">
        <span class="sr-only">Close announcement</span>
        <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" stroke-width="1.5" stroke="currentColor" aria-hidden="true" class="h-5 w-5">
          <path stroke-linecap="round" stroke-linejoin="round" d="M6 18L18 6M6 6l12 12"></path>
        </svg>
      </button>
    </div>
  </div>
  <div class="p-6">
    <div class="prose prose-sm max-w-none text-gray-700">
      <p><strong>The server is under heavy load.</strong> To block bots, a captcha may appear from time to time.</p>
    </div>
    <div class="mt-6 flex justify-end gap-3">
      <button type="button" onclick="this.closest('#headlessui-dialog-panel-6').remove()" class="inline-flex items-center justify-center rounded-md px-4 py-2.5 text-sm font-semibold text-gray-700 ring-1 ring-inset ring-gray-300 hover:bg-gray-50"> Close </button>
    </div>
  </div>
</div>
"""


MAILBOX_HTML = """
<input id="username" name="username">
<button type="submit" onclick="window.wrongSubmit=true">Sponsored submit</button>
<button type="submit" id="get" onclick="fetchInbox()"><span>Get Email</span></button>
<div class="overflow-y-auto" id="inbox"></div>
<iframe title="Sponsored" srcdoc="Security code: 999999"></iframe>
<div id="message"></div>
<div id="overlay" style="position:fixed;inset:0;z-index:9999"
     onclick="window.overlayClicks++;window.open('https://ads.example/')"></div>
<script>
window.requests=0; window.opened=[]; window.overlayClicks=0; window.wrongSubmit=false;
window.retryScenario=RETRY_SCENARIO;
function fetchInbox() {
  window.requests++;
  document.getElementById('get').disabled=true;
  document.querySelector('#get span').style.display='none';
  // Simulate an ad script attached to the real button as well as an overlay.
  window.open('https://ads.example/');
  document.getElementById('message').innerHTML='';
  document.getElementById('inbox').innerHTML='';
  setTimeout(() => {
    const notice = window.retryScenario && window.requests===1;
    const rows = notice ? [['notice', 'Microsoft account unusual sign-in activity']] : [
      ['notice', 'New app(s) connected to your Microsoft account'],
      ['new', 'Personal Microsoft account security code'],
      ['old', 'Personal Microsoft account security code']
    ];
    rows.forEach(([id, subject]) => {
      const li=document.createElement('li');
      li.textContent='account-security-noreply '+subject;
      li.addEventListener('click', () => {
        window.opened.push(id);
        const iframe=document.createElement('iframe');
        iframe.title='Email content';
        iframe.setAttribute('sandbox','allow-popups allow-popups-to-escape-sandbox');
        iframe.srcdoc='<table><tr><td id="i4">'+(id==='notice' ? 'Sign-in details' :
          'Security code: <span>'+(id==='new' ? '825827' : '111111')+'</span>')+'</td></tr></table>';
        document.getElementById('message').replaceChildren(iframe);
      });
      document.getElementById('inbox').appendChild(li);
    });
    document.getElementById('get').disabled=false;
    document.querySelector('#get span').style.display='';
  }, 300);
}
// A bubbling click handler mimics a page-level ad trigger.
document.addEventListener('click', () => window.overlayClicks++);
</script>
"""


def check_dom_clicks_ignore_overlay_and_read_latest_email(retry):
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context()
        html = MAILBOX_HTML.replace("RETRY_SCENARIO", "true" if retry else "false")
        context.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body=html if "fviainboxes.com" in route.request.url else "<body>Other tab</body>"
        ))
        microsoft = context.new_page()
        microsoft.goto("https://account.live.com/identity/confirm")
        unrelated = context.new_page()
        unrelated.goto("https://notes.example/")
        mailbox = context.new_page()
        mailbox.goto("https://fviainboxes.com/")
        try:
            code = read_code_in_fviainboxes_tab(
                context, "sample@fviainboxes.com", timeout_ms=25000,
                exclude_codes={"111111"},
            )
            assert code == "825827"
            assert mailbox.locator("#username").input_value() == "sample"
            assert mailbox.evaluate("window.requests") == (2 if retry else 1)
            assert mailbox.evaluate("window.opened") == (["notice", "new"] if retry else ["new"])
            assert mailbox.evaluate("window.overlayClicks") == 0
            assert mailbox.evaluate("window.wrongSubmit") is False
            assert not microsoft.is_closed()
            assert not unrelated.is_closed()
            assert len(context.pages) == 3
        finally:
            browser.close()


class FviainboxesDomTests(unittest.TestCase):
    def test_dom_clicks_ignore_overlay_and_read_latest_email(self):
        for retry in (False, True):
            with self.subTest(retry=retry):
                check_dom_clicks_ignore_overlay_and_read_latest_email(retry)

    def test_single_use_code_extraction(self):
        from app.services.microsoft_recovery import _extract_microsoft_code
        email_body = """Hi llevatarkeenpk7t@fviainboxes.com,

We received your request for a single-use code to use with your Microsoft account.

Your single-use code is: 899030

Only enter this code on an official website or app. Don't share it with anyone. We'll never ask for it outside an official platform.

Thanks,
The Microsoft account team
Privacy Statement: https://go.microsoft.com/fwlink/?LinkId=521839
Microsoft Corporation, One Microsoft Way, Redmond, WA 98052
"""
        code = _extract_microsoft_code(email_body)
        self.assertEqual(code, "899030")

        # Test các biến thể khác
        self.assertEqual(_extract_microsoft_code("Your single-use code is: 123456"), "123456")
        self.assertEqual(_extract_microsoft_code("Security code: 825827"), "825827")
        self.assertEqual(_extract_microsoft_code("Mã dùng một lần của bạn là: 654321"), "654321")

    def test_dismiss_notice_popup_via_click(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(f"<body>{NOTICE_POPUP_SNIPPET}</body>")
            self.assertTrue(is_fviainboxes_notice_present(page))
            dismissed = dismiss_fviainboxes_notice(page)
            self.assertTrue(dismissed)
            self.assertFalse(is_fviainboxes_notice_present(page))
            browser.close()

    def test_dismiss_notice_popup_via_escape(self):
        escape_html = """
        <div id="headlessui-dialog-panel-6" data-headlessui-state="open">
          <h2>Notice</h2>
          <script>
          window.addEventListener('keydown', e => {
              if (e.key === 'Escape') document.getElementById('headlessui-dialog-panel-6').remove();
          });
          </script>
        </div>
        """
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_content(escape_html)
            self.assertTrue(is_fviainboxes_notice_present(page))
            dismissed = dismiss_fviainboxes_notice(page)
            self.assertTrue(dismissed)
            self.assertFalse(is_fviainboxes_notice_present(page))
            browser.close()

    def test_read_code_with_notice_popup_present(self):
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context()
            html = MAILBOX_HTML.replace("RETRY_SCENARIO", "false") + NOTICE_POPUP_SNIPPET
            context.route("**/*", lambda route: route.fulfill(
                content_type="text/html", body=html if "fviainboxes.com" in route.request.url else "<body>Other tab</body>"
            ))
            mailbox = context.new_page()
            mailbox.goto("https://fviainboxes.com/")
            try:
                code = read_code_in_fviainboxes_tab(
                    context, "sample@fviainboxes.com", timeout_ms=25000,
                )
                self.assertEqual(code, "825827")
                self.assertFalse(is_fviainboxes_notice_present(mailbox))
            finally:
                browser.close()


if __name__ == "__main__":
    unittest.main()

