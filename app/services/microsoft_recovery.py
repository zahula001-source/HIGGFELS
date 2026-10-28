import json
import re
import urllib.request
import urllib.error
from dataclasses import dataclass
from typing import Optional, Set, Tuple


SMAIL1S_MESSAGES_URL = "https://smail1s.com/get_messages"


class MailboxAccessDenied(RuntimeError):
    """The provider denied access; retrying the same client is not useful."""


def read_code_in_smail_tab(
    context,
    email: str,
    password: str,
    timeout_ms: int = 60000,
    *,
    refresh: bool = False,
    exclude_codes: Optional[Set[str]] = None,
) -> str:
    """Read a wmhotmail code through the visible smail1s web UI."""
    smail_pages = [p for p in context.pages if not p.is_closed() and "smail1s.com" in p.url]
    page = next((p for p in smail_pages if p.locator("#data").count() > 0), None)
    page = page or (smail_pages[0] if smail_pages else None)
    if page is None:
        page = context.new_page()
    for duplicate in smail_pages:
        if duplicate != page:
            try:
                duplicate.close()
            except Exception:
                pass
    page.bring_to_front()
    # The watchdog calls this function repeatedly. Keep the existing page and
    # request; navigating here would clear the results and cause an endless reload.
    data = page.locator("#data")
    needs_request = not page.url.startswith("https://smail1s.com") or data.count() == 0
    if needs_request:
        try:
            page.goto("https://smail1s.com/", wait_until="commit", timeout=15000)
        except Exception:
            # Cloudflare or slow resources can outlive navigation; the DOM may
            # still become usable, so continue and wait for the form explicitly.
            pass
        data = page.locator("#data")
        data.wait_for(state="visible", timeout=15000)
        data.fill(f"{email}|{password}")
        mode = page.locator("#modeRoundcube")
        if mode.count() > 0:
            try:
                mode.check(force=True)
            except Exception:
                page.locator('label[for="modeRoundcube"]').click(force=True)
        else:
            page.locator('label[for="modeRoundcube"]').click(force=True)
        page.locator("#btnFetch").click(force=True)
    elif refresh:
        # Existing result rows are deliberately refreshed.  Otherwise a
        # failed Microsoft OTP would make us submit the same stale code again.
        fetch_button = page.locator("#btnFetch")
        fetch_button.wait_for(state="visible", timeout=10000)
        fetch_button.click(force=True)
        page.wait_for_timeout(300)
        refresh_deadline = __import__("time").monotonic() + min(timeout_ms / 1000, 30)
        while __import__("time").monotonic() < refresh_deadline:
            try:
                label = fetch_button.inner_text(timeout=500).lower()
            except Exception:
                label = ""
            if "đang tải" not in label and "loading" not in label:
                break
            page.wait_for_timeout(300)
        page.wait_for_timeout(500)
    excluded = {str(code).strip() for code in (exclude_codes or set()) if code}
    deadline = __import__("time").monotonic() + timeout_ms / 1000
    while __import__("time").monotonic() < deadline:
        buttons = page.locator("button.copy-btn[data-code]")
        for i in range(buttons.count()):
            button = buttons.nth(i)
            if button.is_visible(timeout=200):
                code = (button.get_attribute("data-code") or "").strip()
                if re.fullmatch(r"\d{4,8}", code) and code not in excluded:
                    try:
                        row_text = button.locator("xpath=ancestor::tr[1]").inner_text(timeout=200).lower()
                    except Exception:
                        row_text = ""
                    if not row_text or "microsoft" in row_text or "security" in row_text or "安全" in row_text:
                        return code
        page.wait_for_timeout(1000)
    raise TimeoutError("Không thấy mã Microsoft trên tab smail1s")


def _extract_microsoft_code(text: str) -> Optional[str]:
    """Trích xuất mã OTP Microsoft (single-use code, security code, mã dùng một lần, v.v.)."""
    if not text:
        return None
    normalized = text.replace("\xa0", " ").replace("&nbsp;", " ")
    patterns = [
        # Dạng single-use code: "Your single-use code is: 899030" hoặc "single-use code is: 899030"
        r"single[- ]use\s+code(?:\s+is)?\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6})\b",
        # Tiếng Việt: "Mã dùng một lần của bạn là: 899030"
        r"mã\s+dùng\s+một\s+lần(?:\s+của\s+bạn)?(?:\s+là)?\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6})\b",
        # Dạng truyền thống: "Security code: 825827" hoặc "Security code is: 825827"
        r"security\s+code(?:\s+is)?\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6,8})\b",
        # Tiếng Việt: "Mã bảo mật: 825827"
        r"mã\s+bảo\s+mật(?:\s+là)?\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6,8})\b",
        # Các dạng khác: "Verification code: 899030" / "Your code is: 899030"
        r"(?:verification|account|confirmation)\s+code(?:\s+is)?\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6})\b",
        r"your\s+code\s+is\s*[:：]?\s*(?:<[^>]+>)*\s*(\d{6})\b",
        # Fallback: "code: 899030"
        r"\bcode\s*[:：]\s*(?:<[^>]+>)*\s*(\d{6})\b",
    ]
    for pat in patterns:
        m = re.search(pat, normalized, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return None


def read_code_in_fviainboxes_tab(
    context, email: str, timeout_ms: int = 60000, *, refresh: bool = False,
    exclude_codes: Optional[Set[str]] = None,
) -> str:
    """Read the newest code using DOM clicks, unaffected by ad overlays."""
    import time
    from urllib.parse import urlsplit

    def host(tab):
        return urlsplit(tab.url).hostname

    microsoft_pages = [p for p in context.pages if not p.is_closed() and host(p) in {
        "account.live.com", "login.live.com", "login.microsoftonline.com",
    }]
    pages = [p for p in context.pages if not p.is_closed() and host(p) == "fviainboxes.com"]
    page = pages[0] if pages else context.new_page()
    for duplicate in pages[1:]:
        duplicate.close()

    def close_mailbox_popup(popup):
        # Only popups opened by this mailbox; other profile tabs are preserved.
        try:
            popup.close()
        except Exception:
            pass

    page.on("popup", close_mailbox_popup)
    try:
        page.bring_to_front()
        if host(page) != "fviainboxes.com":
            page.goto("https://fviainboxes.com/", wait_until="domcontentloaded", timeout=20000)
        # Tự động phát hiện và giải Cloudflare Turnstile như người thật nếu fviainboxes bắt xác minh
        try:
            from app.services.stealth import solve_cloudflare_turnstile
            solve_cloudflare_turnstile(page, timeout_sec=10)
        except Exception as e_cf:
            print(f"fviainboxes turnstile check: {e_cf}")
        user_input = page.locator("#username, input[name='username']").first
        user_input.wait_for(state="visible", timeout=15000)
        user_input.fill(email.split("@", 1)[0])
        # No generic submit fallback: the page also contains sponsored controls.
        # Match the span's text even while it is hidden by the loading spinner.
        get_mail = page.locator('button[type="submit"]:has(span:text-is("Get Email"))')
        get_mail.wait_for(state="visible", timeout=10000)
        excluded = {str(c).strip() for c in (exclude_codes or set()) if c}
        deadline = time.monotonic() + timeout_ms / 1000
        click_dom = """el => {
            if (el.disabled) return false;
            // Let the element's Vue handler run, then stop bubbling to ads.
            el.addEventListener('click', event => event.stopPropagation(), {once: true});
            HTMLElement.prototype.click.call(el);
            return true;
        }"""
        for attempt in range(4):
            if time.monotonic() >= deadline:
                break
            # Nếu fviainboxes kích hoạt captcha_required giữa chừng, tự động click giải Turnstile
            try:
                from app.services.stealth import solve_cloudflare_turnstile
                solve_cloudflare_turnstile(page, timeout_sec=8)
            except Exception:
                pass
            # Wait for the previous request to finish instead of force-clicking
            # a disabled/loading button. Retry only when no usable code arrived.
            while not get_mail.evaluate(click_dom):
                if time.monotonic() >= deadline:
                    raise TimeoutError("Get Email vẫn đang tải")
                page.wait_for_timeout(250)
            print(f"fviainboxes: requested inbox ({attempt + 1}/4)")
            opened = False
            read_deadline = min(deadline, time.monotonic() + 10)
            while time.monotonic() < read_deadline:
                page.wait_for_timeout(250)
                if not get_mail.is_enabled():
                    continue
                if not opened:
                    rows = page.locator("div.overflow-y-auto li, ul li").filter(
                        has_text="account-security-noreply"
                    )
                    if rows.count() == 0:
                        rows = page.locator("li, tr, [role='listitem']").filter(
                            has_text="account-security-noreply"
                        )
                    if rows.count() == 0:
                        continue
                    # Ưu tiên các thư có tiêu đề liên quan đến mã xác minh/mã dùng một lần
                    code_rows = rows.filter(
                        has_text=re.compile(
                            r"(Microsoft account security code|Your single[- ]use code|single[- ]use code|security code|mã dùng một lần|mã bảo mật)",
                            re.I,
                        )
                    )
                    row = code_rows.first if code_rows.count() else rows.first
                    row.evaluate(click_dom)
                    opened = True

                # 1. Kiểm tra iframe chứa nội dung email
                frames = page.locator('iframe[title="Email content"]')
                for index in range(frames.count()):
                    iframe = frames.nth(index).element_handle()
                    frame = iframe.content_frame() if iframe else None
                    if frame is None:
                        continue
                    # A) Kiểm tra ô td#i4 nếu có (dạng email Microsoft cũ)
                    try:
                        cell = frame.locator("td#i4")
                        if cell.count() > 0:
                            text = cell.first.text_content(timeout=500) or ""
                            code = _extract_microsoft_code(text)
                            if code and code not in excluded:
                                print(f"fviainboxes: read security code {code} from iframe td#i4")
                                return code
                    except Exception:
                        pass
                    # B) Kiểm tra toàn bộ body của iframe (dạng Your single-use code)
                    try:
                        body_loc = frame.locator("body")
                        if body_loc.count() > 0:
                            text = body_loc.first.inner_text(timeout=500) or ""
                            code = _extract_microsoft_code(text)
                            if code and code not in excluded:
                                print(f"fviainboxes: read security code {code} from iframe body")
                                return code
                            # Thử raw html content nếu có thẻ span/b ngăn cách
                            raw_html = frame.content()
                            code = _extract_microsoft_code(raw_html)
                            if code and code not in excluded:
                                print(f"fviainboxes: read security code {code} from iframe html")
                                return code
                    except Exception:
                        pass

                # 2. Kiểm tra vùng đọc email trực tiếp trên trang chính (nếu không dùng iframe)
                if opened:
                    try:
                        reading_pane = page.locator(
                            '#message, div.email-content, div.message-content, [data-testid="email-body"], '
                            'div:has-text("Your single-use code"):not(:has(li)), '
                            'div:has-text("single-use code"):not(:has(li))'
                        )
                        for p_idx in range(min(reading_pane.count(), 5)):
                            p_elem = reading_pane.nth(p_idx)
                            p_text = p_elem.inner_text(timeout=300) or ""
                            if "single-use code" in p_text.lower() or "security code" in p_text.lower():
                                code = _extract_microsoft_code(p_text)
                                if code and code not in excluded:
                                    print(f"fviainboxes: read security code {code} from main reading pane")
                                    return code
                    except Exception:
                        pass
            if attempt < 3 and time.monotonic() < deadline:
                print("fviainboxes: no usable security code; retrying Get Email")
                page.wait_for_timeout(min(3000, max(0, (deadline - time.monotonic()) * 1000)))
        raise TimeoutError("Không thấy mã Microsoft trên tab fviainboxes")
    finally:
        page.remove_listener("popup", close_mailbox_popup)
        for microsoft_page in microsoft_pages:
            if not microsoft_page.is_closed():
                microsoft_page.bring_to_front()
                break


def click_use_password(page) -> bool:
    """Check the current DOM and click 'Use your password' / 'Sử dụng mật khẩu của bạn'."""
    selectors = [
        'span[role="button"]:has-text("Use your password")',
        'span.fui-Link:has-text("Use your password")',
        '[role="button"]:has-text("Use your password")',
        'span:has-text("Use your password")',
        'a:has-text("Use your password")',
        'button:has-text("Use your password")',
        'span[role="button"]:has-text("Sử dụng mật khẩu")',
        'span.fui-Link:has-text("Sử dụng mật khẩu")',
        '[role="button"]:has-text("Sử dụng mật khẩu")',
        'span:has-text("Sử dụng mật khẩu")',
        'a:has-text("Sử dụng mật khẩu")',
        'button:has-text("Sử dụng mật khẩu")',
        '#iUsePasswordLink',
        '#idA_PWD_SwitchToPassword',
    ]
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible(timeout=250):
                try:
                    loc.scroll_into_view_if_needed(timeout=1000)
                except Exception:
                    pass
                loc.click(force=True, timeout=2000)
                page.wait_for_timeout(500)
                print(f"[click_use_password] Clicked via selector: {sel}")
                return True
        except Exception:
            pass

    try:
        clicked = page.evaluate("""() => {
            const isVisible = (el) => {
                if (!el) return false;
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return false;
                const rect = el.getBoundingClientRect();
                return rect.width > 0 && rect.height > 0;
            };

            const candidates = document.querySelectorAll('span, a, button, div, [role="button"], .fui-Link, input[type="button"]');
            for (const el of candidates) {
                const text = (el.innerText || el.textContent || el.value || '').trim().toLowerCase();
                const matches = (
                    text === 'use your password' ||
                    text.includes('use your password') ||
                    text.includes('use password') ||
                    text.includes('sử dụng mật khẩu') ||
                    text.includes('dùng mật khẩu') ||
                    text.includes('usar su contraseña') ||
                    text.includes('usar contraseña') ||
                    text.includes('utiliser votre mot de passe') ||
                    el.id === 'iUsePasswordLink' ||
                    el.id === 'idA_PWD_SwitchToPassword'
                );
                if (matches && isVisible(el)) {
                    try { el.focus(); } catch(e) {}
                    try { el.click(); } catch(e) {}
                    try { el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true })); } catch(e) {}
                    try { el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true })); } catch(e) {}
                    try { el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true })); } catch(e) {}
                    try { el.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, which: 13, bubbles: true })); } catch(e) {}
                    return true;
                }
            }
            return false;
        }""")
        if clicked:
            page.wait_for_timeout(500)
            print("[click_use_password] Clicked via JS evaluation")
            return True
    except Exception as e:
        print(f"[click_use_password] JS error: {e}")

    return False


def click_human_like(page, target) -> bool:
    """Mô phỏng click chuột như người thật:
    - Blur phần tử đang focus để kích hoạt xác thực giá trị (tránh lỗi 'That code didn't work')
    - Cuộn phần tử vào màn hình (scroll_into_view_if_needed)
    - Di chuyển chuột từ từ đến tâm nút (page.mouse.move)
    - Hover phần tử (element.hover)
    - Giữ chuột (page.mouse.down -> sleep 80ms -> page.mouse.up)
    - Playwright click với delay
    - JavaScript dispatch đầy đủ chuỗi sự kiện chuột
    """
    if target is None:
        return False
    try:
        # Blur phần tử đang focus để kích hoạt sự kiện change/blur của Microsoft
        try:
            if hasattr(page, "evaluate"):
                page.evaluate("() => { if (document.activeElement && document.activeElement.blur) document.activeElement.blur(); }")
        except Exception:
            pass

        if isinstance(target, str):
            loc = page.locator(target) if hasattr(page, "locator") else None
            if loc is None or (hasattr(loc, "count") and loc.count() == 0):
                return False
            elem = loc.first if hasattr(loc, "first") else loc
        else:
            elem = target

        if hasattr(elem, "is_visible") and not elem.is_visible(timeout=500):
            return False

        # 1. Scroll vào tầm nhìn
        if hasattr(elem, "scroll_into_view_if_needed"):
            try:
                elem.scroll_into_view_if_needed(timeout=1000)
            except Exception:
                pass

        # 2. Lấy tọa độ bounding box và di chuyển chuột đến nút
        box = None
        if hasattr(elem, "bounding_box"):
            try:
                b = elem.bounding_box()
                if isinstance(b, dict):
                    box = b
            except Exception:
                box = None

        if box and hasattr(page, "mouse"):
            target_x = box.get("x", 0) + box.get("width", 0) / 2
            target_y = box.get("y", 0) + box.get("height", 0) / 2
            try:
                page.mouse.move(target_x, target_y, steps=5)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(80)
            except Exception:
                pass

        # 3. Hover vào nút
        if hasattr(elem, "hover"):
            try:
                elem.hover(timeout=1000)
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(80)
            except Exception:
                pass

        # 4. Nhấn giữ chuột như người thật (mousedown -> wait 80ms -> mouseup)
        if box and hasattr(page, "mouse"):
            try:
                page.mouse.down()
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(80)
                page.mouse.up()
                if hasattr(page, "wait_for_timeout"):
                    page.wait_for_timeout(50)
            except Exception:
                pass

        # 5. Playwright click
        clicked = False
        if hasattr(elem, "click"):
            try:
                elem.click(timeout=3000)
                clicked = True
            except TypeError:
                try:
                    elem.click()
                    clicked = True
                except Exception:
                    pass
            except Exception:
                pass

        # 6. JavaScript dispatch chuỗi sự kiện chuột đầy đủ
        if hasattr(elem, "evaluate"):
            try:
                elem.evaluate(r"""(btn) => {
                    if (!btn) return;
                    btn.focus();
                    const opts = { bubbles: true, cancelable: true, view: window };
                    btn.dispatchEvent(new MouseEvent('mouseenter', opts));
                    btn.dispatchEvent(new MouseEvent('mouseover', opts));
                    btn.dispatchEvent(new MouseEvent('mousedown', opts));
                    btn.dispatchEvent(new MouseEvent('mouseup', opts));
                    btn.dispatchEvent(new MouseEvent('click', opts));
                    if (btn.form) {
                        try { btn.form.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true })); } catch(e){}
                    }
                }""")
                clicked = True
            except Exception:
                pass

        return clicked
    except Exception as e:
        print(f"click_human_like error: {e}")
        return False


def fill_and_submit_otp(page, otp_code: str, first_visible_func=None) -> bool:
    """Điền mã OTP vào trang Microsoft (hỗ trợ cả ô đơn lẻ và nhiều ô rời rạc Fluent UI: codeEntry-0..5)
    và bấm nút xác nhận / Tiếp theo hoặc Enter.
    """
    code_digits = re.sub(r"\D", "", str(otp_code or "").strip())
    if not code_digits:
        return False

    seg_selector = (
        'input[id^="codeEntry-"], '
        'div[data-testid="codeEntry"] input, '
        'div[data-testid="codeInputWrapper"] input, '
        'input[aria-label*="Enter code digit" i], '
        'input[id^="idTxtBx_SAOTCC_OTC_"]'
    )
    segmented_inputs = page.locator(seg_selector)
    seg_count = 0
    try:
        seg_count = segmented_inputs.count()
    except Exception:
        seg_count = 0

    if seg_count >= 4:
        print(f"Watchdog: detected {seg_count} segmented OTP inputs (codeEntry / Fluent UI), filling code {code_digits}...")
        # 1) Thử paste vào ô đầu tiên (Fluent UI component thường lắng nghe onPaste trên ô đầu tiên để tự chia đều)
        try:
            page.evaluate(r"""(code) => {
                const first = document.getElementById('codeEntry-0') || 
                              document.querySelector('[data-testid="codeEntry"] input') ||
                              document.querySelector('input[id^="codeEntry-"]');
                if (!first) return;
                first.focus();
                const dt = new DataTransfer();
                dt.setData('text/plain', code);
                const pasteEv = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
                first.dispatchEvent(pasteEv);
            }""", code_digits)
            page.wait_for_timeout(100)
        except Exception:
            pass

        # 2) Dùng JS set giá trị theo prototype setter của HTMLInputElement và kích hoạt đầy đủ các sự kiện (input, change, keydown, keyup)
        try:
            page.evaluate(r"""(code) => {
                const inputs = Array.from(document.querySelectorAll(
                    'input[id^="codeEntry-"], div[data-testid="codeEntry"] input, div[data-testid="codeInputWrapper"] input, input[aria-label*="Enter code digit" i], input[id^="idTxtBx_SAOTCC_OTC_"]'
                ));
                const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                for (let i = 0; i < code.length && i < inputs.length; i++) {
                    const el = inputs[i];
                    el.focus();
                    if (setter) {
                        setter.call(el, code[i]);
                    } else {
                        el.value = code[i];
                    }
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keydown', { key: code[i], code: `Digit${code[i]}`, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keypress', { key: code[i], code: `Digit${code[i]}`, bubbles: true }));
                    el.dispatchEvent(new KeyboardEvent('keyup', { key: code[i], code: `Digit${code[i]}`, bubbles: true }));
                }
            }""", code_digits)
            page.wait_for_timeout(150)
        except Exception:
            pass

        # 3) Đảm bảo Playwright locator fill từng ô
        for i, digit in enumerate(code_digits):
            if i < seg_count:
                try:
                    inp = segmented_inputs.nth(i)
                    val = ""
                    if hasattr(inp, "input_value"):
                        try:
                            val = inp.input_value(timeout=100)
                        except Exception:
                            val = ""
                    if val != digit:
                        if hasattr(inp, "click"):
                            try:
                                inp.click(timeout=500)
                            except Exception:
                                pass
                        inp.fill(digit, timeout=1000)
                        page.wait_for_timeout(50)
                except Exception:
                    try:
                        segmented_inputs.nth(i).fill(digit, timeout=1000)
                    except Exception:
                        pass
    else:
        single_input = None
        if first_visible_func is not None:
            single_input = first_visible_func(
                '#iOttText, input[name="otc"], input[autocomplete="one-time-code"], '
                'input[id^="idTxtBx_SAOTCC_OTC"], input[id*="otc" i], '
                'input[inputmode="numeric"]:not([maxlength="1"]), input[type="text"]:not([maxlength="1"])'
            )
        if single_input is None:
            try:
                loc = page.locator(
                    '#iOttText, input[name="otc"], input[autocomplete="one-time-code"], '
                    'input[id^="idTxtBx_SAOTCC_OTC"], input[id*="otc" i]'
                )
                if loc.count() > 0:
                    single_input = loc.first
            except Exception:
                pass

        if single_input is not None:
            try:
                single_input.click(timeout=1000)
            except Exception:
                pass
            single_input.fill(code_digits, timeout=3000)
            try:
                page.evaluate(r"""(val) => {
                    const el = document.getElementById('iOttText') || 
                               document.querySelector('input[name="otc"]') || 
                               document.querySelector('input[autocomplete="one-time-code"]') ||
                               document.querySelector('input[inputmode="numeric"]:not([maxlength="1"])');
                    if (!el) return;
                    el.focus();
                    const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                    if (setter) setter.call(el, val);
                    el.dispatchEvent(new Event('input', { bubbles: true }));
                    el.dispatchEvent(new Event('change', { bubbles: true }));
                }""", code_digits)
            except Exception:
                pass
            print(f"Watchdog: filled OTP {code_digits} in single input")

    # Bấm nút xác nhận / tiếp theo
    page.wait_for_timeout(300)
    submit_selectors = (
        '#iVerifyCodeAction, #idSubmit_SAOTCC_Continue, #idSIButton9, '
        'button[data-testid="primaryButton"], '
        'button[type="submit"], input[type="submit"], '
        'button:has-text("Next"), button:has-text("Verify"), '
        'button:has-text("Tiếp theo"), button:has-text("Xác nhận"), '
        'button:has-text("Tiếp tục")'
    )
    submit_button = None
    if first_visible_func is not None:
        submit_button = first_visible_func(submit_selectors)
    if submit_button is None:
        try:
            btn_loc = page.locator(submit_selectors)
            for idx in range(btn_loc.count()):
                btn = btn_loc.nth(idx)
                if btn.is_visible(timeout=200):
                    submit_button = btn
                    break
        except Exception:
            pass

    submitted = False
    if submit_button is not None:
        try:
            is_en = True
            if hasattr(submit_button, "is_enabled"):
                try:
                    is_en = submit_button.is_enabled()
                except Exception:
                    is_en = True
            if is_en:
                submitted = click_human_like(page, submit_button)
                if not submitted and hasattr(submit_button, "click"):
                    submit_button.click(timeout=3000)
                    submitted = True
                print("Watchdog: clicked submit button for OTP")
        except Exception as e:
            print(f"Watchdog: error clicking OTP submit button: {e}")

    if not submitted:
        try:
            if seg_count >= 4:
                segmented_inputs.last.press("Enter")
            elif single_input is not None:
                single_input.press("Enter")
            else:
                page.keyboard.press("Enter")
            print("Watchdog: pressed Enter to submit OTP")
        except Exception as e:
            print(f"Watchdog: error pressing Enter: {e}")

    return True


@dataclass(frozen=True)
class MicrosoftAccount:
    email: str
    password: str
    refresh_token: str = ""
    client_id: str = ""
    recovery_email: str = ""
    recovery_password: str = ""

    @property
    def is_v2(self) -> bool:
        # A recovery address is enough for Microsoft's proof-selection page.
        # The mailbox password is optional because the OTP may be entered
        # manually (or retrieved by a separate mailbox integration).
        return bool(self.recovery_email)


def parse_microsoft_account(raw: str) -> Optional[MicrosoftAccount]:
    """Parse legacy rows and recovery-mail rows.

    Supported layouts:
      email|password|refresh_token|client_id
      email|password|refresh_token|client_id|recovery_email
      email|password|refresh_token|client_id|recovery_email|recovery_password
    """
    parts = [part.strip() for part in (raw or "").strip().split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    # Five-field rows are the common imported format where the recovery
    # mailbox password is intentionally omitted.
    recovery_email = parts[4] if len(parts) > 4 else ""
    recovery_password = parts[5] if len(parts) > 5 else ""
    return MicrosoftAccount(
        email=parts[0],
        password=parts[1],
        refresh_token=parts[2] if len(parts) > 2 else "",
        client_id=parts[3] if len(parts) > 3 else "",
        recovery_email=recovery_email,
        recovery_password=recovery_password,
    )


def _extract_code(message: dict) -> str:
    direct = str(message.get("code") or "").strip()
    if re.fullmatch(r"\d{4,8}", direct):
        return direct
    text = " ".join(
        str(message.get(field) or "")
        for field in ("subject", "message", "body", "text")
    )
    extracted = _extract_microsoft_code(text)
    if extracted:
        return extracted
    patterns = (
        r"(?:single[- ]use\s+code(?:\s+is)?)\D{0,20}(\d{4,8})",
        r"(?:security|verification|confirmation)\s+code\D{0,30}(\d{4,8})",
        r"(?:m[aã]\s+(?:b[aả]o\s+m[aậ]t|x[aá]c\s+(?:minh|nh[aậ]n)|d[uù]ng\s+m[oộ]t\s+l[aầ]n))\D{0,30}(\d{4,8})",
        r"\b(\d{6})\b",
    )
    for pattern in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            return match.group(1)
    return ""


def fetch_roundcube_messages(
    email: str,
    password: str,
    timeout: float = 15,
) -> Tuple[Set[str], str]:
    """Return message UIDs and the newest extracted OTP via the smail1s API.

    ProxyHandler({}) is deliberate: the mailbox request must use the host's
    original connection, not the VPN/proxy assigned to the browser profile.
    """
    payload = json.dumps(
        {"mode": "roundcube", "data": f"{email}|{password}"}
    ).encode("utf-8")
    request = urllib.request.Request(
        SMAIL1S_MESSAGES_URL,
        data=payload,
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        method="POST",
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            result = json.loads(response.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise MailboxAccessDenied(
                f"smail1s refused API access (HTTP {error.code}); manual OTP required"
            ) from None
        raise

    rows = result.get("data") or []
    if not rows:
        return set(), ""
    row = rows[0] or {}
    if row.get("error"):
        raise RuntimeError(str(row["error"]))
    messages = row.get("messages") or []
    uids = {str(message.get("uid")) for message in messages if message.get("uid") is not None}
    for message in messages:
        code = _extract_code(message)
        if code:
            return uids, code
    return uids, ""

