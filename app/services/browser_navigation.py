"""Keep VPN installation pages out of automation and user profile tabs."""

import re
from urllib.parse import urlsplit


def navigate_higgsfield(page, url, log=print, attempts=3, timeout_ms=30000):
    """Wait for the DOM, allowing quiz/auth redirects and slow VPN assets.

    Retry failed connections, but do not reload an already usable document
    merely because a media resource or analytics script has not finished.
    """
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError

    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            return
        except Exception as error:
            if page.is_closed():
                raise
            if isinstance(error, PlaywrightTimeoutError):
                try:
                    current = urlsplit(page.url)
                    usable = (
                        current.hostname == "higgsfield.ai"
                        and (current.path == urlsplit(url).path or current.path == "/quiz" or current.path.startswith("/auth/"))
                    ) and page.evaluate("""() =>
                        ['interactive', 'complete'].includes(document.readyState)
                        && !!document.body?.innerText.trim()
                    """)
                    if usable:
                        log("Higgsfield: DOM đã hiển thị, tiếp tục thao tác dù tài nguyên tải chậm.")
                        return
                except Exception:
                    pass
            if attempt == attempts:
                raise
            log(f"Higgsfield: tải trang chưa thành công ({attempt}/{attempts}), thử lại sau khi kết nối ổn định: {error}")
            page.wait_for_timeout(1500)


VPN_WELCOME_URL = re.compile(
    r"^https?://[^/]+/(?:.*welcome.*|.*thank-you.*|.*installed.*|.*success.*)(?:[/?#]|$)", re.I
)
HIGGSFIELD_PRICING_URL = re.compile(
    r"^https?://(?:www\.)?higgsfield\.ai/pricing(?:/|[?#]|$)", re.I
)

PRICING_NAVIGATION_GUARD = r"""(() => {
    if (!['higgsfield.ai', 'www.higgsfield.ai'].includes(location.hostname.toLowerCase())) return;
    if (window.__higgsfieldPricingGuard) return;
    window.__higgsfieldPricingGuard = true;

    const isPricing = value => {
        try {
            const url = new URL(value, location.href);
            return ['higgsfield.ai', 'www.higgsfield.ai'].includes(url.hostname.toLowerCase()) &&
                /^\/pricing(?:\/|$)/i.test(url.pathname);
        } catch {
            return false;
        }
    };

    document.addEventListener('click', event => {
        const link = event.composedPath().find(
            element => element instanceof HTMLAnchorElement && isPricing(element.href)
        );
        if (link) {
            event.preventDefault();
            event.stopImmediatePropagation();
        }
    }, true);

    for (const method of ['pushState', 'replaceState']) {
        const original = history[method];
        history[method] = function(state, title, url) {
            if (url && isPricing(url)) {
                queueMicrotask(() => window.dispatchEvent(
                    new PopStateEvent('popstate', {state: history.state})
                ));
                return;
            }
            return original.apply(this, arguments);
        };
    }
})();"""


def install_higgsfield_pricing_guard(context, log=None):
    """Prevent ad clicks from navigating video automation to the pricing page."""
    if getattr(context, "_higgsfield_pricing_guard_installed", False):
        return
    context.route(HIGGSFIELD_PRICING_URL, lambda route: _handle_pricing_route(route, log))
    context.add_init_script(PRICING_NAVIGATION_GUARD)
    context._higgsfield_pricing_guard_installed = True
    for page in list(context.pages):
        try:
            if not page.is_closed():
                page.evaluate(PRICING_NAVIGATION_GUARD)
        except Exception:
            pass


def _handle_pricing_route(route, log):
    if route.request.is_navigation_request():
        if log:
            log(f"Chặn điều hướng quảng cáo đến pricing: {route.request.url}")
        route.abort()
    else:
        route.continue_()


def is_vpn_welcome_url(url):
    parsed = urlsplit(url)
    if parsed.scheme not in ("http", "https"):
        return False
    
    # Không chặn các trang web chính của tool
    hostname = parsed.hostname or ""
    if any(domain in hostname for domain in ["higgsfield.ai", "microsoft.com", "live.com", "google.com"]):
        return False
    if not any(domain in hostname for domain in (
        "hola.org", "holavpn", "hola-vpn", "1clickvpn", "urban-vpn", "freevpn", "touchvpn"
    )):
        return False
        
    path = parsed.path.lower().rstrip("/")
    return (
        "thank" in path
        or "welcome" in path
        or "installed" in path
        or "success" in path
        or "install" in path
    )
def install_vpn_welcome_guard(context, log=None):
    """Block VPN welcome pages without closing tabs or the profile browser."""
    if getattr(context, "_vpn_welcome_guard_installed", False):
        return
    context._vpn_welcome_guard_installed = True

    def block_welcome(route):
        route.fulfill(status=200, content_type="text/html", body="<!doctype html><title></title>")

    context.route(VPN_WELCOME_URL, block_welcome)

    def dismiss(page):
        if page.is_closed() or not is_vpn_welcome_url(page.url):
            return
        try:
            # Extension welcome tabs can navigate simultaneously. Closing each
            # one based on a shared page count can race and close the whole browser.
            page.goto("about:blank", wait_until="commit")
            if log:
                log("Blocked VPN welcome page")
        except Exception:
            # The owning task may already have closed this page.
            pass

    def watch(page):
        def navigated(frame):
            if frame == page.main_frame:
                dismiss(page)

        page.on("framenavigated", navigated)
        dismiss(page)

    context.on("page", watch)
    for page in list(context.pages):
        watch(page)
