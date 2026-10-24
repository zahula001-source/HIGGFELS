"""Refresh generation history without reloading the upload form."""

STATUS_SELECTOR = ':is(span, div):visible:text-matches("^(Processing|Generating)$", "i")'


def wait_for_generation(page, timeout=15000):
    page.locator(STATUS_SELECTOR).first.wait_for(state="visible", timeout=timeout)


def refresh_video_history(page):
    for label in ("Motion Library", "History"):
        # Covers both button tabs and the site's q-tabs-tab-label spans.
        tab = page.get_by_text(label, exact=True).filter(visible=True).first
        tab.click(timeout=10000)
        page.wait_for_timeout(800)


def confirm_generation(page):
    try:
        wait_for_generation(page)
    except Exception:
        refresh_video_history(page)
        wait_for_generation(page)
