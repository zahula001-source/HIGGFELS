from __future__ import annotations

import json
import sys
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HTML_PATH = ROOT / (sys.argv[1] if len(sys.argv) > 1 else "popup.html")
CSS_PATH = ROOT / "popup.css"
DOCK_CSS_PATH = ROOT / "dock-polish.css"
SITE_POLISH_PATH = ROOT / "site-polish.js"
MANIFEST_PATH = ROOT / "manifest.json"

REQUIRED_IDS = {
    "view-license-lock", "main-unlocked-ui", "display-machine-id",
    "btn-copy-machine-id", "input-license-key", "btn-activate-license",
    "activation-error", "settings-license-info", "tab-generator",
    "tab-prompts", "tab-accounts", "tab-settings", "tab-logs",
    "view-generator", "view-prompts", "view-accounts", "view-settings",
    "view-logs", "badge-duration", "badge-ratio", "btn-open-studio",
    "btn-fetch", "btn-clear-session", "sel-duration", "prompts-container",
    "prompt-counter", "textarea-quick-prompts", "btn-add-bulk-prompts",
    "btn-clear-prompts", "file-upload-prompts", "btn-trigger-upload",
    "btn-reset-progress", "input-search-prompts", "count-all",
    "count-queued", "count-done", "profiles-container", "accounts-counter",
    "input-search-accounts", "file-upload-accounts",
    "btn-trigger-upload-accounts", "btn-capture-session",
    "btn-clear-all-accounts", "input-profile-name", "input-profile-cookies",
    "btn-import-profile", "header-active-account", "chk-autorotate",
    "chk-autonext", "chk-auto-dl", "chk-safety",
    "whatsapp-channel-link", "app-footer",
}

REQUIRED_DYNAMIC_CLASSES = {
    "nav-btn", "tab-content", "dur-pill", "ratio-pill", "filter-pill",
    "btn-toggle-done", "prompt-info-column", "prompt-num-badge",
    "btn-prompt-paste", "btn-prompt-del", "btn-mini-tab",
    "btn-mini-switch", "prompt-card", "prompt-title-text",
    "prompt-text-preview", "profile-card", "profile-num-badge",
    "profile-info-column", "profile-name-text", "profile-meta-text",
    "profile-actions-row", "prompt-done", "active-profile-card",
}


class ContractParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: Counter[str] = Counter()
        self.attrs_by_id: dict[str, dict[str, str | None]] = {}
        self.values: dict[str, list[str]] = {
            "data-dur": [],
            "data-ratio": [],
            "data-filter": [],
        }
        self.local_refs: list[str] = []
        self.in_fetch_button = 0
        self.fetch_has_span = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        element_id = attr_map.get("id")
        if element_id:
            self.ids[element_id] += 1
            self.attrs_by_id[element_id] = attr_map
        for name in self.values:
            if attr_map.get(name) is not None:
                self.values[name].append(str(attr_map[name]))
        if tag in {"script", "img"} and attr_map.get("src"):
            self.local_refs.append(str(attr_map["src"]))
        if tag == "link" and attr_map.get("href"):
            self.local_refs.append(str(attr_map["href"]))
        if element_id == "btn-fetch":
            self.in_fetch_button = 1
        elif self.in_fetch_button:
            self.in_fetch_button += 1
            if tag == "span":
                self.fetch_has_span = True

    def handle_endtag(self, tag: str) -> None:
        if self.in_fetch_button:
            self.in_fetch_button -= 1


def fail(message: str, failures: list[str]) -> None:
    failures.append(message)


def main() -> int:
    failures: list[str] = []
    html = HTML_PATH.read_text(encoding="utf-8")
    css = CSS_PATH.read_text(encoding="utf-8")
    dock_css = DOCK_CSS_PATH.read_text(encoding="utf-8")
    site_polish = SITE_POLISH_PATH.read_text(encoding="utf-8")
    parser = ContractParser()
    parser.feed(html)

    missing_ids = sorted(REQUIRED_IDS - set(parser.ids))
    if missing_ids:
        fail(f"Missing required IDs: {', '.join(missing_ids)}", failures)

    duplicate_ids = sorted(name for name, count in parser.ids.items() if count != 1)
    if duplicate_ids:
        fail(f"IDs must be unique: {', '.join(duplicate_ids)}", failures)

    expected_values = {
        "data-dur": {"10", "15", "20", "25", "30", "60"},
        "data-ratio": {"9:16", "16:9", "1:1", "3:4", "4:3", "21:9"},
        "data-filter": {"all", "queued", "done"},
    }
    for name, expected in expected_values.items():
        actual = set(parser.values[name])
        if actual != expected or len(parser.values[name]) != len(expected):
            fail(f"{name} mismatch: expected {sorted(expected)}, got {parser.values[name]}", failures)

    if not parser.fetch_has_span:
        fail("#btn-fetch must contain a descendant <span>", failures)

    whatsapp_attrs = parser.attrs_by_id.get("whatsapp-channel-link", {})
    expected_whatsapp_url = "https://whatsapp.com/channel/0029VbDkJSq1CYoXFhiE9g1Y"
    if whatsapp_attrs.get("href") != expected_whatsapp_url:
        fail("WhatsApp channel link does not match the requested URL", failures)
    if whatsapp_attrs.get("target") != "_blank":
        fail("WhatsApp channel link must open in a new tab", failures)
    link_rel = set((whatsapp_attrs.get("rel") or "").split())
    if not {"noopener", "noreferrer"}.issubset(link_rel):
        fail("WhatsApp channel link must use noopener and noreferrer", failures)

    if "Studio version 0.9.1" not in html or "AI workflow companion" in html:
        fail("Popup header must display Studio version 0.9.1", failures)
    if "made with" not in html or "❤️" not in html:
        fail("Popup footer must display made with ❤️", failures)
    for static_selector in (".community-link", ".app-footer"):
        if static_selector not in css:
            fail(f"Missing popup CSS selector: {static_selector}", failures)

    studio_tab_attrs = parser.attrs_by_id.get("tab-generator", {})
    studio_view_attrs = parser.attrs_by_id.get("view-generator", {})
    prompts_tab_attrs = parser.attrs_by_id.get("tab-prompts", {})
    if "hidden" not in studio_tab_attrs or studio_tab_attrs.get("aria-hidden") != "true":
        fail("The disabled Studio tab must remain hidden and aria-hidden", failures)
    if "hidden" not in studio_view_attrs or studio_view_attrs.get("aria-hidden") != "true":
        fail("The disabled Studio panel must remain hidden and aria-hidden", failures)
    if "active" not in (prompts_tab_attrs.get("class") or "").split():
        fail("Prompts must be the default active popup tab", failures)

    for local_ref in parser.local_refs:
        if "://" not in local_ref and not (ROOT / local_ref).exists():
            fail(f"Missing referenced asset: {local_ref}", failures)

    for class_name in sorted(REQUIRED_DYNAMIC_CLASSES):
        if f".{class_name}" not in css:
            fail(f"Missing dynamic CSS selector: .{class_name}", failures)

    mojibake_markers = ("ðŸ", "âš", "âœ", "âž", "ï¸")
    if any(marker in html for marker in mojibake_markers):
        fail("Visible HTML still contains mojibake markers", failures)

    if html.find('<script src="popup.js"></script>') < html.find('id="main-unlocked-ui"'):
        fail("popup.js must load after the functional DOM", failures)

    try:
        manifest = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        fail(f"manifest.json is invalid: {error}", failures)
        manifest = {}

    if manifest.get("action", {}).get("default_popup") != "popup.html":
        fail("Manifest default_popup must remain popup.html", failures)

    if manifest.get("name") != "StudioRelay":
        fail("Manifest name must be StudioRelay", failures)

    if manifest.get("version") != "10.1.3":
        fail("Manifest version must be 10.1.3", failures)

    if manifest.get("action", {}).get("default_title") != "StudioRelay":
        fail("Manifest default_title must be StudioRelay", failures)

    content_scripts = manifest.get("content_scripts", [])
    if not any("dock-polish.css" in entry.get("css", []) for entry in content_scripts):
        fail("dock-polish.css must be registered as a content-script stylesheet", failures)

    if not any("site-polish.js" in entry.get("js", []) for entry in content_scripts):
        fail("site-polish.js must be registered as a content script", failures)

    manifest_refs: set[str] = set()
    background_worker = manifest.get("background", {}).get("service_worker")
    if background_worker:
        manifest_refs.add(background_worker)
    manifest_refs.update(manifest.get("icons", {}).values())
    manifest_refs.update(manifest.get("action", {}).get("default_icon", {}).values())
    default_popup = manifest.get("action", {}).get("default_popup")
    if default_popup:
        manifest_refs.add(default_popup)
    for entry in content_scripts:
        manifest_refs.update(entry.get("js", []))
        manifest_refs.update(entry.get("css", []))
    for entry in manifest.get("web_accessible_resources", []):
        manifest_refs.update(
            resource for resource in entry.get("resources", [])
            if "*" not in resource
        )
    for manifest_ref in sorted(manifest_refs):
        if not (ROOT / manifest_ref).exists():
            fail(f"Missing manifest runtime file: {manifest_ref}", failures)

    forbidden_legacy_artifacts = {
        "icon.jpg",
        "popup-legacy.css",
        "popup-legacy.html",
    }
    for legacy_name in sorted(forbidden_legacy_artifacts):
        if (ROOT / legacy_name).exists():
            fail(f"Unused legacy theme artifact still exists: {legacy_name}", failures)

    required_dock_selectors = {
        '[id^="channa-dock-"]',
        '[id^="channa-seq-"]',
        "#channa-inpage-toast",
        "#channa-tab-session-badge",
    }
    for selector in sorted(required_dock_selectors):
        if selector not in dock_css:
            fail(f"Missing injected-dock selector: {selector}", failures)

    required_site_copy = {
        "Dola 30s by Kartar",
        "30s (Kartar Mode)",
        "Fetch & Download done",
        "channa-tab-session-badge",
        "studio-relay-download-status",
        "studio-relay-mode-pill",
    }
    for token in sorted(required_site_copy):
        if token not in site_polish and token not in dock_css:
            fail(f"Missing site-polish contract: {token}", failures)

    for path, source in ((CSS_PATH, css), (DOCK_CSS_PATH, dock_css)):
        if source.count("{") != source.count("}"):
            fail(f"Unbalanced CSS braces in {path.name}", failures)

    if failures:
        for item in failures:
            print(f"FAIL: {item}")
        return 1

    print(f"PASS: {HTML_PATH.name} preserves the popup DOM contract.")
    print(f"PASS: {len(REQUIRED_IDS)} required IDs are present and unique.")
    print("PASS: Studio disable, Kartar/download labels, popup/dock CSS, asset, and manifest checks succeeded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
