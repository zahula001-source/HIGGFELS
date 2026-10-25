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

# Hola is loaded unpacked, so Chrome assigns its runtime extension ID. The
# popup URL is discovered from the active profile rather than hard-coded.
HOLA_EXTENSION_NAME = "hola-vpn"

# Backward compatibility
EXTENSION_ID = ONECLICK_EXTENSION_ID
POPUP_URL = ONECLICK_POPUP_URL

RESERVATIONS_FILE = Path(DATA_DIR) / "vpn_ip_reservations.json"
ACTIVE_VPN_FILE = Path(DATA_DIR) / "active_vpn.txt"

_reservation_lock = threading.RLock()
_reserved_ips: dict[str, str] = {}
_live_vpn_profiles: set[str] = set()


def get_active_vpn() -> str:
    """Return the selected VPN provider: Hola VPN or 1ClickVPN."""
    try:
        if ACTIVE_VPN_FILE.exists():
            val = ACTIVE_VPN_FILE.read_text(encoding="utf-8").strip().lower()
            if val in ("hola-vpn", "1clickvpn"):
                return val
    except Exception:
        pass
    return "hola-vpn"


def set_active_vpn(name: str) -> None:
    """Persist the selected VPN provider."""
    value = name.strip().lower()
    if value not in ("hola-vpn", "1clickvpn"):
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


HOLA_CANDIDATE_COUNTRIES = [
    "United States",
    "United Kingdom",
    "Germany",
    "France",
    "Canada",
    "Netherlands",
    "Japan",
    "Italy",
    "Brazil",
    "Argentina",
    "Singapore",
    "Australia",
]


def _get_hola_extension_id(context) -> str:
    """Detect dynamic or store extension ID for Hola VPN."""
    sw_list = getattr(context, "service_workers", None)
    if isinstance(sw_list, (list, tuple)):
        for sw in sw_list:
            url = getattr(sw, "url", "")
            if isinstance(url, str) and ("bg.bg.bundle.js" in url or "hola" in url.lower()):
                parts = url.split("/")
                if len(parts) >= 3 and parts[2]:
                    return parts[2]
    pages_list = getattr(context, "pages", None)
    if isinstance(pages_list, (list, tuple)):
        for pg in pages_list:
            url = getattr(pg, "url", "")
            if isinstance(url, str) and "chrome-extension://" in url and ("/js/popup.html" in url or "hola" in url.lower()):
                parts = url.split("/")
                if len(parts) >= 3 and parts[2]:
                    return parts[2]
    return "eppiocemhmnlbhjplcgkofciiegomcon"


def _wait_for_hola_ready(popup, hola_id: str) -> None:
    if popup.is_closed():
        raise RuntimeError("Hola popup bi dong")
    popup_url = f"chrome-extension://{hola_id}/js/popup.html"
    for attempt in range(5):
        if popup.is_closed():
            raise RuntimeError("Hola popup bi dong")
        try:
            popup.goto(popup_url, wait_until="domcontentloaded", timeout=10000)
            break
        except Exception:
            if popup.is_closed():
                raise RuntimeError("Hola popup bi dong")
            if attempt == 4:
                # If Web Store ID failed, try finding another ID from context service workers
                ctx = popup.context
                for sw in getattr(ctx, "service_workers", []):
                    if "bg.bg.bundle.js" in getattr(sw, "url", ""):
                        alt_id = sw.url.split("/")[2]
                        if alt_id != hola_id:
                            popup_url = f"chrome-extension://{alt_id}/js/popup.html"
                            try:
                                popup.goto(popup_url, wait_until="domcontentloaded", timeout=10000)
                                break
                            except Exception:
                                pass
            if not popup.is_closed():
                popup.wait_for_timeout(1000)

    if popup.is_closed():
        raise RuntimeError("Hola popup bi dong")
    popup.bring_to_front()
    deadline = time.time() + 25
    while time.time() < deadline:
        if popup.is_closed():
            raise RuntimeError("Hola popup bi dong")
        try:
            has_ui = popup.evaluate("""() => {
                const closeBtn = document.querySelector('.close_btn___bottom_sheet-module, [class*="close_btn"]');
                if (closeBtn) closeBtn.click();
                document.querySelectorAll('[class*="dialog___dialog"], [class*="fade___bottom_sheet"]').forEach(el => el.remove());
                const btn = document.querySelector('div[class*="connect_button___"]');
                const countryBtn = document.querySelector('div[class*="country_button___"], [class*="country_btn"]');
                return !!(btn || countryBtn);
            }""")
            if has_ui:
                return
        except Exception:
            pass
        if not popup.is_closed():
            popup.wait_for_timeout(600)
        else:
            raise RuntimeError("Hola popup bi dong")


def _choose_hola_country(popup, excluded: set[str]) -> str:
    try:
        popup.evaluate("""() => {
            const closeBtn = document.querySelector('.close_btn___bottom_sheet-module, [class*="close_btn"]');
            if (closeBtn) closeBtn.click();
            document.querySelectorAll('[class*="dialog___dialog"], [class*="fade___bottom_sheet"]').forEach(el => el.remove());
        }""")
    except Exception:
        pass

    dropdown = popup.locator("div[class*='country_button___'], div[class*='country_btn___']").first
    if not dropdown.count():
        dropdown = popup.get_by_text("United States", exact=False).first
    try:
        dropdown.click(force=True, timeout=5000)
    except Exception:
        popup.evaluate("""() => {
            const el = document.querySelector("div[class*='country_button___'], div[class*='country_btn___']");
            if (el) el.click();
        }""")
    popup.wait_for_timeout(1200)

    candidates = [c for c in HOLA_CANDIDATE_COUNTRIES if c not in excluded] or HOLA_CANDIDATE_COUNTRIES
    chosen = random.choice(candidates)

    target_item = popup.locator("li[class*='country_item___']").filter(has_text=chosen).first
    if target_item.count():
        try:
            target_item.click(force=True, timeout=3000)
        except Exception:
            popup.evaluate("""(country) => {
                const lis = Array.from(document.querySelectorAll("li"));
                const target = lis.find(li => li.innerText && li.innerText.includes(country));
                if (target) target.click();
            }""", chosen)
    else:
        search_input = popup.locator("input[placeholder*='Search']").first
        if search_input.count() and search_input.is_visible():
            search_input.fill(chosen)
            popup.wait_for_timeout(800)
            first_item = popup.locator("li[class*='country_item___']").first
            if first_item.count():
                first_item.click(force=True)
            else:
                popup.keyboard.press("Escape")

    popup.wait_for_timeout(1500)
    try:
        popup.evaluate("""() => {
            document.querySelectorAll('[class*="bottom_sheet"], [class*="fade"]').forEach(el => el.remove());
        }""")
    except Exception:
        pass
    return chosen


def _hola_is_connected(popup) -> bool:
    """Return True if Hola popup currently shows an active connection."""
    try:
        text = popup.locator("body").inner_text(timeout=3000)
        return "Disconnect" in text or "You are browsing through" in text
    except Exception:
        return False


def _hola_disconnect(popup) -> None:
    """Click Disconnect on Hola popup if currently connected."""
    try:
        btn = popup.locator("div[class*='connect_button___']").first
        if btn.count():
            btn_text = btn.inner_text(timeout=2000).strip()
            if "Disconnect" in btn_text:
                print("  [VPN] Hola đang kết nối — ngắt VPN cũ trước...", flush=True)
                popup.evaluate("""() => {
                    document.querySelectorAll('[class*="dialog"], [class*="fade"]').forEach(el => el.remove());
                }""")
                btn.click(force=True, timeout=3000)
                # Chờ VPN thực sự ngắt
                deadline2 = time.time() + 15
                while time.time() < deadline2:
                    try:
                        t = popup.locator("body").inner_text(timeout=2000)
                        if "Connect" in t and "Disconnect" not in t:
                            break
                    except Exception:
                        pass
                    popup.wait_for_timeout(700)
    except Exception:
        pass


def _wait_hola_connected(popup) -> None:
    btn = popup.locator("div[class*='connect_button___']").first
    if btn.count():
        try:
            btn_text = btn.inner_text().strip()
            if "Connect" in btn_text:
                print("  [VPN] Bấm nút Connect trên Hola VPN...", flush=True)
                popup.evaluate("""() => {
                    document.querySelectorAll('[class*="dialog"], [class*="fade"]').forEach(el => el.remove());
                }""")
                btn.click(force=True, timeout=3000)
        except Exception:
            pass

    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            text = popup.locator("body").inner_text()
            if "Disconnect" in text or "You are browsing through" in text:
                return
        except Exception:
            pass
        popup.wait_for_timeout(800)


def _connect_hola_vpn(context, profile_id: str, max_attempts: int = 8) -> dict[str, str]:
    """Automate Hola VPN to connect to a new unique IP."""
    hola_id = _get_hola_extension_id(context)
    popup = context.new_page()
    popup.add_init_script("window.close = function() {};")
    attempted: set[str] = set()
    try:
        _wait_for_hola_ready(popup, hola_id)

        # Nếu Hola đang kết nối sẵn → đọc IP thật trước khi ngắt
        # (IP thật máy khi không VPN làm baseline để phát hiện IP đổi)
        if _hola_is_connected(popup):
            _hola_disconnect(popup)
            popup.wait_for_timeout(2000)

        # Đọc IP gốc KHÔNG qua VPN làm baseline so sánh
        try:
            previous = _public_ip(context)
        except Exception:
            previous = ""
        print(f"  [VPN] Hola: IP gốc = {previous or '(không đọc được)'}", flush=True)

        for attempt in range(max_attempts):
            country = _choose_hola_country(popup, attempted)
            attempted.add(country)
            _wait_hola_connected(popup)
            # Chờ VPN ổn định trước khi kiểm tra IP
            popup.wait_for_timeout(4000)
            try:
                ip = _public_ip(context)
            except Exception:
                ip = ""

            if not ip:
                print(f"  [VPN] Hola VPN: chưa đọc được IP sau khi connect ({attempt+1}/{max_attempts}), thử lại...", flush=True)
                popup.reload(wait_until="domcontentloaded", timeout=15000)
                _wait_for_hola_ready(popup, hola_id)
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
                        print(f"  [VPN] Hola VPN đã kết nối thành công: IP {ip} ({country})", flush=True)
                        return {"ip": ip, "country": country}
                    print(f"  [VPN] Hola VPN: IP {ip} ({country}) đã bị profile khác dùng, thử quốc gia khác ({attempt+1}/{max_attempts})...", flush=True)
            else:
                print(f"  [VPN] Hola VPN: IP {ip} chưa thay đổi so với gốc, thử quốc gia khác ({attempt+1}/{max_attempts})...", flush=True)

            attempted.add(country)
            popup.reload(wait_until="domcontentloaded", timeout=15000)
            _wait_for_hola_ready(popup, hola_id)

        raise RuntimeError(f"Hola VPN không sinh được IP mới sau {max_attempts} lần thử")
    finally:
        try:
            popup.close()
        except Exception:
            pass



def _disable_hola_extension(context, hola_id: str) -> None:
    """Tắt Hola VPN extension qua chrome://extensions để tránh xung đột với 1ClickVPN."""
    page = context.new_page()
    try:
        page.goto("chrome://extensions/", wait_until="domcontentloaded", timeout=10000)
        page.wait_for_timeout(1500)
        # chrome://extensions dùng shadow DOM đa tầng — tìm và toggle qua JS
        disabled = page.evaluate("""(holaId) => {
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
                if (itemId.toLowerCase() === (holaId || '').toLowerCase()) {
                    const toggle = shadowQuery(item.shadowRoot || item, 'cr-toggle');
                    if (toggle && toggle.checked) {
                        toggle.click();
                        return true;
                    }
                    return false;
                }
            }
            return false;
        }""", hola_id)
        if disabled:
            print(f"  [VPN] Đã tắt Hola VPN extension ({hola_id})", flush=True)
        else:
            print(f"  [VPN] Hola extension không tắt được qua shadow DOM (id={hola_id}), tiếp tục dùng 1ClickVPN", flush=True)
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"  [VPN] Không tắt được Hola extension: {e}", flush=True)
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


def connect_unique_vpn_ip(context, profile_id: str, max_attempts: int = 8) -> dict[str, str]:
    """Kết nối VPN với IP độc nhất.

    Logic ưu tiên:
    1. Thử Hola VPN trước (tối đa 2 lần).
    2. Nếu Hola thất bại → tự động tắt Hola extension và chuyển sang 1ClickVPN.
    3. Nếu setting chọn sẵn 1ClickVPN → dùng 1ClickVPN luôn.
    """
    active = get_active_vpn()

    if active == "1clickvpn":
        # Người dùng đã chọn 1ClickVPN thủ công
        return _connect_1clickvpn(context, profile_id, max_attempts=max_attempts)

    # --- Thử Hola VPN trước (2 lần) ---
    hola_attempts = 2
    print(f"  [VPN] Thử Hola VPN trước ({hola_attempts} lần)...", flush=True)
    hola_error: Exception | None = None
    try:
        result = _connect_hola_vpn(context, profile_id, max_attempts=hola_attempts)
        return result
    except Exception as e:
        hola_error = e
        print(f"  [VPN] Hola VPN thất bại sau {hola_attempts} lần: {e}", flush=True)

    # --- Fallback sang 1ClickVPN (thử tối đa 4 lần) ---
    print("  [VPN] Chuyển sang 1ClickVPN (thử tối đa 4 lần)...", flush=True)

    # Tắt Hola extension để tránh xung đột
    try:
        hola_id = _get_hola_extension_id(context)
        _disable_hola_extension(context, hola_id)
    except Exception as e:
        print(f"  [VPN] Bỏ qua bước tắt Hola: {e}", flush=True)

    # Chờ extension bị tắt ổn định
    import time as _time
    _time.sleep(2)

    oneclick_attempts = 4
    oneclick_last_error = None
    for oc_try in range(1, oneclick_attempts + 1):
        try:
            result = _connect_1clickvpn(context, profile_id, max_attempts=max_attempts)
            try:
                set_active_vpn("1clickvpn")
            except Exception:
                pass
            return result
        except Exception as e2:
            oneclick_last_error = e2
            print(f"  [VPN] 1ClickVPN thất bại lần {oc_try}/{oneclick_attempts}: {e2}", flush=True)
            if oc_try < oneclick_attempts:
                _time.sleep(3)

    raise RuntimeError(
        f"Cả Hola VPN ({hola_error}) lẫn 1ClickVPN (sau {oneclick_attempts} lần: {oneclick_last_error}) đều thất bại"
    ) from oneclick_last_error


_load_reservations()
