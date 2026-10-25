"""Tự cài tiện ích Chrome (extension .crx / thư mục đã giải nén).

- Nhận đường dẫn file `.crx`/`.zip` hoặc thư mục chứa `manifest.json`.
- Mỗi profile có thư mục extensions riêng (không lẫn giữa các profile).
- Có thể cài cho MỘT profile hoặc ÁP CHO TOÀN BỘ profile.
"""
from __future__ import annotations

import os
import json
import shutil
import tempfile
import zipfile
from pathlib import Path

ONECLICK_EXTENSION_ID = "pphgdbgldlmicfdkhondlafkiomnelnk"
ONECLICK_PUBLIC_KEY = "MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAqoJDyiKQ+SGDdD/sVqXBprZzGRPorww6T07qUwv0wbpH47Xiqz6pyD78qzPE2wkkYPH16fVLhSz5QK4MwoKVaF1k0r7omxlYXbkPDBu1cuRkQzKzfcmSjkl7RpZseRuX8pTyJIFaaYLVBlyzloLVpUhF1ShCntOd5p0/A+4gWwn3lVN5x8Ew/i/BW6WdTpvz/Y7jYuWUnCic3Zwxr71Yvf/N9HaXXalfLY4PN+POB7DFkfNVZsj3+oNAJpsPw8z8+r3hlaLkyXiKkJNI/dsgjAg7WvR43wo+J+qVe6o/xmdJyejlXfubEbaoKneVLkjZ0OnDo+9uHk480A1FFff+WwIDAQAB"
URBAN_EXTENSION_ID = "eppiocemhmnlbhjplcgkofciiegomcon"
URBAN_EXTENSION_NAME = "urbanvpn"


def pin_oneclick_extension(user_data_dir: str | Path) -> None:
    """Chrome's toolbar preference stores extension IDs, not folder names."""
    preference = Path(user_data_dir) / "Default" / "Preferences"
    prefs = json.loads(preference.read_text(encoding="utf-8")) if preference.is_file() else {}
    pinned = prefs.setdefault("extensions", {}).setdefault("pinned_extensions", [])
    pinned[:] = [item for item in pinned if item != "1clickvpn"]
    if ONECLICK_EXTENSION_ID not in pinned:
        pinned.append(ONECLICK_EXTENSION_ID)
    preference.parent.mkdir(parents=True, exist_ok=True)
    preference.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def pin_urban_extension(user_data_dir: str | Path) -> None:
    preference = Path(user_data_dir) / "Default" / "Preferences"
    prefs = json.loads(preference.read_text(encoding="utf-8")) if preference.is_file() else {}
    pinned = prefs.setdefault("extensions", {}).setdefault("pinned_extensions", [])
    if URBAN_EXTENSION_ID not in pinned:
        pinned.append(URBAN_EXTENSION_ID)
    preference.parent.mkdir(parents=True, exist_ok=True)
    preference.write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")


def ensure_vpn_extensions_enabled(user_data_dir: str | Path) -> None:
    """Đảm bảo 1ClickVPN và Urban VPN không bị Chrome vô hiệu hóa trong Preferences."""
    canonical_dir = Path(__file__).parent.parent / "data" / "extensions"
    for pref_name in ("Preferences", "Secure Preferences"):
        pref_file = Path(user_data_dir) / "Default" / pref_name
        if not pref_file.is_file():
            continue
        try:
            data = json.loads(pref_file.read_text(encoding="utf-8", errors="ignore"))
            settings = data.get("extensions", {}).get("settings", {})
            modified = False
            for ext_id in (ONECLICK_EXTENSION_ID, URBAN_EXTENSION_ID):
                if ext_id in settings:
                    entry = settings[ext_id]
                    # Xoa entry neu tro vao thu muc profile hoac bi disable_reasons
                    ext_path = str(entry.get("path", "")).replace("\\", "/")
                    if "data/browsers" in ext_path or entry.get("disable_reasons") or entry.get("state") == 0:
                        del settings[ext_id]
                        modified = True
            if modified:
                pref_file.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass


def pin_active_vpn_extension(user_data_dir: str | Path) -> None:
    """Pin cả 1ClickVPN và Urban VPN lên toolbar Chrome và đảm bảo chúng luôn được bật."""
    ensure_vpn_extensions_enabled(user_data_dir)
    pin_oneclick_extension(user_data_dir)
    pin_urban_extension(user_data_dir)


def direct_connection_extension(user_data_dir: str | Path) -> str:
    """Keep VPN extensions visible while enforcing the requested direct mode.

    chrome.proxy can override --no-proxy-server, so direct mode needs its own
    setting. Load this last, and omit it entirely when Sinh IP is enabled.
    """
    folder = Path(user_data_dir) / "automation_extensions" / "direct_connection"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "manifest.json").write_text(json.dumps({
        "manifest_version": 3, "name": "Direct connection", "version": "1.0",
        "permissions": ["proxy"], "background": {"service_worker": "background.js"},
    }), encoding="utf-8")
    (folder / "background.js").write_text("""const useDirect = () => {
    chrome.proxy.settings.set({value: {mode: 'direct'}, scope: 'regular'});
};
chrome.runtime.onInstalled.addListener(useDirect);
chrome.runtime.onStartup.addListener(useDirect);
chrome.proxy.settings.onChange.addListener(details => {
    if (details.value.mode !== 'direct') useDirect();
});
useDirect();
""", encoding="utf-8")
    return str(folder.resolve())


def _extract(path: Path, dest_dir: Path, folder_name: str | None = None) -> Path:
    """Giải nén file .crx/.zip vào một thư mục con trong dest_dir."""
    dest_dir = dest_dir / (folder_name or path.stem)
    if dest_dir.exists():
        shutil.rmtree(dest_dir, ignore_errors=True)
    dest_dir.parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="cloakext_"))
    try:
        with zipfile.ZipFile(path) as z:
            z.extractall(tmp)
        # Tìm thư mục chứa manifest.json (crx đôi khi bọc một thư mục con).
        src = _find_manifest_root(tmp)
        shutil.move(str(src), str(dest_dir))
        return dest_dir
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _find_manifest_root(base: Path) -> Path:
    if (base / "manifest.json").exists():
        return base
    for child in base.iterdir():
        if child.is_dir() and (child / "manifest.json").exists():
            return child
    raise ValueError(f"Không tìm thấy manifest.json trong {base.name}")


def resolve_extension_paths(raw: str, profile_dir: Path, install: bool = True) -> list[str]:
    """Trả về danh sách đường dẫn thư mục extension hợp lệ cho một profile.

    Nếu một mục là file .crx/.zip thì tự giải nén vào profile_dir/extensions.
    Nếu là thư mục hợp lệ (có manifest.json) thì dùng trực tiếp.
    """
    out: list[str] = []
    ext_dir = profile_dir / "extensions"
    for item in (raw or "").split(";"):
        item = item.strip()
        if not item:
            continue
            
        low = item.lower()
        ext_id = None
        if "chromewebstore.google.com" in low or "/webstore/" in low:
            import re
            m = re.search(r"/detail/(?:[a-z0-9_-]+/)?([a-z0-9]{32})", low)
            if m:
                ext_id = m.group(1)
        elif len(item) == 32 and item.isalnum():
            ext_id = item

        if ext_id in (ONECLICK_EXTENSION_ID, URBAN_EXTENSION_ID) or "1clickvpn" in low or "urbanvpn" in low:
            global_dir = Path(__file__).parent.parent / "data" / "extensions"
            canonical_path = global_dir / ("1clickvpn" if (ext_id == ONECLICK_EXTENSION_ID or "1clickvpn" in low) else "urbanvpn")
            if canonical_path.is_dir():
                out.append(str(canonical_path.resolve()))
                continue

        if ext_id and ("http" in low or "chromewebstore" in low or len(item) == 32):
            if install:
                try:
                    installed_dir = ext_dir / ext_id
                    installed_manifest = installed_dir / "manifest.json"
                    if installed_manifest.is_file():
                        out.append(str(installed_dir))
                        continue
                    crx_url = f"https://clients2.google.com/service/update2/crx?response=redirect&prodversion=125.0.0.0&acceptformat=crx2,crx3&x=id%3D{ext_id}%26installsource%3Dondemand%26uc"
                    import tempfile
                    from urllib.request import urlopen, Request
                    req = Request(crx_url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urlopen(req, timeout=15) as resp:
                        body = resp.read()
                    if len(body) > 50:
                        tmp_crx = Path(tempfile.mktemp(suffix=".crx"))
                        tmp_crx.write_bytes(body)
                        installed_dir = _extract(tmp_crx, ext_dir, ext_id)
                        if ext_id == ONECLICK_EXTENSION_ID:
                            manifest_path = installed_dir / "manifest.json"
                            manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
                            manifest["key"] = ONECLICK_PUBLIC_KEY
                            manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
                        out.append(str(installed_dir))
                        try:
                            tmp_crx.unlink()
                        except Exception:
                            pass
                except Exception:
                    pass
            else:
                out.append(item)
            continue

        try:
            p = Path(item)
            if p.is_file() and p.suffix.lower() in (".crx", ".zip"):
                if install:
                    try:
                        out.append(str(_extract(p, ext_dir)))
                    except Exception:
                        continue
                else:
                    out.append(item)
            elif p.is_dir():
                if (p / "manifest.json").exists():
                    out.append(str(p))
            elif Path(item + ".crx").is_file():
                if install:
                    try:
                        out.append(str(_extract(Path(item + ".crx"), ext_dir)))
                    except Exception:
                        continue
        except Exception:
            pass
    return out
