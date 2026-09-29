# StudioRelay

StudioRelay is a compact Chrome extension workspace for Dola-based video workflows. It keeps reusable prompts, account profiles, automation settings, and activity in one focused popup.

## Interface

The v10.1.3 redesign uses a Graphite + Indigo visual system:

- Neutral dark surfaces with one primary accent.
- Compact SVG navigation without decorative emoji.
- Consistent primary, secondary, quiet, and destructive actions.
- Accessible focus states, keyboard tab navigation, and reduced-motion support.
- A reusable confirmation overlay for destructive actions.
- A responsive 420px popup layout with styled empty and populated states.
- Matching Graphite + Indigo styling for the injected Dola Prompt Dock, toast, and session badge.

The visual direction adapts patterns from 21st.dev while remaining dependency-free. The extension continues to use plain HTML, CSS, and JavaScript so it stays compatible with Manifest V3 popup restrictions.

## Main workflows

### Dola page status

- The side panel Studio tab is intentionally disabled; Prompts opens by default.
- Switching or running an account shows **Dola 30s by Kartar** on the page.
- The active generation enhancement displays **30s (Kartar Mode)** in violet beside Create Video.
- Each account opens 2 simultaneous tabs (to utilize 4 points for 2 videos).
- Generated video cards display **Fetch & Download done** with the Graphite + Indigo download treatment.
- The side panel header displays **Studio version 1.6** and links to the StudioRelay WhatsApp channel.

### Prompts

- Paste multiple prompts or import CSV/TXT files.
- Search and filter queued or completed prompts.
- Paste a prompt into the active page.
- Track and reset prompt progress.

### Accounts

- Import JSON, Netscape, CSV, or raw cookie data.
- Capture the signed-in account from the active tab.
- Search, switch, open, and remove saved account profiles (spawning 2 tabs per account).

Only import or manage accounts and session data that you are authorized to use.

### Settings and activity

- Configure default duration and automation behavior.
- Review license state.
- View recent extension status in the Activity tab.

## Project files

| File | Purpose |
| --- | --- |
| `manifest.json` | Manifest V3 metadata, permissions, side panel, and entry points |
| `popup.html` | StudioRelay Side Panel UI structure |
| `popup.css` | Graphite + Indigo + Poppins component system |
| `dock-polish.css` | Non-invasive StudioRelay theme overrides for injected page controls |
| `site-polish.js` | Runtime-safe page label normalization for Kartar status indicators |
| `ui-polish.js` | Accessible tabs, runtime copy cleanup, and confirmation overlay |
| `popup.js` | Existing popup behavior and storage integration |
| `background.js` | Background session and tab workflows |
| `content.js` | Isolated page bridge |
| `inject.js` | In-page workflow integration |
| `brand-icon.svg` | Source logo artwork |
| `icon16.png`, `icon48.png`, `icon128.png` | Chrome extension icon variants |

## Install locally

1. Open `chrome://extensions/`.
2. Enable **Developer mode**.
3. Choose **Load unpacked**.
4. Select this project directory.
5. After source changes, use the reload button on the extension card.

## Validation

Run the zero-dependency popup contract check:

```powershell
python scratch\validate_redesign.py
```

It verifies required DOM IDs, duration/ratio/filter contracts, referenced assets, popup and dock CSS contracts, and manifest wiring.

## Compatibility note

Some internal storage keys, message names, license prefixes, and injected selectors still use earlier `ctb`, `CHANNA`, or `channa-` namespaces. They are intentionally preserved so existing licenses, saved data, and cross-script communication continue to work. They are not part of the visible StudioRelay brand.
