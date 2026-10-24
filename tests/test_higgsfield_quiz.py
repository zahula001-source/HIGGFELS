"""Run the supplied Higgsfield answer cards in a real browser, without signup."""
import sys
from pathlib import Path
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playwright.sync_api import Locator, sync_playwright
from app.browser_settings import ensure_chrome_extension_binary
from app.services.higgsfield_quiz import handle_quiz_step
from app.services.browser_navigation import navigate_higgsfield


CARDS = (Path(__file__).parent / "fixtures" / "higgsfield_quiz_options.html").read_text(encoding="utf-8")
MOBILE_TRY_CARDS = (Path(__file__).parent / "fixtures" / "higgsfield_quiz_mobile_try.html").read_text(encoding="utf-8")
HTML = """<style>
body {margin:0;background:#080808;color:white;font-family:Arial}
section {padding:20px;max-width:850px;margin:auto} h1 {text-align:center}
.relative {position:relative} .flex.flex-col.gap-2 {display:flex;flex-direction:column;gap:8px}
button {width:100%;min-height:60px;text-align:left;padding:12px;background:#222;color:white;border:0}
button span {display:block} button svg {display:none} button[aria-pressed=true] {background:#454}
.q-checkbox {position:absolute;right:10px;top:20px;pointer-events:none}
[data-test-layout=mobile] {display:none}
@media(max-width:700px) {[data-test-layout=desktop] {display:none} [data-test-layout=mobile] {display:block}}
</style>""" + "".join(
    f'<section data-test-layout="{layout}" ' + ('data-quiz-mobile-question="true"' if layout == "mobile" else '') + '>'
    '<div class="progress">1 of 6</div><h1>What do you want<br>to achieve with Higgsfield?</h1>'
    + CARDS + '<button data-next disabled>Continue</button></section>' for layout in ("desktop", "mobile")
) + """<script>
window.attempts=0;window.selections=0;window.nextClicks=0;window.wrongClicks=0;
window.ignoreOptions=0;window.nextDelay=0;
document.querySelectorAll('button[aria-pressed]').forEach(el => el.dataset.testAnswer='true');
document.addEventListener('click', event => {
    const button=event.target.closest('button');
    if (!button) return;
    const root=button.closest('section');
    if (!root || !root.getClientRects().length) {window.wrongClicks++;return;}
    if (button.hasAttribute('data-test-answer')) {
        window.attempts++;
        if (window.ignoreOptions-->0) return;
        if (button.getAttribute('aria-pressed')==='true') {window.wrongClicks++;return;}
        window.selections++;
        if (button.hasAttribute('aria-pressed')) button.setAttribute('aria-pressed','true');
        button.parentElement.querySelector('[role=checkbox]').setAttribute('aria-checked','true');
        setTimeout(() => root.querySelector('[data-next]').disabled=false, window.nextDelay);
    } else if (button.hasAttribute('data-next')) {
        window.nextClicks++;
        root.querySelector('.progress').textContent=(window.nextClicks+1)+' of 6';
        root.querySelectorAll('[data-test-answer]').forEach(el => el.setAttribute('aria-pressed','false'));
        root.querySelectorAll('[role=checkbox]').forEach(el => el.setAttribute('aria-checked','false'));
        button.disabled=true;
    }
});
</script>"""


class QuizTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pw = sync_playwright().start()
        cls.browser = cls.pw.chromium.launch(executable_path=str(ensure_chrome_extension_binary()), headless=True)

    @classmethod
    def tearDownClass(cls):
        cls.browser.close()
        cls.pw.stop()

    def setUp(self):
        self.context = self.browser.new_context(viewport={"width":1280, "height":850})
        self.addCleanup(self.context.close)
        self.context.route("**/*", lambda route: route.fulfill(content_type="text/html", body=HTML))
        self.page = self.context.new_page()
        self.page.goto("https://higgsfield.ai/quiz?rp=%2Fai%2Fvideo")
        self.state = {}
        self.logs = []

    def advance(self, count=1):
        for _ in range(15):
            handle_quiz_step(self.page, self.state, self.logs.append)
            if self.page.evaluate("window.nextClicks") >= count:
                return
            self.page.wait_for_timeout(150)
        self.fail(f"Quiz did not advance: {self.logs}")

    def check_one_answer(self):
        self.assertEqual(self.page.evaluate("window.selections"), 1)
        self.assertEqual(self.page.evaluate("window.wrongClicks"), 0)

    def test_desktop_and_mobile_subtitle_and_hidden_duplicate(self):
        for width in (1280, 390):
            with self.subTest(width=width):
                self.page.set_viewport_size({"width":width, "height":850})
                self.page.reload()
                self.state.clear()
                self.page.evaluate("window.nextDelay=150")
                self.advance()
                self.check_one_answer()

    def test_mouse_fallback_when_locator_fails(self):
        with patch.object(Locator, "click", side_effect=RuntimeError("transient actionability failure")):
            self.advance()
        self.check_one_answer()
        self.assertTrue(any("mouse" in line for line in self.logs))

    def test_javascript_fallback_when_physical_click_misses(self):
        with patch.object(Locator, "click", side_effect=RuntimeError("transient actionability failure")), \
                patch.object(self.page.mouse, "click", return_value=None):
            self.advance()
        self.check_one_answer()
        self.assertTrue(any("javascript" in line for line in self.logs))

    def test_missed_click_is_retried_instead_of_blacklisted(self):
        self.page.evaluate("window.ignoreOptions=1")
        self.advance()
        self.check_one_answer()
        self.assertEqual(self.page.evaluate("window.attempts"), 2)

    def test_selected_answer_is_not_toggled_while_continue_loads(self):
        self.page.evaluate("window.nextDelay=1000")
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertEqual(self.page.evaluate("window.attempts"), 1)
        self.advance()
        self.check_one_answer()

    def test_same_answer_can_be_selected_on_following_question(self):
        self.advance()
        self.advance(2)
        self.assertEqual(self.page.evaluate("window.selections"), 2)
        self.assertEqual(self.page.evaluate("window.wrongClicks"), 0)

    def test_wait_for_hydration_and_checkbox_wrapper_fallback(self):
        self.page.evaluate("""() => {
            const buttons=[...document.querySelectorAll('[data-test-answer]')];
            buttons.forEach(el => {el.disabled=true;el.removeAttribute('aria-pressed');});
            setTimeout(() => buttons.forEach(el => el.disabled=false), 300);
        }""")
        self.assertFalse(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertEqual(self.page.evaluate("window.attempts"), 0)
        self.page.wait_for_timeout(350)
        self.advance()
        self.check_one_answer()

    def test_personal_use_block_subtitle_and_auto_advance(self):
        # The new first question has block titles/subtitles and no Continue.
        for tag in ('button type="button"', 'div class="cursor-pointer"'):
            with self.subTest(tag=tag):
                closing = tag.split()[0]
                self.page.set_content(f'''<section><h1>How do you plan<br>to use Higgsfield?</h1>
                    <{tag} data-personal><div>For personal use</div><div>For your own projects, at your own pace</div></{closing}>
                    <{tag}><div>For my team/organization</div><div>For teams that create and ship together</div></{closing}>
                    </section><script>
                    window.personalClicks=0;
                    document.querySelector('[data-personal]').onclick=() => {{
                        window.personalClicks++;
                        document.querySelector('section').innerHTML='<h1>What do you want to achieve with Higgsfield?</h1>';
                    }};
                    </script>''')
                self.assertTrue(handle_quiz_step(self.page, {}, self.logs.append))
                self.assertEqual(self.page.evaluate('window.personalClicks'), 1)

    def test_radio_selection_waits_for_continue_without_toggling(self):
        self.page.set_content('''<section><h1>How do you plan to use Higgsfield?</h1>
            <div class="row">
                <button data-personal><div>For personal use</div><div>For your own projects, at your own pace</div><input type="radio" name="use"></button>
                <button><div>For my team/organization</div><div>For teams that create and ship together</div><input type="radio" name="use"></button>
            </div><button data-next disabled>Continue</button></section>
            <script>
                window.personalClicks=0;
                document.querySelector('[data-personal]').onclick=event => {
                    window.personalClicks++;
                    event.currentTarget.querySelector('input').checked=true;
                    setTimeout(() => document.querySelector('[data-next]').disabled=false, 1100);
                };
                document.querySelector('[data-next]').onclick=() => document.querySelector('h1').textContent='Next question';
            </script>''')
        state = {}
        self.assertTrue(handle_quiz_step(self.page, state, self.logs.append))
        self.assertTrue(handle_quiz_step(self.page, state, self.logs.append))
        self.page.wait_for_timeout(1200)
        self.assertTrue(handle_quiz_step(self.page, state, self.logs.append))
        self.assertEqual(self.page.evaluate('window.personalClicks'), 1)
        self.assertEqual(self.page.locator('h1').inner_text(), 'Next question')

    def test_navigation_does_not_wait_for_slow_image(self):
        pending = []
        self.page.route('**/slow.png', lambda route: pending.append(route))
        self.page.route('**/ai/video**', lambda route: route.fulfill(
            content_type='text/html', body='<h1>Video editor</h1><img src="/slow.png">'))
        navigate_higgsfield(self.page, 'https://higgsfield.ai/ai/video?model=genjutsu', timeout_ms=1000)
        self.assertEqual(self.page.locator('h1').inner_text(), 'Video editor')
        self.assertEqual(self.page.evaluate('document.readyState'), 'interactive')
        self.page.wait_for_timeout(50)
        self.assertTrue(pending)
        for route in pending:
            route.fulfill(status=204, body='')

    def show_mobile_try(self, selected=True, next_delay=0):
        self.page.set_viewport_size({'width':390, 'height':850})
        self.page.set_content('''<style>
            body {margin:0;padding-bottom:100px;font-family:Arial}
            .grid {display:grid;grid-template-columns:1fr 1fr;gap:8px}
            .relative {position:relative} button[aria-pressed] {height:128px;width:100%}
            button svg {display:none} .q-checkbox {position:absolute;right:10px;top:10px;pointer-events:none}
            [data-quiz-mobile-continue] {position:fixed;bottom:0;left:0;right:0;padding:16px;background:white}
            [data-quiz-mobile-continue] button {width:100%;height:48px}
            [data-test-desktop] {display:none}
            </style><main><div class="progress">3 of 6</div>''' + MOBILE_TRY_CARDS + '''
            <div data-quiz-mobile-continue="true"><button type="button">Continue</button></div>
            <div data-test-desktop><h1>What do you want to try on Higgsfield?</h1><button>Continue</button></div>
            </main><script>
                window.answerClicks=0;window.continueClicks=0;window.wrongClicks=0;
                window.nextDelay=0;
                document.querySelector('[data-quiz-mobile-question]').addEventListener('click', event => {
                    const button=event.target.closest('button[aria-pressed]');
                    if (!button) return;
                    window.answerClicks++;
                    if (button.getAttribute('aria-pressed')==='true') {window.wrongClicks++;return;}
                    button.setAttribute('aria-pressed','true');
                    button.parentElement.querySelector('[role=checkbox]').setAttribute('aria-checked','true');
                    setTimeout(() => document.querySelector('[data-quiz-mobile-continue] button').disabled=false, window.nextDelay);
                });
                document.querySelector('[data-quiz-mobile-continue] button').onclick=() => {
                    window.continueClicks++;
                    document.querySelector('.progress').textContent='4 of 6';
                    document.querySelector('h1').textContent='Next question';
                };
                document.querySelector('[data-test-desktop] button').onclick=() => window.wrongClicks++;
            </script>''')
        if not selected:
            self.page.evaluate('''delay => {
                window.nextDelay=delay;
                document.querySelectorAll('[aria-pressed]').forEach(el => el.setAttribute('aria-pressed','false'));
                document.querySelectorAll('[role=checkbox]').forEach(el => el.setAttribute('aria-checked','false'));
                document.querySelector('[data-quiz-mobile-continue] button').disabled=true;
            }''', next_delay)

    def test_mobile_continue_outside_question_with_selected_answer(self):
        self.show_mobile_try()
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertEqual(self.page.evaluate('window.continueClicks'), 1)
        self.assertEqual(self.page.evaluate('window.answerClicks'), 0)
        self.assertEqual(self.page.evaluate('window.wrongClicks'), 0)

    def test_fixed_continue_click_uses_mouse_and_javascript_fallbacks(self):
        for strategy in ('mouse', 'javascript'):
            with self.subTest(strategy=strategy):
                self.show_mobile_try()
                self.state.clear()
                self.logs.clear()
                with patch.object(Locator, 'click', side_effect=RuntimeError('transient click failure')):
                    if strategy == 'javascript':
                        with patch.object(self.page.mouse, 'click', return_value=None):
                            self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
                    else:
                        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
                self.assertEqual(self.page.evaluate('window.continueClicks'), 1)
                self.assertEqual(self.page.evaluate('window.answerClicks'), 0)
                self.assertTrue(any('Continue/Next' in line and strategy in line for line in self.logs))

    def test_mobile_continue_appears_later_without_toggling_answer(self):
        self.show_mobile_try(selected=False, next_delay=1000)
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertEqual(self.page.evaluate('window.answerClicks'), 1)
        self.page.wait_for_timeout(1100)
        self.assertTrue(handle_quiz_step(self.page, self.state, self.logs.append))
        self.assertEqual(self.page.evaluate('window.continueClicks'), 1)
        self.assertEqual(self.page.evaluate('window.wrongClicks'), 0)

    def test_enabled_continue_is_used_even_with_unrecognized_selected_answer(self):
        self.page.set_content('''<main>
            <div><h1>What do you want to try on Higgsfield?</h1>
                <button disabled aria-pressed="false">Supercomputer</button>
                <button aria-pressed="true">A newly added product</button>
            </div><footer><button data-next>Continue</button></footer>
            </main><script>
                document.querySelector('[data-next]').onclick=() => document.querySelector('h1').textContent='Next question';
            </script>''')
        self.assertTrue(handle_quiz_step(self.page, {}, self.logs.append))
        self.assertEqual(self.page.locator('h1').inner_text(), 'Next question')

    def test_desktop_continue_in_separate_footer_ignores_hidden_mobile_button(self):
        self.page.set_content('''<main>
            <div data-quiz-mobile-question="true" style="display:none"><h1>Mobile question</h1></div>
            <div data-quiz-mobile-continue="true" style="display:none"><button>Continue</button></div>
            <div data-desktop-question><h1>What do you want to try on Higgsfield?</h1><button aria-pressed="true">Supercomputer</button></div>
            </main><footer><button data-next>Continue</button></footer><script>
                window.answerClicks=0;window.wrongClicks=0;
                document.querySelector('[aria-pressed]').onclick=() => window.answerClicks++;
                document.querySelector('[data-quiz-mobile-continue] button').onclick=() => window.wrongClicks++;
                document.querySelector('[data-next]').onclick=() => document.querySelector('[data-desktop-question] h1').textContent='Next question';
            </script>''')
        self.assertTrue(handle_quiz_step(self.page, {}, self.logs.append))
        self.assertEqual(self.page.locator('h1:visible').inner_text(), 'Next question')
        self.assertEqual(self.page.evaluate('window.answerClicks'), 0)
        self.assertEqual(self.page.evaluate('window.wrongClicks'), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
