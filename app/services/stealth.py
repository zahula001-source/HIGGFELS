"""Stealth & Cloudflare Turnstile human-like handling.

Provides:
- get_real_chrome_binary(): Detects official Google Chrome on Windows.
- install_stealth_guard(): Injects anti-detect scripts removing automation flags.
- solve_cloudflare_turnstile(): Clicks Cloudflare Turnstile with human mouse dynamics.
"""
from __future__ import annotations

import math
import os
import random
import time
from pathlib import Path
from typing import Any, Optional


def get_real_chrome_binary() -> Optional[Path]:
    """Find installed official Google Chrome on Windows to ensure 100% genuine signatures."""
    candidates = [
        Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
        Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    ]
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "Google" / "Chrome" / "Application" / "chrome.exe")

    for p in candidates:
        try:
            if p.is_file():
                return p
        except Exception:
            pass
    return None


STEALTH_JS = """
(() => {
    // 1. Hide navigator.webdriver completely
    try {
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
            configurable: true
        });
        delete Object.getPrototypeOf(navigator).webdriver;
    } catch (e) {}

    // 2. Polyfill window.chrome with genuine structure
    try {
        if (!window.chrome) {
            window.chrome = {};
        }
        if (!window.chrome.runtime) {
            window.chrome.runtime = {
                OnInstalledReason: { CHROME_UPDATE: 'chrome_update', INSTALL: 'install', SHARED_MODULE_UPDATE: 'shared_module_update', UPDATE: 'update' },
                OnRestartRequiredReason: { APP_UPDATE: 'app_update', OS_UPDATE: 'os_update', PERIODIC: 'periodic' },
                PlatformArch: { ARM: 'arm', ARM64: 'arm64', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformNaclArch: { ARM: 'arm', MIPS: 'mips', MIPS64: 'mips64', X86_32: 'x86-32', X86_64: 'x86-64' },
                PlatformOs: { ANDROID: 'android', CROS: 'cros', LINUX: 'linux', MAC: 'mac', OPENBSD: 'openbsd', WIN: 'win' },
                RequestUpdateCheckStatus: { NO_UPDATE: 'no_update', THROTTLED: 'throttled', UPDATE_AVAILABLE: 'update_available' }
            };
        }
        if (!window.chrome.app) {
            window.chrome.app = {
                isInstalled: false,
                InstallState: { DISABLED: 'disabled', INSTALLED: 'installed', NOT_INSTALLED: 'not_installed' },
                RunningState: { CANNOT_RUN: 'cannot_run', READY_TO_RUN: 'ready_to_run', RUNNING: 'running' }
            };
        }
        if (!window.chrome.csi) window.chrome.csi = function() {};
        if (!window.chrome.loadTimes) window.chrome.loadTimes = function() {};
    } catch (e) {}

    // 3. Ensure navigator.plugins has realistic length
    try {
        if (!navigator.plugins || navigator.plugins.length === 0) {
            const fakePlugins = [
                { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
                { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: 'Portable Document Format' }
            ];
            Object.defineProperty(navigator, 'plugins', {
                get: () => fakePlugins,
                configurable: true
            });
        }
    } catch (e) {}

    // 4. Permissions query fix
    try {
        if (window.navigator && window.navigator.permissions) {
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters && parameters.name === 'notifications' ?
                    Promise.resolve({ state: typeof Notification !== 'undefined' ? Notification.permission : 'default' }) :
                    originalQuery(parameters)
            );
        }
    } catch (e) {}
})();
"""


def install_stealth_guard(target: Any) -> None:
    """Inject anti-detect evasions into context or page so every page load stays authentic."""
    try:
        if hasattr(target, "add_init_script"):
            target.add_init_script(STEALTH_JS)
    except Exception as e:
        print(f"[Stealth] Failed to attach init script: {e}")


def human_mouse_move(page: Any, start_x: float, start_y: float, end_x: float, end_y: float, steps: int = 25) -> None:
    """Move the mouse using a smooth ease-in-out curve with realistic human jitter."""
    dist = math.hypot(end_x - start_x, end_y - start_y)
    if dist < 1:
        return

    steps = max(15, min(steps, round(dist / 10)))
    for i in range(steps + 1):
        progress = i / steps
        # Smooth ease-in-out polynomial
        eased = progress * progress * (3.0 - 2.0 * progress)
        cx = start_x + (end_x - start_x) * eased
        cy = start_y + (end_y - start_y) * eased

        # Subtle sub-pixel jitter
        if 0 < i < steps:
            wobble = math.sin(math.pi * progress) * 2.0
            cx += (random.random() - 0.5) * wobble
            cy += (random.random() - 0.5) * wobble

        try:
            page.mouse.move(round(cx, 1), round(cy, 1))
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(random.randint(6, 16))
            else:
                time.sleep(random.uniform(0.006, 0.016))
        except Exception:
            pass


def solve_cloudflare_turnstile(page: Any, timeout_sec: int = 15) -> bool:
    """Detect and complete Cloudflare Turnstile verification using natural human cursor trajectory.

    Prevents bot detection (red error banner / failure icon) by:
    1. Finding the exact bounding box of the Turnstile iframe.
    2. Targeting the checkbox (left-aligned inside the widget).
    3. Moving the mouse along a bezier curve with micro-jitter.
    4. Hovering before click, realistic mousedown duration, then mouseup.
    5. Waiting for the token to be set or the challenge to clear.
    """
    if page is None or getattr(page, "is_closed", lambda: False)():
        return False

    deadline = time.monotonic() + timeout_sec
    last_click_time = 0.0

    for attempt in range(3):
        if time.monotonic() >= deadline:
            break

        # 1. Kiem tra xem Turnstile da hoan thanh chua
        try:
            token = page.evaluate("""() => {
                const el = document.querySelector('input[name="cf-turnstile-response"]');
                return el ? el.value : '';
            }""")
            if token and len(token) > 10:
                print(f"[Turnstile] Da co token xac minh ({token[:20]}...), hoan thanh!")
                return True
        except Exception:
            pass

        # 2. Tim frame hoac element chua Turnstile
        target_frame = None
        turnstile_iframe = None
        try:
            for f in page.frames:
                url_lower = (getattr(f, "url", "") or "").lower()
                if "challenges.cloudflare.com" in url_lower or "turnstile" in url_lower:
                    target_frame = f
                    try:
                        el = f.frame_element()
                        if el and getattr(el, "is_visible", lambda timeout=0: True)():
                            turnstile_iframe = el
                            break
                    except Exception:
                        pass
        except Exception:
            pass

        if not turnstile_iframe:
            for sel in [
                'iframe[src*="challenges.cloudflare.com"]',
                'iframe[src*="turnstile"]',
                'iframe[title*="Cloudflare"]',
                'div[ref="turnstileContainer"] iframe',
                '.cf-turnstile iframe',
            ]:
                try:
                    loc = page.locator(sel)
                    if loc.count() > 0 and loc.first.is_visible(timeout=300):
                        turnstile_iframe = loc.first
                        break
                except Exception:
                    pass

        # Khong thay iframe Turnstile tren trang -> kiem tra xem co van ban bat xac minh khong
        if not turnstile_iframe:
            try:
                body_text = page.locator("body").inner_text(timeout=500)
                is_cf_present = (
                    "Verify you are human" in body_text
                    or "Xác minh bạn là con người" in body_text
                    or "Turnstile" in body_text
                )
            except Exception:
                is_cf_present = False

            if not is_cf_present:
                # Khong co Turnstile tren trang nay
                return False

            # Dang tai hoac chua render xong iframe -> cho nhe
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(500)
            else:
                time.sleep(0.5)
            continue

        # 3. Lay toa do bounding box tren trang
        try:
            turnstile_iframe.scroll_into_view_if_needed(timeout=1500)
        except Exception:
            pass

        box = None
        try:
            box = turnstile_iframe.bounding_box()
        except Exception:
            box = None

        if not box or box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(500)
            continue

        # Checkbox chuan cua Turnstile nam o goc trai widget (x + 28..36px, y + height / 2)
        target_x = box["x"] + random.uniform(28, 36)
        target_y = box["y"] + (box["height"] / 2.0) + random.uniform(-3, 3)

        # Tranh click lai qua nhanh neu vua bam
        if time.monotonic() - last_click_time < 3.0:
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(500)
            continue

        print(f"[Turnstile] Phat hien hop kiem (Lan {attempt + 1}/3) tai ({round(target_x)}, {round(target_y)}), dang di chuyen chuot nguoi that...")

        # Di chuyen chuot muot ma tu vi tri xuat phat tu nhien
        start_x = max(20.0, box["x"] - random.uniform(80, 180))
        start_y = max(20.0, box["y"] - random.uniform(50, 120))
        try:
            page.mouse.move(start_x, start_y)
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(random.randint(80, 180))
            human_mouse_move(page, start_x, start_y, target_x, target_y, steps=random.randint(22, 32))
            # Hover quan sat
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(random.randint(220, 380))
            # Click vat ly giu phim
            page.mouse.down()
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(random.randint(85, 145))
            page.mouse.up()
            last_click_time = time.monotonic()
            print("[Turnstile] Da nhan hop kiem, dang cho ket qua xac thuc...")
        except Exception as e:
            print(f"[Turnstile] Loi thao tac chuot: {e}")
            try:
                turnstile_iframe.click(position={"x": 32, "y": box["height"] / 2.0}, timeout=2000)
                last_click_time = time.monotonic()
            except Exception:
                pass

        # 4. Cho ket qua xac thuc sau khi click
        verify_wait_end = min(deadline, time.monotonic() + 6.0)
        while time.monotonic() < verify_wait_end:
            if hasattr(page, "wait_for_timeout"):
                page.wait_for_timeout(400)
            else:
                time.sleep(0.4)

            # Kiem tra xem da co token chua
            try:
                token = page.evaluate("""() => {
                    const el = document.querySelector('input[name="cf-turnstile-response"]');
                    return el ? el.value : '';
                }""")
                if token and len(token) > 10:
                    print(f"[Turnstile] Xac minh thanh cong (Token: {token[:20]}...)!")
                    return True
            except Exception:
                pass

            # Kiem tra xem iframe co bien mat khong (tren fviainboxes widget se unmount khi thanh cong)
            try:
                if not turnstile_iframe.is_visible(timeout=200):
                    print("[Turnstile] Hop kiem da an, hoan tat xac minh!")
                    return True
            except Exception:
                return True

            # Kiem tra loi do "Verification failed" hoac "Turnstile error"
            try:
                body_now = page.locator("body").inner_text(timeout=300)
                if "Verification failed" in body_now or "Turnstile error" in body_now:
                    print("[Turnstile] Phat hien trang thai loi do, cho Turnstile tu reset de thu lai...")
                    if hasattr(page, "wait_for_timeout"):
                        page.wait_for_timeout(2500)
                    break
            except Exception:
                pass

    return False

