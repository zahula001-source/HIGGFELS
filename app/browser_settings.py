"""Project-local CloakBrowser v146 selection; never modifies the user's license."""
import os
import json
import shutil
import tempfile
import urllib.request
import zipfile
from pathlib import Path

VERSION = "146.0.7680.177.5"
BINARY = Path.home() / ".cloakbrowser" / ("chromium-" + VERSION) / "chrome.exe"
CHROME_EXTENSION_BINARY = Path(__file__).resolve().parent.parent / "data" / "browser_bins" / "chrome-136" / "chrome-win64" / "chrome.exe"
CHROME_EXTENSION_URL = "https://storage.googleapis.com/chrome-for-testing-public/136.0.7103.113/win64/chrome-win64.zip"
ENGINE = os.environ.setdefault("HIGGSFIELD_BROWSER_ENGINE", "chrome").lower()
CONFIG_PATH = Path(__file__).resolve().parent.parent / "data" / "config.json"
if ENGINE == "cloakbrowser":
    if not BINARY.is_file():
        raise RuntimeError(f"CloakBrowser v146 binary not found: {BINARY}")
    os.environ["CLOAKBROWSER_BINARY_PATH"] = str(BINARY)
    os.environ["CLOAKBROWSER_VERSION"] = VERSION

def ensure_chrome_extension_binary() -> Path:
    """Tai Chrome 136 portable tu Google neu may chua co."""
    if CHROME_EXTENSION_BINARY.is_file():
        return CHROME_EXTENSION_BINARY

    install_root = CHROME_EXTENSION_BINARY.parent.parent
    install_root.mkdir(parents=True, exist_ok=True)
    temp_root = Path(tempfile.mkdtemp(prefix="higgsfield_chrome136_"))
    archive = temp_root / "chrome-136.zip"
    try:
        request = urllib.request.Request(CHROME_EXTENSION_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=120) as response, archive.open("wb") as output:
            shutil.copyfileobj(response, output)
        with zipfile.ZipFile(archive) as package:
            package.extractall(install_root)
    finally:
        shutil.rmtree(temp_root, ignore_errors=True)

    if not CHROME_EXTENSION_BINARY.is_file():
        raise RuntimeError("Tai Chrome 136 co extension that bai")
    return CHROME_EXTENSION_BINARY


def browser_launch_options():
    """Keep auxiliary workflows on the same engine as the profile runner."""
    if os.environ.get("HIGGSFIELD_BROWSER_ENGINE") == "cloakbrowser":
        return {"executable_path": str(BINARY)}
    return {"executable_path": str(ensure_chrome_extension_binary())}

def algodata_disabled():
    """Disable only the AlgoData proxy; 1ClickVPN remains independent."""
    try:
        return bool(json.loads(CONFIG_PATH.read_text(encoding="utf-8")).get("disable_algodata"))
    except (OSError, ValueError):
        return False


def network_mode(generate_ip=False):
    return ("vpn" if generate_ip else "direct") if algodata_disabled() else "algodata"


def filter_proxy_extensions(paths, generate_ip=False):
    """Giữ các extension VPN cần thiết: Khi sinh IP (generate_ip), nạp cả 1ClickVPN và UrbanVPN để có thể tự động fallback."""
    proxy_off = algodata_disabled()

    oneclick_manifest = CONFIG_PATH.parent / "extensions" / "1clickvpn" / "manifest.json"
    urban_manifest = CONFIG_PATH.parent / "extensions" / "urbanvpn" / "manifest.json"
    try:
        oneclick_key = json.loads(oneclick_manifest.read_text(encoding="utf-8-sig")).get("key")
    except (OSError, ValueError):
        oneclick_key = None
    try:
        urban_key = json.loads(urban_manifest.read_text(encoding="utf-8-sig")).get("key")
    except (OSError, ValueError):
        urban_key = None

    allowed = []
    seen = set()
    for path in dict.fromkeys(paths):
        try:
            manifest = json.loads((Path(path) / "manifest.json").read_text(encoding="utf-8-sig"))
        except (OSError, ValueError):
            continue
        permissions = manifest.get("permissions", []) + manifest.get("optional_permissions", [])
        m_key = manifest.get("key")
        resolved = Path(path).resolve()
        is_oneclick = (
            resolved == oneclick_manifest.parent.resolve()
            or bool(oneclick_key and m_key == oneclick_key)
            or "1clickvpn" in resolved.name.casefold()
            or "1clickvpn" in str(manifest.get("name", "")).casefold()
        )
        is_urban = (
            resolved == urban_manifest.parent.resolve()
            or bool(urban_key and m_key == urban_key)
            or "urbanvpn" in resolved.name.casefold()
            or "urban vpn" in str(manifest.get("name", "")).casefold()
            or "urban-vpn" in str(manifest.get("homepage_url", "")).casefold()
        )

        if is_oneclick or is_urban:
            vpn_name = "1clickvpn" if is_oneclick else "urbanvpn"
            if vpn_name in seen:
                continue
            seen.add(vpn_name)
            canonical = str(oneclick_manifest.parent.resolve()) if is_oneclick else str(urban_manifest.parent.resolve())
            allowed.append(canonical)
            continue
        elif proxy_off and "proxy" in permissions:
            continue
        allowed.append(str(resolved))

    # Đảm bảo khi generate_ip thì cả 2 extension 1ClickVPN và UrbanVPN đều có mặt để fallback
    if generate_ip:
        if "1clickvpn" not in seen and oneclick_manifest.parent.is_dir():
            allowed.append(str(oneclick_manifest.parent.resolve()))
            seen.add("1clickvpn")
        if "urbanvpn" not in seen and urban_manifest.parent.is_dir():
            allowed.append(str(urban_manifest.parent.resolve()))
            seen.add("urbanvpn")

    return allowed


def get_global_args(proxy=None, engine=None, generate_ip=False):
    import json
    selected_engine = (engine or os.environ.get("HIGGSFIELD_BROWSER_ENGINE", "chrome")).lower()
    try:
        config_path = CONFIG_PATH
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            extra = []
            if cfg.get("disable_algodata") and not generate_ip:
                extra.append("--no-proxy-server")
            if selected_engine != "cloakbrowser":
                extra.append("--disable-features=DisableLoadExtensionCommandLineSwitch")
            if cfg.get("lightweight_cache"):
                extra.extend(["--disk-cache-size=1", "--media-cache-size=1"])
            if cfg.get("block_media"):
                extra.append("--blink-settings=imagesEnabled=false")
                
            # WebRTC Protection
            extra.append("--force-webrtc-ip-handling-policy=disable_non_proxied_udp")
            extra.append("--enforce-webrtc-ip-permission-check")

            # Timezone mapping
            if proxy and "username" in proxy:
                tz = "Asia/Ho_Chi_Minh"
                if "__cr.de" in proxy["username"]:
                    tz = "Europe/Berlin"
                elif "__cr.us" in proxy["username"]:
                    tz = "America/New_York"
                elif "__cr.jp" in proxy["username"]:
                    tz = "Asia/Tokyo"
                elif "__cr.kr" in proxy["username"]:
                    tz = "Asia/Seoul"
                    
                extra.append(f"--lang=vi")
                extra.append(f"--accept-lang=en-US,en,vi")
                extra.append(f"--fingerprint-timezone={tz}")
                extra.append(f"--fingerprint-locale=en-US")
                
            return extra
    except:
        pass
    fallback = ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--enforce-webrtc-ip-permission-check"]
    if algodata_disabled() and not generate_ip:
        fallback.append("--no-proxy-server")
    if selected_engine != "cloakbrowser":
        fallback.insert(0, "--disable-features=DisableLoadExtensionCommandLineSwitch")
    return fallback

def get_algo_proxy(profile_name: str) -> dict:
    import json
    from pathlib import Path
    if algodata_disabled():
        return None

    import hashlib
    # 8-char session id from profile name for sticky session. Append _v2 for fresh IPs.
    sessid = hashlib.md5((profile_name or "default").encode('utf-8') + b"_v2").hexdigest()[:8]
    countries = ['us', 'jp', 'kr', 'de']
    idx = int(hashlib.md5((profile_name + "_country").encode('utf-8')).hexdigest(), 16) % len(countries)
    country = countries[idx]
    
    sub_key = "QCI7yt83XsaSqv"
    username = f"{sub_key}__cr.{country}__sessid.{sessid}"
    
    return {
        "server": "http://gw.algoinfra.network:23000",
        "username": username,
        "password": sub_key
    }
