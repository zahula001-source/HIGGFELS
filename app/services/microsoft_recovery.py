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
                    rows = page.locator("div.overflow-y-auto li").filter(
                        has_text="account-security-noreply"
                    )
                    if rows.count() == 0:
                        continue
                    # The list is newest-first. Prefer the newest security-code
                    # email when a newer notification sits above it.
                    code_rows = rows.filter(has_text=re.compile("Microsoft account security code", re.I))
                    row = code_rows.first if code_rows.count() else rows.first
                    row.evaluate(click_dom)
                    opened = True
                # Only read the email iframe, never sponsored frames or arbitrary
                # six-digit numbers in notifications/advertisements.
                frames = page.locator('iframe[title="Email content"]')
                for index in range(frames.count()):
                    iframe = frames.nth(index).element_handle()
                    frame = iframe.content_frame() if iframe else None
                    if frame is None:
                        continue
                    cell = frame.locator("td#i4")
                    if cell.count() == 0:
                        continue
                    text = cell.first.text_content(timeout=1000) or ""
                    match = re.search(r"Security\s+code\s*:\s*(\d{6})\b", text, re.I)
                    if match and match.group(1) not in excluded:
                        print("fviainboxes: read security code from email iframe")
                        return match.group(1)
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
    patterns = (
        r"(?:security|verification|confirmation)\s+code\D{0,30}(\d{4,8})",
        r"(?:m[aã]\s+(?:b[aả]o\s+m[aậ]t|x[aá]c\s+(?:minh|nh[aậ]n)))\D{0,30}(\d{4,8})",
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

