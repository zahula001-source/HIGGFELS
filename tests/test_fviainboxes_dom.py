"""Browser regression checks using intercepted local HTML, no real mailbox."""
import unittest
from playwright.sync_api import sync_playwright

from app.services.microsoft_recovery import read_code_in_fviainboxes_tab


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


if __name__ == "__main__":
    unittest.main()
