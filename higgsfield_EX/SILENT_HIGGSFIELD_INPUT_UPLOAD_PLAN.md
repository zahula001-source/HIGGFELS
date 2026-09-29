# StudioRelay Silent Dola Input Upload Plan

## Confirmed Failure

1. File Explorer/Downloads supplies Dola with a browser/OS File and uploads successfully.
2. A File constructed in the extension side panel crosses into Dola as filename text, visible in the composer screenshot.
3. Token-to-synthetic-drop avoids the filename text, but Dola rejects the scripted drop.
4. Therefore neither cross-panel constructed File transport nor synthetic DragEvent transport is reliable.

## Selected Design

The gallery drag is only a user trigger. Image bytes remain in extension IndexedDB.

1. Dragstart carries one opaque versioned record token and no File/text/URL representation.
2. The Dola capture listener consumes that token before the page can paste anything.
3. The background resolves the token to the stored Blob once.
4. MAIN-world code reconstructs one File.
5. It first uses an already-mounted Dola image input when available.
6. Otherwise it silently activates the real Dola plus/upload workflow:
   - identify the plus/add attachment control inside the active composer;
   - suppress temporary menu visibility and native file-picker default action;
   - click the plus control once;
   - discover a newly mounted/captured file input;
   - only if required, click one high-confidence upload/image/file menu item;
   - assign exactly one File and dispatch exactly one change event.
7. No synthetic paste, synthetic file drop, OS picker, retry family, or Create Images button click is allowed.
8. Done requires a new Dola attachment preview/control/filename.

## Safety Contract

- Page activation is bounded by one operation ID and a short timeout.
- Only small composer-linked plus/upload controls may be activated.
- Generate/Create Images, send, profile, avatar, video, and audio controls are rejected.
- File chooser suppression exists only during the short internal activation window and is always restored.
- Temporary menu-hiding CSS is removed in finally cleanup.
- One operation assigns one File to one input and emits one change.
- Failure leaves the record queued with a specific error.

## Acceptance Checks

- Gallery drag has zero File items and exactly one custom token.
- The original token drop is prevented before Dola can paste the filename.
- Gallery token handling reaches the silent input routine once.
- Silent input routine contains no DragEvent, ClipboardEvent, paste, or drop dispatch.
- At most one plus control and one upload option are activated.
- Exactly one input assignment and one change event occur.
- The OS file picker never opens from scripted activation.
- No Create Images or send button is clicked.
- Done remains downstream of visible attachment evidence.

## Implemented Result

- Gallery drag now exposes one private versioned token and zero File, filename, URL, or image-byte drag items.
- The Dola capture listener consumes the token once, deduplicates its operation ID for 60 seconds, and resolves the stored image through the extension background.
- MAIN-world upload now uses an existing high-confidence Dola image input or silently activates the composer plus/upload route to mount and capture the real input.
- The file picker default action and temporary upload UI are suppressed only during the bounded activation window and restored in finally cleanup.
- Exactly one FileList assignment and one change dispatch occur on the selected Dola input. No synthetic DragEvent, paste, drop retry, Create Images click, or send click remains.
- Manual completion still depends on downstream Dola attachment evidence; failures remain queued.
- Old native-drag registry remnants were removed, and build/version was advanced to 1.9.

## Verification Result

- Manifest JSON parses successfully and the required scripts remain wired into the background/content-script entries.
- All modified JavaScript files have balanced braces, parentheses, and brackets.
- Static assertions confirm one gallery token writer, one token consumer path, one change-event site, bounded alternative input-assignment branches, two allowed UI activation sites, and zero forbidden synthetic drop/paste implementations.
- Live Chrome validation was attempted through the Chrome-control workflow but the host Windows ACL prevented the browser-control kernel from starting. A real runtime drag must therefore be checked after reloading build 1.9 and refreshing Dola.
