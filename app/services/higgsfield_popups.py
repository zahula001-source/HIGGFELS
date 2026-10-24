"""Dismiss known Higgsfield upsell dialogs by their title and close button."""


UPGRADE_PLAN_GUARD = r"""(() => {
    if (location.hostname !== 'higgsfield.ai' || window.top !== window) return;
    if (window.__higgsfieldUpgradePlanGuard) return;
    window.__higgsfieldUpgradePlanGuard = true;

    const visible = el => el && el.isConnected && el.getClientRects().length > 0 &&
        getComputedStyle(el).display !== 'none' &&
        getComputedStyle(el).visibility !== 'hidden';
    const cross = 'M7.757.75L16.2516.25M16.257.75L7.7516.25';
    const lastClicks = new WeakMap();
    let queued = false;

    function dismiss() {
        queued = false;
        const headings = [...document.querySelectorAll('h1, h2')].filter(el => {
            if (!visible(el) || el.classList.contains('sr-only')) return false;
            const title = (el.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase();
            return title === 'upgrade plan to buy credits' ||
                title === 'enjoy 30% off special offer on ultimate & creator plans';
        });
        for (const heading of headings) {
            const isSpecialOffer = heading.tagName === 'H1';
            // Use the containing dialog where available. For the fullscreen
            // version, walk up to the nearest container with its fixed X button.
            const dialog = heading.closest('[role="dialog"], [aria-modal="true"]');
            let scope = dialog || heading.parentElement;
            while (scope && scope !== document.body && scope !== document.documentElement) {
                const button = [...scope.querySelectorAll('button[type="button"]')]
                    .find(btn => {
                        if (!visible(btn) || btn.disabled) return false;
                        if (isSpecialOffer) {
                            // The special offer uses a compact top-right X button
                            // with a filled close glyph rather than the credits
                            // modal's outlined cross path.
                            const rect = btn.getBoundingClientRect();
                            const topRight = rect.width <= 40 && rect.height <= 40 &&
                                rect.top < window.innerHeight * 0.4 &&
                                rect.right > window.innerWidth * 0.65;
                            const closeGlyph = [...btn.querySelectorAll('svg path')].some(path =>
                                (path.getAttribute('d') || '').includes('7.99857 8.93385')
                            );
                            return topRight && closeGlyph;
                        }
                        return btn.classList.contains('fixed') && btn.classList.contains('rounded-full') &&
                            [...btn.querySelectorAll('svg path')].some(path =>
                                (path.getAttribute('d') || '').replace(/\s+/g, '') === cross
                            );
                    });
                if (button) {
                    const now = performance.now();
                    if (now - (lastClicks.get(button) ?? -Infinity) >= 500) {
                        lastClicks.set(button, now);
                        button.click();
                    }
                    break;
                }
                if (dialog) break;
                scope = scope.parentElement;
            }
        }
    }

    function schedule() {
        if (!queued) {
            queued = true;
            queueMicrotask(dismiss);
        }
    }
    // Observe insertions, text changes, and visibility changes, including when
    // React mounts the X button after the title. The interval covers animations.
    const observer = new MutationObserver(schedule);
    observer.observe(document, {
        childList: true, subtree: true, characterData: true, attributes: true,
        attributeFilter: ['class', 'style', 'hidden', 'disabled', 'aria-hidden', 'd'],
    });
    setInterval(dismiss, 500);
    dismiss();
})();"""


def install_upgrade_plan_guard(context):
    """Install on future documents and immediately handle already-open tabs."""
    if getattr(context, "_upgrade_plan_guard_installed", False):
        return
    context.add_init_script(UPGRADE_PLAN_GUARD)
    context._upgrade_plan_guard_installed = True
    for page in list(context.pages):
        try:
            if not page.is_closed():
                page.evaluate(UPGRADE_PLAN_GUARD)
        except Exception:
            # Navigating documents receive the init script automatically.
            pass
