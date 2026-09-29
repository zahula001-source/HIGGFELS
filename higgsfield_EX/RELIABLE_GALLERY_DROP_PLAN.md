# StudioRelay Reliable Gallery-to-Dola Drop Plan

## Confirmed Failure Chain

1. The side panel currently requires `DataTransfer.items.add(File)` to succeed.
2. If Chrome rejects or strips that constructed file across the extension-side-panel/page boundary, `dragstart` calls `preventDefault()` and cancels the drag.
3. The Dola receiver accepts only `dataTransfer.files`, so it cannot recover the image when the file payload is absent.
4. The screenshot is in Dola's general `Message...` composer, where a file input may not exist until another mode is active.
5. The current synthetic fallback dispatches a drop on the outer composer surface only; it does not try the actual textbox or a file-only paste event.

## Repair Contract

1. Never cancel a gallery drag merely because Chrome rejects the constructed `File` item.
2. Put a small record token in standard drag formats plus the custom format; keep the real File as a best-effort fast path.
3. On Dola, recognize StudioRelay drag types during `dragover`, allow copy-drop anywhere on the page, and consume the token on trusted `drop`.
4. Resolve the token in the extension background and return the original IndexedDB image as a data URL; image bytes are never placed in text drag data.
5. Reconstruct the original `File` in the Dola content script.
6. Attempt attachment without clicking page controls:
   - composer-linked file input;
   - file-only paste on the active textbox;
   - file drop on the active textbox so the event bubbles to its composer.
7. Verify an actual Dola attachment preview/control/filename after every attempt.
8. Mark the matching gallery record Done only after verified Dola UI evidence; persist a queued error on failure.
9. Preserve the existing gallery layout, filters, deletion, click upload, and bulk serial upload.

## Validation

- Constructed File rejection no longer cancels dragstart.
- Token formats contain only the queue record ID, never image bytes or a filename that Dola could paste as prompt text.
- Trusted StudioRelay drops are accepted anywhere on the Dola document and routed to the active composer.
- No Dola page `.click()` call exists in the drop/upload content script.
- Every Done transition remains downstream of verified attachment evidence.

## Implemented Repair

- Dragstart is token-first and never depends on a constructed cross-boundary File.
- The Dola content script accepts trusted token/image drops anywhere on the document.
- The background resolves the gallery ID to the original IndexedDB Blob.
- The active composer is tried through linked input, file-only paste, and textbox drop with verification after each attempt.
- Verified success marks Done; failure persists a queued error.
- A surviving native browser `File` now has priority over the token fallback, preserving the trusted Dola drop event.
- The side panel reports verified attachment success or the persisted queued error after every gallery drag.
- Static integration validation passed: manifest JSON, handler wiring, balanced delimiters, and the zero-page-click rule.

## Duplicate-Upload Regression Fix

- Confirmed cause: a trusted native File drop attached once, then the extension fallback attached the same File again when preview detection was late.
- Trusted native File drops are now observation-only and are never re-sent through input, paste, or synthetic drop.
- Token-only drops retain the single extension attachment pipeline.
- Native verification now waits 6 seconds and reacquires the active composer after a Dola rerender.
