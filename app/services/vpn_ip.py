"""Automate 1ClickVPN and prevent duplicate exit IPs across working profiles."""

from __future__ import annotations

import json
import ipaddress
import random
import re
import threading
import time
from pathlib import Path

from app.core.config import DATA_DIR


ONECLICK_EXTENSION_ID = "pphgdbgldlmicfdkhondlafkiomnelnk"
ONECLICK_POPUP_URL = f"chrome-extension://{ONECLICK_EXTENSION_ID}/popup/index.html"

URBAN_EXTENSION_ID = "eppiocemhmnlbhjplcgkofciiegomcon"
URBAN_POPUP_URL = f"chrome-extension://{URBAN_EXTENSION_ID}/popup/index.html"
URBAN_EXTENSION_NAME = "urbanvpn"

# Backward compatibility
EXTENSION_ID = ONECLICK_EXTENSION_ID
POPUP_URL = ONECLICK_POPUP_URL

RESERVATIONS_FILE = Path(DATA_DIR) / "vpn_ip_reservations.json"
ACTIVE_VPN_FILE = Path(DATA_DIR) / "active_vpn.txt"

_reservation_lock = threading.RLock()
_reserved_ips: dict[str, str] = {}
_live_vpn_profiles: set[str] = set()


def get_active_vpn() -> str:
    """Return the selected VPN provider: 1clickvpn or urbanvpn."""
    try:
        if ACTIVE_VPN_FILE.exists():
            val = ACTIVE_VPN_FILE.read_text(encoding="utf-8").strip().lower()
            if val in ("1clickvpn", "urbanvpn"):
                return val
    except Exception:
        pass
    return "1clickvpn"


def set_active_vpn(name: str) -> None:
    """Persist the selected VPN provider."""
    value = name.strip().lower()
    if value not in ("1clickvpn", "urbanvpn"):
        raise ValueError(f"Unsupported VPN provider: {name}")
    ACTIVE_VPN_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_VPN_FILE.write_text(value, encoding="utf-8")


def _load_reservations() -> None:
    try:
        raw = json.loads(RESERVATIONS_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            _reserved_ips.update({str(k): str(v) for k, v in raw.items() if v})
    except Exception:
        pass


def _save_reservations() -> None:
    RESERVATIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp_file = RESERVATIONS_FILE.with_suffix(".tmp")
    temp_file.write_text(json.dumps(_reserved_ips, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_file.replace(RESERVATIONS_FILE)


def release_vpn_ip(profile_id: str) -> None:
    """Release the reserved IP when a profile is closed by this app."""
    with _reservation_lock:
        _live_vpn_profiles.discard(str(profile_id))
        if _reserved_ips.pop(str(profile_id), None) is not None:
            _save_reservations()


def _public_ip(context) -> str:
    """Read the exit IP inside Chrome so the request goes through the VPN."""
    page = context.new_page()
    try:
        for url in [
            "https://api.ipify.org?format=json",
            "https://api64.ipify.org?format=json",
            "https://icanhazip.com",
            "https://ifconfig.me/ip",
        ]:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=12000)
                body = page.locator("body").inner_text(timeout=5000).strip()
                try:
                    ip = str(json.loads(body).get("ip", "")).strip()
                except Exception:
                    match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", body)
                    ip = match.group(0) if match else ""
                if ip:
                    return str(ipaddress.ip_address(ip))
            except Exception:
                continue
        raise RuntimeError("Khong doc duoc IP sau khi ket noi VPN")
    finally:
        try:
            page.close()
        except Exception:
            pass


def _wait_for_popup_ready(page) -> None:
    for attempt in range(15):
        try:
            page.goto(ONECLICK_POPUP_URL, wait_until="domcontentloaded", timeout=10000)
            break
        except Exception:
            if attempt == 14:
                raise
            page.wait_for_timeout(1000)
    page.bring_to_front()
    reset_attempted = False

    deadline = time.time() + 60
    registration_retries = 0
    max_registration_retries = 4
    while time.time() < deadline:
        body = page.locator("body").inner_text(timeout=3000)
        body_lower = body.casefold()

        # This is an extension-reported initialization failure, not a normal
        # loading state. Surface it immediately instead of waiting for timeout.
        if "initialization takes longer than expected" in body_lower:
            reset = page.get_by_text("Reset", exact=True)
            if reset.count() and reset.first.is_visible() and not reset_attempted:
                reset_attempted = True
                print("  [VPN] 1ClickVPN stuck initializing; clicking Reset once...", flush=True)
                reset.first.click(timeout=2000)
                page.wait_for_timeout(2500)
                deadline = time.time() + 60
                continue
            raise RuntimeError(
                "1ClickVPN remains stuck initializing after Reset; restart the Chrome profile "
                "before trying the VPN again."
            )

        if "connection is unstable" in body_lower or "you might have trouble connecting" in body_lower:
            raise RuntimeError("1ClickVPN reports an unstable connection")

        if "Registration error" in body:
            retry = page.get_by_text("Retry", exact=True)
            if registration_retries < max_registration_retries and retry.count() and retry.first.is_visible():
                registration_retries += 1
                print(f"  [VPN] 1ClickVPN báo 'Registration error', thử bấm Retry ({registration_retries}/{max_registration_retries})...", flush=True)
                retry.first.click()
                page.wait_for_timeout(4000)
                deadline = max(deadline, time.time() + 30)
                continue
            raise RuntimeError(f"1ClickVPN bị lỗi HTTP 429: Too many requests sau {max_registration_retries} lần thử! (Registration error)")

        decline = page.get_by_text("Decline", exact=True)
        if decline.count() and decline.first.is_visible():
            decline.first.click()
            page.wait_for_timeout(1200)
            continue

        if "Disable other extension" in body:
            disable_btn = page.get_by_text("Disable other extension", exact=False)
            if disable_btn.count() and disable_btn.first.is_visible():
                disable_btn.first.click()
                page.wait_for_timeout(2000)
                continue

        if page.locator(".home-page__box--type-location").count():
            return
            
        # Try to click common popup/overlay buttons
        for btn_text in ["Agree", "Accept", "Continue", "Next", "Got it", "Skip", "No thanks", "Close", "Got It"]:
            try:
                btn = page.locator(f'text="{btn_text}"').last
                if btn.is_visible(timeout=500):
                    btn.click(timeout=1000)
                    page.wait_for_timeout(1000)
            except:
                pass
                
        page.wait_for_timeout(700)
        
    raise RuntimeError("1ClickVPN khoi tao qua lau")


ONECLICK_PREFERRED_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "Canada",
    "Netherlands",
    "Japan",
    "Singapore",
    "Australia",
    "Brazil",
    "Italy",
    "Spain",
    "Sweden",
    "Switzerland",
    "Austria",
    "Belgium",
    "Norway",
    "Denmark",
    "Finland",
    "Ireland",
    "New Zealand",
]


def _choose_random_country(page, excluded: set[str]) -> str:
    # 1. Bấm vào box Location ở trang chủ nếu đang ở trang chủ để mở danh sách
    location = page.locator(".home-page__box--type-location")
    if location.count() and location.first.is_visible():
        try:
            location.first.click(timeout=3000)
        except Exception:
            page.evaluate("() => { const el = document.querySelector('.home-page__box--type-location'); if (el) el.click(); }")
        page.wait_for_timeout(800)

    # 2. Đợi danh sách quốc gia xuất hiện
    page.wait_for_selector("li.country-list__item", state="visible", timeout=10000)

    # 3. Lọc TUYỆT ĐỐI chỉ lấy các quốc gia khả dụng (loại trừ --disabled và --active)
    available_names = page.evaluate("""() => {
        const items = document.querySelectorAll('li.country-list__item:not(.country-list__item--disabled):not(.country-list__item--active)');
        const names = [];
        for (const item of items) {
            const nameEl = item.querySelector('.country-list__name');
            const txt = (nameEl ? nameEl.innerText : item.innerText || '').trim();
            if (txt && !names.includes(txt)) {
                names.push(txt);
            }
        }
        return names;
    }""")

    if not available_names:
        available_names = page.evaluate("""() => {
            const items = document.querySelectorAll('li.country-list__item:not(.country-list__item--disabled)');
            return Array.from(items).map(item => {
                const nameEl = item.querySelector('.country-list__name');
                return (nameEl ? nameEl.innerText : item.innerText || '').trim();
            }).filter(Boolean);
        }""")

    candidates = [name for name in available_names if name not in excluded]
    if not candidates:
        candidates = available_names
    if not candidates:
        raise RuntimeError("1ClickVPN khong co quoc gia kha dung nao")

    # Ưu tiên các quốc gia server lớn, ổn định cao
    preferred = [c for c in ONECLICK_PREFERRED_COUNTRIES if c in candidates]
    chosen = random.choice(preferred) if preferred else random.choice(candidates)
    print(f"  [VPN] 1ClickVPN: Chon quoc gia '{chosen}' (trong {len(candidates)} quoc gia kha dung)...", flush=True)

    # 4. Dùng ô Search để lọc ngay quốc gia đó lên đầu danh sách (tránh vuốt cuộn bị ul chặn pointer events)
    search_input = page.locator(".base-search__input, input[placeholder*='Search'], input[type='text']").first
    if search_input.count() and search_input.is_visible():
        try:
            search_input.fill("")
            search_input.fill(chosen)
            page.wait_for_timeout(500)
        except Exception:
            pass

    # 5. Click dứt khoát vào item đã chọn
    clicked = False
    target = page.locator("li.country-list__item:not(.country-list__item--disabled)").filter(has_text=chosen).first
    if not target.count() or not target.is_visible():
        target = page.locator("li.country-list__item:not(.country-list__item--disabled)").first

    if target.count() and target.is_visible():
        try:
            target.scroll_into_view_if_needed(timeout=1000)
            target.click(force=True, timeout=2000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        # Fallback bằng evaluate dispatch click trực tiếp
        page.evaluate("""(countryName) => {
            const items = Array.from(document.querySelectorAll('li.country-list__item:not(.country-list__item--disabled)'));
            const target = items.find(el => (el.innerText || '').toLowerCase().includes(countryName.toLowerCase())) || items[0];
            if (target) {
                target.scrollIntoView({ block: 'center' });
                target.click();
                target.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
            }
        }""", chosen)

    page.wait_for_timeout(1500)
    return chosen


def _wait_connected(page) -> None:
    # 1ClickVPN tự động chuyển về trang chủ và kết nối sau khi chọn quốc gia.
    page.wait_for_timeout(2500)
    deadline = time.time() + 35
    clicked_power = False
    start_time = time.time()
    while time.time() < deadline:
        try:
            body = page.locator("body").inner_text(timeout=2000)
        except Exception:
            page.wait_for_timeout(500)
            continue

        body_lower = body.casefold()
        if "connected" in body_lower and ("surfing from" in body_lower or "disconnect" in body_lower):
            return
        if (
            "connection is unstable" in body_lower
            or "you might have trouble connecting" in body_lower
        ):
            raise RuntimeError("1ClickVPN bao Connection is unstable")
        if "connection was dropped" in body_lower or "could not connect" in body_lower:
            raise RuntimeError("May chu VPN vua chon khong ket noi duoc")

        # Chỉ bấm toggle nếu đã qua ít nhất 8s mà vẫn Disconnected hoàn toàn
        if not clicked_power and "disconnected" in body_lower and (time.time() - start_time) >= 8:
            button = page.locator(".toggle-button__wrapper")
            if button.count() and button.first.is_visible():
                print("  [VPN] 1ClickVPN chua ket noi, bam nut Power...", flush=True)
                button.first.click(force=True)
                clicked_power = True
        page.wait_for_timeout(900)
    raise RuntimeError("1ClickVPN ket noi qua lau")


URBAN_CANDIDATE_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "Canada",
    "Netherlands",
    "Japan",
    "Singapore",
    "Australia",
    "Austria",
    "Belgium",
    "Denmark",
    "Spain",
    "Sweden",
    "Switzerland",
    "Italy",
    "Norway",
    "Poland",
    "Portugal",
    "New Zealand",
    "Ireland",
    "Czechia",
    "Finland",
    "Romania",
]


def _wait_for_urban_ready(page) -> None:
    for attempt in range(15):
        try:
            page.goto(URBAN_POPUP_URL, wait_until="domcontentloaded", timeout=10000)
            break
        except Exception:
            if attempt == 14:
                raise
            page.wait_for_timeout(1000)
    page.bring_to_front()

    deadline = time.time() + 30
    while time.time() < deadline:
        if page.is_closed():
            raise RuntimeError("Trang Urban VPN bi dong")

        # 1. Kiểm tra màn hình 'Service interruption' (xung đột proxy extension khác)
        try:
            interruption_btn = page.locator(".interruption-page__action, button:has-text('Disable other extension')")
            if interruption_btn.count() and interruption_btn.first.is_visible():
                print("  [VPN] Urban VPN bao 'Service interruption', bam Disable other extension...", flush=True)
                interruption_btn.first.click(force=True)
                page.wait_for_timeout(2000)
                continue
        except Exception:
            pass

        # 2. Xử lý các popup consent / agree / accept nếu có
        for btn_text in ["Agree", "Accept", "Continue", "Next", "Got it", "Skip", "No thanks"]:
            try:
                btn = page.locator(f'button:has-text("{btn_text}"), text="{btn_text}"').last
                if btn.count() and btn.is_visible():
                    btn.click(force=True, timeout=1000)
                    page.wait_for_timeout(1000)
            except Exception:
                pass

        # 3. Kiểm tra xem đã hiển thị giao diện chính (có nút play hoặc chọn location)
        try:
            has_main = page.evaluate("""() => {
                const play = document.querySelector('.play-button');
                const loc = document.querySelector('.location-view');
                return !!(play || loc);
            }""")
            if has_main:
                return
        except Exception:
            pass

        page.wait_for_timeout(700)

    raise RuntimeError("Urban VPN khoi tao qua lau")


def _choose_urban_country(page, excluded: set[str]) -> str:
    # 1. Mở dropdown chọn quốc gia nếu chưa mở
    is_open = page.locator(".location-selector, .location-selector-input__native")
    if not (is_open.count() and is_open.first.is_visible()):
        loc_dropdown = page.locator(".location-view__content-dropdown, .location-view__content, .location-view")
        if loc_dropdown.count() and loc_dropdown.first.is_visible():
            try:
                loc_dropdown.first.click(timeout=3000)
            except Exception:
                page.evaluate("() => { const el = document.querySelector('.location-view__content-dropdown, .location-view'); if (el) el.click(); }")
            page.wait_for_timeout(1000)

    page.wait_for_selector(".location-selector, .location-selector-input__native, .selector-option", timeout=10000)

    candidates = [c for c in URBAN_CANDIDATE_COUNTRIES if c not in excluded] or URBAN_CANDIDATE_COUNTRIES
    chosen = random.choice(candidates)
    print(f"  [VPN] Urban VPN: Chon quoc gia '{chosen}'...", flush=True)

    # 2. Dùng ô Search để tìm chính xác quốc gia
    search_input = page.locator(".location-selector-input__native, input[placeholder*='Search']").first
    if search_input.count() and search_input.is_visible():
        try:
            search_input.fill("")
            search_input.fill(chosen)
            page.wait_for_timeout(600)
        except Exception:
            pass

    # 3. Click vào quốc gia không bị disabled
    # Loại trừ .selector-option__non-accessible-location và .selector-option--not-available
    clicked = False
    valid_option_sel = ".selector-option:not(.selector-option__non-accessible-location):not(.selector-option--not-available)"
    target = page.locator(valid_option_sel).filter(has_text=chosen).first
    if not target.count() or not target.is_visible():
        target = page.locator(valid_option_sel).first

    if target.count() and target.is_visible():
        try:
            target.scroll_into_view_if_needed(timeout=1000)
            target.click(force=True, timeout=2000)
            clicked = True
        except Exception:
            pass

    if not clicked:
        clicked = page.evaluate("""(name) => {
            const items = Array.from(document.querySelectorAll('.selector-option:not(.selector-option__non-accessible-location):not(.selector-option--not-available)'));
            const found = items.find(el => (el.innerText || '').toLowerCase().includes(name.toLowerCase())) || items[0];
            if (found) {
                found.scrollIntoView({ block: 'center' });
                found.click();
                found.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true }));
                return true;
            }
            return false;
        }""", chosen)

    page.wait_for_timeout(1500)
    return chosen


def _wait_urban_connected(page) -> None:
    # 1. Sau khi chọn quốc gia, kiểm tra xem đã kết nối chưa. Nếu Not connected thì bấm nút play
    page.wait_for_timeout(1200)
    try:
        body = page.locator("body").inner_text(timeout=2000)
    except Exception:
        body = ""

    body_lower = body.casefold()
    if "not connected" in body_lower or "play" in body_lower:
        play_btn = page.locator(".play-button").first
        if play_btn.count() and play_btn.is_visible():
            print("  [VPN] Urban VPN: Bam nut Play de ket noi...", flush=True)
            play_btn.click(force=True)

    deadline = time.time() + 35
    while time.time() < deadline:
        if page.is_closed():
            raise RuntimeError("Trang Urban VPN bi dong")

        try:
            body = page.locator("body").inner_text(timeout=2000)
        except Exception:
            page.wait_for_timeout(500)
            continue

        body_lower = body.casefold()
        if "connected" in body_lower and "not connected" not in body_lower and "connecting" not in body_lower:
            return
        if "could not connect" in body_lower or "no connection" in body_lower or "connection failed" in body_lower:
            raise RuntimeError("Urban VPN bao khong ket noi duoc")

        page.wait_for_timeout(900)

    raise RuntimeError("Urban VPN ket noi qua lau")


def _connect_urban_vpn(context, profile_id: str, max_attempts: int = 4) -> dict[str, str]:
    """Kết nối Urban VPN và trả về IP mới độc nhất."""
    popup = context.new_page()
    attempted: set[str] = set()
    try:
        _wait_for_urban_ready(popup)
        try:
            previous = _public_ip(context)
        except Exception:
            previous = ""
        print(f"  [VPN] Urban VPN: IP goc = {previous or '(khong doc duoc)'}", flush=True)

        for attempt in range(max_attempts):
            country = ""
            try:
                country = _choose_urban_country(popup, attempted)
                attempted.add(country)
                _wait_urban_connected(popup)
                popup.wait_for_timeout(3000)
            except Exception as e:
                err_msg = str(e)
                print(f"  [VPN] Urban VPN: Quoc gia '{country or 'da chon'}' loi ({err_msg}), thu quoc gia khac ({attempt+1}/{max_attempts})...", flush=True)
                try:
                    popup.reload(wait_until="domcontentloaded", timeout=15000)
                    _wait_for_urban_ready(popup)
                except Exception:
                    pass
                continue

            try:
                ip = _public_ip(context)
            except Exception:
                ip = ""

            if not ip:
                print(f"  [VPN] Urban VPN: chua doc duoc IP ({attempt+1}/{max_attempts}), thu lai...", flush=True)
                popup.reload(wait_until="domcontentloaded", timeout=15000)
                _wait_for_urban_ready(popup)
                continue

            if ip != previous:
                with _reservation_lock:
                    try:
                        from app.browser import is_running
                        stale = [owner_id for owner_id in _reserved_ips
                                 if owner_id not in _live_vpn_profiles and not is_running(owner_id)]
                        for owner_id in stale:
                            _reserved_ips.pop(owner_id, None)
                    except Exception:
                        pass
                    owner = next(
                        (owner_id for owner_id, owner_ip in _reserved_ips.items()
                         if owner_ip == ip and owner_id != str(profile_id)),
                        None,
                    )
                    if owner is None:
                        _reserved_ips[str(profile_id)] = ip
                        _live_vpn_profiles.add(str(profile_id))
                        _save_reservations()
                        context.once("close", lambda *_: release_vpn_ip(profile_id))
                        print(f"  [VPN] Urban VPN da ket noi thanh cong: IP {ip} ({country})", flush=True)
                        return {"ip": ip, "country": country}
                    print(f"  [VPN] Urban VPN: IP {ip} ({country}) bi profile khac dung, thu quoc gia khac ({attempt+1}/{max_attempts})...", flush=True)
            else:
                print(f"  [VPN] Urban VPN: IP chua doi ({attempt+1}/{max_attempts}), thu quoc gia khac...", flush=True)

            popup.reload(wait_until="domcontentloaded", timeout=15000)
            _wait_for_urban_ready(popup)

        raise RuntimeError(f"Urban VPN khong sinh duoc IP moi sau {max_attempts} lan thu")
    finally:
        try:
            popup.close()
        except Exception:
            pass


def _disable_extension(context, ext_id: str) -> None:
    """Tắt extension qua chrome://extensions để nhường quyền proxy."""
    page = context.new_page()
    try:
        page.goto("chrome://extensions/", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(1500)
        disabled = page.evaluate("""(extId) => {
            function shadowQuery(root, selector) {
                const el = root.querySelector(selector);
                if (el) return el;
                for (const child of root.querySelectorAll('*')) {
                    if (child.shadowRoot) {
                        const found = shadowQuery(child.shadowRoot, selector);
                        if (found) return found;
                    }
                }
                return null;
            }
            function shadowQueryAll(root, selector) {
                let results = Array.from(root.querySelectorAll(selector));
                for (const child of root.querySelectorAll('*')) {
                    if (child.shadowRoot) {
                        results = results.concat(shadowQueryAll(child.shadowRoot, selector));
                    }
                }
                return results;
            }

            const items = shadowQueryAll(document, 'extensions-item');
            for (const item of items) {
                const itemId = item.getAttribute('id') || item.id || '';
                if (itemId.toLowerCase() === (extId || '').toLowerCase()) {
                    const toggle = shadowQuery(item.shadowRoot || item, 'cr-toggle');
                    if (toggle && toggle.checked) {
                        toggle.click();
                        return true;
                    }
                    return false;
                }
            }
            return false;
        }""", ext_id)
        if disabled:
            print(f"  [VPN] Da tat extension ({ext_id})", flush=True)
        else:
            print(f"  [VPN] Extension ({ext_id}) da tat hoac khong the toggle", flush=True)
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"  [VPN] Khong tat duoc extension: {e}", flush=True)
    finally:
        try:
            page.close()
        except Exception:
            pass


def _connect_1clickvpn(context, profile_id: str, max_attempts: int = 8) -> dict[str, str]:
    """Kết nối 1ClickVPN và trả về IP mới độc nhất."""
    popup = context.new_page()
    attempted: set[str] = set()
    try:
        _wait_for_popup_ready(popup)
        try:
            previous = _public_ip(context)
        except Exception:
            previous = ""
        print(f"  [VPN] 1ClickVPN: IP goc = {previous or '(khong doc duoc)'}", flush=True)

        for attempt in range(max_attempts):
            country = ""
            try:
                country = _choose_random_country(popup, attempted)
                attempted.add(country)
                _wait_connected(popup)
                popup.wait_for_timeout(3000)
            except Exception as e:
                err_msg = str(e)
                print(f"  [VPN] 1ClickVPN: Quoc gia '{country or 'da chon'}' loi ({err_msg}), tu dong doi sang quoc gia khac ({attempt+1}/{max_attempts})...", flush=True)
                try:
                    popup.reload(wait_until="domcontentloaded", timeout=15000)
                    _wait_for_popup_ready(popup)
                except Exception:
                    pass
                continue

            try:
                ip = _public_ip(context)
            except Exception:
                ip = ""

            if not ip:
                print(f"  [VPN] 1ClickVPN: chua doc duoc IP ({attempt+1}/{max_attempts}), thu lai...", flush=True)
                popup.reload(wait_until="domcontentloaded", timeout=15000)
                _wait_for_popup_ready(popup)
                continue

            if ip != previous:
                with _reservation_lock:
                    try:
                        from app.browser import is_running
                        stale = [owner_id for owner_id in _reserved_ips
                                 if owner_id not in _live_vpn_profiles and not is_running(owner_id)]
                        for owner_id in stale:
                            _reserved_ips.pop(owner_id, None)
                    except Exception:
                        pass
                    owner = next(
                        (owner_id for owner_id, owner_ip in _reserved_ips.items()
                         if owner_ip == ip and owner_id != str(profile_id)),
                        None,
                    )
                    if owner is None:
                        _reserved_ips[str(profile_id)] = ip
                        _live_vpn_profiles.add(str(profile_id))
                        _save_reservations()
                        context.once("close", lambda *_: release_vpn_ip(profile_id))
                        print(f"  [VPN] 1ClickVPN da ket noi thanh cong: IP {ip} ({country})", flush=True)
                        return {"ip": ip, "country": country}
                    print(f"  [VPN] 1ClickVPN: IP {ip} ({country}) bi profile khac dung, thu quoc gia khac ({attempt+1}/{max_attempts})...", flush=True)
            else:
                print(f"  [VPN] 1ClickVPN: IP chua doi ({attempt+1}/{max_attempts}), thu quoc gia khac...", flush=True)

            popup.reload(wait_until="domcontentloaded", timeout=15000)
            _wait_for_popup_ready(popup)

        raise RuntimeError(f"1ClickVPN khong sinh duoc IP moi sau {max_attempts} lan thu")
    finally:
        try:
            popup.close()
        except Exception:
            pass


def connect_unique_vpn_ip(context, profile_id: str, max_attempts: int = 4) -> dict[str, str]:
    """Kết nối VPN với IP độc nhất.

    Logic mới:
    1. Thử 1ClickVPN trước 4 lần.
    2. Nếu 1ClickVPN không được sau 4 lần:
       -> Tắt 1ClickVPN đi.
       -> Mở Urban VPN lên thử 4 lần.
    3. Hoàn toàn loại bỏ Hola VPN.
    """
    print("  [VPN] Bat dau thu 1ClickVPN truoc (toi da 4 lan)...", flush=True)
    oneclick_error: Exception | None = None
    try:
        result = _connect_1clickvpn(context, profile_id, max_attempts=4)
        try:
            set_active_vpn("1clickvpn")
        except Exception:
            pass
        return result
    except Exception as e:
        oneclick_error = e
        print(f"  [VPN] 1ClickVPN that bai sau 4 lan: {e}", flush=True)

    # 1ClickVPN không được -> Tắt 1ClickVPN và chuyển sang Urban VPN
    print("  [VPN] 1ClickVPN khong ket noi duoc -> Tat 1ClickVPN va chuyen sang Urban VPN (thu 4 lan)...", flush=True)
    try:
        _disable_extension(context, ONECLICK_EXTENSION_ID)
    except Exception as e:
        print(f"  [VPN] Bo qua buoc tat 1ClickVPN: {e}", flush=True)

    import time as _time
    _time.sleep(2)

    urban_error: Exception | None = None
    try:
        result = _connect_urban_vpn(context, profile_id, max_attempts=4)
        try:
            set_active_vpn("urbanvpn")
        except Exception:
            pass
        return result
    except Exception as e:
        urban_error = e
        print(f"  [VPN] Urban VPN that bai sau 4 lan: {e}", flush=True)

    raise RuntimeError(
        f"Ca 1ClickVPN (sau 4 lan: {oneclick_error}) lan Urban VPN (sau 4 lan: {urban_error}) deu that bai"
    ) from urban_error


_load_reservations()
