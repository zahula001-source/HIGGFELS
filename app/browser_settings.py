"""Project-local CloakBrowser v146 selection; never modifies the user's license."""
import os
from pathlib import Path

VERSION = "146.0.7680.177.5"
BINARY = Path.home() / ".cloakbrowser" / ("chromium-" + VERSION) / "chrome.exe"
ENGINE = os.environ.setdefault("HIGGSFIELD_BROWSER_ENGINE", "cloakbrowser").lower()
if ENGINE == "cloakbrowser":
    if not BINARY.is_file():
        raise RuntimeError(f"CloakBrowser v146 binary not found: {BINARY}")
    os.environ["CLOAKBROWSER_BINARY_PATH"] = str(BINARY)
    os.environ["CLOAKBROWSER_VERSION"] = VERSION

def browser_launch_options():
    """Keep auxiliary workflows on the same engine as the profile runner."""
    if os.environ.get("HIGGSFIELD_BROWSER_ENGINE") == "cloakbrowser":
        return {"executable_path": str(BINARY)}
    return {"channel": "chrome"}

def get_global_args(proxy=None):
    import json
    try:
        config_path = Path(__file__).parent.parent / "data" / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            extra = []
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
    return ["--force-webrtc-ip-handling-policy=disable_non_proxied_udp", "--enforce-webrtc-ip-permission-check"]

def get_algo_proxy(profile_name: str) -> dict:
    import json
    from pathlib import Path
    try:
        config_path = Path(__file__).parent.parent / "data" / "config.json"
        if config_path.exists():
            cfg = json.loads(config_path.read_text(encoding="utf-8"))
            if cfg.get("disable_algodata"):
                return None
    except:
        pass

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
