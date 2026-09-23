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
