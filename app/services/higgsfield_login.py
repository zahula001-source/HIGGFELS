VIDEO_URL = "https://higgsfield.ai/ai/video?model=genjutsu"


def video_login_state(page):
    """Return None until video navigation has rendered, then inspect auth buttons."""
    from urllib.parse import urlsplit, parse_qs
    url = urlsplit(page.url)
    if url.hostname != "higgsfield.ai" or url.path != "/ai/video":
        return None
    if parse_qs(url.query).get("model") != ["genjutsu"]:
        return None
    return page.evaluate(r"""() => {
        const visible = el => !!el.getClientRects().length;
        const auth = [...document.querySelectorAll('button.hfnav-auth-login, button.hfnav-auth-signup')];
        if (auth.some(visible)) return false;
        const buttons = [...document.querySelectorAll('button')];
        if (buttons.some(el => visible(el) && /^(login|sign up)$/i.test((el.innerText || '').trim()))) return false;
        if ([...document.querySelectorAll('button')].some(el => visible(el) && (el.innerText || '').includes('Continue with Microsoft'))) return false;
        // Do not count a blank/loading document as authenticated.
        if (!document.querySelector('.hfnav-actions-group, button.hfnav-avatar-ring, button[aria-label="Account menu"], header, nav')) return null;
        return true;
    }""")


def wait_video_login_state(page, timeout_ms=8000):
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    stable_since = None
    while time.monotonic() < deadline:
        state = video_login_state(page)
        if state is False:
            return False
        if state is True:
            if stable_since is None:
                stable_since = time.monotonic()
            elif time.monotonic() - stable_since >= 1:
                return True
        else:
            stable_since = None
        page.wait_for_timeout(200)
    return None


def read_free_gens(page, timeout_ms=8000):
    """Read the free-generation switch after login without changing it."""
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        result = page.evaluate(r"""() => {
            const switches = [...document.querySelectorAll(
                'button[role="switch"][aria-label="Use free gens"], [role="switch"]'
            )].filter(el => !!el.getClientRects().length);
            const sw = switches.find(el => /use free gens/i.test(el.getAttribute('aria-label') || el.innerText || ''));
            if (!sw) return null;
            const card = sw.closest('.rounded-xl') || sw.parentElement?.parentElement;
            const text = (card?.innerText || '').replace(/\s+/g, ' ');
            const match = text.match(/use free gens\s*(\d+)/i);
            const count = match ? Number(match[1]) : null;
            return {
                enabled: sw.getAttribute('aria-checked') === 'true',
                disabled: !!sw.disabled || sw.getAttribute('aria-disabled') === 'true',
                count
            };
        }""")
        if result is not None and not result.get('enabled') and not result.get('disabled') and result.get('count') != 0:
            try:
                page.locator('button[role="switch"][aria-label="Use free gens"]').click(force=True, timeout=2000)
                page.wait_for_timeout(350)
                continue
            except Exception:
                pass
        if result is not None:
            return result
        page.wait_for_timeout(250)
    return None


def read_quality(page, timeout_ms=6000):
    """Read the selected Quality value (480p/720p) after the editor renders."""
    import re
    import time
    deadline = time.monotonic() + timeout_ms / 1000
    while time.monotonic() < deadline:
        value = page.evaluate(r"""() => {
            const nodes = [...document.querySelectorAll(
                'button[aria-label="Quality"], [role="button"], button, div.rounded-xl'
            )].filter(el => !!el.getClientRects().length);
            for (const el of nodes) {
                const text = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
                if (!/^Quality\b/i.test(text) && el.getAttribute('aria-label') !== 'Quality') continue;
                if (/720\s*p?/i.test(text)) return '720p';
                if (/480\s*p?/i.test(text)) return '480p';
            }
            return '';
        }""")
        if value:
            return value
        page.wait_for_timeout(250)
    return ""
