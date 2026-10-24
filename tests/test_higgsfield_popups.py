"""Exercise the credits popup guard against locally intercepted browser pages."""
import unittest

from playwright.sync_api import sync_playwright

from app.services.higgsfield_popups import install_upgrade_plan_guard


HTML = """
<style>.sr-only { position:absolute;width:1px;height:1px;overflow:hidden; }</style>
<button type="button" class="fixed rounded-full" id="unrelated-close"
        onclick="window.wrongClicks++">
  <svg><path d="M7.75 7.75L16.25 16.25M16.25 7.75L7.75 16.25"></path></svg>
</button>
<div id="root"></div>
<script>
window.closedPopups=0;window.wrongClicks=0;window.purchases=0;
window.mountPopup = (hidden=false, lateButton=false, fullscreen=false) => {
    const popup=document.createElement('div');
    popup.id='upgrade';
    if (!fullscreen) popup.setAttribute('role','dialog');
    if (hidden) popup.style.display='none';
    popup.innerHTML='<h2 class="sr-only">Upgrade Plan to buy credits</h2>'+
        '<div><h2>Upgrade Plan to buy credits</h2></div>'+
        '<button onclick="window.purchases++">Get Plus</button>';
    document.getElementById('root').appendChild(popup);
    const addButton=() => {
        const close=document.createElement('button');
        close.type='button';close.className='fixed right-4 z-40 rounded-full';
        close.innerHTML='<svg><path d="M7.75 7.75L16.25 16.25M16.25 7.75L7.75 16.25"></path></svg>';
        close.onclick=() => {window.closedPopups++;popup.remove();};
        popup.appendChild(close);
    };
    if (lateButton) setTimeout(addButton,100); else addButton();
};
</script>
"""


class UpgradePlanGuardTests(unittest.TestCase):
    def setUp(self):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context()
        self.context.route("**/*", lambda route: route.fulfill(
            content_type="text/html", body=HTML,
        ))
        self.page = self.context.new_page()
        self.page.goto("https://higgsfield.ai/ai/video?model=genjutsu")

    def tearDown(self):
        self.browser.close()
        self.playwright.stop()

    def test_existing_delayed_and_repeated_popups(self):
        self.page.evaluate("mountPopup()")
        install_upgrade_plan_guard(self.context)
        install_upgrade_plan_guard(self.context)
        self.page.wait_for_function("window.closedPopups === 1")
        self.page.evaluate("mountPopup(false,true,true)")
        self.page.wait_for_function("window.closedPopups === 2")
        self.page.evaluate("mountPopup(true)")
        self.page.wait_for_timeout(600)
        self.assertEqual(self.page.evaluate("window.closedPopups"), 2)
        self.page.evaluate("document.getElementById('upgrade').style.display=''")
        self.page.wait_for_function("window.closedPopups === 3")
        self.assertEqual(self.page.evaluate("window.wrongClicks"), 0)
        self.assertEqual(self.page.evaluate("window.purchases"), 0)

    def test_reload_new_tabs_and_other_domains(self):
        install_upgrade_plan_guard(self.context)
        self.page.reload()
        self.page.evaluate("mountPopup()")
        self.page.wait_for_function("window.closedPopups === 1")
        new_page = self.context.new_page()
        new_page.goto("https://higgsfield.ai/ai/video?model=genjutsu")
        new_page.evaluate("mountPopup()")
        new_page.wait_for_function("window.closedPopups === 1")
        other = self.context.new_page()
        other.goto("https://fviainboxes.com/")
        other.evaluate("mountPopup()")
        other.wait_for_timeout(600)
        self.assertEqual(other.evaluate("window.closedPopups"), 0)


if __name__ == "__main__":
    unittest.main()
