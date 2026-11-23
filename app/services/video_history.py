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


def set_status_zoom_80(page):
    page.keyboard.press("Control+0")
    page.keyboard.press("Control+-")
    page.keyboard.press("Control+-")


def confirm_generation(page):
    try:
        wait_for_generation(page)
    except Exception:
        refresh_video_history(page)
        try:
            wait_for_generation(page)
        except Exception:
            set_status_zoom_80(page)
            wait_for_generation(page)


def schedule_video_recheck(context, profile_id, task, minutes):
    from app.browser import close_profile

    task["recheck_after_minutes"] = minutes
    task["message"] = "Đang đóng Chrome để hẹn giờ kiểm tra video..."
    try:
        context.close()
    except Exception:
        pass
    close_profile(profile_id, stop_video_tasks=False)
    if task.get("force_stop"):
        task.update(status="cancelled", message="Đã dừng kiểm tra video.")
    else:
        task.update(
            status="awaiting_recheck",
            message=f"Đã đóng Chrome. Sẽ mở lại kiểm tra video sau {minutes} phút.",
        )


def get_recheck_video(page, recheck):
    return page.evaluate("""({ asset_id, previous_asset_ids }) => {
        const cards = Array.from(document.querySelectorAll('#assets-grid [data-asset-id]'));
        const card = asset_id
            ? cards.find(item => item.getAttribute('data-asset-id') === asset_id)
            : cards[0];
        if (!card || previous_asset_ids.includes(card.getAttribute('data-asset-id'))) return null;

        const status = card.getAttribute('data-job-status');
        if (status !== 'completed') return null;
        const video = card.querySelector('video');
        const url = [video?.currentSrc, video?.src, video?.querySelector('source')?.src]
            .find(src => src && /^(https?:|blob:)/.test(src));
        if (url) return url;

        card.scrollIntoView({ block: 'nearest' });
        card.dispatchEvent(new MouseEvent('mouseover', { bubbles: true }));
        const play = card.querySelector('.play-icon-gWzeeV, .xg-icon-play, [aria-label="play"]');
        if (play && !play.dataset.recheckClicked) {
            play.dataset.recheckClicked = 'true';
            play.click();
        }
        return null;
    }""", recheck)
