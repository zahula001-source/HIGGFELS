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

    deadline = time.time() + 35
    registration_retries = 0
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
                deadline = time.time() + 35
                continue
            raise RuntimeError(
                "1ClickVPN remains stuck initializing after Reset; restart the Chrome profile "
                "before trying the VPN again."
            )

        if "connection is unstable" in body_lower or "you might have trouble connecting" in body_lower:
            raise RuntimeError("1ClickVPN reports an unstable connection")

        if "Registration error" in body:
            retry = page.get_by_text("Retry", exact=True)
            if registration_retries < 2 and retry.count() and retry.first.is_visible():
                registration_retries += 1
                print(f"  [VPN] 1ClickVPN báo 'Registration error', thử bấm Retry ({registration_retries}/2)...", flush=True)
                retry.first.click()
                page.wait_for_timeout(4000)
                continue
            raise RuntimeError("1ClickVPN bị lỗi HTTP 429: Too many requests! (Registration error)")

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


def _choose_random_country(page, excluded: set[str]) -> str:
    location = page.locator(".home-page__box--type-location")
    location.wait_for(state="visible", timeout=10000)
    location.click()

    countries = page.locator("li.country-list__item")
    countries.first.wait_for(state="visible", timeout=10000)
    names = [name.strip() for name in countries.all_inner_texts() if name.strip()]
    candidates = [name for name in names if name not in excluded] or names
    if not candidates:
        raise RuntimeError("1ClickVPN khong co danh sach quoc gia")

    country = random.choice(candidates)
    countries.filter(has_text=country).first.click()
    return country


def _wait_connected(page) -> None:
    # Selecting a country normally starts connecting. Click power once only if needed.
    deadline = time.time() + 35
    clicked_power = False
    while time.time() < deadline:
        body = page.locator("body").inner_text(timeout=3000)
        body_lower = body.casefold()
        if "Connected" in body and "Surfing from:" in body:
            return
        if (
            "connection is unstable" in body_lower
            or "you might have trouble connecting" in body_lower
        ):
            raise RuntimeError("1ClickVPN bao Connection is unstable")
        if "connection was dropped" in body_lower or "could not connect" in body_lower:
            raise RuntimeError("May chu VPN vua chon khong ket noi duoc")
        if not clicked_power and "Disconnected" in body:
            button = page.locator(".toggle-button__wrapper")
            if button.count() and button.first.is_visible():
                button.first.click()
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
    popup_url = f"chrome-extension://{hola_id}/js/popup.html"
    for attempt in range(5):
        try:
            popup.goto(popup_url, wait_until="domcontentloaded", timeout=10000)
            break
        except Exception:
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
            popup.wait_for_timeout(1000)

    popup.bring_to_front()
    deadline = time.time() + 25
    while time.time() < deadline:
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
        popup.wait_for_timeout(600)


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


def connect_unique_vpn_ip(context, profile_id: str, max_attempts: int = 8) -> dict[str, str]:
    """Connect to a unique VPN IP using the selected provider (Hola VPN or 1ClickVPN)."""
    if get_active_vpn() == "hola-vpn":
        return _connect_hola_vpn(context, profile_id, max_attempts=max_attempts)
    popup = context.new_page()
    attempted = set()
    try:
        _wait_for_popup_ready(popup)
        previous = _public_ip(context)
        for _ in range(max_attempts):
            country = _choose_random_country(popup, attempted)
            attempted.add(country)
            _wait_connected(popup)
            ip = _public_ip(context)
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
                        return {"ip": ip, "country": country}
            popup.reload(wait_until="domcontentloaded", timeout=15000)
            _wait_for_popup_ready(popup)
        raise RuntimeError("1ClickVPN did not provide a new IP")
    finally:
        try:
            popup.close()
        except Exception:
            pass


_load_reservations()
