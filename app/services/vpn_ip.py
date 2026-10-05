"""Automate 1ClickVPN and prevent duplicate exit IPs across working profiles."""

from __future__ import annotations

import json
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
        if not ip:
            raise RuntimeError("Khong doc duoc IP sau khi ket noi VPN")
        return ip
    finally:
        try:
            page.close()
        except Exception:
            pass


def _wait_for_popup_ready(page) -> None:
    page.goto(POPUP_URL, wait_until="domcontentloaded", timeout=20000)
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
        _wait_for_popup_ready(popup)
        for _ in range(max_attempts):
            try:
                country = _choose_random_country(popup, attempted_countries)
                attempted_countries.add(country)
                _wait_connected(popup)
                ip = _public_ip(context)

                with _reservation_lock:
                    # Drop stale reservations left by browsers that have exited.
                    try:
                        from app.browser import is_running
                        stale = [owner_id for owner_id in _reserved_ips if not is_running(owner_id)]
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
                        _save_reservations()
                        return {"ip": ip, "country": country}
                last_error = RuntimeError(f"IP {ip} dang duoc profile {owner} su dung")
            except Exception as exc:
                last_error = exc

            try:
                popup.reload(wait_until="domcontentloaded", timeout=15000)
                _wait_for_popup_ready(popup)
            except Exception:
                pass

        raise RuntimeError(f"Khong sinh duoc IP VPN rieng sau {max_attempts} lan: {last_error}")
    finally:
        try:
            popup.close()
        except Exception:
            pass


_load_reservations()
