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


def click_use_password(page) -> bool:
    """Check the current DOM without waiting for a missing password input."""
    try:
        exact = page.locator('[data-testid="viewFooter"] span[role="button"]').filter(has_text="Use your password").first
        if exact.count() > 0 and exact.is_visible(timeout=200):
            exact.click(force=True, timeout=3000)
            page.wait_for_timeout(500)
            return True
    except Exception:
        pass
    return page.evaluate("""() => {
        const nodes = document.querySelectorAll('button, a, [role="button"], span');
        for (const el of nodes) {
            if (!el.getClientRects().length) continue;
            const text = (el.innerText || '').trim().toLowerCase();
            if (text === 'use your password' || text === 'sử dụng mật khẩu của bạn' ||
                el.id === 'iUsePasswordLink' || el.id === 'idA_PWD_SwitchToPassword') {
                el.click();
                return true;
            }
        }
        return false;
    }""")


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
        return bool(self.recovery_email and self.recovery_password)


def parse_microsoft_account(raw: str) -> Optional[MicrosoftAccount]:
    """Parse both legacy 4-field and recovery-mail 6-field account rows."""
    parts = [part.strip() for part in (raw or "").strip().split("|")]
    if len(parts) < 2 or not parts[0] or not parts[1]:
        return None
    return MicrosoftAccount(
        email=parts[0],
        password=parts[1],
        refresh_token=parts[2] if len(parts) > 2 else "",
        client_id=parts[3] if len(parts) > 3 else "",
        recovery_email=parts[4] if len(parts) > 4 else "",
        recovery_password=parts[5] if len(parts) > 5 else "",
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

