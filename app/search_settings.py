"""A profile-local extension using Chromium's supported search settings override."""
import json
from pathlib import Path

def google_search_extension(user_data_dir):
    folder = Path(user_data_dir) / "automation_extensions" / "google_search"
    folder.mkdir(parents=True, exist_ok=True)
    manifest = {
        "manifest_version": 3,
        "name": "Google Search for Higgsfield Profiles",
        "version": "1.0.0",
        "description": "Use Google when searching from the address bar.",
        "chrome_settings_overrides": {
            "search_provider": {
                "name": "Google", "keyword": "google.com",
                "search_url": "https://www.google.com/search?q={searchTerms}",
                "favicon_url": "https://www.google.com/favicon.ico",
                "encoding": "UTF-8", "is_default": True
            }
        }
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return str(folder)
