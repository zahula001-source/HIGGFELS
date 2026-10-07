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


EXTENSION_ID = "pphgdbgldlmicfdkhondlafkiomnelnk"
POPUP_URL = f"chrome-extension://{EXTENSION_ID}/popup/index.html"
RESERVATIONS_FILE = Path(DATA_DIR) / "vpn_ip_reservations.json"

_reservation_lock = threading.RLock()
_reserved_ips: dict[str, str] = {}
_live_vpn_profiles: set[str] = set()


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
        page.goto("https://api.ipify.org?format=json", wait_until="domcontentloaded", timeout=20000)
        body = page.locator("body").inner_text(timeout=5000).strip()
        try:
            ip = str(json.loads(body).get("ip", "")).strip()
        except Exception:
            match = re.search(r"\b(?:\d{1,3}\.){3}\d{1,3}\b", body)
            ip = match.group(0) if match else ""
        try:
            ip = str(ipaddress.ip_address(ip))
        except ValueError:
            raise RuntimeError("Khong doc duoc IP sau khi ket noi VPN")
        return ip
    finally:
        try:
            page.close()
        except Exception:
            pass


def _wait_for_popup_ready(page) -> None:
    for attempt in range(15):
        try:
            page.goto(POPUP_URL, wait_until="domcontentloaded", timeout=10000)
            break
        except Exception:
            if attempt == 14:
                raise
            page.wait_for_timeout(1000)
    page.bring_to_front()
    deadline = time.time() + 35
    while time.time() < deadline:
        body = page.locator("body").inner_text(timeout=3000)
        if "Registration error" in body:
            retry = page.get_by_text("Retry", exact=True)
            if retry.count() and retry.first.is_visible():
                retry.first.click()
                page.wait_for_timeout(2500)
                continue
            raise RuntimeError("1ClickVPN bao Registration error")

        decline = page.get_by_text("Decline", exact=True)
        if decline.count() and decline.first.is_visible():
            decline.first.click()
            page.wait_for_timeout(1200)
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
        
    # Dump HTML for debugging
    try:
        html = page.content()
        (Path(DATA_DIR) / "vpn_error.html").write_text(html, encoding="utf-8")
        print(f"  [VPN] Đã lưu HTML màn hình lỗi vào data/vpn_error.html", flush=True)
    except:
        pass
        
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
        if "Connected" in body and "Surfing from:" in body:
            return
        if "Connection was dropped" in body or "Could not connect" in body:
            raise RuntimeError("May chu VPN vua chon khong ket noi duoc")
        if not clicked_power and "Disconnected" in body:
            button = page.locator(".toggle-button__wrapper")
            if button.count() and button.first.is_visible():
                button.first.click()
                clicked_power = True
        page.wait_for_timeout(900)
    raise RuntimeError("1ClickVPN ket noi qua lau")


def connect_unique_vpn_ip(context, profile_id: str, max_attempts: int = 8) -> dict[str, str]:
    """Choose a random location and accept only an unreserved exit IP."""
    popup = context.new_page()
    attempted_countries: set[str] = set()
    last_error: Exception | None = None
    try:
        print(f"  [VPN] Mở trang popup của 1ClickVPN...", flush=True)
        _wait_for_popup_ready(popup)
        print(f"  [VPN] Popup đã sẵn sàng, lấy IP hiện tại...", flush=True)
        previous_ip = _public_ip(context)
        print(f"  [VPN] IP hiện tại: {previous_ip}", flush=True)
        # Make the automatic VPN operation visible instead of flashing in the background.
        popup.bring_to_front()
        popup.wait_for_timeout(1200)
        for attempt in range(max_attempts):
            try:
                print(f"  [VPN] Đang chọn quốc gia ngẫu nhiên (Lần thử {attempt+1}/{max_attempts})...", flush=True)
                country = _choose_random_country(popup, attempted_countries)
                attempted_countries.add(country)
                print(f"  [VPN] Đã chọn {country}, đang đợi kết nối...", flush=True)
                _wait_connected(popup)
                ip = _public_ip(context)
                print(f"  [VPN] Đã kết nối, IP mới: {ip}", flush=True)
                if ip == previous_ip:
                    raise RuntimeError("VPN chưa đổi IP; không tiếp tục bằng IP cũ")


                with _reservation_lock:
                    # Drop stale reservations left by browsers that have exited.
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
                        popup.bring_to_front()
                        popup.wait_for_timeout(3000)
                        return {"ip": ip, "country": country}
                last_error = RuntimeError(f"IP {ip} dang duoc profile {owner} su dung")
            except Exception as exc:
                last_error = exc
                print(f"  [VPN] Lỗi ở lần thử {attempt+1}: {exc}", flush=True)

            try:
                print(f"  [VPN] Tải lại popup để thử lại...", flush=True)
                popup.reload(wait_until="domcontentloaded", timeout=15000)
                _wait_for_popup_ready(popup)
            except Exception as reload_err:
                print(f"  [VPN] Lỗi khi tải lại popup: {reload_err}", flush=True)

        raise RuntimeError(f"Khong sinh duoc IP VPN rieng sau {max_attempts} lan: {last_error}")
    finally:
        try:
            popup.close()
        except Exception:
            pass


_load_reservations()
